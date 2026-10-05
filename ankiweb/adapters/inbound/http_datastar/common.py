"""Shared hypermedia helpers for the Datastar screens under ``http_datastar``.

Contract
--------
Targeted elements are updated in place with Datastar fragments (such as deck
tree updates), while errors are sent as Datastar signals and page transitions
use standard backend redirects and native anchors per the Tao of Datastar.

* ``refresh_screen``  -- re-render screen content and morph it into a target selector.
* ``error_response``  -- patch the ``error`` signal with a unified error message.
"""

from __future__ import annotations

from typing import Any, Callable

from datastar_py.fastapi import DatastarResponse, ServerSentEventGenerator as SSE


async def refresh_screen(
    service: Any,
    render: Callable[..., str],
    selector: str | None = None,
) -> DatastarResponse:
    """Render ``render(col)`` on the collection thread and patch it into ``selector``."""
    body = await service.run(render)
    if selector is not None:
        return DatastarResponse(SSE.patch_elements(body, selector=selector))
    return DatastarResponse(SSE.patch_elements(body))


def error_response(message: object) -> DatastarResponse:
    """Patch the ``error`` signal with the unified error message."""
    return DatastarResponse(SSE.patch_signals({"error": str(message)}))


__all__ = [
    "error_response",
    "refresh_screen",
]
