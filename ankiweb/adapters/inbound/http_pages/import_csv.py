from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from datastar_py.fastapi import (
    DatastarResponse,
    ServerSentEventGenerator as SSE,
    ReadSignals,
)

from ankiweb.core.i18n import tr
from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.adapters.inbound.http_shared.page import render_page
import anki.import_export_pb2 as ie
from ankiweb import import_tmp

logger = logging.getLogger(__name__)


def _make_column_options(meta: ie.CsvMetadata) -> list[dict[str, Any]]:
    deck_col = meta.deck_column if meta.WhichOneof("deck") == "deck_column" else None
    notetype_col = meta.notetype_column if meta.WhichOneof("notetype") == "notetype_column" else None

    options = [
        {"value": 0, "label": tr.change_notetype_nothing(), "short_label": None, "disabled": False}
    ]

    preview_first_row = list(meta.preview[0].vals) if meta.preview else []

    for idx, col_label in enumerate(meta.column_labels, start=1):
        if idx == notetype_col:
            label = f"{idx}: {tr.notetypes_notetype()}"
            options.append({"value": idx, "label": label, "short_label": None, "disabled": True})
        elif idx == deck_col:
            label = f"{idx}: {tr.decks_deck()}"
            options.append({"value": idx, "label": label, "short_label": None, "disabled": True})
        elif idx == meta.guid_column:
            label = f"{idx}: GUID"
            options.append({"value": idx, "label": label, "short_label": None, "disabled": True})
        elif not col_label:
            val_text = preview_first_row[idx - 1] if idx - 1 < len(preview_first_row) else ""
            label = f"{idx}: {val_text}" if val_text else str(idx)
            options.append({"value": idx, "label": label, "short_label": str(idx), "disabled": False})
        else:
            label = f"{idx}: {col_label}"
            options.append({"value": idx, "label": label, "short_label": None, "disabled": False})

    return options


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
    req = ie.CsvMetadataRequest(path=csv_path)
    if override_delimiter is not None:
        req.delimiter = override_delimiter
    if override_is_html is not None:
        req.is_html = override_is_html
    if override_notetype_id is not None:
        req.notetype_id = override_notetype_id
    if override_deck_id is not None:
        req.deck_id = override_deck_id

    meta = col._backend.get_csv_metadata(req)

    # Apply overrides that are not in CsvMetadataRequest
    dupe_resolution = (
        override_dupe_resolution if override_dupe_resolution is not None else meta.dupe_resolution
    )
    match_scope = (
        override_match_scope if override_match_scope is not None else meta.match_scope
    )
    global_tags = (
        override_global_tags if override_global_tags is not None else " ".join(meta.global_tags)
    )
    updated_tags = (
        override_updated_tags if override_updated_tags is not None else " ".join(meta.updated_tags)
    )
    tags_column = (
        override_tags_column if override_tags_column is not None else meta.tags_column
    )

    notetypes_raw = col.models.all_names_and_ids()
    notetypes = [{"id": n.id, "name": n.name} for n in notetypes_raw]

    decks_raw = col.decks.all_names_and_ids()
    decks = [{"id": d.id, "name": d.name} for d in decks_raw]

    new_deck_name = meta.deck_name if meta.WhichOneof("deck") == "deck_name" else ""
    if new_deck_name:
        decks.append({"id": 0, "name": new_deck_name})

    selected_deck_id = (
        override_deck_id
        if override_deck_id is not None
        else (0 if new_deck_name else (meta.deck_id or (decks[0]["id"] if decks else 1)))
    )

    selected_notetype_id = (
        override_notetype_id
        if override_notetype_id is not None
        else (meta.global_notetype.id if meta.WhichOneof("notetype") == "global_notetype" else (notetypes[0]["id"] if notetypes else 0))
    )

    # Get model fields
    model = col.models.get(selected_notetype_id)
    field_names = [f["name"] for f in model["flds"]] if model else []

    if override_field_columns is not None and len(override_field_columns) == len(field_names):
        field_columns = override_field_columns
    else:
        field_columns = list(meta.global_notetype.field_columns) if meta.WhichOneof("notetype") == "global_notetype" else []
        while len(field_columns) < len(field_names):
            field_columns.append(0)

    column_options = _make_column_options(meta)

    # Delimiter choices
    delimiter_choices = [
        {"value": ie.CsvMetadata.Delimiter.TAB, "label": tr.importing_tab()},
        {"value": ie.CsvMetadata.Delimiter.PIPE, "label": tr.importing_pipe()},
        {"value": ie.CsvMetadata.Delimiter.SEMICOLON, "label": tr.importing_semicolon()},
        {"value": ie.CsvMetadata.Delimiter.COLON, "label": tr.importing_colon()},
        {"value": ie.CsvMetadata.Delimiter.COMMA, "label": tr.importing_comma()},
        {"value": ie.CsvMetadata.Delimiter.SPACE, "label": tr.studying_space()},
    ]

    dupe_resolution_choices = [
        {"value": ie.CsvMetadata.DupeResolution.UPDATE, "label": tr.importing_update()},
        {"value": ie.CsvMetadata.DupeResolution.PRESERVE, "label": tr.importing_preserve()},
        {"value": ie.CsvMetadata.DupeResolution.DUPLICATE, "label": tr.importing_duplicate()},
    ]

    match_scope_choices = [
        {"value": ie.CsvMetadata.MatchScope.NOTETYPE, "label": tr.notetypes_notetype()},
        {"value": ie.CsvMetadata.MatchScope.NOTETYPE_AND_DECK, "label": tr.importing_notetype_and_deck()},
    ]

    # Previews
    preview_headers = [opt["short_label"] or opt["label"] for opt in column_options[1:]]
    preview_rows = [list(r.vals) for r in meta.preview]

    # Help items
    help_dict = {
        "file": {
            "title": tr.importing_file(),
            "sections": [
                {"title": tr.importing_field_separator(), "content": tr.importing_field_separator_help()},
                {"title": tr.importing_allow_html_in_fields(), "content": tr.importing_allow_html_in_fields_help()},
            ],
        },
        "import_options": {
            "title": tr.importing_import_options(),
            "sections": [
                {"title": tr.notetypes_notetype(), "content": tr.importing_notetype_help()},
                {"title": tr.decks_deck(), "content": tr.importing_deck_help()},
                {"title": tr.importing_existing_notes(), "content": tr.importing_existing_notes_help()},
                {"title": tr.importing_match_scope(), "content": tr.importing_match_scope_help()},
                {"title": tr.importing_tag_all_notes(), "content": tr.importing_tag_all_notes_help()},
                {"title": tr.importing_tag_updated_notes(), "content": tr.importing_tag_updated_notes_help()},
            ],
        },
    }

    field_rows = []
    for idx, name in enumerate(field_names):
        col_idx = field_columns[idx] if idx < len(field_columns) else 0
        field_rows.append({
            "index": idx,
            "name": name,
            "selected_column": col_idx,
            "options": column_options[1:] if idx == 0 else column_options,
        })

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

    new_deck_warning = (
        tr.importing_new_deck_will_be_created(name=new_deck_name)
        if (new_deck_name and selected_deck_id == 0)
        else ""
    )

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
        details.append({
            "status": tr.adding_added(),
            "reason": tr.importing_added_new_note(),
            "fields": ", ".join(n.fields),
            "nid": n.id.nid,
            "can_browse": True,
        })
    for n in log.updated:
        details.append({
            "status": tr.importing_updated(),
            "reason": tr.importing_note_updated_as_file_had_newer(),
            "fields": ", ".join(n.fields),
            "nid": n.id.nid,
            "can_browse": True,
        })
    for n in log.duplicate:
        details.append({
            "status": tr.importing_skipped(),
            "reason": tr.importing_existing_note_skipped(),
            "fields": ", ".join(n.fields),
            "nid": n.id.nid,
            "can_browse": True,
        })
    for n in first_field_notes:
        if log.dupe_resolution == ie.CsvMetadata.DupeResolution.DUPLICATE:
            details.append({
                "status": tr.adding_added(),
                "reason": tr.importing_duplicate_note_added(),
                "fields": ", ".join(n.fields),
                "nid": n.id.nid,
                "can_browse": True,
            })
        elif log.dupe_resolution == ie.CsvMetadata.DupeResolution.PRESERVE:
            details.append({
                "status": tr.importing_skipped(),
                "reason": tr.importing_existing_note_skipped(),
                "fields": ", ".join(n.fields),
                "nid": n.id.nid,
                "can_browse": True,
            })
        else:
            details.append({
                "status": tr.importing_updated(),
                "reason": tr.importing_note_updated_as_file_had_newer(),
                "fields": ", ".join(n.fields),
                "nid": n.id.nid,
                "can_browse": True,
            })

    for n in conflicting:
        details.append({
            "status": tr.importing_skipped(),
            "reason": tr.importing_note_skipped_update_due_to_notetype2(),
            "fields": ", ".join(n.fields),
            "nid": n.id.nid,
            "can_browse": False,
        })
    for n in missing_notetype:
        details.append({
            "status": tr.importing_skipped(),
            "reason": tr.importing_note_skipped_due_to_missing_notetype(),
            "fields": ", ".join(n.fields),
            "nid": n.id.nid,
            "can_browse": False,
        })
    for n in missing_deck:
        details.append({
            "status": tr.importing_skipped(),
            "reason": tr.importing_note_skipped_due_to_missing_deck(),
            "fields": ", ".join(n.fields),
            "nid": n.id.nid,
            "can_browse": False,
        })
    for n in empty_first_field:
        details.append({
            "status": tr.importing_skipped(),
            "reason": tr.importing_note_skipped_due_to_empty_first_field(),
            "fields": ", ".join(n.fields),
            "nid": n.id.nid,
            "can_browse": False,
        })

    total_found = log.found_notes

    return {
        "found_notes": total_found,
        "found_notes_text": tr.importing_notes_found_in_file2(notes=total_found),
        "added_count": len(added_notes),
        "added_text": tr.importing_notes_added(count=len(added_notes)) if added_notes else "",
        "updated_count": len(updated_notes),
        "updated_text": tr.importing_notes_updated(count=len(updated_notes)) if updated_notes else "",
        "skipped_count": len(skipped_notes),
        "skipped_text": tr.importing_existing_notes_skipped(count=len(skipped_notes)) if skipped_notes else "",
        "failed_count": len(failed_notes),
        "failed_text": tr.importing_notes_failed(count=len(failed_notes)) if failed_notes else "",
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


def make_router(get_service: Callable) -> APIRouter:
    router = APIRouter()

    @router.get("/import-csv/{path:path}")
    async def page(path: str):
        service = get_service()
        if not path.startswith("/"):
            path = "/" + path

        if not import_tmp.is_within(service.settings, path):
            err_html = f'<div class="alert alert-error m-4">Import path not allowed: {path}</div>'
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

    @router.post("/import-csv/update-options")
    async def update_options(payload: ReadSignals):
        service = get_service()
        if not payload or not isinstance(payload, dict):
            return DatastarResponse()

        csv_path = payload.get("csv_path", "")
        if not csv_path.startswith("/"):
            csv_path = "/" + csv_path

        delimiter = int(payload.get("delimiter", 0))
        is_html = bool(payload.get("is_html", False))
        notetype_id = int(payload.get("notetype_id", 0))
        deck_id = int(payload.get("deck_id", 0))
        dupe_resolution = int(payload.get("dupe_resolution", 0))
        match_scope = int(payload.get("match_scope", 0))
        global_tags = str(payload.get("global_tags", ""))
        updated_tags = str(payload.get("updated_tags", ""))
        tags_column = int(payload.get("tags_column", 0))

        # Collect field columns
        def get_model_len(col):
            m = col.models.get(notetype_id)
            return len(m["flds"]) if m else 0

        num_fields = await service.run(get_model_len)
        field_cols = [int(payload.get(f"field_col_{i}", 0)) for i in range(num_fields)]

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

    @router.post("/import-csv/submit")
    async def submit_import(payload: ReadSignals):
        service = get_service()
        if not payload or not isinstance(payload, dict):
            return DatastarResponse()

        csv_path = payload.get("csv_path", "")
        if not csv_path.startswith("/"):
            csv_path = "/" + csv_path

        if not import_tmp.is_within(service.settings, csv_path):
            err_html = '<div class="alert alert-error m-3">Import path not allowed</div>'
            return DatastarResponse(SSE.patch_elements(err_html, selector="#import-alert-area"))

        delimiter = int(payload.get("delimiter", 0))
        is_html = bool(payload.get("is_html", False))
        notetype_id = int(payload.get("notetype_id", 0))
        deck_id = int(payload.get("deck_id", 0))
        dupe_resolution = int(payload.get("dupe_resolution", 0))
        match_scope = int(payload.get("match_scope", 0))
        global_tags = str(payload.get("global_tags", "")).strip().split()
        updated_tags = str(payload.get("updated_tags", "")).strip().split()
        tags_column = int(payload.get("tags_column", 0))

        def do_import(col):
            req = ie.CsvMetadataRequest(path=csv_path)
            req.delimiter = delimiter
            req.is_html = is_html
            req.notetype_id = notetype_id
            if deck_id != 0:
                req.deck_id = deck_id

            meta = col._backend.get_csv_metadata(req)

            m = col.models.get(notetype_id)
            num_fields = len(m["flds"]) if m else 0
            field_cols = [int(payload.get(f"field_col_{i}", 0)) for i in range(num_fields)]

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

            resp = col._backend.import_csv(path=csv_path, metadata=meta)
            return resp

        try:
            resp = await service.run_op(do_import, initiator="import_csv")
            res_data = _process_import_log(resp)
            html = render_import_csv_result_html(res_data, filename=Path(csv_path).name)
            return DatastarResponse(SSE.patch_elements(html, selector="#import-csv-content"))
        except Exception as e:
            logger.exception("CSV import failed")
            err_html = f'<div class="alert alert-error m-3">Import failed: {e}</div>'
            return DatastarResponse(SSE.patch_elements(err_html, selector="#import-alert-area"))

    return router
