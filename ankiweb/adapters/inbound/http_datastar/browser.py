from __future__ import annotations
import html
import datetime
import re
import time
from typing import Callable
from fastapi import APIRouter
from datastar_py.fastapi import (
    DatastarResponse,
    ServerSentEventGenerator as SSE,
    ReadSignals,
)
from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.core.i18n import tr

_TAG_STRIP = re.compile(r"<[^>]+>")
_LIMIT = 500


def _format_due(card, col) -> str:
    if card.queue == -1:
        return tr.browsing_suspended()
    elif card.queue in (-2, -3):
        return tr.browsing_buried()
    elif card.queue == 0:
        return f"{tr.actions_new()} #{card.due}"
    elif card.queue == 1:
        try:
            dt = datetime.datetime.fromtimestamp(card.due)
            if dt.date() == datetime.date.today():
                return dt.strftime("%H:%M")
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(card.due)
    elif card.queue in (2, 3):
        try:
            days_diff = card.due - col.sched.today
            due_date = datetime.date.today() + datetime.timedelta(days=days_diff)
            return due_date.isoformat()
        except Exception:
            return str(card.due)
    return ""


def _card_count_str(count: int) -> str:
    """Localized '<n> cards' with Fluent's bidi isolates and nbsp normalised for plain text."""
    raw = tr.card_templates_card_count(count=count)
    return re.sub(r"[\u2068\u2069]", "", raw).replace("\xa0", " ")


def _status_html(count: int) -> str:
    """``#browser-status`` element (same markup/classes as browser.html.jinja) for a morph patch."""
    return (
        '<span id="browser-status" class="text-base-content/60">'
        f"{html.escape(_card_count_str(count))}</span>"
    )


def render_browser_html(col, query: str = "") -> str:
    decks = [{"id": d.id, "name": d.name} for d in col.decks.all_names_and_ids()]
    tags = list(col.tags.all())
    try:
        cids = list(col.find_cards(query or ""))
    except Exception:
        cids = []
    initial_rows = _rows_html(_row_data(col, cids[:_LIMIT]))
    return templating.render(
        "browser.html.jinja",
        decks=decks,
        tags=tags,
        query=query,
        initial_rows=initial_rows,
        initial_count=len(cids),
        count_label=_card_count_str(len(cids)),
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
        sort = (
            note.fields[sf]
            if sf < len(note.fields)
            else (note.fields[0] if note.fields else "")
        )
        try:
            template_name = card.template().get("name", "")
        except Exception:
            template_name = ""
        note_type_name = model.get("name", "")
        deck_name = col.decks.name(card.did)
        tags_str = " ".join(note.tags)
        due_str = _format_due(card, col)
        is_suspended = (card.queue == -1)
        rows.append({
            "cid": cid,
            "sort_text": _TAG_STRIP.sub("", sort)[:200],
            "template_name": template_name,
            "note_type_name": note_type_name,
            "deck": deck_name,
            "tags": tags_str,
            "due": due_str,
            "is_suspended": is_suspended,
        })
    return rows


def _rows_html(rows) -> str:
    return templating.render("browser_rows.html.jinja", rows=rows)


def _detail_html(col, cid) -> str:
    card = col.get_card(cid)
    note = card.note()
    model = note.note_type()
    fields = [
        {"name": f["name"], "value": note.fields[i]}
        for i, f in enumerate(model["flds"])
    ]
    tags = " ".join(note.tags)
    return templating.render(
        "browser_detail.html.jinja",
        deck_name=col.decks.name(card.did),
        tags=tags,
        fields=fields,
    )


def _io_detail_html(nid) -> str:
    return templating.render("browser_io_detail.html.jinja", nid=nid)


def make_browser_routes(get_service: Callable, get_hub: Callable) -> APIRouter:
    router = APIRouter(prefix="/browse")

    async def _search_events(query: str):
        service = get_service()
        hub = get_hub()

        def run(col):
            try:
                cids = list(col.find_cards(query or ""))
            except Exception:
                return None, ""
            return cids, _rows_html(_row_data(col, cids[:_LIMIT]))

        cids, rows_html = await service.run(run)
        if cids is None:
            err_body = '<tbody id="results-body"><tr><td colspan="5">invalid search</td></tr></tbody>'
            status_html = _status_html(0)
            return [
                SSE.patch_elements(err_body, selector="#results-body"),
                SSE.patch_elements(status_html, selector="#browser-status"),
                SSE.execute_script("window.__ankiwebResetSel && window.__ankiwebResetSel();"),
            ]
        if hub:
            hub.ui_state.browser_open = True
            hub.ui_state.last_browse_query = query
            hub.ui_state.matched_card_ids = cids
        body_html = f'<tbody id="results-body">{rows_html}</tbody>'
        status_html = _status_html(len(cids))
        return [
            SSE.patch_elements(body_html, selector="#results-body"),
            SSE.patch_elements(status_html, selector="#browser-status"),
            SSE.execute_script("window.__ankiwebResetSel && window.__ankiwebResetSel();"),
        ]

    async def _do_search(query: str):
        events = await _search_events(query)
        return DatastarResponse(events)

    async def _reload():
        hub = get_hub()
        last_q = hub.ui_state.last_browse_query if hub else ""
        events = await _search_events(last_q or "")
        empty_detail = '<div id="detail"></div>'
        all_events = [*events, SSE.patch_elements(empty_detail, selector="#detail")]
        return DatastarResponse(all_events)

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

    @router.post("/search")
    async def search(payload: ReadSignals):
        q = ""
        if payload and isinstance(payload, dict):
            q = str(payload.get("query", ""))
        return await _do_search(q)

    @router.post("/searchdeck/{did}")
    async def search_deck(did: int):
        service = get_service()
        name = await service.run(lambda col: col.decks.name(did))
        return await _do_search(f'deck:"{name}"')

    @router.post("/searchtag")
    async def search_tag(payload: ReadSignals):
        tag = ""
        if payload and isinstance(payload, dict):
            tag = str(payload.get("tag", ""))
        return await _do_search(f'tag:"{tag}"')

    @router.post("/refresh")
    async def refresh():
        return await _reload()

    @router.post("/select")
    async def select_cards(payload: ReadSignals):
        cids = []
        if payload and isinstance(payload, dict):
            cids = [int(c) for c in payload.get("cids", []) if c is not None]
        return await _handle_selection(cids)

    @router.post("/open/{cid}")
    async def open_card(cid: int):
        return await _handle_selection([cid])

    async def _handle_selection(cids: list[int]):
        service = get_service()
        hub = get_hub()

        def _resolve(col):
            ns = _nids(col, cids)
            is_io = bool(
                len(cids) == 1
                and ns
                and col.models.get(col.get_note(ns[0]).mid).get("originalStockKind")
                == 6
            )
            return ns, is_io

        nids, is_io = await service.run(_resolve)
        if hub:
            hub.ui_state.selected_card_ids = cids
            hub.ui_state.selected_note_ids = nids

        if len(cids) == 1 and nids and not is_io:
            nid = nids[0]
            edit_script = f"""(function() {{
                var d = document.getElementById('detail');
                var f = document.getElementById('editor-frame');
                if (f && f.contentWindow) {{
                    f.contentWindow.postMessage({{
                        type: 'ankiwebLoadNid',
                        nid: {nid}
                    }}, '*');
                }} else {{
                    d.innerHTML = "<iframe id='editor-frame' class='editor-frame' src='/edit?nid={nid}'></iframe>";
                }}
            }})();"""
            return DatastarResponse(SSE.execute_script(edit_script))
        elif len(cids) == 1 and nids:
            detail = f'<div id="detail">{_io_detail_html(nids[0])}</div>'
            return DatastarResponse(SSE.patch_elements(detail, selector="#detail"))
        else:
            empty_detail = '<div id="detail"></div>'
            return DatastarResponse(
                SSE.patch_elements(empty_detail, selector="#detail")
            )

    @router.post("/suspend")
    async def suspend():
        service = get_service()
        hub = get_hub()
        cids = list(hub.ui_state.selected_card_ids or []) if hub else []
        if not cids:
            return DatastarResponse()
        await service.run_op(
            lambda col: col.sched.suspend_cards(cids), initiator="browser"
        )
        if hub:
            hub.ui_state.selected_card_ids = []
            hub.ui_state.selected_note_ids = []
        return await _reload()

    @router.post("/unsuspend")
    async def unsuspend():
        service = get_service()
        hub = get_hub()
        cids = list(hub.ui_state.selected_card_ids or []) if hub else []
        if not cids:
            return DatastarResponse()
        await service.run_op(
            lambda col: col.sched.unsuspend_cards(cids), initiator="browser"
        )
        if hub:
            hub.ui_state.selected_card_ids = []
            hub.ui_state.selected_note_ids = []
        return await _reload()

    @router.post("/forget")
    async def forget():
        service = get_service()
        hub = get_hub()
        cids = list(hub.ui_state.selected_card_ids or []) if hub else []
        if not cids:
            return DatastarResponse()
        await service.run_op(
            lambda col: col.sched.schedule_cards_as_new(cids), initiator="browser"
        )
        if hub:
            hub.ui_state.selected_card_ids = []
            hub.ui_state.selected_note_ids = []
        return await _reload()

    @router.post("/delete")
    async def delete_notes():
        service = get_service()
        hub = get_hub()
        cids = list(hub.ui_state.selected_card_ids or []) if hub else []
        if not cids:
            return DatastarResponse()
        await service.run_op(
            lambda col: col.remove_notes(_nids(col, cids)), initiator="browser"
        )
        if hub:
            hub.ui_state.selected_card_ids = []
            hub.ui_state.selected_note_ids = []
        return await _reload()

    @router.post("/setdue")
    async def set_due(payload: ReadSignals):
        service = get_service()
        hub = get_hub()
        cids = list(hub.ui_state.selected_card_ids or []) if hub else []
        val = ""
        if payload and isinstance(payload, dict):
            val = str(payload.get("value", "")).strip()
        if not (cids and val):
            return DatastarResponse()
        await service.run_op(
            lambda col: col.sched.set_due_date(cids, val), initiator="browser"
        )
        return await _reload()

    @router.post("/changedeck")
    async def change_deck(payload: ReadSignals):
        service = get_service()
        hub = get_hub()
        cids = list(hub.ui_state.selected_card_ids or []) if hub else []
        deck = ""
        if payload and isinstance(payload, dict):
            deck = str(payload.get("deck", "")).strip()
        if not (cids and deck):
            return DatastarResponse()
        await service.run_op(
            lambda col: col.set_deck(cids, col.decks.id(deck)), initiator="browser"
        )
        return await _reload()

    @router.post("/changenotetype")
    async def change_notetype():
        service = get_service()
        hub = get_hub()
        cids = list(hub.ui_state.selected_card_ids or []) if hub else []
        nids = list(hub.ui_state.selected_note_ids or []) if hub else []
        if not nids and cids:
            nids = await service.run(lambda col: _nids(col, cids))
        if nids:
            try:
                old = await service.run(
                    lambda col: col.models.get_single_notetype_of_notes(nids)
                )
            except Exception:
                return DatastarResponse()
            return DatastarResponse(SSE.redirect(f"/change-notetype/{old}"))
        return DatastarResponse()

    @router.post("/addtag")
    async def add_tag(payload: ReadSignals):
        service = get_service()
        hub = get_hub()
        cids = list(hub.ui_state.selected_card_ids or []) if hub else []
        tag = ""
        if payload and isinstance(payload, dict):
            tag = str(payload.get("tag", "")).strip()
        if not (cids and tag):
            return DatastarResponse()

        def do_tag(col):
            nids = _nids(col, cids)
            return col.tags.bulk_add(nids, tag)

        await service.run_op(do_tag, initiator="browser")
        return await _reload()

    @router.post("/removetag")
    async def remove_tag(payload: ReadSignals):
        service = get_service()
        hub = get_hub()
        cids = list(hub.ui_state.selected_card_ids or []) if hub else []
        tag = ""
        if payload and isinstance(payload, dict):
            tag = str(payload.get("tag", "")).strip()
        if not (cids and tag):
            return DatastarResponse()

        def do_untag(col):
            nids = _nids(col, cids)
            return col.tags.bulk_remove(nids, tag)

        await service.run_op(do_untag, initiator="browser")
        return await _reload()

    return router
