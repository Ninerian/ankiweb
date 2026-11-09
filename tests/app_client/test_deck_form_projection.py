from dataclasses import replace

import pytest

from ankiweb.adapters.inbound.http_app.deck_form import FormDraft, project_form


@pytest.fixture
def draft() -> FormDraft:
    return FormDraft(name=" Study ", emoji="📚", mode="langs", src="de", dst="es")


def test_create_projection_trims_preview_and_suggests_target_flag(
    draft: FormDraft,
) -> None:
    projection = project_form(draft)

    assert projection.name == "Study"
    assert projection.emoji == "📚"
    assert projection.chip == "pair"
    assert projection.message == ""
    assert projection.src_flag == "🇩🇪"
    assert projection.dst_flag == "🇪🇸"
    assert projection.suggestion == "🇪🇸"
    assert projection.can_submit_content is True
    assert projection.dirty == 0
    assert not projection.changed_name
    assert not projection.changed_emoji
    assert not projection.changed_languages
    assert draft.name == " Study "


@pytest.mark.parametrize(
    ("name", "count"),
    [("", 0), (" Study ", 7), ("🧬", 2), ("a🧬b", 4), ("\ufeff", 1)],
)
def test_name_count_matches_raw_javascript_utf16_length(
    draft: FormDraft, name: str, count: int
) -> None:
    assert project_form(replace(draft, name=name)).name_count == count


@pytest.mark.parametrize(
    ("mode", "src", "dst", "chip", "message", "can_submit"),
    [
        ("langs", "de", "es", "pair", "", True),
        ("langs", "", "", "unset", "", False),
        ("langs", "de", "", "unset", "missing_dst", False),
        ("langs", "", "es", "unset", "missing_src", False),
        ("langs", "de", "de", "unset", "same", False),
        ("none", "de", "de", "none", "", True),
        ("other", "de", "es", "unset", "", False),
    ],
)
def test_language_projection_matches_form_rules(
    draft: FormDraft,
    mode: str,
    src: str,
    dst: str,
    chip: str,
    message: str,
    can_submit: bool,
) -> None:
    projection = project_form(replace(draft, mode=mode, src=src, dst=dst))
    assert projection.chip == chip
    assert projection.message == message
    assert projection.can_submit_content is can_submit


def test_empty_names_are_not_submittable(draft: FormDraft) -> None:
    projection = project_form(replace(draft, name="  \t\n"))
    assert projection.name == ""
    assert projection.can_submit_content is False


@pytest.mark.parametrize(
    ("name", "expected"),
    [("\ufeff  Study\u00a0", "Study"), ("\ufeff", ""), ("\u0085", "\u0085")],
)
def test_preview_name_uses_javascript_trim_rules(
    draft: FormDraft, name: str, expected: str
) -> None:
    projection = project_form(replace(draft, name=name))
    assert projection.name == expected
    assert projection.can_submit_content is bool(expected)


def test_preview_does_not_add_early_domain_validation(draft: FormDraft) -> None:
    projection = project_form(replace(draft, name="Parent::Child", emoji="invalid"))
    assert projection.name == "Parent::Child"
    assert projection.emoji == "invalid"
    assert projection.can_submit_content is True


@pytest.mark.parametrize(
    ("src", "dst", "emoji", "mode", "suggestion"),
    [
        ("de", "es", "📚", "langs", "🇪🇸"),
        ("", "es", "📚", "langs", "🇪🇸"),
        ("de", "de", "📚", "langs", ""),
        ("de", "es", "🇪🇸", "langs", ""),
        ("de", "", "📚", "langs", ""),
        ("de", "es", "📚", "none", ""),
    ],
)
def test_flag_suggestion_is_an_explicit_optional_choice(
    draft: FormDraft, src: str, dst: str, emoji: str, mode: str, suggestion: str
) -> None:
    projection = project_form(replace(draft, src=src, dst=dst, emoji=emoji, mode=mode))
    assert projection.suggestion == suggestion
    assert projection.emoji == emoji


def test_missing_flags_use_placeholder(draft: FormDraft) -> None:
    projection = project_form(replace(draft, src="", dst=""))
    assert projection.src_flag == projection.dst_flag == "?"


@pytest.mark.parametrize(
    ("mode", "src", "dst", "allowed"),
    [
        ("langs", "", "", False),
        ("langs", "de", "", True),
        ("langs", "", "es", True),
        ("langs", "de", "es", True),
        ("none", "de", "es", False),
    ],
)
def test_swap_availability_uses_visible_language_values(
    draft: FormDraft, mode: str, src: str, dst: str, allowed: bool
) -> None:
    projection = project_form(replace(draft, mode=mode, src=src, dst=dst))
    assert projection.can_swap is allowed


@pytest.mark.parametrize(
    ("changes", "name", "emoji", "languages", "dirty"),
    [
        ({}, False, False, False, 0),
        ({"name": "Study"}, True, False, False, 1),
        ({"emoji": "🧬"}, False, True, False, 1),
        ({"src": "fr", "dst": "it"}, False, False, True, 1),
        ({"mode": "none"}, False, False, True, 1),
        ({"name": "Other", "emoji": "🧬", "dst": "fr"}, True, True, True, 3),
    ],
)
def test_settings_dirty_counts_groups_and_raw_name(
    draft: FormDraft,
    changes: dict[str, str],
    name: bool,
    emoji: bool,
    languages: bool,
    dirty: int,
) -> None:
    projection = project_form(replace(draft, **changes), draft)
    assert projection.changed_name is name
    assert projection.changed_emoji is emoji
    assert projection.changed_languages is languages
    assert projection.dirty == dirty


def test_settings_submit_requires_both_changes_and_valid_content(
    draft: FormDraft,
) -> None:
    assert project_form(draft, draft).can_submit_content is False
    assert project_form(replace(draft, name="New"), draft).can_submit_content is True
    assert project_form(replace(draft, name=" "), draft).can_submit_content is False
    assert project_form(replace(draft, src="es"), draft).can_submit_content is False


def test_hidden_language_changes_are_ignored_but_preserved(draft: FormDraft) -> None:
    baseline = replace(draft, mode="none")
    hidden = replace(baseline, src="fr", dst="it")
    projection = project_form(hidden, baseline)
    assert projection.changed_languages is False
    assert projection.dirty == 0
    assert hidden.src == "fr" and hidden.dst == "it"
    restored = project_form(replace(hidden, mode="langs"), baseline)
    assert restored.changed_languages is True
    assert restored.src_flag == "🇫🇷" and restored.dst_flag == "🇮🇹"


def test_removing_existing_pair_warns_only_for_settings(draft: FormDraft) -> None:
    changed = replace(draft, mode="none")
    assert project_form(changed, draft).message == "none_removes"
    assert project_form(changed).message == ""
    assert project_form(changed, replace(draft, mode="none")).message == ""
