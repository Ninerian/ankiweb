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
from ankiweb.core.i18n import tr

logger = logging.getLogger(__name__)

def render_fields_html(col, ntid: int) -> str:
    m = col.models.get(ntid)
    sortf = m["sortf"]
    rows = {}
    order = []
    fields_for_template = []
    sort_key = ""
    for idx, f in enumerate(m["flds"]):
        key = f"f{idx}"
        order.append(key)
        row = {
            "orig": f["ord"],
            "name": f.get("name", ""),
            "font": f.get("font", "Arial"),
            "size": int(f.get("size", 20)),
            "rtl": bool(f.get("rtl", False)),
            "description": f.get("description", ""),
        }
        rows[key] = row
        fields_for_template.append({**row, "key": key})
        if f["ord"] == sortf:
            sort_key = key
    if not sort_key and order:
        sort_key = order[0]

    field_draft = {
        "rows": rows,
        "order": order,
        "nextId": len(order),
        "sortKey": sort_key,
    }
    return templating.render(
        "fields.html.jinja",
        fields=fields_for_template,
        field_draft=field_draft,
        ntid=int(ntid),
        add_label=tr.fields_add_field(),
        save_label=tr.actions_save(),
        cancel_label=tr.actions_cancel(),
    )

def make_fields_routes(get_service: Callable) -> APIRouter:
    router = APIRouter(prefix="/fields")

    @router.post("/cancel")
    async def cancel():
        return redirect_response("/deckbrowser")
    @router.post("/savefields")
    async def save_fields(payload: ReadSignals):
        service = get_service()
        if not payload or not isinstance(payload, dict):
            return DatastarResponse()
        p = payload

        # Normalize canonical fieldDraft structure if present, with fallback for direct fields payloads
        if "fieldDraft" in p and isinstance(p["fieldDraft"], dict):
            draft = p["fieldDraft"]
            rows = draft.get("rows", {}) or {}
            order = draft.get("order", []) or []
            sort_key = draft.get("sortKey")

            payload_fields = []
            for key in order:
                if key in rows:
                    payload_fields.append(dict(rows[key]))

            if sort_key in order:
                sortf = order.index(sort_key)
            elif payload_fields:
                sortf = 0
            else:
                sortf = 0
        else:
            payload_fields = p.get("fields", [])
            sortf = int(p.get("sortf", 0))

        def apply(col):
            ntid = int(p["notetypeId"])
            m = col.models.get(ntid)
            cur = list(m["flds"])
            by_ord = {f["ord"]: f for f in cur}
            kept = {f["orig"] for f in payload_fields if f.get("orig") is not None}
            deletes = [f for f in cur if f["ord"] not in kept]
            remaining = (
                len(cur)
                - len(deletes)
                + sum(1 for f in payload_fields if f.get("orig") is None)
            )
            if len(payload_fields) == 0 or remaining < 1:
                raise ValueError("a notetype needs at least one field")
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
            col.models.set_sort_index(m, sortf)
            changes = col.models.update_dict(m)
            # If Anki's backend remapped sortf during field addition/removal, re-apply desired sortf
            m_reloaded = col.models.get(ntid)
            if m_reloaded["sortf"] != sortf:
                col.models.set_sort_index(m_reloaded, sortf)
                col.models.update_dict(m_reloaded)
            return changes
        try:
            await service.run_op(apply, initiator="fields")
        except Exception as exc:
            logger.exception("Failed to save note type fields")
            return error_response(exc)

        return redirect_response("/deckbrowser")

    return router
