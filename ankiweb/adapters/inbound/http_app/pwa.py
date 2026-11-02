"""Public install assets and offline fallback for the app-scoped PWA."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse, Response

from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.core.app_client.lang import ResolvedLang

APP_SCOPE = "/app/"
APP_MANIFEST_PATH = "/app/manifest.webmanifest"
APP_SERVICE_WORKER_PATH = "/app/service-worker.js"
APP_OFFLINE_PATH = "/app/offline"
APP_THEME_COLOR_LIGHT = "#f4f3ed"
APP_THEME_COLOR_DARK = "#121316"
APP_PWA_PUBLIC_PATHS = (APP_MANIFEST_PATH, APP_SERVICE_WORKER_PATH, APP_OFFLINE_PATH)

APP_MANIFEST = {
    "name": "AnkiWeb",
    "short_name": "Anki",
    "id": APP_SCOPE,
    "start_url": APP_SCOPE,
    "scope": APP_SCOPE,
    "display": "standalone",
    "theme_color": APP_THEME_COLOR_LIGHT,
    "background_color": APP_THEME_COLOR_LIGHT,
    "icons": [
        {
            "src": "/shell/static/icons/icon-192.png",
            "sizes": "192x192",
            "type": "image/png",
            "purpose": "any maskable",
        },
        {
            "src": "/shell/static/icons/icon-512.png",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "any maskable",
        },
    ],
}

# Authenticated HTML and other non-app assets are never stored in this cache.
SERVICE_WORKER_JS = """\
const CACHE = "__CACHE_NAME__";
const CACHE_PREFIX = "ankiweb-app-";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll([
        new Request("/app/offline", {cache: "reload"}),
        new Request("/shell/static/app-client.css?v=__BUILD_HASH__", {cache: "reload"}),
      ]))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys
        .filter((key) => key.startsWith(CACHE_PREFIX) && key !== CACHE)
        .map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;

  if (url.pathname === "/shell/static/app-client.css" || url.pathname.startsWith("/shell/static/app/")) {
    event.respondWith(
      caches.open(CACHE).then((cache) =>
        cache.match(req).then((hit) => hit || fetch(new Request(req, {cache: "reload"})).then(async (res) => {
          if (res.ok) await cache.put(req, res.clone());
          return res;
        }))
      )
    );
  } else if (req.mode === "navigate" && url.pathname.startsWith("/app/")) {
    event.respondWith(
      fetch(req).catch(() => caches.match("/app/offline").then((hit) => hit || Response.error()))
    );
  }
});
"""


def build_hash(static_dir: Path) -> str:
    """Hash the deployed app CSS and JavaScript to version the worker cache."""
    digest = sha256()
    paths = [static_dir / "app-client.css", *sorted((static_dir / "app").glob("*.js"))]
    for path in paths:
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def build_app_pwa_router(static_dir: Path, lang: ResolvedLang) -> APIRouter:
    router = APIRouter()

    @router.get(APP_MANIFEST_PATH)
    def manifest() -> JSONResponse:
        return JSONResponse(APP_MANIFEST, media_type="application/manifest+json")

    @router.get(APP_SERVICE_WORKER_PATH)
    def service_worker() -> Response:
        version = build_hash(static_dir)
        cache_name = f"ankiweb-app-{version}"
        return Response(
            SERVICE_WORKER_JS.replace("__CACHE_NAME__", cache_name).replace(
                "__BUILD_HASH__", version
            ),
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": APP_SCOPE},
        )

    @router.get(APP_OFFLINE_PATH, response_class=HTMLResponse)
    def offline() -> HTMLResponse:
        return HTMLResponse(
            templating.render(
                "app/offline.html.jinja",
                app_lang=lang,
                app_asset_version=build_hash(static_dir),
            )
        )

    return router
