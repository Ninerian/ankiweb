import json
from html.parser import HTMLParser
from pathlib import Path

import pytest
from anki.cards import CardId
from anki.collection import Collection
from anki.decks import DeckId
from fastapi.testclient import TestClient

from ankiweb.app import create_app
from ankiweb.core.app_client.deck_progress import progress_pct
from ankiweb.core.app_client.decks import DEFAULT_EMOJI, deck_rows, split_emoji
from ankiweb.core.app_client.revlog import day_start_ms
from ankiweb.core.auth import COOKIE, auth_token
from ankiweb.core.config import Settings


def _add_cards(col: Collection, deck_name: str, count: int = 1) -> list[int]:
    deck_id = col.decks.id(deck_name)
    model = col.models.by_name("Basic")
    assert deck_id is not None
    assert model is not None
    card_ids = []
    for index in range(count):
        note = col.new_note(model)
        note["Front"] = f"{deck_name} {index}"
        note["Back"] = "answer"
        col.add_note(note, deck_id)
        card_ids.append(note.cards()[0].id)
    return card_ids


def _insert_review(col: Collection, card_id: int, offset_ms: int = 1) -> None:
    assert col.db is not None
    col.db.execute(
        "insert into revlog values (?, ?, -1, 3, 1, 0, 2500, 1000, 1)",
        day_start_ms(col) + offset_ms,
        card_id,
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("🇩🇪 German B1 Vocab", ("🇩🇪", "German B1 Vocab")),
        ("🧬Biology", ("🧬", "Biology")),
        ("⚗️ Chemistry", ("⚗️", "Chemistry")),
        ("👩‍💻 Coding", ("👩‍💻", "Coding")),
        ("👍🏽 Skin tone", ("👍🏽", "Skin tone")),
        ("Biology", (DEFAULT_EMOJI, "Biology")),
        ("🇩 Lone indicator", (DEFAULT_EMOJI, "🇩 Lone indicator")),
        ("1900s", (DEFAULT_EMOJI, "1900s")),
        ("🧬", (DEFAULT_EMOJI, "🧬")),
    ],
)
def test_split_emoji(name: str, expected: tuple[str, str]) -> None:
    assert split_emoji(name) == expected


@pytest.mark.parametrize(
    ("studied", "due", "new", "expected"),
    [(0, 0, 0, 0), (5, 0, 0, 100), (0, 3, 2, 0), (1, 2, 1, 25), (7, 0, 1, 87)],
)
def test_progress_pct(studied: int, due: int, new: int, expected: int) -> None:
    assert progress_pct(studied, due, new) == expected


def test_counts_match_due_tree_and_include_children(
    temp_collection: Collection,
) -> None:
    col = temp_collection
    _add_cards(col, "Parent", 2)
    _add_cards(col, "Parent::A", 3)
    _add_cards(col, "Parent::B", 4)
    _add_cards(col, "Solo", 1)

    rows = {row.name: row for row in deck_rows(col)}

    assert rows["Parent"].new == 9
    assert rows["Solo"].new == 1
    tree = {node.name: node for node in col.sched.deck_due_tree().children}
    for name, row in rows.items():
        node = tree[name]
        assert row.deck_id == node.deck_id
        assert row.new == node.new_count
        assert row.due == node.review_count + node.learn_count
    assert "A" not in rows
    assert "Parent::A" not in rows


def test_order_follows_anki_tree(temp_collection: Collection) -> None:
    col = temp_collection
    for name in ("Zeta", "Alpha", "Mid"):
        _add_cards(col, name)

    assert [row.name for row in deck_rows(col)] == ["Alpha", "Mid", "Zeta"]


def test_basic_only_deck_is_listed(col_with_vocab: Collection) -> None:
    rows = deck_rows(col_with_vocab)

    assert [(row.name, row.new) for row in rows] == [("German B1 Vocab", 4)]


def test_filtered_deck_and_empty_default_are_hidden(
    temp_collection: Collection,
) -> None:
    col = temp_collection
    assert deck_rows(col) == []
    _add_cards(col, "Real")
    filtered = col.sched.get_or_create_filtered_deck(deck_id=DeckId(0))
    filtered.name = "Filtered"
    filtered.config.search_terms[0].search = "deck:Real"
    col.sched.add_or_update_filtered_deck(filtered)
    tree = col.sched.deck_due_tree().children
    assert [node.name for node in tree if node.filtered] == ["Filtered"]

    names = [row.name for row in deck_rows(col)]

    assert names == ["Real"]


def test_default_deck_with_cards_is_listed(temp_collection: Collection) -> None:
    _add_cards(temp_collection, "Default")

    assert [row.name for row in deck_rows(temp_collection)] == ["Default"]


def test_progress_counts_reviews_in_subdecks(temp_collection: Collection) -> None:
    col = temp_collection
    root_card = _add_cards(col, "Root")[0]
    child_cards = _add_cards(col, "Root::Child", 2)
    _add_cards(col, "Idle")
    for offset, card_id in enumerate((root_card, *child_cards, child_cards[0]), 1):
        _insert_review(col, card_id, offset)

    rows = {row.name: row for row in deck_rows(col)}

    assert rows["Idle"].progress_pct == 0
    assert (rows["Root"].due, rows["Root"].new) == (0, 3)
    assert rows["Root"].progress_pct == 57  # 4 reviews / (4 + 3 new)


def test_progress_is_100_when_nothing_is_open(temp_collection: Collection) -> None:
    col = temp_collection
    card_id = _add_cards(col, "Done")[0]
    _insert_review(col, card_id)
    col.sched.bury_cards([CardId(card_id)])

    (row,) = deck_rows(col)

    assert (row.due, row.new) == (0, 0)
    assert row.progress_pct == 100


class _Page(HTMLParser):
    """Collect element attributes of the deck page."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))

    def hrefs(self) -> list[str]:
        return [a["href"] or "" for t, a in self.tags if t == "a" and "href" in a]

    def by_id(self, element_id: str) -> dict[str, str | None]:
        return next(a for _, a in self.tags if a.get("id") == element_id)


def _parse(html: str) -> _Page:
    page = _Page()
    page.feed(html)
    return page


def _client(
    tmp_path: Path, names: list[str], password: str = ""
) -> tuple[TestClient, dict[str, int]]:
    """Return a client over a collection holding one card per named deck."""
    path = tmp_path / "http.anki2"
    col = Collection(str(path))
    try:
        for name in names:
            _add_cards(col, name)
        ids = {node.name: node.deck_id for node in col.sched.deck_due_tree().children}
    finally:
        col.close()
    app = create_app(Settings(collection_path=path, password=password))
    return TestClient(app), ids


def test_page_has_one_learn_and_add_link_per_deck(tmp_path: Path) -> None:
    client, ids = _client(tmp_path, ["Alpha", "Beta::Child"])
    with client:
        html = client.get("/app/").text
    hrefs = _parse(html).hrefs()
    assert sorted(h for h in hrefs if h.startswith("/app/")) == sorted(
        f"/app/{kind}?deck={ids[name]}"
        for name in ("Alpha", "Beta")
        for kind in ("review", "add")
    )
    assert "Child" not in html


def test_rows_have_ids_and_names_are_escaped(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, ["<b>x</b>", "Plain"])
    with client:
        html = client.get("/app/").text
    page = _parse(html)
    row_ids = [a["id"] for t, a in page.tags if t == "article"]
    assert len(row_ids) == 2
    assert all(row_id and row_id.startswith("deck-") for row_id in row_ids)
    assert "<b>" not in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html


def test_search_expression_survives_hostile_names(tmp_path: Path) -> None:
    name = 'It\'s "Q" \\ $x <i>'
    client, _ = _client(tmp_path, [name])
    with client:
        html = client.get("/app/").text
    page = _parse(html)
    row_show = next(a["data-show"] for t, a in page.tags if t == "article")
    empty_show = page.by_id("empty-state")["data-show"]
    assert row_show is not None
    assert empty_show is not None
    literal, _, rest = row_show.partition(".includes(")
    assert json.loads(literal) == name.lower()
    assert "$x" not in row_show
    assert "$q" in rest
    assert json.loads(empty_show.split("!", 2)[2].split(".some(")[0]) == [name.lower()]


def test_empty_state_is_rendered_hidden(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, ["Alpha"])
    with client:
        page = _parse(client.get("/app/").text)
    empty = page.by_id("empty-state")
    assert empty["style"] == "display:none"
    assert page.by_id("deck-search")["type"] == "search"


def test_empty_collection_offers_first_deck(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, [])
    with client:
        html = client.get("/app/").text
    page = _parse(html)
    assert "/app/add" in page.hrefs()
    assert not any(t == "article" for t, _ in page.tags)
    assert "deck-search" not in html


def test_app_root_redirects_to_deck_list(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, ["Alpha"])
    with client:
        response = client.get("/app", follow_redirects=False)
        assert response.status_code in {301, 302, 307, 308}
        assert response.headers["location"] == "/app/"
        assert client.get("/app").text == client.get("/app/").text


def test_deck_list_follows_password_gate(tmp_path: Path) -> None:
    password = f"test-{tmp_path.name}"
    client, _ = _client(tmp_path, ["Alpha"], password)
    with client:
        response = client.get("/app/", follow_redirects=False)
        assert response.status_code == 303
        assert "set-cookie" not in response.headers
        client.cookies.set(COOKIE, auth_token(password))
        assert client.get("/app/").status_code == 200


def test_page_does_not_reference_old_client(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, ["Alpha"])
    with client:
        html = client.get("/app/").text
    for forbidden in (
        "/_anki/",
        "reviewer.js",
        "editor.js",
        "bootstrap.js",
        "/shell/static/app.css",
        "theme.css",
        "components.css",
        "data-theme",
    ):
        assert forbidden not in html
    assert "/shell/static/app-client.css" in html


def test_deck_list_is_never_cached(tmp_path: Path) -> None:
    # Back-navigation from review must show fresh counts, so no history cache.
    client, _ = _client(tmp_path, ["Alpha"])
    with client:
        assert client.get("/app/").headers["cache-control"] == "no-store"
