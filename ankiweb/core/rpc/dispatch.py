from __future__ import annotations
from ankiweb.core.rpc.passthrough import PASSTHROUGH, CONCURRENT, camel_to_snake
from ankiweb.core.rpc.custom_handlers import CUSTOM


async def dispatch_backend_rpc(method: str, body: bytes, hub, service) -> bytes:
    """Route one /_anki/<method> call. Raises LookupError for an unknown method — the
    inbound adapter maps that to HTTP 404; any other exception maps to HTTP 500."""
    snake = camel_to_snake(method)
    if method in CUSTOM:
        return await CUSTOM[method](service, body, hub)
    if snake in CONCURRENT:
        return await service.backend_raw_concurrent(snake, body)
    if snake in PASSTHROUGH:
        return await service.backend_raw(snake, body)
    raise LookupError(f"unknown backend RPC method: {method}")
