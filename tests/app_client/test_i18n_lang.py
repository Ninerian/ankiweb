from pathlib import Path

import anki.lang
import pytest

from ankiweb.core.app_client.lang import ResolvedLang, resolve_lang
from ankiweb.core.config import Settings


@pytest.mark.parametrize(
    ("code", "html_lang", "html_dir", "catalog_lang"),
    [
        ("", "en", "ltr", "en"),
        ("en", "en", "ltr", "en"),
        ("zh_CN", "zh-CN", "ltr", "zh"),
        ("zh-CN", "zh-CN", "ltr", "zh"),
        ("de_DE", "de", "ltr", "de"),
        ("pt_BR", "pt-BR", "ltr", "pt"),
        ("nb_NO", "nb-NO", "ltr", "nb"),
        ("no", "en", "ltr", "en"),
        ("nb", "nb", "ltr", "nb"),
        ("nb_NL", "nb", "ltr", "nb"),
        ("nb_XX", "nb", "ltr", "nb"),
        ("nb-Foo", "en", "ltr", "en"),
        ("nb-123", "en", "ltr", "en"),
        ("ar", "ar", "rtl", "ar"),
        ("ar_SA", "ar", "rtl", "ar"),
        ("he", "he", "rtl", "he"),
        ("fa", "en", "ltr", "en"),
        ("fa_IR", "en", "ltr", "en"),
        ("xx", "en", "ltr", "en"),
    ],
)
def test_resolve_lang(
    tmp_path: Path, code: str, html_lang: str, html_dir: str, catalog_lang: str
) -> None:
    settings = Settings(collection_path=tmp_path / "collection.anki2", lang=code)
    assert resolve_lang(settings) == ResolvedLang(html_lang, html_dir, catalog_lang)


@pytest.mark.parametrize("code", [code for _, code in anki.lang.langs])
def test_all_available_languages(tmp_path: Path, code: str) -> None:
    settings = Settings(collection_path=tmp_path / "collection.anki2", lang=code)
    disk = anki.lang.lang_to_disk_lang(code)
    expected = "en" if disk == "fa" else disk
    base = expected.split("-")[0].split("_")[0]
    result = resolve_lang(settings)
    assert result.html_lang == expected
    assert result.html_dir == ("rtl" if anki.lang.is_rtl(base) else "ltr")
    assert result.catalog_lang == base


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("fa", ("Add", "Decks", "Again")),
        ("fa_IR", ("Add", "Decks", "Again")),
        ("no", ("Add", "Decks", "Again")),
        ("nb", ("Legg til", "Kortstokker", "Igjen")),
        ("nb_NO", ("Legg til", "Kortstokker", "Igjen")),
    ],
)
def test_anki_bundle_fallbacks(code: str, expected: tuple[str, str, str]) -> None:
    # Fail when upstream fixes the Persian bundle or changes Norwegian alias behavior.
    anki.lang.set_lang(code)
    tr = anki.lang.tr_legacyglobal
    assert (tr.actions_add(), tr.actions_decks(), tr.studying_again()) == expected


def test_resolution_uses_settings_not_global_language(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKIWEB_LANG", "ar")
    anki.lang.set_lang("ar")
    settings = Settings(collection_path=tmp_path / "collection.anki2", lang="de_DE")
    assert resolve_lang(settings) == ResolvedLang("de", "ltr", "de")
    anki.lang.set_lang("xx")
    assert resolve_lang(settings) == ResolvedLang("de", "ltr", "de")
