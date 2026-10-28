import pytest
from anki.cards import CardId
from anki.collection import Collection
from anki.decks import DeckId

from ankiweb.core.app_client.deck_progress import progress_pct
from ankiweb.core.app_client.decks import DEFAULT_EMOJI, deck_rows, split_emoji
from ankiweb.core.app_client.revlog import day_start_ms


def _add_cards(col: Collection, deck_name: str, count: int = 1) -> list[int]:
    deck_id = col.decks.id(deck_name)
    model = col.models.by_name("Basic")
    assert deck_id is not None
    assert model is not None
    card_ids = []
    for index in range(count):
        note = col.new_note(model)
        note["Front"] = f"{deck_name} {index}"
        note["Back"] = "answer"
        col.add_note(note, deck_id)
        card_ids.append(note.cards()[0].id)
    return card_ids


def _insert_review(col: Collection, card_id: int, offset_ms: int = 1) -> None:
    assert col.db is not None
    col.db.execute(
        "insert into revlog values (?, ?, -1, 3, 1, 0, 2500, 1000, 1)",
        day_start_ms(col) + offset_ms,
        card_id,
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("🇩🇪 German B1 Vocab", ("🇩🇪", "German B1 Vocab")),
        ("🧬Biology", ("🧬", "Biology")),
        ("⚗️ Chemistry", ("⚗️", "Chemistry")),
        ("👩‍💻 Coding", ("👩‍💻", "Coding")),
        ("👍🏽 Skin tone", ("👍🏽", "Skin tone")),
        ("Biology", (DEFAULT_EMOJI, "Biology")),
        ("🇩 Lone indicator", (DEFAULT_EMOJI, "🇩 Lone indicator")),
        ("1900s", (DEFAULT_EMOJI, "1900s")),
        ("🧬", (DEFAULT_EMOJI, "🧬")),
    ],
)
def test_split_emoji(name: str, expected: tuple[str, str]) -> None:
    assert split_emoji(name) == expected


@pytest.mark.parametrize(
    ("studied", "due", "new", "expected"),
    [(0, 0, 0, 0), (5, 0, 0, 100), (0, 3, 2, 0), (1, 2, 1, 25), (7, 0, 1, 87)],
)
def test_progress_pct(studied: int, due: int, new: int, expected: int) -> None:
    assert progress_pct(studied, due, new) == expected


def test_counts_match_due_tree_and_include_children(
    temp_collection: Collection,
) -> None:
    col = temp_collection
    _add_cards(col, "Parent", 2)
    _add_cards(col, "Parent::A", 3)
    _add_cards(col, "Parent::B", 4)
    _add_cards(col, "Solo", 1)

    rows = {row.name: row for row in deck_rows(col)}

    assert rows["Parent"].new == 9
    assert rows["Solo"].new == 1
    tree = {node.name: node for node in col.sched.deck_due_tree().children}
    for name, row in rows.items():
        node = tree[name]
        assert row.deck_id == node.deck_id
        assert row.new == node.new_count
        assert row.due == node.review_count + node.learn_count
    assert "A" not in rows
    assert "Parent::A" not in rows


def test_order_follows_anki_tree(temp_collection: Collection) -> None:
    col = temp_collection
    for name in ("Zeta", "Alpha", "Mid"):
        _add_cards(col, name)

    assert [row.name for row in deck_rows(col)] == ["Alpha", "Mid", "Zeta"]


def test_basic_only_deck_is_listed(col_with_vocab: Collection) -> None:
    rows = deck_rows(col_with_vocab)

    assert [(row.name, row.new) for row in rows] == [("German B1 Vocab", 4)]


def test_filtered_deck_and_empty_default_are_hidden(
    temp_collection: Collection,
) -> None:
    col = temp_collection
    assert deck_rows(col) == []
    _add_cards(col, "Real")
    filtered = col.sched.get_or_create_filtered_deck(deck_id=DeckId(0))
    filtered.name = "Filtered"
    filtered.config.search_terms[0].search = "deck:Real"
    col.sched.add_or_update_filtered_deck(filtered)
    tree = col.sched.deck_due_tree().children
    assert [node.name for node in tree if node.filtered] == ["Filtered"]

    names = [row.name for row in deck_rows(col)]

    assert names == ["Real"]


def test_default_deck_with_cards_is_listed(temp_collection: Collection) -> None:
    _add_cards(temp_collection, "Default")

    assert [row.name for row in deck_rows(temp_collection)] == ["Default"]


def test_progress_counts_reviews_in_subdecks(temp_collection: Collection) -> None:
    col = temp_collection
    root_card = _add_cards(col, "Root")[0]
    child_cards = _add_cards(col, "Root::Child", 2)
    _add_cards(col, "Idle")
    for offset, card_id in enumerate((root_card, *child_cards, child_cards[0]), 1):
        _insert_review(col, card_id, offset)

    rows = {row.name: row for row in deck_rows(col)}

    assert rows["Idle"].progress_pct == 0
    assert (rows["Root"].due, rows["Root"].new) == (0, 3)
    assert rows["Root"].progress_pct == 57  # 4 reviews / (4 + 3 new)


def test_progress_is_100_when_nothing_is_open(temp_collection: Collection) -> None:
    col = temp_collection
    card_id = _add_cards(col, "Done")[0]
    _insert_review(col, card_id)
    col.sched.bury_cards([CardId(card_id)])

    (row,) = deck_rows(col)

    assert (row.due, row.new) == (0, 0)
    assert row.progress_pct == 100
