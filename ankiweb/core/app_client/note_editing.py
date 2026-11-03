"""Edit vocabulary notes and journal pending Lernfortschritt resets."""

import logging
from dataclasses import dataclass

import anki.collection  # Initialize before anki.cards to avoid an import cycle.
from anki.cards import CardId
from anki.collection_pb2 import OpChanges
from anki.errors import AnkiException
from anki.notes import NoteId
from anki.utils import to_json_bytes

from ankiweb.core.app_client.deck_notes import editable_deck_note
from ankiweb.core.app_client.vocab import (
    VocabFields,
    read_vocab_note,
)
from ankiweb.core.app_client.vocab import (
    update_vocab_note_with_changes as update_vocab_note,
)

_logger = logging.getLogger(__name__)
_PENDING_PROGRESS_RESETS = "ankiweb_pending_progress_resets"
_MAX_PENDING_RESETS = 50
_MAX_PENDING_RESET_BYTES = 4096


class InvalidFields(Exception):
    """The request did not contain valid editable fields."""


class ProgressResetFailed(Exception):
    """The note was saved but its learning progress was not reset."""


class ProgressResetUnrecorded(Exception):
    """The reset could not be recorded before saving the note."""


class ProgressResetUncleared(Exception):
    """The reset succeeded but its journal entry could not be cleared."""


@dataclass
class EditOutcome:
    progress_reset: bool
    changes: OpChanges


def _pending_resets(col: anki.collection.Collection) -> list[list[int | str]]:
    pending = col.get_config(_PENDING_PROGRESS_RESETS, [])
    if not isinstance(pending, list) or any(
        not isinstance(item, list)
        or len(item) != 3
        or any(
            not isinstance(value, int) or isinstance(value, bool) for value in item[:2]
        )
        or not isinstance(item[2], str)
        for item in pending
    ):
        raise ValueError("Invalid pending progress reset configuration")
    return pending


def _prepare_reset(
    col: anki.collection.Collection,
    deck_id: int,
    nid: int,
    original: VocabFields,
    values: VocabFields,
    learned: bool,
    fingerprint: str,
) -> tuple[list[list[int | str]], list[int | str] | None, bool]:
    pending = _pending_resets(col)
    marker = next((item for item in pending if item[:2] == [deck_id, nid]), None)
    if (
        marker is not None
        or not learned
        or original.normalized() == values.normalized()
    ):
        return pending, marker, False
    marker = [deck_id, nid, fingerprint]
    updated_pending = [*pending, marker]
    try:
        if (
            len(updated_pending) > _MAX_PENDING_RESETS
            or len(to_json_bytes(updated_pending)) > _MAX_PENDING_RESET_BYTES
        ):
            raise ValueError("Pending progress reset capacity exceeded")
        # Preserve Anki undo history; a DB transaction is unsafe here.
        col.set_config(_PENDING_PROGRESS_RESETS, updated_pending, undoable=False)
    except Exception as exc:
        raise ProgressResetUnrecorded from exc
    return pending, marker, True


def _update_existing_note(
    col: anki.collection.Collection,
    nid: int,
    values: VocabFields,
    original: VocabFields,
    pending: list[list[int | str]],
    created_marker: bool,
    logger: logging.Logger,
) -> OpChanges | None:
    try:
        return update_vocab_note(
            col, NoteId(nid), values.front, values.back, values.hint, values.example
        )
    except (AnkiException, ValueError):
        if created_marker:
            try:
                persisted = VocabFields.from_mapping(read_vocab_note(col, NoteId(nid)))
                if persisted.normalized() == original.normalized():
                    col.set_config(_PENDING_PROGRESS_RESETS, pending, undoable=False)
            except Exception:
                logger.exception("Failed to remove unused pending progress reset")
        raise


def _reset_and_clear(
    col: anki.collection.Collection,
    card_ids: list[CardId],
    pending: list[list[int | str]],
    marker: list[int | str],
    changes: OpChanges,
) -> None:
    try:
        reset_changes = col.sched.schedule_cards_as_new(card_ids, reset_counts=True)
    except Exception as exc:
        # A scheduler may have written cards or revlog before failing, without
        # returning OpChanges. Conservatively invalidate affected client views.
        changes.card = True
        changes.study_queues = True
        changes.browser_table = True
        raise ProgressResetFailed from exc
    if reset_changes is not None:
        changes.MergeFrom(reset_changes)
    try:
        col.set_config(
            _PENDING_PROGRESS_RESETS,
            [item for item in pending if item is not marker],
            undoable=False,
        )
    except Exception as exc:
        raise ProgressResetUncleared from exc


def edit_deck_note(
    col: anki.collection.Collection,
    deck_id: int,
    nid: int,
    fields: VocabFields | None,
    *,
    logger: logging.Logger = _logger,
    changes: OpChanges | None = None,
) -> EditOutcome:
    """Save a selected note and reset changed learned cards, with recovery journal."""
    if changes is None:
        changes = OpChanges()
    note, card_ids = editable_deck_note(col, deck_id, nid)
    if fields is None:
        raise InvalidFields
    fingerprint = note.fields.fingerprint()
    pending, marker, created_marker = _prepare_reset(
        col, deck_id, nid, note.fields, fields, note.learned, fingerprint
    )
    updated = _update_existing_note(
        col, nid, fields, note.fields, pending, created_marker, logger
    )
    # A marker may precede a crashed note write: unchanged original text
    # is not evidence that an edit completed, so do not reset it.
    progress_reset = marker is not None and (
        updated is not None or fingerprint != marker[2]
    )
    if updated is not None:
        changes.MergeFrom(updated)
    if progress_reset:
        assert marker is not None
        _reset_and_clear(col, card_ids, pending, marker, changes)
    return EditOutcome(progress_reset, changes)
