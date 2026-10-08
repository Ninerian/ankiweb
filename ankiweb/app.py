from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from starlette_compress import CompressMiddleware

# Initialize Anki through the collection adapter before screens import its cyclic modules.
import ankiweb.adapters.outbound.anki_collection_adapter as collection_adapter
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
from ankiweb.core.auth import COOKIE, auth_token, cookie_ok, password_ok
from ankiweb.core.bridge.hub import BridgeHub
from ankiweb.core.config import Settings, host_allowed
from ankiweb.core.notify.engine import NotifierState


def _login_html(error: bool = False) -> str:
    """Self-contained login page (no /_anki assets, so it works before authentication)."""
    err = (
        "<p style='color:#c0392b;margin:0 0 12px'>Wrong password</p>"
        if error
        else ""
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>ankiweb</title><style>"
        "body{font-family:system-ui,sans-serif;margin:0;min-height:100vh;display:flex;"
        "align-items:center;justify-content:center;background:#f0f0f0}"
        "form{background:#fff;padding:28px 34px;border-radius:10px;text-align:center;"
        "box-shadow:0 2px 10px rgba(0,0,0,.12)}h1{font-size:18px;margin:0 0 18px}"
        "input{font-size:16px;padding:9px 10px;width:220px;box-sizing:border-box}"
        "button{font-size:16px;padding:9px 22px;margin-top:14px;cursor:pointer;"
        "border:0;border-radius:6px;background:#2d7dd2;color:#fff}</style></head><body>"
        "<form method='post' action='/login'><h1>ankiweb</h1>"
        f"{err}"
        "<input type='password' name='password' autofocus placeholder='Password'><br>"
        "<button type='submit'>Enter</button></form></body></html>"
    )


def create_app(
    settings: Settings | None = None,
    service: collection_adapter.CollectionService | None = None,
    hub: BridgeHub | None = None,
    notifier=None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    owns = service is None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        svc = service
        if owns:
            svc = collection_adapter.CollectionService(settings)
            await svc.open()
        h = hub if hub is not None else BridgeHub()
        if svc is not None:
            svc.subscribe(
                lambda flags, initiator: h.broadcast_opchanges(flags, initiator)
            )
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

    app = FastAPI(title="ankiweb", lifespan=lifespan)

    async def host_guard(request, call_next):
        host = request.headers.get("host", "")
        if not host_allowed(host, settings.allowed_hosts):
            return PlainTextResponse("forbidden host", status_code=403)
        return await call_next(request)

    app.add_middleware(BaseHTTPMiddleware, dispatch=host_guard)

    async def auth_guard(request, call_next):
        # Open by default; only gates when ANKIWEB_PASSWORD is set. /login, /logout, /healthz
        # stay reachable so an unauthenticated user can reach the login form.
        if (
            settings.password
            and request.url.path not in ("/login", "/logout", "/healthz")
            and not cookie_ok(request.cookies.get(COOKIE), settings.password)
        ):
            return RedirectResponse("/login", status_code=303)
        return await call_next(request)

    app.add_middleware(BaseHTTPMiddleware, dispatch=auth_guard)

    # Outermost: negotiates zstd/brotli/gzip from Accept-Encoding. text/event-stream (the
    # Datastar SSE streams) is excluded by default, so streaming responses stay unbuffered.
    app.add_middleware(CompressMiddleware)

    # --- specific routes FIRST, media catch-all LAST (Starlette matches in order) ---
    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/login", response_class=HTMLResponse)
    def login_form():
        # already authenticated (or no gate) -> straight to the app
        return HTMLResponse(_login_html())

    @app.post("/login")
    async def login_submit(request: Request):
        form = await request.form()
        pwd = form.get("password", "")
        pwd_str = pwd if isinstance(pwd, str) else ""
        if settings.password and password_ok(pwd_str, settings.password):
            resp = RedirectResponse("/", status_code=303)
            resp.set_cookie(
                COOKIE,
                auth_token(settings.password),
                httponly=True,
                samesite="lax",
                max_age=30 * 86400,
            )
            return resp
        return HTMLResponse(_login_html(error=True), status_code=401)

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
            lambda: app.state.service, lambda: app.state.notifier, lambda: app.state.hub,
            settings=settings,
        )
    )  # GET / + /notify
    app.include_router(
        build_media_router(lambda: app.state.service)
    )  # GET  /{path} — LAST

    return app
