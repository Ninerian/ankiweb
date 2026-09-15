from __future__ import annotations
import json
from typing import Any
from ankiweb.i18n import tr
from ankiweb.screens import templating
from ankiweb.screens.editor import _munge, paste_handler_js, editor_links_js
from ankiweb.ankiconnect.actions._helpers import check_addable
from ankiweb.adapters.outbound.anki_collection_adapter import op_changes_to_flags


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


def add_page_body(decks, notetypes, paste_handler_js: str, editor_links_js: str) -> str:
    return templating.render(
        "add_page_body.html.jinja",
        decks=decks,
        notetypes=notetypes,
        paste_handler_js=paste_handler_js,
        editor_links_js=editor_links_js,
    )


def render_add_html(col) -> str:
    cur_nt = col.models.current()["id"]
    cur_did = col.decks.get_current_id()
    decks = [
        {"id": d.id, "name": d.name, "selected": d.id == cur_did}
        for d in col.decks.all_names_and_ids()
    ]
    notetypes = [
        {"id": m.id, "name": m.name, "selected": m.id == cur_nt}
        for m in col.models.all_names_and_ids()
    ]
    return add_page_body(decks, notetypes, paste_handler_js(), editor_links_js())


def make_add_handler(service, hub):
    state: dict[str, Any] = {"notetype_id": None, "deck_id": None, "tags": []}

    async def handler(arg: str):
        head, _, rest = arg.partition(":")
        if head == "addReady":

            def init(col):
                ntid = int(col.models.current()["id"])
                did = int(col.decks.get_current_id())
                return ntid, did, _empty_load(col, ntid)

            ntid, did, data = await service.run(init)
            state.update(notetype_id=ntid, deck_id=did, tags=[])
            await hub.push_call("add", "ankiwebLoadNote", [data])
        elif head == "setnotetype":
            ntid = int(rest)
            state["notetype_id"] = ntid
            state["tags"] = []
            data = await service.run(lambda col: _empty_load(col, ntid))
            await hub.push_call("add", "ankiwebLoadNote", [data])
        elif head == "setdeck":
            state["deck_id"] = int(rest)
        elif head == "saveTags":
            state["tags"] = json.loads(rest)
        elif head == "addnote":
            fields = json.loads(rest)
            ntid_raw = state["notetype_id"]
            did_raw = state["deck_id"]
            ntid = int(ntid_raw) if ntid_raw is not None else 0
            did = int(did_raw) if did_raw is not None else 0
            tags = list(state["tags"] or [])

            def add(col):
                model = col.models.get(ntid)
                note = col.new_note(model)
                for i, h in enumerate(fields):
                    if i < len(note.fields):
                        note.fields[i] = _munge(col, h)
                note.tags = tags
                ok, err = check_addable(col, note, None)
                if not ok:
                    return (None, err), None
                op = col.add_note(note, did)
                return (note.id, None), op

            (nid, err), op = await service.run(add)
            if op is not None:
                flags = op_changes_to_flags(getattr(op, "changes", op))
                if any(flags.values()):
                    await service.emit(flags, "add")
            if err:
                await hub.push_call("add", "ankiwebToast", [err])
            else:
                data = await service.run(lambda col: _empty_load(col, ntid))
                await hub.push_call("add", "ankiwebLoadNote", [data])
                await hub.push_call("add", "ankiwebToast", [tr.adding_added()])
        return None

    return handler
