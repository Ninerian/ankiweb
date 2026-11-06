import pytest
from anki.collection import Collection, OpChanges, OpChangesWithCount
from anki.decks import DEFAULT_DECK_ID, DeckId

from ankiweb.core.app_client.deck_languages import LANGUAGES, LanguagePair, apply_marker
from ankiweb.core.app_client.decks import (
    DEFAULT_EMOJI,
    DeckNameError,
    create_deck,
    deck_rows,
    deck_settings,
    delete_deck,
    update_deck_settings,
)
from ankiweb.core.app_client.emoji_picker import ALL_EMOJI
from ankiweb.core.op_changes import op_changes_to_flags


def _deck(col: Collection, deck_id: int) -> dict:
    deck = col.decks.get(DeckId(deck_id), default=False)
    assert deck is not None
    return deck


def _set_description(
    col: Collection, deck_id: int, desc: str, md: bool = False
) -> dict:
    deck = _deck(col, deck_id)
    deck["desc"] = desc
    deck["md"] = md
    col.decks.update_dict(deck)
    return _deck(col, deck_id)


def _add_card(col: Collection, deck_id: int) -> None:
    model = col.models.by_name("Basic")
    assert model is not None
    note = col.new_note(model)
    note["Front"] = f"Card in {deck_id}"
    note["Back"] = "Answer"
    col.add_note(note, DeckId(deck_id))


@pytest.mark.parametrize("languages", [None, LanguagePair("de", "es")])
def test_create_stores_languages_atomically_and_undoes_in_one_step(
    temp_collection: Collection, languages: LanguagePair | None
) -> None:
    col = temp_collection
    row = create_deck(col, "Spanish", "📚", languages)
    stored = _deck(col, row.deck_id)
    assert stored["name"] == "Spanish · 📚"
    assert stored["desc"] == apply_marker("", languages)
    assert row.languages == languages
    assert row.changes is not None
    assert op_changes_to_flags(row.changes)["deck"]
    assert deck_settings(col, row.deck_id).languages == languages
    assert next(item for item in deck_rows(col) if item.deck_id == row.deck_id) == row

    col.undo()
    assert col.decks.get(DeckId(row.deck_id), default=False) is None


def test_creation_requires_a_validated_language_pair(
    temp_collection: Collection,
) -> None:
    col = temp_collection
    before = col.decks.all_names_and_ids()
    status = col.undo_status()
    with pytest.raises(TypeError):
        create_deck(col, "Study", "📚", ("de", "es"))  # ty: ignore[invalid-argument-type]
    assert col.decks.all_names_and_ids() == before
    assert col.undo_status() == status


@pytest.mark.parametrize(
    "emoji", sorted(set(ALL_EMOJI) | {language.flag for language in LANGUAGES})
)
def test_picker_emoji_and_language_flags_are_accepted(
    temp_collection: Collection, emoji: str
) -> None:
    col = temp_collection
    row = create_deck(col, "Language", emoji, None)
    assert deck_settings(col, row.deck_id).emoji == emoji
    update_deck_settings(col, row.deck_id, "Language", "📚", None)
    assert deck_settings(col, row.deck_id).emoji == "📚"
    changes = update_deck_settings(col, row.deck_id, "Language", emoji, None)
    assert isinstance(changes, OpChanges)
    assert _deck(col, row.deck_id)["name"] == f"Language · {emoji}"


def test_update_keeps_description_and_other_deck_settings_when_pair_unchanged(
    temp_collection: Collection,
) -> None:
    col = temp_collection
    pair = LanguagePair("de", "es")
    row = create_deck(col, "Spanish", "📚", pair)
    before = _set_description(
        col,
        row.deck_id,
        "Before\n<!--ankiweb:lang=de>es-->after<!--ankiweb:lang=fr>de-->",
        md=True,
    )
    changes = update_deck_settings(col, row.deck_id, "SPANISH", "🧬", pair)
    after = _deck(col, row.deck_id)
    assert isinstance(changes, OpChanges)
    assert op_changes_to_flags(changes)["deck"]
    assert after["name"] == "SPANISH · 🧬"
    assert after["desc"] == before["desc"]
    assert after["md"] == before["md"] is True
    assert {k: v for k, v in after.items() if k not in {"name", "mod", "usn"}} == {
        k: v for k, v in before.items() if k not in {"name", "mod", "usn"}
    }


def test_changing_and_removing_pair_preserves_description_body_and_markdown(
    temp_collection: Collection,
) -> None:
    col = temp_collection
    row = create_deck(col, "Study", "📚", LanguagePair("de", "es"))
    before = _set_description(
        col, row.deck_id, "<!--ankiweb:lang=de>es-->Text\n**bold**", True
    )
    pair = LanguagePair("fr", "it")
    update_deck_settings(col, row.deck_id, "Study", "📚", pair)
    updated = _deck(col, row.deck_id)
    assert updated["desc"] == "<!--ankiweb:lang=fr>it-->Text\n**bold**"
    assert updated["md"] == before["md"]
    assert deck_settings(col, row.deck_id).languages == pair
    update_deck_settings(col, row.deck_id, "Study", "📚", None)
    assert _deck(col, row.deck_id)["desc"] == "Text\n**bold**"
    assert deck_settings(col, row.deck_id).languages is None


def test_invalid_marker_is_preserved_when_languages_remain_none(
    temp_collection: Collection,
) -> None:
    col = temp_collection
    row = create_deck(col, "Study", "📚", None)
    before = _set_description(col, row.deck_id, "<!--ankiweb:lang=xx>de-->Body")
    update_deck_settings(col, row.deck_id, "Renamed", "📚", None)
    assert _deck(col, row.deck_id)["desc"] == before["desc"]


def test_unvalidated_update_languages_do_not_mutate_deck(
    temp_collection: Collection,
) -> None:
    col = temp_collection
    row = create_deck(col, "Study", "📚", None)
    before = _deck(col, row.deck_id)
    status = col.undo_status()
    with pytest.raises(TypeError):
        update_deck_settings(col, row.deck_id, "New", "🧬", ("de", "es"))  # ty: ignore[invalid-argument-type]
    assert _deck(col, row.deck_id) == before
    assert col.undo_status() == status


def test_case_change_excludes_own_id_but_rejects_another_normalized_root(
    temp_collection: Collection,
) -> None:
    col = temp_collection
    row = create_deck(col, "Straße", "📚", None)
    create_deck(col, "Café", "🧬", None)
    update_deck_settings(col, row.deck_id, "STRASSE", "📚", None)
    assert deck_settings(col, row.deck_id).name == "STRASSE"
    before = _deck(col, row.deck_id)
    undo_status = col.undo_status()
    with pytest.raises(DeckNameError) as error:
        update_deck_settings(col, row.deck_id, "Cafe\u0301", "📚", None)
    assert error.value.kind == "taken"
    assert _deck(col, row.deck_id) == before
    assert col.undo_status() == undo_status


@pytest.mark.parametrize(
    ("name", "emoji", "kind"),
    [
        ("", "📚", "empty"),
        ("A::B", "📚", "invalid"),
        ("A" * 41, "📚", "too_long"),
        ("Study", "🦄", "invalid"),
        ("Study", "🧬🧪", "invalid"),
        ("Study", "", "invalid"),
    ],
)
def test_invalid_update_is_atomic(
    temp_collection: Collection, name: str, emoji: str, kind: str
) -> None:
    col = temp_collection
    row = create_deck(col, "Study", "📚", LanguagePair("de", "es"))
    before = _deck(col, row.deck_id)
    undo_status = col.undo_status()
    with pytest.raises(DeckNameError) as error:
        update_deck_settings(col, row.deck_id, name, emoji, LanguagePair("fr", "it"))
    assert error.value.kind == kind
    assert _deck(col, row.deck_id) == before
    assert col.undo_status() == undo_status


@pytest.mark.parametrize("stored_name", ["Legacy", "Legacy · 🗂️", "Legacy · 🦄"])
def test_unchanged_legacy_emoji_remains_editable(
    temp_collection: Collection, stored_name: str
) -> None:
    col = temp_collection
    deck_id = col.decks.add_normal_deck_with_name(stored_name).id
    initial = deck_settings(col, deck_id)
    assert initial.emoji == ("🦄" if stored_name.endswith("🦄") else DEFAULT_EMOJI)
    update_deck_settings(
        col, deck_id, "Legacy", initial.emoji, LanguagePair("en", "de")
    )
    assert _deck(col, deck_id)["name"] == stored_name
    update_deck_settings(
        col, deck_id, "Renamed", initial.emoji, LanguagePair("en", "de")
    )
    assert _deck(col, deck_id)["name"] == stored_name.replace("Legacy", "Renamed")


def test_nested_rename_and_language_change_are_one_undo_step(
    temp_collection: Collection,
) -> None:
    col = temp_collection
    row = create_deck(col, "Parent", "📚", LanguagePair("de", "es"))
    child = col.decks.add_normal_deck_with_name("Parent · 📚::Child").id
    grandchild = col.decks.add_normal_deck_with_name(
        "Parent · 📚::Child::Grandchild"
    ).id
    before = _set_description(col, row.deck_id, "<!--ankiweb:lang=de>es-->body", True)
    changes = update_deck_settings(
        col, row.deck_id, "New", "🧬", LanguagePair("fr", "it")
    )
    assert op_changes_to_flags(changes)["deck"]
    assert _deck(col, row.deck_id)["name"] == "New · 🧬"
    assert _deck(col, child)["name"] == "New · 🧬::Child"
    assert _deck(col, grandchild)["name"] == "New · 🧬::Child::Grandchild"
    assert _deck(col, row.deck_id)["desc"] == "<!--ankiweb:lang=fr>it-->body"

    col.undo()
    assert _deck(col, row.deck_id)["name"] == before["name"]
    assert _deck(col, row.deck_id)["desc"] == before["desc"]
    assert _deck(col, row.deck_id)["md"] == before["md"]
    assert _deck(col, child)["name"] == "Parent · 📚::Child"
    assert _deck(col, grandchild)["name"] == "Parent · 📚::Child::Grandchild"


def test_delete_counts_descendants_and_undo_restores_all(
    temp_collection: Collection,
) -> None:
    col = temp_collection
    row = create_deck(col, "Parent", "📚", None)
    child = col.decks.add_normal_deck_with_name("Parent · 📚::Child").id
    grandchild = col.decks.add_normal_deck_with_name(
        "Parent · 📚::Child::Grandchild"
    ).id
    _add_card(col, row.deck_id)
    _add_card(col, child)
    _add_card(col, grandchild)
    assert deck_settings(col, row.deck_id).card_count == 3
    result = delete_deck(col, row.deck_id)
    assert isinstance(result, OpChangesWithCount)
    assert result.count == 3
    assert op_changes_to_flags(result.changes)["deck"]
    for deck_id in (row.deck_id, child, grandchild):
        assert col.decks.get(DeckId(deck_id), default=False) is None
    col.undo()
    assert deck_settings(col, row.deck_id).card_count == 3
    assert _deck(col, child)["name"] == "Parent · 📚::Child"
    assert _deck(col, grandchild)["name"] == "Parent · 📚::Child::Grandchild"


def test_default_deck_is_protected_from_deletion(temp_collection: Collection) -> None:
    col = temp_collection
    child = col.decks.add_normal_deck_with_name("Default::Child").id
    _add_card(col, DEFAULT_DECK_ID)
    _add_card(col, child)
    before = _deck(col, DEFAULT_DECK_ID)
    status = col.undo_status()
    with pytest.raises(DeckNameError) as error:
        delete_deck(col, DEFAULT_DECK_ID)
    assert error.value.kind == "protected"
    assert _deck(col, DEFAULT_DECK_ID) == before
    assert _deck(col, child)["name"] == "Default::Child"
    assert col.decks.card_count(DEFAULT_DECK_ID, True) == 2
    assert col.undo_status() == status


def test_unknown_child_and_filtered_decks_are_not_editable(
    temp_collection: Collection,
) -> None:
    col = temp_collection
    child = col.decks.add_normal_deck_with_name("Parent::Child").id
    _add_card(col, child)
    filtered = col.sched.get_or_create_filtered_deck(deck_id=DeckId(0))
    filtered.name = "Filtered"
    filtered.config.search_terms[0].search = "deck:Parent"
    filtered_id = col.sched.add_or_update_filtered_deck(filtered).id
    for deck_id in (0, 987654321, child, filtered_id):
        for action in (
            lambda deck_id=deck_id: deck_settings(col, deck_id),
            lambda deck_id=deck_id: update_deck_settings(
                col, deck_id, "Renamed", "📚", None
            ),
            lambda deck_id=deck_id: delete_deck(col, deck_id),
        ):
            with pytest.raises(DeckNameError) as error:
                action()
            assert error.value.kind == "not_found"


def test_rows_read_each_root_marker_without_inheriting_children(
    temp_collection: Collection,
) -> None:
    col = temp_collection
    first = create_deck(col, "Alpha", "📚", LanguagePair("de", "es"))
    second = create_deck(col, "Beta", "🧬", None)
    child = col.decks.add_normal_deck_with_name("Beta · 🧬::Child").id
    _set_description(col, child, "<!--ankiweb:lang=fr>it-->child")
    rows = deck_rows(col)
    assert [(row.deck_id, row.languages) for row in rows] == [
        (first.deck_id, LanguagePair("de", "es")),
        (second.deck_id, None),
    ]
