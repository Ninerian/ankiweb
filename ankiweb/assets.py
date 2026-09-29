from __future__ import annotations
from pathlib import Path
from typing import Callable
from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from ankiweb.core.i18n import tr
# Injected into the served SvelteKit shell so the SPA's bridgeCommand("browserSearch:<q>")
# (e.g. graphs count-links) opens ankiweb's browser instead of being a no-op. The SPA has no
# pycmd host otherwise; this defines a minimal one before the app modules load. Other bridge
# commands are intentionally ignored (same as before).
_SPA_HEAD = (
    '<link rel="stylesheet" href="/shell/static/vendor/bootstrap.min.css">'
    '<script src="/shell/static/vendor/bootstrap.bundle.min.js"></script>'
    '<script src="/shell/static/spa_bridge.js"></script>'
)

def _spa_navbar() -> str:
    """Mirrors _toolbar.html.jinja's labels/keys so both navbars localize identically."""
    return (
        '<nav id="ankiweb-spa-toolbar" class="navbar navbar-expand-md bg-body-tertiary border-bottom sticky-top">'
        '  <div class="container-fluid">'
        f'    <button type="button" class="back-btn btn btn-sm btn-outline-secondary me-2" onclick="location.href=\'/deckbrowser\';">\u2039 {tr.actions_decks()}</button>'
        '    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#spaNavbarNav" aria-controls="spaNavbarNav" aria-expanded="false" aria-label="Toggle navigation">'
        '      <span class="navbar-toggler-icon"></span>'
        '    </button>'
        '    <div class="collapse navbar-collapse" id="spaNavbarNav">'
        '      <ul class="navbar-nav me-auto mb-2 mb-md-0">'
        f'        <li class="nav-item"><a class="nav-link" href="/deckbrowser">{tr.actions_decks()}</a></li>'
        f'        <li class="nav-item"><a class="nav-link" href="/add">{tr.actions_add()}</a></li>'
        f'        <li class="nav-item"><a class="nav-link" href="/browse">{tr.qt_misc_browse()}</a></li>'
        f'        <li class="nav-item"><a class="nav-link" href="/graphs">{tr.qt_misc_stats()}</a></li>'
        f'        <li class="nav-item"><a class="nav-link" href="/preferences">{tr.preferences_preferences()}</a></li>'
        f'        <li class="nav-item"><a class="nav-link" href="/tools">{tr.qt_accel_tools().replace("&", "")}</a></li>'
        '        <li class="nav-item"><a class="nav-link" href="/about" title="Source code (AGPL)">Source</a></li>'
        '        <li class="nav-item dropdown">'
        '          <a class="nav-link dropdown-toggle" href="#" role="button" data-bs-toggle="dropdown" aria-expanded="false" title="ankiweb extras">Extras</a>'
        '          <ul class="dropdown-menu">'
        '            <li><a class="dropdown-item" href="/notify">Push notifications</a></li>'
        '          </ul>'
        '        </li>'
        '      </ul>'
        '      <button type="button" class="btn btn-link nav-link ms-auto" onclick="window.ankiwebToggleNight()" title="Toggle night mode">\U0001f319</button>'
        '    </div>'
        '  </div>'
        '</nav>'
    )

# subset of mediasrv _mime_for_path (mediasrv.py:171-210)
MIME = {
    ".css": "text/css",
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".html": "text/html",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".json": "application/json",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".map": "application/json",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/opus",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
}
SVELTEKIT_PAGES = {
    "editor",
    "graphs",
    "congrats",
    "card-info",
    "change-notetype",
    "deck-options",
    "import-anki-package",
    "import-csv",
    "import-page",
    "image-occlusion",
}


# vendored binary assets that are content-stable across the pinned anki version: cache hard.
# (fonts are the big one — MathJax CHTML lazy-loads ~dozens of woff glyph files per render.)
_STATIC_ASSET_EXTS = {
    "woff",
    "woff2",
    "ttf",
    "otf",
    "eot",
    "svg",
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "ico",
}


def _mime(path: str) -> str:
    ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return MIME.get(ext, "application/octet-stream")


def _resolve(rel: str) -> str:
    """Replicate mediasrv _extract_internal_request rewrites for the _anki/ namespace."""
    first = rel.split("/", 1)[0]
    if first in SVELTEKIT_PAGES:
        return f"sveltekit/{rel}"
    if rel.startswith("_app/"):
        return f"sveltekit/{rel}"
    if "/" not in rel:  # bare file at /_anki/<file>
        if rel.endswith(".css"):
            return f"css/{rel}"
        if rel.endswith(".js"):
            stem = rel[:-3].removesuffix(".min")  # jquery.min -> jquery
            if stem in ("jquery", "jquery-ui", "plot"):
                return f"js/vendor/{rel}"
            return f"js/{rel}"
    return rel


def build_router(assets_dir: Path) -> APIRouter:
    router = APIRouter()

    @router.get("/_anki/{path:path}")
    def serve(path: str, request: Request) -> Response:
        rel = _resolve(path)
        target = (assets_dir / rel).resolve()
        try:
            target.relative_to(assets_dir.resolve())
        except ValueError:
            return PlainTextResponse("forbidden", status_code=403)

        if not target.is_file():
            # SvelteKit SPA fallback for non-immutable sveltekit paths
            if rel.startswith("sveltekit/") and "immutable" not in rel:
                fallback = assets_dir / "sveltekit" / "index.html"
                if fallback.is_file():
                    return FileResponse(fallback, media_type="text/html")
            return PlainTextResponse("not found", status_code=404)

        headers = {}
        ext = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
        if "immutable" in rel:
            headers["Cache-Control"] = "max-age=31536000"
        elif ext in _STATIC_ASSET_EXTS:
            # Vendored, version-pinned, content-stable binaries (esp. MathJax's lazily-loaded
            # CHTML glyph fonts). Without a cache header the browser re-downloads them FULLY on
            # every card render -> slow card switches. They never change at runtime.
            headers["Cache-Control"] = "max-age=31536000"
        elif rel.endswith((".css", ".js")):
            # Vendored frontend bundles (editor.js is 3.5 MB) are version-pinned. Caching them
            # for a day means the Browser's per-card editor iframe (and the reviewer) reuse the
            # cache instead of re-downloading megabytes on every card switch. (max-age=0 forced a
            # revalidation that came back as a full 200 here, defeating the cache.) A re-vendor is
            # picked up within a day, or immediately via a hard refresh.
            headers["Cache-Control"] = "max-age=86400"
        return FileResponse(target, media_type=_mime(rel), headers=headers)

    return router


def build_sveltekit_router(assets_dir: Path) -> APIRouter:
    """Serve the vendored SvelteKit SPA at ROOT paths (its index.html imports /_app/...
    and client-routes by location.pathname). E2/E3 add more page routes here."""
    router = APIRouter()
    index = assets_dir / "sveltekit" / "index.html"

    def _shell_with_bridge() -> str:
        html = index.read_text(encoding="utf-8")
        html = html.replace('<body data-sveltekit-preload-data="hover">', '<body data-sveltekit-preload-data="hover">' + _spa_navbar(), 1)
        return html.replace("</body>", _SPA_HEAD + "</body>", 1)
    @router.get("/graphs")
    def graphs_page() -> Response:
        return HTMLResponse(_shell_with_bridge())

    @router.get("/editor")
    @router.get("/editor/{path:path}")
    def editor_page(path: str = "") -> Response:
        return HTMLResponse(_shell_with_bridge())

    @router.get("/deck-options/{deck_id}")
    def deck_options_page(deck_id: str) -> Response:
        return HTMLResponse(_shell_with_bridge())

    @router.get("/change-notetype/{ids:path}")
    def change_notetype_page(ids: str) -> Response:
        return HTMLResponse(_shell_with_bridge())

    @router.get("/card-info/{ids:path}")
    def card_info_page(ids: str) -> Response:
        return HTMLResponse(_shell_with_bridge())

    @router.get("/import-csv/{path:path}")
    def import_csv_page(path: str) -> Response:
        return HTMLResponse(_shell_with_bridge())

    @router.get("/import-anki-package/{path:path}")
    def import_anki_package_page(path: str) -> Response:
        return HTMLResponse(_shell_with_bridge())

    @router.get("/image-occlusion/{path:path}")
    def image_occlusion_page(path: str) -> Response:
        return HTMLResponse(_shell_with_bridge())
    @router.get("/_app/{path:path}")
    def app_asset(path: str) -> Response:
        rel = _resolve("_app/" + path)
        target = (assets_dir / rel).resolve()
        try:
            target.relative_to(assets_dir.resolve())
        except ValueError:
            return PlainTextResponse("forbidden", status_code=403)
        if not target.is_file():
            return PlainTextResponse("not found", status_code=404)
        headers = {"Cache-Control": "max-age=31536000"} if "immutable" in rel else {}
        return FileResponse(target, media_type=_mime(rel), headers=headers)

    @router.get("/favicon.ico")
    def favicon() -> Response:
        f = assets_dir / "imgs" / "favicon.ico"
        if f.is_file():
            return FileResponse(f, media_type="image/x-icon")
        return Response(status_code=204)

    return router


def build_media_router(get_service: Callable) -> APIRouter:
    router = APIRouter()

    @router.get("/{path:path}")
    async def serve_media(path: str) -> Response:
        service = get_service()  # lazy: service is created in lifespan, not import time
        media_dir = Path(await service.run(lambda col: col.media.dir())).resolve()
        target = (media_dir / path).resolve()
        try:
            target.relative_to(media_dir)
        except ValueError:
            return PlainTextResponse("forbidden", status_code=403)
        if not target.is_file():
            return PlainTextResponse("not found", status_code=404)
        return FileResponse(target, media_type=_mime(path))

    return router
