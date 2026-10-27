from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import anki.import_export_pb2 as ie
from datastar_py.fastapi import (
    DatastarResponse,
    ReadSignals,
)
from datastar_py.fastapi import (
    ServerSentEventGenerator as SSE,
)
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from ankiweb import import_tmp
from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.adapters.inbound.http_shared.page import render_page
from ankiweb.core.i18n import tr

logger = logging.getLogger(__name__)


def _column_option(
    idx: int,
    col_label: str,
    notetype_col: int | None,
    deck_col: int | None,
    guid_col: int,
    preview_first_row: list[str],
) -> dict[str, Any]:
    if idx == notetype_col:
        label = f"{idx}: {tr.notetypes_notetype()}"
    elif idx == deck_col:
        label = f"{idx}: {tr.decks_deck()}"
    elif idx == guid_col:
        label = f"{idx}: GUID"
    elif not col_label:
        val_text = (
            preview_first_row[idx - 1] if idx - 1 < len(preview_first_row) else ""
        )
        label = f"{idx}: {val_text}" if val_text else str(idx)
        return {
            "value": idx,
            "label": label,
            "short_label": str(idx),
            "disabled": False,
        }
    else:
        label = f"{idx}: {col_label}"
        return {"value": idx, "label": label, "short_label": None, "disabled": False}
    return {"value": idx, "label": label, "short_label": None, "disabled": True}


def _make_column_options(meta: ie.CsvMetadata) -> list[dict[str, Any]]:
    deck_col = meta.deck_column if meta.WhichOneof("deck") == "deck_column" else None
    notetype_col = (
        meta.notetype_column
        if meta.WhichOneof("notetype") == "notetype_column"
        else None
    )

    options = [
        {
            "value": 0,
            "label": tr.change_notetype_nothing(),
            "short_label": None,
            "disabled": False,
        }
    ]

    preview_first_row = list(meta.preview[0].vals) if meta.preview else []

    for idx, col_label in enumerate(meta.column_labels, start=1):
        options.append(
            _column_option(
                idx,
                col_label,
                notetype_col,
                deck_col,
                meta.guid_column,
                preview_first_row,
            )
        )

    return options


def _new_deck_name(meta: ie.CsvMetadata, decks: list[dict[str, Any]]) -> str:
    new_deck_name = meta.deck_name if meta.WhichOneof("deck") == "deck_name" else ""
    if new_deck_name:
        decks.append({"id": 0, "name": new_deck_name})
    return new_deck_name


def _selected_deck_id(
    meta: ie.CsvMetadata,
    decks: list[dict[str, Any]],
    override_deck_id: int | None,
    new_deck_name: str,
) -> int:
    return (
        override_deck_id
        if override_deck_id is not None
        else (
            0 if new_deck_name else (meta.deck_id or (decks[0]["id"] if decks else 1))
        )
    )


def _selected_notetype(
    meta: ie.CsvMetadata,
    notetypes: list[dict[str, Any]],
    override_notetype_id: int | None,
) -> int:
    return (
        override_notetype_id
        if override_notetype_id is not None
        else (
            meta.global_notetype.id
            if meta.WhichOneof("notetype") == "global_notetype"
            else (notetypes[0]["id"] if notetypes else 0)
        )
    )


def _field_columns(
    meta: ie.CsvMetadata,
    field_names: list[str],
    override_field_columns: list[int] | None,
) -> list[int]:
    if override_field_columns is not None and len(override_field_columns) == len(
        field_names
    ):
        return override_field_columns
    field_columns = (
        list(meta.global_notetype.field_columns)
        if meta.WhichOneof("notetype") == "global_notetype"
        else []
    )
    while len(field_columns) < len(field_names):
        field_columns.append(0)
    return field_columns


def _field_rows(
    field_names: list[str],
    field_columns: list[int],
    column_options: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for idx, name in enumerate(field_names):
        col_idx = field_columns[idx] if idx < len(field_columns) else 0
        rows.append(
            {
                "index": idx,
                "name": name,
                "selected_column": col_idx,
                "options": column_options[1:] if idx == 0 else column_options,
            }
        )
    return rows


def _metadata_request(
    csv_path: str,
    delimiter: int | None,
    is_html: bool | None,
    notetype_id: int | None,
    deck_id: int | None,
) -> ie.CsvMetadataRequest:
    req = ie.CsvMetadataRequest(path=csv_path)
    if delimiter is not None:
        req.delimiter = cast(ie.CsvMetadata.Delimiter.ValueType, delimiter)
    if is_html is not None:
        req.is_html = is_html
    if notetype_id is not None:
        req.notetype_id = notetype_id
    if deck_id is not None:
        req.deck_id = deck_id
    return req


def _new_deck_warning(new_deck_name: str, selected_deck_id: int) -> str:
    if new_deck_name and selected_deck_id == 0:
        return tr.importing_new_deck_will_be_created(name=new_deck_name)
    return ""


def _build_context(
    col,
    csv_path: str,
    override_delimiter: int | None = None,
    override_is_html: bool | None = None,
    override_notetype_id: int | None = None,
    override_deck_id: int | None = None,
    override_dupe_resolution: int | None = None,
    override_match_scope: int | None = None,
    override_global_tags: str | None = None,
    override_updated_tags: str | None = None,
    override_field_columns: list[int] | None = None,
    override_tags_column: int | None = None,
    error_msg: str | None = None,
    info_msg: str | None = None,
) -> dict[str, Any]:
    req = _metadata_request(
        csv_path,
        override_delimiter,
        override_is_html,
        override_notetype_id,
        override_deck_id,
    )

    meta = col._backend.get_csv_metadata(req)

    # Apply overrides that are not in CsvMetadataRequest
    dupe_resolution = (
        override_dupe_resolution
        if override_dupe_resolution is not None
        else meta.dupe_resolution
    )
    match_scope = (
        override_match_scope if override_match_scope is not None else meta.match_scope
    )
    global_tags = (
        override_global_tags
        if override_global_tags is not None
        else " ".join(meta.global_tags)
    )
    updated_tags = (
        override_updated_tags
        if override_updated_tags is not None
        else " ".join(meta.updated_tags)
    )
    tags_column = (
        override_tags_column if override_tags_column is not None else meta.tags_column
    )

    notetypes_raw = col.models.all_names_and_ids()
    notetypes = [{"id": n.id, "name": n.name} for n in notetypes_raw]

    decks_raw = col.decks.all_names_and_ids()
    decks = [{"id": d.id, "name": d.name} for d in decks_raw]

    new_deck_name = _new_deck_name(meta, decks)
    selected_deck_id = _selected_deck_id(meta, decks, override_deck_id, new_deck_name)
    selected_notetype_id = _selected_notetype(meta, notetypes, override_notetype_id)

    # Get model fields
    model = col.models.get(selected_notetype_id)
    field_names = [f["name"] for f in model["flds"]] if model else []

    field_columns = _field_columns(meta, field_names, override_field_columns)

    column_options = _make_column_options(meta)

    # Delimiter choices
    delimiter_choices = [
        {"value": ie.CsvMetadata.Delimiter.TAB, "label": tr.importing_tab()},
        {"value": ie.CsvMetadata.Delimiter.PIPE, "label": tr.importing_pipe()},
        {
            "value": ie.CsvMetadata.Delimiter.SEMICOLON,
            "label": tr.importing_semicolon(),
        },
        {"value": ie.CsvMetadata.Delimiter.COLON, "label": tr.importing_colon()},
        {"value": ie.CsvMetadata.Delimiter.COMMA, "label": tr.importing_comma()},
        {"value": ie.CsvMetadata.Delimiter.SPACE, "label": tr.studying_space()},
    ]

    dupe_resolution_choices = [
        {"value": ie.CsvMetadata.DupeResolution.UPDATE, "label": tr.importing_update()},
        {
            "value": ie.CsvMetadata.DupeResolution.PRESERVE,
            "label": tr.importing_preserve(),
        },
        {
            "value": ie.CsvMetadata.DupeResolution.DUPLICATE,
            "label": tr.importing_duplicate(),
        },
    ]

    match_scope_choices = [
        {"value": ie.CsvMetadata.MatchScope.NOTETYPE, "label": tr.notetypes_notetype()},
        {
            "value": ie.CsvMetadata.MatchScope.NOTETYPE_AND_DECK,
            "label": tr.importing_notetype_and_deck(),
        },
    ]

    # Previews
    preview_headers = [opt["short_label"] or opt["label"] for opt in column_options[1:]]
    preview_rows = [list(r.vals) for r in meta.preview]

    # Help items
    help_dict = {
        "file": {
            "title": tr.importing_file(),
            "sections": [
                {
                    "title": tr.importing_field_separator(),
                    "content": tr.importing_field_separator_help(),
                },
                {
                    "title": tr.importing_allow_html_in_fields(),
                    "content": tr.importing_allow_html_in_fields_help(),
                },
            ],
        },
        "import_options": {
            "title": tr.importing_import_options(),
            "sections": [
                {
                    "title": tr.notetypes_notetype(),
                    "content": tr.importing_notetype_help(),
                },
                {"title": tr.decks_deck(), "content": tr.importing_deck_help()},
                {
                    "title": tr.importing_existing_notes(),
                    "content": tr.importing_existing_notes_help(),
                },
                {
                    "title": tr.importing_match_scope(),
                    "content": tr.importing_match_scope_help(),
                },
                {
                    "title": tr.importing_tag_all_notes(),
                    "content": tr.importing_tag_all_notes_help(),
                },
                {
                    "title": tr.importing_tag_updated_notes(),
                    "content": tr.importing_tag_updated_notes_help(),
                },
            ],
        },
    }

    field_rows = _field_rows(field_names, field_columns, column_options)

    # Signals
    signals = {
        "csv_path": csv_path,
        "delimiter": meta.delimiter,
        "is_html": meta.is_html,
        "notetype_id": selected_notetype_id,
        "deck_id": selected_deck_id,
        "dupe_resolution": dupe_resolution,
        "match_scope": match_scope,
        "global_tags": global_tags,
        "updated_tags": updated_tags,
        "tags_column": tags_column,
        "active_help": "",
    }
    for idx, col_idx in enumerate(field_columns):
        signals[f"field_col_{idx}"] = col_idx

    new_deck_warning = _new_deck_warning(new_deck_name, selected_deck_id)

    filename = Path(csv_path).name

    return {
        "csv_path": csv_path,
        "filename": filename,
        "meta": meta,
        "delimiter": meta.delimiter,
        "force_delimiter": meta.force_delimiter,
        "delimiter_choices": delimiter_choices,
        "is_html": meta.is_html,
        "force_is_html": meta.force_is_html,
        "notetypes": notetypes,
        "selected_notetype_id": selected_notetype_id,
        "decks": decks,
        "selected_deck_id": selected_deck_id,
        "new_deck_name": new_deck_name,
        "new_deck_warning": new_deck_warning,
        "dupe_resolution": dupe_resolution,
        "dupe_resolution_choices": dupe_resolution_choices,
        "match_scope": match_scope,
        "match_scope_choices": match_scope_choices,
        "global_tags": global_tags,
        "updated_tags": updated_tags,
        "tags_column": tags_column,
        "column_options": column_options,
        "field_rows": field_rows,
        "preview_headers": preview_headers,
        "preview_rows": preview_rows,
        "help_dict": help_dict,
        "initial_signals_json": json.dumps(signals),
        "error_msg": error_msg,
        "info_msg": info_msg,
    }


def _first_field_detail(
    note: ie.ImportResponse.Note, dupe_resolution: int
) -> dict[str, Any]:
    if dupe_resolution == ie.CsvMetadata.DupeResolution.DUPLICATE:
        status = tr.adding_added()
        reason = tr.importing_duplicate_note_added()
    elif dupe_resolution == ie.CsvMetadata.DupeResolution.PRESERVE:
        status = tr.importing_skipped()
        reason = tr.importing_existing_note_skipped()
    else:
        status = tr.importing_updated()
        reason = tr.importing_note_updated_as_file_had_newer()
    return {
        "status": status,
        "reason": reason,
        "fields": ", ".join(note.fields),
        "nid": note.id.nid,
        "can_browse": True,
    }


def _append_failed_details(
    details: list[dict[str, Any]],
    conflicting: list[ie.ImportResponse.Note],
    missing_notetype: list[ie.ImportResponse.Note],
    missing_deck: list[ie.ImportResponse.Note],
    empty_first_field: list[ie.ImportResponse.Note],
) -> None:
    for n in conflicting:
        details.append(
            {
                "status": tr.importing_skipped(),
                "reason": tr.importing_note_skipped_update_due_to_notetype2(),
                "fields": ", ".join(n.fields),
                "nid": n.id.nid,
                "can_browse": False,
            }
        )
    for n in missing_notetype:
        details.append(
            {
                "status": tr.importing_skipped(),
                "reason": tr.importing_note_skipped_due_to_missing_notetype(),
                "fields": ", ".join(n.fields),
                "nid": n.id.nid,
                "can_browse": False,
            }
        )
    for n in missing_deck:
        details.append(
            {
                "status": tr.importing_skipped(),
                "reason": tr.importing_note_skipped_due_to_missing_deck(),
                "fields": ", ".join(n.fields),
                "nid": n.id.nid,
                "can_browse": False,
            }
        )
    for n in empty_first_field:
        details.append(
            {
                "status": tr.importing_skipped(),
                "reason": tr.importing_note_skipped_due_to_empty_first_field(),
                "fields": ", ".join(n.fields),
                "nid": n.id.nid,
                "can_browse": False,
            }
        )


def _process_import_log(resp: ie.ImportResponse) -> dict[str, Any]:
    log = resp.log

    added_notes = list(log.new)
    updated_notes = list(log.updated)
    skipped_notes = list(log.duplicate)
    first_field_notes = list(log.first_field_match)

    conflicting = list(log.conflicting)
    missing_notetype = list(log.missing_notetype)
    missing_deck = list(log.missing_deck)
    empty_first_field = list(log.empty_first_field)

    failed_notes = conflicting + missing_notetype + missing_deck + empty_first_field

    # Depending on dupeResolution, first_field_match belongs to updated, duplicate, or added
    if log.dupe_resolution == ie.CsvMetadata.DupeResolution.DUPLICATE:
        added_notes.extend(first_field_notes)
    elif log.dupe_resolution == ie.CsvMetadata.DupeResolution.PRESERVE:
        skipped_notes.extend(first_field_notes)
    else:  # UPDATE
        updated_notes.extend(first_field_notes)

    details: list[dict[str, Any]] = []

    for n in log.new:
        details.append(
            {
                "status": tr.adding_added(),
                "reason": tr.importing_added_new_note(),
                "fields": ", ".join(n.fields),
                "nid": n.id.nid,
                "can_browse": True,
            }
        )
    for n in log.updated:
        details.append(
            {
                "status": tr.importing_updated(),
                "reason": tr.importing_note_updated_as_file_had_newer(),
                "fields": ", ".join(n.fields),
                "nid": n.id.nid,
                "can_browse": True,
            }
        )
    for n in log.duplicate:
        details.append(
            {
                "status": tr.importing_skipped(),
                "reason": tr.importing_existing_note_skipped(),
                "fields": ", ".join(n.fields),
                "nid": n.id.nid,
                "can_browse": True,
            }
        )
    for n in first_field_notes:
        details.append(_first_field_detail(n, log.dupe_resolution))

    _append_failed_details(
        details, conflicting, missing_notetype, missing_deck, empty_first_field
    )

    total_found = log.found_notes

    return {
        "found_notes": total_found,
        "found_notes_text": tr.importing_notes_found_in_file2(notes=total_found),
        "added_count": len(added_notes),
        "added_text": tr.importing_notes_added(count=len(added_notes))
        if added_notes
        else "",
        "updated_count": len(updated_notes),
        "updated_text": tr.importing_notes_updated(count=len(updated_notes))
        if updated_notes
        else "",
        "skipped_count": len(skipped_notes),
        "skipped_text": tr.importing_existing_notes_skipped(count=len(skipped_notes))
        if skipped_notes
        else "",
        "failed_count": len(failed_notes),
        "failed_text": tr.importing_notes_failed(count=len(failed_notes))
        if failed_notes
        else "",
        "details": details,
    }


def render_import_csv_html(col, csv_path: str, **kwargs) -> str:
    ctx = _build_context(col, csv_path=csv_path, **kwargs)
    return templating.render("pages/import_csv.html.jinja", **ctx)


def render_import_csv_result_html(result: dict[str, Any], filename: str) -> str:
    return templating.render(
        "pages/import_csv_result.html.jinja",
        result=result,
        filename=filename,
    )


async def _csv_page(get_service: Callable, path: str) -> HTMLResponse:
    service = get_service()
    if not path.startswith("/"):
        path = "/" + path

    if not import_tmp.is_within(service.settings, path):
        err_html = (
            f'<div class="alert alert-error m-4">Import path not allowed: {path}</div>'
        )
        return HTMLResponse(render_page("importcsv", err_html))

    def render(col):
        return render_import_csv_html(col, path)

    try:
        body = await service.run(render)
    except Exception as e:
        logger.exception("Failed to render import-csv page")
        err_html = f'<div class="alert alert-error m-4">Failed to load CSV: {e}</div>'
        return HTMLResponse(render_page("importcsv", err_html))

    return HTMLResponse(render_page("importcsv", body))


async def _update_csv_options(
    get_service: Callable, payload: ReadSignals
) -> DatastarResponse:
    service = get_service()
    if not payload or not isinstance(payload, dict):
        return DatastarResponse()
    payload_data: dict[str, Any] = payload

    csv_path = payload_data.get("csv_path", "")
    if not csv_path.startswith("/"):
        csv_path = "/" + csv_path

    delimiter = int(payload_data.get("delimiter", 0))
    is_html = bool(payload_data.get("is_html"))
    notetype_id = int(payload_data.get("notetype_id", 0))
    deck_id = int(payload_data.get("deck_id", 0))
    dupe_resolution = int(payload_data.get("dupe_resolution", 0))
    match_scope = int(payload_data.get("match_scope", 0))
    global_tags = str(payload_data.get("global_tags", ""))
    updated_tags = str(payload_data.get("updated_tags", ""))
    tags_column = int(payload_data.get("tags_column", 0))

    def get_model_len(col):
        m = col.models.get(notetype_id)
        return len(m["flds"]) if m else 0

    num_fields = await service.run(get_model_len)
    field_cols = [int(payload_data.get(f"field_col_{i}", 0)) for i in range(num_fields)]

    def render(col):
        return render_import_csv_html(
            col,
            csv_path=csv_path,
            override_delimiter=delimiter,
            override_is_html=is_html,
            override_notetype_id=notetype_id,
            override_deck_id=deck_id,
            override_dupe_resolution=dupe_resolution,
            override_match_scope=match_scope,
            override_global_tags=global_tags,
            override_updated_tags=updated_tags,
            override_field_columns=field_cols,
            override_tags_column=tags_column,
        )

    html = await service.run(render)
    return DatastarResponse(SSE.patch_elements(html, selector="#import-csv-content"))


def _execute_csv_import(
    col,
    csv_path: str,
    payload_data: dict[str, Any],
    delimiter: int,
    is_html: bool,
    notetype_id: int,
    deck_id: int,
    dupe_resolution: int,
    match_scope: int,
    global_tags: list[str],
    updated_tags: list[str],
    tags_column: int,
) -> ie.ImportResponse:
    req = ie.CsvMetadataRequest(path=csv_path)
    req.delimiter = cast(ie.CsvMetadata.Delimiter.ValueType, delimiter)
    req.is_html = is_html
    req.notetype_id = notetype_id
    if deck_id != 0:
        req.deck_id = deck_id

    meta = col._backend.get_csv_metadata(req)
    m = col.models.get(notetype_id)
    num_fields = len(m["flds"]) if m else 0
    field_cols = [int(payload_data.get(f"field_col_{i}", 0)) for i in range(num_fields)]

    meta.dupe_resolution = dupe_resolution
    meta.match_scope = match_scope
    meta.tags_column = tags_column
    del meta.global_tags[:]
    meta.global_tags.extend(global_tags)
    del meta.updated_tags[:]
    meta.updated_tags.extend(updated_tags)

    if meta.WhichOneof("notetype") == "global_notetype":
        del meta.global_notetype.field_columns[:]
        meta.global_notetype.field_columns.extend(field_cols)

    if deck_id != 0:
        meta.deck_id = deck_id
    elif meta.deck_name:
        # keep meta.deck_name as is
        pass

    # Clear preview to mirror SvelteKit doImport behavior
    del meta.preview[:]
    return col._backend.import_csv(path=csv_path, metadata=meta)


async def _submit_csv_import(
    get_service: Callable, payload: ReadSignals
) -> DatastarResponse:
    service = get_service()
    if not payload or not isinstance(payload, dict):
        return DatastarResponse()
    payload_data: dict[str, Any] = payload

    csv_path = payload_data.get("csv_path", "")
    if not csv_path.startswith("/"):
        csv_path = "/" + csv_path

    if not import_tmp.is_within(service.settings, csv_path):
        err_html = '<div class="alert alert-error m-3">Import path not allowed</div>'
        return DatastarResponse(
            SSE.patch_elements(err_html, selector="#import-alert-area")
        )

    delimiter = int(payload_data.get("delimiter", 0))
    is_html = bool(payload_data.get("is_html"))
    notetype_id = int(payload_data.get("notetype_id", 0))
    deck_id = int(payload_data.get("deck_id", 0))
    dupe_resolution = int(payload_data.get("dupe_resolution", 0))
    match_scope = int(payload_data.get("match_scope", 0))
    global_tags = str(payload_data.get("global_tags", "")).strip().split()
    updated_tags = str(payload_data.get("updated_tags", "")).strip().split()
    tags_column = int(payload_data.get("tags_column", 0))

    def do_import(col):
        return _execute_csv_import(
            col,
            csv_path,
            payload_data,
            delimiter,
            is_html,
            notetype_id,
            deck_id,
            dupe_resolution,
            match_scope,
            global_tags,
            updated_tags,
            tags_column,
        )

    try:
        resp = await service.run_op(do_import, initiator="import_csv")
        res_data = _process_import_log(resp)
        html = render_import_csv_result_html(res_data, filename=Path(csv_path).name)
        return DatastarResponse(
            SSE.patch_elements(html, selector="#import-csv-content")
        )
    except Exception as e:
        logger.exception("CSV import failed")
        err_html = f'<div class="alert alert-error m-3">Import failed: {e}</div>'
        return DatastarResponse(
            SSE.patch_elements(err_html, selector="#import-alert-area")
        )


def make_router(get_service: Callable) -> APIRouter:
    router = APIRouter()

    @router.get("/import-csv/{path:path}")
    async def page(path: str):
        return await _csv_page(get_service, path)

    @router.post("/import-csv/update-options")
    async def update_options(payload: ReadSignals):
        return await _update_csv_options(get_service, payload)

    @router.post("/import-csv/submit")
    async def submit_import(payload: ReadSignals):
        return await _submit_csv_import(get_service, payload)

    return router
