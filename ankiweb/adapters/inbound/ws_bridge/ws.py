"""WebSocket endpoint for Anki desktop bridge compatibility (/ws).

Transport boundary:
- Serves native reviewer/legacy screen pycmd commands and server push calls.
- Dispatches commands to BridgeHub and registers client contexts.
- Broadcasts opchanges flags across connected sessions for cross-screen sync.
- Modern Datastar in-page actions, field saves, and queries use HTTP/SSE, not this socket.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from anki.errors import AnkiException
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ankiweb.core.auth import COOKIE, cookie_ok
from ankiweb.core.config import host_allowed

if TYPE_CHECKING:
    from ankiweb.core.bridge.hub import BridgeHub

logger = logging.getLogger(__name__)


async def _dispatch_command(
    websocket: WebSocket, hub: BridgeHub, context: str, msg: dict[str, Any]
) -> None:
    try:
        result = await hub.dispatch_cmd(context, msg.get("arg", ""))
    except (AnkiException, OSError, RuntimeError, TypeError, ValueError):
        logger.exception("WebSocket command dispatch failed for context %s", context)
        result = None  # a handler error must not drop the session
    if msg.get("id") is not None:
        await websocket.send_json({"type": "result", "id": msg["id"], "value": result})


async def _process_message(
    websocket: WebSocket, hub: BridgeHub, context: str, msg: dict[str, Any]
) -> None:
    mtype = msg.get("type")
    if mtype == "cmd":
        await _dispatch_command(websocket, hub, context, msg)
    elif mtype == "result":
        mid = msg.get("id")
        if mid is not None:
            hub.resolve(mid, msg.get("value"))
    elif mtype == "ready":
        pass  # domDone handshake; per-screen logic handles buffering


async def _receive_messages(websocket: WebSocket, hub: BridgeHub, context: str) -> None:
    while True:
        # A bad-JSON frame, non-object payload, or handler error must not drop the socket.
        try:
            msg = await websocket.receive_json()
        except WebSocketDisconnect:
            raise
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Ignoring malformed WebSocket frame: %s", exc)
            continue
        if not isinstance(msg, dict):
            continue
        await _process_message(websocket, hub, context, msg)


def build_router(get_hub, allowed_hosts=(), password="") -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket, context: str = "default"):
        # BaseHTTPMiddleware (host + auth guards) does NOT cover WS upgrades — check here too.
        host = websocket.headers.get("host", "")
        if not host_allowed(host, allowed_hosts):
            await websocket.close(code=1008)
            return
        if not cookie_ok(websocket.cookies.get(COOKIE), password):
            await websocket.close(code=1008)
            return
        hub = get_hub()
        await websocket.accept()
        hub.register(context, websocket)
        hub.ui_state.current_screen = context
        try:
            await _receive_messages(websocket, hub, context)
        except WebSocketDisconnect:
            pass
        finally:
            hub.unregister(context, websocket)

    return router
