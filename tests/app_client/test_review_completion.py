import time

import pytest
from anki.collection import Collection

from ankiweb.core.app_client import streak, study
from ankiweb.core.app_client.completion import Ease, mood, recall, summarize
from ankiweb.core.app_client.revlog import day_start_ms


@pytest.mark.parametrize(
    ("tally", "expected"),
    [
        ({}, "tough"),
        ({1: 0, 2: 0, 3: 3, 4: 2}, "perfect"),
        ({1: 0, 2: 0, 3: 601, 4: 399}, "great"),
        ({1: 1, 2: 0, 3: 0, 4: 9}, "great"),
        ({1: 15, 2: 0, 3: 85, 4: 0}, "great"),
        ({1: 31, 2: 0, 3: 169, 4: 0}, "good"),
        ({1: 40, 2: 0, 3: 60, 4: 0}, "good"),
        ({1: 81, 2: 0, 3: 119, 4: 0}, "tough"),
    ],
)
def test_mood_uses_unrounded_thresholds(tally, expected):
    assert mood(tally) == expected


def test_rounded_recall_does_not_change_mood():
    almost_great: dict[Ease, int] = {1: 31, 3: 169}
    almost_good: dict[Ease, int] = {1: 81, 3: 119}
    assert recall(almost_great) == 85
    assert mood(almost_great) == "good"
    assert recall(almost_good) == 60
    assert mood(almost_good) == "tough"


def test_summary_snapshots_counts_and_distribution():
    tally: dict[Ease, int] = {1: 1, 2: 2, 3: 1, 4: 1}
    summary = summarize(tally)
    tally[1] = 100
    assert summary.reviewed == 5
    assert summary.recall_percent == 80
    assert summary.mood == "good"
    assert summary.hard_effort is True
    assert summary.tally == {1: 1, 2: 2, 3: 1, 4: 1}
    assert summary.percentages == {1: 20.0, 2: 40.0, 3: 20.0, 4: 20.0}


def test_hard_effort_threshold_and_empty_tally():
    assert summarize({2: 399, 3: 601}).hard_effort is False
    assert summarize({2: 40, 3: 60}).hard_effort is True
    empty = summarize({})
    assert empty.reviewed == 0
    assert empty.recall_percent == 0
    assert empty.mood == "tough"
    assert empty.hard_effort is False
    assert empty.tally == {1: 0, 2: 0, 3: 0, 4: 0}
    assert empty.percentages == {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([], 0),
        ([1, 3, 2], 0),
        ([3, 2, 4, 1, 3, 4], 3),
        ([4, 3, 2], 3),
        ([3, 0, 4], 1),
    ],
)
def test_streak_counts_newest_successes_until_reset(rows, expected):
    assert streak.streak_from_revlog(iter(rows)) == expected


def _add_card(col: Collection, deck_name: str) -> tuple[int, int]:
    deck_id = col.decks.id(deck_name)
    model = col.models.by_name("Basic")
    assert deck_id is not None and model is not None
    note = col.new_note(model)
    note["Front"] = deck_name
    note["Back"] = "Answer"
    col.add_note(note, deck_id)
    return deck_id, note.cards()[0].id


def _insert_review(col: Collection, card_id: int, timestamp: int, ease: int) -> None:
    assert col.db is not None
    col.db.execute(
        "insert into revlog values (?, ?, -1, ?, 1, 0, 2500, 1000, 1)",
        timestamp,
        card_id,
        ease,
    )


def test_current_streak_obeys_boundary_and_includes_all_decks(temp_collection):
    col = temp_collection
    _, first = _add_card(col, "First")
    _, second = _add_card(col, "Second")
    start = day_start_ms(col)
    _insert_review(col, first, start - 1, 1)
    _insert_review(col, first, start, 1)
    _insert_review(col, first, start + 1, 3)
    _insert_review(col, second, start + 2, 2)
    _insert_review(col, first, start + 3, 4)
    assert streak.current_streak(col) == 3
    assert col.db.scalar("select count(*) from revlog") == 5
    _insert_review(col, second, start + 4, 1)
    assert streak.current_streak(col) == 0
    _insert_review(col, second, start + 5, 3)
    assert streak.current_streak(col) == 1


def test_five_hundred_reviews_expand_without_a_streak_cap(temp_collection, monkeypatch):
    col = temp_collection
    _, card_id = _add_card(col, "Long streak")
    start = day_start_ms(col)
    _insert_review(col, card_id, start + 1, 1)
    for i in range(500):
        _insert_review(col, card_id, start + i + 2, 2 + i % 3)

    limits = []
    recent_eases = streak.recent_eases

    def record_limit(collection, limit):
        limits.append(limit)
        return recent_eases(collection, limit)

    monkeypatch.setattr(streak, "recent_eases", record_limit)
    before = time.monotonic()
    assert streak.current_streak(col) == 500
    elapsed = time.monotonic() - before
    assert limits == [64, 128, 256, 512]
    assert elapsed < 10
    assert col.db.scalar("select count(*) from revlog") == 501


@pytest.mark.parametrize(("ease", "rated_streak"), [(1, 0), (3, 3)])
def test_undo_removes_rating_from_revlog_and_restores_streak(
    temp_collection, ease, rated_streak
):
    col = temp_collection
    deck_id, card_id = _add_card(col, "Undo")
    start = day_start_ms(col)
    _insert_review(col, card_id, start + 1, 3)
    _insert_review(col, card_id, start + 2, 4)
    session = study.StudySession()
    view = study.start(col, session, deck_id)
    assert view is not None
    assert streak.current_streak(col) == 2
    study.answer(col, session, view.card_id, ease)
    assert streak.current_streak(col) == rated_streak
    assert col.db.scalar("select count(*) from revlog") == 3
    col.undo()
    assert col.db.scalar("select count(*) from revlog") == 2
    assert streak.current_streak(col) == 2
