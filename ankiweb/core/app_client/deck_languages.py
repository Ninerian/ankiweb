"""Language pairs and description markers for decks."""

import re
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "LANGUAGES",
    "DeckLanguageError",
    "Language",
    "LanguagePair",
    "apply_marker",
    "choose",
    "read_marker",
    "strip_marker",
]


@dataclass(frozen=True)
class Language:
    """A supported language and its display flag."""

    code: str
    flag: str


LANGUAGES: tuple[Language, ...] = (
    Language("de", "🇩🇪"),
    Language("en", "🇬🇧"),
    Language("es", "🇪🇸"),
    Language("fr", "🇫🇷"),
    Language("it", "🇮🇹"),
    Language("pt", "🇵🇹"),
    Language("nl", "🇳🇱"),
    Language("pl", "🇵🇱"),
    Language("tr", "🇹🇷"),
    Language("ru", "🇷🇺"),
    Language("ja", "🇯🇵"),
    Language("zh", "🇨🇳"),
    Language("ko", "🇰🇷"),
    Language("ar", "🇸🇦"),
    Language("sv", "🇸🇪"),
    Language("la", "🏛️"),
)
_LANGUAGE_CODES = frozenset(language.code for language in LANGUAGES)
_MARKER = re.compile(r"<!--ankiweb:lang=([a-z]{2,3})>([a-z]{2,3})-->")


class DeckLanguageError(Exception):
    """An invalid language choice, identified by its kind."""

    def __init__(self, kind: Literal["same", "unknown", "incomplete"]) -> None:
        self.kind = kind
        super().__init__(kind)


@dataclass(frozen=True)
class LanguagePair:
    """A pair of distinct supported language codes."""

    src: str
    dst: str

    def __post_init__(self) -> None:
        if self.src not in _LANGUAGE_CODES or self.dst not in _LANGUAGE_CODES:
            raise DeckLanguageError("unknown")
        if self.src == self.dst:
            raise DeckLanguageError("same")


def read_marker(desc: str) -> LanguagePair | None:
    """Read the first matching marker, ignoring an invalid pair."""
    match = _MARKER.search(desc)
    if match is None:
        return None
    try:
        return LanguagePair(match.group(1), match.group(2))
    except DeckLanguageError:
        return None


def strip_marker(desc: str) -> str:
    """Remove all matching markers without changing surrounding text."""
    return _MARKER.sub("", desc)


def apply_marker(desc: str, pair: LanguagePair | None) -> str:
    """Replace all matching markers with one leading marker, or none."""
    desc = strip_marker(desc)
    if pair is None:
        return desc
    return f"<!--ankiweb:lang={pair.src}>{pair.dst}-->{desc}"


def choose(mode: str, src: str, dst: str) -> LanguagePair | None:
    """Convert a language selection into a validated pair or no pair."""
    if mode == "none":
        return None
    if mode != "langs":
        raise DeckLanguageError("unknown")
    if not src or not dst:
        raise DeckLanguageError("incomplete")
    return LanguagePair(src, dst)
