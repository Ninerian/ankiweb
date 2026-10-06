"""Image Occlusion next router and endpoints.

Serves:
  GET  /image-occlusion/{path:path}
  GET  /image-occlusion-img/{path:path}
  POST /image-occlusion/save
"""

from __future__ import annotations

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


def make_router(get_service: Callable) -> APIRouter:
    router = APIRouter()

    @router.get("/image-occlusion-img/{path:path}")
    async def serve_io_image(path: str):
        """Serve an image from import_tmp or col.media."""
        service = get_service()
        # Check if it's within import_tmp
        resolved_path = Path(path).resolve()
        if import_tmp.is_within(service.settings, str(resolved_path)) and resolved_path.is_file():
            # touch on read
            try:
                os.utime(resolved_path, None)
            except OSError:
                pass
            return FileResponse(resolved_path)

        # Fallback to col.media.dir()
        media_dir = Path(await service.run(lambda col: col.media.dir())).resolve()
        target = (media_dir / path).resolve()
        try:
            target.relative_to(media_dir)
        except ValueError:
            return PlainTextResponse("forbidden", status_code=403)
        if target.is_file():
            return FileResponse(target)

        return PlainTextResponse("not found", status_code=404)

    @router.get("/image-occlusion/{path:path}", response_class=HTMLResponse)
    async def image_occlusion_page(path: str, request: Request):
        service = get_service()

        # Determine mode: edit (leading digits) vs add (image path)
        is_edit = path.isdigit() or (path and path[0].isdigit() and "/" not in path)
        mode = "edit" if is_edit else "add"

        def load_data(col):
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

                # Reconstruct occlusions cloze string from note_pb.occlusions
                # Each item has shapes and ordinal
                cloze_parts = []
                total_shapes = 0
                for occ in note_pb.occlusions:
                    ord_num = occ.ordinal
                    for sh in occ.shapes:
                        total_shapes += 1
                        props = {p.name: p.value for p in sh.properties}
                        # shape type: rect, ellipse, polygon, text
                        sh_type = sh.shape
                        props_str = "".join(f":{k}={v}" for k, v in props.items())
                        if hide_all and "oi" not in props:
                            props_str += ":oi=1"
                        cloze_parts.append(f"{{{{c{ord_num}::image-occlusion:{sh_type}{props_str}}}}}")
                occlusions = "<br>".join(cloze_parts)
                shapes_count = total_shapes

                # Get note model id and comments
                n = col.get_note(note_id)
                default_nt_id = n.mid
                if "Comments" in n:
                    comments = n["Comments"]
            else:
                image_path = path
                # Path confinement check
                if not import_tmp.is_within(service.settings, image_path):
                    # Check if relative filename inside import_tmp or io_dir
                    resolved = (import_tmp.dir(service.settings) / image_path).resolve()
                    if import_tmp.is_within(service.settings, str(resolved)):
                        image_path = str(resolved)
                    else:
                        raise HTTPException(status_code=403, detail="Image path forbidden")

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

        ctx = await service.run(load_data)

        body = templating.render(
            "pages/image_occlusion.html.jinja",
            tr=tr,
            **ctx,
        )
        return HTMLResponse(
            render_page(
                context="image-occlusion",
                body=body,
                toolbar=True,
            )
        )

    @router.post("/image-occlusion/save")
    async def save_image_occlusion(payload: ReadSignals):
        service = get_service()
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
        non_text_occlusions = re.findall(r"\{\{c([1-9]\d*)::image-occlusion:", occlusions or "")
        shapes_count = int(payload.get("shapes_count", len(non_text_occlusions)))
        if shapes_count <= 0 and len(non_text_occlusions) > 0:
            shapes_count = len(non_text_occlusions)

        # Reject empty occlusion / 0 non-text shapes (legacy returns early without saving)
        if not occlusions or shapes_count <= 0 or len(non_text_occlusions) == 0:
            return signals_response({
                "is_saving": False,
                "status_msg": "Cannot save: no occlusions drawn.",
                "status_type": "danger",
            })

        # Adjust occlusions for hide_all (ensure :oi=1 is present on all shapes or removed)
        if hide_all:
            def add_oi(m):
                content = m.group(1)
                if ":oi=" not in content:
                    return "{{" + content + ":oi=1}}"
                return m.group(0)
            occlusions = re.sub(r"\{\{([^}]+)\}\}", add_oi, occlusions)
        else:
            occlusions = re.sub(r":oi=1", "", occlusions)
        saved_nid = note_id

        def do_save(col):
            nonlocal saved_nid
            if mode == "edit":
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
            else:
                # Add mode
                # Ensure image_path is valid
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
                # Find created note id
                # The latest added note
                created_nids = col.find_notes('note:"Image Occlusion"')
                saved_nid = created_nids[-1] if created_nids else 0
                created_nid = saved_nid
                if created_nid and comments:
                    try:
                        n = col.get_note(created_nid)
                        if "Comments" in n:
                            n["Comments"] = comments
                            col.update_note(n)
                    except (anki.errors.AnkiException, KeyError) as e:
                        logger.warning("Could not set Comments field: %s", e)

                return op

        try:
            await service.run_op(do_save)
            return DatastarResponse([
                SSE.patch_signals({
                    "is_saving": False,
                    "status_msg": "Saved successfully!",
                    "status_type": "success",
                    "note_id": saved_nid,
                }),
                SSE.redirect("/deckbrowser"),
            ])
        except Exception as e:
            logger.exception("Failed to save image occlusion note")
            return signals_response({
                "is_saving": False,
                "status_msg": f"Failed to save: {e!s}",
                "status_type": "danger",
            })

    return router
