"""Summarize the ratings from one study session."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

Ease = Literal[1, 2, 3, 4]
Mood = Literal["perfect", "great", "good", "tough"]
_RATINGS: tuple[Ease, ...] = (1, 2, 3, 4)


def mood(tally: Mapping[Ease, int]) -> Mood:
    """Classify a session using exact, unrounded proportions."""
    total = sum(tally.get(ease, 0) for ease in _RATINGS)
    if not total:
        return "tough"
    again = tally.get(1, 0)
    if not again and 5 * tally.get(4, 0) >= 2 * total:
        return "perfect"
    if 20 * (total - again) >= 17 * total:
        return "great"
    if 5 * (total - again) >= 3 * total:
        return "good"
    return "tough"


def recall(tally: Mapping[Ease, int]) -> int:
    """Return recall as a whole percent, rounding halves up as in the mockup."""
    total = sum(tally.get(ease, 0) for ease in _RATINGS)
    if not total:
        return 0
    successful = total - tally.get(1, 0)
    return (200 * successful + total) // (2 * total)


@dataclass(frozen=True)
class CompletionSummary:
    """Display-ready statistics, independent of the day's revlog."""

    reviewed: int
    recall_percent: int
    mood: Mood
    hard_effort: bool
    tally: dict[Ease, int]
    percentages: dict[Ease, float]


def summarize(tally: Mapping[Ease, int]) -> CompletionSummary:
    """Snapshot a session's tally and derive its presentation values."""
    counts = {ease: tally.get(ease, 0) for ease in _RATINGS}
    total = sum(counts.values())
    return CompletionSummary(
        reviewed=total,
        recall_percent=recall(counts),
        mood=mood(counts),
        hard_effort=bool(total and 5 * counts[2] >= 2 * total),
        tally=counts,
        percentages={
            ease: 100 * counts[ease] / total if total else 0.0 for ease in _RATINGS
        },
    )
