"""Deck-Kartenliste and editable vocabulary note selection."""

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import groupby

import anki.collection  # Initialize before anki.cards to avoid an import cycle.
from anki.cards import CardId
from anki.models import NotetypeId
from anki.notes import NoteId

from ankiweb.core.app_client.vocab import (
    NOTETYPE_NAME,
    VocabFields,
    ensure_vocab_model,
    read_vocab_note,
)


class NoteNotEditable(Exception):
    """The note is not an editable vocabulary note in the requested deck."""


@dataclass(frozen=True)
class DeckNote:
    nid: int
    fields: VocabFields
    learned: bool


def is_learned(card_types: Iterable[int]) -> bool:
    """A note is Gelernt if any of its selected-deck cards is not new."""
    return any(card_type != 0 for card_type in card_types)


def deck_notes(col: anki.collection.Collection, deck_id: int) -> list[DeckNote]:
    """Return the dedicated vocabulary notes in a deck, newest first."""
    db = col.db
    if db is None:
        raise RuntimeError("Collection database is not available")
    model = ensure_vocab_model(col)
    rows = db.all(
        "select n.id, c.type from notes n "
        "join cards c on c.nid = n.id "
        "where n.mid = ? and c.did = ? order by n.id desc",
        model["id"],
        deck_id,
    )
    return [
        DeckNote(
            nid,
            VocabFields.from_mapping(read_vocab_note(col, NoteId(nid))),
            is_learned(card_type for _, card_type in cards),
        )
        for nid, cards in groupby(rows, key=lambda row: row[0])
    ]


def editable_deck_note(
    col: anki.collection.Collection, deck_id: int, nid: int
) -> tuple[DeckNote, list[CardId]]:
    """Find an editable note and the IDs of its cards in the selected deck."""
    if not 0 < nid < 2**63:
        raise NoteNotEditable
    db = col.db
    if db is None:
        raise RuntimeError("Collection database is not available")
    cards = db.all("select id, type from cards where nid = ? and did = ?", nid, deck_id)
    if not cards:
        raise NoteNotEditable
    try:
        fields = VocabFields.from_mapping(read_vocab_note(col, NoteId(nid)))
    except ValueError as exc:
        raise NoteNotEditable from exc
    return (
        DeckNote(nid, fields, is_learned(card_type for _, card_type in cards)),
        [CardId(card_id) for card_id, _ in cards],
    )


def _record_added_notes(
    col: anki.collection.Collection,
    rows: list[tuple[int, int, int]],
    vocab_types: dict[int, bool],
    present: set[int],
    in_deck: set[int],
) -> None:
    for nid, mid, matches in rows:
        if mid not in vocab_types:
            model = col.models.get(NotetypeId(mid))
            if model is None:
                raise ValueError(f"Note type {mid} is missing")
            vocab_types[mid] = model["name"] == NOTETYPE_NAME
        if vocab_types[mid]:
            present.add(nid)
            if matches:
                in_deck.add(nid)


def added_note_membership(
    col: anki.collection.Collection, deck_id: int, ids: list[int]
) -> tuple[set[int], set[int]]:
    """Find session-added vocabulary notes still present and in this deck."""
    if not ids:
        return set(), set()
    db = col.db
    if db is None:
        raise RuntimeError("Collection database is not available")
    present: set[int] = set()
    in_deck: set[int] = set()
    vocab_types: dict[int, bool] = {}
    for start in range(0, len(ids), 32):
        batch = ids[start : start + 32]
        rows = db.all(
            "select n.id, n.mid, exists(select 1 from cards c where c.nid = n.id "
            "and c.did = ?) from notes n where n.id in ("
            "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
            "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            deck_id,
            *batch,
            *([None] * (32 - len(batch))),
        )
        _record_added_notes(col, rows, vocab_types, present, in_deck)
    return present, in_deck
