from __future__ import annotations

import json
import logging

from anki.errors import AnkiException
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ankiweb.core.auth import COOKIE, cookie_ok
from ankiweb.core.config import host_allowed

logger = logging.getLogger(__name__)


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
            while True:
                # Malformed-frame hardening: a bad-JSON frame, a non-object payload, a
                # missing field, or a handler error must NOT drop the live socket.
                try:
                    msg = await websocket.receive_json()
                except WebSocketDisconnect:
                    raise
                except (json.JSONDecodeError, ValueError) as exc:
                    logger.warning("Ignoring malformed WebSocket frame: %s", exc)
                    continue  # malformed JSON frame — skip, keep the connection alive
                if not isinstance(msg, dict):
                    continue
                mtype = msg.get("type")
                if mtype == "cmd":
                    try:
                        result = await hub.dispatch_cmd(context, msg.get("arg", ""))
                    except (AnkiException, OSError, RuntimeError, TypeError, ValueError):
                        logger.exception("WebSocket command dispatch failed for context %s", context)
                        result = None  # a handler error must not drop the session
                    if msg.get("id") is not None:
                        await websocket.send_json(
                            {"type": "result", "id": msg["id"], "value": result}
                        )
                elif mtype == "result":
                    mid = msg.get("id")
                    if mid is not None:
                        hub.resolve(mid, msg.get("value"))
                elif mtype == "ready":
                    pass  # domDone handshake; per-screen logic handles buffering
        except WebSocketDisconnect:
            pass
        finally:
            hub.unregister(context, websocket)

    return router
