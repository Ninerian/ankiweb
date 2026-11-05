import logging
import time

import pytest
from anki.cards import CardId
from anki.collection import Collection
from anki.decks import DeckId
from anki.scheduler.v3 import QueuedCards

from ankiweb.core.app_client import study
from ankiweb.core.app_client.study import (
    QueueCounts,
    StaleCard,
    StudySession,
    answer,
    fetch_next,
)


def add_cards(
    col: Collection, count: int, deck: str = "Study"
) -> tuple[DeckId, list[CardId]]:
    deck_id = col.decks.id(deck)
    assert deck_id is not None
    model = col.models.by_name("Basic")
    assert model is not None
    card_ids = []
    for i in range(count):
        note = col.new_note(model)
        note["Front"] = f"Question {i}"
        note["Back"] = f"Answer {i}"
        col.add_note(note, deck_id)
        card_ids.append(note.cards()[0].id)
    return deck_id, card_ids


def test_queue_counts_maps_all_fields():
    queued = QueuedCards(new_count=3, learning_count=4, review_count=5)
    assert QueueCounts.from_queue(queued) == QueueCounts(3, 4, 5)


def test_five_new_cards_follow_creation_order_and_counts(temp_collection):
    col = temp_collection
    deck_id, card_ids = add_cards(col, 5)
    session = StudySession()
    for i, card_id in enumerate(card_ids):
        view = fetch_next(col, session, deck_id)
        assert view is not None
        assert view.card_id == card_id
        assert view.deck == "Study"
        assert f"Question {i}" in view.question_html
        assert f"Answer {i}" in view.answer_html
        assert view.counts == QueueCounts(new=5 - i, learning=0, review=0)
        answer(col, session, card_id, 4)
    assert fetch_next(col, session, deck_id) is None


@pytest.mark.parametrize("ease", [1, 2])
def test_again_and_hard_requeue_as_learning(temp_collection, ease):
    col = temp_collection
    deck_id, card_ids = add_cards(col, 2)
    session = StudySession()
    first = fetch_next(col, session, deck_id)
    assert first is not None
    answer(col, session, first.card_id, ease)

    next_view = fetch_next(col, session, deck_id)
    assert next_view is not None
    assert next_view.counts == QueueCounts(new=1, learning=1, review=0)
    answer(col, session, next_view.card_id, 4)
    returning = fetch_next(col, session, deck_id)
    assert returning is not None
    assert returning.card_id == card_ids[0]
    assert returning.counts == QueueCounts(new=0, learning=1, review=0)
    answer(col, session, returning.card_id, 4)
    assert col.get_card(returning.card_id).reps == 2


def test_queue_and_deck_tree_use_their_respective_learning_fields(temp_collection):
    col = temp_collection
    deck_id, _ = add_cards(col, 2)
    session = StudySession()
    first = fetch_next(col, session, deck_id)
    assert first is not None
    answer(col, session, first.card_id, 1)
    view = fetch_next(col, session, deck_id)
    assert view is not None
    assert view.counts == QueueCounts(new=1, learning=1, review=0)
    tree = col.sched.deck_due_tree()
    assert tree is not None
    node = next(child for child in tree.children if child.deck_id == deck_id)
    assert (node.new_count, node.learn_count, node.review_count) == (1, 1, 0)


@pytest.mark.parametrize("ease", [0, 5])
def test_invalid_ease_preserves_in_flight_card(temp_collection, ease):
    col = temp_collection
    deck_id, _ = add_cards(col, 1)
    session = StudySession()
    view = fetch_next(col, session, deck_id)
    assert view is not None
    before = (session.card, session.states, session.context, session._card_snapshot)
    with pytest.raises(ValueError):
        answer(col, session, view.card_id, ease)
    assert (
        session.card,
        session.states,
        session.context,
        session._card_snapshot,
    ) == before
    answer(col, session, view.card_id, 4)


def test_stale_id_and_duplicate_answer_preserve_session(temp_collection):
    col = temp_collection
    deck_id, _ = add_cards(col, 1)
    session = StudySession()
    with pytest.raises(StaleCard):
        answer(col, session, 123, 4)
    view = fetch_next(col, session, deck_id)
    assert view is not None
    before = (session.card, session.states, session.context, session._card_snapshot)
    with pytest.raises(StaleCard):
        answer(col, session, view.card_id + 1, 4)
    assert (
        session.card,
        session.states,
        session.context,
        session._card_snapshot,
    ) == before
    answer(col, session, view.card_id, 4)
    with pytest.raises(StaleCard):
        answer(col, session, view.card_id, 4)


def test_stale_answer_in_another_session_preserves_undo(temp_collection, monkeypatch):
    col = temp_collection
    deck_id, card_ids = add_cards(col, 1)
    card_id = card_ids[0]
    first_session = StudySession()
    stale_session = StudySession()
    first = fetch_next(col, first_session, deck_id)
    stale = fetch_next(col, stale_session, deck_id)
    assert first is not None
    assert stale is not None
    assert first.card_id == stale.card_id == card_id
    assert stale_session.card is not None
    assert stale_session.states is not None
    assert stale_session.context is not None
    initial_reps = stale_session.card.reps
    initial_reviews = col.db.scalar("select count() from revlog where cid = ?", card_id)

    answer(col, first_session, card_id, 4)
    assert col.get_card(card_id).reps == initial_reps + 1
    assert col.db.scalar("select count() from revlog where cid = ?", card_id) == (
        initial_reviews + 1
    )
    undo_status = col.undo_status()
    assert undo_status.undo

    before = (stale_session.card, stale_session.states, stale_session.context)
    with pytest.raises(ValueError):
        answer(col, stale_session, card_id, 0)
    assert (stale_session.card, stale_session.states, stale_session.context) == before

    def unexpected_build_answer(**kwargs):
        pytest.fail("Stale answer reached build_answer")

    monkeypatch.setattr(col.sched, "build_answer", unexpected_build_answer)
    with pytest.raises(StaleCard):
        answer(col, stale_session, card_id, 4)
    assert stale_session.card is None
    assert stale_session.states is None
    assert stale_session.context is None
    assert stale_session._card_snapshot is None
    assert col.undo_status() == undo_status
    assert col.get_card(card_id).reps == initial_reps + 1
    assert col.db.scalar("select count() from revlog where cid = ?", card_id) == (
        initial_reviews + 1
    )

    col.undo()
    assert col.get_card(card_id).reps == initial_reps
    assert col.db.scalar("select count() from revlog where cid = ?", card_id) == (
        initial_reviews
    )


@pytest.mark.parametrize("same_mod_and_usn", [False, True])
def test_external_reschedule_rejects_stale_answer_and_preserves_undo(
    temp_collection, monkeypatch, same_mod_and_usn
):
    col = temp_collection
    deck_id, card_ids = add_cards(col, 1)
    card_id = card_ids[0]
    session = StudySession()
    view = fetch_next(col, session, deck_id)
    assert view is not None
    assert view.card_id == card_id
    assert session.card is not None
    assert session.states is not None
    assert session.context is not None
    assert session._card_snapshot is not None
    before = col.db.first(
        "select mod, usn, type, queue, due, reps from cards where id = ?", card_id
    )
    assert before is not None
    assert before[5] == session.card.reps == 0

    col.sched.set_due_date([card_id], "0")
    after = col.db.first(
        "select mod, usn, type, queue, due, reps from cards where id = ?", card_id
    )
    assert after is not None
    assert after[5] == before[5]
    assert after[2:5] != before[2:5]
    undo_status = col.undo_status()
    assert undo_status.undo == "Set Due Date"

    if same_mod_and_usn:
        # Simulate the timestamp/usn collision even if execution crosses a second.
        session._card_snapshot = (
            after[0],
            after[1],
            *session._card_snapshot[2:],
        )
        assert session._card_snapshot[:2] == tuple(after[:2])

    def unexpected_build_answer(**kwargs):
        pytest.fail("Rescheduled card reached build_answer")

    monkeypatch.setattr(col.sched, "build_answer", unexpected_build_answer)
    with pytest.raises(StaleCard):
        answer(col, session, card_id, 4)
    assert session.card is None
    assert session.states is None
    assert session.context is None
    assert session._card_snapshot is None
    assert col.undo_status() == undo_status
    assert (
        col.db.first(
            "select mod, usn, type, queue, due, reps from cards where id = ?", card_id
        )
        == after
    )

    col.undo()
    restored = col.db.first(
        "select type, queue, due, reps from cards where id = ?", card_id
    )
    assert restored == before[2:]


@pytest.mark.parametrize(
    "update_sql",
    [
        "update cards set mod = mod + 1 where id = ?",
        "update cards set usn = usn + 1 where id = ?",
        "update cards set due = due + 1 where id = ?",
        "update cards set ivl = ivl + 1 where id = ?",
        'update cards set data = \'{"cd":{"x":1}}\' where id = ?',
    ],
)
def test_persisted_card_field_changes_reject_stale_answer(
    temp_collection, monkeypatch, update_sql
):
    col = temp_collection
    deck_id, card_ids = add_cards(col, 1)
    session = StudySession()
    view = fetch_next(col, session, deck_id)
    assert view is not None
    col.db.execute(update_sql, card_ids[0])

    def unexpected_build_answer(**kwargs):
        pytest.fail("Changed card reached build_answer")

    monkeypatch.setattr(col.sched, "build_answer", unexpected_build_answer)
    with pytest.raises(StaleCard):
        answer(col, session, view.card_id, 4)
    assert session.card is None
    assert session.states is None
    assert session.context is None
    assert session._card_snapshot is None


def test_deleted_card_answer_clears_session_and_preserves_undo(temp_collection):
    col = temp_collection
    deck_id, card_ids = add_cards(col, 1)
    session = StudySession()
    view = fetch_next(col, session, deck_id)
    assert view is not None
    assert view.card_id == card_ids[0]
    assert session.card is not None
    assert session.states is not None
    assert session.context is not None
    col.remove_notes([session.card.nid])
    assert col.db.scalar("select reps from cards where id = ?", view.card_id) is None
    undo_status = col.undo_status()
    assert undo_status.undo

    with pytest.raises(StaleCard):
        answer(col, session, view.card_id, 4)
    assert session.card is None
    assert session.states is None
    assert session.context is None
    assert session._card_snapshot is None
    assert col.undo_status() == undo_status

    col.undo()
    assert col.get_card(card_ids[0]).id == card_ids[0]


def test_stale_answer_then_serves_next_card(temp_collection):
    col = temp_collection
    deck_id, card_ids = add_cards(col, 2)
    first_session = StudySession()
    second_session = StudySession()
    first = fetch_next(col, first_session, deck_id)
    second = fetch_next(col, second_session, deck_id)
    assert first is not None
    assert second is not None
    assert first.card_id == second.card_id == card_ids[0]

    answer(col, first_session, first.card_id, 4)
    with pytest.raises(StaleCard):
        answer(col, second_session, second.card_id, 4)
    assert (second_session.card, second_session.states, second_session.context) == (
        None,
        None,
        None,
    )
    next_view = fetch_next(col, second_session, deck_id)
    assert next_view is not None
    assert next_view.card_id == card_ids[1]


def test_deleted_card_answer_then_serves_next_card(temp_collection):
    col = temp_collection
    deck_id, card_ids = add_cards(col, 2)
    session = StudySession()
    view = fetch_next(col, session, deck_id)
    assert view is not None
    assert session.card is not None
    col.remove_notes([session.card.nid])

    with pytest.raises(StaleCard):
        answer(col, session, view.card_id, 4)
    assert (session.card, session.states, session.context) == (None, None, None)
    next_view = fetch_next(col, session, deck_id)
    assert next_view is not None
    assert next_view.card_id == card_ids[1]


@pytest.mark.parametrize("ease", [1, 2, 3, 4])
def test_answer_records_the_requested_rating(temp_collection, ease):
    col = temp_collection
    deck_id, _ = add_cards(col, 1)
    session = StudySession()
    view = fetch_next(col, session, deck_id)
    assert view is not None
    answer(col, session, view.card_id, ease)
    assert col.db.scalar("select ease from revlog order by id desc limit 1") == ease


def test_answer_records_elapsed_time_in_revlog(temp_collection):
    col = temp_collection
    deck_id, _ = add_cards(col, 1)
    session = StudySession()
    view = fetch_next(col, session, deck_id)
    assert view is not None
    time.sleep(0.05)
    answer(col, session, view.card_id, 4)
    assert col.db.scalar("select time from revlog order by id desc limit 1") >= 40


def test_refetch_restarts_timer_for_same_card(temp_collection):
    col = temp_collection
    deck_id, _ = add_cards(col, 1)
    session = StudySession()
    first = fetch_next(col, session, deck_id)
    assert first is not None
    assert session.card is not None
    assert session.card.timer_started is not None
    session.card.timer_started -= 60
    next_view = fetch_next(col, session, deck_id)
    assert next_view is not None
    assert next_view.card_id == first.card_id
    answer(col, session, next_view.card_id, 4)
    assert col.db.scalar("select time from revlog order by id desc limit 1") < 30000


def test_empty_queue_clears_session(temp_collection):
    col = temp_collection
    deck_id, card_ids = add_cards(col, 1)
    session = StudySession()
    assert fetch_next(col, session, deck_id) is not None
    col.sched.bury_cards(card_ids)
    assert fetch_next(col, session, deck_id) is None
    assert session.card is None
    assert session.states is None
    assert session.context is None
    assert session._card_snapshot is None


def test_labels_remove_isolates_and_nbsp(temp_collection, monkeypatch):
    col = temp_collection
    deck_id, _ = add_cards(col, 1)
    monkeypatch.setattr(
        col.sched,
        "describe_next_states",
        lambda states: ["<\u20681\u2069\u00a0min", "2\u00a0min", "3", "4"],
    )
    view = fetch_next(col, StudySession(), deck_id)
    assert view is not None
    assert view.labels == ("<1 min", "2 min", "3", "4")


def test_rendered_html_is_sanitized_and_audio_removed(
    temp_collection, caplog, monkeypatch
):
    col = temp_collection
    deck_id = col.decks.id("Study")
    assert deck_id is not None
    model = col.models.by_name("Basic")
    assert model is not None
    model["css"] = ""
    col.models.update_dict(model)
    note = col.new_note(model)
    note["Front"] = "<b>safe</b><script>alert(1)</script>[sound:front.mp3]"
    note["Back"] = '<img src="javascript:alert(2)">[sound:back.mp3]'
    col.add_note(note, deck_id)
    inputs = []
    sanitize = study.sanitize_html

    def capture(content: str) -> str:
        inputs.append(content)
        return sanitize(content)

    monkeypatch.setattr(study, "sanitize_html", capture)
    session = StudySession()
    with caplog.at_level(logging.DEBUG, logger="ankiweb.core.app_client.study"):
        view = fetch_next(col, session, deck_id)
    assert view is not None
    assert session.card is not None
    assert session.card.question().startswith("<style></style>")
    assert len(inputs) == 2
    assert all(not value.startswith("<style></style>") for value in inputs)
    assert all("[anki:play:" not in value for value in inputs)
    assert view.question_html.startswith("<b>safe</b>")
    assert "<style" not in view.question_html
    assert "<script" not in view.question_html
    assert "alert(1)" not in view.question_html
    assert "javascript:" not in view.answer_html
    assert "[anki:play:" not in view.question_html
    assert "[anki:play:" not in view.answer_html
    assert any("audio" in record.message.lower() for record in caplog.records)
