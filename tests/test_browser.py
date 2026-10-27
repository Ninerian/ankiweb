from html.parser import HTMLParser
from pathlib import Path
from typing import Any, cast

import pytest
from anki.collection import Collection, SearchNode
from anki.decks import DeckId
from anki.models import NotetypeId
from fastapi.testclient import TestClient

from ankiweb.app import create_app
from ankiweb.core.config import Settings


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(collection_path=tmp_path / "c.anki2"))) as c:
        assert c.portal is not None
        app = cast(Any, c.app)
        c.portal.call(app.state.service.run, _seed)
        yield c


def _seed(col):
    for q in ("dog", "cat"):
        n = col.new_note(col.models.by_name("Basic"))
        n["Front"] = q
        n["Back"] = q.upper()
        col.add_note(n, col.decks.id("Default"))
    col.tags.bulk_add(col.find_notes(""), "animals")
    col.decks.id("Spanish")


def test_browse_route_renders(client):
    r = client.get("/browse")
    assert r.status_code == 200
    assert 'window.__ankiwebContext = "browser"' in r.text
    assert "id='results'" in r.text or 'id="results"' in r.text
    assert "id='search'" in r.text or 'id="search"' in r.text
    assert "Default" in r.text
    assert "animals" in r.text


def test_browse_search_pushes_rows_and_mirrors_ui_state(client):
    from conftest import parse_datastar_events

    hub = client.app.state.hub
    r = client.post(
        "/browse/search", json={"query": "dog"}, headers={"Datastar-Request": "true"}
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("dog" in data and ">cat<" not in data for _, data in events)
    from ankiweb.adapters.inbound.http_datastar.browser import _card_count_str

    # the status line is updated to the localized "<n> cards" label for the match count
    assert any(
        "browser-status" in data and _card_count_str(1) in data for _, data in events
    )
    assert hub.ui_state.browser_open is True
    assert hub.ui_state.last_browse_query == "dog"
    assert len(hub.ui_state.matched_card_ids) == 1


def _extract_sidebar_links(html_text: str) -> dict[str, str]:
    from html.parser import HTMLParser

    class SidebarParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links: dict[str, str] = {}
            self._current_href: str | None = None
            self._current_title: str | None = None
            self._current_text: list[str] = []

        def handle_starttag(self, tag, attrs):
            if tag == "a":
                attr_dict = dict(attrs)
                classes = (attr_dict.get("class") or "").split()
                if "side-item" in classes and "href" in attr_dict:
                    self._current_href = attr_dict["href"]
                    self._current_title = attr_dict.get("title") or None
                    self._current_text = []

        def handle_data(self, data):
            if self._current_href is not None:
                self._current_text.append(data)

        def handle_endtag(self, tag):
            if tag == "a" and self._current_href is not None:
                label = "".join(self._current_text).strip()
                key = self._current_title or label
                self.links[key] = self._current_href
                self._current_href = None
                self._current_title = None
                self._current_text = []

    parser = SidebarParser()
    parser.feed(html_text)
    return parser.links


def _extract_cids_from_html(html_text: str) -> list[int]:
    import re

    return [int(cid) for cid in re.findall(r'<tr[^>]*\bdata-cid="(\d+)"', html_text)]


def _extract_cids_from_search_post(client, query: str) -> list[int]:
    from conftest import parse_datastar_events

    r = client.post(
        "/browse/search",
        json={"query": query},
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    for event_type, data in events:
        if event_type == "datastar-patch-elements" and "results-body" in data:
            return _extract_cids_from_html(data)
    return []


def test_browse_sidebar_links_and_exact_search_results(client):
    from urllib.parse import parse_qs, urlparse

    browse_get = client.get("/browse")
    assert browse_get.status_code == 200
    links = _extract_sidebar_links(browse_get.text)
    assert "Default" in links
    assert "animals" in links

    default_href = links["Default"]
    parsed_deck = urlparse(default_href)
    assert parsed_deck.path == "/browse"
    deck_query = parse_qs(parsed_deck.query).get("q", [""])[0]
    assert deck_query

    deck_get = client.get(default_href)
    assert deck_get.status_code == 200
    deck_get_cids = _extract_cids_from_html(deck_get.text)
    deck_post_cids = _extract_cids_from_search_post(client, deck_query)
    assert len(deck_get_cids) == 2
    assert deck_get_cids == deck_post_cids

    animals_href = links["animals"]
    parsed_tag = urlparse(animals_href)
    assert parsed_tag.path == "/browse"
    tag_query = parse_qs(parsed_tag.query).get("q", [""])[0]
    assert tag_query

    tag_get = client.get(animals_href)
    assert tag_get.status_code == 200
    tag_get_cids = _extract_cids_from_html(tag_get.text)
    tag_post_cids = _extract_cids_from_search_post(client, tag_query)
    assert len(tag_get_cids) == 2
    assert tag_get_cids == tag_post_cids


def test_browse_sidebar_special_characters_and_wildcard_escaping(client):
    from urllib.parse import parse_qs, urlparse

    special_deck = 'Quoted "deck" + & # Ω'
    special_tag = 'quote"+&#Ω*'
    decoy_tag = 'quote"+&#Ω-decoy'
    child_deck = 'Quoted "deck" + & # Ω::Subdeck'

    def seed_special(col):
        col.decks.id(special_deck)
        col.decks.id(child_deck)

        # Note in special deck
        nt = col.models.by_name("Basic")
        n1 = col.new_note(nt)
        n1["Front"] = "special deck card"
        n1["Back"] = "ans 1"
        col.add_note(n1, col.decks.id(special_deck))

        # Note in child deck
        n2 = col.new_note(nt)
        n2["Front"] = "child deck card"
        n2["Back"] = "ans 2"
        col.add_note(n2, col.decks.id(child_deck))

        # Note with literal wildcard tag
        n3 = col.new_note(nt)
        n3["Front"] = "literal wildcard tag card"
        n3["Back"] = "ans 3"
        col.add_note(n3, col.decks.id("Default"))
        col.tags.bulk_add([n3.id], special_tag)

        # Decoy note that would match if '*' were interpreted as a wildcard
        n4 = col.new_note(nt)
        n4["Front"] = "decoy tag card"
        n4["Back"] = "ans 4"
        col.add_note(n4, col.decks.id("Default"))
        col.tags.bulk_add([n4.id], decoy_tag)

        return n1.id, n2.id, n3.id, n4.id

    n1_id, n2_id, n3_id, n4_id = _run(client, seed_special)
    c1_id = _run(client, lambda col: col.get_note(n1_id).cards()[0].id)
    c2_id = _run(client, lambda col: col.get_note(n2_id).cards()[0].id)
    c3_id = _run(client, lambda col: col.get_note(n3_id).cards()[0].id)
    c4_id = _run(client, lambda col: col.get_note(n4_id).cards()[0].id)

    browse_get = client.get("/browse")
    assert browse_get.status_code == 200
    links = _extract_sidebar_links(browse_get.text)

    assert special_deck in links
    assert child_deck in links
    assert special_tag in links
    assert decoy_tag in links

    # 1. Deck link navigation vs canonical POST
    deck_href = links[special_deck]
    parsed_deck = urlparse(deck_href)
    deck_query = parse_qs(parsed_deck.query).get("q", [""])[0]
    assert deck_query

    deck_get = client.get(deck_href)
    assert deck_get.status_code == 200
    deck_get_cids = _extract_cids_from_html(deck_get.text)
    deck_post_cids = _extract_cids_from_search_post(client, deck_query)
    assert deck_get_cids == deck_post_cids
    # Parent deck includes child deck cards per Anki deck search semantics
    assert c1_id in deck_get_cids
    assert c2_id in deck_get_cids
    assert c3_id not in deck_get_cids
    assert c4_id not in deck_get_cids

    # Child deck specifically
    child_href = links[child_deck]
    child_query = parse_qs(urlparse(child_href).query).get("q", [""])[0]
    child_get = client.get(child_href)
    assert child_get.status_code == 200
    child_get_cids = _extract_cids_from_html(child_get.text)
    child_post_cids = _extract_cids_from_search_post(client, child_query)
    assert child_get_cids == child_post_cids
    assert child_get_cids == [c2_id]

    # 2. Tag with literal wildcard '*' vs decoy
    tag_href = links[special_tag]
    tag_query = parse_qs(urlparse(tag_href).query).get("q", [""])[0]
    tag_get = client.get(tag_href)
    assert tag_get.status_code == 200
    tag_get_cids = _extract_cids_from_html(tag_get.text)
    tag_post_cids = _extract_cids_from_search_post(client, tag_query)
    assert tag_get_cids == tag_post_cids
    # Must only match the exact note with special_tag, NOT the decoy note
    assert tag_get_cids == [c3_id]
    assert c4_id not in tag_get_cids


_SPECIAL_DECK = 'Quoted "deck"* Ω'
_DECK_NAMES = (
    "Root",
    "Root::Unit1",
    "Root::Unit1::Lesson",
    "Root::Unit1::Lesson::Deep",
    "Root::Unit10",
    "Root::Unit10::Lesson",
    "Other",
    "Other::Chapter",
    "Other::Chapter::Leaf",
    _SPECIAL_DECK,
    f"{_SPECIAL_DECK}::Child",
)


def _seed_deck_paths(col: Collection) -> dict[str, str]:
    for name in _DECK_NAMES:
        col.decks.id(name)
    return {
        name: col.build_search_string(SearchNode(deck=name)) for name in _DECK_NAMES
    }


@pytest.fixture
def deck_queries(client: TestClient) -> dict[str, str]:
    return cast(dict[str, str], _run(client, _seed_deck_paths))


class _DeckStateParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.details: list[bool] = []
        self.in_section = False
        self.in_summary = False
        self.expanded: set[str] = set()
        self.active: set[str] = set()
        self.current: set[str] = set()
        self.names: set[str] = set()
        self.visible: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "details" and attributes.get("id") == "sidebar-decks-section":
            self.in_section = True
        if not self.in_section:
            return
        if tag == "details":
            self.details.append("open" in attributes)
        elif tag == "summary":
            self.in_summary = True
        elif tag == "a":
            self._record_anchor(attributes)

    def _record_anchor(self, attributes: dict[str, str | None]) -> None:
        name = attributes.get("title")
        if not name:
            return
        self.names.add(name)
        ancestors = self.details[:-1] if self.in_summary else self.details
        if all(ancestors):
            self.visible.add(name)
        if self.in_summary and len(self.details) > 1 and self.details[-1]:
            self.expanded.add(name)
        if "menu-active" in (attributes.get("class") or "").split():
            self.active.add(name)
        if attributes.get("aria-current") == "true":
            self.current.add(name)

    def handle_endtag(self, tag: str) -> None:
        if not self.in_section:
            return
        if tag == "summary":
            self.in_summary = False
        elif tag == "details":
            self.details.pop()
            if not self.details:
                self.in_section = False


def _deck_state(html: str) -> _DeckStateParser:
    parser = _DeckStateParser()
    parser.feed(html)
    assert set(_DECK_NAMES) <= parser.names
    return parser


def _assert_deck_search_state(
    client: TestClient, query: str, selected: set[str], expanded: set[str]
) -> None:
    from conftest import parse_datastar_events

    response = client.get("/browse", params={"q": query})
    assert response.status_code == 200
    get_state = _deck_state(response.text)

    response = client.post(
        "/browse/search",
        json={"query": query},
        headers={"Datastar-Request": "true"},
    )
    assert response.status_code == 200
    patches = [
        data
        for event, data in parse_datastar_events(response.text)
        if event == "datastar-patch-elements" and "sidebar-decks-section" in data
    ]
    assert len(patches) == 1
    assert 'id="sidebar-panel"' not in patches[0]
    assert 'id="sidebar-tags-section"' not in patches[0]
    assert 'id="sidebar-card-types-section"' not in patches[0]
    post_state = _deck_state(patches[0])
    visible = {
        name
        for name in _DECK_NAMES
        if all(
            "::".join(name.split("::")[:depth]) in expanded
            for depth in range(1, len(name.split("::")))
        )
    }

    for state in (get_state, post_state):
        assert state.active == selected
        assert state.current == selected
        assert state.expanded == expanded
        assert state.visible & set(_DECK_NAMES) == visible


@pytest.mark.parametrize(
    ("name", "expanded"),
    [
        ("Root", {"Root"}),
        ("Root::Unit1", {"Root", "Root::Unit1"}),
        ("Root::Unit10", {"Root", "Root::Unit10"}),
        (
            "Root::Unit1::Lesson",
            {"Root", "Root::Unit1", "Root::Unit1::Lesson"},
        ),
        (
            "Root::Unit1::Lesson::Deep",
            {"Root", "Root::Unit1", "Root::Unit1::Lesson"},
        ),
        (_SPECIAL_DECK, {_SPECIAL_DECK}),
        (f"{_SPECIAL_DECK}::Child", {_SPECIAL_DECK}),
    ],
)
def test_browse_deck_search_opens_only_selected_path(
    client: TestClient, deck_queries: dict[str, str], name: str, expanded: set[str]
) -> None:
    _assert_deck_search_state(client, deck_queries[name], {name}, expanded)


@pytest.mark.parametrize("query", ['deck:"Root::Unit1"', 'deck:"rOoT::uNiT1"'])
def test_browse_deck_search_accepts_alternate_quoting(
    client: TestClient, deck_queries: dict[str, str], query: str
) -> None:
    _assert_deck_search_state(
        client,
        query,
        {"Root::Unit1"},
        {"Root", "Root::Unit1"},
    )


def _basic_card_type_query(col: Collection) -> str:
    model = col.models.by_name("Basic")
    assert model is not None
    return f"mid:{model['id']} card:1"


@pytest.mark.parametrize(
    "query",
    [
        "",
        "dog",
        "deck:(((",
        "-deck:Root::Unit1",
        "deck:Root::Unit1 OR deck:Root::Unit10",
        "deck:Root::Unit*",
        "deck:Root::Unit1 dog",
        'deck:"Root::Unit1" card:1',
        None,
    ],
)
def test_browse_other_searches_clear_deck_selection(
    client: TestClient, deck_queries: dict[str, str], query: str | None
) -> None:
    if query is None:
        query = cast(str, _run(client, _basic_card_type_query))
    _assert_deck_search_state(
        client,
        deck_queries["Root::Unit1::Lesson"],
        {"Root::Unit1::Lesson"},
        {"Root", "Root::Unit1", "Root::Unit1::Lesson"},
    )
    _assert_deck_search_state(client, query, set(), {"Root", "Other", _SPECIAL_DECK})


def test_browse_selection_and_refresh_do_not_patch_decks(client: TestClient) -> None:
    from conftest import parse_datastar_events

    cid = _run(client, lambda col: next(iter(col.find_cards("dog"))))
    responses = (
        client.post(f"/browse/open/{cid}"),
        client.post(
            "/browse/refresh",
            json={"selectedCids": [cid], "selectionAnchor": cid, "browserQuery": "dog"},
            headers={"Datastar-Request": "true"},
        ),
    )
    for response in responses:
        assert response.status_code == 200
        assert all(
            "sidebar-decks-section" not in data and "sidebar-panel" not in data
            for event, data in parse_datastar_events(response.text)
            if event == "datastar-patch-elements"
        )


def _assert_card_type_link(
    client: TestClient, links: dict[str, str], label: str, expected_ids: set[int]
) -> None:
    from urllib.parse import parse_qs, urlparse

    assert label in links
    href = links[label]
    parsed = urlparse(href)
    assert parsed.path == "/browse"
    query = parse_qs(parsed.query).get("q", [""])[0]
    assert query

    response = client.get(href)
    assert response.status_code == 200
    assert set(_extract_cids_from_html(response.text)) == expected_ids
    assert set(_extract_cids_from_search_post(client, query)) == expected_ids
    if not expected_ids:
        assert _run(client, lambda col: col.find_cards(query)) == []


def _add_card_type_model(
    col: Collection,
    deck_id: DeckId,
    name: str,
    template_fields: list[tuple[str, str]],
) -> tuple[str, list[str], dict[int, int]]:
    model = col.models.new(name)
    for field in ("Front", "Back", "Extra", "Unused"):
        col.models.add_field(model, col.models.new_field(field))
    for template_name, field in template_fields:
        template = col.models.new_template(template_name)
        template["qfmt"] = f"{{{{{field}}}}}"
        template["afmt"] = "{{FrontSide}}<hr id=answer>{{Back}}"
        col.models.add_template(model, template)
    result = col.models.add_dict(model)
    saved_model = col.models.get(NotetypeId(result.id))
    assert saved_model is not None
    note = col.new_note(saved_model)
    note["Front"] = f"{name} question"
    note["Back"] = f"{name} answer"
    note["Extra"] = f"{name} extra"
    col.add_note(note, deck_id)
    return (
        str(saved_model["name"]),
        [str(template["name"]) for template in saved_model["tmpls"]],
        {card.ord: int(card.id) for card in note.cards()},
    )


def _seed_card_type_templates(col: Collection) -> dict[str, set[int]]:
    model_name = 'Quoted "model"* & Ω'
    decoy_model_name = 'Quoted "model" decoy & Ω'
    first_template = 'Front "card"* & Ω'
    decoy_template = 'Front "card" decoy & Ω'
    shared_template = 'Shared "card"* & Ω'
    unused_template = 'Unused "card" & Ω'
    deck_id = col.decks.id("Default")
    assert deck_id is not None

    model_name, templates, cards = _add_card_type_model(
        col,
        deck_id,
        model_name,
        [
            (first_template, "Front"),
            (shared_template, "Back"),
            (decoy_template, "Extra"),
            (unused_template, "Unused"),
        ],
    )
    decoy_model_name, decoy_templates, decoy_cards = _add_card_type_model(
        col,
        deck_id,
        decoy_model_name,
        [(decoy_template, "Front"), (shared_template, "Back")],
    )
    assert set(cards) == {0, 1, 2}
    assert set(decoy_cards) == {0, 1}
    first_template, shared_template, decoy_template, unused_template = templates
    decoy_model_template, decoy_shared_template = decoy_templates

    cloze = col.models.by_name("Cloze")
    assert cloze is not None
    cloze_note = col.new_note(cloze)
    cloze_note["Text"] = "{{c1::first}} and {{c2::second}}"
    col.add_note(cloze_note, deck_id)
    cloze_cards = {card.ord: int(card.id) for card in cloze_note.cards()}
    assert set(cloze_cards) == {0, 1}
    cloze_name = str(cloze["name"])
    cloze_template = str(cloze["tmpls"][0]["name"])
    return {
        f"{first_template} — {model_name}": {cards[0]},
        f"{shared_template} — {model_name}": {cards[1]},
        f"{decoy_template} — {model_name}": {cards[2]},
        f"{unused_template} — {model_name}": set(),
        f"{decoy_model_template} — {decoy_model_name}": {decoy_cards[0]},
        f"{decoy_shared_template} — {decoy_model_name}": {decoy_cards[1]},
        f"{cloze_template} — {cloze_name}": set(cloze_cards.values()),
    }


def test_browse_sidebar_card_templates_filter_exact_cards(client: TestClient) -> None:
    expected = cast(dict[str, set[int]], _run(client, _seed_card_type_templates))
    browse = client.get("/browse")
    assert browse.status_code == 200
    links = _extract_sidebar_links(browse.text)
    cloze_label = next(label for label, ids in expected.items() if len(ids) == 2)
    cloze_suffix = f" — {cloze_label.rpartition(' — ')[2]}"
    assert {label for label in links if label.endswith(cloze_suffix)} == {cloze_label}

    for label, expected_ids in expected.items():
        _assert_card_type_link(client, links, label, expected_ids)


def test_browse_open_pushes_detail_and_selection(client):
    assert client.portal is not None
    cid = client.portal.call(
        client.app.state.service.run, lambda col: next(iter(col.find_cards("dog")))
    )
    hub = client.app.state.hub
    r = client.post(f"/browse/open/{cid}")
    assert r.status_code == 200
    assert hub.ui_state.selected_card_ids == [cid]
    assert len(hub.ui_state.selected_note_ids) == 1


def test_browse_invalid_search_does_not_crash(client):
    from conftest import parse_datastar_events

    r = client.post(
        "/browse/search",
        json={"query": "deck:((("},
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("invalid search" in data for _, data in events)
    assert any("0 cards" in data for _, data in events)


@pytest.mark.parametrize("query", ["re:[", "Front:re:[", "tag:re:["])
def test_browse_invalid_compiled_regex_returns_invalid_search(client, query):
    from conftest import parse_datastar_events

    response = client.post(
        "/browse/search",
        json={"query": query},
        headers={"Datastar-Request": "true"},
    )
    assert response.status_code == 200
    events = parse_datastar_events(response.text)
    assert any("invalid search" in data for _, data in events)
    assert any("0 cards" in data for _, data in events)


def test_browse_page_with_invalid_compiled_regex_renders_empty_results(client):
    response = client.get("/browse", params={"q": "re:["})
    assert response.status_code == 200
    assert 'value="re:["' in response.text
    assert "0 cards" in response.text


def test_browse_refresh_preserves_editor_state_and_updates_rows(client):
    from conftest import parse_datastar_events

    hub = client.app.state.hub
    cid = _run(client, lambda col: next(iter(col.find_cards("dog"))))
    nid = _run(client, lambda col: col.get_card(cid).nid)

    search = client.post(
        "/browse/search", json={"query": "dog"}, headers={"Datastar-Request": "true"}
    )
    assert search.status_code == 200
    opened = client.post(f"/browse/open/{cid}")
    assert opened.status_code == 200
    assert hub.ui_state.selected_card_ids == [cid]
    assert hub.ui_state.selected_note_ids == [nid]

    def update_front(col):
        note = col.get_note(nid)
        note["Front"] = "dog refreshed"
        col.update_note(note, skip_undo_entry=True)

    _run(client, update_front)
    response = client.post(
        "/browse/refresh",
        json={
            "selectedCids": [cid],
            "selectionAnchor": cid,
            "query": "draft cat query",
            "browserQuery": "dog",
        },
        headers={"Datastar-Request": "true"},
    )
    assert response.status_code == 200
    events = parse_datastar_events(response.text)
    element_patches = [
        data for event_type, data in events if event_type == "datastar-patch-elements"
    ]
    assert any(
        "results-body" in data and "dog refreshed" in data for data in element_patches
    )
    assert any("browser-status" in data for data in element_patches)
    assert all("#detail" not in data for data in element_patches)
    assert hub.ui_state.selected_card_ids == [cid]
    assert hub.ui_state.selected_note_ids == [nid]
    assert hub.ui_state.matched_card_ids == [cid]
    assert hub.ui_state.last_browse_query == "dog"

    invalid_response = client.post(
        "/browse/refresh",
        json={
            "selectedCids": [cid],
            "selectionAnchor": cid,
            "query": "draft cat query",
            "browserQuery": "re:[",
        },
        headers={"Datastar-Request": "true"},
    )
    assert invalid_response.status_code == 200
    invalid_events = parse_datastar_events(invalid_response.text)
    invalid_elements = [
        data
        for event_type, data in invalid_events
        if event_type == "datastar-patch-elements"
    ]
    assert any("invalid search" in data for data in invalid_elements)
    assert any("browser-status" in data for data in invalid_elements)
    assert all("#detail" not in data for data in invalid_elements)
    assert hub.ui_state.selected_card_ids == [cid]
    assert hub.ui_state.selected_note_ids == [nid]
    assert hub.ui_state.matched_card_ids == []


def _run(client, fn):
    assert client.portal is not None
    return client.portal.call(client.app.state.service.run, fn)


def test_refresh_keeps_detail_for_card_outside_search_results(client):
    from conftest import parse_datastar_events

    hub = client.app.state.hub
    cid = _run(client, lambda col: next(iter(col.find_cards("dog"))))
    nid = _run(client, lambda col: col.get_card(cid).nid)
    searched = client.post(
        "/browse/search",
        json={"query": "dog"},
        headers={"Datastar-Request": "true"},
    )
    assert searched.status_code == 200
    opened = client.post(f"/browse/open/{cid}", data={"browserQuery": "dog"})
    assert opened.status_code == 200
    assert hub.ui_state.selected_card_ids == [cid]
    assert hub.ui_state.selected_note_ids == [nid]

    def move_note_outside_search(col):
        note = col.get_note(nid)
        note["Front"] = "wolf refreshed"
        note["Back"] = "WOLF"
        col.update_note(note, skip_undo_entry=True)

    _run(client, move_note_outside_search)
    response = client.post(
        "/browse/refresh",
        data={
            "selectedCids": [str(cid)],
            "selectionAnchor": str(cid),
            "browserQuery": "dog",
        },
        headers={"Datastar-Request": "true"},
    )
    assert response.status_code == 200
    events = parse_datastar_events(response.text)
    element_patches = [
        data for event_type, data in events if event_type == "datastar-patch-elements"
    ]
    results_patch = next(data for data in element_patches if "results-body" in data)
    assert _extract_cids_from_html(results_patch) == []
    assert all("#detail" not in data for data in element_patches)
    assert hub.ui_state.selected_card_ids == [cid]
    assert hub.ui_state.selected_note_ids == [nid]
    assert hub.ui_state.matched_card_ids == []
    assert _run(client, lambda col: col.get_note(nid)["Front"]) == "wolf refreshed"


def test_refresh_closes_detail_when_selected_note_is_deleted(client):
    from html.parser import HTMLParser

    from conftest import parse_datastar_events

    hub = client.app.state.hub
    cid = _run(client, lambda col: next(iter(col.find_cards("dog"))))
    nid = _run(client, lambda col: col.get_card(cid).nid)
    searched = client.post(
        "/browse/search",
        json={"query": "dog"},
        headers={"Datastar-Request": "true"},
    )
    assert searched.status_code == 200
    opened = client.post(f"/browse/open/{cid}", data={"browserQuery": "dog"})
    assert opened.status_code == 200
    assert hub.ui_state.selected_card_ids == [cid]
    assert hub.ui_state.selected_note_ids == [nid]

    _run(client, lambda col: col.remove_notes([nid]))
    response = client.post(
        "/browse/refresh",
        data={
            "selectedCids": [str(cid)],
            "selectionAnchor": str(cid),
            "browserQuery": "dog",
        },
        headers={"Datastar-Request": "true"},
    )
    assert response.status_code == 200
    events = parse_datastar_events(response.text)
    element_patches = [
        data for event_type, data in events if event_type == "datastar-patch-elements"
    ]
    results_patch = next(data for data in element_patches if "results-body" in data)
    assert _extract_cids_from_html(results_patch) == []
    detail_patch = next(data for data in element_patches if "#detail" in data)

    class IframeFinder(HTMLParser):
        def __init__(self):
            super().__init__()
            self.found = False

        def handle_starttag(self, tag, attrs):
            if tag == "iframe":
                self.found = True

    detail = IframeFinder()
    detail.feed(detail_patch)
    assert not detail.found
    assert hub.ui_state.selected_card_ids == []
    assert hub.ui_state.selected_note_ids == []
    assert hub.ui_state.matched_card_ids == []
    assert _run(client, lambda col: col.find_cards("dog")) == []


def test_selection_forms_keep_anchor_across_toggle_and_range(client):
    from html.parser import HTMLParser

    cids = _run(client, lambda col: list(col.find_cards("")))
    assert len(cids) == 2
    first, second = cids
    hub = client.app.state.hub

    single = client.post(
        "/browse/select",
        data={"browserQuery": "", "cid": str(first), "mode": "single"},
        headers={"Datastar-Request": "true"},
    )
    assert single.status_code == 200
    assert hub.ui_state.selected_card_ids == [first]

    toggled_off = client.post(
        "/browse/select",
        data={
            "browserQuery": "",
            "selectedCids": [str(first)],
            "selectionAnchor": str(first),
            "cid": str(first),
            "mode": "toggle",
        },
        headers={"Datastar-Request": "true"},
    )
    assert toggled_off.status_code == 200
    assert hub.ui_state.selected_card_ids == []

    class StateInputParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.values = {}

        def handle_starttag(self, tag, attrs):
            if tag != "input":
                return
            fields = dict(attrs)
            name = fields.get("name")
            if name:
                self.values.setdefault(name, []).append(fields.get("value", ""))

    state = StateInputParser()
    state.feed(toggled_off.text)
    assert state.values["selectionAnchor"] == [str(first)]
    assert state.values.get("selectedCids", []) == []

    ranged = client.post(
        "/browse/select",
        data={
            "browserQuery": "",
            "selectionAnchor": state.values["selectionAnchor"][0],
            "cid": str(second),
            "mode": "range",
        },
        headers={"Datastar-Request": "true"},
    )
    assert ranged.status_code == 200
    assert hub.ui_state.selected_card_ids == cids

    selected_all = client.post(
        "/browse/select",
        data={"browserQuery": "", "mode": "all"},
        headers={"Datastar-Request": "true"},
    )
    assert selected_all.status_code == 200
    assert hub.ui_state.selected_card_ids == cids

    selected_none = client.post(
        "/browse/select",
        data={
            "browserQuery": "",
            "selectedCids": [str(cid) for cid in cids],
            "mode": "none",
        },
        headers={"Datastar-Request": "true"},
    )
    assert selected_none.status_code == 200
    assert hub.ui_state.selected_card_ids == []


def test_select_then_suspend(client):
    from conftest import parse_datastar_events

    hub = client.app.state.hub
    cids = _run(client, lambda col: list(col.find_cards("")))
    r1 = client.post(
        "/browse/select",
        json={"selectedCids": cids},
        headers={"Datastar-Request": "true"},
    )
    assert r1.status_code == 200
    assert hub.ui_state.selected_card_ids == cids
    assert len(hub.ui_state.selected_note_ids) == 2

    r2 = client.post(
        "/browse/suspend",
        json={
            "selectedCids": cids,
            "browserQuery": "",
        },
        headers={"Datastar-Request": "true"},
    )
    assert r2.status_code == 200
    events2 = parse_datastar_events(r2.text)
    assert any("results-body" in data for _, data in events2)
    assert any(
        event_type == "datastar-patch-elements" and "#detail" in data
        for event_type, data in events2
    )
    assert hub.ui_state.selected_card_ids == []
    assert hub.ui_state.selected_note_ids == []
    assert all(_run(client, lambda col, c=c: col.get_card(c).queue) == -1 for c in cids)


def test_mutation_routes_are_silent_noop_with_empty_selection(client):
    # guard-failure branches (nothing selected) must reproduce the old handler's
    # silent `return None` no-op — a 204 with zero SSE events — not unconditionally
    # re-search and wipe the open #detail pane.
    hub = client.app.state.hub
    hub.ui_state.selected_card_ids = []
    hub.ui_state.selected_note_ids = []
    for path, kwargs in [
        (
            "/browse/suspend",
            {"json": {"selectedCids": []}, "headers": {"Datastar-Request": "true"}},
        ),
        (
            "/browse/unsuspend",
            {"json": {"selectedCids": []}, "headers": {"Datastar-Request": "true"}},
        ),
        (
            "/browse/forget",
            {"json": {"selectedCids": []}, "headers": {"Datastar-Request": "true"}},
        ),
        (
            "/browse/delete",
            {"json": {"selectedCids": []}, "headers": {"Datastar-Request": "true"}},
        ),
        (
            "/browse/setdue",
            {
                "json": {"selectedCids": [], "value": "0"},
                "headers": {"Datastar-Request": "true"},
            },
        ),
        (
            "/browse/changedeck",
            {
                "json": {"selectedCids": [], "deck": "Spanish"},
                "headers": {"Datastar-Request": "true"},
            },
        ),
        (
            "/browse/addtag",
            {
                "json": {"selectedCids": [], "tag": "marked"},
                "headers": {"Datastar-Request": "true"},
            },
        ),
        (
            "/browse/removetag",
            {
                "json": {"selectedCids": [], "tag": "marked"},
                "headers": {"Datastar-Request": "true"},
            },
        ),
    ]:
        r = client.post(path, **kwargs)
        assert r.status_code == 204, f"{path} should no-op (204) with empty selection"
        assert r.text == ""


def test_delete_removes_notes(client):
    from conftest import parse_datastar_events

    cid = _run(client, lambda col: next(iter(col.find_cards("dog"))))
    before = _run(client, lambda col: len(col.find_notes("")))
    r = client.post(
        "/browse/delete",
        json={"selectedCids": [cid]},
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("results-body" in data for _, data in events)
    assert _run(client, lambda col: len(col.find_notes(""))) == before - 1


def test_changedeck_moves_card(client):
    from conftest import parse_datastar_events

    cid = _run(client, lambda col: next(iter(col.find_cards("dog"))))
    r = client.post(
        "/browse/changedeck",
        json={"selectedCids": [cid], "deck": "Spanish"},
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("results-body" in data for _, data in events)
    did = _run(client, lambda col: col.get_card(cid).did)
    assert did == _run(client, lambda col: col.decks.id("Spanish"))


def test_add_and_remove_tag(client):
    cid = _run(client, lambda col: next(iter(col.find_cards("dog"))))
    nid = _run(client, lambda col: col.get_card(cid).nid)
    r1 = client.post(
        "/browse/addtag",
        json={"selectedCids": [cid], "tag": "marked"},
        headers={"Datastar-Request": "true"},
    )
    assert r1.status_code == 200
    assert "marked" in _run(client, lambda col: col.get_note(nid).tags)

    r2 = client.post(
        "/browse/removetag",
        json={"selectedCids": [cid], "tag": "marked"},
        headers={"Datastar-Request": "true"},
    )
    assert r2.status_code == 200
    assert "marked" not in _run(client, lambda col: col.get_note(nid).tags)


def test_setdue_runs(client):
    from conftest import parse_datastar_events

    cid = _run(client, lambda col: next(iter(col.find_cards("dog"))))
    r = client.post(
        "/browse/setdue",
        json={"selectedCids": [cid], "value": "0"},
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("results-body" in data for _, data in events)


def test_action_selection_overrides_differently_populated_hub(client):
    # A new form submission is authoritative, NEVER cached hub selection.
    hub = client.app.state.hub
    dog_cid = _run(client, lambda col: next(iter(col.find_cards("dog"))))
    cat_cid = _run(client, lambda col: next(iter(col.find_cards("cat"))))
    hub.ui_state.selected_card_ids = [dog_cid]
    response = client.post(
        "/browse/suspend",
        data={
            "browserQuery": "",
            "query": "dog",
            "selectedCids": [str(cat_cid)],
        },
        headers={"Datastar-Request": "true"},
    )
    assert response.status_code == 200
    cat_queue = _run(client, lambda col: col.get_card(cat_cid).queue)
    dog_queue = _run(client, lambda col: col.get_card(dog_cid).queue)
    assert cat_queue == -1
    assert dog_queue != -1
    assert hub.ui_state.last_browse_query == ""


def test_form_without_selection_never_falls_back_to_cached_cards(client):
    hub = client.app.state.hub
    cids = _run(client, lambda col: list(col.find_cards("")))
    hub.ui_state.selected_card_ids = list(cids)
    response = client.post("/browse/suspend", data={"browserQuery": ""})
    assert response.status_code == 204
    assert all(
        _run(client, lambda col, cid=cid: col.get_card(cid).queue) != -1 for cid in cids
    )


def test_form_mutation_filters_duplicate_stale_and_overflow_ids(client):
    hub = client.app.state.hub
    dog_cid = _run(client, lambda col: next(iter(col.find_cards("dog"))))
    cat_cid = _run(client, lambda col: next(iter(col.find_cards("cat"))))
    hub.ui_state.selected_card_ids = [cat_cid]
    original_queues = _run(
        client,
        lambda col: {
            dog_cid: col.get_card(dog_cid).queue,
            cat_cid: col.get_card(cat_cid).queue,
        },
    )

    response = client.post(
        "/browse/suspend",
        data={
            "browserQuery": "",
            "selectedCids": [
                str(dog_cid),
                str(dog_cid),
                str(2**40),
                str(2**100),
            ],
        },
        headers={"Datastar-Request": "true"},
    )
    assert response.status_code == 200
    queues = _run(
        client,
        lambda col: {
            dog_cid: col.get_card(dog_cid).queue,
            cat_cid: col.get_card(cat_cid).queue,
        },
    )
    assert original_queues[dog_cid] != -1
    assert original_queues[cat_cid] != -1
    assert queues == {dog_cid: -1, cat_cid: original_queues[cat_cid]}
    assert hub.ui_state.selected_card_ids == []


def test_valid_and_invalid_search_clearing_state(client):
    from conftest import parse_datastar_events

    hub = client.app.state.hub
    hub.ui_state.selected_card_ids = [12345]
    hub.ui_state.selected_note_ids = [67890]
    hub.ui_state.matched_card_ids = [12345]

    # Explicit searches clear selection, refresh results, and close detail.
    r1 = client.post(
        "/browse/search",
        json={"query": "dog", "browserQuery": "stale query"},
        headers={"Datastar-Request": "true"},
    )
    assert r1.status_code == 200
    events1 = parse_datastar_events(r1.text)
    assert any(
        event_type == "datastar-patch-elements" and "#detail" in data
        for event_type, data in events1
    )
    assert hub.ui_state.selected_card_ids == []
    assert hub.ui_state.selected_note_ids == []
    assert len(hub.ui_state.matched_card_ids) == 1

    # An invalid explicit search has the same reset semantics.
    hub.ui_state.selected_card_ids = [12345]
    hub.ui_state.selected_note_ids = [67890]
    hub.ui_state.matched_card_ids = [12345]
    r2 = client.post(
        "/browse/search",
        json={"query": "re:["},
        headers={"Datastar-Request": "true"},
    )
    assert r2.status_code == 200
    events2 = parse_datastar_events(r2.text)
    assert any(
        event_type == "datastar-patch-elements" and "#detail" in data
        for event_type, data in events2
    )
    assert hub.ui_state.selected_card_ids == []
    assert hub.ui_state.matched_card_ids == []
    assert hub.ui_state.selected_note_ids == []


def test_note_deduplication_for_sibling_cards(client):
    # Sibling cards belonging to the same note should de-duplicate for note-level actions
    def seed_siblings(col):
        m_rev = col.models.by_name("Basic (and reversed card)")
        d = col.decks.id("Default")
        n = col.new_note(m_rev)
        n["Front"] = "sibling1"
        n["Back"] = "sibling2"
        col.add_note(n, d)
        cards = n.cards()
        return n.id, cards[0].id, cards[1].id

    nid, c1, c2 = _run(client, seed_siblings)
    # Adding tag with both sibling card IDs selected
    r = client.post(
        "/browse/addtag",
        json={"selectedCids": [c1, c2], "tag": "siblingtag"},
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200
    tags = _run(client, lambda col: col.get_note(nid).tags)
    assert tags.count("siblingtag") == 1


def test_invalid_due_response_without_mutation(client):
    cid = _run(client, lambda col: next(iter(col.find_cards("dog"))))
    orig_due = _run(client, lambda col: col.get_card(cid).due)
    orig_queue = _run(client, lambda col: col.get_card(cid).queue)

    response = client.post(
        "/browse/setdue",
        data={"selectedCids": [str(cid)], "value": "not-a-valid-due"},
        headers={"Datastar-Request": "true"},
    )
    assert response.status_code == 200
    card_after = _run(client, lambda col: col.get_card(cid))
    assert card_after.due == orig_due
    assert card_after.queue == orig_queue


def test_row_data_rich_fields_and_formatted_due(client):
    import datetime
    import time
    from datetime import UTC

    from ankiweb.adapters.inbound.http_datastar.browser import _row_data

    def seed_various_cards(col):
        m_rev = col.models.by_name("Basic (and reversed card)")
        d = col.decks.id("Default")
        note = col.new_note(m_rev)
        note["Front"] = "alpha"
        note["Back"] = "beta"
        note.tags = ["tag1", "tag2"]
        col.add_note(note, d)

        cards = note.cards()
        c1, c2 = cards[0], cards[1]

        # c1 is new
        c1.queue = 0
        c1.due = 7
        col.update_card(c1)

        # c2 is review
        c2.queue = 2
        c2.type = 2
        c2.due = col.sched.today + 4
        col.update_card(c2)

        # single basic note for suspended & learn
        m_basic = col.models.by_name("Basic")
        note2 = col.new_note(m_basic)
        note2["Front"] = "gamma"
        note2["Back"] = "delta"
        col.add_note(note2, d)
        c3 = note2.cards()[0]
        c3.queue = -1
        col.update_card(c3)

        note3 = col.new_note(m_basic)
        note3["Front"] = "learn_card"
        note3["Back"] = "epsilon"
        col.add_note(note3, d)
        c4 = note3.cards()[0]
        c4.queue = 1
        c4.due = int(time.time()) + 300
        col.update_card(c4)

        # c5 is review past due
        note4 = col.new_note(m_basic)
        note4["Front"] = "past_due_card"
        note4["Back"] = "zeta"
        col.add_note(note4, d)
        c5 = note4.cards()[0]
        c5.queue = 2
        c5.type = 2
        c5.due = col.sched.today - 3
        col.update_card(c5)

        return c1.id, c2.id, c3.id, c4.id, c5.id

    c1_id, c2_id, c3_id, c4_id, c5_id = _run(client, seed_various_cards)

    def check_rows(col):
        rows = _row_data(col, [c1_id, c2_id, c3_id, c4_id, c5_id])
        return rows

    rows = _run(client, check_rows)
    assert len(rows) == 5

    r1 = next(r for r in rows if r["cid"] == c1_id)
    assert r1["sort_text"] == "alpha"
    assert r1["template_name"] == "Card 1"
    assert r1["note_type_name"] == "Basic (and reversed card)"
    assert r1["deck"] == "Default"
    assert r1["tags"] == "tag1 tag2"
    assert "#7" in r1["due"]
    assert r1["is_suspended"] is False

    r2 = next(r for r in rows if r["cid"] == c2_id)
    assert r2["sort_text"] == "alpha"
    assert r2["template_name"] == "Card 2"
    assert r2["note_type_name"] == "Basic (and reversed card)"
    today = datetime.datetime.now(tz=UTC).astimezone().date()
    assert r2["due"] == (today + datetime.timedelta(days=4)).isoformat()
    assert r2["is_suspended"] is False
    r3 = next(r for r in rows if r["cid"] == c3_id)
    assert r3["sort_text"] == "gamma"
    assert r3["is_suspended"] is True
    assert len(r3["due"]) > 0  # e.g. 'Suspended' or 'Ausgeschlossen'

    r4 = next(r for r in rows if r["cid"] == c4_id)
    assert r4["sort_text"] == "learn_card"
    assert ":" in r4["due"]  # HH:MM timestamp

    r5 = next(r for r in rows if r["cid"] == c5_id)
    assert r5["sort_text"] == "past_due_card"
    assert r5["due"] == (today - datetime.timedelta(days=3)).isoformat()
    # verify rendering of these rows includes template names and tags
    html = client.get("/browse?q=alpha").text
    assert "Card 1" in html
    assert "Card 2" in html
    assert "tag1 tag2" in html


def test_browse_q_param_prefills_input(client):
    r = client.get("/browse?q=deck:Default")
    assert r.status_code == 200
    assert 'value="deck:Default"' in r.text


def test_browse_q_param_html_escaped(client):
    r = client.get('/browse?q=front:"a<b>"')
    assert r.status_code == 200
    assert "&lt;b&gt;" in r.text
    assert "<b&gt;" not in r.text
