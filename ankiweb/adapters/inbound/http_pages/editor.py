from __future__ import annotations
import json
import logging
from typing import Any, Callable

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from datastar_py.fastapi import (
    DatastarResponse,
    ServerSentEventGenerator as SSE,
    ReadSignals,
)

from ankiweb.core.i18n import tr
from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.adapters.inbound.http_shared.page import render_page
from ankiweb.core.ankiconnect_actions.actions._helpers import check_addable
from ankiweb.core.op_changes import op_changes_to_flags
from ankiweb.adapters.inbound.http_screens.editor import _munge

logger = logging.getLogger(__name__)


def _build_editor_context(
    col,
    mode: str,  # "add" or "edit"
    nid: int | None = None,
    notetype_id: int | None = None,
    deck_id: int | None = None,
    sticky_values: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Prepares template context and initial signals for /edit and /add."""
    if sticky_values is None:
        sticky_values = {}

    decks_raw = col.decks.all_names_and_ids()
    cur_did = deck_id or col.decks.get_current_id()
    decks = [{"id": d.id, "name": d.name} for d in decks_raw]

    notetypes_raw = col.models.all_names_and_ids()
    notetypes = [{"id": m.id, "name": m.name} for m in notetypes_raw]

    note = None
    if mode == "edit" and nid is not None:
        note = col.get_note(nid)
        model = note.note_type()
        notetype_id = model["id"]
        notetype_name = model["name"]
        tags = list(note.tags)
        field_vals = list(note.fields)
    else:
        # Add mode
        if not notetype_id:
            notetype_id = int(col.models.current()["id"])
        model = col.models.get(notetype_id)
        notetype_name = model["name"]
        tags = []
        field_vals = ["" for _ in model["flds"]]
        # Prepopulate sticky values if any
        for idx, val in sticky_values.items():
            if idx < len(field_vals):
                field_vals[idx] = val

    cloze_ords = set(col.models.cloze_fields(model["id"]))
    flds = model["flds"]

    fields_info = []
    signals = {
        "mode": mode,
        "nid": nid,
        "notetype_id": notetype_id,
        "deck_id": cur_did,
        "tags_str": " ".join(tags),
        "is_duplicate": False,
        "toast_msg": "",
        "context_menu": {"visible": False, "x": 0, "y": 0},
    }

    for i, fld in enumerate(flds):
        val = field_vals[i] if i < len(field_vals) else ""
        collapsed = bool(fld.get("collapsed", False))
        sticky = bool(fld.get("sticky", False))
        plain_text = bool(fld.get("plainText", False))
        is_cloze = i in cloze_ords
        desc = fld.get("description", "")
        font = fld.get("font", "Arial")
        size = int(fld.get("size", 20))
        rtl = bool(fld.get("rtl", False))

        fields_info.append({
            "index": i,
            "name": fld["name"],
            "value": val,
            "collapsed": collapsed,
            "sticky": sticky,
            "plain_text": plain_text,
            "is_cloze": is_cloze,
            "description": desc,
            "font": font,
            "size": size,
            "rtl": rtl,
        })

        signals[f"field_val_{i}"] = val
        signals[f"field_collapsed_{i}"] = collapsed
        signals[f"field_sticky_{i}"] = sticky
        signals[f"field_plain_{i}"] = plain_text
        signals[f"field_saving_{i}"] = False
        signals[f"field_saved_{i}"] = False

    return {
        "mode": mode,
        "nid": nid,
        "notetype_id": notetype_id,
        "notetype_name": notetype_name,
        "deck_id": cur_did,
        "decks": decks,
        "notetypes": notetypes,
        "fields": fields_info,
        "tags": tags,
        "initial_signals_json": json.dumps(signals),
    }


def make_router(get_service: Callable) -> APIRouter:
    router = APIRouter()
    # In-memory store for sticky fields in Add mode per session
    sticky_storage: dict[int, dict[int, str]] = {}  # notetype_id -> {field_idx: val}

    @router.get("/edit")
    async def get_edit(nid: int = Query(...)):
        service = get_service()

        def build(col):
            ctx = _build_editor_context(col, mode="edit", nid=nid)
            body = templating.render("pages/editor.html.jinja", **ctx)
            return render_page(
                context="editor",
                body=body,
                toolbar=False,
            )

        html = await service.run(build)
        return HTMLResponse(html)

    @router.get("/add")
    async def get_add():
        service = get_service()

        def build(col):
            cur_ntid = int(col.models.current()["id"])
            sticky = sticky_storage.get(cur_ntid, {})
            ctx = _build_editor_context(col, mode="add", notetype_id=cur_ntid, sticky_values=sticky)
            body = templating.render("pages/editor.html.jinja", **ctx)
            return render_page(
                context="add",
                body=body,
                toolbar=True,
            )

        html = await service.run(build)
        return HTMLResponse(html)

    @router.post("/editor/save-field")
    async def save_field(request: Request, payload_signals: ReadSignals = None):
        service = get_service()
        body_bytes = await request.body()
        payload = {}
        if body_bytes:
            try:
                payload = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                pass
        if not payload and payload_signals:
            payload = payload_signals
        if payload_signals:
            if not payload.get("nid") and payload_signals.get("nid"):
                payload["nid"] = payload_signals.get("nid")

        idx = int(payload.get("index", 0))
        html_val = str(payload.get("html", payload.get(f"field_val_{idx}", "")))
        nid = payload.get("nid")
        def fn(col):
            if nid is not None:
                note = col.get_note(int(nid))
                if 0 <= idx < len(note.fields):
                    note.fields[idx] = _munge(col, html_val)
                    col.update_note(note, skip_undo_entry=True)
            return True

        if nid is not None:
            await service.run(fn)

        return DatastarResponse(
            SSE.patch_signals({
                f"field_val_{idx}": html_val,
                f"field_saving_{idx}": False,
                f"field_saved_{idx}": True,
            })
        )

    @router.post("/editor/blur-field")
    async def blur_field(request: Request, payload_signals: ReadSignals = None):
        service = get_service()
        body_bytes = await request.body()
        payload = {}
        if body_bytes:
            try:
                payload = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                pass
        logger.warning(f"BLUR_FIELD payload={payload}, payload_signals={payload_signals}")
        if not payload and payload_signals:
            payload = payload_signals
        if payload_signals:
            if not payload.get("nid") and payload_signals.get("nid"):
                payload["nid"] = payload_signals.get("nid")
        idx = int(payload.get("index", 0))
        html_val = str(payload.get("html", payload.get(f"field_val_{idx}", "")))
        nid = payload.get("nid")
        def fn(col):
            if nid is not None:
                note = col.get_note(int(nid))
                if 0 <= idx < len(note.fields):
                    note.fields[idx] = _munge(col, html_val)
                    return col.update_note(note, skip_undo_entry=True)
            return None

        if nid is not None:
            await service.run_op(fn, initiator="editor")
        return DatastarResponse(
            SSE.patch_signals({
                f"field_val_{idx}": html_val,
                f"field_saving_{idx}": False,
                f"field_saved_{idx}": True,
            })
        )

    @router.post("/editor/save-tags")
    async def save_tags(payload: ReadSignals):
        service = get_service()
        if not payload or not isinstance(payload, dict):
            return DatastarResponse()

        nid = payload.get("nid")
        tags_raw = payload.get("tags")
        if tags_raw is None:
            tags_str = str(payload.get("tags_str", ""))
            tags = [t.strip() for t in tags_str.split() if t.strip()]
        elif isinstance(tags_raw, list):
            tags = [str(t).strip() for t in tags_raw if str(t).strip()]
        else:
            tags = [str(tags_raw).strip()]

        if nid is not None:
            def fn(col):
                note = col.get_note(int(nid))
                note.tags = tags
                return col.update_note(note, skip_undo_entry=True)

            await service.run_op(fn, initiator="editor")

        return DatastarResponse(
            SSE.patch_signals({"tags_str": " ".join(tags)})
        )

    @router.post("/editor/toggle-collapse")
    async def toggle_collapse(payload: ReadSignals, idx: int = Query(...)):
        service = get_service()
        if not payload or not isinstance(payload, dict):
            return DatastarResponse()

        ntid = payload.get("notetype_id")
        if ntid is not None:
            def fn(col):
                model = col.models.get(int(ntid))
                if 0 <= idx < len(model["flds"]):
                    cur = bool(model["flds"][idx].get("collapsed", False))
                    model["flds"][idx]["collapsed"] = not cur
                    col.models.save(model)
                    return not cur
                return False

            new_collapsed = await service.run(fn)
            return DatastarResponse(
                SSE.patch_signals({f"field_collapsed_{idx}": new_collapsed})
            )
        return DatastarResponse()

    @router.post("/editor/toggle-sticky")
    async def toggle_sticky(payload: ReadSignals, idx: int = Query(...)):
        service = get_service()
        if not payload or not isinstance(payload, dict):
            return DatastarResponse()

        ntid = payload.get("notetype_id")
        if ntid is not None:
            def fn(col):
                model = col.models.get(int(ntid))
                if 0 <= idx < len(model["flds"]):
                    cur = bool(model["flds"][idx].get("sticky", False))
                    model["flds"][idx]["sticky"] = not cur
                    col.models.save(model)
                    return not cur
                return False

            new_sticky = await service.run(fn)
            return DatastarResponse(
                SSE.patch_signals({f"field_sticky_{idx}": new_sticky})
            )
        return DatastarResponse()

    @router.post("/editor/change-notetype")
    async def change_notetype(payload: ReadSignals):
        service = get_service()
        if not payload or not isinstance(payload, dict):
            return DatastarResponse()

        ntid = int(payload.get("notetype_id", 0))
        did = int(payload.get("deck_id", 0))
        sticky = sticky_storage.get(ntid, {})

        def render(col):
            col.models.set_current(col.models.get(ntid))
            ctx = _build_editor_context(col, mode="add", notetype_id=ntid, deck_id=did, sticky_values=sticky)
            return templating.render("pages/editor.html.jinja", **ctx)

        html = await service.run(render)
        return DatastarResponse(SSE.patch_elements(html, selector="#editor-root"))

    @router.post("/editor/change-deck")
    async def change_deck(payload: ReadSignals):
        service = get_service()
        if not payload or not isinstance(payload, dict):
            return DatastarResponse()

        did = int(payload.get("deck_id", 0))

        def fn(col):
            col.decks.select(did)
            return True

        await service.run(fn)
        return DatastarResponse(SSE.patch_signals({"deck_id": did}))

    @router.post("/editor/undo")
    async def undo():
        service = get_service()

        def do_undo(col):
            from anki.errors import UndoEmpty
            if not col.undo_status().undo:
                return False, "Nothing to undo"
            try:
                op = col.undo()
                return True, "Undone"
            except UndoEmpty:
                return False, "Nothing to undo"

        success, msg = await service.run(do_undo)
        return DatastarResponse(
            SSE.patch_signals({"toast_msg": msg})
        )

    @router.post("/editor/add-note")
    async def add_note(payload: ReadSignals):
        service = get_service()
        if not payload or not isinstance(payload, dict):
            return DatastarResponse()

        ntid = int(payload.get("notetype_id", 0))
        did = int(payload.get("deck_id", 0))
        tags_str = str(payload.get("tags_str", ""))
        tags = [t.strip() for t in tags_str.split() if t.strip()]

        def do_add(col):
            model = col.models.get(ntid)
            note = col.new_note(model)
            num_flds = len(model["flds"])

            for i in range(num_flds):
                raw_val = payload.get(f"field_val_{i}", "")
                note.fields[i] = _munge(col, str(raw_val))

            note.tags = tags
            ok, err = check_addable(col, note, None)
            if not ok:
                return (None, err), False

            op = col.add_note(note, did)
            return (note.id, None), op

        (note_id, err), op = await service.run(do_add)

        if op:
            flags = op_changes_to_flags(getattr(op, "changes", op))
            if any(flags.values()):
                await service.emit(flags, "add")

        if err:
            is_dup = "duplicate" in err.lower()
            return DatastarResponse(
                SSE.patch_signals({
                    "toast_msg": err,
                    "is_duplicate": is_dup,
                })
            )

        # Successful addition! Record sticky field values
        def get_model_sticky(col):
            m = col.models.get(ntid)
            sticky_dict = {}
            for i, fld in enumerate(m["flds"]):
                if fld.get("sticky", False):
                    sticky_dict[i] = _munge(col, str(payload.get(f"field_val_{i}", "")))
            return sticky_dict

        sticky = await service.run(get_model_sticky)
        sticky_storage[ntid] = sticky

        # Rerender blank note preserving sticky fields
        def render_fresh(col):
            ctx = _build_editor_context(col, mode="add", notetype_id=ntid, deck_id=did, sticky_values=sticky)
            return templating.render("pages/editor.html.jinja", **ctx)

        html = await service.run(render_fresh)

        # Re-render the container and show success toast
        return DatastarResponse(
            [
                SSE.patch_elements(html, selector="#editor-root"),
                SSE.patch_signals({"toast_msg": tr.adding_added(), "is_duplicate": False}),
            ]
        )

    return router
