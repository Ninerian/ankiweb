from __future__ import annotations
import json
from ankiweb.i18n import tr
from ankiweb.screens import templating


def render_card_layout_html(col, ntid: int) -> str:
    m = col.models.get(ntid)
    templates = [
        {
            "ord": t["ord"],
            "name": t.get("name", ""),
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


def make_card_layout_handler(service, hub):
    state = {"ntid": None}

    async def handler(arg: str):
        cmd, _, rest = arg.partition(":")
        if cmd == "cancel":
            await hub.push_call("cardlayout", "ankiwebNavigate", ["/deckbrowser"])
            return None
        if cmd == "previewlayout":
            # rest carries the ntid (the page knows it via #ntid); fall back to the most
            # recent notetype the page reported so a bare 'previewlayout' still works.
            ntid = None
            if rest:
                try:
                    ntid = int(rest)
                except ValueError:
                    ntid = None
            if ntid is None:
                ntid = state["ntid"]

            def find_nid(col):
                if ntid is not None:
                    return (col.models.nids(ntid) or [None])[0]
                # no ntid context: pick the first notetype that has notes
                for m in col.models.all():
                    nids = col.models.nids(m["id"])
                    if nids:
                        return nids[0]
                return None

            nid = await service.run(find_nid)
            if nid is not None:
                await hub.push_call("cardlayout", "ankiwebNavigate", ["/preview/" + str(nid)])
            else:
                await hub.push_call(
                    "cardlayout", "ankiwebCardLayoutError",
                    ["Add a note of this type first to preview."])
            return None
        if cmd != "savelayout":
            return None
        try:
            p = json.loads(rest)
        except Exception:
            return None
        state["ntid"] = int(p["notetypeId"])

        def apply(col):
            ntid = int(p["notetypeId"]); m = col.models.get(ntid)
            cur = list(m["tmpls"]); by_ord = {t["ord"]: t for t in cur}
            payload = p["templates"]
            kept = {t["orig"] for t in payload if t.get("orig") is not None}
            deletes = [t for t in cur if t["ord"] not in kept]
            remaining = len(cur) - len(deletes) + sum(1 for t in payload if t.get("orig") is None)
            if len(payload) == 0 or remaining < 1:
                raise Exception("a notetype needs at least one card type")
            for t in deletes:
                col.models.remove_template(m, t)
            for tp in payload:
                if tp.get("orig") is not None:
                    td = by_ord[tp["orig"]]
                    td["name"] = tp["name"]
                    td["qfmt"] = tp.get("qfmt", "")
                    td["afmt"] = tp.get("afmt", "")
            for tp in payload:
                if tp.get("orig") is None:
                    nt = col.models.new_template(tp["name"])
                    nt["qfmt"] = tp.get("qfmt", "")
                    nt["afmt"] = tp.get("afmt", "")
                    col.models.add_template(m, nt)

            def by_name(nm):
                return next(x for x in m["tmpls"] if x["name"] == nm)
            for i, tp in enumerate(payload):
                col.models.reposition_template(m, by_name(tp["name"]), i)
            m["css"] = p.get("css", "")
            return col.models.update_dict(m)

        try:
            await service.run_op(apply, initiator="cardlayout")
        except Exception as exc:
            await hub.push_call("cardlayout", "ankiwebCardLayoutError", [str(exc)])
            return None
        await hub.push_call("cardlayout", "ankiwebNavigate", ["/deckbrowser"])
        return None

    return handler
