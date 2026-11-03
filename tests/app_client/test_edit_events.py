import json
from collections.abc import Callable
from typing import cast

from anki.cards import CardId
from anki.collection import Collection
from anki.notes import NoteId
from anki.scheduler.v3 import Scheduler
from anki.scheduler_pb2 import CardAnswer
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from ankiweb.core.app_client.vocab import escape_field

_ORIGINAL = {
    "front": "Original",
    "back": "Answer",
    "hint": "Old hint",
    "example": "Old example",
}
_UPDATED = {
    "front": "Changed <front>",
    "back": "Changed & answer",
    "hint": "New hint",
    "example": "New *example*",
}
_FIELDS = ("front", "back", "hint", "example")
_SCHEDULE = ("type", "queue", "due", "ivl", "factor", "reps", "lapses")


def _run[T](client: TestClient, fn: Callable[[Collection], T]) -> T:
    assert client.portal is not None
    service = cast(FastAPI, client.app).state.service
    return client.portal.call(service.run, fn)


def _signals(response: Response) -> dict[str, object]:
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    for line in response.text.splitlines():
        if line.startswith("data: signals "):
            return json.loads(line.removeprefix("data: signals "))
    raise AssertionError("No Datastar signal patch")


def _seed_learned(client: TestClient) -> tuple[NoteId, CardId]:
    created = client.post("/app/edit/commit?deck=1", json=_ORIGINAL)
    assert _signals(created)["count"] == 1

    def learn(col: Collection) -> tuple[NoteId, CardId]:
        notes = col.find_notes("")
        assert len(notes) == 1
        nid = notes[0]
        cards = col.get_note(nid).cards()
        assert len(cards) == 1
        cid = cards[0].id
        scheduler = col.sched
        assert isinstance(scheduler, Scheduler)
        for rating in (CardAnswer.EASY, CardAnswer.AGAIN, CardAnswer.EASY):
            card = col.get_card(cid)
            card.start_timer()
            states = col._backend.get_scheduling_states(cid)
            scheduler.answer_card(
                scheduler.build_answer(card=card, states=states, rating=rating)
            )
        card = col.get_card(cid)
        assert card.type == 2 and card.reps > 0 and card.lapses > 0
        assert card.ivl > 0 and card.factor > 0 and card.due > 0
        return nid, cid

    return _run(client, learn)


def _snapshot(
    client: TestClient, nid: NoteId, cid: CardId
) -> tuple[list[str], tuple[int, ...]]:
    def snapshot(col: Collection) -> tuple[list[str], tuple[int, ...]]:
        note = col.get_note(nid)
        card = col.get_card(cid)
        return (
            [note[key.capitalize()] for key in _FIELDS],
            tuple(getattr(card, key) for key in _SCHEDULE),
        )

    return _run(client, snapshot)


def test_changed_learned_note_broadcasts_note_and_card_changes(
    client: TestClient,
) -> None:
    nid, cid = _seed_learned(client)
    events: list[tuple[dict[str, bool], str | None]] = []
    cast(FastAPI, client.app).state.service.subscribe(
        lambda flags, initiator: events.append((flags, initiator))
    )

    response = client.post("/app/edit/commit?deck=1", json={**_UPDATED, "nid": nid})

    signals = _signals(response)
    assert signals["_editSaved"] is True
    assert signals["progressReset"] is True
    assert signals["error"] == ""
    assert len(events) == 1
    flags, initiator = events[0]
    assert initiator == "app"
    assert flags["note"] is True
    assert flags["card"] is True
    fields, schedule = _snapshot(client, nid, cid)
    assert fields == [escape_field(_UPDATED[key]) for key in _FIELDS]
    assert schedule[:2] == (0, 0)
    assert schedule[-2:] == (0, 0)
    assert _run(client, lambda col: col.find_notes("")) == [nid]


def test_unchanged_learned_note_emits_no_event(client: TestClient) -> None:
    nid, cid = _seed_learned(client)
    before = _snapshot(client, nid, cid)
    events: list[tuple[dict[str, bool], str | None]] = []
    cast(FastAPI, client.app).state.service.subscribe(
        lambda flags, initiator: events.append((flags, initiator))
    )

    response = client.post("/app/edit/commit?deck=1", json={**_ORIGINAL, "nid": nid})

    signals = _signals(response)
    assert signals["_editSaved"] is True
    assert signals["progressReset"] is False
    assert signals["error"] == ""
    assert events == []
    assert _snapshot(client, nid, cid) == before
    assert _run(client, lambda col: col.find_notes("")) == [nid]


def test_adding_note_broadcasts_note_changes(client: TestClient) -> None:
    assert client.get("/app/edit?deck=1").status_code == 200
    events: list[tuple[dict[str, bool], str | None]] = []
    cast(FastAPI, client.app).state.service.subscribe(
        lambda flags, initiator: events.append((flags, initiator))
    )

    response = client.post("/app/edit/commit?deck=1", json=_ORIGINAL)

    signals = _signals(response)
    assert signals["count"] == 1
    assert signals["error"] == ""
    assert len(events) == 1
    flags, initiator = events[0]
    assert initiator == "app"
    assert flags["note"] is True
    assert flags["card"] is True

    def saved(col: Collection) -> tuple[list[str], list[int]]:
        notes = col.find_notes("")
        assert len(notes) == 1
        note = col.get_note(notes[0])
        return (
            [note[key.capitalize()] for key in _FIELDS],
            [card.did for card in note.cards()],
        )

    fields, decks = _run(client, saved)
    assert fields == [escape_field(_ORIGINAL[key]) for key in _FIELDS]
    assert decks == [1]
