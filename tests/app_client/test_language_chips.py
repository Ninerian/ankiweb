# ruff: noqa: RUF001 - catalog tests intentionally include look-alike characters.
import pytest

from ankiweb.core.app_client.deck_languages import LANGUAGES
from ankiweb.core.app_client.language_chips import language_chips


@pytest.mark.parametrize("language", [language.code for language in LANGUAGES])
def test_catalog_values_are_unique_and_insert_exact_text(language: str) -> None:
    chips = language_chips(language)
    values = [chip.value for chip in chips]
    assert len(values) == len(set(values))
    assert all(chip.label for chip in chips)
    for chip in chips:
        assert chip.value in (chip.label, chip.label + " ")
        if chip.value.endswith(" "):
            assert not chip.label.endswith(" ")
            assert not chip.value.endswith("  ")
        if "'" in chip.label or chip.label == "ال":
            assert chip.value == chip.label
    assert bool(chips) == (language != "ko")


@pytest.mark.parametrize(
    ("language", "articles", "attached", "characters"),
    [
        ("de", "der die das", "", "ä Ä ö Ö ü Ü ß ẞ"),
        ("en", "a an the", "", ""),
        ("es", "el la los las un una", "", "á Á é É í Í ó Ó ú Ú ü Ü ñ Ñ ¿ ¡"),
        (
            "fr",
            "le la les un une",
            "l'",
            "à À â Â æ Æ ç Ç é É è È ê Ê ë Ë î Î ï Ï ô Ô œ Œ ù Ù û Û ü Ü ÿ Ÿ",
        ),
        ("it", "il lo la i gli le un uno una", "l' un'", "à À è È é É ì Ì ò Ò ù Ù"),
        (
            "pt",
            "o a os as um uma",
            "",
            "á Á à À â Â ã Ã ç Ç é É ê Ê í Í ó Ó ô Ô õ Õ ú Ú",
        ),
        ("nl", "de het een", "", "é É ë Ë ï Ï"),
        ("pl", "", "", "ą Ą ć Ć ę Ę ł Ł ń Ń ó Ó ś Ś ź Ź ż Ż"),
        ("tr", "", "", "ç Ç ğ Ğ ı İ ö Ö ş Ş ü Ü"),
        ("ru", "", "", "ё Ё"),
        ("ja", "", "", "「 」 、 。 ー"),
        ("zh", "", "", "《 》 、 。 ？ ！"),
        ("ko", "", "", ""),
        ("ar", "", "ال", "أ إ آ ؤ ئ ء ى ة"),
        ("sv", "en ett", "", "å Å ä Ä ö Ö"),
        ("la", "", "", "ā Ā ē Ē ī Ī ō Ō ū Ū ȳ Ȳ"),
    ],
)
def test_catalog_contains_expected_ordered_chips(
    language: str, articles: str, attached: str, characters: str
) -> None:
    expected = [(word, word + " ") for word in articles.split()]
    expected += [(word, word) for word in attached.split()]
    expected += [(character, character) for character in characters.split()]
    assert [(chip.label, chip.value) for chip in language_chips(language)] == expected


@pytest.mark.parametrize("language", ["ko", "unknown", ""])
def test_no_chips_for_unsupported_or_no_help_language(language: str) -> None:
    assert language_chips(language) == ()
