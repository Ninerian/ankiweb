"""Shared hypermedia helpers for the Datastar screens under ``http_datastar``.

Contract
--------
Targeted elements are updated in place with Datastar fragments (such as deck
tree updates), while errors/signals are sent as Datastar signals and native page
transitions use whole-document redirects per the Tao of Datastar.

* ``elements_response`` -- patch HTML elements into the DOM (optionally targeted).
* ``signals_response``  -- patch signal key/values into the Datastar store.
* ``redirect_response`` -- trigger whole-document navigation via SSE.redirect.
* ``refresh_screen``    -- re-render screen content and morph it into a target selector.
* ``error_response``    -- patch the ``error`` signal with a unified error message.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from datastar_py.attributes import SignalValue
from datastar_py.fastapi import DatastarResponse
from datastar_py.fastapi import ServerSentEventGenerator as SSE

if TYPE_CHECKING:
    from ankiweb.core.ports import CollectionPort

def elements_response(
    elements: str, selector: str | None = None
) -> DatastarResponse:
    """Patch HTML elements into the DOM, preserving default SDK outer patch mode."""
    if selector is not None:
        return DatastarResponse(SSE.patch_elements(elements, selector=selector))
    return DatastarResponse(SSE.patch_elements(elements))


def signals_response(
    signals: dict[str, SignalValue],
) -> DatastarResponse:
    """Patch signals into the Datastar store without altering values or types."""
    return DatastarResponse(SSE.patch_signals(signals))


def redirect_response(location: str) -> DatastarResponse:
    """Trigger whole-document native navigation via SSE redirect."""
    return DatastarResponse(SSE.redirect(location))


async def refresh_screen(
    service: CollectionPort | Any,
    render: Callable[..., str],
    selector: str | None = None,
) -> DatastarResponse:
    """Render ``render(col)`` on the collection thread and patch it into ``selector``."""
    body = await service.run(render)
    return elements_response(body, selector=selector)


def error_response(message: object) -> DatastarResponse:
    """Patch the ``error`` signal with the unified error message."""
    return signals_response({"error": str(message)})

__all__ = [
    "elements_response",
    "error_response",
    "redirect_response",
    "refresh_screen",
    "signals_response",
]
