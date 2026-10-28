import anki.lang
import pytest
from jinja2 import Environment

from ankiweb.adapters.inbound.http_shared.templating import _env
from ankiweb.core.app_client.lang import ResolvedLang
from ankiweb.core.app_client.strings import STRINGS, s


def test_catalog_uses_explicit_language_and_formats_values() -> None:
    assert s("app_decks_learn_deck", lang="en", deck="Biology") == "Learn Biology"
    assert s("app_decks_learn_deck", lang="de", deck="Biologie") == "Biologie lernen"


def test_catalog_falls_back_per_key_and_for_unknown_languages(monkeypatch) -> None:
    monkeypatch.delitem(STRINGS["de"], "app_decks_no_results")
    assert s("app_decks_no_results", lang="de") == "No decks found"
    assert s("app_decks_no_results", lang="fr") == "No decks found"
    assert s("app_decks_no_results", lang="xx") == "No decks found"
    assert s("app_decks_learn_deck", lang="fr", deck="Biology") == "Learn Biology"


def test_catalog_rejects_unknown_key_and_missing_format_argument() -> None:
    for lang in ("en", "de", "fr"):
        with pytest.raises(KeyError, match="app_not_a_real_key"):
            s("app_not_a_real_key", lang=lang)
    with pytest.raises(KeyError, match="deck"):
        s("app_decks_learn_deck", lang="de")


def test_catalog_does_not_read_anki_process_language() -> None:
    anki.lang.set_lang("de")
    assert s("app_decks_no_results", lang="en") == "No decks found"
    anki.lang.set_lang("en")
    assert s("app_decks_no_results", lang="de") == "Keine Stapel gefunden"


def test_jinja_uses_each_render_context_and_escapes_values() -> None:
    assert isinstance(_env, Environment)
    template = _env.from_string(
        '{{ s("app_decks_learn_deck", deck=deck) }} | {{ s("app_decks_no_results") }}'
    )
    english = ResolvedLang(html_lang="en", html_dir="ltr", catalog_lang="en")
    german = ResolvedLang(html_lang="de", html_dir="ltr", catalog_lang="de")
    assert template.render(app_lang=english, deck="<Birds>") == (
        "Learn &lt;Birds&gt; | No decks found"
    )
    assert template.render(app_lang=german, deck="<Vögel>") == (
        "&lt;Vögel&gt; lernen | Keine Stapel gefunden"
    )
    assert template.render(app_lang=english, deck="Cats") == (
        "Learn Cats | No decks found"
    )


def test_jinja_requires_language_context() -> None:
    template = _env.from_string('{{ s("app_decks_no_results") }}')
    with pytest.raises(KeyError, match="app_lang"):
        template.render()


def test_jinja_falls_back_to_english_and_rejects_unknown_key() -> None:
    french = ResolvedLang(html_lang="fr", html_dir="ltr", catalog_lang="fr")
    template = _env.from_string('{{ s("app_decks_no_results") }}')
    assert template.render(app_lang=french) == "No decks found"
    missing = _env.from_string('{{ s("app_not_a_real_key") }}')
    with pytest.raises(KeyError, match="app_not_a_real_key"):
        missing.render(app_lang=french)
