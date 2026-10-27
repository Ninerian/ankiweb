from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

import ankiweb.core.ankiconnect_actions.extra_actions  # noqa: F401 — registers /extra_actions/<name>
from ankiweb.adapters.inbound.http_ankiconnect.cors import allow_origin
from ankiweb.adapters.inbound.http_ankiconnect.rest import (
    build_actions_router,
    build_extra_actions_router,
)
from ankiweb.adapters.outbound.anki_collection_adapter import CollectionService
from ankiweb.ankiconnect.config import AnkiConnectConfig
from ankiweb.ankiconnect.dispatch import dispatch_one
from ankiweb.core.ankiconnect_actions.runtime import Runtime
from ankiweb.core.bridge.hub import BridgeHub
from ankiweb.core.config import Settings

# Group descriptions shown under each tag heading in Swagger (/docs).
_OPENAPI_TAGS = [
    {
        "name": "actions",
        "description": (
            "**Native AnkiConnect actions**, documented here for convenience. Each route simply "
            "forwards to the canonical dispatcher, so it works — but for real integrations prefer "
            "calling AnkiConnect the standard way: **`POST /`** with a "
            '`{"action", "version", "params"}` body. That root endpoint is the source of '
            "truth and stays byte-compatible with existing AnkiConnect clients/scripts."
        ),
    },
    {
        "name": "extra_actions",
        "description": (
            "**ankiweb-original actions — NOT part of AnkiConnect.** These exist only here: call "
            "**`POST /extra_actions/<name>`**. They are deliberately unknown to the canonical "
            "`POST /` root (which mirrors upstream AnkiConnect exactly)."
        ),
    },
]


@asynccontextmanager
async def _app_lifespan(
    app: FastAPI,
    settings: Settings,
    service: CollectionService | None,
    config: AnkiConnectConfig,
    hub: Any,
    notifier: Any,
) -> AsyncGenerator[None, None]:
    owns_service = service is None
    svc = service
    if owns_service:
        svc = CollectionService(settings)
        await svc.open()
    app.state.service = svc
    app.state.config = config
    app.state.hub = hub
    app.state.notifier = notifier  # shared NotifierState, or None if not wired
    try:
        yield
    finally:
        if owns_service and svc is not None:
            await svc.close()


def _cors_headers(
    origin: str | None, config: AnkiConnectConfig
) -> tuple[bool, dict[str, str]]:
    allowed, header = allow_origin(origin, config.cors_origin_list)
    return allowed, {
        "Access-Control-Allow-Origin": header,
        "Access-Control-Allow-Headers": "*",
    }


async def _handle_rpc(
    request: Request, app: FastAPI, config: AnkiConnectConfig
) -> JSONResponse:
    origin = request.headers.get("origin")
    allowed, headers = _cors_headers(origin, config)
    try:
        req = await request.json()
    except ValueError:
        req = {}
    if not req:  # empty body → liveness probe
        return JSONResponse({"apiVersion": "AnkiConnect v.6"}, headers=headers)
    action_name = req.get("action") or ""
    if not allowed and action_name != "requestPermission":
        return JSONResponse(
            {"result": None, "error": "origin not allowed"},
            status_code=403,
            headers=headers,
        )
    rt = Runtime(service=app.state.service, config=app.state.config, hub=app.state.hub)
    if action_name == "requestPermission":  # inject CORS result + origin
        req.setdefault("params", {})
        req["params"]["allowed"] = allowed
        req["params"]["origin"] = origin
    reply = await dispatch_one(rt, req)
    return JSONResponse(reply, headers=headers)


def create_ankiconnect_app(
    settings: Settings | None = None,
    service: CollectionService | None = None,
    config: AnkiConnectConfig | None = None,
    hub=None,
    notifier=None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    config = config or AnkiConnectConfig()
    hub = hub if hub is not None else BridgeHub()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with _app_lifespan(app, settings, service, config, hub, notifier):
            yield

    app = FastAPI(
        title="ankiweb-ankiconnect", lifespan=lifespan, openapi_tags=_OPENAPI_TAGS
    )

    @app.options("/")
    async def preflight(request: Request):
        _, headers = _cors_headers(request.headers.get("origin"), config)
        if request.headers.get("access-control-request-private-network") == "true":
            headers["Access-Control-Allow-Private-Network"] = "true"
        return Response(status_code=200, headers=headers)

    @app.get("/")
    async def probe():
        return JSONResponse({"apiVersion": "AnkiConnect v.6"})

    @app.post("/")
    async def rpc(request: Request):
        return await _handle_rpc(request, app, config)

    # Additive typed surface for /docs (one POST /actions/<name> per action). The canonical
    # POST / above is the source of truth; these routes call the same dispatch_one.
    app.include_router(build_actions_router())
    # ankiweb-original actions: documented + callable at /extra_actions/<name> only.
    app.include_router(build_extra_actions_router())

    return app
