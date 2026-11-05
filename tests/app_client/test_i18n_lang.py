from html import escape
from pathlib import Path

import anki.lang
import pytest
from fastapi.testclient import TestClient

from ankiweb.app import create_app
from ankiweb.core.app_client.lang import ResolvedLang, resolve_lang
from ankiweb.core.config import Settings


@pytest.mark.parametrize(
    ("code", "html_lang", "html_dir", "catalog_lang"),
    [
        ("", "en", "ltr", "en"),
        ("en", "en", "ltr", "en"),
        ("en_AU", "en-GB", "ltr", "en"),
        ("en-Latn-US", "en", "ltr", "en"),
        ("zh", "zh-CN", "ltr", "zh"),
        ("zh-cn", "zh-CN", "ltr", "zh"),
        ("zh_CN", "zh-CN", "ltr", "zh"),
        ("zh-CN", "zh-CN", "ltr", "zh"),
        ("zh-Hans-CN", "zh-CN", "ltr", "zh"),
        ("zh-Hant-TW", "zh-TW", "ltr", "zh"),
        ("zh_HK", "zh-TW", "ltr", "zh"),
        ("de_DE", "de", "ltr", "de"),
        ("de-DE-1901", "de", "ltr", "de"),
        ("DE", "de", "ltr", "de"),
        ("de_DE.UTF-8", "en", "ltr", "en"),
        ("pt", "pt-BR", "ltr", "pt"),
        ("pt_BR", "pt-BR", "ltr", "pt"),
        ("pt_PT", "pt-PT", "ltr", "pt"),
        ("ga", "ga-IE", "ltr", "ga"),
        ("hy", "hy-AM", "ltr", "hy"),
        ("sv_FI", "sv-SE", "ltr", "sv"),
        ("nb_NO", "nb-NO", "ltr", "nb"),
        ("no", "en", "ltr", "en"),
        ("nb", "nb-NO", "ltr", "nb"),
        ("nb_NL", "nb-NO", "ltr", "nb"),
        ("nb_XX", "nb-NO", "ltr", "nb"),
        ("nb-Foo", "en", "ltr", "en"),
        ("nb-123", "nb-NO", "ltr", "nb"),
        ("ar", "ar", "rtl", "ar"),
        ("AR", "ar", "rtl", "ar"),
        ("ar_SA", "ar", "rtl", "ar"),
        ("ar-Arab-SA", "ar", "rtl", "ar"),
        ("he", "he", "rtl", "he"),
        ("HE", "he", "rtl", "he"),
        ("fa", "en", "ltr", "en"),
        ("fa_IR", "en", "ltr", "en"),
        ("xx", "en", "ltr", "en"),
    ],
)
def test_resolve_lang(
    tmp_path: Path, code: str, html_lang: str, html_dir: str, catalog_lang: str
) -> None:
    settings = Settings(collection_path=tmp_path / "collection.anki2", lang=code)
    result = resolve_lang(settings)
    assert result == ResolvedLang(html_lang, html_dir, catalog_lang)
    assert anki_text(code) == anki_text(result.html_lang)


def anki_text(code: str) -> tuple[str, str]:
    try:
        anki.lang.set_lang(code)
        tr = anki.lang.tr_legacyglobal
        return tr.actions_decks(), tr.studying_again()
    finally:
        anki.lang.set_lang("en")


@pytest.mark.parametrize("code", [code for _, code in anki.lang.langs])
def test_all_available_languages(tmp_path: Path, code: str) -> None:
    settings = Settings(collection_path=tmp_path / "collection.anki2", lang=code)
    result = resolve_lang(settings)
    base = result.html_lang.split("-")[0]
    assert anki_text(code) == anki_text(result.html_lang)
    assert result.html_dir == ("rtl" if base in {"ar", "he", "ug", "yi"} else "ltr")
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
    try:
        anki.lang.set_lang(code)
        tr = anki.lang.tr_legacyglobal
        assert (tr.actions_add(), tr.actions_decks(), tr.studying_again()) == expected
    finally:
        anki.lang.set_lang("en")


def test_resolution_uses_settings_not_global_language(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANKIWEB_LANG", "ar")
    try:
        anki.lang.set_lang("ar")
        settings = Settings(collection_path=tmp_path / "collection.anki2", lang="de_DE")
        assert resolve_lang(settings) == ResolvedLang("de", "ltr", "de")
        anki.lang.set_lang("xx")
        assert resolve_lang(settings) == ResolvedLang("de", "ltr", "de")
    finally:
        anki.lang.set_lang("en")


@pytest.mark.parametrize(
    ("code", "html_lang", "html_dir", "reference", "different"),
    [
        ("", "en", "ltr", "en", "de_DE"),
        ("zh_HK", "zh-TW", "ltr", "zh_TW", "zh_CN"),
        ("ga", "ga-IE", "ltr", "ga_IE", "en"),
        ("pt_AO", "pt-BR", "ltr", "pt_BR", "pt_PT"),
        ("pt", "pt-BR", "ltr", "pt_BR", "pt_PT"),
        ("De", "de", "ltr", "de_DE", "en"),
        ("nb-123", "nb-NO", "ltr", "nb_NO", "en"),
        ("zh-Hant", "zh-CN", "ltr", "zh_CN", "zh_TW"),
        ("zh-Hans-HK", "zh-TW", "ltr", "zh_TW", "zh_CN"),
        ("de-Foo", "en", "ltr", "en", "de_DE"),
        ("sv_FI", "sv-SE", "ltr", "sv_SE", "en"),
        ("ar_SA", "ar", "rtl", "ar", "en"),
    ],
)
def test_rendered_language_matches_anki_translation(
    tmp_path: Path,
    code: str,
    html_lang: str,
    html_dir: str,
    reference: str,
    different: str,
) -> None:
    tr = anki.lang.tr_legacyglobal
    try:
        anki.lang.set_lang(reference)
        expected = (tr.actions_decks(), tr.studying_again())
        anki.lang.set_lang(different)
        assert (tr.actions_decks(), tr.studying_again()) != expected

        settings = Settings(collection_path=tmp_path / "collection.anki2", lang=code)
        with TestClient(create_app(settings)) as client:
            response = client.get("/app/")
            translated = (tr.actions_decks(), tr.studying_again())
    finally:
        anki.lang.set_lang("en")

    assert response.status_code == 200
    assert translated == expected
    assert f'<html lang="{html_lang}" dir="{html_dir}">' in response.text
    assert f"<title>{escape(expected[0])}</title>" in response.text
