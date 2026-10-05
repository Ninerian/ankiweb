from __future__ import annotations

import copy
import logging
from collections.abc import Callable

from datastar_py.fastapi import (
    DatastarResponse,
    ReadSignals,
)
from datastar_py.fastapi import (
    ServerSentEventGenerator as SSE,
)
from fastapi import APIRouter

from ankiweb.adapters.inbound.http_datastar.common import error_response
from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.core.i18n import tr

logger = logging.getLogger(__name__)

def _heading() -> str:
    """Prefer the desktop "Manage Note Types" string; fall back to a keyless heading.
    (qt_misc_manage_note_types exists; notetypes_notetypes does not.)"""
    try:
        return tr.qt_misc_manage_note_types()
    except AttributeError:
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
            return error_response("A name is required.")

        def do_rename(col):
            m = col.models.get(ntid)
            m["name"] = newname
            return col.models.update_dict(m)

        try:
            await service.run_op(do_rename, initiator="notetypes")
        except Exception as exc:
            logger.exception("Failed to rename note type %s", ntid)
            return error_response(exc)

        return DatastarResponse(SSE.execute_script("window.location.reload()"))

    @router.post("/delete/{ntid}")
    async def delete_notetype(ntid: int):
        service = get_service()
        if await service.run(lambda col: len(col.models.all_names_and_ids())) <= 1:
            return error_response("Cannot delete the only note type")

        def do_delete(col):
            return col.models.remove(ntid)

        try:
            await service.run_op(do_delete, initiator="notetypes")
        except Exception as exc:
            logger.exception("Failed to delete note type %s", ntid)
            return error_response(exc)

        return DatastarResponse(SSE.execute_script("window.location.reload()"))

    @router.post("/add/{base_ntid}")
    async def add_notetype(base_ntid: int, payload: ReadSignals):
        service = get_service()
        newname = ""
        if payload and isinstance(payload, dict):
            newname = str(payload.get("name", "")).strip()
        if not newname:
            return error_response("A name is required.")

        def do_add(col):
            base = col.models.get(base_ntid)
            nt = copy.deepcopy(base)
            nt["name"] = newname
            nt["id"] = 0
            return col.models.add_dict(nt)

        try:
            await service.run_op(do_add, initiator="notetypes")
        except Exception as exc:
            logger.exception("Failed to add note type based on %s", base_ntid)
            return error_response(exc)

        return DatastarResponse(SSE.execute_script("window.location.reload()"))

    return router
