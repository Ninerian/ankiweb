from __future__ import annotations

import logging
from collections.abc import Callable

from datastar_py.fastapi import (
    DatastarResponse,
    ReadSignals,
)
from fastapi import APIRouter

from ankiweb.adapters.inbound.http_datastar.common import (
    error_response,
    redirect_response,
)
from ankiweb.adapters.inbound.http_shared import templating

logger = logging.getLogger(__name__)

def render_card_layout_html(col, ntid: int) -> str:
    m = col.models.get(ntid)
    rows = {}
    order = []
    templates_for_template = []
    for idx, t in enumerate(m["tmpls"]):
        key = f"t{idx}"
        order.append(key)
        row = {
            "orig": t["ord"],
            "name": t.get("name", ""),
            "qfmt": t.get("qfmt", ""),
            "afmt": t.get("afmt", ""),
        }
        rows[key] = row
        templates_for_template.append({**row, "key": key})

    css = m.get("css", "")
    layout_draft = {
        "rows": rows,
        "order": order,
        "nextId": len(order),
        "css": css,
    }
    return templating.render(
        "card_layout.html.jinja",
        templates=templates_for_template,
        layout_draft=layout_draft,
        css=css,
        ntid=int(ntid),
    )


def make_card_layout_routes(get_service: Callable) -> APIRouter:
    router = APIRouter(prefix="/card-layout")
    state: dict[str, int | None] = {"ntid": None}

    @router.post("/cancel")
    async def cancel():
        return redirect_response("/deckbrowser")
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
            return redirect_response(f"/preview/{nid}")
        else:
            return error_response("Add a note of this type first to preview.")

    @router.post("/savelayout")
    async def save_layout(payload: ReadSignals):
        service = get_service()
        if not payload or not isinstance(payload, dict):
            return DatastarResponse()
        p = payload
        state["ntid"] = int(p["notetypeId"])

        # Canonical layoutDraft structure strictly (no legacy payload fallback)
        draft = p.get("layoutDraft")
        if not isinstance(draft, dict):
            return DatastarResponse()
        rows = draft.get("rows", {}) or {}
        order = draft.get("order", []) or []
        payload_templates = []
        for key in order:
            if key in rows and isinstance(rows[key], dict):
                payload_templates.append(dict(rows[key]))
        css = draft.get("css", "")
        def apply(col):
            ntid = int(p["notetypeId"])
            m = col.models.get(ntid)
            cur = list(m["tmpls"])
            by_ord = {t["ord"]: t for t in cur}
            kept = {t["orig"] for t in payload_templates if t.get("orig") is not None}
            deletes = [t for t in cur if t["ord"] not in kept]
            remaining = (
                len(cur)
                - len(deletes)
                + sum(1 for t in payload_templates if t.get("orig") is None)
            )
            if len(payload_templates) == 0 or remaining < 1:
                raise ValueError("a notetype needs at least one card type")
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
            m["css"] = css
            return col.models.update_dict(m)

        try:
            await service.run_op(apply, initiator="cardlayout")
        except Exception as exc:
            logger.exception("Failed to save card layout")
            return error_response(exc)

        return redirect_response("/deckbrowser")

    return router
