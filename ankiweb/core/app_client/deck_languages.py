"""Language pairs and description markers for decks."""

import re
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "LANGUAGES",
    "DeckLanguageError",
    "Language",
    "LanguageErrorKind",
    "LanguageMode",
    "LanguagePair",
    "apply_marker",
    "choose",
    "read_marker",
    "replace_description",
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
_MARKER = re.compile(
    r"<!--ankiweb:lang=([a-z]{2,3})>([a-z]{2,3})-->"
    r"(?:<!--ankiweb:lang-separator-->\n\n)?"
)
_SEPARATOR = "<!--ankiweb:lang-separator-->\n\n"


class LanguageMode(StrEnum):
    """How a deck relates to languages; values are the wire/form values."""

    PAIR = "langs"
    NONE = "none"


class LanguageErrorKind(StrEnum):
    """Why a language choice is invalid."""

    SAME = "same"
    UNKNOWN = "unknown"
    INCOMPLETE = "incomplete"


class DeckLanguageError(Exception):
    """An invalid language choice, identified by its kind."""

    def __init__(self, kind: LanguageErrorKind) -> None:
        self.kind = kind
        super().__init__(kind)


@dataclass(frozen=True)
class LanguagePair:
    """A pair of distinct supported language codes."""

    src: str
    dst: str

    def __post_init__(self) -> None:
        if self.src not in _LANGUAGE_CODES or self.dst not in _LANGUAGE_CODES:
            raise DeckLanguageError(LanguageErrorKind.UNKNOWN)
        if self.src == self.dst:
            raise DeckLanguageError(LanguageErrorKind.SAME)


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
    """Replace matching markers with one Markdown-safe leading marker, or none."""
    desc = strip_marker(desc)
    if pair is None:
        return desc
    return f"<!--ankiweb:lang={pair.src}>{pair.dst}-->{_SEPARATOR}{desc}"


def replace_description(desc: str, previous: str, *, markdown: bool) -> str:
    """Replace visible text, preserving language metadata and legacy Markdown."""
    desc = strip_marker(desc)
    matches = tuple(_MARKER.finditer(previous))
    pair = read_marker(previous)
    needs_migration = (
        markdown
        and pair is not None
        and any(not match.group().endswith(_SEPARATOR) for match in matches)
    )
    if desc == strip_marker(previous) and not needs_migration:
        return previous

    markers = []
    for index, match in enumerate(matches):
        if index and pair is not None:
            try:
                LanguagePair(match.group(1), match.group(2))
            except DeckLanguageError:
                pass
            else:
                # Canonicalize supported duplicates, but keep unknown metadata.
                continue
        markers.append(
            f"<!--ankiweb:lang={match.group(1)}>{match.group(2)}-->{_SEPARATOR}"
        )
    return "".join(markers) + desc


def choose(mode: str, src: str, dst: str) -> LanguagePair | None:
    """Convert a language selection into a validated pair or no pair."""
    try:
        selected = LanguageMode(mode)
    except ValueError:
        raise DeckLanguageError(LanguageErrorKind.UNKNOWN) from None
    if selected is LanguageMode.NONE:
        return None
    if not src or not dst:
        raise DeckLanguageError(LanguageErrorKind.INCOMPLETE)
    return LanguagePair(src, dst)
