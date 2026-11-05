from pathlib import Path
from typing import cast

import anki.consts
import pytest
from anki.cards import CardId
from anki.collection import Collection
from anki.collection_pb2 import OpChanges
from anki.decks import DeckId
from anki.scheduler.v3 import QueuedCards, Scheduler

from ankiweb.adapters.outbound.anki_collection_adapter import CollectionService
from ankiweb.core.app_client import study
from ankiweb.core.config import Settings
from ankiweb.core.op_changes import op_changes_to_flags


def add_cards(
    col: Collection, count: int, deck: str = "Review"
) -> tuple[DeckId, list[CardId]]:
    deck_id = col.decks.id(deck)
    model = col.models.by_name("Basic")
    assert deck_id is not None and model is not None
    ids = []
    for i in range(count):
        note = col.new_note(model)
        note["Front"] = f"{deck} question {i}"
        note["Back"] = f"Answer {i}"
        col.add_note(note, deck_id)
        ids.append(note.cards()[0].id)
    return deck_id, ids


def test_card_sanitizer_preserves_only_whitelisted_classes():
    html = (
        '<div class="av-front-text forbidden" onclick="alert(1)">front'
        '<span class="av-hint av-back-text av-example other">*word*</span>'
        '<script class="av-example">alert(2)</script>'
        '<img src="javascript:alert(3)" class="av-hint" onerror="alert(4)">'
        '<a href="javascript:alert(5)" class="av-example">link</a></div>'
    )
    rendered = study.sanitize_html(html)
    assert 'class="av-front-text"' in rendered
    assert 'class="av-hint av-back-text av-example"' in rendered
    assert "forbidden" not in rendered and "other" not in rendered
    assert "<script" not in rendered and "alert(2)" not in rendered
    assert "javascript:" not in rendered and "onclick" not in rendered
    assert "onerror" not in rendered and "<a " not in rendered
    assert "<span" in rendered and "*word*" in rendered


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        (
            (
                '<img src="https://example.com/image.png" class="av-hint other" '
                'onerror="alert(1)">'
            ),
            '<img src="https://example.com/image.png" class="av-hint">',
        ),
        ('<br class="av-hint other">', '<br class="av-hint">'),
        (
            '<span class="av-example other"><b>x</b></span>',
            '<span class="av-example"><b>x</b></span>',
        ),
    ],
)
def test_card_sanitizer_preserves_safe_classes_on_void_and_nested_tags(html, expected):
    assert study.sanitize_html(html) == expected


def test_escaped_example_text_stays_escaped_for_client_highlighting():
    rendered = study.sanitize_html(
        '<div class="av-example">&lt;b&gt;*word*&lt;/b&gt; &amp; text</div>'
    )
    assert rendered == (
        '<div class="av-example">&lt;b&gt;*word*&lt;/b&gt; &amp; text</div>'
    )


def test_rendered_card_keeps_design_classes_without_unsafe_html(temp_collection):
    col = temp_collection
    deck_id = col.decks.id("Classes")
    model = col.models.by_name("Basic")
    assert deck_id is not None and model is not None
    model["tmpls"][0]["qfmt"] = (
        '<div class="av-front-text unsafe" onclick="alert(1)">{{Front}}</div>'
        '<div class="av-example">{{Back}}</div>'
    )
    col.models.update_dict(model)
    note = col.new_note(model)
    note["Front"] = "<b>safe</b><script>alert(2)</script>"
    note["Back"] = "*word*"
    col.add_note(note, deck_id)
    view = study.start(col, study.StudySession(), deck_id)
    assert view is not None
    assert 'class="av-front-text"' in view.question_html
    assert 'class="av-example"' in view.question_html
    assert "<b>safe</b>" in view.question_html
    assert "<script" not in view.question_html and "onclick" not in view.question_html
    assert "unsafe" not in view.question_html and "*word*" in view.question_html


def test_start_resets_session_and_uses_anki_queue_count(temp_collection):
    col = temp_collection
    deck_id, _ = add_cards(col, 3)
    session = study.StudySession()
    first = study.start(col, session, deck_id)
    assert first is not None and first.counts.total == session.start_total == 3
    study.answer_next(col, session, first.card_id, 4)
    assert session.tally[4] == session.reviewed == 1
    restarted = study.start(col, session, deck_id)
    assert restarted is not None and restarted.counts.total == session.start_total == 2
    assert session.tally == {1: 0, 2: 0, 3: 0, 4: 0}
    assert session.reviewed == 0 and session.last_rated is None


def test_start_keeps_counts_when_queue_has_no_immediately_available_card(
    temp_collection, monkeypatch
):
    col = temp_collection
    deck_id = col.decks.id("Empty")
    assert deck_id is not None
    monkeypatch.setattr(
        col.sched,
        "get_queued_cards",
        lambda **kwargs: QueuedCards(learning_count=2),
    )
    session = study.StudySession()
    assert study.start(col, session, deck_id) is None
    assert session.start_total == 2
    assert session.card is None


def test_mark_and_flag_keep_in_flight_state_and_timer(temp_collection):
    col = temp_collection
    deck_id, _ = add_cards(col, 1)
    session = study.StudySession()
    view = study.start(col, session, deck_id)
    assert view is not None and session.card is not None
    card, states, context = session.card, session.states, session.context
    assert card.timer_started is not None
    card.timer_started -= 1
    timer = card.timer_started
    for action, expected in (
        (lambda: study.toggle_mark(col, session, view.card_id), (True, 0)),
        (lambda: study.set_flag(col, session, view.card_id, 4), (True, 4)),
        (lambda: study.toggle_mark(col, session, view.card_id), (False, 4)),
        (lambda: study.set_flag(col, session, view.card_id, 0), (False, 0)),
    ):
        result = action()
        assert isinstance(result.changes, OpChanges)
        assert result.view is not None
        assert (result.view.marked, result.view.flag) == expected
        assert (
            session.card is card
            and session.states is states
            and session.context is context
        )
        assert session.card.timer_started == timer
    assert not col.get_card(CardId(view.card_id)).note().has_tag("marked")
    assert col.get_card(CardId(view.card_id)).user_flag() == 0
    study.answer(col, session, view.card_id, 4)
    assert col.db.scalar("select time from revlog order by id desc limit 1") >= 1000


@pytest.mark.parametrize("flag", [-1, 5])
def test_invalid_flag_is_rejected_without_mutating_card(temp_collection, flag):
    col = temp_collection
    deck_id, _ = add_cards(col, 1)
    session = study.StudySession()
    view = study.start(col, session, deck_id)
    assert view is not None
    with pytest.raises(ValueError):
        study.set_flag(col, session, view.card_id, flag)
    assert col.get_card(CardId(view.card_id)).user_flag() == 0
    assert session.card is not None and session.card.id == view.card_id


@pytest.mark.parametrize("action, queue", [(study.bury, -3), (study.suspend, -1)])
def test_bury_suspend_and_undo_restore_card(temp_collection, action, queue):
    col = temp_collection
    deck_id, _ = add_cards(col, 2)
    session = study.StudySession()
    first = study.start(col, session, deck_id)
    assert first is not None
    result = action(col, session, first.card_id)
    assert isinstance(result.changes, OpChanges)
    assert col.get_card(CardId(first.card_id)).queue == queue
    assert result.view is not None and result.view.card_id != first.card_id
    restored = study.undo(col, session)
    assert isinstance(restored.changes, OpChanges)
    assert col.get_card(CardId(first.card_id)).queue == 0
    assert restored.view is not None and restored.view.counts.total == 2


def test_forget_resets_review_to_new(temp_collection):
    col = temp_collection
    deck_id, _ = add_cards(col, 1)
    session = study.StudySession()
    first = study.start(col, session, deck_id)
    assert first is not None
    study.answer_next(col, session, first.card_id, 4)
    # Bring the graduated card back as due before forgetting it.
    col.sched.set_due_date([CardId(first.card_id)], "0")
    due = study.start(col, session, deck_id)
    assert due is not None and due.card_id == first.card_id
    result = study.forget(col, session, due.card_id)
    assert isinstance(result.changes, OpChanges)
    assert col.get_card(CardId(due.card_id)).type == anki.consts.CARD_TYPE_NEW
    assert result.view is not None and result.view.card_id == first.card_id


def test_set_due_and_invalid_spec(temp_collection):
    col = temp_collection
    deck_id, _ = add_cards(col, 2)
    session = study.StudySession()
    view = study.start(col, session, deck_id)
    assert view is not None
    with pytest.raises(ValueError, match=r".+"):
        study.set_due(col, session, view.card_id, "not-a-date")
    assert session.card is not None and session.card.id == view.card_id
    result = study.set_due(col, session, view.card_id, "3")
    assert isinstance(result.changes, OpChanges)
    assert col.get_card(CardId(view.card_id)).type == anki.consts.CARD_TYPE_REV
    assert result.view is not None and result.view.card_id != view.card_id


def test_delete_note_and_undo(temp_collection):
    col = temp_collection
    deck_id, _ = add_cards(col, 2)
    session = study.StudySession()
    view = study.start(col, session, deck_id)
    assert view is not None and session.card is not None
    note_id = session.card.nid
    result = study.delete_note(col, session, view.card_id)
    assert isinstance(result.changes, OpChanges)
    assert col.db.scalar("select count() from notes where id = ?", note_id) == 0
    assert result.view is not None and result.view.card_id != view.card_id
    study.undo(col, session)
    assert col.db.scalar("select count() from notes where id = ?", note_id) == 1
    assert col.db.scalar("select count() from cards where id = ?", view.card_id) == 1


def test_answer_returns_changes_and_undo_reverses_session_and_revlog(temp_collection):
    col = temp_collection
    deck_id, _ = add_cards(col, 2)
    session = study.StudySession()
    first = study.start(col, session, deck_id)
    assert first is not None
    result = study.answer_next(col, session, first.card_id, 4)
    assert isinstance(result.changes, OpChanges)
    assert result.view is not None and result.view.counts.total == 1
    assert session.last_rated == (first.card_id, 4)
    assert session.reviewed == 1 and session.tally[4] == 1
    assert col.db.scalar("select count() from revlog") == 1
    restored = study.undo(col, session)
    assert restored.view is not None and restored.view.card_id == first.card_id
    assert restored.view.counts.total == 2
    assert (
        session.reviewed == 0 and session.tally[4] == 0 and session.last_rated is None
    )
    assert col.db.scalar("select count() from revlog") == 0


def test_raw_answer_returns_opchanges(temp_collection):
    col = temp_collection
    deck_id, _ = add_cards(col, 1)
    session = study.StudySession()
    view = study.start(col, session, deck_id)
    assert view is not None
    assert isinstance(study.answer(col, session, view.card_id, 3), OpChanges)


def test_undo_after_other_action_does_not_remove_rating(temp_collection):
    col = temp_collection
    deck_id, _ = add_cards(col, 2)
    session = study.StudySession()
    first = study.start(col, session, deck_id)
    assert first is not None
    second = study.answer_next(col, session, first.card_id, 4).view
    assert second is not None
    study.toggle_mark(col, session, second.card_id)
    assert session.last_rated is None
    study.undo(col, session)
    assert session.reviewed == 1 and session.tally[4] == 1
    assert col.db.scalar("select count() from revlog") == 1
    assert not col.get_card(CardId(second.card_id)).note().has_tag("marked")


def test_undo_after_another_sessions_answer_does_not_remove_own_tally(temp_collection):
    col = temp_collection
    deck_id, _ = add_cards(col, 3)
    ours = study.StudySession()
    first = study.start(col, ours, deck_id)
    assert first is not None
    second = study.answer_next(col, ours, first.card_id, 4).view
    assert second is not None
    theirs = study.StudySession()
    other = study.start(col, theirs, deck_id)
    assert other is not None and other.card_id == second.card_id
    study.answer_next(col, theirs, other.card_id, 3)
    study.undo(col, ours)
    assert ours.reviewed == 1 and ours.tally[4] == 1
    assert col.db.scalar("select count() from revlog") == 1
    assert col.db.scalar("select cid from revlog") == first.card_id


@pytest.mark.parametrize("cause", ["answered_elsewhere", "deleted"])
def test_stale_answer_leaves_tally_and_last_rating_untouched(temp_collection, cause):
    col = temp_collection
    deck_id, _ = add_cards(col, 3)
    ours = study.StudySession()
    first = study.start(col, ours, deck_id)
    assert first is not None
    second = study.answer_next(col, ours, first.card_id, 4).view
    assert second is not None
    tally_before = dict(ours.tally)
    last_rated_before = ours.last_rated
    assert ours.card is not None
    if cause == "answered_elsewhere":
        theirs = study.StudySession()
        other = study.start(col, theirs, deck_id)
        assert other is not None and other.card_id == second.card_id
        study.answer(col, theirs, other.card_id, 3)
    else:
        col.remove_notes([ours.card.nid])

    with pytest.raises(study.StaleCard):
        study.answer(col, ours, second.card_id, 1)

    assert ours.tally == tally_before
    assert ours.reviewed == 1
    assert ours.last_rated == last_rated_before


def test_undo_after_legacy_mutation_does_not_remove_own_tally(temp_collection):
    col = temp_collection
    deck_id, _ = add_cards(col, 2)
    session = study.StudySession()
    first = study.start(col, session, deck_id)
    assert first is not None
    second = study.answer_next(col, session, first.card_id, 4).view
    assert second is not None
    col.set_user_flag_for_cards(1, [CardId(second.card_id)])
    study.undo(col, session)
    assert session.reviewed == 1 and session.tally[4] == 1
    assert col.db.scalar("select count() from revlog") == 1
    assert col.get_card(CardId(second.card_id)).user_flag() == 0


def test_empty_undo_stack_raises_nothing_to_undo(temp_collection):
    with pytest.raises(study.NothingToUndo):
        study.undo(temp_collection, study.StudySession())


@pytest.mark.parametrize(
    "action",
    [
        study.toggle_mark,
        lambda c, s, cid: study.set_flag(c, s, cid, 1),
        study.bury,
        study.suspend,
        study.forget,
        lambda c, s, cid: study.set_due(c, s, cid, "3"),
        study.delete_note,
        lambda c, s, cid: study.answer_next(c, s, cid, 4),
    ],
)
def test_actions_reject_stale_card(temp_collection, action):
    col = temp_collection
    deck_id, _ = add_cards(col, 1)
    session = study.StudySession()
    view = study.start(col, session, deck_id)
    assert view is not None
    with pytest.raises(study.StaleCard):
        action(col, session, view.card_id + 1)
    assert session.card is not None and session.card.id == view.card_id


def test_interleaved_decks_restore_own_queue_without_resetting_card(temp_collection):
    col = temp_collection
    first_id, _ = add_cards(col, 2, "First")
    second_id, _ = add_cards(col, 3, "Second")
    first_session, second_session = study.StudySession(), study.StudySession()
    first = study.start(col, first_session, first_id)
    second = study.start(col, second_session, second_id)
    assert first is not None and second is not None
    first_card, first_states = first_session.card, first_session.states
    refreshed = study.toggle_mark(col, first_session, first.card_id).view
    assert refreshed is not None and refreshed.counts.total == 2
    assert first_session.card is first_card and first_session.states is first_states
    study.current_view(col, second_session)
    next_first = study.answer_next(col, first_session, first.card_id, 4).view
    assert next_first is not None and next_first.deck == "First"
    assert next_first.counts.total == 1
    next_second = study.answer_next(col, second_session, second.card_id, 4).view
    assert next_second is not None and next_second.deck == "Second"
    assert next_second.counts.total == 2


def test_mixed_notetypes_obey_daily_limit_without_filtering(temp_collection):
    col = temp_collection
    deck_id, basic_ids = add_cards(col, 200)
    basic = col.models.by_name("Basic")
    assert basic is not None
    vocab_model = col.models.copy(basic, add=False)
    vocab_model["name"] = study.VOCAB_NOTETYPE
    col.models.add_dict(vocab_model)
    vocab_model = col.models.by_name(study.VOCAB_NOTETYPE)
    assert vocab_model is not None
    vocab = col.new_note(vocab_model)
    vocab["Front"], vocab["Back"] = "Vocab", "Vocabulary"
    col.add_note(vocab, deck_id)
    vocab_id = vocab.cards()[0].id
    session = study.StudySession()
    view = study.start(col, session, deck_id)
    assert view is not None
    assert session.start_total == view.counts.total == 20
    assert view.other_notetype and view.card_id in basic_ids
    queued = cast(Scheduler, col.sched).get_queued_cards(fetch_limit=100)
    queued_ids = {card.card.id for card in queued.cards}
    assert len(queued_ids) == 20 and vocab_id not in queued_ids


@pytest.mark.parametrize(
    "name",
    ["mark", "flag", "bury", "suspend", "forget", "due", "delete", "undo", "answer"],
)
async def test_service_broadcasts_underlying_opchanges_for_each_wrapper(
    tmp_path: Path, name: str
):
    service = CollectionService(Settings(collection_path=tmp_path / "broadcast.anki2"))
    await service.open()
    try:
        deck_id, _ = await service.run(lambda col: add_cards(col, 1))
        session = study.StudySession()
        first = await service.run(lambda col: study.start(col, session, deck_id))
        assert first is not None
        if name == "forget":
            await service.run(lambda col: study.answer(col, session, first.card_id, 4))
            await service.run(
                lambda col: col.sched.set_due_date([CardId(first.card_id)], "0")
            )
            view = await service.run(lambda col: study.start(col, session, deck_id))
            assert view is not None
        elif name == "undo":
            await service.run(
                lambda col: study.toggle_mark(col, session, first.card_id)
            )

        assert session.card is not None
        card_id = session.card.id
        actions = {
            "mark": lambda col: study.toggle_mark(col, session, card_id),
            "flag": lambda col: study.set_flag(col, session, card_id, 2),
            "bury": lambda col: study.bury(col, session, card_id),
            "suspend": lambda col: study.suspend(col, session, card_id),
            "forget": lambda col: study.forget(col, session, card_id),
            "due": lambda col: study.set_due(col, session, card_id, "3"),
            "delete": lambda col: study.delete_note(col, session, card_id),
            "undo": lambda col: study.undo(col, session),
            "answer": lambda col: study.answer_next(col, session, card_id, 4),
        }
        seen = []
        service.subscribe(lambda flags, initiator: seen.append((flags, initiator)))
        result = await service.run_op(actions[name], initiator="app")
        flags = op_changes_to_flags(result.changes)
        assert any(flags.values())
        assert seen == [(flags, "app")]
    finally:
        await service.close()
