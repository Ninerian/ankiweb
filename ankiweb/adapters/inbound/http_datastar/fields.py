from __future__ import annotations
import html
from typing import Callable
from fastapi import APIRouter
from datastar_py.fastapi import (
    DatastarResponse,
    ServerSentEventGenerator as SSE,
    ReadSignals,
)
from ankiweb.core.i18n import tr
from ankiweb.adapters.inbound.http_shared import templating


def render_fields_html(col, ntid: int) -> str:
    m = col.models.get(ntid)
    sortf = m["sortf"]
    fields = [
        {
            "ord": f["ord"],
            "name": f.get("name", ""),
            "font": f.get("font", "Arial"),
            "size": int(f.get("size", 20)),
            "rtl": bool(f.get("rtl", False)),
            "description": f.get("description", ""),
        }
        for f in m["flds"]
    ]
    return templating.render(
        "fields.html.jinja",
        fields=fields,
        sortf=sortf,
        ntid=int(ntid),
        add_label=tr.fields_add_field(),
        save_label=tr.actions_save(),
        cancel_label=tr.actions_cancel(),
    )


def make_fields_routes(get_service: Callable) -> APIRouter:
    router = APIRouter(prefix="/fields")

    @router.post("/cancel")
    async def cancel():
        return DatastarResponse(SSE.redirect("/deckbrowser"))

    @router.post("/savefields")
    async def save_fields(payload: ReadSignals):
        service = get_service()
        if not payload or not isinstance(payload, dict):
            return DatastarResponse()
        p = payload

        def apply(col):
            ntid = int(p["notetypeId"])
            m = col.models.get(ntid)
            cur = list(m["flds"])
            by_ord = {f["ord"]: f for f in cur}
            payload_fields = p["fields"]
            kept = {f["orig"] for f in payload_fields if f.get("orig") is not None}
            deletes = [f for f in cur if f["ord"] not in kept]
            remaining = (
                len(cur)
                - len(deletes)
                + sum(1 for f in payload_fields if f.get("orig") is None)
            )
            if len(payload_fields) == 0 or remaining < 1:
                raise Exception("a notetype needs at least one field")
            for f in deletes:
                col.models.remove_field(m, f)
            for fp in payload_fields:
                if fp.get("orig") is not None:
                    fd = by_ord[fp["orig"]]
                    if fd["name"] != fp["name"]:
                        col.models.rename_field(m, fd, fp["name"])
            for fp in payload_fields:
                if fp.get("orig") is None:
                    col.models.add_field(m, col.models.new_field(fp["name"]))

            def by_name(nm):
                return next(x for x in m["flds"] if x["name"] == nm)

            for i, fp in enumerate(payload_fields):
                fd = by_name(fp["name"])
                fd["font"] = fp.get("font", "Arial")
                fd["size"] = int(fp.get("size", 20))
                fd["rtl"] = bool(fp.get("rtl", False))
                fd["description"] = fp.get("description", "")
                col.models.reposition_field(m, fd, i)
            col.models.set_sort_index(m, int(p.get("sortf", 0)))
            return col.models.update_dict(m)

        try:
            await service.run_op(apply, initiator="fields")
        except Exception as exc:
            err_html = f'<div id="err" style="color:#c00;margin-top:8px;">{html.escape(str(exc))}</div>'
            return DatastarResponse(SSE.patch_elements(err_html, selector="#err"))

        return DatastarResponse(SSE.redirect("/deckbrowser"))

    return router
