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


def _signals(response: _TextResponse) -> dict[str, object]:
    for line in response.text.splitlines():
        if line.startswith("data: signals "):
            return cast(
                dict[str, object], json.loads(line.removeprefix("data: signals "))
            )
    raise AssertionError("No Datastar signal patch")


class _Region(HTMLParser):
    """Collect note rows and text inside one stable fragment ID."""

    def __init__(self, html: str, region_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.region_id = region_id
        self.depth = 0
        self.found = False
        self.ids: list[int] = []
        self.text: list[str] = []
        self.rows: dict[int, list[str]] = {}
        self.row: int | None = None
        self.row_depth = 0
        self.has_stamp = False
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if not self.depth:
            if attributes.get("id") != self.region_id or self.found:
                return
            self.found = True
            self.depth = 1
        elif tag not in _VOID_TAGS:
            self.depth += 1
        if "data-ts" in attributes:
            self.has_stamp = True
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
        if self.depth and tag not in _VOID_TAGS:
            if self.row is not None and self.row_depth == self.depth:
                self.row = None
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.text.append(data)
            if self.row is not None:
                self.rows[self.row].append(data)


def _region(response: _TextResponse, region_id: str) -> _Region:
    region = _Region(response.text, region_id)
    assert region.found, f"Missing #{region_id}"
    return region


def _load(client: TestClient, nid: NoteId, deck: DeckId = DEFAULT_DECK) -> _Response:
    return client.post(f"/app/edit/card/{nid}?deck={deck}")


def _commit(
    client: TestClient,
    nid: NoteId,
    values: dict[str, str],
    deck: DeckId = DEFAULT_DECK,
    claimed_learned: bool | None = None,
) -> _Response:
    payload: dict[str, object] = {"nid": nid, **values}
    if claimed_learned is not None:
        payload["learned"] = claimed_learned
    return client.post(f"/app/edit/commit?deck={deck}", json=payload)


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


def test_deck_list_spans_sessions_and_edits_without_growing_pile(
    client: TestClient,
) -> None:
    assert client.get("/app/edit?deck=1").status_code == 200
    prior = client.post(
        "/app/edit/commit?deck=1",
        json={
            "front": "Prior session",
            "back": "Earlier",
            "hint": "Old hint",
            "example": "Old example",
        },
    )
    assert _signals(prior)["count"] == 1
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
    page = client.get("/app/edit?deck=1")
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
        response = client.post(
            "/app/edit/commit?deck=1",
            json={"front": f"Current {index}", "back": f"Current answer {index}"},
        )
        assert response.status_code == 200
        assert _signals(response)["count"] == index + 1
        assert _signals(response)["deckCount"] == 7 + index
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
    signals = _signals(loaded)
    assert {key: signals[key] for key in original} == original
    assert signals["editOriginal"] == original
    assert signals["nid"] == prior_id and signals["step"] == 1
    assert signals["learned"] is False and signals["progressReset"] is False

    updated = {**original, "front": "Updated earlier card"}
    response = _commit(client, prior_id, updated)
    assert response.status_code == 200
    saved_signals = _signals(response)
    assert saved_signals["count"] == 5
    assert saved_signals["deckCount"] == 11
    assert saved_signals["nid"] == 0
    assert saved_signals["progressReset"] is False
    assert saved_signals["learned"] is False
    assert all(saved_signals[key] == "" for key in original)
    assert not _region(response, "added-cards").has_stamp
    assert _region(response, "deck-cards").ids == sorted(
        [prior_id, *existing, *added_ids]
    )
    assert set(_run(client, lambda col: col.find_notes(""))) == before_ids
    assert _signals(_load(client, prior_id))["front"] == updated["front"]


@pytest.mark.parametrize(
    ("lang", "marker", "legend", "warning"),
    [
        (
            "en",
            "Learned",
            "Changing a learned card resets its learning progress.",
            "Changes to this learned card will reset its learning progress.",
        ),
        (
            "de_DE",
            "Gelernt",
            "Änderungen an gelernten Karten setzen den Lernfortschritt zurück.",
            "Änderungen an dieser gelernten Karte setzen den Lernfortschritt zurück.",
        ),
    ],
)
def test_learned_deck_card_is_localized(
    tmp_path: Path, lang: str, marker: str, legend: str, warning: str
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
            page = client.get("/app/edit?deck=1")
            assert page.status_code == 200
            deck = _region(page, "deck-cards")
            assert deck.ids == [nid]
            row = deck.rows[int(nid)]
            assert "Reviewed" in row and "Answer" in row and marker in row
            assert "".join(_region(page, "deck-cards-legend").text).strip() == legend
            assert "".join(_region(page, "edit-warning").text).strip() == warning

            loaded = _load(client, nid)
            assert loaded.status_code == 200
            assert _signals(loaded)["learned"] is True
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
    assert _signals(_load(client, nid))["learned"] is True
    other_deck = _run(client, lambda col: col.get_card(foreign).did)
    assert _signals(_load(client, nid, other_deck))["learned"] is False


@pytest.mark.parametrize("stage", ["learning", "review"])
def test_changed_learned_note_resets_only_selected_deck_and_retains_history(
    client: TestClient, stage: str
) -> None:
    nid, first, learned, foreign = _run(client, lambda col: _siblings(col, stage))
    ids = (first, learned, foreign)
    before = _snapshots(client, ids)
    page = client.get("/app/edit?deck=1")
    row = _region(page, "deck-cards").rows[int(nid)]
    assert "learned" in " ".join(row).lower()
    loaded = _load(client, nid)
    assert loaded.status_code == 200 and _signals(loaded)["learned"] is True

    response = _commit(
        client,
        nid,
        {"front": "Changed", "back": "Answer", "hint": "Hint", "example": "Example"},
        claimed_learned=False,
    )
    assert response.status_code == 200
    assert _signals(response)["progressReset"] is True
    assert _signals(response)["learned"] is False
    assert _signals(response)["count"] == 0
    after = _snapshots(client, ids)
    for cid in (first, learned):
        fields, history = after[cid]
        assert fields[0] == 0 and fields[5:] == (0, 0)
        old_history = before[cid][1]
        assert all(row in history for row in old_history)
        added = [row for row in history if row not in old_history]
        assert len(added) == 1 and added[0][-1] == 4
    assert after[foreign] == before[foreign]
    assert _signals(_load(client, nid))["learned"] is False


@pytest.mark.parametrize("stage", ["learning", "review"])
def test_unchanged_learned_note_and_cancel_preserve_schedule_and_history(
    client: TestClient, stage: str
) -> None:
    nid, first, learned, foreign = _run(client, lambda col: _siblings(col, stage))
    ids = (first, learned, foreign)
    before = _snapshots(client, ids)
    assert _signals(_load(client, nid))["learned"] is True
    # Returning to the new-card editor without posting a commit is cancellation.
    assert client.get("/app/edit?deck=1").status_code == 200
    assert _snapshots(client, ids) == before

    response = _commit(
        client,
        nid,
        {"front": "Original", "back": "Answer", "hint": "Hint", "example": "Example"},
    )
    assert response.status_code == 200
    assert _signals(response)["progressReset"] is False
    assert _snapshots(client, ids) == before


def test_changed_unlearned_note_ignores_learned_cards_in_another_deck(
    client: TestClient,
) -> None:
    nid, first, second, foreign = _run(client, lambda col: _siblings(col, None))
    ids = (first, second, foreign)
    before = _snapshots(client, ids)
    page = client.get("/app/edit?deck=1")
    row = _region(page, "deck-cards").rows[int(nid)]
    assert "learned" not in " ".join(row).lower()
    assert _signals(_load(client, nid))["learned"] is False
    other_deck = _run(client, lambda col: col.get_card(foreign).did)
    assert _signals(_load(client, nid, other_deck))["learned"] is True

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
    assert _signals(response)["progressReset"] is False
    assert _snapshots(client, ids) == before
