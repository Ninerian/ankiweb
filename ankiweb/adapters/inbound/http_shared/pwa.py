"""PWA install surface: web app manifest + service worker.

Both are served unauthenticated (see app._auth_guard): browsers fetch the manifest
credential-less by default, and neither contains user data. The service worker is a route,
not a static file, so its scope is "/" (a worker's max scope is its own path).

The worker deliberately caches nothing but static shell assets: authenticated HTML, /_anki/
RPC and media must always hit the server, otherwise a cached page would be shown without
the login check.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

MANIFEST_PATH = "/manifest.webmanifest"
SERVICE_WORKER_PATH = "/service-worker.js"
THEME_COLOR = "#ffd43b"
BACKGROUND_COLOR = "#f4f3ed"

MANIFEST = {
    "name": "AnkiWeb",
    "short_name": "Anki",
    "id": "/",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "theme_color": THEME_COLOR,
    "background_color": BACKGROUND_COLOR,
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

# Cache-first only for /shell/static/ GETs (versioned by deploy: bump CACHE to evict).
# Everything else is not intercepted, so the browser's normal network path applies.
SERVICE_WORKER_JS = """\
const CACHE = "ankiweb-shell-v1";

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys
        .filter((k) => k.startsWith("ankiweb-shell-") && k !== CACHE)
        .map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;
  if (!url.pathname.startsWith("/shell/static/")) return;
  event.respondWith(
    caches.open(CACHE).then((cache) =>
      cache.match(req).then((hit) => hit || fetch(req).then((res) => {
        if (res.ok) cache.put(req, res.clone());
        return res;
      }))
    )
  );
});
"""


def build_pwa_router() -> APIRouter:
    router = APIRouter()

    @router.get(MANIFEST_PATH)
    def manifest():
        return JSONResponse(MANIFEST, media_type="application/manifest+json")

    @router.get(SERVICE_WORKER_PATH)
    def service_worker():
        return Response(
            SERVICE_WORKER_JS,
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
        )

    return router
