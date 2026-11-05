"""Curated emoji choices for new decks."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EmojiGroup:
    key: str
    emojis: tuple[str, ...]


EMOJI_GROUPS: tuple[EmojiGroup, ...] = (
    EmojiGroup(
        key="study",
        emojis=(
            "📚",
            "📖",
            "📒",
            "📔",
            "📓",
            "📕",
            "📗",
            "📘",
            "📙",
            "✏️",
            "📝",
            "📐",
            "📏",
            "🎓",
            "🧪",
            "🔬",
            "🧬",
            "🔭",
        ),
    ),
    EmojiGroup(
        key="nature",
        emojis=(
            "🌱",
            "🌿",
            "🌳",
            "🌵",
            "🌻",
            "🌷",
            "🍀",
            "🍄",
            "🐝",
            "🦋",
            "🐱",
            "🐶",
            "🐬",
            "🦊",
            "☀️",
            "🌧️",
            "🌈",
            "🌙",
        ),
    ),
    EmojiGroup(
        key="fun",
        emojis=(
            "⚽",
            "🏀",
            "🏈",
            "⚾",
            "🎾",
            "🏓",
            "🎮",
            "🎲",
            "🎯",
            "🎸",
            "🎹",
            "🎵",
            "🎤",
            "🍎",
            "🍕",
            "🍦",
            "🍰",
            "🍣",
        ),
    ),
    EmojiGroup(
        key="world",
        emojis=(
            "🌍",
            "🌎",
            "🌏",
            "🗺️",
            "🧭",
            "🏠",
            "🏰",
            "🗼",
            "🗽",
            "🏝️",
            "🏔️",
            "🏕️",
            "🚀",
            "✈️",
            "🚂",
            "🇩🇪",
            "🇫🇷",
            "🇯🇵",
        ),
    ),
)

ALL_EMOJI: frozenset[str] = frozenset(
    emoji for group in EMOJI_GROUPS for emoji in group.emojis
)
