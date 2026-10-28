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
    before = (session.card, session.states, session.context)
    with pytest.raises(ValueError):
        answer(col, session, view.card_id, ease)
    assert (session.card, session.states, session.context) == before
    answer(col, session, view.card_id, 4)


def test_stale_id_and_duplicate_answer_preserve_session(temp_collection):
    col = temp_collection
    deck_id, _ = add_cards(col, 1)
    session = StudySession()
    with pytest.raises(StaleCard):
        answer(col, session, 123, 4)
    view = fetch_next(col, session, deck_id)
    assert view is not None
    before = (session.card, session.states, session.context)
    with pytest.raises(StaleCard):
        answer(col, session, view.card_id + 1, 4)
    assert (session.card, session.states, session.context) == before
    answer(col, session, view.card_id, 4)
    with pytest.raises(StaleCard):
        answer(col, session, view.card_id, 4)


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
