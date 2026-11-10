from __future__ import annotations

import json
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol, cast

import anki.collection
import anki.lang
import pytest
from anki.cards import CardId
from anki.decks import DeckId
from anki.notes import NoteId
from anki.scheduler.v3 import Scheduler
from anki.scheduler_pb2 import CardAnswer
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ankiweb.app import create_app
from ankiweb.core.app_client.vocab import add_vocab_note
from ankiweb.core.config import Settings

DEFAULT_DECK = DeckId(1)
_CARD_FIELDS = ("type", "queue", "due", "ivl", "factor", "reps", "lapses")
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


def _run[T](
    client: TestClient, operation: Callable[[anki.collection.Collection], T]
) -> T:
    assert client.portal is not None
    service = cast(FastAPI, client.app).state.service
    return client.portal.call(service.run, operation)


class _TextResponse(Protocol):
    @property
    def text(self) -> str: ...


class _Response(_TextResponse, Protocol):
    @property
    def status_code(self) -> int: ...


class _Region(HTMLParser):
    """Collect note rows and text inside one stable fragment ID."""

    def __init__(self, html: str, region_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.region_id = region_id
        self.depth = 0
        self.found = False
        self.attributes: dict[str, str | None] = {}
        self.ids: list[int] = []
        self.text: list[str] = []
        self.rows: dict[int, list[str]] = {}
        self.row: int | None = None
        self.row_depth = 0
        self.has_stamp = False
        self.fields: dict[str, str] = {}
        self.field: str | None = None
        self.counters: dict[str, str] = {}
        self.counter: str | None = None
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if not self.depth:
            if attributes.get("id") != self.region_id or self.found:
                return
            self.found = True
            self.attributes = attributes
            self.depth = 1
        elif tag not in _VOID_TAGS:
            self.depth += 1
        if "data-ts" in attributes:
            self.has_stamp = True
        if tag == "textarea" and (name := attributes.get("name")) is not None:
            self.field = name
            self.fields[name] = ""
        if (counter := attributes.get("data-counter-for")) is not None:
            self.counter = counter
            self.counters[counter] = ""
        if (nid := attributes.get("data-note-id")) is not None:
            self.row = int(nid)
            self.row_depth = self.depth
            self.ids.append(self.row)
            self.rows[self.row] = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "textarea":
            self.field = None
        if tag == "span" and self.counter is not None:
            self.counter = None
        if self.depth and tag not in _VOID_TAGS:
            if self.row is not None and self.row_depth == self.depth:
                self.row = None
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth:
            if self.field is not None:
                self.fields[self.field] += data
            if self.counter is not None:
                self.counters[self.counter] += data
            self.text.append(data)
            if self.row is not None:
                self.rows[self.row].append(data)


def _html(response: _TextResponse) -> str:
    if "event: datastar-patch-elements" not in response.text:
        return response.text
    return "\n".join(
        line.removeprefix("data: elements ")
        for line in response.text.splitlines()
        if line.startswith("data: elements ")
    )


def _region(response: _TextResponse, region_id: str) -> _Region:
    region = _Region(_html(response), region_id)
    assert region.found, f"Missing #{region_id}"
    return region


def _has_region(response: _TextResponse, region_id: str) -> bool:
    return _Region(_html(response), region_id).found


def _page_guard(page: _Response) -> str:
    assert page.status_code == 200
    form = _region(page, "edit-session")
    return f"{form.attributes['data-instance']}/{form.attributes['data-rev']}"


def _form_guard(client: TestClient, deck: DeckId) -> str:
    return _page_guard(client.get(f"/app/edit/{deck}/front"))


def _assert_form(
    response: _TextResponse,
    nid: int,
    fields: dict[str, str],
    *,
    learned: bool = False,
) -> None:
    form = _region(response, "edit-form")
    session = _region(response, "edit-session")
    assert session.attributes["data-nid"] == str(nid)
    assert json.loads(cast(str, session.attributes["data-original"])) == fields
    assert form.counters == {
        key: str(len(value.encode("utf-16-le")) // 2) for key, value in fields.items()
    }
    error = _region(response, "edit-error")
    assert "hidden" in error.attributes and error.attributes["role"] == "alert"
    assert "".join(error.text).strip() == ""
    assert form.fields == fields
    assert _has_region(response, "edit-warning") is learned


def _assert_count(response: _TextResponse, count: int, deck_count: int) -> None:
    assert "".join(_region(response, "summary-count").text).strip() == str(count)
    label = _region(response, "pile").attributes["aria-label"]
    assert label is not None and label.split()[0] == str(deck_count)


def _load(client: TestClient, nid: NoteId, deck: DeckId = DEFAULT_DECK) -> _Response:
    guard = _form_guard(client, deck)
    return client.post(
        f"/app/edit/{deck}/{guard}/card/{nid}",
        data={"nid": "0", "front": "", "back": "", "hint": "", "example": ""},
    )


def _commit(
    client: TestClient,
    nid: NoteId,
    values: dict[str, str],
    deck: DeckId = DEFAULT_DECK,
    claimed_learned: bool | None = None,
) -> _Response:
    payload = {
        "nid": str(nid),
        "front": "",
        "back": "",
        "hint": "",
        "example": "",
        **values,
    }
    if claimed_learned is not None:
        payload["learned"] = str(claimed_learned).lower()
    guard = _form_guard(client, deck)
    return client.post(f"/app/edit/{deck}/{guard}/commit", data=payload)


def _answer(
    col: anki.collection.Collection, cid: CardId, rating: CardAnswer.Rating.V
) -> None:
    card = col.get_card(cid)
    card.start_timer()
    states = col._backend.get_scheduling_states(cid)
    sched = col.sched
    assert isinstance(sched, Scheduler)
    sched.answer_card(sched.build_answer(card=card, states=states, rating=rating))


def _learn(col: anki.collection.Collection, cid: CardId, stage: str) -> None:
    # The real scheduler transitions used in the installed-Anki reset experiment.
    _answer(col, cid, CardAnswer.EASY)
    _answer(col, cid, CardAnswer.AGAIN)
    if stage == "learning":
        sched = col.sched
        assert isinstance(sched, Scheduler)
        sched.schedule_cards_as_new([cid], reset_counts=False)
        _answer(col, cid, CardAnswer.AGAIN)
    else:
        assert stage == "review"
        _answer(col, cid, CardAnswer.EASY)
    card = col.get_card(cid)
    assert card.type == (1 if stage == "learning" else 2)
    assert card.reps > 0 and card.lapses > 0


def _snapshot(
    col: anki.collection.Collection, cid: CardId
) -> tuple[tuple[int, ...], list[tuple[int, ...]]]:
    card = col.get_card(cid)
    fields = tuple(getattr(card, key) for key in _CARD_FIELDS)
    assert col.db is not None
    rows = col.db.all(
        "SELECT id, cid, usn, ease, ivl, lastIvl, factor, time, type "
        "FROM revlog WHERE cid = ? ORDER BY id",
        cid,
    )
    return fields, [tuple(row) for row in rows]


def _snapshots(
    client: TestClient, ids: tuple[CardId, ...]
) -> dict[CardId, tuple[tuple[int, ...], list[tuple[int, ...]]]]:
    return _run(client, lambda col: {cid: _snapshot(col, cid) for cid in ids})


def _siblings(
    col: anki.collection.Collection,
    selected_stage: str | None,
    other_stage: str | None = "review",
) -> tuple[NoteId, CardId, CardId, CardId]:
    """Create scheduler-real cards for one note across two decks.

    Vocab has one strictly validated template, so independent scheduler-created
    cards are attached to the note as same-template siblings after answering.
    """
    selected = DeckId(1)
    other = col.decks.id("Other deck")
    assert other is not None
    nid = add_vocab_note(col, selected, "Original", "Answer", "Hint", "Example")
    first = col.get_note(nid).cards()[0].id
    second_nid = add_vocab_note(col, selected, "Selected sibling", "Answer")
    second = col.get_note(second_nid).cards()[0].id
    other_nid = add_vocab_note(col, other, "Other sibling", "Answer")
    foreign = col.get_note(other_nid).cards()[0].id
    if selected_stage is not None:
        _learn(col, second, selected_stage)
    if other_stage is not None:
        _learn(col, foreign, other_stage)
    # Keep ord 0: the only valid template in the supported notetype. Donor
    # notes have no cards afterwards and therefore cannot appear in either deck.
    assert col.db is not None
    col.db.execute("UPDATE cards SET nid = ? WHERE id IN (?, ?)", nid, second, foreign)
    return nid, first, second, foreign


def test_tab_guards_and_session_counts_ignore_claimed_form_state(
    client: TestClient,
) -> None:
    tab_a = client.get("/app/edit/1/front")
    tab_b = client.get("/app/edit/1/front")
    guard_a, guard_b = _page_guard(tab_a), _page_guard(tab_b)
    assert guard_a != guard_b
    original_cookies = dict(client.cookies)
    payload = {
        "nid": "0",
        "front": "First",
        "back": "Answer",
        "hint": "",
        "example": "",
        "learned": "true",
        "progressReset": "true",
        "count": "999",
        "deckCount": "999",
    }

    first = client.post(f"/app/edit/1/{guard_a}/commit", data=payload)
    _assert_count(first, 1, 1)
    assert not _has_region(first, "progress-reset-notice")
    assert (
        f'data-instance="{_region(tab_a, "edit-session").attributes["data-instance"]}"'
        in first.text
    )

    second = client.post(
        f"/app/edit/1/{guard_b}/commit", data={**payload, "front": "Second"}
    )
    _assert_count(second, 2, 2)
    assert (
        f'data-instance="{_region(tab_b, "edit-session").attributes["data-instance"]}"'
        in second.text
    )

    client.cookies.clear()
    other = client.get("/app/edit/1/front")
    _assert_count(other, 0, 2)
    third = client.post(
        f"/app/edit/1/{_page_guard(other)}/commit",
        data={**payload, "front": "Third"},
    )
    _assert_count(third, 1, 3)

    client.cookies.clear()
    client.cookies.update(original_cookies)
    restored = client.get("/app/edit/1/front")
    _assert_count(restored, 2, 3)


def test_deck_list_spans_sessions_and_edits_without_growing_pile(
    client: TestClient,
) -> None:
    assert client.get("/app/edit/1/front").status_code == 200
    prior = _commit(
        client,
        NoteId(0),
        {
            "front": "Prior session",
            "back": "Earlier",
            "hint": "Old hint",
            "example": "Old example",
        },
    )
    _assert_count(prior, 1, 1)
    prior_id = _run(client, lambda col: col.find_notes("")[0])

    def seed(col: anki.collection.Collection) -> tuple[list[NoteId], NoteId, NoteId]:
        other = col.decks.id("Foreign deck")
        model = col.models.by_name("Basic")
        assert other is not None and model is not None
        ids = [
            add_vocab_note(col, DeckId(1), f"Existing {i}", f"Answer {i}")
            for i in range(5)
        ]
        foreign = add_vocab_note(col, other, "Foreign vocabulary", "Answer")
        basic = col.new_note(model)
        basic["Front"], basic["Back"] = "Foreign notetype", "Answer"
        col.add_note(basic, DeckId(1))
        return ids, foreign, basic.id

    existing, foreign, basic = _run(client, seed)
    client.cookies.clear()
    page = client.get("/app/edit/1/front")
    assert page.status_code == 200
    assert _region(page, "deck-cards").ids == sorted([prior_id, *existing])
    pile = _region(page, "added-cards")
    assert all(f"Existing {index}" in " ".join(pile.text) for index in range(5))
    assert "Prior session" not in " ".join(pile.text)
    for nid in (foreign, basic):
        assert _load(client, nid).status_code == 404
        assert (
            _commit(client, nid, {"front": "Denied", "back": "Answer"}).status_code
            == 404
        )

    added_ids: set[NoteId] = set()
    for index in range(5):
        response = _commit(
            client,
            NoteId(0),
            {"front": f"Current {index}", "back": f"Current answer {index}"},
        )
        assert response.status_code == 200
        _assert_count(response, index + 1, 7 + index)
        added_ids = set(_run(client, lambda col: col.find_notes(""))) - {
            prior_id,
            *existing,
            foreign,
            basic,
        }
    pile = _region(response, "added-cards")
    assert all(f"Current {index}" in " ".join(pile.text) for index in range(5))
    assert "Prior session" not in " ".join(pile.text)
    assert _region(response, "deck-cards").ids == sorted(
        [prior_id, *existing, *added_ids]
    )

    before_ids = set(_run(client, lambda col: col.find_notes("")))
    original = {
        "front": "Prior session",
        "back": "Earlier",
        "hint": "Old hint",
        "example": "Old example",
    }
    loaded = _load(client, prior_id)
    assert loaded.status_code == 200
    _assert_form(loaded, prior_id, original)
    assert _region(loaded, "edit-step").attributes["data-step"] == "1"
    assert not _has_region(loaded, "progress-reset-notice")

    updated = {**original, "front": "Updated earlier card"}
    response = _commit(client, prior_id, updated)
    assert response.status_code == 200
    _assert_count(response, 5, 11)
    _assert_form(response, 0, dict.fromkeys(original, ""))
    assert not _has_region(response, "progress-reset-notice")
    assert not _region(response, "added-cards").has_stamp
    assert _region(response, "deck-cards").ids == sorted(
        [prior_id, *existing, *added_ids]
    )
    assert set(_run(client, lambda col: col.find_notes(""))) == before_ids
    _assert_form(_load(client, prior_id), prior_id, updated)


@pytest.mark.parametrize(
    ("lang", "marker", "warning"),
    [
        (
            "en",
            "Learned",
            "Changes to this learned card will reset its learning progress.",
        ),
        (
            "de_DE",
            "Gelernt",
            "Änderungen an dieser gelernten Karte setzen den Lernfortschritt zurück.",
        ),
    ],
)
def test_learned_deck_card_is_localized(
    tmp_path: Path, lang: str, marker: str, warning: str
) -> None:
    settings = Settings(collection_path=tmp_path / "localized.anki2", lang=lang)
    try:
        with TestClient(create_app(settings)) as client:

            def seed(col: anki.collection.Collection) -> NoteId:
                nid = add_vocab_note(col, DEFAULT_DECK, "Reviewed", "Answer")
                note = col.get_note(nid)
                model = note.note_type()
                assert model is not None
                assert model["name"] == "AnkiWeb Vocab"
                assert [field["name"] for field in model["flds"]] == [
                    "Front",
                    "Back",
                    "Hint",
                    "Example",
                ]
                assert [template["name"] for template in model["tmpls"]] == ["Card 1"]
                _learn(col, note.cards()[0].id, "review")
                return nid

            nid = _run(client, seed)
            page = client.get("/app/edit/1/front")
            assert page.status_code == 200
            deck = _region(page, "deck-cards")
            assert deck.ids == [nid]
            row = deck.rows[int(nid)]
            assert "Reviewed" in row and "Answer" in row and marker in row
            assert not _has_region(page, "edit-warning")

            loaded = _load(client, nid)
            assert loaded.status_code == 200
            assert "".join(_region(loaded, "edit-warning").text).strip() == warning
    finally:
        anki.lang.set_lang("en")


def test_learned_status_considers_every_card_in_selected_deck(
    client: TestClient,
) -> None:
    nid, first, learned, foreign = _run(
        client, lambda col: _siblings(col, "review", None)
    )
    assert _run(client, lambda col: col.get_card(first).type) == 0
    assert _run(client, lambda col: col.get_card(learned).type) == 2
    assert _run(client, lambda col: col.get_card(foreign).type) == 0
    assert _has_region(_load(client, nid), "edit-warning")
    other_deck = _run(client, lambda col: col.get_card(foreign).did)
    assert not _has_region(_load(client, nid, other_deck), "edit-warning")


@pytest.mark.parametrize("stage", ["learning", "review"])
def test_changed_learned_note_resets_only_selected_deck_and_retains_history(
    client: TestClient, stage: str
) -> None:
    nid, first, learned, foreign = _run(client, lambda col: _siblings(col, stage))
    ids = (first, learned, foreign)
    before = _snapshots(client, ids)
    page = client.get("/app/edit/1/front")
    row = _region(page, "deck-cards").rows[int(nid)]
    assert "learned" in " ".join(row).lower()
    loaded = _load(client, nid)
    assert loaded.status_code == 200 and _has_region(loaded, "edit-warning")

    response = _commit(
        client,
        nid,
        {"front": "Changed", "back": "Answer", "hint": "Hint", "example": "Example"},
        claimed_learned=False,
    )
    assert response.status_code == 200
    assert _has_region(response, "progress-reset-notice")
    assert not _has_region(response, "edit-warning")
    _assert_count(response, 0, 1)
    after = _snapshots(client, ids)
    for cid in (first, learned):
        fields, history = after[cid]
        assert fields[0] == 0 and fields[5:] == (0, 0)
        old_history = before[cid][1]
        assert all(row in history for row in old_history)
        added = [row for row in history if row not in old_history]
        assert len(added) == 1 and added[0][-1] == 4
    assert after[foreign] == before[foreign]
    assert not _has_region(_load(client, nid), "edit-warning")


@pytest.mark.parametrize("stage", ["learning", "review"])
def test_unchanged_learned_note_and_cancel_preserve_schedule_and_history(
    client: TestClient, stage: str
) -> None:
    nid, first, learned, foreign = _run(client, lambda col: _siblings(col, stage))
    ids = (first, learned, foreign)
    before = _snapshots(client, ids)
    assert _has_region(_load(client, nid), "edit-warning")
    # Returning to the new-card editor without posting a commit is cancellation.
    assert client.get("/app/edit/1/front").status_code == 200
    assert _snapshots(client, ids) == before

    response = _commit(
        client,
        nid,
        {"front": "Original", "back": "Answer", "hint": "Hint", "example": "Example"},
    )
    assert response.status_code == 200
    assert not _has_region(response, "progress-reset-notice")
    assert _snapshots(client, ids) == before


def test_changed_unlearned_note_ignores_learned_cards_in_another_deck(
    client: TestClient,
) -> None:
    nid, first, second, foreign = _run(client, lambda col: _siblings(col, None))
    ids = (first, second, foreign)
    before = _snapshots(client, ids)
    page = client.get("/app/edit/1/front")
    row = _region(page, "deck-cards").rows[int(nid)]
    assert "learned" not in " ".join(row).lower()
    assert not _has_region(_load(client, nid), "edit-warning")
    other_deck = _run(client, lambda col: col.get_card(foreign).did)
    assert _has_region(_load(client, nid, other_deck), "edit-warning")

    response = _commit(
        client,
        nid,
        {
            "front": "Changed unlearned",
            "back": "Answer",
            "hint": "Hint",
            "example": "Example",
        },
        claimed_learned=True,
    )
    assert response.status_code == 200
    assert not _has_region(response, "progress-reset-notice")
    assert _snapshots(client, ids) == before


def _assert_edit_page(
    response: _Response,
    view: str,
    card: int = 0,
    fields: dict[str, str] | None = None,
    learned: bool = False,
) -> dict[str, str | None]:
    assert response.status_code == 200
    attributes = _region(response, "add-wizard").attributes
    assert attributes["data-initial-view"] == view
    assert attributes["data-initial-card"] == str(card)
    _assert_form(
        response,
        card,
        fields
        if fields is not None
        else dict.fromkeys(("front", "back", "hint", "example"), ""),
        learned=learned,
    )
    signals = attributes["data-signals"]
    assert signals is not None
    assert f"_browsing: {str(view == 'cards').lower()}" in signals
    return attributes


@pytest.mark.parametrize(
    ("path", "view"),
    [
        ("front", "editor"),
        ("cards", "cards"),
    ],
)
def test_edit_url_initial_view(client: TestClient, path: str, view: str) -> None:
    page = client.get(f"/app/edit/1/{path}")
    _assert_edit_page(page, view)


@pytest.mark.parametrize(
    ("step", "number"), [("front", "1"), ("back", "2"), ("preview", "3")]
)
def test_edit_url_loads_plain_text_card_and_original_values(
    client: TestClient, step: str, number: str
) -> None:
    values = {
        "front": (
            'Front 😀 <script>alert("x")</script>\n& more " autofocus onfocus="alert(1)'
        ),
        "back": 'Back "quoted"',
        "hint": "Hint & help 🐕",
        "example": "Example\n*word* 🎉",
    }
    nid = _run(
        client,
        lambda col: add_vocab_note(
            col,
            DEFAULT_DECK,
            values["front"],
            values["back"],
            values["hint"],
            values["example"],
        ),
    )
    page = client.get(f"/app/edit/1/cards/{nid}/{step}")
    attributes = _assert_edit_page(page, "card", nid, values)
    assert _region(page, "edit-step").attributes["data-step"] == number
    assert "autofocus" not in attributes
    assert "onfocus" not in attributes
    assert "<script>alert" not in page.text
    response = _load(client, nid)
    assert response.status_code == 200
    _assert_form(response, nid, values)


def test_edit_url_learned_status_matches_selected_deck(client: TestClient) -> None:
    nid, _, _, foreign = _run(client, lambda col: _siblings(col, "review", None))
    other_deck = _run(client, lambda col: col.get_card(foreign).did)
    for deck, learned in ((DEFAULT_DECK, True), (other_deck, False)):
        page = client.get(f"/app/edit/{deck}/cards/{nid}/front")
        attributes = _assert_edit_page(
            page,
            "card",
            nid,
            {
                "front": "Original",
                "back": "Answer",
                "hint": "Hint",
                "example": "Example",
            },
            learned,
        )
        assert attributes["data-deck-id"] == str(deck)
        response = _load(client, nid, deck)
        assert response.status_code == 200
        assert _has_region(response, "edit-warning") is learned


@pytest.mark.parametrize(
    "card", ["nope", "0", "-1", "9223372036854775808", "999999999"]
)
def test_edit_url_invalid_card_opens_plain_editor(
    client: TestClient, card: str
) -> None:
    url = f"/app/edit/1/cards/{card}/front"
    redirect = client.get(url, follow_redirects=False)
    assert redirect.status_code == 303
    assert redirect.headers["location"] == "/app/edit/1/front"
    page = client.get(url)
    _assert_edit_page(page, "editor")


def test_edit_url_rejects_foreign_unsupported_and_deleted_notes(
    client: TestClient,
) -> None:
    def seed(col: anki.collection.Collection) -> tuple[NoteId, NoteId, NoteId]:
        other = col.decks.id("Foreign deck")
        model = col.models.by_name("Basic")
        assert other is not None and model is not None
        foreign = add_vocab_note(col, other, "Foreign vocabulary", "Answer")
        basic = col.new_note(model)
        basic["Front"], basic["Back"] = "Unsupported type", "Answer"
        col.add_note(basic, DEFAULT_DECK)
        deleted = add_vocab_note(col, DEFAULT_DECK, "Deleted", "Answer")
        col.remove_notes([deleted])
        return foreign, basic.id, deleted

    foreign, basic, deleted = _run(client, seed)
    for nid in (foreign, basic, deleted):
        assert _load(client, nid).status_code == 404
        url = f"/app/edit/1/cards/{nid}/front"
        redirect = client.get(url, follow_redirects=False)
        assert redirect.status_code == 303
        assert redirect.headers["location"] == "/app/edit/1/front"
        page = client.get(url)
        _assert_edit_page(page, "editor")
