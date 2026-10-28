"""Study queue and answers, independent of the legacy client.

``get_queued_cards`` counts use ``new_count``, ``learning_count`` and
``review_count``; ``deck_due_tree`` nodes use ``new_count``, ``learn_count``
and ``review_count`` instead.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import cast

import anki.collection  # Initialize before anki.cards to avoid an import cycle.
from anki.cards import Card, CardId
from anki.decks import DeckId
from anki.scheduler.v3 import (
    CardAnswer,
    QueuedCards,
    Scheduler,
    SchedulingContext,
    SchedulingStates,
)
from anki.sound import AV_REF_RE

from ankiweb.core.html_sanitize import sanitize_html

logger = logging.getLogger(__name__)
_EMPTY_STYLE = re.compile(r"^\s*<style>\s*</style>", re.IGNORECASE)
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


@dataclass(frozen=True)
class CardView:
    card_id: int
    deck: str
    question_html: str
    answer_html: str
    labels: tuple[str, str, str, str]
    counts: QueueCounts


class StudySession:
    """The card and scheduling state currently in flight in one session."""

    def __init__(self) -> None:
        self.card: Card | None = None
        self.states: SchedulingStates | None = None
        self.context: SchedulingContext | None = None
        self.added_note_ids: list[int] = []


class StaleCard(Exception):
    """The requested card is not the session's current card."""


def _clean_label(label: str) -> str:
    return label.replace("\u2068", "").replace("\u2069", "").replace("\u00a0", " ")


def _render_html(html: str) -> str:
    html = _EMPTY_STYLE.sub("", html, count=1)
    html, removed = AV_REF_RE.subn("", html)
    if removed:
        logger.debug("Removed %d unsupported audio/video references", removed)
    return sanitize_html(html)


def fetch_next(
    col: anki.collection.Collection, session: StudySession, deck_id: int | None
) -> CardView | None:
    scheduler = cast(Scheduler, col.sched)
    if deck_id is not None:
        col.decks.set_current(DeckId(deck_id))
    queued = scheduler.get_queued_cards(fetch_limit=1)
    if not queued.cards:
        session.card = None
        session.states = None
        session.context = None
        return None

    top = queued.cards[0]
    card = col.get_card(CardId(top.card.id))
    card.start_timer()
    session.card = card
    session.states = top.states
    session.context = top.context
    again, hard, good, easy = scheduler.describe_next_states(top.states)
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
        counts=QueueCounts.from_queue(queued),
    )


def answer(
    col: anki.collection.Collection, session: StudySession, card_id: int, ease: int
) -> None:
    card = session.card
    if card is None or card.id != card_id:
        raise StaleCard("Card is not in flight")
    if ease not in _RATINGS:
        raise ValueError("Ease must be between 1 and 4")
    assert session.states is not None
    scheduler = cast(Scheduler, col.sched)
    response = scheduler.build_answer(
        card=card, states=session.states, rating=_RATINGS[ease]
    )
    scheduler.answer_card(response)
    session.card = None
    session.states = None
    session.context = None
