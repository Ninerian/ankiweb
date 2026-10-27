"""Image Occlusion next router and endpoints.

Serves:
  GET  /image-occlusion/{path:path}
  GET  /image-occlusion-img/{path:path}
  POST /image-occlusion/save
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path

import anki.errors
from datastar_py.fastapi import (
    DatastarResponse,
    ReadSignals,
)
from datastar_py.fastapi import (
    ServerSentEventGenerator as SSE,
)
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

from ankiweb import import_tmp
from ankiweb.adapters.inbound.http_datastar.common import signals_response
from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.adapters.inbound.http_shared.page import render_page
from ankiweb.core.i18n import tr

logger = logging.getLogger(__name__)


def _find_import_tmp(candidate: str, settings) -> Path | None:
    resolved = Path(candidate).resolve()
    if import_tmp.is_within(settings, str(resolved)) and resolved.is_file():
        try:
            os.utime(resolved, None)
        except OSError:
            pass
        return resolved
    return None


def _resolve_media(media_raw: str, rel_path: str) -> tuple[Path | None, int | None]:
    base = Path(media_raw).resolve()
    target = (base / rel_path).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None, 403
    if target.is_file():
        return target, 200
    return None, 404


async def _io_serve_io_image(service, path):
    """Serve an image from import_tmp or col.media."""

    # Check if it's within import_tmp
    resolved_tmp = await asyncio.to_thread(_find_import_tmp, path, service.settings)
    if resolved_tmp is not None:
        return FileResponse(resolved_tmp)

    # Fallback to col.media.dir()
    raw_media_dir = await service.run(lambda col: col.media.dir())

    target_path, status = await asyncio.to_thread(_resolve_media, raw_media_dir, path)
    if status == 403:
        return PlainTextResponse("forbidden", status_code=403)
    if status == 200 and target_path is not None:
        return FileResponse(target_path)
    return PlainTextResponse("not found", status_code=404)


def _occlusion_shapes(note_pb, hide_all):
    cloze_parts = []
    total_shapes = 0
    for occ in note_pb.occlusions:
        ord_num = occ.ordinal
        for sh in occ.shapes:
            total_shapes += 1
            props = {p.name: p.value for p in sh.properties}
            sh_type = sh.shape
            props_str = "".join(f":{k}={v}" for k, v in props.items())
            if hide_all and "oi" not in props:
                props_str += ":oi=1"
            cloze_parts.append(
                f"{{{{c{ord_num}::image-occlusion:{sh_type}{props_str}}}}}"
            )
    return "<br>".join(cloze_parts), total_shapes


def _occlusion_edit_data(col, path):
    note_id = int(path)
    resp = col.get_image_occlusion_note(note_id=note_id)
    oneof = resp.WhichOneof("value")
    if oneof == "error":
        raise HTTPException(status_code=404, detail=resp.error)
    note_pb = resp.note
    header = note_pb.header
    back_extra = note_pb.back_extra
    tags = list(note_pb.tags)
    image_url = f"/image-occlusion-img/{note_pb.image_file_name}"
    hide_all = bool(note_pb.occlude_inactive)
    occlusions, shapes_count = _occlusion_shapes(note_pb, hide_all)
    n = col.get_note(note_id)
    default_nt_id = n.mid
    comments = ""
    if "Comments" in n:
        comments = n["Comments"]
    return (
        note_id,
        image_url,
        header,
        back_extra,
        tags,
        hide_all,
        occlusions,
        shapes_count,
        default_nt_id,
        comments,
    )


def _occlusion_add_path(settings, path):
    image_path = path
    if not import_tmp.is_within(settings, image_path):
        resolved = (import_tmp.dir(settings) / image_path).resolve()
        if import_tmp.is_within(settings, str(resolved)):
            image_path = str(resolved)
        else:
            raise HTTPException(status_code=403, detail="Image path forbidden")
    return image_path


def _load_occlusion_page(col, service, path, is_edit, mode):
    # Decks list
    decks_raw = col.decks.all_names_and_ids()
    decks = [{"id": d.id, "name": d.name} for d in decks_raw]

    # Notetypes list
    notetypes_raw = col.models.all_names_and_ids()
    notetypes = [{"id": n.id, "name": n.name} for n in notetypes_raw]

    # Find default image occlusion notetype
    io_nt = col.models.by_name("Image Occlusion")
    if not io_nt:
        col.add_image_occlusion_notetype()
        io_nt = col.models.by_name("Image Occlusion")
    default_nt_id = io_nt["id"] if io_nt else (notetypes[0]["id"] if notetypes else 0)

    # Selected deck id
    selected_deck_id = col.decks.get_current_id()

    note_id = 0
    image_path = ""
    image_url = ""
    header = ""
    back_extra = ""
    comments = ""
    tags: list[str] = []
    occlusions = ""
    hide_all = True
    shapes_count = 0

    if is_edit:
        (
            note_id,
            image_url,
            header,
            back_extra,
            tags,
            hide_all,
            occlusions,
            shapes_count,
            default_nt_id,
            comments,
        ) = _occlusion_edit_data(col, path)
    else:
        image_path = _occlusion_add_path(service.settings, path)

        image_url = f"/image-occlusion-img/{image_path}"

    return {
        "decks": decks,
        "notetypes": notetypes,
        "selected_deck_id": selected_deck_id,
        "selected_notetype_id": default_nt_id,
        "mode": mode,
        "note_id": note_id,
        "image_path": image_path,
        "image_url": image_url,
        "header": header,
        "back_extra": back_extra,
        "comments": comments,
        "tags_str": " ".join(tags),
        "occlusions": occlusions,
        "hide_all": hide_all,
        "shapes_count": shapes_count,
    }


async def _io_image_occlusion_page(service, path, request):

    # Determine mode: edit (leading digits) vs add (image path)
    is_edit = path.isdigit() or (path and path[0].isdigit() and "/" not in path)
    mode = "edit" if is_edit else "add"

    def load_data(col):
        # Decks list
        return _load_occlusion_page(col, service, path, is_edit, mode)

    ctx = await service.run(load_data)

    body = templating.render(
        "pages/image_occlusion.html.jinja",
        tr=tr,
        **ctx,
    )
    # Edit mode (numeric note id) is only reached through the Browser's detail
    # iframe, like /edit: render the editor alone, without the global toolbar
    # and its mobile bottom dock. Add mode is a standalone page and keeps it.
    return HTMLResponse(
        render_page(
            context="image-occlusion",
            body=body,
            toolbar=not is_edit,
        )
    )


def _add_occlusion_oi(match):
    content = match.group(1)
    if ":oi=" not in content:
        return "{{" + content + ":oi=1}}"
    return match.group(0)


def _occlusion_visibility(occlusions, hide_all):
    if hide_all:
        return re.sub(r"\{\{([^}]+)\}\}", _add_occlusion_oi, occlusions)
    return occlusions.replace(r":oi=1", "")


def _update_occlusion_note(
    col, note_id, occlusions, header, back_extra, tags, comments
):
    op = col.update_image_occlusion_note(
        note_id=note_id,
        occlusions=occlusions,
        header=header,
        back_extra=back_extra,
        tags=tags,
    )
    if comments:
        try:
            n = col.get_note(note_id)
            if "Comments" in n and n["Comments"] != comments:
                n["Comments"] = comments
                col.update_note(n)
        except (anki.errors.AnkiException, KeyError) as e:
            logger.warning("Could not update Comments field: %s", e)
    return op


def _add_occlusion_note(
    col,
    service,
    notetype_id,
    image_path,
    occlusions,
    header,
    back_extra,
    tags,
    comments,
):
    if not import_tmp.is_within(service.settings, image_path):
        raise ValueError(f"image path not allowed: {image_path}")
    op = col.add_image_occlusion_note(
        notetype_id=notetype_id,
        image_path=image_path,
        occlusions=occlusions,
        header=header,
        back_extra=back_extra,
        tags=tags,
    )
    created_nids = col.find_notes('note:"Image Occlusion"')
    saved_nid = created_nids[-1] if created_nids else 0
    if saved_nid and comments:
        try:
            n = col.get_note(saved_nid)
            if "Comments" in n:
                n["Comments"] = comments
                col.update_note(n)
        except (anki.errors.AnkiException, KeyError) as e:
            logger.warning("Could not set Comments field: %s", e)
    return op, saved_nid


async def _io_save_image_occlusion(service, payload):
    if not payload or not isinstance(payload, dict):
        return DatastarResponse()

    mode = payload.get("mode", "add")
    note_id = int(payload.get("note_id", 0))
    image_path = payload.get("image_path", "")
    header = payload.get("header", "")
    back_extra = payload.get("back_extra", "")
    comments = payload.get("comments", "")
    tags_str = payload.get("tags_str", "")
    tags = [t.strip() for t in tags_str.split() if t.strip()]
    occlusions = payload.get("occlusions", "")
    hide_all = bool(payload.get("hide_all", True))
    notetype_id = int(payload.get("selected_notetype_id", 0))
    int(payload.get("selected_deck_id", 1))

    # Count non-text occlusions: c1, c2, ... (c0 is text)
    non_text_occlusions = re.findall(
        r"\{\{c([1-9]\d*)::image-occlusion:", occlusions or ""
    )
    shapes_count = int(payload.get("shapes_count", len(non_text_occlusions)))
    if shapes_count <= 0 and len(non_text_occlusions) > 0:
        shapes_count = len(non_text_occlusions)

    # Reject empty occlusion / 0 non-text shapes (legacy returns early without saving)
    if not occlusions or shapes_count <= 0 or len(non_text_occlusions) == 0:
        return signals_response(
            {
                "is_saving": False,
                "status_msg": "Cannot save: no occlusions drawn.",
                "status_type": "danger",
            }
        )

    occlusions = _occlusion_visibility(occlusions, hide_all)
    saved_nid = note_id

    def do_save(col):
        nonlocal saved_nid
        if mode == "edit":
            return _update_occlusion_note(
                col, note_id, occlusions, header, back_extra, tags, comments
            )
        op, saved_nid = _add_occlusion_note(
            col,
            service,
            notetype_id,
            image_path,
            occlusions,
            header,
            back_extra,
            tags,
            comments,
        )
        return op

    try:
        await service.run_op(do_save)
        return DatastarResponse(
            [
                SSE.patch_signals(
                    {
                        "is_saving": False,
                        "status_msg": "Saved successfully!",
                        "status_type": "success",
                        "note_id": saved_nid,
                    }
                ),
                SSE.redirect("/deckbrowser"),
            ]
        )
    except Exception as e:
        logger.exception("Failed to save image occlusion note")
        return signals_response(
            {
                "is_saving": False,
                "status_msg": f"Failed to save: {e!s}",
                "status_type": "danger",
            }
        )


def make_router(get_service: Callable) -> APIRouter:
    router = APIRouter()

    @router.get("/image-occlusion-img/{path:path}")
    async def serve_io_image(path: str):
        return await _io_serve_io_image(get_service(), path)

    @router.get("/image-occlusion/{path:path}", response_class=HTMLResponse)
    async def image_occlusion_page(path: str, request: Request):
        return await _io_image_occlusion_page(get_service(), path, request)

    @router.post("/image-occlusion/save")
    async def save_image_occlusion(payload: ReadSignals):
        return await _io_save_image_occlusion(get_service(), payload)

    return router
