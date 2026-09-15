from __future__ import annotations
import copy
import html
from typing import Callable
from fastapi import APIRouter
from datastar_py.fastapi import (
    DatastarResponse,
    ServerSentEventGenerator as SSE,
    ReadSignals,
)
from ankiweb.i18n import tr
from ankiweb.adapters.inbound.http_shared import templating


def _heading() -> str:
    """Prefer the desktop "Manage Note Types" string; fall back to a keyless heading.
    (qt_misc_manage_note_types exists; notetypes_notetypes does not.)"""
    try:
        return tr.qt_misc_manage_note_types()
    except Exception:
        return "Note Types"


def render_notetypes_html(col) -> str:
    rows = []
    for nt in col.models.all_names_and_ids():
        ntid = int(nt.id)
        count = len(col.models.nids(ntid))
        rows.append({"id": ntid, "name": nt.name, "count": count})

    return templating.render(
        "notetypes.html.jinja",
        heading=_heading(),
        rows=rows,
        L_rename=tr.actions_rename(),
        L_delete=tr.actions_delete(),
        L_add=tr.actions_add(),
        L_name=tr.actions_name(),
        L_fields=tr.notetypes_fields(),
        L_cards=tr.notetypes_cards(),
    )


def make_notetypes_routes(get_service: Callable) -> APIRouter:
    router = APIRouter(prefix="/notetypes")

    @router.post("/rename/{ntid}")
    async def rename(ntid: int, payload: ReadSignals):
        service = get_service()
        newname = ""
        if payload and isinstance(payload, dict):
            newname = str(payload.get("name", "")).strip()
        if not newname:
            err_html = '<div id="err" style="color:#c00;margin-top:8px;">A name is required.</div>'
            return DatastarResponse(SSE.patch_elements(err_html, selector="#err"))

        def do_rename(col):
            m = col.models.get(ntid)
            m["name"] = newname
            return col.models.update_dict(m)

        try:
            await service.run_op(do_rename, initiator="notetypes")
        except Exception as exc:
            err_html = f'<div id="err" style="color:#c00;margin-top:8px;">{html.escape(str(exc))}</div>'
            return DatastarResponse(SSE.patch_elements(err_html, selector="#err"))

        return DatastarResponse(SSE.execute_script("window.location.reload()"))

    @router.post("/delete/{ntid}")
    async def delete_notetype(ntid: int):
        service = get_service()
        if await service.run(lambda col: len(col.models.all_names_and_ids())) <= 1:
            err_html = '<div id="err" style="color:#c00;margin-top:8px;">Cannot delete the only note type</div>'
            return DatastarResponse(SSE.patch_elements(err_html, selector="#err"))

        def do_delete(col):
            return col.models.remove(ntid)

        try:
            await service.run_op(do_delete, initiator="notetypes")
        except Exception as exc:
            err_html = f'<div id="err" style="color:#c00;margin-top:8px;">{html.escape(str(exc))}</div>'
            return DatastarResponse(SSE.patch_elements(err_html, selector="#err"))

        return DatastarResponse(SSE.execute_script("window.location.reload()"))

    @router.post("/add/{base_ntid}")
    async def add_notetype(base_ntid: int, payload: ReadSignals):
        service = get_service()
        newname = ""
        if payload and isinstance(payload, dict):
            newname = str(payload.get("name", "")).strip()
        if not newname:
            err_html = '<div id="err" style="color:#c00;margin-top:8px;">A name is required.</div>'
            return DatastarResponse(SSE.patch_elements(err_html, selector="#err"))

        def do_add(col):
            base = col.models.get(base_ntid)
            nt = copy.deepcopy(base)
            nt["name"] = newname
            nt["id"] = 0
            return col.models.add_dict(nt)

        try:
            await service.run_op(do_add, initiator="notetypes")
        except Exception as exc:
            err_html = f'<div id="err" style="color:#c00;margin-top:8px;">{html.escape(str(exc))}</div>'
            return DatastarResponse(SSE.patch_elements(err_html, selector="#err"))

        return DatastarResponse(SSE.execute_script("window.location.reload()"))

    return router
