from __future__ import annotations

import pytest
from anki.cards import CardId
from anki.collection import Collection  # Initialize before importing anki.cards.
from anki.decks import DeckId
from anki.notes import NoteId
from anki.scheduler.v3 import Scheduler
from anki.scheduler_pb2 import CardAnswer

from ankiweb.core.app_client.deck_notes import (
    DeckNote,
    NoteNotEditable,
    deck_notes,
    editable_deck_note,
    is_learned,
)
from ankiweb.core.app_client.vocab import VocabFields, add_vocab_note

SELECTED = DeckId(1)
SIBLING_FIELDS = VocabFields(
    "Original <front>", "Answer & more", "Hint\nline", "Example"
)


def _answer(col: Collection, cid: CardId, rating: CardAnswer.Rating.V) -> None:
    card = col.get_card(cid)
    card.start_timer()
    states = col._backend.get_scheduling_states(cid)
    sched = col.sched
    assert isinstance(sched, Scheduler)
    sched.answer_card(sched.build_answer(card=card, states=states, rating=rating))


def _learn(col: Collection, cid: CardId, stage: str) -> None:
    # Use the same real scheduler transitions as the edit-deck behavior tests.
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
    assert col.get_card(cid).type == (1 if stage == "learning" else 2)


def _siblings(
    col: Collection, selected_stage: str | None, other_stage: str | None
) -> tuple[DeckId, NoteId, CardId, CardId, CardId]:
    other = col.decks.id("Other deck")
    assert other is not None
    nid = add_vocab_note(
        col,
        SELECTED,
        SIBLING_FIELDS.front,
        SIBLING_FIELDS.back,
        SIBLING_FIELDS.hint,
        SIBLING_FIELDS.example,
    )
    first = col.get_note(nid).cards()[0].id
    second_nid = add_vocab_note(col, SELECTED, "Selected sibling", "Answer")
    second = col.get_note(second_nid).cards()[0].id
    foreign_nid = add_vocab_note(col, other, "Foreign sibling", "Answer")
    foreign = col.get_note(foreign_nid).cards()[0].id
    if selected_stage is not None:
        _learn(col, second, selected_stage)
    if other_stage is not None:
        _learn(col, foreign, other_stage)
    # Vocab supports one template; attach real scheduler-created donor cards to
    # the same note, keeping ord 0 and leaving the donor notes without cards.
    assert col.db is not None
    col.db.execute("UPDATE cards SET nid = ? WHERE id IN (?, ?)", nid, second, foreign)
    return other, nid, first, second, foreign


@pytest.mark.parametrize(
    ("card_types", "expected"),
    [
        ([], False),
        ([0], False),
        ([0, 0, 0], False),
        ([1], True),
        ([2], True),
        ([3], True),
        ([0, 1, 0], True),
        ([2, 0], True),
        ([-1], True),
    ],
)
def test_is_learned_requires_any_nonzero_type(
    card_types: list[int], expected: bool
) -> None:
    assert is_learned(card_types) is expected


def test_deck_notes_filters_and_orders_notes_with_plain_text_fields(
    temp_collection: Collection,
) -> None:
    col = temp_collection
    other = col.decks.id("Other deck")
    assert other is not None
    assert deck_notes(col, SELECTED) == []

    older_fields = VocabFields("Älter < & >", "back\nline", "hint & text", "*example*")
    older = add_vocab_note(
        col,
        SELECTED,
        older_fields.front,
        older_fields.back,
        older_fields.hint,
        older_fields.example,
    )
    moved = add_vocab_note(col, SELECTED, "Moved elsewhere", "Answer")
    col.set_deck([card.id for card in col.get_note(moved).cards()], other)
    newest_fields = VocabFields("Newer", "answer <b> &", "", "second\nline")
    newest = add_vocab_note(
        col,
        SELECTED,
        newest_fields.front,
        newest_fields.back,
        newest_fields.hint,
        newest_fields.example,
    )
    foreign = add_vocab_note(col, other, "Only in another deck", "Answer")
    basic_model = col.models.by_name("Basic")
    assert basic_model is not None
    basic = col.new_note(basic_model)
    basic["Front"], basic["Back"] = "Basic note", "Answer"
    col.add_note(basic, SELECTED)

    assert newest > older
    assert deck_notes(col, SELECTED) == [
        DeckNote(newest, newest_fields, False),
        DeckNote(older, older_fields, False),
    ]
    assert [note.nid for note in deck_notes(col, other)] == [foreign, moved]


@pytest.mark.parametrize(
    ("selected_stage", "other_stage", "selected_learned", "other_learned"),
    [
        (None, None, False, False),
        (None, "review", False, True),
        ("learning", None, True, False),
        ("review", None, True, False),
        ("review", "review", True, True),
    ],
)
def test_learned_and_editable_cards_are_scoped_to_the_selected_deck(
    temp_collection: Collection,
    selected_stage: str | None,
    other_stage: str | None,
    selected_learned: bool,
    other_learned: bool,
) -> None:
    col = temp_collection
    other, nid, first, second, foreign = _siblings(col, selected_stage, other_stage)
    assert col.get_card(first).type == 0
    assert col.get_card(second).type == (
        0 if selected_stage is None else 1 if selected_stage == "learning" else 2
    )
    assert col.get_card(foreign).type == (0 if other_stage is None else 2)

    selected_note = DeckNote(nid, SIBLING_FIELDS, selected_learned)
    foreign_note = DeckNote(nid, SIBLING_FIELDS, other_learned)
    assert deck_notes(col, SELECTED) == [selected_note]
    assert deck_notes(col, other) == [foreign_note]
    editable, selected_ids = editable_deck_note(col, SELECTED, nid)
    assert editable == selected_note
    assert len(selected_ids) == 2
    assert set(selected_ids) == {first, second}
    editable, foreign_ids = editable_deck_note(col, other, nid)
    assert editable == foreign_note
    assert foreign_ids == [foreign]


def test_learned_uses_card_type_not_queue(temp_collection: Collection) -> None:
    col = temp_collection
    other, nid, first, second, foreign = _siblings(col, "review", None)
    assert col.db is not None
    # Suspended cards have a negative queue regardless of their learning state.
    col.db.execute(
        "UPDATE cards SET queue = -1 WHERE id IN (?, ?, ?)", first, second, foreign
    )
    assert deck_notes(col, SELECTED) == [DeckNote(nid, SIBLING_FIELDS, True)]
    assert deck_notes(col, other) == [DeckNote(nid, SIBLING_FIELDS, False)]
    assert editable_deck_note(col, SELECTED, nid)[0].learned is True
    assert editable_deck_note(col, other, nid)[0].learned is False


@pytest.mark.parametrize("nid", [-1, 0, 2**63, 2**63 + 1, 2**63 - 1])
def test_editable_note_rejects_out_of_range_or_missing_id(
    temp_collection: Collection, nid: int
) -> None:
    with pytest.raises(NoteNotEditable):
        editable_deck_note(temp_collection, SELECTED, nid)


def test_editable_note_rejects_deleted_foreign_and_non_vocab_notes(
    temp_collection: Collection,
) -> None:
    col = temp_collection
    other = col.decks.id("Other deck")
    basic_model = col.models.by_name("Basic")
    assert other is not None and basic_model is not None
    foreign = add_vocab_note(col, other, "Foreign", "Answer")
    basic = col.new_note(basic_model)
    basic["Front"], basic["Back"] = "Basic", "Answer"
    col.add_note(basic, SELECTED)
    deleted = add_vocab_note(col, SELECTED, "Deleted", "Answer")
    col.remove_notes([deleted])

    for nid in (foreign, basic.id, deleted):
        with pytest.raises(NoteNotEditable):
            editable_deck_note(col, SELECTED, nid)
