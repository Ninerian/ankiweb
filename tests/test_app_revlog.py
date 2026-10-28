from datetime import datetime, timedelta
from pathlib import Path

import pytest
from anki.cards import CardId
from anki.collection import Collection
from anki.decks import DeckId
from anki.scheduler.v3 import CardAnswer
from anki.scheduler.v3 import Scheduler as V3Scheduler
from fastapi.testclient import TestClient

from ankiweb.ankiconnect.app import create_ankiconnect_app
from ankiweb.core.app_client.revlog import day_start_ms, recent_eases, studied_by_deck
from ankiweb.core.config import Settings


def _add_card(col: Collection, deck_name: str) -> tuple[int, CardId]:
    deck_id = col.decks.id(deck_name)
    model = col.models.by_name("Basic")
    assert deck_id is not None
    assert model is not None
    note = col.new_note(model)
    note["Front"] = deck_name
    note["Back"] = "answer"
    col.add_note(note, deck_id)
    return deck_id, note.cards()[0].id


def _insert_review(
    col: Collection, card_id: int, timestamp: int, ease: int, revlog_type: int = 1
) -> None:
    assert col.db is not None
    col.db.execute(
        "insert into revlog values (?, ?, -1, ?, 1, 0, 2500, 1000, ?)",
        timestamp,
        card_id,
        ease,
        revlog_type,
    )


@pytest.mark.parametrize("rollover", [4, 0, 23])
def test_day_boundary_follows_collection_rollover(
    temp_collection: Collection, rollover: int
) -> None:
    col = temp_collection
    # Anki caches scheduler timing, so configure rollover before the first cutoff read.
    col.set_config("rollover", rollover)
    start = day_start_ms(col)
    # Anki computes the cutoff using the current offset, even across a DST change.
    cutoff_at_current_offset = datetime.fromtimestamp(
        col.sched.day_cutoff, datetime.now().astimezone().tzinfo
    )
    assert cutoff_at_current_offset.hour == rollover
    deck_id, card_id = _add_card(col, "Boundary")
    _insert_review(col, card_id, start - 1, 1)
    _insert_review(col, card_id, start, 2)
    _insert_review(col, card_id, start + 1, 3)

    assert studied_by_deck(col) == {deck_id: 1}
    assert recent_eases(col, 10) == [3]


def test_two_am_review_belongs_to_previous_day(temp_collection: Collection) -> None:
    col = temp_collection
    col.set_config("rollover", 4)
    start = day_start_ms(col)
    start_local = datetime.fromtimestamp(start / 1000)
    cutoff_at_current_offset = datetime.fromtimestamp(
        col.sched.day_cutoff, datetime.now().astimezone().tzinfo
    )
    assert cutoff_at_current_offset.hour == 4
    two_am = start_local.replace(hour=2, minute=0, second=0, microsecond=0)
    if datetime.fromtimestamp(two_am.timestamp()).hour != 2:
        # On a spring-forward day, local 02:00 does not exist.
        two_am -= timedelta(days=1)
    assert datetime.fromtimestamp(two_am.timestamp()).hour == 2
    review_ms = int(two_am.timestamp() * 1000)
    assert review_ms < start
    deck_id, card_id = _add_card(col, "Early")
    _insert_review(col, card_id, review_ms, 1)
    _insert_review(col, card_id, start + 1, 4)

    assert studied_by_deck(col) == {deck_id: 1}
    assert recent_eases(col, 10) == [4]


def test_studied_by_deck_does_not_aggregate_children(
    temp_collection: Collection,
) -> None:
    col = temp_collection
    parent_id, parent_card = _add_card(col, "Parent")
    child_id, child_card = _add_card(col, "Parent::Child")
    other_id, other_card = _add_card(col, "Other")
    start = day_start_ms(col)
    _insert_review(col, parent_card, start + 1, 1)
    _insert_review(col, child_card, start + 2, 2)
    _insert_review(col, child_card, start + 3, 3)
    _insert_review(col, other_card, start + 4, 4)
    _insert_review(col, other_card, start - 1, 1)

    assert studied_by_deck(col) == {parent_id: 1, child_id: 2, other_id: 1}


def test_recent_eases_newest_first_and_limited(temp_collection: Collection) -> None:
    col = temp_collection
    _, card_id = _add_card(col, "Eases")
    start = day_start_ms(col)
    assert recent_eases(col, 5) == []
    _insert_review(col, card_id, start + 10, 2)
    _insert_review(col, card_id, start + 30, 4)
    _insert_review(col, card_id, start + 20, 1)
    _insert_review(col, card_id, start - 1, 3)

    assert recent_eases(col, 10) == [4, 1, 2]
    assert recent_eases(col, 2) == [4, 1]
    assert recent_eases(col, 0) == []


def test_manual_entries_are_not_counted_as_reviews(temp_collection: Collection) -> None:
    col = temp_collection
    deck_id, card_id = _add_card(col, "Reviewed")
    _, manual_only_card = _add_card(col, "Manual only")
    start = day_start_ms(col)
    _insert_review(col, card_id, start + 1, 4)
    _insert_review(col, card_id, start + 2, 0, revlog_type=4)
    _insert_review(col, card_id, start + 3, 0, revlog_type=5)
    _insert_review(col, manual_only_card, start + 4, 0, revlog_type=4)

    assert studied_by_deck(col) == {deck_id: 1}
    assert recent_eases(col, 10) == [4]
    assert recent_eases(col, 1) == [4]


@pytest.mark.parametrize("operations", [("due",), ("forget",), ("due", "forget")])
@pytest.mark.parametrize("helper", ["studied", "eases"])
def test_manual_scheduling_does_not_count_as_study(
    temp_collection: Collection, operations: tuple[str, ...], helper: str
) -> None:
    col = temp_collection
    _, due_card = _add_card(col, "Manual")
    _, forgotten_card = _add_card(col, "Manual")
    for operation in operations:
        if operation == "due":
            col.sched.set_due_date([due_card], "1")
        else:
            col.sched.schedule_cards_as_new([forgotten_card])

    if helper == "studied":
        assert studied_by_deck(col) == {}
    else:
        assert recent_eases(col, 10) == []

    studied_deck, _ = _add_card(col, "Study")
    col.decks.set_current(DeckId(studied_deck))
    assert isinstance(col.sched, V3Scheduler)
    queued = col.sched.get_queued_cards(fetch_limit=1)
    assert queued.cards
    top = queued.cards[0]
    card = col.get_card(CardId(top.card.id))
    card.start_timer()
    answer = col.sched.build_answer(
        card=card, states=top.states, rating=CardAnswer.Rating.GOOD
    )
    col.sched.answer_card(answer)
    col.sched.set_due_date([due_card], "3")

    if helper == "studied":
        assert studied_by_deck(col) == {studied_deck: 1}
    else:
        assert recent_eases(col, 10) == [3]
        assert recent_eases(col, 1) == [3]


@pytest.mark.parametrize("rollover", [4, 0, 23])
def test_reviewed_today_action_uses_same_boundary(
    tmp_path: Path, rollover: int
) -> None:
    settings = Settings(collection_path=tmp_path / "collection.anki2")
    with TestClient(create_ankiconnect_app(settings)) as client:

        def seed(col: Collection) -> tuple[int, dict[int, int], list[int]]:
            col.set_config("rollover", rollover)
            start = day_start_ms(col)
            deck_id, card_id = _add_card(col, "Parity")
            _insert_review(col, card_id, start - 1, 1)
            _insert_review(col, card_id, start, 2)
            _insert_review(col, card_id, start + 1, 3)
            _insert_review(col, card_id, start + 2, 0, revlog_type=4)
            _insert_review(col, card_id, start + 3, 0, revlog_type=5)
            return deck_id, studied_by_deck(col), recent_eases(col, 10)

        assert client.portal is not None
        deck_id, counts, eases = client.portal.call(client.app.state.service.run, seed)
        response = client.post("/actions/getNumCardsReviewedToday", json={})

    assert response.status_code == 200
    assert response.json() == {"result": 3, "error": None}
    assert counts == {deck_id: 1}
    assert eases == [3]
