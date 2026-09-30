from __future__ import annotations
import os
import tempfile
from fastapi import APIRouter, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from starlette.background import BackgroundTask

from ankiweb.adapters.inbound.http_shared.page import render_page
from ankiweb.adapters.inbound.http_datastar.deckbrowser import (
    render_deckbrowser_html,
    make_deckbrowser_routes,
)
from ankiweb.adapters.inbound.http_datastar.overview import (
    render_overview_html,
    make_overview_routes,
)
from ankiweb.adapters.inbound.http_screens.reviewer import (
    reviewer_page_body,
    make_reviewer_handler,
)
from ankiweb.adapters.inbound.http_datastar.browser import (
    render_browser_html,
    make_browser_routes,
)
from ankiweb.adapters.inbound.http_screens.editor import (
    editor_page_body,
    make_editor_handler,
)
from ankiweb.adapters.inbound.http_screens.add import render_add_html, make_add_handler
from ankiweb.adapters.inbound.http_datastar.custom_study import (
    render_custom_study_html,
    make_custom_study_routes,
)
from ankiweb.adapters.inbound.http_shared.about import render_about_html
from ankiweb.adapters.inbound.http_shared.component_gallery import render_component_gallery_html
from ankiweb.adapters.inbound.http_datastar.dev_progress import router as dev_progress_router
from ankiweb.adapters.inbound.http_pages import make_pages_router
from ankiweb.adapters.inbound.http_datastar.filtered_deck import (
    render_filtered_deck_html,
    make_filtered_deck_routes,
)
from ankiweb.adapters.inbound.http_shared.export import render_export_html
from ankiweb.adapters.inbound.http_datastar.preferences import (
    render_preferences_html,
    make_preferences_routes,
)
from ankiweb.adapters.inbound.http_shared.preview import render_preview_html
from ankiweb.adapters.inbound.http_datastar.fields import (
    render_fields_html,
    make_fields_routes,
)
from ankiweb.adapters.inbound.http_datastar.card_layout import (
    render_card_layout_html,
    make_card_layout_routes,
)
from ankiweb.adapters.inbound.http_datastar.tools import (
    render_tools_html,
    make_tools_routes,
)
from ankiweb.adapters.inbound.http_datastar.notetypes import (
    render_notetypes_html,
    make_notetypes_routes,
)
from ankiweb.adapters.inbound.http_shared.notify import (
    render_notify_html,
    config_from_form,
)
from ankiweb.core.notify.engine import header_safe

_MIME_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/bmp": ".bmp",
}


def build_screen_router(get_service, get_notifier=None, get_hub=None, settings=None) -> APIRouter:
    router = APIRouter()
    router.include_router(make_deckbrowser_routes(get_service))
    router.include_router(make_overview_routes(get_service))
    router.include_router(make_custom_study_routes(get_service))
    router.include_router(make_filtered_deck_routes(get_service))
    router.include_router(make_preferences_routes(get_service))
    router.include_router(make_fields_routes(get_service))
    router.include_router(make_card_layout_routes(get_service))
    router.include_router(make_tools_routes(get_service))
    router.include_router(make_notetypes_routes(get_service))
    if get_hub is not None:
        router.include_router(make_browser_routes(get_service, get_hub))

    @router.get("/", response_class=HTMLResponse)
    @router.get("/deckbrowser", response_class=HTMLResponse)
    async def deckbrowser_page():
        service = get_service()
        body = await service.run(render_deckbrowser_html)
        return HTMLResponse(render_page("deckbrowser", body))

    @router.get("/overview", response_class=HTMLResponse)
    async def overview_page():
        service = get_service()
        body = await service.run(render_overview_html)
        return HTMLResponse(render_page("overview", body, ["css/overview.css"]))

    @router.get("/custom-study", response_class=HTMLResponse)
    async def custom_study_page():
        service = get_service()
        body = await service.run(render_custom_study_html)
        return HTMLResponse(render_page("customstudy", body))

    @router.get("/filtered-deck", response_class=HTMLResponse)
    async def filtered_deck_new_page():
        service = get_service()
        body = await service.run(lambda col: render_filtered_deck_html(col, 0))
        return HTMLResponse(render_page("filtereddeck", body))

    @router.get("/filtered-deck/{deck_id}", response_class=HTMLResponse)
    async def filtered_deck_edit_page(deck_id: int):
        service = get_service()
        body = await service.run(lambda col: render_filtered_deck_html(col, deck_id))
        return HTMLResponse(render_page("filtereddeck", body))

    @router.get("/reviewer", response_class=HTMLResponse)
    async def reviewer_page():
        return HTMLResponse(
            render_page(
                "reviewer",
                reviewer_page_body(),
                ["css/reviewer.css"],
                [
                    "js/vendor/jquery.min.js",
                    "js/mathjax.js",
                    "js/vendor/mathjax/tex-chtml-full.js",
                    "js/reviewer.js",
                ],
                toolbar=False,
            )
        )

    @router.get("/browse", response_class=HTMLResponse)
    async def browse_page(q: str = ""):
        service = get_service()
        body = await service.run(lambda col: render_browser_html(col, q))
        return HTMLResponse(render_page("browser", body))

    @router.get("/preferences", response_class=HTMLResponse)
    async def preferences_page():
        service = get_service()
        body = await service.run(render_preferences_html)
        return HTMLResponse(render_page("preferences", body))

    @router.get("/notetypes", response_class=HTMLResponse)
    async def notetypes_page():
        service = get_service()
        body = await service.run(render_notetypes_html)
        return HTMLResponse(render_page("notetypes", body))

    @router.get("/fields/{ntid}", response_class=HTMLResponse)
    async def fields_page(ntid: int):
        service = get_service()
        body = await service.run(lambda col: render_fields_html(col, ntid))
        return HTMLResponse(render_page("fields", body))

    @router.get("/card-layout/{ntid}", response_class=HTMLResponse)
    async def card_layout_page(ntid: int):
        service = get_service()
        body = await service.run(lambda col: render_card_layout_html(col, ntid))
        return HTMLResponse(render_page("cardlayout", body))

    @router.get("/tools", response_class=HTMLResponse)
    async def tools_page():
        service = get_service()
        body = await service.run(render_tools_html)
        return HTMLResponse(render_page("tools", body))

    @router.get("/notify", response_class=HTMLResponse)
    async def notify_page():
        state = get_notifier() if get_notifier is not None else None
        return HTMLResponse(render_page("notify", render_notify_html(state)))

    @router.post("/notify")
    async def notify_post(
        action: str = Form("save"),
        enabled: bool = Form(False),
        url: str = Form(""),
        token: str = Form(""),
        poll_sec: float = Form(60.0),
        retry_sec: float = Form(30.0),
        scope: str = Form("leaf"),
    ):
        state = get_notifier() if get_notifier is not None else None
        if not header_safe(token):
            form = {
                "enabled": enabled,
                "url": url,
                "token": token,
                "poll_sec": poll_sec,
                "retry_sec": retry_sec,
                "scope": scope,
            }
            return HTMLResponse(
                render_page(
                    "notify",
                    render_notify_html(
                        state,
                        error="Token must be ASCII / latin-1 (it is sent in an HTTP header).",
                        form=form,
                    ),
                ),
                status_code=400,
            )
        if state is not None:
            state.update(
                config_from_form(enabled, url, token, poll_sec, retry_sec, scope)
            )
            if action == "resync":
                state.request_resync()  # drop the baseline so all learnable decks re-push
        return RedirectResponse("/notify", status_code=303)

    @router.get("/about", response_class=HTMLResponse)
    async def about_page():
        # AGPL §13 Corresponding-Source offer (settings carries the source URL).
        return HTMLResponse(
            render_page("about", render_about_html(get_service().settings))
        )
    is_dev = settings.dev if settings is not None else False
    if is_dev:
        @router.get("/dev/components", response_class=HTMLResponse)
        async def component_gallery_page():
            # Dev harness for the ts/ -> Jinja component migration; needs no collection.
            return HTMLResponse(render_page("components", render_component_gallery_html()))

        # Dev-only simulated backend progress stream for the BackendProgressIndicator demo.
        router.include_router(dev_progress_router)

    @router.get("/preview/{nid}", response_class=HTMLResponse)
    async def preview_page(nid: int):
        service = get_service()
        body = await service.run(lambda col: render_preview_html(col, nid))
        return HTMLResponse(render_page("preview", body))

    @router.post("/upload_media")
    async def upload_media(file: UploadFile):
        data = await file.read()
        base = (file.filename or "paste").rsplit("/", 1)[-1].rsplit("\\", 1)[
            -1
        ] or "paste"
        if "." not in base:
            base += _MIME_EXT.get(file.content_type or "", ".png")
        fname = await get_service().run(lambda col: col.media.write_data(base, data))
        return {"filename": fname}

    @router.get("/export", response_class=HTMLResponse)
    async def export_page():
        service = get_service()
        body = await service.run(render_export_html)
        return HTMLResponse(render_page("export", body))

    @router.post("/export")
    async def export_post(
        target: str = Form("all"),
        fmt: str = Form("apkg"),
        with_scheduling: bool = Form(False),
        with_media: bool = Form(False),
        with_deck_configs: bool = Form(False),
        legacy: bool = Form(False),
        with_html: bool = Form(False),
        with_tags: bool = Form(False),
        with_deck: bool = Form(False),
        with_notetype: bool = Form(False),
        with_guid: bool = Form(False),
    ):
        import anki.import_export_pb2 as ie

        service = get_service()

        def make_limit():
            lim = ie.ExportLimit()
            if target == "all":
                lim.whole_collection.SetInParent()
            else:
                lim.deck_id = int(target)
            return lim

        suffix = {
            "apkg": ".apkg",
            "colpkg": ".colpkg",
            "notes_csv": ".csv",
            "cards_csv": ".csv",
        }.get(fmt, ".apkg")
        fd, out = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        try:
            if fmt == "apkg":
                opts = ie.ExportAnkiPackageOptions(
                    with_scheduling=with_scheduling,
                    with_media=with_media,
                    with_deck_configs=with_deck_configs,
                    legacy=legacy,
                )
                lim = make_limit()
                await service.run(
                    lambda col: col.export_anki_package(
                        out_path=out, options=opts, limit=lim
                    )
                )
                filename, media = "export.apkg", "application/octet-stream"
            elif fmt == "colpkg":
                await service.run(
                    lambda col: col.export_collection_package(out, with_media, legacy)
                )
                await (
                    service.reopen()
                )  # export_collection_package closed the collection
                filename, media = "collection.colpkg", "application/octet-stream"
            elif fmt == "notes_csv":
                lim = make_limit()
                await service.run(
                    lambda col: col.export_note_csv(
                        out_path=out,
                        limit=lim,
                        with_html=with_html,
                        with_tags=with_tags,
                        with_deck=with_deck,
                        with_notetype=with_notetype,
                        with_guid=with_guid,
                    )
                )
                filename, media = "notes.csv", "text/csv"
            elif fmt == "cards_csv":
                lim = make_limit()
                await service.run(
                    lambda col: col.export_card_csv(
                        out_path=out, limit=lim, with_html=with_html
                    )
                )
                filename, media = "cards.csv", "text/csv"
            else:
                os.remove(out)
                return HTMLResponse("unknown export format", status_code=400)
        except Exception as exc:
            try:
                os.remove(out)
            except OSError:
                pass
            body = await service.run(render_export_html)
            return HTMLResponse(
                render_page(
                    "export",
                    f"<div style='color:#c00'>Export failed: {exc}</div>" + body,
                )
            )
        return FileResponse(
            out,
            media_type=media,
            filename=filename,
            background=BackgroundTask(os.remove, out),
        )

    @router.post("/image-occlusion/upload")
    async def image_occlusion_upload(file: UploadFile):
        from fastapi.responses import JSONResponse
        from ankiweb import import_tmp

        service = get_service()
        import_tmp.io_gc(service.settings)
        name = (file.filename or "").lower()
        ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
        if ext not in (
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".webp",
            ".bmp",
            ".svg",
            ".avif",
        ):
            return JSONResponse(
                {"error": f"unsupported image type: {ext or '(none)'}"}, status_code=400
            )
        dest = import_tmp.io_allocate(service.settings, ext)
        dest.write_bytes(await file.read())
        await service.run(
            lambda col: col.add_image_occlusion_notetype()
        )  # idempotent ensure
        return {"path": str(dest)}

    @router.post("/import/upload")
    async def import_upload(file: UploadFile):
        from fastapi.responses import JSONResponse
        from ankiweb import import_tmp

        service = get_service()
        import_tmp.gc(service.settings)  # lazy TTL sweep
        name = (file.filename or "").lower()
        ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
        routes = {
            ".csv": "import-csv",
            ".tsv": "import-csv",
            ".txt": "import-csv",
            ".apkg": "import-anki-package",
            ".zip": "import-anki-package",
        }
        route = routes.get(ext)
        if route is None:
            return JSONResponse(
                {"error": f"unsupported file type: {ext or '(none)'}"}, status_code=400
            )
        dest = import_tmp.allocate(service.settings, ext)
        dest.write_bytes(await file.read())
        return {"route": route, "path": str(dest)}

    # Replacements for vendored SvelteKit pages, served at original URLs.
    router.include_router(make_pages_router(get_service))
    return router


def register_screen_handlers(service, hub) -> None:
    hub.set_handler("reviewer", make_reviewer_handler(service, hub))
    hub.set_handler("editor", make_editor_handler(service, hub))
    hub.set_handler("add", make_add_handler(service, hub))
