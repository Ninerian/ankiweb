import pytest

from ankiweb.core.app_client.deck_languages import (
    LANGUAGES,
    DeckLanguageError,
    LanguagePair,
    apply_marker,
    choose,
    read_marker,
    strip_marker,
)


def test_supported_language_catalog() -> None:
    assert [(language.code, language.flag) for language in LANGUAGES] == [
        ("de", "🇩🇪"),
        ("en", "🇬🇧"),
        ("es", "🇪🇸"),
        ("fr", "🇫🇷"),
        ("it", "🇮🇹"),
        ("pt", "🇵🇹"),
        ("nl", "🇳🇱"),
        ("pl", "🇵🇱"),
        ("tr", "🇹🇷"),
        ("ru", "🇷🇺"),
        ("ja", "🇯🇵"),
        ("zh", "🇨🇳"),
        ("ko", "🇰🇷"),
        ("ar", "🇸🇦"),
        ("sv", "🇸🇪"),
        ("la", "🏛️"),
    ]


@pytest.mark.parametrize(
    "code",
    [
        "de",
        "en",
        "es",
        "fr",
        "it",
        "pt",
        "nl",
        "pl",
        "tr",
        "ru",
        "ja",
        "zh",
        "ko",
        "ar",
        "sv",
        "la",
    ],
)
def test_every_supported_language_can_be_source_or_target(code: str) -> None:
    other = "de" if code == "en" else "en"
    source_pair = choose("langs", code, other)
    target_pair = choose("langs", other, code)
    assert source_pair is not None
    assert target_pair is not None
    assert (source_pair.src, source_pair.dst) == (code, other)
    assert (target_pair.src, target_pair.dst) == (other, code)


@pytest.mark.parametrize(
    ("marked", "plain"),
    [
        (
            '<p title="x &amp; y">ä<!--ankiweb:lang=de>en--><br>  text</p>',
            '<p title="x &amp; y">ä<br>  text</p>',
        ),
        (
            "# Heading\n<!--ankiweb:lang=de>en-->\n- **one**\n- [two](url)",
            "# Heading\n\n- **one**\n- [two](url)",
        ),
        (
            "\r\nFirst\r\n<!--ankiweb:lang=de>en-->Second\r\n",
            "\r\nFirst\r\nSecond\r\n",
        ),
        (
            " \t  <!--ankiweb:lang=de>en-->  leading\n    indented\n",
            " \t    leading\n    indented\n",
        ),
    ],
)
def test_marker_changes_preserve_description_bytes(marked: str, plain: str) -> None:
    pair = LanguagePair("fr", "ja")
    assert strip_marker(marked).encode("utf-8") == plain.encode("utf-8")
    assert apply_marker(marked, None).encode("utf-8") == plain.encode("utf-8")
    assert apply_marker(marked, pair).encode("utf-8") == (
        "<!--ankiweb:lang=fr>ja-->" + plain
    ).encode("utf-8")


def test_reads_first_marker_and_relocates_it_to_front() -> None:
    description = "  Intro\n<!--ankiweb:lang=de>en-->body"
    pair = read_marker(description)
    assert pair == LanguagePair("de", "en")
    assert apply_marker(description, pair) == "<!--ankiweb:lang=de>en-->  Intro\nbody"


def test_multiple_markers_read_first_and_are_canonicalized() -> None:
    description = (
        "A<!--ankiweb:lang=de>en-->B<!--ankiweb:lang=fr>es-->"
        "C<!--ankiweb:lang=xx>en-->D"
    )
    assert read_marker(description) == LanguagePair("de", "en")
    assert strip_marker(description) == "ABCD"
    assert apply_marker(description, LanguagePair("ja", "ko")) == (
        "<!--ankiweb:lang=ja>ko-->ABCD"
    )


def test_unknown_first_marker_does_not_fall_through_to_valid_marker() -> None:
    description = "<!--ankiweb:lang=xx>en-->a<!--ankiweb:lang=de>en-->b"
    assert read_marker(description) is None
    assert strip_marker(description) == "ab"


def test_same_language_marker_is_not_a_valid_pair() -> None:
    assert read_marker("<!--ankiweb:lang=en>en-->") is None


def test_no_marker_and_unrecognized_comment_are_preserved() -> None:
    description = "  <!--ankiweb:lang=DE>en-->\nbody"
    assert read_marker(description) is None
    assert strip_marker(description) == description
    assert apply_marker(description, None) == description


def test_removing_only_marker_leaves_empty_description() -> None:
    description = "<!--ankiweb:lang=de>en-->"
    assert strip_marker(description) == ""
    assert apply_marker(description, None) == ""


@pytest.mark.parametrize(
    ("pair", "expected"),
    [
        (LanguagePair("de", "en"), "<!--ankiweb:lang=de>en-->  Hello\nworld"),
        (None, "  Hello\nworld"),
    ],
)
def test_applying_marker_is_idempotent(
    pair: LanguagePair | None, expected: str
) -> None:
    description = "  Hello<!--ankiweb:lang=fr>es-->\nworld"
    once = apply_marker(description, pair)
    assert once == expected
    assert apply_marker(once, pair) == expected


def test_choose_valid_languages() -> None:
    pair = choose("langs", "de", "en")
    assert pair == LanguagePair("de", "en")


@pytest.mark.parametrize("src,dst", [("", ""), ("de", ""), ("", "en")])
def test_choose_incomplete_languages(src: str, dst: str) -> None:
    with pytest.raises(DeckLanguageError) as error:
        choose("langs", src, dst)
    assert error.value.kind == "incomplete"


def test_same_languages_raise_same_error() -> None:
    with pytest.raises(DeckLanguageError) as error:
        choose("langs", "de", "de")
    assert error.value.kind == "same"
    with pytest.raises(DeckLanguageError) as direct_error:
        LanguagePair("de", "de")
    assert direct_error.value.kind == "same"


@pytest.mark.parametrize("src,dst", [("xx", "en"), ("de", "xx"), ("xx", "xx")])
def test_unknown_languages_raise_unknown_error(src: str, dst: str) -> None:
    with pytest.raises(DeckLanguageError) as error:
        choose("langs", src, dst)
    assert error.value.kind == "unknown"


@pytest.mark.parametrize(
    "src,dst", [("", ""), ("de", "en"), ("de", "de"), ("xx", "en")]
)
def test_none_mode_ignores_language_selection(src: str, dst: str) -> None:
    assert choose("none", src, dst) is None


@pytest.mark.parametrize("mode", ["", "language", "LANGS", "None"])
def test_invalid_mode_raises_unknown_error(mode: str) -> None:
    with pytest.raises(DeckLanguageError) as error:
        choose(mode, "de", "en")
    assert error.value.kind == "unknown"
