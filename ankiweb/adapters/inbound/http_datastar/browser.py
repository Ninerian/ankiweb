from __future__ import annotations

import datetime
import html
import json
import logging
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from json import JSONDecodeError
from typing import TYPE_CHECKING, Any

from anki.cards import Card, CardId
from anki.collection import Collection, SearchNode
from anki.errors import InvalidInput, NotFoundError, SearchError, TemplateError
from anki.notes import NoteId
from datastar_py.fastapi import (
    DatastarResponse,
)
from datastar_py.fastapi import (
    ServerSentEventGenerator as SSE,
)
from fastapi import APIRouter, Request
from starlette.datastructures import FormData, QueryParams, UploadFile

from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.core.i18n import tr

if TYPE_CHECKING:
    from ankiweb.adapters.outbound.anki_collection_adapter import CollectionService
    from ankiweb.core.bridge.hub import BridgeHub

logger = logging.getLogger(__name__)

_TAG_STRIP = re.compile(r"<[^>]+>")
_LIMIT = 500
_MAX_I64 = 2**63 - 1


def _parse_positive_int64(raw: object) -> int | None:
    """Parse positive 64-bit integer, strictly rejecting booleans, floats, and overflow."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        val = raw
    elif isinstance(raw, str):
        s = raw.strip()
        if not s.isdigit():
            return None
        try:
            val = int(s)
        except ValueError:
            return None
    else:
        return None

    if 1 <= val <= _MAX_I64:
        return val
    return None


def _format_due(card: Card, col: Collection) -> str:
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
            due_date = datetime.datetime.now(
                datetime.UTC
            ).astimezone().date() + datetime.timedelta(days=days_diff)
            return due_date.isoformat()
        except (OverflowError, TypeError, ValueError):
            return str(card.due)
    return ""


def _card_count_str(count: int) -> str:
    """Localized '<n> cards' with Fluent's bidi isolates and nbsp normalised for plain text."""
    raw = tr.card_templates_card_count(count=count)
    return re.sub(r"[\u2068\u2069]", "", raw).replace("\xa0", " ")


def _selection_label_str(selected_count: int, total_count: int) -> str:
    """Localized '<selected> of <total> cards selected' formatted from fluent window title."""
    raw = tr.browsing_window_title(total=987654, selected=123456)
    clean = raw.replace("\u2068", "").replace("\u2069", "")
    if "(" in clean and ")" in clean:
        pattern = clean.split("(")[1].split(")")[0]
    else:
        pattern = clean
    return pattern.replace("123456", str(selected_count)).replace(
        "987654", str(total_count)
    )


def _status_html(count: int) -> str:
    """``#browser-status`` element for morph patch."""
    return (
        '<span id="browser-status" class="text-base-content/60">'
        f"{html.escape(_card_count_str(count))}</span>"
    )


def _card_template_name(card: Card) -> str | int | None:
    try:
        template = card.template()
        return template.get("name", "") if template is not None else ""
    except (IndexError, TemplateError):
        return ""


def _sort_field(fields: list[str], index: int) -> str:
    return fields[index] if index < len(fields) else (fields[0] if fields else "")


def _row_data(
    col: Collection,
    cids: Sequence[CardId | int],
    selected_cids_set: AbstractSet[CardId | int] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sel_set = selected_cids_set or set()
    for cid in cids:
        try:
            card = col.get_card(CardId(int(cid)))
        except NotFoundError:
            continue
        note = card.note()
        model = note.note_type()
        sf = model.get("sortf", 0) if model is not None else 0
        sort = _sort_field(note.fields, sf)
        template_name = _card_template_name(card)
        note_type_name = model.get("name", "") if model is not None else ""
        deck_name = col.decks.name(card.did)
        tags_str = " ".join(note.tags)
        due_str = _format_due(card, col)
        is_suspended = card.queue == -1
        rows.append(
            {
                "cid": int(cid),
                "sort_text": _TAG_STRIP.sub("", sort)[:200],
                "template_name": template_name,
                "note_type_name": note_type_name,
                "deck": deck_name,
                "tags": tags_str,
                "due": due_str,
                "is_suspended": is_suspended,
                "selected": cid in sel_set,
            }
        )
    return rows


def _nids(col: Collection, cids: Sequence[CardId | int]) -> list[NoteId]:
    out: list[NoteId] = []
    for c in cids:
        try:
            nid = col.get_card(CardId(int(c))).nid
        except NotFoundError:
            continue
        if nid not in out:
            out.append(nid)
    return out


def _resolve_detail_nid(
    col: Collection, cids: Sequence[CardId | int]
) -> tuple[int | None, bool]:
    if len(cids) != 1:
        return None, False
    ns = _nids(col, cids)
    if not ns:
        return None, False
    nid = ns[0]
    try:
        note = col.get_note(nid)
        model = col.models.get(note.mid)
        is_io = bool(model is not None and model.get("originalStockKind") == 6)
    except NotFoundError:
        return None, False
    return int(nid), is_io


def _validate_cids(col: Collection, cids: Sequence[CardId | int]) -> list[CardId]:
    valid: list[CardId] = []
    seen: set[CardId] = set()
    for cid in cids:
        parsed_id = _parse_positive_int64(cid)
        if parsed_id is None:
            continue
        typed_cid = CardId(parsed_id)
        if typed_cid in seen:
            continue
        try:
            col.get_card(typed_cid)
            seen.add(typed_cid)
            valid.append(typed_cid)
        except NotFoundError:
            continue
    return valid


def _resolve_deck_id(col: Collection, name: str) -> int:
    """Resolve or create a deck without fabricating a destination on failure."""
    deck_id = col.decks.id(name)
    if deck_id is None:
        raise InvalidInput(f"Unable to resolve deck: {name}", None, None, None)
    return int(deck_id)


def _matched_cards(
    col: Collection,
    query: str,
    matched_cids: Sequence[CardId | int] | None,
    search_error: bool,
) -> tuple[list[CardId], bool]:
    if matched_cids is not None:
        return [CardId(int(c)) for c in matched_cids], search_error
    try:
        return list(col.find_cards(query or "")), search_error
    except (SearchError, InvalidInput):
        return [], True


def _selection_anchor(
    col: Collection,
    selection_anchor: CardId | int | None,
    selected_cids: Sequence[CardId],
) -> CardId | None:
    fallback = selected_cids[0] if selected_cids else None
    if selection_anchor is None:
        return fallback
    parsed = _parse_positive_int64(selection_anchor)
    if parsed is None:
        return fallback
    candidate = CardId(parsed)
    try:
        col.get_card(candidate)
    except NotFoundError:
        return fallback
    return candidate


def _all_visible_selected(
    visible_cids: Sequence[CardId],
    selected_cids: Sequence[CardId],
    selected_set: AbstractSet[CardId],
) -> bool:
    return bool(
        visible_cids
        and len(selected_cids) >= len(visible_cids)
        and all(c in selected_set for c in visible_cids)
    )


def build_browser_context(
    col: Collection,
    query: str = "",
    *,
    selected_cids: Sequence[CardId | int] | None = None,
    selection_anchor: CardId | int | None = None,
    matched_cids: Sequence[CardId | int] | None = None,
    decks: list[dict[str, str]] | None = None,
    tags: list[dict[str, str]] | None = None,
    open_detail: bool = False,
    dialog: str = "",
    error: str = "",
    value: str = "",
    search_error: bool = False,
) -> dict[str, Any]:
    """Build validated, request-local state shared by all browser components.

    Submitted selection is never inferred from the shared BridgeHub mirror.
    Existing cards remain selected even when they no longer match the filter.
    """
    if decks is None:
        decks = [
            {
                "name": d.name,
                "query": col.build_search_string(SearchNode(deck=d.name)),
            }
            for d in col.decks.all_names_and_ids()
        ]
    if tags is None:
        tags = [
            {
                "name": name,
                "query": col.build_search_string(SearchNode(tag=name)),
            }
            for name in col.tags.all()
        ]

    resolved_matched_cids, has_search_error = _matched_cards(
        col, query, matched_cids, search_error
    )

    visible_cids = resolved_matched_cids[:_LIMIT]
    raw_sel = selected_cids or []

    # Deduplicate & validate selected CIDs against the collection
    valid_selected_cids = _validate_cids(col, raw_sel)
    seen_cids = set(valid_selected_cids)

    # Preserve valid existing anchor even if currently unselected
    anchor = _selection_anchor(col, selection_anchor, valid_selected_cids)

    rows = _row_data(col, visible_cids, seen_cids)
    count = len(resolved_matched_cids)
    count_label = _card_count_str(count)
    sel_label = _selection_label_str(len(valid_selected_cids), count)
    all_sel = _all_visible_selected(visible_cids, valid_selected_cids, seen_cids)
    part_sel = bool(valid_selected_cids and not all_sel)

    detail_nid, detail_is_io = _resolve_detail_nid(col, valid_selected_cids)

    return {
        "decks": decks,
        "tags": tags,
        "query": query,
        "rows": rows,
        "count": count,
        "count_label": count_label,
        "selected_cids": [int(c) for c in valid_selected_cids],
        "selection_anchor": int(anchor) if anchor is not None else None,
        "selection_label": sel_label,
        "all_selected": all_sel,
        "partial_selection": part_sel,
        "detail_nid": detail_nid,
        "detail_is_io": detail_is_io,
        "open_detail": open_detail,
        "dialog": dialog,
        "error": error,
        "value": value,
        "search_error": has_search_error,
        "matched_cids": [int(c) for c in resolved_matched_cids],
    }


def render_browser_page(col: Collection, query: str = "") -> tuple[str, list[int]]:
    """Render full browser HTML page and return (html, canonical_matched_cids)."""
    ctx = build_browser_context(col, query=query, selected_cids=[])
    matched_cids: list[int] = ctx["matched_cids"]
    rendered = templating.render("browser.html.jinja", **ctx)
    return rendered, matched_cids


@dataclass
class BrowserRequestData:
    """Tab-local form state and interaction intent, not a shared session cache."""

    browser_query: str = ""
    selected_cids: list[CardId] = field(default_factory=list)
    selection_anchor: CardId | None = None
    cid: CardId | None = None
    mode: str = ""
    open_detail: bool = False
    value: str = ""
    deck: str = ""
    tag: str = ""


def _request_query(data: Mapping[str, object], prefer_query_draft: bool) -> object:
    first, last = (
        ("query", "browserQuery") if prefer_query_draft else ("browserQuery", "query")
    )
    if first in data:
        return data[first]
    if "q" in data:
        return data["q"]
    return data.get(last)


def _append_selected(out: BrowserRequestData, values: Iterable[object]) -> None:
    for value in values:
        if isinstance(value, UploadFile):
            continue
        parsed = _parse_positive_int64(value)
        if parsed is not None:
            out.selected_cids.append(CardId(parsed))


def _apply_query_params(
    out: BrowserRequestData, qp: QueryParams, prefer_query_draft: bool
) -> None:
    query = _request_query(qp, prefer_query_draft)
    if query is not None:
        out.browser_query = str(query)
    if "cid" in qp:
        parsed_cid = _parse_positive_int64(qp["cid"])
        if parsed_cid is not None:
            out.cid = CardId(parsed_cid)
    if "mode" in qp:
        out.mode = qp["mode"]
    if "openDetail" in qp:
        out.open_detail = qp["openDetail"] not in ("0", "false", "False", "")
    if "selectionAnchor" in qp:
        parsed_anchor = _parse_positive_int64(qp["selectionAnchor"])
        if parsed_anchor is not None:
            out.selection_anchor = CardId(parsed_anchor)
    _append_selected(out, qp.getlist("selectedCids"))
    for name in ("value", "deck", "tag"):
        if name in qp:
            setattr(out, name, qp[name])


def _body_card_id(raw: object) -> CardId | None:
    if raw is None or isinstance(raw, UploadFile):
        return None
    parsed = _parse_positive_int64(raw)
    return CardId(parsed) if parsed is not None else None


def _apply_body_ids(out: BrowserRequestData, data: Mapping[str, object]) -> None:
    if "cid" in data and out.cid is None:
        out.cid = _body_card_id(data["cid"])
    if "selectionAnchor" in data and out.selection_anchor is None:
        out.selection_anchor = _body_card_id(data["selectionAnchor"])


def _apply_body_action(out: BrowserRequestData, data: Mapping[str, object]) -> None:
    mode = data.get("mode")
    if not out.mode and mode is not None and not isinstance(mode, UploadFile):
        out.mode = str(mode)
    if "openDetail" in data and not out.open_detail:
        detail = data["openDetail"]
        if not isinstance(detail, UploadFile):
            out.open_detail = str(detail) not in ("0", "false", "False", "")


def _apply_body_text(out: BrowserRequestData, data: Mapping[str, object]) -> None:
    for name in ("value", "deck", "tag"):
        value = data.get(name)
        if (
            not getattr(out, name)
            and value is not None
            and not isinstance(value, UploadFile)
        ):
            setattr(out, name, str(value))


def _apply_body(
    out: BrowserRequestData, data: Mapping[str, object], prefer_query_draft: bool
) -> None:
    query = _request_query(data, prefer_query_draft)
    if query is not None and not isinstance(query, UploadFile):
        out.browser_query = str(query)
    _apply_body_ids(out, data)
    _apply_body_action(out, data)
    _apply_body_text(out, data)


def _apply_form(
    out: BrowserRequestData, form: FormData, prefer_query_draft: bool
) -> None:
    _apply_body(out, form, prefer_query_draft)
    _append_selected(out, form.getlist("selectedCids"))


def _apply_json(
    out: BrowserRequestData, data: dict[str, Any], prefer_query_draft: bool
) -> None:
    _apply_body(out, data, prefer_query_draft)
    selected = data.get("selectedCids")
    if isinstance(selected, list):
        _append_selected(out, selected)


async def _parse_browser_request(
    request: Request, *, prefer_query_draft: bool = False
) -> BrowserRequestData:
    """Explicitly decode Request data from query params, forms, and JSON."""
    out = BrowserRequestData()
    _apply_query_params(out, request.query_params, prefer_query_draft)
    content_type = request.headers.get("content-type", "").lower()
    if (
        "application/x-www-form-urlencoded" in content_type
        or "multipart/form-data" in content_type
    ):
        _apply_form(out, await request.form(), prefer_query_draft)
    elif "application/json" in content_type:
        try:
            body_bytes = await request.body()
            if body_bytes:
                data = json.loads(body_bytes.decode("utf-8"))
                if isinstance(data, dict):
                    _apply_json(out, data, prefer_query_draft)
        except (JSONDecodeError, UnicodeDecodeError):
            logger.warning("Failed to decode JSON body in browser request")
    return out


def _range_selection(
    visible_cids: Sequence[CardId], anchor: CardId | None, target_cid: CardId
) -> tuple[list[CardId], CardId]:
    if anchor is not None and anchor in visible_cids and target_cid in visible_cids:
        idx_a = visible_cids.index(anchor)
        idx_b = visible_cids.index(target_cid)
        lo, hi = min(idx_a, idx_b), max(idx_a, idx_b)
        return list(visible_cids[lo : hi + 1]), anchor
    return [target_cid], target_cid


def _compute_new_selection(
    visible_cids: Sequence[CardId],
    current_selected: Sequence[CardId],
    anchor: CardId | None,
    target_cid: CardId | None,
    mode: str,
) -> tuple[list[CardId], CardId | None]:
    """Compute server-authoritative selection state without client list math."""
    if mode == "all":
        return list(visible_cids), (visible_cids[0] if visible_cids else None)
    elif mode == "none":
        return [], None

    if target_cid is None:
        return list(current_selected), anchor

    if mode == "single":
        return [target_cid], target_cid
    elif mode == "toggle":
        cur_set = set(current_selected)
        if target_cid in cur_set:
            new_list = [c for c in current_selected if c != target_cid]
            # Toggle always sets anchor to clicked CID, even when deselecting
            return new_list, target_cid
        else:
            return list(current_selected) + [target_cid], target_cid
    elif mode == "range":
        return _range_selection(visible_cids, anchor, target_cid)
    return [target_cid], target_cid


def _render_selection_patches(ctx: dict[str, Any]) -> list[Any]:
    """Render standard patches after a selection change."""
    state_html = templating.render("browser_state.html.jinja", **ctx)
    results_html = templating.render("browser_results.html.jinja", **ctx)
    actions_html = templating.render("browser_actions.html.jinja", **ctx)
    sel_row_html = templating.render("browser_selection.html.jinja", **ctx)
    detail_shell_html = templating.render("browser_detail_shell.html.jinja", **ctx)
    status_html = _status_html(ctx["count"])
    dialogs_html = templating.render("browser_dialogs.html.jinja", **ctx)
    events = [
        SSE.patch_elements(state_html, selector="#browser-state"),
        SSE.patch_elements(results_html, selector="#results"),
        SSE.patch_elements(actions_html, selector="#browser-actions"),
        SSE.patch_elements(sel_row_html, selector="#browser-selection-status-row"),
        SSE.patch_elements(detail_shell_html, selector="#detail"),
        SSE.patch_elements(status_html, selector="#browser-status"),
        SSE.patch_elements(dialogs_html, selector="#browser-dialogs"),
    ]
    if ctx.get("open_detail") and ctx.get("detail_nid"):
        events.append(SSE.execute_script("window.ankiwebOpenMobileDetail?.()"))
    return events


def _render_refresh_patches(
    ctx: dict[str, Any], *, selection_deleted: bool = False
) -> list[Any]:
    """Render background refresh patches."""
    state_html = templating.render("browser_state.html.jinja", **ctx)
    results_html = templating.render("browser_results.html.jinja", **ctx)
    actions_html = templating.render("browser_actions.html.jinja", **ctx)
    sel_row_html = templating.render("browser_selection.html.jinja", **ctx)
    status_html = _status_html(ctx["count"])
    events = [
        SSE.patch_elements(state_html, selector="#browser-state"),
        SSE.patch_elements(results_html, selector="#results"),
        SSE.patch_elements(actions_html, selector="#browser-actions"),
        SSE.patch_elements(sel_row_html, selector="#browser-selection-status-row"),
        SSE.patch_elements(status_html, selector="#browser-status"),
    ]
    if selection_deleted:
        detail_shell_html = templating.render("browser_detail_shell.html.jinja", **ctx)
        events.extend(
            [
                SSE.patch_elements(detail_shell_html, selector="#detail"),
                SSE.execute_script("window.ankiwebCloseMobileDetail?.()"),
            ]
        )
    return events


def _mirror_hub(
    hub: BridgeHub | None,
    query: str,
    matched_cids: Sequence[CardId | int],
    selected_cids: Sequence[CardId | int],
    col: Collection,
) -> None:
    if not hub:
        return
    hub.ui_state.browser_open = True
    hub.ui_state.last_browse_query = query
    hub.ui_state.matched_card_ids = [int(c) for c in matched_cids]
    hub.ui_state.selected_card_ids = [int(c) for c in selected_cids]
    hub.ui_state.selected_note_ids = [int(n) for n in _nids(col, selected_cids)]


def _search_context(
    col: Collection, query: str
) -> tuple[dict[str, Any], list[CardId], bool]:
    matched, search_failed = _matched_cards(col, query, None, False)
    ctx = build_browser_context(
        col,
        query=query,
        selected_cids=[],
        selection_anchor=None,
        matched_cids=matched,
        open_detail=False,
        search_error=search_failed,
    )
    return ctx, matched, search_failed


def _select_context(
    col: Collection,
    parsed: BrowserRequestData,
) -> tuple[dict[str, Any], list[CardId], list[CardId]]:
    matched, _ = _matched_cards(col, parsed.browser_query, None, False)
    selected, anchor = _compute_new_selection(
        matched[:_LIMIT],
        parsed.selected_cids,
        parsed.selection_anchor,
        parsed.cid,
        parsed.mode or "single",
    )
    ctx = build_browser_context(
        col,
        query=parsed.browser_query,
        selected_cids=selected,
        selection_anchor=anchor,
        matched_cids=matched,
        open_detail=parsed.open_detail,
    )
    return ctx, matched, [CardId(c) for c in ctx["selected_cids"]]


def _dialog_context(
    col: Collection, parsed: BrowserRequestData, action: str
) -> dict[str, Any]:
    valid_sel = _validate_cids(col, parsed.selected_cids)
    return build_browser_context(
        col,
        query=parsed.browser_query,
        selected_cids=valid_sel,
        selection_anchor=parsed.selection_anchor,
        dialog=action if valid_sel else "",
    )


async def _run_browser_mutation(
    get_service: Callable[[], CollectionService],
    get_hub: Callable[[], BridgeHub] | None,
    request: Request,
    op_fn: Callable[[Collection, list[CardId], BrowserRequestData], Any],
    dialog_name: str = "",
    submitted_value: str = "",
) -> DatastarResponse:
    service = get_service()
    hub = get_hub() if get_hub is not None else None
    parsed = await _parse_browser_request(request)
    applied_q = parsed.browser_query
    raw_cids = parsed.selected_cids
    anchor = parsed.selection_anchor

    # Pre-validate and deduplicate selected CIDs before operation
    valid_cids = await service.run(lambda col: _validate_cids(col, raw_cids))
    if not valid_cids:
        return DatastarResponse()

    try:
        await service.run_op(
            lambda col: op_fn(col, valid_cids, parsed), initiator="browser"
        )
    except (InvalidInput, NotFoundError) as exc:
        err_msg = str(exc)
        logger.warning("Browser mutation error: %s", err_msg)

        def err_ctx(col: Collection) -> dict[str, Any]:
            return build_browser_context(
                col,
                query=applied_q,
                selected_cids=valid_cids,
                selection_anchor=anchor,
                dialog=dialog_name,
                error=err_msg,
                value=submitted_value,
            )

        ctx = await service.run(err_ctx)
        dialogs_html = templating.render("browser_dialogs.html.jinja", **ctx)
        return DatastarResponse(
            [SSE.patch_elements(dialogs_html, selector="#browser-dialogs")]
        )

    # Mutation success: re-fetch and clear selection & close dialog
    def reload_ctx(col: Collection) -> tuple[dict[str, Any], list[CardId]]:
        ctx = build_browser_context(
            col,
            query=applied_q,
            selected_cids=[],
            selection_anchor=None,
            dialog="",
        )
        matched = [CardId(c) for c in ctx["matched_cids"]]
        return ctx, matched

    ctx, matched = await service.run(reload_ctx)
    await service.run(lambda col: _mirror_hub(hub, applied_q, matched, [], col))
    events = _render_selection_patches(ctx)
    return DatastarResponse(events)


async def _search_browser(
    request: Request,
    get_service: Callable[[], CollectionService],
    get_hub: Callable[[], BridgeHub] | None,
) -> DatastarResponse:
    service = get_service()
    hub = get_hub() if get_hub is not None else None
    parsed = await _parse_browser_request(request, prefer_query_draft=True)
    q = parsed.browser_query

    def run(col: Collection) -> tuple[dict[str, Any], list[CardId], bool]:
        return _search_context(col, q)

    ctx, matched, search_failed = await service.run(run)
    await service.run(
        lambda col: _mirror_hub(hub, q if not search_failed else "", matched, [], col)
    )
    return DatastarResponse(_render_selection_patches(ctx))


async def _refresh_browser(
    request: Request,
    get_service: Callable[[], CollectionService],
    get_hub: Callable[[], BridgeHub] | None,
) -> DatastarResponse:
    service = get_service()
    hub = get_hub() if get_hub is not None else None
    parsed = await _parse_browser_request(request)
    applied_q = parsed.browser_query
    cur_sel = parsed.selected_cids
    cur_anc = parsed.selection_anchor

    def run(col: Collection) -> tuple[dict[str, Any], list[CardId], list[CardId], bool]:
        ctx = build_browser_context(
            col,
            query=applied_q,
            selected_cids=cur_sel,
            selection_anchor=cur_anc,
            open_detail=False,
        )
        matched = [CardId(c) for c in ctx["matched_cids"]]
        selected = [CardId(c) for c in ctx["selected_cids"]]
        selection_deleted = bool(set(cur_sel) - set(selected))
        return ctx, matched, selected, selection_deleted

    ctx, matched, valid_sel, selection_deleted = await service.run(run)
    await service.run(lambda col: _mirror_hub(hub, applied_q, matched, valid_sel, col))
    return DatastarResponse(
        _render_refresh_patches(ctx, selection_deleted=selection_deleted)
    )


async def _select_browser_cards(
    request: Request,
    get_service: Callable[[], CollectionService],
    get_hub: Callable[[], BridgeHub] | None,
) -> DatastarResponse:
    service = get_service()
    hub = get_hub() if get_hub is not None else None
    parsed = await _parse_browser_request(request)
    applied_q = parsed.browser_query

    def run(col: Collection) -> tuple[dict[str, Any], list[CardId], list[CardId]]:
        return _select_context(col, parsed)

    ctx, matched, valid_sel = await service.run(run)
    await service.run(lambda col: _mirror_hub(hub, applied_q, matched, valid_sel, col))
    return DatastarResponse(_render_selection_patches(ctx))


async def _open_browser_card(
    cid: int,
    request: Request,
    get_service: Callable[[], CollectionService],
    get_hub: Callable[[], BridgeHub] | None,
) -> DatastarResponse:
    service = get_service()
    hub = get_hub() if get_hub is not None else None
    parsed = await _parse_browser_request(request)
    applied_q = parsed.browser_query
    parsed_cid = _parse_positive_int64(cid)
    card_id = CardId(parsed_cid) if parsed_cid is not None else CardId(cid)

    def run(col: Collection) -> tuple[dict[str, Any], list[CardId], list[CardId]]:
        ctx = build_browser_context(
            col,
            query=applied_q,
            selected_cids=[card_id],
            selection_anchor=card_id,
            open_detail=True,
        )
        matched = [CardId(c) for c in ctx["matched_cids"]]
        selected = [CardId(c) for c in ctx["selected_cids"]]
        return ctx, matched, selected

    ctx, matched, valid_sel = await service.run(run)
    await service.run(lambda col: _mirror_hub(hub, applied_q, matched, valid_sel, col))
    return DatastarResponse(_render_selection_patches(ctx))


async def _set_browser_due(
    request: Request,
    get_service: Callable[[], CollectionService],
    get_hub: Callable[[], BridgeHub] | None,
) -> DatastarResponse:
    parsed = await _parse_browser_request(request)
    val = parsed.value.strip()
    if not val:
        return DatastarResponse()
    return await _run_browser_mutation(
        get_service,
        get_hub,
        request,
        lambda col, cids, p: col.sched.set_due_date(cids, val),
        dialog_name="setdue",
        submitted_value=val,
    )


async def _change_browser_deck(
    request: Request,
    get_service: Callable[[], CollectionService],
    get_hub: Callable[[], BridgeHub] | None,
) -> DatastarResponse:
    parsed = await _parse_browser_request(request)
    deck = parsed.deck.strip()
    if not deck:
        return DatastarResponse()
    return await _run_browser_mutation(
        get_service,
        get_hub,
        request,
        lambda col, cids, p: col.set_deck(cids, _resolve_deck_id(col, deck)),
        dialog_name="changedeck",
        submitted_value=deck,
    )


async def _add_browser_tag(
    request: Request,
    get_service: Callable[[], CollectionService],
    get_hub: Callable[[], BridgeHub] | None,
) -> DatastarResponse:
    parsed = await _parse_browser_request(request)
    tag = parsed.tag.strip()
    if not tag:
        return DatastarResponse()
    return await _run_browser_mutation(
        get_service,
        get_hub,
        request,
        lambda col, cids, p: col.tags.bulk_add(_nids(col, cids), tag),
        dialog_name="addtag",
        submitted_value=tag,
    )


async def _remove_browser_tag(
    request: Request,
    get_service: Callable[[], CollectionService],
    get_hub: Callable[[], BridgeHub] | None,
) -> DatastarResponse:
    parsed = await _parse_browser_request(request)
    tag = parsed.tag.strip()
    if not tag:
        return DatastarResponse()
    return await _run_browser_mutation(
        get_service,
        get_hub,
        request,
        lambda col, cids, p: col.tags.bulk_remove(_nids(col, cids), tag),
        dialog_name="removetag",
        submitted_value=tag,
    )


def make_browser_routes(
    get_service: Callable[[], CollectionService],
    get_hub: Callable[[], BridgeHub] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/browse")

    @router.post("/search")
    async def search(request: Request) -> DatastarResponse:
        return await _search_browser(request, get_service, get_hub)

    @router.post("/refresh")
    async def refresh(request: Request) -> DatastarResponse:
        return await _refresh_browser(request, get_service, get_hub)

    @router.post("/select")
    async def select_cards(request: Request) -> DatastarResponse:
        return await _select_browser_cards(request, get_service, get_hub)

    @router.post("/open/{cid}")
    async def open_card(cid: int, request: Request) -> DatastarResponse:
        return await _open_browser_card(cid, request, get_service, get_hub)

    @router.get("/dialog/close")
    async def close_dialog(request: Request) -> DatastarResponse:
        service = get_service()
        parsed = await _parse_browser_request(request)
        applied_q = parsed.browser_query
        cur_sel = parsed.selected_cids
        cur_anc = parsed.selection_anchor

        def run(col: Collection) -> dict[str, Any]:
            return build_browser_context(
                col,
                query=applied_q,
                selected_cids=cur_sel,
                selection_anchor=cur_anc,
                dialog="",
            )

        ctx = await service.run(run)
        dialogs_html = templating.render("browser_dialogs.html.jinja", **ctx)
        return DatastarResponse(
            [SSE.patch_elements(dialogs_html, selector="#browser-dialogs")]
        )

    @router.get("/dialog/{action}")
    async def open_dialog(action: str, request: Request) -> DatastarResponse:
        service = get_service()
        parsed = await _parse_browser_request(request)

        def run(col: Collection) -> dict[str, Any]:
            return _dialog_context(col, parsed, action)

        ctx = await service.run(run)
        dialogs_html = templating.render("browser_dialogs.html.jinja", **ctx)
        return DatastarResponse(
            [SSE.patch_elements(dialogs_html, selector="#browser-dialogs")]
        )

    async def _handle_mutation(
        request: Request,
        op_fn: Callable[[Collection, list[CardId], BrowserRequestData], Any],
        dialog_name: str = "",
        submitted_value: str = "",
    ) -> DatastarResponse:
        return await _run_browser_mutation(
            get_service, get_hub, request, op_fn, dialog_name, submitted_value
        )

    @router.post("/suspend")
    async def suspend(request: Request) -> DatastarResponse:
        return await _handle_mutation(
            request, lambda col, cids, p: col.sched.suspend_cards(cids)
        )

    @router.post("/unsuspend")
    async def unsuspend(request: Request) -> DatastarResponse:
        return await _handle_mutation(
            request, lambda col, cids, p: col.sched.unsuspend_cards(cids)
        )

    @router.post("/forget")
    async def forget(request: Request) -> DatastarResponse:
        return await _handle_mutation(
            request, lambda col, cids, p: col.sched.schedule_cards_as_new(cids)
        )

    @router.post("/delete")
    async def delete_notes(request: Request) -> DatastarResponse:
        return await _handle_mutation(
            request,
            lambda col, cids, p: col.remove_notes(_nids(col, cids)),
            dialog_name="delete",
        )

    @router.post("/setdue")
    async def set_due(request: Request) -> DatastarResponse:
        return await _set_browser_due(request, get_service, get_hub)

    @router.post("/changedeck")
    async def change_deck(request: Request) -> DatastarResponse:
        return await _change_browser_deck(request, get_service, get_hub)

    @router.post("/addtag")
    async def add_tag(request: Request) -> DatastarResponse:
        return await _add_browser_tag(request, get_service, get_hub)

    @router.post("/removetag")
    async def remove_tag(request: Request) -> DatastarResponse:
        return await _remove_browser_tag(request, get_service, get_hub)

    return router
