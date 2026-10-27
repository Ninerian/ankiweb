from __future__ import annotations

import asyncio
import logging
import os
import urllib.parse
from collections.abc import AsyncGenerator, Callable
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict, cast

import anki.collection_pb2 as col_pb
import anki.errors
import anki.import_export_pb2 as ie
import anyio
from datastar_py.fastapi import (
    DatastarResponse,
    ReadSignals,
)
from datastar_py.fastapi import (
    ServerSentEventGenerator as SSE,
)
from datastar_py.sse import DatastarEvent
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from ankiweb import import_tmp
from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.adapters.inbound.http_shared.page import render_page
from ankiweb.core.i18n import tr

if TYPE_CHECKING:
    from anki.collection import Collection

    from ankiweb.core.ports import CollectionPort

logger = logging.getLogger(__name__)

HELP_URL_ROOT = "https://docs.ankiweb.net/importing/packaged-decks.html"
HELP_URL_SCHEDULING = (
    "https://docs.ankiweb.net/importing/packaged-decks.html#scheduling"
)
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


class _SummaryQueue(TypedDict):
    notes: list[ie.ImportResponse.Note]
    reason: str


class _SummaryItem(TypedDict):
    action: str
    summary_text: str
    count: int
    can_browse: bool
    icon: str
    queues: list[_SummaryQueue]
    browse_query: NotRequired[str]


class _DetailRow(TypedDict):
    action: str
    reason: str
    can_browse: bool
    nid: int
    fields: list[str]
    fields_joined: str


def _merge_first_field_summary(
    summaries: list[_SummaryItem],
    notes: list[ie.ImportResponse.Note],
    action: str,
    reason: str,
) -> None:
    if notes:
        for summary in summaries:
            if summary["action"] == action:
                summary["queues"].append({"notes": notes, "reason": reason})
                summary["count"] += len(notes)
                break


def _set_browse_queries(summaries: list[_SummaryItem]) -> None:
    for summary in summaries:
        if not summary["can_browse"]:
            summary["browse_query"] = ""
            continue
        all_nids = [
            str(note.id.nid)
            for queue in summary["queues"]
            for note in queue["notes"]
            if note.id.nid
        ]
        summary["browse_query"] = "nid:" + ",".join(all_nids) if all_nids else ""


def _summary_detail_rows(summaries: list[_SummaryItem]) -> list[_DetailRow]:
    rows: list[_DetailRow] = []
    for summary in summaries:
        for queue in summary["queues"]:
            for note in queue["notes"]:
                fields = list(note.fields)
                rows.append(
                    {
                        "action": summary["action"],
                        "reason": queue["reason"],
                        "can_browse": summary["can_browse"],
                        "nid": note.id.nid,
                        "fields": fields,
                        "fields_joined": ", ".join(fields),
                    }
                )
    return rows


def _build_log_summary_and_rows(
    log: ie.ImportResponse.Log,
) -> tuple[list[_SummaryItem], list[_DetailRow]]:
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

    summaries: list[_SummaryItem] = [
        {
            "action": tr.adding_added(),
            "summary_text": tr.importing_notes_added(count=len(log.new)),
            "count": len(log.new),
            "can_browse": True,
            "icon": "newBox",
            "queues": [
                {"notes": list(log.new), "reason": tr.importing_added_new_note()}
            ],
        },
        {
            "action": tr.importing_skipped(),
            "summary_text": tr.importing_existing_notes_skipped(
                count=len(log.duplicate)
            ),
            "count": len(log.duplicate),
            "can_browse": True,
            "icon": "checkCircle",
            "queues": [
                {
                    "notes": list(log.duplicate),
                    "reason": tr.importing_existing_note_skipped(),
                }
            ],
        },
        {
            "action": tr.importing_updated(),
            "summary_text": tr.importing_notes_updated(count=len(log.updated)),
            "count": len(log.updated),
            "can_browse": True,
            "icon": "updateIcon",
            "queues": [
                {
                    "notes": list(log.updated),
                    "reason": tr.importing_note_updated_as_file_had_newer(),
                }
            ],
        },
        {
            "action": tr.importing_skipped(),
            "summary_text": tr.importing_notes_failed(
                count=(
                    len(log.conflicting)
                    + len(log.missing_notetype)
                    + len(log.missing_deck)
                    + len(log.empty_first_field)
                )
            ),
            "count": (
                len(log.conflicting)
                + len(log.missing_notetype)
                + len(log.missing_deck)
                + len(log.empty_first_field)
            ),
            "can_browse": False,
            "icon": "closeBox",
            "queues": [
                {
                    "notes": list(log.conflicting),
                    "reason": tr.importing_note_skipped_update_due_to_notetype2(),
                },
                {
                    "notes": list(log.missing_notetype),
                    "reason": tr.importing_note_skipped_due_to_missing_notetype(),
                },
                {
                    "notes": list(log.missing_deck),
                    "reason": tr.importing_note_skipped_due_to_missing_deck(),
                },
                {
                    "notes": list(log.empty_first_field),
                    "reason": tr.importing_note_skipped_due_to_empty_first_field(),
                },
            ],
        },
    ]

    _merge_first_field_summary(summaries, first_field_notes, ff_action, ff_reason)
    _set_browse_queries(summaries)
    return summaries, _summary_detail_rows(summaries)


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
    tmpl = (
        "pages/import_anki_package_modal.html.jinja"
        if as_modal
        else "pages/import_anki_package.html.jinja"
    )
    return templating.render(tmpl, **ctx)


def render_import_package_modal(
    package_path: str, options: ie.ImportAnkiPackageOptions
) -> str:
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


def _package_presets(col) -> ie.ImportAnkiPackageOptions:
    try:
        return col._backend.get_import_anki_package_presets()
    except anki.errors.AnkiException:
        return ie.ImportAnkiPackageOptions()


async def _package_modal(get_service: Callable, path: str) -> HTMLResponse:
    service = get_service()
    package_path = urllib.parse.unquote(path)
    options = await service.run(_package_presets)
    modal_html = render_import_package_modal(package_path, options)
    return HTMLResponse(modal_html)


async def _package_page(get_service: Callable, path: str) -> HTMLResponse:
    service = get_service()
    package_path = urllib.parse.unquote(path)
    options = await service.run(_package_presets)
    body = render_import_anki_package_html(package_path, options)
    return HTMLResponse(render_page("import_package", body))


def _import_progress_label(raw_progress: bytes, last_label: str) -> str | None:
    progress = col_pb.Progress()
    progress.ParseFromString(raw_progress)
    if progress.WhichOneof("value") == "importing":
        label = progress.importing
        if label and label != last_label:
            return label
    return None


async def _import_package_stream(
    service: CollectionPort, execute_import: Callable[[Collection], ie.ImportResponse]
) -> AsyncGenerator[DatastarEvent, None]:
    initial_label = tr.actions_import()
    last_label = initial_label
    yield SSE.patch_signals({"importProgressLabel": initial_label})

    worker_task = asyncio.create_task(service.run(execute_import))
    worker_result_read = False
    try:
        while not worker_task.done():
            done, _ = await asyncio.wait([worker_task], timeout=0.1)
            if done:
                break
            try:
                raw_progress = await service.backend_raw_concurrent(
                    "latest_progress", b""
                )
                label = _import_progress_label(raw_progress, last_label)
                if label:
                    last_label = label
                    yield SSE.patch_signals({"importProgressLabel": label})
            except Exception:
                logger.warning("Failed to poll latest_progress", exc_info=True)

        try:
            resp = await asyncio.shield(worker_task)
            worker_result_read = True
            html = render_import_page_html(log=resp.log)
        except Exception as e:
            worker_result_read = True
            logger.exception("Import package failed")
            html = render_import_page_html(error=str(e))

        yield SSE.patch_elements(html, selector="#import-package-container")
    finally:
        with anyio.CancelScope(shield=True):
            if not worker_result_read:
                try:
                    await asyncio.shield(worker_task)
                except Exception:
                    logger.exception("Background import failed after client disconnect")


async def _do_package_import(
    get_service: Callable, payload: ReadSignals
) -> DatastarResponse:
    service = get_service()
    if not payload or not isinstance(payload, dict):
        return DatastarResponse()
    payload_data: dict[str, Any] = payload

    package_path = payload_data.get("package_path", "")
    with_scheduling = bool(payload_data.get("with_scheduling"))
    with_deck_configs = bool(payload_data.get("with_deck_configs"))
    merge_notetypes = bool(payload_data.get("merge_notetypes"))
    update_notes = int(payload_data.get("update_notes", 0))
    update_notetypes = int(payload_data.get("update_notetypes", 0))

    if not import_tmp.is_within(service.settings, package_path):
        error_html = render_import_page_html(error="Import path not allowed")
        return DatastarResponse(
            SSE.patch_elements(error_html, selector="#import-package-container")
        )

    req = ie.ImportAnkiPackageRequest(
        package_path=package_path,
        options=ie.ImportAnkiPackageOptions(
            with_scheduling=with_scheduling,
            with_deck_configs=with_deck_configs,
            merge_notetypes=merge_notetypes,
            update_notes=cast(
                ie.ImportAnkiPackageUpdateCondition.ValueType, update_notes
            ),
            update_notetypes=cast(
                ie.ImportAnkiPackageUpdateCondition.ValueType, update_notetypes
            ),
        ),
    )

    def execute_import(col):
        out_raw = col._backend.import_anki_package_raw(req.SerializeToString())
        resp = ie.ImportResponse()
        resp.ParseFromString(out_raw)
        return resp

    return DatastarResponse(_import_package_stream(service, execute_import))


async def _direct_package_import(get_service: Callable, path: str) -> HTMLResponse:
    service = get_service()
    package_path = urllib.parse.unquote(path)

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


def make_router(get_service: Callable) -> APIRouter:
    router = APIRouter()

    @router.get("/import-anki-package/modal/{path:path}")
    async def import_anki_package_modal_content(path: str):
        return await _package_modal(get_service, path)

    @router.get("/import-anki-package/{path:path}")
    async def import_anki_package_page(path: str):
        return await _package_page(get_service, path)

    @router.post("/import-anki-package/do-import")
    async def do_import(payload: ReadSignals):
        return await _do_package_import(get_service, payload)

    @router.get("/import-page/{path:path}")
    async def import_page_route(path: str):
        return await _direct_package_import(get_service, path)

    return router
