from pathlib import Path

import anki.lang
import pytest
from fastapi.testclient import TestClient

from ankiweb.adapters.inbound.http_app.layout import render_app_page
from ankiweb.adapters.inbound.http_shared.templating import render
from ankiweb.app import create_app
from ankiweb.core.app_client.lang import ResolvedLang, resolve_lang
from ankiweb.core.config import Settings
from ankiweb.core.i18n import tr


def test_layout_defaults_to_english_and_accepts_explicit_language() -> None:
    default_page = render_app_page("Title", "<main>Content</main>", active="")
    assert '<html lang="en" dir="ltr">' in default_page
    arabic_page = render(
        "app/base.html.jinja",
        title="Title",
        body="<main>Content</main>",
        scripts=(),
        app_lang=ResolvedLang("ar", "rtl", "ar"),
    )
    assert '<html lang="ar" dir="rtl">' in arabic_page


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("de_DE", ResolvedLang("de", "ltr", "de")),
        ("ar_SA", ResolvedLang("ar", "rtl", "ar")),
        ("fa_IR", ResolvedLang("en", "ltr", "en")),
        ("xx", ResolvedLang("en", "ltr", "en")),
        ("no", ResolvedLang("en", "ltr", "en")),
        ("nb", ResolvedLang("nb", "ltr", "nb")),
    ],
)
def test_ping_uses_startup_language_not_accept_language(
    tmp_path: Path,
    code: str,
    expected: ResolvedLang,
) -> None:
    settings = Settings(collection_path=tmp_path / "collection.anki2", lang=code)
    with TestClient(create_app(settings)) as client:
        first = client.get("/app/ping", headers={"Accept-Language": "ar,fr;q=0.9"})
        second = client.get("/app/ping", headers={"Accept-Language": "de,en;q=0.9"})

    assert first.status_code == second.status_code == 200
    assert first.text == second.text
    assert f'<html lang="{expected.html_lang}" dir="{expected.html_dir}">' in first.text


@pytest.mark.parametrize(
    ("code", "html_lang", "translated"),
    [("no", "en", "Again"), ("nb", "nb", "Igjen"), ("nb_NO", "nb-NO", "Igjen")],
)
def test_layout_language_matches_rendered_anki_text(
    tmp_path: Path, code: str, html_lang: str, translated: str
) -> None:
    settings = Settings(collection_path=tmp_path / "collection.anki2", lang=code)
    with TestClient(create_app(settings)) as client:
        response = client.get("/app/ping")
        anki.lang.set_lang(code)
        page = render(
            "app/base.html.jinja",
            title=tr.studying_again(),
            body="",
            scripts=(),
            app_lang=resolve_lang(settings),
        )
    assert f'<html lang="{html_lang}" dir="ltr">' in response.text
    assert f'<html lang="{html_lang}" dir="ltr">' in page
    assert f"<title>{translated}</title>" in page
