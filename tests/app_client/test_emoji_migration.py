from anki.cards import CardId
from anki.collection import Collection
from anki.decks import DeckId

from ankiweb.core.app_client.emoji_migration import (
    MigrationResult,
    apply_emoji_migration,
    filtered_deck_warning_count,
    plan_emoji_migration,
)


def _deck(col: Collection, name: str) -> DeckId:
    return DeckId(col.decks.add_normal_deck_with_name(name).id)


def _card(col: Collection, did: DeckId) -> CardId:
    model = col.models.by_name("Basic")
    assert model is not None
    note = col.new_note(model)
    note["Front"], note["Back"] = "Question", "Answer"
    col.add_note(note, did)
    return note.cards()[0].id


def test_rename_preserves_ids_cards_and_is_idempotent(
    temp_collection: Collection,
) -> None:
    col = temp_collection
    first = _deck(col, "🧬 Bio")
    second = _deck(col, "📚 Words")
    card = _card(col, first)
    plan = plan_emoji_migration(col)
    assert {item.deck_id for item in plan} == {first, second}
    result = apply_emoji_migration(col, [first, second])
    assert result == MigrationResult(2, 0, 0)
    assert col.decks.name(first) == "Bio · 🧬"
    assert col.decks.name(second) == "Words · 📚"
    assert col.get_card(card).did == first
    assert plan_emoji_migration(col) == []
    assert apply_emoji_migration(col, [first, second]) == MigrationResult(0, 2, 0)
    col.undo()
    assert col.decks.name(first) == "🧬 Bio"
    assert col.decks.name(second) == "📚 Words"
    assert col.get_card(card).did == first


def test_conflicts_and_children_are_not_applied(temp_collection: Collection) -> None:
    col = temp_collection
    conflict = _deck(col, "🧬 Biology")
    _deck(col, "biology · 🧬")
    child = _deck(col, "Parent::📚 Child")
    long = _deck(col, "📚 " + "a" * 41)
    emoji_only = _deck(col, "📚")
    plan = {item.deck_id: item for item in plan_emoji_migration(col)}
    assert plan[conflict].status == "conflict"
    assert plan[child].status == "skipped" and plan[child].reason == "child"
    assert plan[long].reason == "too_long"
    assert plan[emoji_only].reason == "emoji_only"
    assert apply_emoji_migration(col, plan.keys()) == MigrationResult(0, 4, 0)
    assert col.decks.name(conflict) == "🧬 Biology"
    assert col.decks.name(child) == "Parent::📚 Child"


def test_parent_with_prefixed_child_is_not_renamed(temp_collection: Collection) -> None:
    col = temp_collection
    root = _deck(col, "🧬 Parent")
    child = _deck(col, "🧬 Parent::📚 Child")
    plan = {item.deck_id: item for item in plan_emoji_migration(col)}
    assert plan[root].status == plan[child].status == "skipped"
    assert apply_emoji_migration(col, [root, child]) == MigrationResult(0, 2, 0)
    assert col.decks.name(root) == "🧬 Parent"
    assert col.decks.name(child) == "🧬 Parent::📚 Child"


def test_individual_failure_does_not_abort_others(
    temp_collection: Collection, monkeypatch
) -> None:
    col = temp_collection
    fail = _deck(col, "🧬 Fail")
    succeed = _deck(col, "📚 Succeed")
    rename = col.decks.rename

    def sometimes_fails(deck, name):
        if deck == fail:
            raise ValueError("failure")
        return rename(deck, name)

    monkeypatch.setattr(col.decks, "rename", sometimes_fails)
    assert apply_emoji_migration(col, [fail, succeed]) == MigrationResult(1, 0, 1)
    assert col.decks.name(fail) == "🧬 Fail"
    assert col.decks.name(succeed) == "Succeed · 📚"
    col.undo()
    assert col.decks.name(succeed) == "📚 Succeed"


def test_filtered_search_warning_counts_decks_once(temp_collection: Collection) -> None:
    col = temp_collection
    did = _deck(col, "🧬 Bio")
    _card(col, did)
    filtered = col.sched.get_or_create_filtered_deck(DeckId(0))
    filtered.name = "Filtered"
    filtered.config.search_terms[0].search = 'deck:"🧬 Bio"'
    filtered_id = DeckId(col.sched.add_or_update_filtered_deck(filtered).id)
    plan = plan_emoji_migration(col)
    assert filtered_deck_warning_count(col, plan) == 1
    apply_emoji_migration(col, [did])
    assert (
        "🧬 Bio"
        in col.sched.get_or_create_filtered_deck(filtered_id)
        .config.search_terms[0]
        .search
    )
