import json
from collections.abc import Callable
from typing import cast

import pytest
from anki.cards import CardId
from anki.collection import Collection
from anki.collection_pb2 import OpChanges
from anki.notes import Note, NoteId
from anki.scheduler.v3 import Scheduler
from anki.scheduler_pb2 import CardAnswer
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from starlette.websockets import WebSocketDisconnect

from ankiweb.core.app_client.vocab import VocabFields, escape_field
from ankiweb.core.op_changes import op_changes_to_flags

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
_JOURNAL = "ankiweb_pending_progress_resets"


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


def test_disconnected_socket_does_not_interrupt_editor_broadcast(
    client: TestClient,
) -> None:
    class DisconnectedSocket:
        sends = 0

        async def send_json(self, message: dict[str, object]) -> None:
            self.sends += 1
            raise WebSocketDisconnect(code=1006)

    class HealthySocket:
        def __init__(self) -> None:
            self.messages: list[dict[str, object]] = []

        async def send_json(self, message: dict[str, object]) -> None:
            self.messages.append(message)

    assert client.get("/app/edit?deck=1").status_code == 200
    broken = DisconnectedSocket()
    healthy = HealthySocket()
    hub = cast(FastAPI, client.app).state.hub
    hub.register("reviewer", broken)
    hub.register("reviewer", healthy)

    response = client.post("/app/edit/commit?deck=1", json=_ORIGINAL)

    signals = _signals(response)
    assert signals["count"] == 1
    assert signals["error"] == ""
    assert broken.sends == 1
    assert len(healthy.messages) == 1
    message = healthy.messages[0]
    assert message["type"] == "opchanges"
    assert message["initiator"] == "app"
    flags = message["flags"]
    assert isinstance(flags, dict)
    assert flags["note"] is True
    assert flags["card"] is True

    def saved(col: Collection) -> list[list[str]]:
        return [
            [col.get_note(nid)[name.capitalize()] for name in _FIELDS]
            for nid in col.find_notes("")
        ]

    assert _run(client, saved) == [[escape_field(_ORIGINAL[key]) for key in _FIELDS]]


def _record_note_changes(monkeypatch: pytest.MonkeyPatch) -> list[OpChanges]:
    original = Collection.update_note
    recorded: list[OpChanges] = []

    def update(
        self: Collection, note: Note, skip_undo_entry: bool = False
    ) -> OpChanges:
        changes = original(self, note, skip_undo_entry=skip_undo_entry)
        recorded.append(changes)
        return changes

    monkeypatch.setattr(Collection, "update_note", update)
    return recorded


def _assert_pending_marker(client: TestClient, nid: NoteId) -> None:
    marker = [1, nid, VocabFields.from_mapping(_ORIGINAL).fingerprint()]
    assert _run(client, lambda col: col.get_config(_JOURNAL)) == [marker]


@pytest.mark.parametrize(
    "partial", [False, True], ids=["before-reset", "partial-reset"]
)
def test_scheduler_failure_broadcasts_persisted_changes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, partial: bool
) -> None:
    nid, cid = _seed_learned(client)
    before = _snapshot(client, nid, cid)
    note_changes = _record_note_changes(monkeypatch)
    scheduler_class = _run(client, lambda col: type(col.sched))
    original_reset = scheduler_class.schedule_cards_as_new
    calls: list[tuple[list[CardId], bool]] = []

    def fail(self: Scheduler, card_ids: list[CardId], *, reset_counts: bool) -> None:
        assert self.col.get_config(_JOURNAL) == [
            [1, nid, VocabFields.from_mapping(_ORIGINAL).fingerprint()]
        ]
        calls.append((card_ids, reset_counts))
        if partial:
            original_reset(self, card_ids, reset_counts=reset_counts)
        raise RuntimeError("deterministic scheduler failure")

    monkeypatch.setattr(scheduler_class, "schedule_cards_as_new", fail)
    events: list[tuple[dict[str, bool], str | None]] = []
    cast(FastAPI, client.app).state.service.subscribe(
        lambda flags, initiator: events.append((flags, initiator))
    )

    response = client.post("/app/edit/commit?deck=1", json={**_UPDATED, "nid": nid})

    assert _signals(response) == {
        "error": (
            "The note text was saved, but learning progress was not reset. "
            "Please try saving again."
        )
    }
    assert "datastar-patch-elements" not in response.text
    assert calls == [([cid], True)]
    assert len(note_changes) == 1
    assert len(events) == 1
    flags, initiator = events[0]
    assert initiator == "app"
    assert flags["note"] is True
    for name, changed in op_changes_to_flags(note_changes[0]).items():
        if changed:
            assert flags[name] is True
    fields, schedule = _snapshot(client, nid, cid)
    assert fields == [escape_field(_UPDATED[key]) for key in _FIELDS]
    if partial:
        assert schedule[:2] == (0, 0)
        assert schedule[-2:] == (0, 0)
        assert flags["card"] is True
        assert flags["study_queues"] is True
        assert flags["browser_table"] is True
    else:
        assert schedule == before[1]
    _assert_pending_marker(client, nid)


def test_journal_clear_failure_broadcasts_note_and_reset_changes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    nid, cid = _seed_learned(client)
    note_changes = _record_note_changes(monkeypatch)
    scheduler_class = _run(client, lambda col: type(col.sched))
    original_reset = scheduler_class.schedule_cards_as_new
    reset_changes: list[OpChanges] = []
    calls: list[tuple[list[CardId], bool]] = []

    def reset(
        self: Scheduler, card_ids: list[CardId], *, reset_counts: bool
    ) -> OpChanges:
        calls.append((card_ids, reset_counts))
        changes = original_reset(self, card_ids, reset_counts=reset_counts)
        reset_changes.append(changes)
        return changes

    original_set_config = Collection.set_config

    def reject_clear(
        self: Collection, key: str, value: object, *, undoable: bool = False
    ) -> object:
        if key == _JOURNAL and value == []:
            raise RuntimeError("deterministic journal clear failure")
        return original_set_config(self, key, value, undoable=undoable)

    monkeypatch.setattr(scheduler_class, "schedule_cards_as_new", reset)
    monkeypatch.setattr(Collection, "set_config", reject_clear)
    events: list[tuple[dict[str, bool], str | None]] = []
    cast(FastAPI, client.app).state.service.subscribe(
        lambda flags, initiator: events.append((flags, initiator))
    )

    response = client.post("/app/edit/commit?deck=1", json={**_UPDATED, "nid": nid})

    assert _signals(response) == {
        "error": (
            "The note text was saved and learning progress was reset, but the "
            "pending reset could not be cleared. Please contact support."
        )
    }
    assert "datastar-patch-elements" not in response.text
    assert calls == [([cid], True)]
    assert len(note_changes) == len(reset_changes) == len(events) == 1
    expected = OpChanges()
    expected.MergeFrom(note_changes[0])
    expected.MergeFrom(reset_changes[0])
    flags, initiator = events[0]
    assert initiator == "app"
    assert flags == op_changes_to_flags(expected)
    assert flags["note"] is True
    assert flags["card"] is True
    fields, schedule = _snapshot(client, nid, cid)
    assert fields == [escape_field(_UPDATED[key]) for key in _FIELDS]
    assert schedule[:2] == (0, 0)
    assert schedule[-2:] == (0, 0)
    _assert_pending_marker(client, nid)
