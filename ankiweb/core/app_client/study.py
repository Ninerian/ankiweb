"""Study queue and answers, independent of the legacy client.

``get_queued_cards`` counts use ``new_count``, ``learning_count`` and
``review_count``; ``deck_due_tree`` nodes use ``new_count``, ``learn_count``
and ``review_count`` instead.

Starting on GET/reload resets the timer and session tally. The sanitized answer
is present in the page before reveal. Foreign note types may disrupt layout;
MathJax is not supported. Tally is per session and may differ from day streak.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Literal, cast

import anki.collection  # Initialize before anki.cards to avoid an import cycle.
from anki.cards import Card, CardId
from anki.collection_pb2 import OpChanges
from anki.decks import DeckId
from anki.errors import InvalidInput, NotFoundError, UndoEmpty
from anki.scheduler.v3 import (
    CardAnswer,
    QueuedCards,
    Scheduler,
    SchedulingContext,
    SchedulingStates,
)
from anki.sound import AV_REF_RE

from ankiweb.core.html_sanitize import _HTMLSanitizer

logger = logging.getLogger(__name__)
_EMPTY_STYLE = re.compile(r"^\s*<style>\s*</style>", re.IGNORECASE)
VOCAB_NOTETYPE = "AnkiWeb Vocab"
MARKED_TAG = "marked"
_CARD_CLASSES = frozenset({"av-front-text", "av-hint", "av-back-text", "av-example"})
Ease = Literal[1, 2, 3, 4]
_RATINGS = {
    1: CardAnswer.Rating.AGAIN,
    2: CardAnswer.Rating.HARD,
    3: CardAnswer.Rating.GOOD,
    4: CardAnswer.Rating.EASY,
}


@dataclass(frozen=True)
class QueueCounts:
    new: int
    learning: int
    review: int

    @classmethod
    def from_queue(cls, queued: QueuedCards) -> QueueCounts:
        return cls(queued.new_count, queued.learning_count, queued.review_count)

    @property
    def total(self) -> int:
        return self.new + self.learning + self.review


@dataclass(frozen=True)
class CardView:
    card_id: int
    deck: str
    question_html: str
    answer_html: str
    labels: tuple[str, str, str, str]
    counts: QueueCounts
    marked: bool = False
    flag: int = 0
    other_notetype: bool = False


class StudySession:
    """The card and scheduling state currently in flight in one session."""

    def __init__(self) -> None:
        self.card: Card | None = None
        self.states: SchedulingStates | None = None
        self.context: SchedulingContext | None = None
        self._card_snapshot: tuple[int | str, ...] | None = None
        self.deck_id: int | None = None
        self.start_total = 0
        self.tally: dict[Ease, int] = {1: 0, 2: 0, 3: 0, 4: 0}
        self.reviewed = 0
        self.last_rated: tuple[int, Ease] | None = None
        self._last_rated_step: int | None = None


@dataclass(frozen=True)
class StudyStep:
    """Result of a study command; ``changes`` is what ``run_op`` broadcasts."""

    changes: OpChanges
    view: CardView | None = field(default=None)


class StaleCard(Exception):
    """The requested card is not in flight or has changed in the collection."""


class NothingToUndo(Exception):
    """The collection has no undoable operation."""


class _CardHTMLSanitizer(_HTMLSanitizer):
    """Keep only the fixed card classes after the shared sanitizer accepts a tag."""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        before = len(self.result)
        super().handle_starttag(tag, attrs)
        if len(self.result) == before:
            return
        classes = [
            item
            for name, value in attrs
            if name == "class" and value is not None
            for item in value.split()
            if item in _CARD_CLASSES
        ]
        if classes:
            self.result[-1] = self.result[-1][:-1] + f' class="{" ".join(classes)}">'


def sanitize_html(content: str) -> str:
    """Apply the shared sanitizer while retaining safe card-design classes."""
    if not content:
        return ""
    parser = _CardHTMLSanitizer()
    parser.feed(content)
    parser.close()
    return "".join(parser.result)


def _clean_label(label: str) -> str:
    return label.replace("\u2068", "").replace("\u2069", "").replace("\u00a0", " ")


def _render_html(html: str) -> str:
    html = _EMPTY_STYLE.sub("", html, count=1)
    html, removed = AV_REF_RE.subn("", html)
    if removed:
        logger.debug("Removed %d unsupported audio/video references", removed)
    return sanitize_html(html)


def _card_snapshot(
    col: anki.collection.Collection, card_id: CardId
) -> tuple[int | str, ...] | None:
    # Compare persisted fields, not time-dependent scheduler states. The data
    # column includes FSRS and custom scheduling data.
    assert col.db is not None
    row = col.db.first(
        "select mod, usn, type, queue, due, did, ivl, factor, reps, lapses, "
        '"left", odue, odid, data from cards where id = ?',
        card_id,
    )
    return tuple(row) if row is not None else None


def _view(
    col: anki.collection.Collection, session: StudySession, counts: QueueCounts
) -> CardView:
    """Describe the in-flight card without touching its timer or states."""
    card, states = session.card, session.states
    assert card is not None and states is not None
    scheduler = cast(Scheduler, col.sched)
    # Tags and flags are written to the database; read them back from there.
    stored = col.get_card(card.id)
    note = stored.note()
    notetype = note.note_type()
    again, hard, good, easy = scheduler.describe_next_states(states)
    return CardView(
        card_id=card.id,
        deck=col.decks.name(card.did),
        question_html=_render_html(card.question()),
        answer_html=_render_html(card.answer()),
        labels=(
            _clean_label(again),
            _clean_label(hard),
            _clean_label(good),
            _clean_label(easy),
        ),
        counts=counts,
        marked=note.has_tag(MARKED_TAG),
        flag=stored.user_flag(),
        other_notetype=notetype is None or notetype["name"] != VOCAB_NOTETYPE,
    )


def _select_deck(col: anki.collection.Collection, deck_id: int | None) -> None:
    # The current deck is collection-global and may have been changed by another tab.
    if deck_id is not None and col.decks.get_current_id() != deck_id:
        col.decks.set_current(DeckId(deck_id))


def fetch_next(
    col: anki.collection.Collection, session: StudySession, deck_id: int | None
) -> CardView | None:
    scheduler = cast(Scheduler, col.sched)
    _select_deck(col, deck_id)
    queued = scheduler.get_queued_cards(fetch_limit=1)
    if not queued.cards:
        session.card = None
        session.states = None
        session.context = None
        session._card_snapshot = None
        return None

    top = queued.cards[0]
    card = col.get_card(CardId(top.card.id))
    snapshot = _card_snapshot(col, card.id)
    if snapshot is None:
        session.card = None
        session.states = None
        session.context = None
        session._card_snapshot = None
        raise StaleCard("Card has changed in the collection")
    card.start_timer()
    session.card = card
    session.states = top.states
    session.context = top.context
    session._card_snapshot = snapshot
    return _view(col, session, QueueCounts.from_queue(queued))


def start(
    col: anki.collection.Collection, session: StudySession, deck_id: int
) -> CardView | None:
    """Begin a study run: reset the tally and progress baseline, fetch the head."""
    session.deck_id = deck_id
    session.tally = {1: 0, 2: 0, 3: 0, 4: 0}
    session.reviewed = 0
    session.last_rated = None
    session._last_rated_step = None
    view = fetch_next(col, session, deck_id)
    if view is not None:
        session.start_total = view.counts.total
    else:
        queued = cast(Scheduler, col.sched).get_queued_cards(fetch_limit=1)
        session.start_total = QueueCounts.from_queue(queued).total
    return view


def current_view(col: anki.collection.Collection, session: StudySession) -> CardView:
    """Re-describe the in-flight card; ``fetch_next`` is NOT called."""
    _select_deck(col, session.deck_id)
    scheduler = cast(Scheduler, col.sched)
    counts = QueueCounts.from_queue(scheduler.get_queued_cards(fetch_limit=1))
    return _view(col, session, counts)


def answer(
    col: anki.collection.Collection, session: StudySession, card_id: int, ease: int
) -> OpChanges:
    card = session.card
    if card is None or card.id != card_id:
        raise StaleCard("Card is not in flight")
    if ease not in _RATINGS:
        raise ValueError("Ease must be between 1 and 4")
    if session._card_snapshot is None or (
        _card_snapshot(col, card.id) != session._card_snapshot
    ):
        session.card = None
        session.states = None
        session.context = None
        session._card_snapshot = None
        raise StaleCard("Card has changed in the collection")
    assert session.states is not None
    _select_deck(col, session.deck_id)
    scheduler = cast(Scheduler, col.sched)
    response = scheduler.build_answer(
        card=card, states=session.states, rating=_RATINGS[ease]
    )
    try:
        changes = scheduler.answer_card(response)
    except (InvalidInput, NotFoundError) as err:
        session.card = None
        session.states = None
        session.context = None
        session._card_snapshot = None
        raise StaleCard("Card is no longer current") from err
    session.card = None
    session.states = None
    session.context = None
    session._card_snapshot = None
    rated = cast(Ease, ease)
    session.tally[rated] += 1
    session.reviewed += 1
    session.last_rated = (card_id, rated)
    session._last_rated_step = col.undo_status().last_step
    return changes


def answer_next(
    col: anki.collection.Collection, session: StudySession, card_id: int, ease: int
) -> StudyStep:
    changes = answer(col, session, card_id, ease)
    return StudyStep(changes, fetch_next(col, session, session.deck_id))


def _in_flight(session: StudySession, card_id: int) -> Card:
    card = session.card
    if card is None or card.id != card_id:
        raise StaleCard("Card is not in flight")
    return card


def _stay(
    col: anki.collection.Collection, session: StudySession, changes: OpChanges
) -> StudyStep:
    session.last_rated = None
    session._last_rated_step = None
    return StudyStep(changes, current_view(col, session))


def _advance(
    col: anki.collection.Collection, session: StudySession, changes: OpChanges
) -> StudyStep:
    session.last_rated = None
    session._last_rated_step = None
    return StudyStep(changes, fetch_next(col, session, session.deck_id))


def toggle_mark(
    col: anki.collection.Collection, session: StudySession, card_id: int
) -> StudyStep:
    card = _in_flight(session, card_id)
    note = col.get_note(card.nid)
    if note.has_tag(MARKED_TAG):
        note.remove_tag(MARKED_TAG)
    else:
        note.add_tag(MARKED_TAG)
    return _stay(col, session, col.update_note(note))


def set_flag(
    col: anki.collection.Collection, session: StudySession, card_id: int, flag: int
) -> StudyStep:
    card = _in_flight(session, card_id)
    if not 0 <= flag <= 4:
        raise ValueError("Flag must be between 0 and 4")
    return _stay(col, session, col.set_user_flag_for_cards(flag, [card.id]).changes)


def bury(
    col: anki.collection.Collection, session: StudySession, card_id: int
) -> StudyStep:
    card = _in_flight(session, card_id)
    return _advance(col, session, col.sched.bury_cards([card.id]).changes)


def suspend(
    col: anki.collection.Collection, session: StudySession, card_id: int
) -> StudyStep:
    card = _in_flight(session, card_id)
    return _advance(col, session, col.sched.suspend_cards([card.id]).changes)


def forget(
    col: anki.collection.Collection, session: StudySession, card_id: int
) -> StudyStep:
    card = _in_flight(session, card_id)
    return _advance(col, session, col.sched.schedule_cards_as_new([card.id]))


def set_due(
    col: anki.collection.Collection, session: StudySession, card_id: int, spec: str
) -> StudyStep:
    card = _in_flight(session, card_id)
    try:
        changes = col.sched.set_due_date([card.id], spec)
    except InvalidInput as exc:
        raise ValueError(str(exc)) from exc
    return _advance(col, session, changes)


def delete_note(
    col: anki.collection.Collection, session: StudySession, card_id: int
) -> StudyStep:
    card = _in_flight(session, card_id)
    return _advance(col, session, col.remove_notes([card.nid]).changes)


def undo(col: anki.collection.Collection, session: StudySession) -> StudyStep:
    """Undo the collection's last operation; take back the tally if it was ours."""
    # Undo is collection-global: the latest operation may belong to another tab.
    own_rating = (
        session.last_rated is not None
        and session._last_rated_step is not None
        and col.undo_status().last_step == session._last_rated_step
    )
    try:
        changes = col.undo()
    except UndoEmpty as exc:
        raise NothingToUndo("Nothing to undo") from exc
    if own_rating and session.last_rated is not None:
        ease = session.last_rated[1]
        session.tally[ease] -= 1
        session.reviewed -= 1
    return _advance(col, session, changes.changes)


def card_info_url(card_id: int) -> str:
    return f"/card-info/{card_id}"
