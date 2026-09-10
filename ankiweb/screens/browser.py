from __future__ import annotations
import re
from ankiweb.i18n import tr
from ankiweb.screens import templating

_TAG_STRIP = re.compile(r"<[^>]+>")
_LIMIT = 500

def render_browser_html(col, query: str = "") -> str:
    decks = [{"id": d.id, "name": d.name} for d in col.decks.all_names_and_ids()]
    tags = list(col.tags.all())
    return templating.render(
        "browser.html.jinja",
        decks=decks,
        tags=tags,
        query=query,
    )

def _row_data(col, cids):
    rows = []
    for cid in cids:
        try:
            card = col.get_card(cid)
        except Exception:
            continue
        note = card.note()
        model = note.note_type()
        sf = model.get("sortf", 0)
        sort = note.fields[sf] if sf < len(note.fields) else (note.fields[0] if note.fields else "")
        rows.append((cid, sort, col.decks.name(card.did), card.due))
    return rows


def _rows_html(rows) -> str:
    row_dicts = [
        {
            "cid": cid,
            "sort_text": _TAG_STRIP.sub("", sort)[:200],
            "deck": deck,
            "due": due,
        }
        for cid, sort, deck, due in rows
    ]
    return templating.render("browser_rows.html.jinja", rows=row_dicts)


def _detail_html(col, cid) -> str:
    card = col.get_card(cid)
    note = card.note()
    model = note.note_type()
    fields = [{"name": f["name"], "value": note.fields[i]} for i, f in enumerate(model["flds"])]
    tags = " ".join(note.tags)
    return templating.render(
        "browser_detail.html.jinja",
        deck_name=col.decks.name(card.did),
        tags=tags,
        fields=fields,
    )


def _io_detail_html(nid) -> str:
    return templating.render("browser_io_detail.html.jinja", nid=nid)

def make_browser_handler(service, hub):
    """Bridge handler for the 'browser' context."""
    async def _do_search(query: str):
        def run(col):
            try:
                cids = list(col.find_cards(query or ""))
            except Exception:
                return None, ""
            return cids, _rows_html(_row_data(col, cids[:_LIMIT]))
        cids, rows_html = await service.run(run)
        if cids is None:
            await hub.push_call("browser", "ankiwebSetRows",
                                ["<tr><td colspan='3'>invalid search</td></tr>", 0])
            return
        hub.ui_state.browser_open = True
        hub.ui_state.last_browse_query = query
        hub.ui_state.matched_card_ids = cids
        await hub.push_call("browser", "ankiwebSetRows", [rows_html, len(cids)])

    async def _reload():
        await _do_search(hub.ui_state.last_browse_query or "")
        await hub.push_call("browser", "ankiwebSetDetail", [""])

    def _nids(col, cids):
        out = []
        for c in cids:
            try:
                nid = col.get_card(c).nid
            except Exception:
                continue
            if nid not in out:
                out.append(nid)
        return out

    async def handler(arg: str):
        cmd, _, rest = arg.partition(":")
        if cmd == "search":
            await _do_search(rest)
        elif cmd == "searchdeck":
            name = await service.run(lambda col: col.decks.name(int(rest)))
            await _do_search(f'deck:"{name}"')
        elif cmd == "searchtag":
            await _do_search(f'tag:"{rest}"')
        elif cmd == "refresh":
            await _do_search(hub.ui_state.last_browse_query or "")
        elif cmd in ("select", "open"):
            cids = [int(c) for c in rest.split(",") if c] if cmd == "select" else [int(rest)]

            def _resolve(col):
                ns = _nids(col, cids)
                is_io = bool(
                    len(cids) == 1 and ns
                    and col.models.get(col.get_note(ns[0]).mid).get("originalStockKind") == 6)
                return ns, is_io

            nids, is_io = await service.run(_resolve)
            hub.ui_state.selected_card_ids = cids
            hub.ui_state.selected_note_ids = nids
            if len(cids) == 1 and nids and not is_io:
                # reuse the mounted editor iframe (postMessage the nid) — no iframe rebuild
                await hub.push_call("browser", "ankiwebEditNote", [nids[0]])
            elif len(cids) == 1 and nids:  # image-occlusion note: a different SPA page
                detail = _io_detail_html(nids[0])
                await hub.push_call("browser", "ankiwebSetDetail", [detail])
            else:
                await hub.push_call("browser", "ankiwebSetDetail", [""])
        elif cmd in ("suspend", "unsuspend", "forget", "delete"):
            cids = list(hub.ui_state.selected_card_ids or [])
            if cids:
                if cmd == "suspend":
                    await service.run_op(lambda col: col.sched.suspend_cards(cids),
                                         initiator="browser")
                elif cmd == "unsuspend":
                    await service.run_op(lambda col: col.sched.unsuspend_cards(cids),
                                         initiator="browser")
                elif cmd == "forget":
                    await service.run_op(lambda col: col.sched.schedule_cards_as_new(cids),
                                         initiator="browser")
                else:
                    await service.run_op(lambda col: col.remove_notes(_nids(col, cids)),
                                         initiator="browser")
                hub.ui_state.selected_card_ids = []
                hub.ui_state.selected_note_ids = []
                await _reload()
        elif cmd == "setdue":
            cids = list(hub.ui_state.selected_card_ids or [])
            if cids and rest:
                await service.run_op(lambda col: col.sched.set_due_date(cids, rest),
                                     initiator="browser")
                await _reload()
        elif cmd == "changedeck":
            cids = list(hub.ui_state.selected_card_ids or [])
            if cids and rest:
                await service.run_op(lambda col: col.set_deck(cids, col.decks.id(rest)),
                                     initiator="browser")
                await _reload()
        elif cmd == "changenotetype":
            cids = list(hub.ui_state.selected_card_ids or [])
            nids = list(hub.ui_state.selected_note_ids or [])
            if not nids and cids:
                nids = await service.run(lambda col: _nids(col, cids))
            if nids:
                try:
                    old = await service.run(
                        lambda col: col.models.get_single_notetype_of_notes(nids))
                except Exception:
                    return None
                await hub.push_call("browser", "ankiwebNavigate",
                                    ["/change-notetype/" + str(old)])
        elif cmd in ("addtag", "removetag"):
            cids = list(hub.ui_state.selected_card_ids or [])
            if cids and rest:
                def tag(col):
                    nids = _nids(col, cids)
                    if cmd == "addtag":
                        return col.tags.bulk_add(nids, rest)
                    return col.tags.bulk_remove(nids, rest)
                await service.run_op(tag, initiator="browser")
                await _reload()
        return None

    return handler
