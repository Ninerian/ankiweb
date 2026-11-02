"""The dedicated vocabulary note type and its plain-text editing contract."""

from __future__ import annotations

import html
import re

from anki.collection import Collection
from anki.decks import DeckId
from anki.models import NotetypeDict, NotetypeId
from anki.notes import Note, NoteId

from ankiweb.core.ankiconnect_actions.actions._helpers import check_addable

NOTETYPE_NAME = "AnkiWeb Vocab"
_FIELD_NAMES = ("Front", "Back", "Hint", "Example")
_FRONT_TEMPLATE = """<div class="av-card av-front">
  <div class="av-front-text">{{Front}}</div>
  {{#Hint}}<div class="av-hint">{{Hint}}</div>{{/Hint}}
</div>"""
_BACK_TEMPLATE = """<div class="av-card av-back">
  <div class="av-front-text">{{Front}}</div>
  {{#Hint}}<div class="av-hint">{{Hint}}</div>{{/Hint}}
  <hr id="answer">
  <div class="av-back-text">{{Back}}</div>
  {{#Example}}<div class="av-example">{{Example}}</div>{{/Example}}
</div>"""
_EXAMPLE_HIGHLIGHT = re.compile(r"\*((?:(?!<br>)[^*\n])+)\*")


class DuplicateNote(ValueError):
    """A different note of this type already has the same first field."""


def _validate_model(model: NotetypeDict) -> None:
    if tuple(field["name"] for field in model["flds"]) != _FIELD_NAMES:
        raise ValueError(f"{NOTETYPE_NAME} has incompatible fields")
    templates = model["tmpls"]
    if (
        len(templates) != 1
        or templates[0]["name"] != "Card 1"
        or templates[0]["qfmt"] != _FRONT_TEMPLATE
        or templates[0]["afmt"] != _BACK_TEMPLATE
    ):
        raise ValueError(f"{NOTETYPE_NAME} has an incompatible template")
    if model["css"] != "" or model["type"] != 0:
        raise ValueError(f"{NOTETYPE_NAME} has incompatible styling or type")


def ensure_vocab_model(col: Collection) -> NotetypeDict:
    """Create the vocab note type or reject an incompatible existing type."""
    model = col.models.by_name(NOTETYPE_NAME)
    if model is not None:
        _validate_model(model)
        return model

    model = col.models.new(NOTETYPE_NAME)
    for name in _FIELD_NAMES:
        col.models.add_field(model, col.models.new_field(name))
    template = col.models.new_template("Card 1")
    template["qfmt"] = _FRONT_TEMPLATE
    template["afmt"] = _BACK_TEMPLATE
    col.models.add_template(model, template)
    model["css"] = ""
    result = col.models.add_dict(model)
    persisted = col.models.get(NotetypeId(result.id))
    if persisted is None:
        raise ValueError(f"Failed to create {NOTETYPE_NAME}")
    return persisted


def escape_field(value: str) -> str:
    """Encode plain text for an Anki HTML field, preserving line breaks."""
    return html.escape(value.replace("\r\n", "\n"), quote=False).replace("\n", "<br>")


def unescape_field(value: str) -> str:
    """Decode an HTML field written by escape_field for editing."""
    return html.unescape(value.replace("<br>", "\n"))


def highlight_example(escaped_value: str) -> str:
    """Highlight asterisk pairs in an already escaped example, within one line."""
    return _EXAMPLE_HIGHLIGHT.sub(r"<mark>\1</mark>", escaped_value)


def _set_fields(note: Note, front: str, back: str, hint: str, example: str) -> None:
    if not front.strip() or not back.strip():
        raise ValueError("Front and back are required")
    for name, value in zip(_FIELD_NAMES, (front, back, hint, example), strict=True):
        note[name] = escape_field(value)


def _check_addable(col: Collection, note: Note) -> None:
    # Anki's fields_check excludes note.id, including when another duplicate exists.
    ok, error = check_addable(col, note, {})
    if not ok:
        if error and "duplicate" in error:
            raise DuplicateNote(error)
        raise ValueError(error)


def _vocab_note(col: Collection, nid: NoteId) -> Note:
    note = col.get_note(nid)
    model = note.note_type()
    if model is None or model["name"] != NOTETYPE_NAME:
        raise ValueError(f"Note is not of type {NOTETYPE_NAME}")
    _validate_model(model)
    return note


def add_vocab_note(
    col: Collection,
    deck_id: DeckId,
    front: str,
    back: str,
    hint: str = "",
    example: str = "",
) -> NoteId:
    """Validate and add a vocab note to the requested deck."""
    note = col.new_note(ensure_vocab_model(col))
    _set_fields(note, front, back, hint, example)
    _check_addable(col, note)
    col.add_note(note, deck_id)
    return note.id


def update_vocab_note(
    col: Collection,
    nid: NoteId,
    front: str,
    back: str,
    hint: str = "",
    example: str = "",
) -> bool:
    """Update changed fields and return whether the note was modified."""
    note = _vocab_note(col, nid)
    original = tuple(
        unescape_field(note[name]).replace("\r\n", "\n") for name in _FIELD_NAMES
    )
    _set_fields(note, front, back, hint, example)
    updated = tuple(
        unescape_field(note[name]).replace("\r\n", "\n") for name in _FIELD_NAMES
    )
    if original == updated:
        return False
    _check_addable(col, note)
    col.update_note(note)
    return True


def read_vocab_note(col: Collection, nid: NoteId) -> dict[str, str]:
    """Return editable plain-text values for a vocab note."""
    note = _vocab_note(col, nid)
    return {name.lower(): unescape_field(note[name]) for name in _FIELD_NAMES}
