from __future__ import annotations

import datetime
import html
import json
import logging
import re
from collections.abc import Callable

from anki.errors import InvalidInput, NotFoundError, SearchError, TemplateError
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
            dt = datetime.datetime.fromtimestamp(card.due, tz=datetime.UTC).astimezone()
            if dt.date() == datetime.datetime.now(datetime.UTC).astimezone().date():
                return dt.strftime("%H:%M")
            return dt.strftime("%Y-%m-%d %H:%M")
        except (OSError, OverflowError, TypeError, ValueError):
            return str(card.due)
    elif card.queue in (2, 3):
        try:
            days_diff = card.due - col.sched.today
            due_date = (
                datetime.datetime.now(datetime.UTC).astimezone().date()
                + datetime.timedelta(days=days_diff)
            )
            return due_date.isoformat()
        except (OverflowError, TypeError, ValueError):
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
    except (SearchError, InvalidInput):
        cids = []
    visible_cids = cids[:_LIMIT]
    initial_rows = _rows_html(_row_data(col, visible_cids))
    return templating.render(
        "browser.html.jinja",
        decks=decks,
        tags=tags,
        query=query,
        initial_rows=initial_rows,
        initial_count=len(cids),
        count_label=_card_count_str(len(cids)),
        initial_cids=visible_cids,
    )


def _row_data(col, cids):
    rows = []
    for cid in cids:
        try:
            card = col.get_card(cid)
        except NotFoundError:
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
        except (IndexError, TemplateError):
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

def _detail_shell_html(content: str = "") -> str:
    return f'<div id="detail" data-attr:data-selected-cids="$selectedCids.join(\',\')">{content}</div>'


def _io_detail_html(nid) -> str:
    return templating.render("browser_io_detail.html.jinja", nid=nid)

def make_browser_routes(get_service: Callable, get_hub: Callable) -> APIRouter:
    router = APIRouter(prefix="/browse")
    def _reset_signals(
        *,
        query: str,
        browser_query: str,
        visible_cids: list[int],
        matched_count: int,
    ) -> str:
        return json.dumps({
            "selectedCids": [],
            "_selectionAnchor": None,
            "_browserAction": "",
            "_visibleCids": visible_cids,
            "_matchedCount": matched_count,
            "query": query,
            "browserQuery": browser_query,
            "value": "",
            "deck": "",
            "tag": "",
            "error": "",
        })
    async def _search_events(
        query: str,
        *,
        applied_query: str | None = None,
        reset_selection: bool = True,
    ):
        service = get_service()
        hub = get_hub()

        def run(col):
            try:
                cids = list(col.find_cards(query or ""))
            except (SearchError, InvalidInput):
                return None, ""
            return cids, _rows_html(_row_data(col, cids[:_LIMIT]))

        cids, rows_html = await service.run(run)
        if cids is None:
            if hub:
                hub.ui_state.browser_open = True
                hub.ui_state.last_browse_query = ""
                hub.ui_state.matched_card_ids = []
                if reset_selection:
                    hub.ui_state.selected_card_ids = []
                    hub.ui_state.selected_note_ids = []
            err_body = '<tbody id="results-body"><tr><td colspan="5">invalid search</td></tr></tbody>'
            status_html = _status_html(0)
            events = [
                SSE.patch_elements(err_body, selector="#results-body"),
                SSE.patch_elements(status_html, selector="#browser-status"),
            ]
            if reset_selection:
                empty_detail = _detail_shell_html()
                events.extend([
                    SSE.patch_elements(empty_detail, selector="#detail"),
                    SSE.patch_signals(
                        _reset_signals(
                            query=query,
                            browser_query="",
                            visible_cids=[],
                            matched_count=0,
                        )
                    ),
                ])
            else:
                events.append(
                    SSE.patch_signals(
                        json.dumps({
                            "_visibleCids": [],
                            "_matchedCount": 0,
                        })
                    )
                )
            return events
        if hub:
            hub.ui_state.browser_open = True
            hub.ui_state.last_browse_query = query
            hub.ui_state.matched_card_ids = cids
            if reset_selection:
                hub.ui_state.selected_card_ids = []
                hub.ui_state.selected_note_ids = []
        body_html = f'<tbody id="results-body">{rows_html}</tbody>'
        status_html = _status_html(len(cids))
        actual_applied_query = query if applied_query is None else applied_query
        visible_cids = cids[:_LIMIT]
        events = [
            SSE.patch_elements(body_html, selector="#results-body"),
            SSE.patch_elements(status_html, selector="#browser-status"),
        ]
        if reset_selection:
            empty_detail = _detail_shell_html()
            events.extend([
                SSE.patch_elements(empty_detail, selector="#detail"),
                SSE.patch_signals(
                    _reset_signals(
                        query=actual_applied_query,
                        browser_query=actual_applied_query,
                        visible_cids=visible_cids,
                        matched_count=len(cids),
                    )
                ),
            ])
        else:
            events.append(
                SSE.patch_signals(
                    json.dumps({
                        "_visibleCids": visible_cids,
                        "_matchedCount": len(cids),
                    })
                )
            )
        return events

    async def _do_search(query: str):
        events = await _search_events(query)
        return DatastarResponse(events)

    async def _reload(applied_query: str = "", *, reset_selection: bool = True):
        events = await _search_events(
            applied_query,
            applied_query=applied_query,
            reset_selection=reset_selection,
        )
        return DatastarResponse(events)
    def _nids(col, cids):
        out = []
        for c in cids:
            try:
                nid = col.get_card(c).nid
            except NotFoundError:
                continue
            if nid not in out:
                out.append(nid)
        return out

    def _get_requested_cids(payload: ReadSignals | None) -> list[int]:
        if not payload or not isinstance(payload, dict):
            return []
        raw = payload.get("selectedCids")
        if not isinstance(raw, list):
            return []
        out: list[int] = []
        for item in raw:
            try:
                out.append(int(item))
            except (TypeError, ValueError):
                continue
        return out

    def _get_browser_query(payload: ReadSignals | None) -> str:
        if not payload or not isinstance(payload, dict):
            return ""
        raw = payload.get("browserQuery")
        if raw is None:
            return ""
        return str(raw)


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
    async def refresh(payload: ReadSignals = None):
        applied_q = _get_browser_query(payload)
        return await _reload(applied_q, reset_selection=False)
    @router.post("/select")
    async def select_cards(payload: ReadSignals):
        cids = _get_requested_cids(payload)
        return await _handle_selection(cids, echo_selection=False)

    @router.post("/open/{cid}")
    async def open_card(cid: int):
        return await _handle_selection([cid], echo_selection=True)

    async def _handle_selection(cids: list[int], *, echo_selection: bool = False):
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

        events = []
        if echo_selection:
            events.append(
                SSE.patch_signals(
                    json.dumps({
                        "selectedCids": cids,
                        "_selectionAnchor": cids[0] if cids else None,
                    })
                )
            )

        guard_cond = ""
        if not echo_selection:
            sorted_cids_json = json.dumps(sorted(cids))
            guard_cond = f"""
                var rows = document.querySelectorAll('#results-body tr.browser-row.selected[data-cid]');
                var cur = Array.prototype.map.call(rows, function(r) {{ return +r.dataset.cid; }}).sort(function(a, b) {{ return a - b; }});
                var expected = {sorted_cids_json};
                if (cur.length !== expected.length) return;
                for (var i = 0; i < cur.length; i++) {{
                    if (cur[i] !== expected[i]) return;
                }}
            """

        cids_joined = ",".join(str(c) for c in cids)
        detail_selector = (
            "#detail"
            if echo_selection
            else f'#detail[data-selected-cids="{cids_joined}"]'
        )

        if len(cids) == 1 and nids and not is_io:
            nid = nids[0]
            edit_script = f"""(function() {{{guard_cond}
                var d = document.getElementById('detail');
                if (!d) return;
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
            events.append(SSE.execute_script(edit_script))
            return DatastarResponse(events)
        elif len(cids) == 1 and nids:
            io_detail = _detail_shell_html(_io_detail_html(nids[0]))
            events.append(SSE.patch_elements(io_detail, selector=detail_selector))
            return DatastarResponse(events)
        else:
            empty_detail = _detail_shell_html()
            events.append(SSE.patch_elements(empty_detail, selector=detail_selector))
            return DatastarResponse(events)

    @router.post("/suspend")
    async def suspend(payload: ReadSignals = None):
        service = get_service()
        cids = _get_requested_cids(payload)
        if not cids:
            return DatastarResponse()
        await service.run_op(
            lambda col: col.sched.suspend_cards(cids), initiator="browser"
        )
        applied_q = _get_browser_query(payload)
        return await _reload(applied_q)

    @router.post("/unsuspend")
    async def unsuspend(payload: ReadSignals = None):
        service = get_service()
        cids = _get_requested_cids(payload)
        if not cids:
            return DatastarResponse()
        await service.run_op(
            lambda col: col.sched.unsuspend_cards(cids), initiator="browser"
        )
        applied_q = _get_browser_query(payload)
        return await _reload(applied_q)

    @router.post("/forget")
    async def forget(payload: ReadSignals = None):
        service = get_service()
        cids = _get_requested_cids(payload)
        if not cids:
            return DatastarResponse()
        await service.run_op(
            lambda col: col.sched.schedule_cards_as_new(cids), initiator="browser"
        )
        applied_q = _get_browser_query(payload)
        return await _reload(applied_q)

    @router.post("/delete")
    async def delete_notes(payload: ReadSignals = None):
        service = get_service()
        cids = _get_requested_cids(payload)
        if not cids:
            return DatastarResponse()
        await service.run_op(
            lambda col: col.remove_notes(_nids(col, cids)), initiator="browser"
        )
        applied_q = _get_browser_query(payload)
        return await _reload(applied_q)

    @router.post("/setdue")
    async def set_due(payload: ReadSignals):
        service = get_service()
        cids = _get_requested_cids(payload)
        val = ""
        if payload and isinstance(payload, dict):
            val = str(payload.get("value", "")).strip()
        if not (cids and val):
            return DatastarResponse()
        try:
            await service.run_op(
                lambda col: col.sched.set_due_date(cids, val), initiator="browser"
            )
        except (InvalidInput, NotFoundError) as exc:
            return error_response(exc)
        applied_q = _get_browser_query(payload)
        return await _reload(applied_q)

    @router.post("/changedeck")
    async def change_deck(payload: ReadSignals):
        service = get_service()
        cids = _get_requested_cids(payload)
        deck = ""
        if payload and isinstance(payload, dict):
            deck = str(payload.get("deck", "")).strip()
        if not (cids and deck):
            return DatastarResponse()
        try:
            await service.run_op(
                lambda col: col.set_deck(cids, col.decks.id(deck)), initiator="browser"
            )
        except (InvalidInput, NotFoundError) as exc:
            return error_response(exc)
        applied_q = _get_browser_query(payload)
        return await _reload(applied_q)

    @router.post("/changenotetype")
    async def change_notetype(payload: ReadSignals = None):
        service = get_service()
        hub = get_hub()
        cids = _get_requested_cids(payload)
        if not cids:
            return DatastarResponse()
        nids = await service.run(lambda col: _nids(col, cids))
        if not nids:
            return DatastarResponse()
        if hub:
            hub.ui_state.selected_card_ids = cids
            hub.ui_state.selected_note_ids = nids
        try:
            old = await service.run(
                lambda col: col.models.get_single_notetype_of_notes(nids)
            )
        except (InvalidInput, NotFoundError) as exc:
            return error_response(exc)
        return DatastarResponse(SSE.redirect(f"/change-notetype/{old}"))

    @router.post("/addtag")
    async def add_tag(payload: ReadSignals):
        service = get_service()
        cids = _get_requested_cids(payload)
        tag = ""
        if payload and isinstance(payload, dict):
            tag = str(payload.get("tag", "")).strip()
        if not (cids and tag):
            return DatastarResponse()

        def do_tag(col):
            nids = _nids(col, cids)
            return col.tags.bulk_add(nids, tag)

        try:
            await service.run_op(do_tag, initiator="browser")
        except (InvalidInput, NotFoundError) as exc:
            return error_response(exc)
        applied_q = _get_browser_query(payload)
        return await _reload(applied_q)

    @router.post("/removetag")
    async def remove_tag(payload: ReadSignals):
        service = get_service()
        cids = _get_requested_cids(payload)
        tag = ""
        if payload and isinstance(payload, dict):
            tag = str(payload.get("tag", "")).strip()
        if not (cids and tag):
            return DatastarResponse()

        def do_untag(col):
            nids = _nids(col, cids)
            return col.tags.bulk_remove(nids, tag)

        try:
            await service.run_op(do_untag, initiator="browser")
        except (InvalidInput, NotFoundError) as exc:
            return error_response(exc)
        applied_q = _get_browser_query(payload)
        return await _reload(applied_q)
    return router
