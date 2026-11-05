"""Daily study progress per root deck, from review counts and the due tree."""

from collections.abc import Iterator, Mapping, Sequence

from anki.decks import DeckTreeNode


def _subtree_ids(node: DeckTreeNode) -> Iterator[int]:
    yield node.deck_id
    for child in node.children:
        yield from _subtree_ids(child)


def progress_pct(studied: int, due: int, new: int) -> int:
    """Return studied / (studied + due + new) as a 0..100 integer."""
    total = studied + due + new
    if total <= 0:
        return 0
    return min(100, studied * 100 // total)


def progress_by_deck(
    studied: Mapping[int, int], roots: Sequence[DeckTreeNode]
) -> dict[int, int]:
    """Map each root deck id to its progress, counting reviews in all subdecks."""
    return {
        root.deck_id: progress_pct(
            sum(studied.get(deck_id, 0) for deck_id in _subtree_ids(root)),
            root.review_count + root.learn_count,
            root.new_count,
        )
        for root in roots
    }
