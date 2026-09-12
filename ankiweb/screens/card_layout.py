from __future__ import annotations
import html
from typing import Callable
from fastapi import APIRouter
from datastar_py.fastapi import (
    DatastarResponse,
    ServerSentEventGenerator as SSE,
    ReadSignals,
)
from ankiweb.i18n import tr
from ankiweb.screens import templating


def render_card_layout_html(col, ntid: int) -> str:
    m = col.models.get(ntid)
    templates = [
        {
            "ord": t["ord"],
            "name": t["name"],
            "qfmt": t.get("qfmt", ""),
            "afmt": t.get("afmt", ""),
        }
        for t in m["tmpls"]
    ]
    css = m.get("css", "")
    return templating.render(
        "card_layout.html.jinja",
        templates=templates,
        css=css,
        ntid=int(ntid),
    )


def make_card_layout_routes(get_service: Callable) -> APIRouter:
    router = APIRouter(prefix="/card-layout")
    state = {"ntid": None}

    @router.post("/cancel")
    async def cancel():
        return DatastarResponse(SSE.redirect("/deckbrowser"))

    @router.post("/previewlayout")
    @router.post("/previewlayout/{ntid}")
    async def preview_layout(ntid: int | None = None):
        service = get_service()
        if ntid is None:
            ntid = state["ntid"]

        def find_nid(col):
            if ntid is not None:
                return (col.models.nids(ntid) or [None])[0]
            for m in col.models.all():
                nids = col.models.nids(m["id"])
                if nids:
                    return nids[0]
            return None

        nid = await service.run(find_nid)
        if nid is not None:
            return DatastarResponse(SSE.redirect(f"/preview/{nid}"))
        else:
            err_html = '<div id="err" style="color:#c00;margin-top:8px;">Add a note of this type first to preview.</div>'
            return DatastarResponse(SSE.patch_elements(err_html, selector="#err"))

    @router.post("/savelayout")
    async def save_layout(payload: ReadSignals):
        service = get_service()
        if not payload or not isinstance(payload, dict):
            return DatastarResponse()
        p = payload
        state["ntid"] = int(p["notetypeId"])

        def apply(col):
            ntid = int(p["notetypeId"])
            m = col.models.get(ntid)
            cur = list(m["tmpls"])
            by_ord = {t["ord"]: t for t in cur}
            payload_templates = p["templates"]
            kept = {t["orig"] for t in payload_templates if t.get("orig") is not None}
            deletes = [t for t in cur if t["ord"] not in kept]
            remaining = (
                len(cur)
                - len(deletes)
                + sum(1 for t in payload_templates if t.get("orig") is None)
            )
            if len(payload_templates) == 0 or remaining < 1:
                raise Exception("a notetype needs at least one card type")
            for t in deletes:
                col.models.remove_template(m, t)
            for tp in payload_templates:
                if tp.get("orig") is not None:
                    td = by_ord[tp["orig"]]
                    td["name"] = tp["name"]
                    td["qfmt"] = tp.get("qfmt", "")
                    td["afmt"] = tp.get("afmt", "")
            for tp in payload_templates:
                if tp.get("orig") is None:
                    nt = col.models.new_template(tp["name"])
                    nt["qfmt"] = tp.get("qfmt", "")
                    nt["afmt"] = tp.get("afmt", "")
                    col.models.add_template(m, nt)

            def by_name(nm):
                return next(x for x in m["tmpls"] if x["name"] == nm)

            for i, tp in enumerate(payload_templates):
                col.models.reposition_template(m, by_name(tp["name"]), i)
            m["css"] = p.get("css", "")
            return col.models.update_dict(m)

        try:
            await service.run_op(apply, initiator="cardlayout")
        except Exception as exc:
            err_html = f'<div id="err" style="color:#c00;margin-top:8px;">{html.escape(str(exc))}</div>'
            return DatastarResponse(SSE.patch_elements(err_html, selector="#err"))

        return DatastarResponse(SSE.redirect("/deckbrowser"))

    return router
