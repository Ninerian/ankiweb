from __future__ import annotations
import json
from ankiweb.i18n import tr
from ankiweb.screens import templating


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


def make_fields_handler(service, hub):
    async def handler(arg: str):
        cmd, _, rest = arg.partition(":")
        if cmd == "cancel":
            await hub.push_call("fields", "ankiwebNavigate", ["/deckbrowser"])
            return None
        if cmd != "savefields":
            return None
        try:
            p = json.loads(rest)
        except Exception:
            return None

        def apply(col):
            ntid = int(p["notetypeId"]); m = col.models.get(ntid)
            cur = list(m["flds"]); by_ord = {f["ord"]: f for f in cur}
            payload = p["fields"]
            kept = {f["orig"] for f in payload if f.get("orig") is not None}
            deletes = [f for f in cur if f["ord"] not in kept]
            remaining = len(cur) - len(deletes) + sum(1 for f in payload if f.get("orig") is None)
            if len(payload) == 0 or remaining < 1:
                raise Exception("a notetype needs at least one field")
            for f in deletes:
                col.models.remove_field(m, f)
            for fp in payload:
                if fp.get("orig") is not None:
                    fd = by_ord[fp["orig"]]
                    if fd["name"] != fp["name"]:
                        col.models.rename_field(m, fd, fp["name"])
            for fp in payload:
                if fp.get("orig") is None:
                    col.models.add_field(m, col.models.new_field(fp["name"]))

            def by_name(nm):
                return next(x for x in m["flds"] if x["name"] == nm)
            for i, fp in enumerate(payload):
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
            await hub.push_call("fields", "ankiwebFieldsError", [str(exc)])
            return None
        await hub.push_call("fields", "ankiwebNavigate", ["/deckbrowser"])
        return None

    return handler
