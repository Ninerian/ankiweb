from __future__ import annotations

import pytest
from anki.cards import CardId
from anki.collection import Collection
from anki.decks import DeckId
from anki.notes import NoteId
from anki.scheduler.v3 import Scheduler
from anki.scheduler_pb2 import CardAnswer

from ankiweb.core.app_client.note_editing import (
    EditOutcome,
    InvalidFields,
    ProgressResetFailed,
    ProgressResetUncleared,
    ProgressResetUnrecorded,
    edit_deck_note,
)
from ankiweb.core.app_client.vocab import VocabFields, add_vocab_note, read_vocab_note
from ankiweb.core.op_changes import op_changes_to_flags

_DECK = DeckId(1)
_JOURNAL = "ankiweb_pending_progress_resets"
_ORIGINAL = VocabFields("Original", "Answer", "Old hint", "Old example")
_CHANGED = VocabFields("Changed", "New answer", "New hint", "New example")


def _seed(col: Collection, *, learned: bool = True) -> tuple[NoteId, CardId]:
    nid = add_vocab_note(
        col, _DECK, _ORIGINAL.front, _ORIGINAL.back, _ORIGINAL.hint, _ORIGINAL.example
    )
    cid = col.get_note(nid).cards()[0].id
    if learned:
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
    return nid, cid


def _schedule(col: Collection, cid: CardId) -> tuple[int, ...]:
    card = col.get_card(cid)
    return tuple(
        getattr(card, name)
        for name in ("type", "queue", "due", "ivl", "factor", "reps", "lapses")
    )


def _fields(col: Collection, nid: NoteId) -> VocabFields:
    return VocabFields.from_mapping(read_vocab_note(col, nid))


def _reject_journal(monkeypatch: pytest.MonkeyPatch, *, clear: bool) -> RuntimeError:
    original = Collection.set_config
    failure = RuntimeError("deterministic config failure")

    def reject(
        self: Collection, key: str, value: object, *, undoable: bool = False
    ) -> object:
        if key == _JOURNAL and (value == []) == clear:
            raise failure
        return original(self, key, value, undoable=undoable)

    monkeypatch.setattr(Collection, "set_config", reject)
    return failure


def test_vocab_fields_normalize_and_fingerprint_only_crlf() -> None:
    windows = VocabFields.from_mapping(
        {"front": "Hünd\r\nline", "back": "answer", "hint": "a\r\nb", "example": "x\ry"}
    )
    unix = VocabFields("Hünd\nline", "answer", "a\nb", "x\ry")
    expected = ("Hünd\nline", "answer", "a\nb", "x\ry")
    assert windows.normalized() == unix.normalized() == expected
    assert windows.fingerprint() == unix.fingerprint()
    assert (
        unix.fingerprint()
        != VocabFields("Hünd\nline", "answer", "a\nb", "x\ny").fingerprint()
    )


def test_unchanged_learned_note_has_no_changes_or_reset(
    temp_collection: Collection,
) -> None:
    nid, cid = _seed(temp_collection)
    before = _schedule(temp_collection, cid)

    result = edit_deck_note(temp_collection, _DECK, nid, _ORIGINAL)

    assert isinstance(result, EditOutcome)
    assert result.progress_reset is False
    assert not any(op_changes_to_flags(result.changes).values())
    assert _schedule(temp_collection, cid) == before
    assert not temp_collection.get_config(_JOURNAL, [])


def test_unchanged_note_preserves_historical_pending_reset(
    temp_collection: Collection,
) -> None:
    nid, cid = _seed(temp_collection)
    before = _schedule(temp_collection, cid)
    marker = [_DECK, nid, "4e712b93e3da7f1ec333a52483473508"]
    temp_collection.set_config(_JOURNAL, [marker], undoable=False)

    result = edit_deck_note(temp_collection, _DECK, nid, _ORIGINAL)

    assert result.progress_reset is False
    assert not any(op_changes_to_flags(result.changes).values())
    assert _fields(temp_collection, nid) == _ORIGINAL
    assert _schedule(temp_collection, cid) == before
    assert temp_collection.get_config(_JOURNAL) == [marker]


def test_changed_learned_note_resets_and_clears_journal(
    temp_collection: Collection, monkeypatch: pytest.MonkeyPatch
) -> None:
    nid, cid = _seed(temp_collection)
    original_set_config = Collection.set_config
    writes: list[tuple[object, bool]] = []

    def record(
        self: Collection, key: str, value: object, *, undoable: bool = False
    ) -> object:
        if key == _JOURNAL:
            writes.append((value, undoable))
        return original_set_config(self, key, value, undoable=undoable)

    monkeypatch.setattr(Collection, "set_config", record)
    result = edit_deck_note(temp_collection, _DECK, nid, _CHANGED)

    assert result.progress_reset is True
    flags = op_changes_to_flags(result.changes)
    assert flags["note"] and flags["card"]
    assert _fields(temp_collection, nid) == _CHANGED
    after = _schedule(temp_collection, cid)
    assert after[:2] == (0, 0)
    assert after[-2:] == (0, 0)
    assert temp_collection.get_config(_JOURNAL, []) == []
    assert len(writes) == 2
    assert writes[0] == ([[_DECK, nid, _ORIGINAL.fingerprint()]], False)
    assert writes[1] == ([], False)


def test_reset_affects_only_cards_in_selected_deck(temp_collection: Collection) -> None:
    nid, selected = _seed(temp_collection)
    other_deck = temp_collection.decks.id("Other deck")
    assert other_deck is not None
    donor = add_vocab_note(temp_collection, other_deck, "Donor", "Answer")
    foreign = temp_collection.get_note(donor).cards()[0].id
    scheduler = temp_collection.sched
    assert isinstance(scheduler, Scheduler)
    card = temp_collection.get_card(foreign)
    card.start_timer()
    states = temp_collection._backend.get_scheduling_states(foreign)
    scheduler.answer_card(
        scheduler.build_answer(card=card, states=states, rating=CardAnswer.EASY)
    )
    before_foreign = _schedule(temp_collection, foreign)
    assert before_foreign[0] != 0
    assert temp_collection.db is not None
    temp_collection.db.execute("UPDATE cards SET nid = ? WHERE id = ?", nid, foreign)

    result = edit_deck_note(temp_collection, _DECK, nid, _CHANGED)

    assert result.progress_reset is True
    assert _schedule(temp_collection, selected)[:2] == (0, 0)
    assert _schedule(temp_collection, foreign) == before_foreign


def test_changed_new_note_updates_without_reset(temp_collection: Collection) -> None:
    nid, cid = _seed(temp_collection, learned=False)
    before = _schedule(temp_collection, cid)

    result = edit_deck_note(temp_collection, _DECK, nid, _CHANGED)

    assert result.progress_reset is False
    assert op_changes_to_flags(result.changes)["note"]
    assert _fields(temp_collection, nid) == _CHANGED
    assert _schedule(temp_collection, cid) == before
    assert temp_collection.get_config(_JOURNAL, []) == []


def test_crlf_only_edit_preserves_learned_schedule(temp_collection: Collection) -> None:
    nid = add_vocab_note(temp_collection, _DECK, "One\nTwo", "Answer", "a\nb")
    cid = temp_collection.get_note(nid).cards()[0].id
    scheduler = temp_collection.sched
    assert isinstance(scheduler, Scheduler)
    card = temp_collection.get_card(cid)
    card.start_timer()
    states = temp_collection._backend.get_scheduling_states(cid)
    scheduler.answer_card(
        scheduler.build_answer(card=card, states=states, rating=CardAnswer.EASY)
    )
    before = _schedule(temp_collection, cid)
    assert before[0] != 0

    result = edit_deck_note(
        temp_collection, _DECK, nid, VocabFields("One\r\nTwo", "Answer", "a\r\nb", "")
    )

    assert result.progress_reset is False
    assert not any(op_changes_to_flags(result.changes).values())
    assert _schedule(temp_collection, cid) == before
    assert temp_collection.get_config(_JOURNAL, []) == []


def test_none_fields_are_invalid_without_mutation(temp_collection: Collection) -> None:
    nid, cid = _seed(temp_collection)
    before = _schedule(temp_collection, cid)
    with pytest.raises(InvalidFields):
        edit_deck_note(temp_collection, _DECK, nid, None)
    assert _fields(temp_collection, nid) == _ORIGINAL
    assert _schedule(temp_collection, cid) == before
    assert temp_collection.get_config(_JOURNAL, []) == []


def test_scheduler_failure_keeps_marker_and_cause(
    temp_collection: Collection, monkeypatch: pytest.MonkeyPatch
) -> None:
    nid, cid = _seed(temp_collection)
    before = _schedule(temp_collection, cid)
    failure = RuntimeError("deterministic scheduler failure")
    calls: list[tuple[list[CardId], bool]] = []

    def fail(self: Scheduler, card_ids: list[CardId], *, reset_counts: bool) -> None:
        assert self.col.get_config(_JOURNAL) == [[_DECK, nid, _ORIGINAL.fingerprint()]]
        calls.append((card_ids, reset_counts))
        raise failure

    monkeypatch.setattr(type(temp_collection.sched), "schedule_cards_as_new", fail)
    with pytest.raises(ProgressResetFailed) as exc:
        edit_deck_note(temp_collection, _DECK, nid, _CHANGED)
    assert exc.value.__cause__ is failure
    assert calls == [([cid], True)]
    assert _fields(temp_collection, nid) == _CHANGED
    assert _schedule(temp_collection, cid) == before
    assert temp_collection.get_config(_JOURNAL) == [
        [_DECK, nid, _ORIGINAL.fingerprint()]
    ]


def test_retry_after_scheduler_failure_resets_even_without_new_text_changes(
    temp_collection: Collection, monkeypatch: pytest.MonkeyPatch
) -> None:
    nid, cid = _seed(temp_collection)
    failure = RuntimeError("reset failed")

    def fail(self: Scheduler, card_ids: list[CardId], *, reset_counts: bool) -> None:
        raise failure

    with monkeypatch.context() as patch:
        patch.setattr(type(temp_collection.sched), "schedule_cards_as_new", fail)
        with pytest.raises(ProgressResetFailed):
            edit_deck_note(temp_collection, _DECK, nid, _CHANGED)
    assert _fields(temp_collection, nid) == _CHANGED
    assert temp_collection.get_config(_JOURNAL) == [
        [_DECK, nid, _ORIGINAL.fingerprint()]
    ]

    result = edit_deck_note(temp_collection, _DECK, nid, _CHANGED)
    assert result.progress_reset is True
    assert _schedule(temp_collection, cid)[:2] == (0, 0)
    assert temp_collection.get_config(_JOURNAL) == []


@pytest.mark.parametrize(
    "invalid",
    [None, {}, [[True, 1, "digest"]], [[1, False, "digest"]], [[1, 2]], [[1, 2, 3]]],
)
def test_invalid_journal_rejected_without_mutation(
    temp_collection: Collection, invalid: object
) -> None:
    nid, cid = _seed(temp_collection)
    before = _schedule(temp_collection, cid)
    temp_collection.set_config(_JOURNAL, invalid, undoable=False)

    with pytest.raises(ValueError, match="Invalid pending progress reset"):
        edit_deck_note(temp_collection, _DECK, nid, _CHANGED)
    assert _fields(temp_collection, nid) == _ORIGINAL
    assert _schedule(temp_collection, cid) == before


def test_journal_write_failure_precedes_note_update(
    temp_collection: Collection, monkeypatch: pytest.MonkeyPatch
) -> None:
    nid, cid = _seed(temp_collection)
    before = _schedule(temp_collection, cid)
    failure = _reject_journal(monkeypatch, clear=False)

    with pytest.raises(ProgressResetUnrecorded) as exc:
        edit_deck_note(temp_collection, _DECK, nid, _CHANGED)
    assert exc.value.__cause__ is failure
    assert _fields(temp_collection, nid) == _ORIGINAL
    assert _schedule(temp_collection, cid) == before
    assert temp_collection.get_config(_JOURNAL, []) == []


def test_journal_clear_failure_follows_completed_reset(
    temp_collection: Collection, monkeypatch: pytest.MonkeyPatch
) -> None:
    nid, cid = _seed(temp_collection)
    failure = _reject_journal(monkeypatch, clear=True)

    with pytest.raises(ProgressResetUncleared) as exc:
        edit_deck_note(temp_collection, _DECK, nid, _CHANGED)
    assert exc.value.__cause__ is failure
    assert _fields(temp_collection, nid) == _CHANGED
    after = _schedule(temp_collection, cid)
    assert after[:2] == (0, 0)
    assert after[-2:] == (0, 0)
    assert temp_collection.get_config(_JOURNAL) == [
        [_DECK, nid, _ORIGINAL.fingerprint()]
    ]


@pytest.mark.parametrize("capacity", ["entries", "bytes"])
def test_journal_capacity_refuses_without_mutation(
    temp_collection: Collection, capacity: str
) -> None:
    nid, cid = _seed(temp_collection)
    before = _schedule(temp_collection, cid)
    pending = (
        [[2, index, "0" * 32] for index in range(50)]
        if capacity == "entries"
        else [[2, 1, "0" * 4096]]
    )
    temp_collection.set_config(_JOURNAL, pending, undoable=False)

    with pytest.raises(ProgressResetUnrecorded) as exc:
        edit_deck_note(temp_collection, _DECK, nid, _CHANGED)
    assert isinstance(exc.value.__cause__, ValueError)
    assert temp_collection.get_config(_JOURNAL) == pending
    assert _fields(temp_collection, nid) == _ORIGINAL
    assert _schedule(temp_collection, cid) == before
