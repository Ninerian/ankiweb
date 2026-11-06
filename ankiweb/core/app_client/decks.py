"""Deck list rows for the app client's home page."""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from anki.collection import Collection, OpChanges, OpChangesWithCount
from anki.decks import DEFAULT_DECK_ID, DeckDict, DeckId

from ankiweb.core.app_client.deck_languages import (
    LANGUAGES,
    LanguagePair,
    apply_marker,
    read_marker,
    replace_description,
    strip_marker,
)
from ankiweb.core.app_client.deck_progress import progress_by_deck
from ankiweb.core.app_client.emoji_picker import ALL_EMOJI
from ankiweb.core.app_client.revlog import studied_by_deck

DEFAULT_EMOJI = "🗂️"
_ALLOWED_EMOJI = frozenset(ALL_EMOJI) | frozenset(lang.flag for lang in LANGUAGES)
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
    languages: LanguagePair | None = None
    changes: object | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class DeckSettings:
    deck_id: int
    name: str
    emoji: str
    languages: LanguagePair | None
    card_count: int


class DeckNameError(Exception):
    def __init__(
        self,
        kind: Literal[
            "empty", "too_long", "invalid", "taken", "not_found", "protected"
        ],
    ) -> None:
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


def _validate_emoji(emoji: str, previous: str | None = None) -> None:
    """Allow picker choices, language flags, or an unchanged legacy emoji."""
    if emoji in _ALLOWED_EMOJI:
        return
    if emoji and emoji == previous and _emoji_end(emoji) == len(emoji):
        return
    raise DeckNameError("invalid")


def _validate_name(col: Collection, name: str, exclude_id: int | None = None) -> str:
    """Normalize a root name and reject collisions with other roots."""
    name = unicodedata.normalize("NFC", name)
    name = "".join(c for c in name if not (c.isascii() and not c.isprintable()))
    name = re.sub(r"^[\s:]+|[\s:]+$", "", name)
    if not name:
        raise DeckNameError("empty")
    if len(name) > 40:
        raise DeckNameError("too_long")
    if "::" in name or _emoji_only(name):
        raise DeckNameError("invalid")
    comparison_name = _comparison_name(name)
    if any(
        _comparison_name(split_emoji(deck.name)[1]) == comparison_name
        for deck in col.decks.all_names_and_ids()
        if "::" not in deck.name and deck.id != exclude_id
    ):
        raise DeckNameError("taken")
    return name


def create_deck(
    col: Collection, name: str, emoji: str, languages: LanguagePair | None
) -> DeckRow:
    """Create a root deck with its language marker in one operation."""
    name = _validate_name(col, name)
    _validate_emoji(emoji)
    if languages is not None and not isinstance(languages, LanguagePair):
        raise TypeError("languages must be a LanguagePair or None")
    deck = col.decks.new_deck()
    deck.name = join_emoji(name, emoji)
    deck.normal.description = apply_marker(deck.normal.description, languages)
    result = col.decks.add_deck(deck)
    return DeckRow(
        deck_id=result.id,
        name=name,
        emoji=emoji,
        due=0,
        new=0,
        progress_pct=0,
        languages=languages,
        changes=result.changes,
    )


def _root_deck(col: Collection, deck_id: int) -> DeckDict:
    deck = col.decks.get(DeckId(deck_id), default=False)
    if deck is None or deck.get("dyn") or "::" in deck["name"]:
        raise DeckNameError("not_found")
    return deck


def deck_settings(col: Collection, deck_id: int) -> DeckSettings:
    """Return editable root settings and the inclusive card count."""
    deck = _root_deck(col, deck_id)
    emoji, name = split_emoji(deck["name"])
    return DeckSettings(
        deck_id=deck_id,
        name=name,
        emoji=emoji,
        languages=read_marker(deck.get("desc", "")),
        card_count=col.decks.card_count(DeckId(deck_id), True),
    )


def update_deck_settings(
    col: Collection,
    deck_id: int,
    name: str,
    emoji: str,
    languages: LanguagePair | None,
) -> OpChanges:
    """Update a root and its descendants in a single undoable operation."""
    deck = _root_deck(col, deck_id)
    old_stored_name = deck["name"]
    old_emoji, old_name = split_emoji(deck["name"])
    name_changed = name != old_name
    if name_changed:
        name = _validate_name(col, name, exclude_id=deck_id)
    _validate_emoji(emoji, previous=old_emoji)
    if languages is not None and not isinstance(languages, LanguagePair):
        raise TypeError("languages must be a LanguagePair or None")

    if name != old_name or emoji != old_emoji:
        if (
            emoji == old_emoji
            and old_name == deck["name"]
            and split_emoji(name)[1] == name
        ):
            stored_name = name
        else:
            stored_name = join_emoji(name, emoji)
        if not name_changed and any(
            _comparison_name(other.name) == _comparison_name(stored_name)
            for other in col.decks.all_names_and_ids()
            if other.id != deck_id
        ):
            raise DeckNameError("taken")
        deck["name"] = stored_name
    desc = deck.get("desc", "")
    if languages != read_marker(desc):
        deck["desc"] = apply_marker(desc, languages)
    elif deck.get("md") and deck["name"] != old_stored_name:
        deck["desc"] = replace_description(strip_marker(desc), desc, markdown=True)
    return col.decks.update_dict(deck)


def delete_deck(col: Collection, deck_id: int) -> OpChangesWithCount:
    """Delete a root deck and its descendants, except the default deck."""
    _root_deck(col, deck_id)
    if deck_id == DEFAULT_DECK_ID:
        raise DeckNameError("protected")
    return col.decks.remove([DeckId(deck_id)])


def deck_rows(col: Collection) -> list[DeckRow]:
    """Return root decks in Anki's order with their counts and daily progress."""
    roots = [
        node
        for node in col.sched.deck_due_tree().children
        if not node.filtered
        and not (node.deck_id == DEFAULT_DECK_ID and node.total_including_children == 0)
    ]
    progress = progress_by_deck(studied_by_deck(col), roots)
    decks_by_id = {deck["id"]: deck for deck in col.decks.all()}
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
                languages=read_marker(decks_by_id[node.deck_id].get("desc", "")),
            )
        )
    return rows
