from __future__ import annotations
from ankiweb.core.op_changes import op_changes_to_flags

_EMPTY, _DUPLICATE = 1, 2  # note.fields_check() int states


async def run_emit(rt, fn):
    """Run fn(col) -> (value, op_with_changes | None); broadcast its OpChanges flags on the
    bus (so an open web UI refreshes); return value. Tolerates a None op (no-op actions)."""
    value, op = await rt.service.run(fn)
    if op is None:
        return value
    changes = getattr(op, "changes", op)
    flags = op_changes_to_flags(changes)
    if any(flags.values()):
        await rt.service.emit(flags, "ankiconnect")
    return value


def build_note(col, spec):
    """Build (not add) an anki Note from an AnkiConnect note spec. Case-insensitive field
    matching. Media fields (audio/video/picture) deferred to B3."""
    spec = spec or {}
    model = col.models.by_name(spec.get("modelName", ""))
    if model is None:
        raise Exception("model was not found: " + str(spec.get("modelName")))
    note = col.new_note(model)
    by_lower = {f["name"].lower(): f["name"] for f in model["flds"]}
    for key, val in (spec.get("fields") or {}).items():
        real = by_lower.get(str(key).lower())
        if real is not None:
            note[real] = val
    for tag in spec.get("tags") or []:
        note.add_tag(tag)
    return note, model


def check_addable(col, note, options):
    options = options or {}
    fc = note.fields_check()
    if fc == _EMPTY:
        return False, "cannot create note because it is empty"
    if fc == _DUPLICATE and not options.get("allowDuplicate", False):
        return False, "cannot create note because it is a duplicate"
    return True, None


def note_to_info(col, note):
    model = note.note_type()
    fields = {}
    for name, (ord_, _f) in col.models.field_map(model).items():
        fields[name] = {"value": note.fields[ord_], "order": ord_}
    return {
        "noteId": note.id,
        "profile": "User 1",
        "tags": list(note.tags),
        "fields": fields,
        "modelName": model["name"],
        "mod": note.mod,
        "cards": list(note.card_ids()),
    }


def card_to_info(col, card):
    note = card.note()
    model = note.note_type()
    fields = {}
    for name, (ord_, _f) in col.models.field_map(model).items():
        fields[name] = {"value": note.fields[ord_], "order": ord_}
    try:
        states = col._backend.get_scheduling_states(card.id)
        next_reviews = list(col.sched.describe_next_states(states))
    except Exception:
        next_reviews = []
    return {
        "cardId": card.id,
        "note": note.id,
        "deckName": col.decks.name(card.did),
        "modelName": model["name"],
        "fieldOrder": card.ord,
        "fields": fields,
        "question": card.question(),
        "answer": card.answer(),
        "css": model.get("css", ""),
        "ord": card.ord,
        "type": card.type,
        "queue": card.queue,
        "due": card.due,
        "reps": card.reps,
        "lapses": card.lapses,
        "left": card.left,
        "mod": card.mod,
        "factor": card.factor,
        "interval": card.ivl,
        "nextReviews": next_reviews,
    }


def _empty_load(col, ntid: int) -> dict:
    model = col.models.get(ntid)
    flds = model["flds"]
    return {
        "fields": [[f["name"], ""] for f in flds],
        "fonts": [
            [f.get("font", "Arial"), int(f.get("size", 20)), bool(f.get("rtl", False))]
            for f in flds
        ],
        "io": False,
        "noteId": 0,
        "meta": {"id": model["id"], "modTime": model.get("mod", 0)},
        "tags": [],
    }


def load_data_for_spec(col, note_spec) -> dict | None:
    """Build the `ankiwebLoadNote` payload for an AnkiConnect note spec
    (modelName/fields/tags) — used by guiAddCards/guiAddNoteSetData to live-prefill
    the open Add dialog. Returns None if the model is unknown (case-insensitive fields)."""
    spec = note_spec or {}
    model = (
        col.models.by_name(spec.get("modelName", "")) if spec.get("modelName") else None
    )
    if model is None:
        return None
    d = _empty_load(col, model["id"])
    by_lower = {f["name"].lower(): i for i, f in enumerate(model["flds"])}
    for key, val in (spec.get("fields") or {}).items():
        i = by_lower.get(str(key).lower())
        if i is not None:
            d["fields"][i][1] = val
    d["tags"] = list(spec.get("tags") or [])
    return d
