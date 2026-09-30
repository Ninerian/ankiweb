from __future__ import annotations
from pathlib import Path
from typing import Callable
from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse

# subset of mediasrv _mime_for_path (mediasrv.py:171-210)
MIME = {
    ".css": "text/css",
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".eot": "application/vnd.ms-fontobject",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
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

    @router.get("/favicon.ico")
    def favicon() -> Response:
        f = assets_dir / "imgs" / "favicon.ico"
        if f.is_file():
            return FileResponse(f, media_type="image/x-icon")
        return Response(status_code=204)

    @router.get("/_anki/{path:path}")
    def serve(path: str, request: Request) -> Response:
        rel = _resolve(path)
        target = (assets_dir / rel).resolve()
        try:
            target.relative_to(assets_dir.resolve())
        except ValueError:
            return PlainTextResponse("forbidden", status_code=403)

        if not target.is_file():
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
