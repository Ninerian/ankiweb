from __future__ import annotations

import html
import json
import logging
from collections.abc import Callable
from functools import partial
from typing import Annotated, Any, cast

import anki.errors
import anki.notetypes_pb2 as nt
from datastar_py.fastapi import (
    DatastarResponse,
    ReadSignals,
)
from datastar_py.fastapi import (
    ServerSentEventGenerator as SSE,
)
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from ankiweb.adapters.inbound.http_datastar.common import (
    elements_response,
    redirect_response,
)
from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.adapters.inbound.http_shared.page import render_page
from ankiweb.core.i18n import tr

logger = logging.getLogger(__name__)


def _compute_unused(old_names: list[str], mapping: list[int | None]) -> list[str]:
    used = {val for val in mapping if val is not None and val >= 0}
    return [name for idx, name in enumerate(old_names) if idx not in used]


def _is_unchanged(
    old_id: int,
    new_id: int,
    fields: list[int | None],
    templates: list[int | None] | None,
) -> bool:
    return (
        old_id == new_id
        and fields == list(range(len(fields)))
        and (templates is None or templates == list(range(len(templates))))
    )


def _context_mapping(defaults, current: list[int | None] | None, count: int):
    default_mapping = [None if val == -1 else val for val in defaults]
    if current is not None and len(current) == count:
        return current
    return default_mapping


def _mapping_rows(names: list[str], mapping: list[int | None]):
    return [
        {
            "new_index": idx,
            "new_name": name,
            "selected_value": -1 if mapping[idx] is None else mapping[idx],
        }
        for idx, name in enumerate(names)
    ]


def _add_mapping_signals(
    signals: dict[str, Any], prefix: str, mapping: list[int | None]
) -> None:
    for idx, val in enumerate(mapping):
        signals[f"{prefix}_map_{idx}"] = -1 if val is None else val


def _prepare_template_context(
    col,
    old_ntid: int,
    new_ntid: int,
    note_ids: list[int],
    current_fields_map: list[int | None] | None = None,
    current_templates_map: list[int | None] | None = None,
    error_msg: str | None = None,
    info_msg: str | None = None,
) -> dict[str, Any]:
    info = col.models.change_notetype_info(
        old_notetype_id=old_ntid,
        new_notetype_id=new_ntid,
    )

    notetypes_raw = col.models.all_names_and_ids()
    notetypes = [{"id": n.id, "name": n.name} for n in notetypes_raw]

    old_field_names = list(info.old_field_names)
    new_field_names = list(info.new_field_names)
    old_template_names = list(info.old_template_names)
    new_template_names = list(info.new_template_names)

    fields_map = _context_mapping(
        info.input.new_fields, current_fields_map, len(new_field_names)
    )
    has_templates = len(info.input.new_templates) > 0 and not info.input.is_cloze
    templates_map = (
        _context_mapping(
            info.input.new_templates, current_templates_map, len(new_template_names)
        )
        if has_templates
        else []
    )

    # Options for old fields dropdown: indices 0..len-1, plus -1 for Nothing
    nothing_label = tr.change_notetype_nothing()
    old_field_options = [
        {"value": idx, "label": name} for idx, name in enumerate(old_field_names)
    ] + [{"value": -1, "label": nothing_label}]

    old_template_options = [
        {"value": idx, "label": name} for idx, name in enumerate(old_template_names)
    ] + [{"value": -1, "label": nothing_label}]

    field_rows = _mapping_rows(new_field_names, fields_map)
    template_rows = (
        _mapping_rows(new_template_names, templates_map) if has_templates else []
    )

    unused_fields = _compute_unused(old_field_names, fields_map)
    unused_templates = (
        _compute_unused(old_template_names, templates_map) if has_templates else []
    )

    initial_signals = {
        "old_notetype_id": old_ntid,
        "target_notetype_id": new_ntid,
        "note_ids": note_ids,
        "collapsed_fields": True,
        "collapsed_templates": True,
        "current_schema": int(info.input.current_schema),
        "old_notetype_name": info.input.old_notetype_name,
        "is_cloze": bool(info.input.is_cloze),
    }
    _add_mapping_signals(initial_signals, "field", fields_map)
    if has_templates:
        _add_mapping_signals(initial_signals, "template", templates_map)

    return {
        "old_notetype_id": old_ntid,
        "new_notetype_id": new_ntid,
        "old_notetype_name": info.input.old_notetype_name,
        "notetypes": notetypes,
        "old_field_options": old_field_options,
        "old_template_options": old_template_options,
        "field_rows": field_rows,
        "template_rows": template_rows,
        "has_templates": has_templates,
        "unused_fields": unused_fields,
        "unused_templates": unused_templates,
        "error_msg": error_msg,
        "info_msg": info_msg,
        "initial_signals_json": json.dumps(initial_signals),
    }


def render_change_notetype_html(
    col,
    old_ntid: int,
    new_ntid: int,
    note_ids: list[int],
    current_fields_map: list[int | None] | None = None,
    current_templates_map: list[int | None] | None = None,
    error_msg: str | None = None,
    info_msg: str | None = None,
) -> str:
    ctx = _prepare_template_context(
        col,
        old_ntid=old_ntid,
        new_ntid=new_ntid,
        note_ids=note_ids,
        current_fields_map=current_fields_map,
        current_templates_map=current_templates_map,
        error_msg=error_msg,
        info_msg=info_msg,
    )
    return templating.render("pages/change_notetype.html.jinja", **ctx)


def render_fatal_error_html(msg: str) -> str:
    return templating.render("pages/change_notetype.html.jinja", fatal_error=msg)


class _SelectionError(ValueError):
    pass


def _parse_card_ids(raw_cids: str | None) -> list[int]:
    if raw_cids is None or not raw_cids:
        raise _SelectionError("Invalid card selection: provide at least one card ID.")

    card_ids: list[int] = []
    for raw_cid in raw_cids.split(","):
        if not raw_cid.isascii() or not raw_cid.isdigit():
            raise _SelectionError(
                "Invalid card selection: card IDs must be positive integers separated by commas."
            )
        try:
            card_id = int(raw_cid)
        except ValueError as exc:
            raise _SelectionError(
                "Invalid card selection: card IDs must be positive integers separated by commas."
            ) from exc
        if card_id <= 0:
            raise _SelectionError(
                "Invalid card selection: card IDs must be positive integers separated by commas."
            )
        card_ids.append(card_id)
    return card_ids


def _resolve_card_selection(col, card_ids: list[int]) -> tuple[int, list[int]]:
    old_ntid: int | None = None
    note_ids: list[int] = []
    seen_note_ids: set[int] = set()

    for card_id in card_ids:
        try:
            card = col.get_card(card_id)
            note = card.note()
        except anki.errors.NotFoundError as exc:
            raise _SelectionError(
                "Invalid card selection: one or more selected cards no longer exist."
            ) from exc

        if old_ntid is None:
            old_ntid = note.mid
        elif note.mid != old_ntid:
            raise _SelectionError(
                "Invalid card selection: all selected cards must have the same note type."
            )

        if card.nid not in seen_note_ids:
            note_ids.append(card.nid)
            seen_note_ids.add(card.nid)

    if old_ntid is None:
        raise _SelectionError("Invalid card selection: provide at least one card ID.")
    return old_ntid, note_ids


def _parse_note_ids(raw_note_ids: Any) -> list[int]:
    if not isinstance(raw_note_ids, list):
        raise _SelectionError(
            "Invalid note selection: note IDs must be provided as a list."
        )
    if not raw_note_ids:
        raise _SelectionError("Invalid note selection: select at least one note.")

    note_ids: list[int] = []
    for raw_note_id in raw_note_ids:
        if isinstance(raw_note_id, bool):
            raise _SelectionError(
                "Invalid note selection: note IDs must be positive integers."
            )
        if isinstance(raw_note_id, int):
            note_id = raw_note_id
        elif (
            isinstance(raw_note_id, str)
            and raw_note_id.isascii()
            and raw_note_id.isdigit()
        ):
            try:
                note_id = int(raw_note_id)
            except ValueError as exc:
                raise _SelectionError(
                    "Invalid note selection: note IDs must be positive integers."
                ) from exc
        else:
            raise _SelectionError(
                "Invalid note selection: note IDs must be positive integers."
            )

        if note_id <= 0:
            raise _SelectionError(
                "Invalid note selection: note IDs must be positive integers."
            )
        note_ids.append(note_id)
    return note_ids


def _validate_note_ids(col, note_ids: list[int], old_ntid: int) -> None:
    for note_id in note_ids:
        try:
            note = col.get_note(note_id)
        except anki.errors.NotFoundError as exc:
            raise _SelectionError(
                "Invalid note selection: one or more selected notes no longer exist."
            ) from exc
        if note.mid != old_ntid:
            raise _SelectionError(
                "Invalid note selection: selected notes must all have the source note type."
            )


def _selection_error_html(message: str) -> str:
    return f'<div class="alert alert-error py-2 px-3 mb-3">{html.escape(message)}</div>'


def _selection_error_response(message: str):
    return elements_response(
        _selection_error_html(message),
        selector="#change-notetype-alert-area",
    )


def _render_initial_selection(col, card_ids: list[int]) -> tuple[str, bool]:
    try:
        old_id, note_ids = _resolve_card_selection(col, card_ids)
    except _SelectionError as exc:
        return render_fatal_error_html(str(exc)), True

    try:
        col.models.change_notetype_info(old_notetype_id=old_id, new_notetype_id=old_id)
    except anki.errors.BackendError as exc:
        return render_fatal_error_html(str(exc)), False

    return render_change_notetype_html(col, old_id, old_id, note_ids), False


async def _change_notetype_page(get_service: Callable, cids: str | None):
    try:
        card_ids = _parse_card_ids(cids)
    except _SelectionError as exc:
        body = render_fatal_error_html(str(exc))
        return HTMLResponse(render_page("changenotetype", body), status_code=400)

    service = get_service()
    body, invalid_selection = await service.run(
        partial(_render_initial_selection, card_ids=card_ids)
    )
    return HTMLResponse(
        render_page("changenotetype", body),
        status_code=400 if invalid_selection else 200,
    )


def _payload_selection(payload) -> tuple[int, int, list[int]]:
    if not payload or not isinstance(payload, dict):
        raise _SelectionError("Invalid payload")
    try:
        old_id = int(cast(Any, payload.get("old_notetype_id")))
        new_id = int(cast(Any, payload.get("target_notetype_id")))
    except (ValueError, TypeError) as exc:
        raise _SelectionError("Malformed notetype IDs") from exc
    return old_id, new_id, _parse_note_ids(payload.get("note_ids"))


def _backend_error_html(exc: Exception) -> str:
    return f'<div class="alert alert-error py-2 px-3 mb-3">{exc}</div>'


def _render_response(body: str):
    if body.startswith('<div class="alert alert-error'):
        return elements_response(body, selector="#change-notetype-alert-area")
    return elements_response(body, selector="#change-notetype-content")


def _render_target(col, old_id: int, new_id: int, note_ids: list[int]) -> str:
    try:
        _validate_note_ids(col, note_ids, old_id)
        return render_change_notetype_html(col, old_id, new_id, note_ids)
    except _SelectionError as exc:
        return _selection_error_html(str(exc))
    except anki.errors.BackendError as exc:
        return _backend_error_html(exc)


async def _select_target(service, payload):
    try:
        old_id, new_id, note_ids = _payload_selection(payload)
    except _SelectionError as exc:
        return _selection_error_response(str(exc))
    body = await service.run(
        partial(_render_target, old_id=old_id, new_id=new_id, note_ids=note_ids)
    )
    return _render_response(body)


def _change_info(col, old_id: int, new_id: int, note_ids: list[int]):
    _validate_note_ids(col, note_ids, old_id)
    return col.models.change_notetype_info(
        old_notetype_id=old_id, new_notetype_id=new_id
    )


def _mapping_counts(col, old_id: int, new_id: int, note_ids: list[int]):
    info = _change_info(col, old_id, new_id, note_ids)
    return len(info.new_field_names), len(info.new_template_names)


def _mapping_value(payload, prefix: str, index: int) -> int | None:
    try:
        val = int(payload.get(f"{prefix}_map_{index}", -1))
    except (ValueError, TypeError):
        val = -1
    return None if val == -1 else val


def _payload_mapping(payload, prefix: str, count: int) -> list[int | None]:
    mapping: list[int | None] = []
    for index in range(count):
        mapping.append(_mapping_value(payload, prefix, index))
    return mapping


def _template_mapping(payload, count: int, new_index: int) -> list[int | None]:
    # Upstream enforces that template mappings cannot have duplicates.
    target = _mapping_value(payload, "template", new_index)
    mapping: list[int | None] = []
    for index in range(count):
        if index == new_index:
            mapping.append(target)
        else:
            current = _mapping_value(payload, "template", index)
            if target is not None and current == target:
                mapping.append(None)
            else:
                mapping.append(current)
    return mapping


def _render_remapping(
    col,
    old_id: int,
    new_id: int,
    note_ids: list[int],
    fields_map: list[int | None],
    templates_map: list[int | None],
) -> str:
    try:
        return render_change_notetype_html(
            col,
            old_ntid=old_id,
            new_ntid=new_id,
            note_ids=note_ids,
            current_fields_map=fields_map,
            current_templates_map=templates_map,
        )
    except anki.errors.BackendError as exc:
        return _backend_error_html(exc)


async def _remap(service, payload, template_index: int | None):
    try:
        old_id, new_id, note_ids = _payload_selection(payload)
        num_fields, num_templates = await service.run(
            partial(_mapping_counts, old_id=old_id, new_id=new_id, note_ids=note_ids)
        )
    except _SelectionError as exc:
        return _selection_error_response(str(exc))
    except anki.errors.BackendError as exc:
        return elements_response(
            _backend_error_html(exc), selector="#change-notetype-alert-area"
        )

    fields_map = _payload_mapping(payload, "field", num_fields)
    templates_map = (
        _payload_mapping(payload, "template", num_templates)
        if template_index is None
        else _template_mapping(payload, num_templates, template_index)
    )
    body = await service.run(
        partial(
            _render_remapping,
            old_id=old_id,
            new_id=new_id,
            note_ids=note_ids,
            fields_map=fields_map,
            templates_map=templates_map,
        )
    )
    return _render_response(body)


def _change_request(
    payload,
    info,
    old_id: int,
    new_id: int,
    fields_map: list[int | None],
    templates_map: list[int | None],
    has_templates: bool,
) -> nt.ChangeNotetypeRequest:
    req = nt.ChangeNotetypeRequest()
    req.old_notetype_id = old_id
    req.new_notetype_id = new_id
    try:
        req.current_schema = int(
            payload.get("current_schema", info.input.current_schema)
        )
    except (ValueError, TypeError):
        req.current_schema = int(info.input.current_schema)
    req.old_notetype_name = str(
        payload.get("old_notetype_name", info.input.old_notetype_name)
    )
    req.is_cloze = bool(payload.get("is_cloze", info.input.is_cloze))
    req.new_fields.extend([-1 if val is None else val for val in fields_map])
    if has_templates:
        req.new_templates.extend([-1 if val is None else val for val in templates_map])
    return req


def _execute_change(
    col, note_ids: list[int], old_id: int, req: nt.ChangeNotetypeRequest
):
    _validate_note_ids(col, note_ids, old_id)
    return col._backend.change_notetype(
        note_ids=note_ids,
        new_fields=req.new_fields,
        new_templates=req.new_templates,
        old_notetype_id=req.old_notetype_id,
        new_notetype_id=req.new_notetype_id,
        current_schema=req.current_schema,
        old_notetype_name=req.old_notetype_name,
        is_cloze=req.is_cloze,
    )


async def _save_change(service, payload):
    try:
        old_id, new_id, note_ids = _payload_selection(payload)
        info = await service.run(
            partial(_change_info, old_id=old_id, new_id=new_id, note_ids=note_ids)
        )
    except _SelectionError as exc:
        return _selection_error_response(str(exc))
    except anki.errors.BackendError as exc:
        return elements_response(
            _backend_error_html(exc), selector="#change-notetype-alert-area"
        )

    num_fields = len(info.new_field_names)
    num_templates = len(info.new_template_names)
    has_templates = len(info.input.new_templates) > 0 and not info.input.is_cloze
    fields_map = _payload_mapping(payload, "field", num_fields)
    templates_map = (
        _payload_mapping(payload, "template", num_templates) if has_templates else []
    )
    if _is_unchanged(
        old_id, new_id, fields_map, templates_map if has_templates else None
    ):
        return DatastarResponse(SSE.execute_script("alert('No changes to save')"))

    req = _change_request(
        payload, info, old_id, new_id, fields_map, templates_map, has_templates
    )
    try:
        await service.run_op(
            partial(_execute_change, note_ids=note_ids, old_id=old_id, req=req),
            initiator="change-notetype",
        )
    except _SelectionError as exc:
        return _selection_error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to change notetype")
        return elements_response(
            _backend_error_html(exc), selector="#change-notetype-alert-area"
        )
    return redirect_response("/deckbrowser")


def make_router(get_service: Callable) -> APIRouter:
    router = APIRouter()

    @router.get("/change-notetype")
    async def page(cids: Annotated[str | None, Query()] = None):
        return await _change_notetype_page(get_service, cids)

    @router.post("/change-notetype/select-target")
    async def select_target(payload: ReadSignals):
        return await _select_target(get_service(), payload)

    @router.post("/change-notetype/remap-field")
    async def remap_field(payload: ReadSignals, new_index: Annotated[int, Query()]):
        return await _remap(get_service(), payload, None)

    @router.post("/change-notetype/remap-template")
    async def remap_template(payload: ReadSignals, new_index: Annotated[int, Query()]):
        return await _remap(get_service(), payload, new_index)

    @router.post("/change-notetype/save")
    async def save(payload: ReadSignals):
        return await _save_change(get_service(), payload)

    return router
