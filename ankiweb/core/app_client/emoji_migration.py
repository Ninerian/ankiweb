"""Plan and apply explicitly confirmed prefix-to-suffix deck renames.

Measured against the bundled Anki: renaming a deck does not rewrite a filtered
deck's search text; grouping two renames with merge_undo_entries lets one undo
restore both names.
"""

import logging
from collections import Counter
from collections.abc import Collection as IdCollection
from dataclasses import dataclass, field
from typing import Literal

from anki.collection import Collection
from anki.collection_pb2 import OpChanges
from anki.decks import DeckId

from ankiweb.core.app_client.decks import (
    _comparison_name,
    _emoji_end,
    _emoji_only,
    join_emoji,
)
from ankiweb.core.app_client.emoji_picker import ALL_EMOJI

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Rename:
    deck_id: int
    old: str
    new: str
    status: Literal["ready", "conflict", "skipped"]
    reason: str


@dataclass(frozen=True)
class MigrationResult:
    ok: int
    skipped: int
    failed: int
    changes: OpChanges = field(default_factory=OpChanges, compare=False, repr=False)


def _prefix(name: str) -> tuple[str, str] | None:
    end = _emoji_end(name)
    emoji = name[:end]
    if emoji not in ALL_EMOJI:
        return None
    if end == len(name):
        return emoji, ""
    if name[end : end + 1] != " ":
        return None
    return emoji, name[end + 1 :]


def _has_suffix(name: str) -> bool:
    head, sep, emoji = name.rpartition(" · ")
    return bool(sep and head.strip() and emoji and _emoji_end(emoji) == len(emoji))


def _candidate(deck_id: int, name: str) -> Rename | None:
    levels = name.split("::")
    if len(levels) > 1:
        if any(_prefix(level) for level in levels[1:]):
            return Rename(deck_id, name, name, "skipped", "child")
        return None
    prefix = _prefix(name)
    if prefix is None or _has_suffix(name):
        return None
    emoji, rest = prefix
    rest = rest.strip()
    if not rest or _emoji_only(rest):
        return Rename(deck_id, name, name, "skipped", "emoji_only")
    if len(rest) > 40:
        return Rename(deck_id, name, name, "skipped", "too_long")
    return Rename(deck_id, name, join_emoji(rest, emoji), "ready", "")


def _mark_conflict(item: Rename, existing: set[str], targets: Counter[str]) -> Rename:
    target = _comparison_name(item.new)
    if item.status == "ready" and (target in existing or targets[target] > 1):
        return Rename(item.deck_id, item.old, item.new, "conflict", "taken")
    return item


def plan_emoji_migration(col: Collection) -> list[Rename]:
    """Return a read-only preview, including conflicts and unsupported decks."""
    decks = col.decks.all_names_and_ids()
    existing = {_comparison_name(deck.name) for deck in decks}
    candidates = [
        candidate
        for deck in decks
        if (candidate := _candidate(deck.id, deck.name)) is not None
    ]
    # Anki renames descendants with their root; protect skipped prefix children.
    protected_roots = {
        _comparison_name(item.old.split("::", 1)[0])
        for item in candidates
        if item.reason == "child"
    }
    candidates = [
        Rename(item.deck_id, item.old, item.new, "skipped", "child")
        if item.status == "ready" and _comparison_name(item.old) in protected_roots
        else item
        for item in candidates
    ]
    targets = Counter(
        _comparison_name(item.new) for item in candidates if item.status == "ready"
    )
    return [_mark_conflict(item, existing, targets) for item in candidates]


def filtered_deck_warning_count(col: Collection, plan: list[Rename]) -> int:
    """Count filtered decks whose stored search text contains an eligible old name."""
    names = [item.old for item in plan if item.status == "ready"]
    if not names:
        return 0
    count = 0
    for deck in col.decks.all():
        if not deck["dyn"]:
            continue
        filtered = col.sched.get_or_create_filtered_deck(DeckId(deck["id"]))
        if any(
            name in term.search
            for term in filtered.config.search_terms
            for name in names
        ):
            count += 1
    return count


def apply_emoji_migration(col: Collection, ids: IdCollection[int]) -> MigrationResult:
    """Apply selected ready entries, preserving other entries on individual failure."""
    selected = set(ids)
    plan = plan_emoji_migration(col)
    ready = [
        item for item in plan if item.deck_id in selected and item.status == "ready"
    ]
    skipped = len(selected) - len(ready)
    if not ready:
        return MigrationResult(0, skipped, 0)
    undo = col.add_custom_undo_entry("Rename deck emoji")
    ok = failed = 0
    for item in ready:
        try:
            col.decks.rename(DeckId(item.deck_id), item.new)
        except Exception:
            logger.exception("Could not migrate deck %s", item.deck_id)
            failed += 1
        else:
            ok += 1
    changes = col.merge_undo_entries(undo)
    return MigrationResult(ok, skipped, failed, changes)
