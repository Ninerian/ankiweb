# ruff: noqa: RUF001 - the catalog intentionally contains look-alike characters.
"""Input-helper buttons (articles and special characters) per target language."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Chip:
    """A button label and the exact text it inserts."""

    label: str
    value: str


# Articles that are followed by a space when inserted.
_ARTICLES: dict[str, str] = {
    "de": "der die das",
    "en": "a an the",
    "es": "el la los las un una",
    "fr": "le la les un une",
    "it": "il lo la i gli le un uno una",
    "pt": "o a os as um uma",
    "nl": "de het een",
    "sv": "en ett",
}

# Elided forms and prefixes that continue directly into the next word.
_ATTACHED: dict[str, str] = {
    "fr": "l'",
    "it": "l' un'",
    "ar": "ال",
}

# Lowercase and uppercase forms are listed explicitly; never derived with
# str.upper(), which is wrong for Turkish and drops the German capital ẞ.
_CHARACTERS: dict[str, str] = {
    "de": "ä Ä ö Ö ü Ü ß ẞ",
    "es": "á Á é É í Í ó Ó ú Ú ü Ü ñ Ñ ¿ ¡",
    "fr": "à À â Â æ Æ ç Ç é É è È ê Ê ë Ë î Î ï Ï ô Ô œ Œ ù Ù û Û ü Ü ÿ Ÿ",
    "it": "à À è È é É ì Ì ò Ò ù Ù",
    "pt": "á Á à À â Â ã Ã ç Ç é É ê Ê í Í ó Ó ô Ô õ Õ ú Ú",
    "nl": "é É ë Ë ï Ï",
    "pl": "ą Ą ć Ć ę Ę ł Ł ń Ń ó Ó ś Ś ź Ź ż Ż",
    "tr": "ç Ç ğ Ğ ı İ ö Ö ş Ş ü Ü",
    "ru": "ё Ё",
    "ja": "「 」 、 。 ー",
    "zh": "《 》 、 。 ？ ！",
    "ar": "أ إ آ ؤ ئ ء ى ة",
    "sv": "å Å ä Ä ö Ö",
    "la": "ā Ā ē Ē ī Ī ō Ō ū Ū ȳ Ȳ",
}


def language_chips(lang: str) -> tuple[Chip, ...]:
    """Return the buttons for a language code, or none for unknown/no-help codes."""
    articles = (Chip(word, f"{word} ") for word in _ARTICLES.get(lang, "").split())
    attached = (Chip(word, word) for word in _ATTACHED.get(lang, "").split())
    characters = (Chip(char, char) for char in _CHARACTERS.get(lang, "").split())
    return (*articles, *attached, *characters)
