from __future__ import annotations

import logging
import os
import urllib.parse
from collections.abc import Callable
from typing import Any, cast

import anki.errors
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

HELP_URL_ROOT = "https://docs.ankiweb.net/importing/packaged-decks.html"
HELP_URL_SCHEDULING = "https://docs.ankiweb.net/importing/packaged-decks.html#scheduling"
HELP_URL_UPDATING = "https://docs.ankiweb.net/importing/packaged-decks.html#updating"


def _help_sections() -> list[dict[str, Any]]:
    return [
        {
            "title": tr.importing_also_import_progress(),
            "help": tr.importing_include_reviews_help(),
            "url": HELP_URL_SCHEDULING,
        },
        {
            "title": tr.importing_with_deck_configs(),
            "help": tr.importing_with_deck_configs_help(),
            "url": HELP_URL_SCHEDULING,
        },
        {
            "title": tr.importing_merge_notetypes(),
            "help": tr.importing_merge_notetypes_help(),
            "url": HELP_URL_UPDATING,
        },
        {
            "title": tr.importing_update_notes(),
            "help": tr.importing_update_notes_help(),
            "url": HELP_URL_UPDATING,
        },
        {
            "title": tr.importing_update_notetypes(),
            "help": tr.importing_update_notetypes_help(),
            "url": HELP_URL_UPDATING,
        },
    ]


def _update_choices() -> list[dict[str, Any]]:
    return [
        {"label": tr.importing_update_if_newer(), "value": 0},
        {"label": tr.importing_update_always(), "value": 1},
        {"label": tr.importing_update_never(), "value": 2},
    ]


def _build_log_summary_and_rows(log: ie.ImportResponse.Log) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build the summaries and details table rows from protobuf ImportResponse.Log.
    Matches upstream ts/routes/import-page/ logic exactly:
    - new notes: action = tr.adding_added(), reason = tr.importing_added_new_note(), can_browse = True
    - duplicate notes: action = tr.importing_skipped(), reason = tr.importing_existing_note_skipped(), can_browse = True
    - updated notes: action = tr.importing_updated(), reason = tr.importing_note_updated_as_file_had_newer(), can_browse = True
    - conflicting: reason = tr.importing_note_skipped_update_due_to_notetype2()
    - missing_notetype: reason = tr.importing_note_skipped_due_to_missing_notetype()
    - missing_deck: reason = tr.importing_note_skipped_due_to_missing_deck()
    - empty_first_field: reason = tr.importing_note_skipped_due_to_empty_first_field()
    - first_field_match (dupe_resolution check):
      if DUPLICATE: action = tr.importing_added(), reason = tr.importing_duplicate_note_added()
      if PRESERVE: action = tr.importing_skipped(), reason = tr.importing_existing_note_skipped()
      else: action = tr.importing_updated(), reason = tr.importing_note_updated_as_file_had_newer()
    """
    dupe_resolution = log.dupe_resolution
    first_field_notes = list(log.first_field_match)

    if dupe_resolution == 0:  # DUPLICATE
        ff_action = tr.importing_added()
        ff_reason = tr.importing_duplicate_note_added()
    elif dupe_resolution == 1:  # PRESERVE
        ff_action = tr.importing_skipped()
        ff_reason = tr.importing_existing_note_skipped()
    else:  # UPDATE
        ff_action = tr.importing_updated()
        ff_reason = tr.importing_note_updated_as_file_had_newer()

    summaries = [
        {
            "action": tr.adding_added(),
            "summary_text": tr.importing_notes_added(count=len(log.new)),
            "count": len(log.new),
            "can_browse": True,
            "icon": "newBox",
            "queues": [{"notes": list(log.new), "reason": tr.importing_added_new_note()}],
        },
        {
            "action": tr.importing_skipped(),
            "summary_text": tr.importing_existing_notes_skipped(count=len(log.duplicate)),
            "count": len(log.duplicate),
            "can_browse": True,
            "icon": "checkCircle",
            "queues": [{"notes": list(log.duplicate), "reason": tr.importing_existing_note_skipped()}],
        },
        {
            "action": tr.importing_updated(),
            "summary_text": tr.importing_notes_updated(count=len(log.updated)),
            "count": len(log.updated),
            "can_browse": True,
            "icon": "updateIcon",
            "queues": [{"notes": list(log.updated), "reason": tr.importing_note_updated_as_file_had_newer()}],
        },
        {
            "action": tr.importing_skipped(),
            "summary_text": tr.importing_notes_failed(count=(
                len(log.conflicting) + len(log.missing_notetype) + len(log.missing_deck) + len(log.empty_first_field)
            )),
            "count": (
                len(log.conflicting) + len(log.missing_notetype) + len(log.missing_deck) + len(log.empty_first_field)
            ),
            "can_browse": False,
            "icon": "closeBox",
            "queues": [
                {"notes": list(log.conflicting), "reason": tr.importing_note_skipped_update_due_to_notetype2()},
                {"notes": list(log.missing_notetype), "reason": tr.importing_note_skipped_due_to_missing_notetype()},
                {"notes": list(log.missing_deck), "reason": tr.importing_note_skipped_due_to_missing_deck()},
                {"notes": list(log.empty_first_field), "reason": tr.importing_note_skipped_due_to_empty_first_field()},
            ],
        },
    ]

    # Merge first_field_match into the matching summary
    if first_field_notes:
        for s in summaries:
            if s["action"] == ff_action:
                s["queues"].append({"notes": first_field_notes, "reason": ff_reason})
                s["count"] += len(first_field_notes)
                break
    # Compute browse_query for each summary
    for s in summaries:
        if s["can_browse"]:
            all_nids = [
                str(note.id.nid)
                for q in s["queues"]
                for note in q.get("notes", [])
                if note.id.nid
            ]
            if all_nids:
                s["browse_query"] = "nid:" + ",".join(all_nids)
            else:
                s["browse_query"] = ""
        else:
            s["browse_query"] = ""

    # Build details table rows: flat list of notes
    rows: list[dict[str, Any]] = []
    for s in summaries:
        for q in s["queues"]:
            for note in q.get("notes", []):
                fields = list(note.fields)
                rows.append({
                    "action": s["action"],
                    "reason": q.get("reason", ""),
                    "can_browse": s["can_browse"],
                    "nid": note.id.nid,
                    "fields": fields,
                    "fields_joined": ", ".join(fields),
                })

    return summaries, rows


def render_import_anki_package_html(
    package_path: str,
    options: ie.ImportAnkiPackageOptions,
    as_modal: bool = False,
) -> str:
    filename = os.path.basename(package_path.rstrip("/\\"))
    ctx = {
        "package_path": package_path,
        "filename": filename,
        "title": tr.importing_import_options(),
        "options": {
            "with_scheduling": options.with_scheduling,
            "with_deck_configs": options.with_deck_configs,
            "merge_notetypes": options.merge_notetypes,
            "update_notes": options.update_notes,
            "update_notetypes": options.update_notetypes,
        },
        "update_choices": _update_choices(),
        "help_title": tr.importing_import_options(),
        "help_url": HELP_URL_ROOT,
        "help_sections": _help_sections(),
    }
    tmpl = "pages/import_anki_package_modal.html.jinja" if as_modal else "pages/import_anki_package.html.jinja"
    return templating.render(tmpl, **ctx)


def render_import_package_modal(package_path: str, options: ie.ImportAnkiPackageOptions) -> str:
    return render_import_anki_package_html(package_path, options, as_modal=True)
def render_import_page_html(
    log: ie.ImportResponse.Log | None = None,
    error: str | None = None,
) -> str:
    if error or log is None:
        ctx = {
            "error": error or "An error occurred during import.",
            "found_notes": 0,
            "summaries": [],
            "rows": [],
        }
    else:
        summaries, rows = _build_log_summary_and_rows(log)
        ctx = {
            "error": None,
            "found_notes": log.found_notes,
            "summaries": summaries,
            "rows": rows,
        }
    return templating.render("pages/import_page.html.jinja", **ctx)


def make_router(get_service: Callable) -> APIRouter:
    router = APIRouter()

    @router.get("/import-anki-package/modal/{path:path}")
    async def import_anki_package_modal_content(path: str):
        service = get_service()
        package_path = urllib.parse.unquote(path)

        def get_options(col):
            try:
                return col._backend.get_import_anki_package_presets()
            except anki.errors.AnkiException:
                return ie.ImportAnkiPackageOptions()

        options = await service.run(get_options)
        modal_html = render_import_package_modal(package_path, options)
        return HTMLResponse(modal_html)
    @router.get("/import-anki-package/{path:path}")
    async def import_anki_package_page(path: str):
        service = get_service()
        package_path = urllib.parse.unquote(path)

        def get_options(col):
            try:
                return col._backend.get_import_anki_package_presets()
            except anki.errors.AnkiException:
                return ie.ImportAnkiPackageOptions()

        options = await service.run(get_options)
        body = render_import_anki_package_html(package_path, options)
        return HTMLResponse(render_page("import_package", body))


    @router.post("/import-anki-package/do-import")
    async def do_import(payload: ReadSignals):
        service = get_service()
        if not payload or not isinstance(payload, dict):
            return DatastarResponse()

        package_path = payload.get("package_path", "")
        with_scheduling = bool(payload.get("with_scheduling", False))
        with_deck_configs = bool(payload.get("with_deck_configs", False))
        merge_notetypes = bool(payload.get("merge_notetypes", False))
        update_notes = int(payload.get("update_notes", 0))
        update_notetypes = int(payload.get("update_notetypes", 0))

        # Check path security
        if not import_tmp.is_within(service.settings, package_path):
            error_html = render_import_page_html(error="Import path not allowed")
            return DatastarResponse(SSE.patch_elements(error_html, selector="#import-package-container"))

        req = ie.ImportAnkiPackageRequest(
            package_path=package_path,
            options=ie.ImportAnkiPackageOptions(
                with_scheduling=with_scheduling,
                with_deck_configs=with_deck_configs,
                merge_notetypes=merge_notetypes,
                update_notes=cast(ie.ImportAnkiPackageUpdateCondition.ValueType, update_notes),
                update_notetypes=cast(ie.ImportAnkiPackageUpdateCondition.ValueType, update_notetypes),
            ),
        )

        def execute_import(col):
            out_raw = col._backend.import_anki_package_raw(req.SerializeToString())
            resp = ie.ImportResponse()
            resp.ParseFromString(out_raw)
            return resp

        try:
            resp = await service.run(execute_import)
            html = render_import_page_html(log=resp.log)
        except Exception as e:
            logger.exception("Import package failed")
            html = render_import_page_html(error=str(e))

        return DatastarResponse(SSE.patch_elements(html, selector="#import-package-container"))

    @router.get("/import-page/{path:path}")
    async def import_page_route(path: str):
        service = get_service()
        package_path = urllib.parse.unquote(path)

        # Directly run import with default presets, matching SvelteKit import-page behaviour
        if not import_tmp.is_within(service.settings, package_path):
            body = render_import_page_html(error="Import path not allowed")
            return HTMLResponse(render_page("import_page", body))

        def execute_direct_import(col):
            opts = col._backend.get_import_anki_package_presets()
            req = ie.ImportAnkiPackageRequest(
                package_path=package_path,
                options=opts,
            )
            out_raw = col._backend.import_anki_package_raw(req.SerializeToString())
            resp = ie.ImportResponse()
            resp.ParseFromString(out_raw)
            return resp

        try:
            resp = await service.run(execute_direct_import)
            body = render_import_page_html(log=resp.log)
        except Exception as e:
            logger.exception("Direct import failed")
            body = render_import_page_html(error=str(e))

        return HTMLResponse(render_page("import_page", body))

    return router
