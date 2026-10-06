from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, cast

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

    default_fields = [
        None if val == -1 else val for val in info.input.new_fields
    ]
    if current_fields_map is not None and len(current_fields_map) == len(new_field_names):
        fields_map = current_fields_map
    else:
        fields_map = default_fields

    has_templates = len(info.input.new_templates) > 0 and not info.input.is_cloze
    if has_templates:
        default_templates = [
            None if val == -1 else val for val in info.input.new_templates
        ]
        if current_templates_map is not None and len(current_templates_map) == len(new_template_names):
            templates_map = current_templates_map
        else:
            templates_map = default_templates
    else:
        templates_map = []

    # Options for old fields dropdown: indices 0..len-1, plus -1 for Nothing
    nothing_label = tr.change_notetype_nothing()
    old_field_options = [
        {"value": idx, "label": name} for idx, name in enumerate(old_field_names)
    ] + [{"value": -1, "label": nothing_label}]

    old_template_options = [
        {"value": idx, "label": name} for idx, name in enumerate(old_template_names)
    ] + [{"value": -1, "label": nothing_label}]

    field_rows = [
        {
            "new_index": idx,
            "new_name": name,
            "selected_value": -1 if fields_map[idx] is None else fields_map[idx],
        }
        for idx, name in enumerate(new_field_names)
    ]

    template_rows = [
        {
            "new_index": idx,
            "new_name": name,
            "selected_value": -1 if templates_map[idx] is None else templates_map[idx],
        }
        for idx, name in enumerate(new_template_names)
    ] if has_templates else []

    unused_fields = _compute_unused(old_field_names, fields_map)
    unused_templates = _compute_unused(old_template_names, templates_map) if has_templates else []

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
    for idx, val in enumerate(fields_map):
        initial_signals[f"field_map_{idx}"] = -1 if val is None else val
    if has_templates:
        for idx, val in enumerate(templates_map):
            initial_signals[f"template_map_{idx}"] = -1 if val is None else val

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


def make_router(get_service: Callable) -> APIRouter:
    router = APIRouter()

    @router.get("/change-notetype/{ids:path}")
    async def page(ids: str):
        service = get_service()
        raw_parts = ids.split("/")
        from_str = raw_parts[0] if raw_parts else ""
        to_str = raw_parts[1] if len(raw_parts) > 1 else None

        try:
            old_id = int(from_str)
        except (ValueError, TypeError):
            msg = f"Cannot convert {from_str} to a BigInt"
            body = render_fatal_error_html(msg)
            return HTMLResponse(render_page("changenotetype", body))

        if to_str is not None:
            try:
                new_id = int(to_str)
            except (ValueError, TypeError):
                msg = f"Cannot convert {to_str} to a BigInt"
                body = render_fatal_error_html(msg)
                return HTMLResponse(render_page("changenotetype", body))
        else:
            new_id = old_id

        def check_and_render(col):
            try:
                col.models.change_notetype_info(
                    old_notetype_id=old_id,
                    new_notetype_id=new_id,
                )
            except anki.errors.BackendError as exc:
                return render_fatal_error_html(str(exc))

            # Fetch note ids of old_id
            note_ids = list(col.models.nids(old_id))

            return render_change_notetype_html(
                col,
                old_ntid=old_id,
                new_ntid=new_id,
                note_ids=note_ids,
            )

        body = await service.run(check_and_render)
        return HTMLResponse(render_page("changenotetype", body))

    @router.post("/change-notetype/select-target")
    async def select_target(payload: ReadSignals):
        service = get_service()
        if not payload or not isinstance(payload, dict):
            err_html = '<div class="alert alert-error py-2 px-3 mb-3">Invalid payload</div>'
            return elements_response(err_html, selector="#change-notetype-alert-area")

        try:
            old_id = int(cast(Any, payload.get("old_notetype_id")))
            new_id = int(cast(Any, payload.get("target_notetype_id")))
        except (ValueError, TypeError):
            err_html = '<div class="alert alert-error py-2 px-3 mb-3">Malformed notetype IDs</div>'
            return elements_response(err_html, selector="#change-notetype-alert-area")

        note_ids = payload.get("note_ids", [])
        if not isinstance(note_ids, list):
            note_ids = []

        def render(col):
            try:
                return render_change_notetype_html(
                    col,
                    old_ntid=old_id,
                    new_ntid=new_id,
                    note_ids=note_ids,
                )
            except anki.errors.BackendError as exc:
                return f'<div class="alert alert-error py-2 px-3 mb-3">{exc}</div>'

        html = await service.run(render)
        if html.startswith('<div class="alert alert-error'):
            return elements_response(html, selector="#change-notetype-alert-area")
        return elements_response(html, selector="#change-notetype-content")

    @router.post("/change-notetype/remap-field")
    async def remap_field(
        payload: ReadSignals,
        new_index: int = Query(...),
    ):
        service = get_service()
        if not payload or not isinstance(payload, dict):
            err_html = '<div class="alert alert-error py-2 px-3 mb-3">Invalid payload</div>'
            return elements_response(err_html, selector="#change-notetype-alert-area")

        try:
            old_id = int(cast(Any, payload.get("old_notetype_id")))
            new_id = int(cast(Any, payload.get("target_notetype_id")))
        except (ValueError, TypeError):
            err_html = '<div class="alert alert-error py-2 px-3 mb-3">Malformed notetype IDs</div>'
            return elements_response(err_html, selector="#change-notetype-alert-area")

        note_ids = payload.get("note_ids", [])
        if not isinstance(note_ids, list):
            note_ids = []

        def get_counts(col):
            info = col.models.change_notetype_info(
                old_notetype_id=old_id,
                new_notetype_id=new_id,
            )
            return len(info.new_field_names), len(info.new_template_names)

        try:
            num_fields, num_templates = await service.run(get_counts)
        except anki.errors.BackendError as exc:
            err_html = f'<div class="alert alert-error py-2 px-3 mb-3">{exc}</div>'
            return elements_response(err_html, selector="#change-notetype-alert-area")

        fields_map: list[int | None] = []
        for i in range(num_fields):
            try:
                val = int(payload.get(f"field_map_{i}", -1))
            except (ValueError, TypeError):
                val = -1
            fields_map.append(None if val == -1 else val)

        templates_map: list[int | None] = []
        for i in range(num_templates):
            try:
                val = int(payload.get(f"template_map_{i}", -1))
            except (ValueError, TypeError):
                val = -1
            templates_map.append(None if val == -1 else val)

        def render(col):
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
                return f'<div class="alert alert-error py-2 px-3 mb-3">{exc}</div>'

        html = await service.run(render)
        if html.startswith('<div class="alert alert-error'):
            return elements_response(html, selector="#change-notetype-alert-area")
        return elements_response(html, selector="#change-notetype-content")

    @router.post("/change-notetype/remap-template")
    async def remap_template(
        payload: ReadSignals,
        new_index: int = Query(...),
    ):
        service = get_service()
        if not payload or not isinstance(payload, dict):
            err_html = '<div class="alert alert-error py-2 px-3 mb-3">Invalid payload</div>'
            return elements_response(err_html, selector="#change-notetype-alert-area")

        try:
            old_id = int(cast(Any, payload.get("old_notetype_id")))
            new_id = int(cast(Any, payload.get("target_notetype_id")))
        except (ValueError, TypeError):
            err_html = '<div class="alert alert-error py-2 px-3 mb-3">Malformed notetype IDs</div>'
            return elements_response(err_html, selector="#change-notetype-alert-area")

        note_ids = payload.get("note_ids", [])
        if not isinstance(note_ids, list):
            note_ids = []

        def get_counts(col):
            info = col.models.change_notetype_info(
                old_notetype_id=old_id,
                new_notetype_id=new_id,
            )
            return len(info.new_field_names), len(info.new_template_names)

        try:
            num_fields, num_templates = await service.run(get_counts)
        except anki.errors.BackendError as exc:
            err_html = f'<div class="alert alert-error py-2 px-3 mb-3">{exc}</div>'
            return elements_response(err_html, selector="#change-notetype-alert-area")

        fields_map: list[int | None] = []
        for i in range(num_fields):
            try:
                val = int(payload.get(f"field_map_{i}", -1))
            except (ValueError, TypeError):
                val = -1
            fields_map.append(None if val == -1 else val)

        # For templates: upstream enforces that template mappings cannot have duplicates.
        try:
            target_val = int(payload.get(f"template_map_{new_index}", -1))
        except (ValueError, TypeError):
            target_val = -1
        real_old_idx = None if target_val == -1 else target_val

        templates_map: list[int | None] = []
        for i in range(num_templates):
            if i == new_index:
                templates_map.append(real_old_idx)
            else:
                try:
                    val = int(payload.get(f"template_map_{i}", -1))
                except (ValueError, TypeError):
                    val = -1
                curr_real = None if val == -1 else val
                if real_old_idx is not None and curr_real == real_old_idx:
                    templates_map.append(None)
                else:
                    templates_map.append(curr_real)

        def render(col):
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
                return f'<div class="alert alert-error py-2 px-3 mb-3">{exc}</div>'

        html = await service.run(render)
        if html.startswith('<div class="alert alert-error'):
            return elements_response(html, selector="#change-notetype-alert-area")
        return elements_response(html, selector="#change-notetype-content")

    @router.post("/change-notetype/save")
    async def save(payload: ReadSignals):
        service = get_service()
        if not payload or not isinstance(payload, dict):
            err_html = '<div class="alert alert-error py-2 px-3 mb-3">Invalid payload</div>'
            return elements_response(err_html, selector="#change-notetype-alert-area")

        try:
            old_id = int(cast(Any, payload.get("old_notetype_id")))
            new_id = int(cast(Any, payload.get("target_notetype_id")))
        except (ValueError, TypeError):
            err_html = '<div class="alert alert-error py-2 px-3 mb-3">Malformed notetype IDs</div>'
            return elements_response(err_html, selector="#change-notetype-alert-area")

        raw_nids = payload.get("note_ids", [])
        note_ids: list[int] = []
        if isinstance(raw_nids, list):
            for nid in raw_nids:
                try:
                    note_ids.append(int(nid))
                except (ValueError, TypeError):
                    pass

        def get_info(col):
            return col.models.change_notetype_info(
                old_notetype_id=old_id,
                new_notetype_id=new_id,
            )

        try:
            info = await service.run(get_info)
        except anki.errors.BackendError as exc:
            err_html = f'<div class="alert alert-error py-2 px-3 mb-3">{exc}</div>'
            return elements_response(err_html, selector="#change-notetype-alert-area")

        num_fields = len(info.new_field_names)
        num_templates = len(info.new_template_names)
        has_templates = len(info.input.new_templates) > 0 and not info.input.is_cloze

        fields_map: list[int | None] = []
        for i in range(num_fields):
            try:
                val = int(payload.get(f"field_map_{i}", -1))
            except (ValueError, TypeError):
                val = -1
            fields_map.append(None if val == -1 else val)

        templates_map: list[int | None] = []
        if has_templates:
            for i in range(num_templates):
                try:
                    val = int(payload.get(f"template_map_{i}", -1))
                except (ValueError, TypeError):
                    val = -1
                templates_map.append(None if val == -1 else val)

        # Check unchanged
        if _is_unchanged(old_id, new_id, fields_map, templates_map if has_templates else None):
            return DatastarResponse(
                SSE.execute_script("alert('No changes to save')")
            )

        req = nt.ChangeNotetypeRequest()
        req.old_notetype_id = old_id
        req.new_notetype_id = new_id
        try:
            req.current_schema = int(payload.get("current_schema", info.input.current_schema))
        except (ValueError, TypeError):
            req.current_schema = int(info.input.current_schema)
        req.old_notetype_name = str(payload.get("old_notetype_name", info.input.old_notetype_name))
        req.is_cloze = bool(payload.get("is_cloze", info.input.is_cloze))
        req.new_fields.extend([-1 if val is None else val for val in fields_map])
        if has_templates:
            req.new_templates.extend([-1 if val is None else val for val in templates_map])

        def execute_change(col):
            final_nids = note_ids
            if not final_nids:
                final_nids = list(col.models.nids(old_id))
            return col._backend.change_notetype(
                note_ids=final_nids,
                new_fields=req.new_fields,
                new_templates=req.new_templates,
                old_notetype_id=req.old_notetype_id,
                new_notetype_id=req.new_notetype_id,
                current_schema=req.current_schema,
                old_notetype_name=req.old_notetype_name,
                is_cloze=req.is_cloze,
            )

        try:
            await service.run_op(execute_change, initiator="change-notetype")
        except Exception as exc:
            logger.exception("Failed to change notetype")
            err_html = f'<div class="alert alert-error py-2 px-3 mb-3">{exc}</div>'
            return elements_response(err_html, selector="#change-notetype-alert-area")

        return redirect_response("/deckbrowser")

    return router
