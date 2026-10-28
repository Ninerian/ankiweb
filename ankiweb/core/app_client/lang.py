from dataclasses import dataclass

import anki.lang

from ankiweb.core.config import Settings


@dataclass(frozen=True)
class ResolvedLang:
    html_lang: str
    html_dir: str
    catalog_lang: str


def resolve_lang(settings: Settings) -> ResolvedLang:
    """Resolve the startup language for the app's HTML and custom catalog."""
    disk = anki.lang.lang_to_disk_lang(settings.lang or "en")
    known = {anki.lang.lang_to_disk_lang(code) for _, code in anki.lang.langs}
    # "no" normalizes to "nb" but Anki translates it as English. Direct "nb"
    # locales do translate, even though only nb-NO appears in the language list.
    parts = settings.lang.replace("_", "-").split("-")
    nb_locale = (
        disk == "nb"
        and parts[0] == "nb"
        and (
            len(parts) == 1
            or (
                len(parts) == 2
                and len(parts[1]) == 2
                and parts[1].isascii()
                and parts[1].isalpha()
            )
        )
    )
    # Anki 26.9.2's Persian bundle fails to parse and falls back to English
    # (observed 2026-10-28). The regression test should fail when upstream fixes it.
    if disk == "fa" or (disk not in known and not nb_locale):
        disk = "en"
    base = disk.split("-")[0].split("_")[0]
    return ResolvedLang(disk, "rtl" if anki.lang.is_rtl(base) else "ltr", base)
