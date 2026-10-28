"""Derive today's cross-deck streak from read-only review history."""

from collections.abc import Iterable

from anki.collection import Collection

from ankiweb.core.app_client.revlog import recent_eases


def streak_from_revlog(rows: Iterable[int]) -> int:
    """Count consecutive successful ratings, starting with the newest."""
    count = 0
    for ease in rows:
        if ease not in (2, 3, 4):
            break
        count += 1
    return count


def current_streak(col: Collection) -> int:
    """Read progressively larger blocks until a reset or the day's end.

    ``recent_eases`` enforces the scheduler's day boundary and returns the
    newest ratings first. Expanding the limit avoids imposing a streak cap;
    each newly fetched suffix is examined once.
    """
    limit = 64
    scanned = 0
    while True:
        rows = recent_eases(col, limit)
        for index in range(scanned, len(rows)):
            if rows[index] not in (2, 3, 4):
                return index
        scanned = len(rows)
        if scanned < limit:
            return scanned
        limit *= 2
