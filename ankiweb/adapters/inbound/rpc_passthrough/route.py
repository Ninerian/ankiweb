from __future__ import annotations
from fastapi import APIRouter, Request
from fastapi.responses import Response, PlainTextResponse
from ankiweb.core.rpc.dispatch import dispatch_backend_rpc

BINARY = "application/binary"


def build_router(get_service, get_hub=None) -> APIRouter:
    router = APIRouter()

    @router.post("/_anki/{method}")
    async def rpc(method: str, request: Request) -> Response:
        if request.headers.get("content-type") != BINARY:
            return PlainTextResponse("bad content type", status_code=403)
        body = await request.body()
        service = get_service()
        hub = get_hub() if get_hub is not None else None
        try:
            out = await dispatch_backend_rpc(method, body, hub, service)
        except LookupError:
            return PlainTextResponse("not found", status_code=404)
        except Exception as exc:
            return PlainTextResponse(str(exc), status_code=500)
        if not out:
            return Response(status_code=204)
        return Response(content=bytes(out), media_type=BINARY)

    return router
