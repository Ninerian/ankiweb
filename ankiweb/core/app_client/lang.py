import re
from dataclasses import dataclass

import anki.lang

from ankiweb.core.config import Settings

# Match the language identifiers accepted by Anki's unic-langid parser:
# language, optional script, optional region, then zero or more variants.
_LANGUAGE_IDENTIFIER = re.compile(
    r"(?P<language>[a-z]{2,3}|[a-z]{5,8})"
    r"(?:[-_][a-z]{4})?"
    r"(?:[-_](?P<region>[a-z]{2}|[0-9]{3}))?"
    r"(?:[-_][a-z0-9]{4,8})*",
    re.ASCII | re.IGNORECASE,
)

_FIXED_LOCALES = {"ga": "ga-IE", "hy": "hy-AM", "nb": "nb-NO", "sv": "sv-SE"}


@dataclass(frozen=True)
class ResolvedLang:
    html_lang: str
    html_dir: str
    catalog_lang: str


def _disk_lang(language: str, region: str) -> str:
    # Keep this mapping aligned with Anki's rslib/i18n remapped_lang_name.
    if language == "en":
        return "en-GB" if region in {"GB", "AU"} else "en"
    if language == "zh":
        return "zh-TW" if region in {"TW", "HK"} else "zh-CN"
    if language == "pt":
        return "pt-PT" if region == "PT" else "pt-BR"
    return _FIXED_LOCALES.get(language, language)


def resolve_lang(settings: Settings) -> ResolvedLang:
    """Resolve the startup language for the app's HTML and custom catalog."""
    match = _LANGUAGE_IDENTIFIER.fullmatch(settings.lang or "en")
    language = match["language"].lower() if match else "en"
    region = (match["region"] or "").upper() if match else ""

    disk = _disk_lang(language, region)

    known = {anki.lang.lang_to_disk_lang(code) for _, code in anki.lang.langs}
    # Anki 26.9.2's Persian bundle fails to parse and falls back to English
    # (observed 2026-10-28). The regression test should fail when upstream fixes it.
    if disk == "fa" or disk not in known:
        disk = "en"
    base = disk.split("-")[0]
    return ResolvedLang(disk, "rtl" if anki.lang.is_rtl(base) else "ltr", base)
