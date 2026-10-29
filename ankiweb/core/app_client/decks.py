"""Deck list rows for the app client's home page."""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from anki.collection import Collection
from anki.decks import DEFAULT_DECK_ID

from ankiweb.core.app_client.deck_progress import progress_by_deck
from ankiweb.core.app_client.emoji_picker import ALL_EMOJI
from ankiweb.core.app_client.revlog import studied_by_deck

DEFAULT_EMOJI = "🗂️"
_ZWJ = "\u200d"
_KEYCAP = "\u20e3"
_VARIATION_SELECTOR = "\ufe0f"
_KEYCAP_BASES = "0123456789#*"
_TAG_FIRST = "\U000e0020"
_TAG_LAST = "\U000e007f"


@dataclass(frozen=True)
class DeckRow:
    deck_id: int
    name: str
    emoji: str
    due: int
    new: int
    progress_pct: int
    changes: object | None = field(default=None, compare=False, repr=False)


class DeckNameError(Exception):
    def __init__(self, kind: Literal["empty", "too_long", "invalid", "taken"]) -> None:
        self.kind = kind
        super().__init__(kind)


def _is_regional_indicator(char: str) -> bool:
    return "\U0001f1e6" <= char <= "\U0001f1ff"


def _is_pictograph(char: str) -> bool:
    return unicodedata.category(char) == "So" and not _is_regional_indicator(char)


def _modifier_end(text: str, index: int) -> int:
    """Skip variation selectors, skin tones, keycap marks and emoji tags."""
    while index < len(text) and (
        text[index] in (_VARIATION_SELECTOR, _KEYCAP)
        or unicodedata.category(text[index]) == "Sk"
        or _TAG_FIRST <= text[index] <= _TAG_LAST
    ):
        index += 1
    return index


def _emoji_end(text: str) -> int:
    """Return the end index of the leading emoji grapheme, or 0 if there is none."""
    if not text:
        return 0
    if _is_regional_indicator(text[0]):
        pair = len(text) > 1 and _is_regional_indicator(text[1])
        return 2 if pair else 0
    if text[0] in _KEYCAP_BASES:
        end = 2 if text[1:2] == _VARIATION_SELECTOR else 1
        return end + 1 if text[end : end + 1] == _KEYCAP else 0
    if not _is_pictograph(text[0]):
        return 0
    end = _modifier_end(text, 1)
    while end + 1 < len(text) and text[end] == _ZWJ and _is_pictograph(text[end + 1]):
        end = _modifier_end(text, end + 2)
    return end


def split_emoji(name: str) -> tuple[str, str]:
    """Split an emoji suffix from a deck name, or use the default emoji."""
    display_name, separator, emoji = name.rpartition(" · ")
    if (
        not separator
        or not display_name.strip()
        or _emoji_end(emoji) != len(emoji)
        or not emoji
    ):
        return DEFAULT_EMOJI, name
    return emoji, display_name.strip()


def join_emoji(name: str, emoji: str) -> str:
    """Join a deck name and exactly one emoji grapheme."""
    if not emoji or _emoji_end(emoji) != len(emoji):
        raise ValueError("emoji must be exactly one emoji grapheme")
    return f"{name.strip()} · {emoji}"


def _emoji_only(name: str) -> bool:
    while name:
        end = _emoji_end(name)
        if not end:
            return False
        name = name[end:].lstrip()
    return True


def _comparison_name(name: str) -> str:
    return unicodedata.normalize("NFC", name.casefold())


def create_deck(col: Collection, name: str, emoji: str) -> DeckRow:
    """Create a root deck; names consisting only of emoji are invalid."""
    name = unicodedata.normalize("NFC", name)
    name = "".join(c for c in name if not (c.isascii() and not c.isprintable()))
    name = re.sub(r"^[\s:]+|[\s:]+$", "", name)
    if not name:
        raise DeckNameError("empty")
    if len(name) > 40:
        raise DeckNameError("too_long")
    if "::" in name or emoji not in ALL_EMOJI or _emoji_only(name):
        raise DeckNameError("invalid")
    comparison_name = _comparison_name(name)
    if any(
        _comparison_name(split_emoji(deck.name)[1]) == comparison_name
        for deck in col.decks.all_names_and_ids()
        if "::" not in deck.name
    ):
        raise DeckNameError("taken")
    result = col.decks.add_normal_deck_with_name(join_emoji(name, emoji))
    return DeckRow(
        deck_id=result.id,
        name=name,
        emoji=emoji,
        due=0,
        new=0,
        progress_pct=0,
        changes=result.changes,
    )


def deck_rows(col: Collection) -> list[DeckRow]:
    """Return root decks in Anki's order with their counts and daily progress."""
    roots = [
        node
        for node in col.sched.deck_due_tree().children
        if not node.filtered
        and not (node.deck_id == DEFAULT_DECK_ID and node.total_including_children == 0)
    ]
    progress = progress_by_deck(studied_by_deck(col), roots)
    rows = []
    for node in roots:
        emoji, name = split_emoji(node.name)
        rows.append(
            DeckRow(
                deck_id=node.deck_id,
                name=name,
                emoji=emoji,
                due=node.review_count + node.learn_count,
                new=node.new_count,
                progress_pct=progress[node.deck_id],
            )
        )
    return rows
