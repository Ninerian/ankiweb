import json
from dataclasses import dataclass

import anki._backend
import anki.lang

from ankiweb.core.config import Settings


@dataclass(frozen=True)
class ResolvedLang:
    html_lang: str
    html_dir: str
    catalog_lang: str


def _disk_lang(locale: str) -> str:
    parts = locale.split("-")
    base = parts[0]
    # Anki remaps these languages to region-specific bundles independently of
    # lang_to_disk_lang(). In particular, scripts do not select Chinese bundles.
    if base == "zh":
        if "HK" in parts and "Hans" not in parts:
            return "zh-HK"
        if "HK" in parts or "TW" in parts:
            return "zh-TW"
        return "zh-CN"
    if base == "pt":
        return "pt-PT" if "PT" in parts else "pt-BR"
    if base == "en":
        return "en-GB" if locale == "en-GB" else "en"
    if base == "ga":
        return "ga-IE"
    disk = anki.lang.lang_to_disk_lang(locale)
    return base if "_" in disk else disk


def resolve_lang(settings: Settings) -> ResolvedLang:
    """Resolve the startup language for the app's HTML and custom catalog."""
    # set_lang() builds the same backend from the original setting. Its reported
    # locales contain only successfully loaded bundles, followed by English.
    backend = anki._backend.RustBackend(langs=[settings.lang or "en"])
    locale = json.loads(backend.i18n_resources(modules=["actions"]))["langs"][0]
    disk = _disk_lang(locale)
    base = disk.split("-")[0]
    return ResolvedLang(disk, "rtl" if anki.lang.is_rtl(base) else "ltr", base)
