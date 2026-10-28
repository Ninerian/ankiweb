import inspect
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from string import Formatter

import anki.lang
import pytest
from anki.collection import Collection
from jinja2 import nodes

from ankiweb.adapters.inbound.http_shared.templating import _env
from ankiweb.core.app_client.strings import STRINGS

APP_TEMPLATES = (
    Path(__file__).resolve().parents[2]
    / "ankiweb/adapters/inbound/http_shared/templates/app"
)

# One set per plan so parallel plans each delete only entries in their own set.
# Each plan removes an entry as its templates use the key.
PRESEEDED_UNUSED_DECKS = {
    "app_decks_study_space",
    "app_decks_my_decks",
    "app_decks_search",
    "app_decks_your_decks",
    "app_decks_progress",
    "app_decks_progress_for",
    "app_decks_no_results",
    "app_decks_try_search",
    "app_decks_add_first",
    "app_decks_edit_add",
    "app_decks_learn_deck",
}
PRESEEDED_UNUSED_REVIEW = {
    "app_review_streak",
    "app_review_streak_title",
    "app_review_streak_reset",
    "app_review_streak_increase",
    "app_review_progress",
    "app_review_more_actions",
    "app_review_card_actions",
    "app_review_other_note_type",
    "app_review_no_cards_due",
    "app_review_unmark_card",
    "app_review_remove_flag",
    "app_review_marked",
    "app_review_unmarked",
    "app_review_flagged",
    "app_review_flag_removed",
    "app_review_buried",
    "app_review_suspended",
    "app_review_note_deleted",
    "app_review_complete_session",
    "app_review_complete_statistics",
    "app_review_complete_reviewed",
    "app_review_complete_recall",
    "app_review_complete_streak",
    "app_review_complete_ratings",
    "app_review_complete_recall_note",
    "app_review_complete_perfect_title",
    "app_review_complete_perfect_subtitle",
    "app_review_complete_great_title",
    "app_review_complete_great_subtitle",
    "app_review_complete_good_title",
    "app_review_complete_good_subtitle",
    "app_review_complete_tough_title",
    "app_review_complete_tough_subtitle",
    "app_review_complete_hard_extra",
    "app_review_complete_back_to_decks",
    "app_review_complete_study_again",
}
PRESEEDED_UNUSED_ADD = {
    "app_add_edit_preview",
}
PRESEEDED_UNUSED = (
    PRESEEDED_UNUSED_DECKS | PRESEEDED_UNUSED_REVIEW | PRESEEDED_UNUSED_ADD
)

# The label inventory from plan 6, section 3; each accepts a zero-argument call.
ANKI_INVENTORY = {
    "actions_decks",
    "actions_add",
    "decks_study",
    "actions_search",
    "studying_again",
    "studying_hard",
    "studying_good",
    "studying_easy",
    "studying_show_answer",
    "undo_undo",
    "studying_bury_card",
    "actions_suspend_card",
    "studying_mark_note",
    "studying_flag_card",
    "browsing_flag",
    "actions_card_info",
    "studying_delete_note",
    "actions_set_due_date",
    "statistics_counts_new_cards",
    "statistics_due_count",
    "notetypes_front_field",
    "notetypes_back_field",
    "actions_preview",
    "actions_options",
    "studying_finish",
    "actions_close",
    "actions_cancel",
    "actions_save",
}


def _custom_references(tree: nodes.Template) -> set[str]:
    custom: set[str] = set()
    for call in tree.find_all(nodes.Call):
        if not isinstance(call.node, nodes.Name) or call.node.name != "s":
            continue
        key = (
            call.args[0]
            if call.args
            else next((kw.value for kw in call.kwargs if kw.key == "key"), None)
        )
        assert isinstance(key, nodes.Const) and isinstance(key.value, str), (
            f"s() key must be a literal string at line {call.lineno}"
        )
        custom.add(key.value)
    return custom


def _anki_references(tree: nodes.Template) -> set[str]:
    anki: set[str] = set()
    for attr in tree.find_all(nodes.Getattr):
        if isinstance(attr.node, nodes.Name) and attr.node.name == "tr":
            anki.add(attr.attr)
    for item in tree.find_all(nodes.Getitem):
        if isinstance(item.node, nodes.Name) and item.node.name == "tr":
            assert isinstance(item.arg, nodes.Const) and isinstance(
                item.arg.value, str
            ), f"tr key must be a literal string at line {item.lineno}"
            anki.add(item.arg.value)
    return anki


def _references(source: str) -> tuple[set[str], set[str]]:
    tree = _env.parse(source)
    return _custom_references(tree), _anki_references(tree)


def _template_references() -> tuple[set[str], set[str]]:
    custom: set[str] = set()
    anki: set[str] = set()
    paths = sorted(APP_TEMPLATES.rglob("*.jinja"))
    assert paths, f"No app templates found in {APP_TEMPLATES}"
    for path in paths:
        custom_keys, anki_keys = _references(path.read_text(encoding="utf-8"))
        custom.update(custom_keys)
        anki.update(anki_keys)
    return custom, anki


def _anki_calls(source: str) -> list[tuple[str, nodes.Call]]:
    calls = []
    for call in _env.parse(source).find_all(nodes.Call):
        target = call.node
        if isinstance(target, nodes.Getattr):
            key = target.attr
        elif isinstance(target, nodes.Getitem) and isinstance(target.arg, nodes.Const):
            key = target.arg.value
        else:
            continue
        if (
            isinstance(target.node, nodes.Name)
            and target.node.name == "tr"
            and isinstance(key, str)
        ):
            calls.append((key, call))
    return calls


def _resolve_anki_call(col: Collection, key: str, call: nodes.Call) -> str | None:
    translate = getattr(col.tr, key)
    assert callable(translate), key
    if call.dyn_args is not None or call.dyn_kwargs is not None:
        return None

    signature = inspect.signature(translate)
    bound = signature.bind(
        *([None] * len(call.args)), **{kw.key: None for kw in call.kwargs}
    )
    samples = {
        int: 3,
        float: 3.0,
        str: "sample",
        "int": 3,
        "float": 3.0,
        "str": "sample",
        "FluentVariable": 3,
    }
    for name in bound.arguments:
        annotation = signature.parameters[name].annotation
        if annotation not in samples:
            # Unknown or variadic types cannot be exercised safely without values.
            return None
        bound.arguments[name] = samples[annotation]
    return translate(*bound.args, **bound.kwargs)


_EXPRESSION = "\ue000"
_VISIBLE_ATTRIBUTES = {
    "title",
    "aria-label",
    "aria-description",
    "aria-placeholder",
    "aria-valuetext",
    "placeholder",
    "alt",
}


class _VisibleText(HTMLParser):
    def __init__(self, path: Path) -> None:
        super().__init__(convert_charrefs=True)
        self.path = path
        self.ignored_tag: str | None = None
        self.hardcoded: list[str] = []

    def _check(self, value: str, where: str) -> None:
        for part in value.split(_EXPRESSION):
            text = part.strip()
            if not any(unicodedata.category(char).startswith("L") for char in text):
                continue
            if text == "AnkiWeb":
                continue
            # The temporary Plan 1 ping screen is removed by Plan 5.
            if self.path == APP_TEMPLATES / "ping.html.jinja" and text == "Ready":
                continue
            self.hardcoded.append(f"{self.getpos()[0]}: {where}: {text!r}")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.ignored_tag is not None:
            return
        if tag in {"script", "style"}:
            self.ignored_tag = tag
            return
        button_input = tag == "input" and dict(attrs).get("type") in {
            "button",
            "reset",
            "submit",
        }
        for name, value in attrs:
            if value is not None and (
                name in _VISIBLE_ATTRIBUTES or (button_input and name == "value")
            ):
                self._check(value, name)

    def handle_endtag(self, tag: str) -> None:
        if self.ignored_tag == tag:
            self.ignored_tag = None

    def handle_data(self, data: str) -> None:
        if self.ignored_tag is None:
            self._check(data, "text")


def _hardcoded_text(path: Path, source: str) -> list[str]:
    # Keep HTML around expressions so both text nodes and attributes are scanned.
    markup: list[str] = []
    for _, jinja_type, value in _env.lex(source):
        if jinja_type == "data":
            markup.append(value)
        elif jinja_type == "variable_begin":
            markup.append(_EXPRESSION)
    parser = _VisibleText(path)
    parser.feed("".join(markup))
    parser.close()
    return parser.hardcoded


def test_reference_inventory_finds_template_attributes_and_calls() -> None:
    custom, anki = _references(
        """<input aria-label="{{ s('app_add_hint') }}">
        {{ s(key="app_decks_search") }} {{ tr.actions_add() }}
        <p title="{{ tr['actions_decks']() }}"></p>"""
    )
    assert custom == {"app_add_hint", "app_decks_search"}
    assert anki == {"actions_add", "actions_decks"}


@pytest.mark.parametrize("source", ["{{ s(key) }}", "{{ s(key=key) }}", "{{ s() }}"])
def test_reference_inventory_rejects_dynamic_custom_keys(source: str) -> None:
    with pytest.raises(AssertionError, match="s\\(\\) key must be a literal"):
        _references(source)


def test_anki_call_inventory_validates_parameterized_keys(temp_collection) -> None:
    calls = _anki_calls("{{ tr.statistics_cards(cards=count) }} {{ tr.actions_add() }}")
    assert [key for key, _ in calls] == ["statistics_cards", "actions_add"]
    plural = _resolve_anki_call(temp_collection, *calls[0])
    assert plural is not None and "3" in plural
    assert _resolve_anki_call(temp_collection, *calls[1]) == "Add"
    wrong_arg = _anki_calls("{{ tr.statistics_cards(count=count) }}")[0]
    with pytest.raises(TypeError):
        _resolve_anki_call(temp_collection, *wrong_arg)
    missing_key = _anki_calls("{{ tr.no_such_translation() }}")[0]
    with pytest.raises(AttributeError):
        _resolve_anki_call(temp_collection, *missing_key)


def test_visible_text_scan_finds_text_and_attributes() -> None:
    source = """
        <p>Hardcoded {{ s('app_add_hint') }}!</p>
        <input placeholder="Type here" aria-label="{{ s('app_add_hint') }}">
        <img alt="Card image" title="Open {{ s('app_add_hint') }}">
        <input type="submit" value="Save">
        <script>const text = 'not visible';</script>
        <style>.some-class { color: red; }</style>
        <span>{{ s('app_add_hint') }}</span><span>123 → ✨</span>
    """
    errors = _hardcoded_text(APP_TEMPLATES / "example.html.jinja", source)
    for text in ("Hardcoded", "Type here", "Card image", "Open", "Save"):
        assert any(text in error for error in errors)
    assert len(errors) == 5


def test_visible_text_scan_has_narrow_legacy_exception() -> None:
    source = "<h1>AnkiWeb</h1><span>Ready</span>"
    assert not _hardcoded_text(APP_TEMPLATES / "ping.html.jinja", source)
    errors = _hardcoded_text(APP_TEMPLATES / "other.html.jinja", source)
    assert len(errors) == 1
    assert "Ready" in errors[0]
    assert _hardcoded_text(APP_TEMPLATES / "ping.html.jinja", "<span>Ready now</span>")


def test_no_hardcoded_text() -> None:
    paths = sorted(APP_TEMPLATES.rglob("*.jinja"))
    assert paths, f"No app templates found in {APP_TEMPLATES}"
    failures = {
        str(path.relative_to(APP_TEMPLATES)): errors
        for path in paths
        if (errors := _hardcoded_text(path, path.read_text(encoding="utf-8")))
    }
    assert not failures, f"Untranslated visible text: {failures}"


def test_strings_complete() -> None:
    english = set(STRINGS["en"])
    referenced, _ = _template_references()
    for language, catalog in STRINGS.items():
        assert set(catalog) <= english, f"{language}: {set(catalog) - english}"
    assert referenced <= english, f"Missing English strings: {referenced - english}"
    assert PRESEEDED_UNUSED <= english, (
        f"Obsolete preseed exceptions: {PRESEEDED_UNUSED - english}"
    )
    assert not (PRESEEDED_UNUSED & referenced), (
        f"Remove used preseed exceptions: {PRESEEDED_UNUSED & referenced}"
    )
    assert english - referenced == PRESEEDED_UNUSED, (
        f"Unexpected unused English strings: {english - referenced - PRESEEDED_UNUSED}"
    )


def test_translated_format_fields_match_english() -> None:
    formatter = Formatter()
    for language, catalog in STRINGS.items():
        for key, text in catalog.items():
            expected = {
                field
                for _, field, _, _ in formatter.parse(STRINGS["en"][key])
                if field is not None
            }
            actual = {
                field for _, field, _, _ in formatter.parse(text) if field is not None
            }
            assert actual == expected, f"{language}/{key}: {actual} != {expected}"


@pytest.mark.parametrize("language", ["en", "de"])
def test_anki_keys_resolve(tmp_path: Path, language: str) -> None:
    _, referenced = _template_references()
    calls = [
        item
        for path in sorted(APP_TEMPLATES.rglob("*.jinja"))
        for item in _anki_calls(path.read_text(encoding="utf-8"))
    ]
    called_keys = {key for key, _ in calls}
    anki.lang.set_lang(language)
    col = Collection(str(tmp_path / f"{language}.anki2"))
    try:
        for key in sorted(ANKI_INVENTORY | (referenced - called_keys)):
            translated = getattr(col.tr, key)()
            assert isinstance(translated, str) and translated, f"{language}: {key}"
        for key, call in calls:
            translated = _resolve_anki_call(col, key, call)
            if translated is not None:
                assert isinstance(translated, str) and translated, f"{language}: {key}"
    finally:
        col.close()
        anki.lang.set_lang("en")
