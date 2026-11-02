from __future__ import annotations

from contextlib import asynccontextmanager

from datastar_py.fastapi import ReadSignals
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from starlette_compress import CompressMiddleware

# Initialize Anki through the collection adapter before screens import its cyclic modules.
import ankiweb.adapters.outbound.anki_collection_adapter as collection_adapter
from ankiweb.adapters.inbound.http_app import build_app_router
from ankiweb.adapters.inbound.http_app.pwa import (
    APP_PWA_PUBLIC_PATHS,
    build_app_pwa_router,
)
from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.adapters.inbound.http_shared.login import (
    datastar_login,
    form_login,
    is_datastar_login,
    wrong_password_text,
)
from ankiweb.adapters.inbound.http_shared.pwa import (
    MANIFEST_PATH,
    SERVICE_WORKER_PATH,
    build_pwa_router,
)
from ankiweb.adapters.inbound.http_shared.routes import (
    build_screen_router,
    register_screen_handlers,
)
from ankiweb.adapters.inbound.rpc_passthrough.route import (
    build_router as build_rpc_router,
)
from ankiweb.adapters.inbound.ws_bridge.ws import build_router as build_ws_router
from ankiweb.adapters.outbound import json_config_store
from ankiweb.assets import (
    build_media_router,
)
from ankiweb.assets import (
    build_router as build_assets_router,
)
from ankiweb.core.app_client.lang import resolve_lang
from ankiweb.core.auth import COOKIE, cookie_ok
from ankiweb.core.bridge.hub import BridgeHub
from ankiweb.core.config import Settings, host_allowed
from ankiweb.core.notify.engine import NotifierState

# Fetched by the browser without credentials (manifest) / before login (worker install).
PWA_PUBLIC_PATHS = (MANIFEST_PATH, SERVICE_WORKER_PATH, *APP_PWA_PUBLIC_PATHS)


def _login_html(request: Request, error: bool = False) -> str:
    return templating.render(
        "login.html.jinja",
        error_text=wrong_password_text() if error else "",
        login_path="/app/login" if request.url.path == "/app/login" else "/login",
    )


def _make_lifespan(settings, service, hub, notifier):
    owns = service is None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        svc = service
        if owns:
            svc = collection_adapter.CollectionService(settings)
            await svc.open()
        h = hub if hub is not None else BridgeHub()
        if svc is not None:
            svc.subscribe(h.broadcast_opchanges)
        app.state.settings = settings
        app.state.service = svc
        app.state.hub = h
        app.state.notifier = (
            notifier
            if notifier is not None
            else NotifierState(
                settings.collection_path.parent / "notify.json", store=json_config_store
            )
        )
        register_screen_handlers(svc, h)
        try:
            yield
        finally:
            if owns and svc is not None:
                await svc.close()

    return lifespan


async def _host_guard(request, call_next, settings):
    host = request.headers.get("host", "")
    if not host_allowed(host, settings.allowed_hosts):
        return PlainTextResponse("forbidden host", status_code=403)
    return await call_next(request)


async def _auth_guard(request, call_next, settings):
    # Open by default; login, logout and health checks remain reachable without a cookie.
    if (
        settings.password
        and request.url.path not in ("/login", "/app/login", "/logout", "/healthz")
        and request.url.path not in PWA_PUBLIC_PATHS
        and not request.url.path.startswith("/shell/static/")
        and not cookie_ok(request.cookies.get(COOKIE), settings.password)
    ):
        path = request.url.path
        login_path = (
            "/app/login" if path == "/app" or path.startswith("/app/") else "/login"
        )
        return RedirectResponse(login_path, status_code=303)
    return await call_next(request)


def _login_destination(request: Request) -> str:
    return "/app/" if request.url.path == "/app/login" else "/"


def create_app(
    settings: Settings | None = None,
    service: collection_adapter.CollectionService | None = None,
    hub: BridgeHub | None = None,
    notifier=None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(
        title="ankiweb", lifespan=_make_lifespan(settings, service, hub, notifier)
    )

    async def host_guard(request, call_next):
        return await _host_guard(request, call_next, settings)

    app.add_middleware(BaseHTTPMiddleware, dispatch=host_guard)

    async def auth_guard(request, call_next):
        return await _auth_guard(request, call_next, settings)

    app.add_middleware(BaseHTTPMiddleware, dispatch=auth_guard)

    # Outermost: negotiates zstd/brotli/gzip from Accept-Encoding. text/event-stream (the
    # Datastar SSE streams) is excluded by default, so streaming responses stay unbuffered.
    app.add_middleware(CompressMiddleware)

    # --- specific routes FIRST, media catch-all LAST (Starlette matches in order) ---
    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/app/login", response_class=HTMLResponse)
    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        return HTMLResponse(_login_html(request))

    @app.post("/app/login")
    @app.post("/login")
    async def login_submit(request: Request, payload: ReadSignals = None):
        destination = _login_destination(request)
        if is_datastar_login(request, payload):
            return await datastar_login(request, payload, settings, destination)
        return await form_login(
            request,
            settings,
            destination,
            lambda: HTMLResponse(_login_html(request, error=True), status_code=401),
        )

    @app.get("/logout")
    def logout():
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(COOKIE)
        return resp

    static_dir = settings.shell_dir / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/shell/static",
        StaticFiles(directory=str(static_dir), check_dir=False),
        name="shell",
    )
    app.include_router(
        build_pwa_router()
    )  # GET /manifest.webmanifest, /service-worker.js
    app.include_router(build_app_pwa_router(static_dir, resolve_lang(settings)))

    app.include_router(build_assets_router(settings.assets_dir))  # GET  /_anki/{path}
    app.include_router(
        build_rpc_router(lambda: app.state.service, lambda: app.state.hub)
    )  # POST /_anki/{method}
    app.include_router(
        build_ws_router(
            lambda: app.state.hub, settings.allowed_hosts, settings.password
        )
    )  # WS /ws
    app.include_router(
        build_screen_router(
            lambda: app.state.service,
            lambda: app.state.notifier,
            lambda: app.state.hub,
            settings=settings,
        )
    )  # GET / + /notify
    app.include_router(
        build_app_router(lambda: app.state.service, settings)
    )  # GET /app/*
    app.include_router(
        build_media_router(lambda: app.state.service)
    )  # GET  /{path} — LAST

    return app
