"""Shared hypermedia helpers for the Datastar screens under ``http_datastar``.

Contract
--------
Every full page wraps its body in ``<main id="screen">`` (see ``shell.html.jinja``). A
screen is refreshed *in place* by morphing that element's inner HTML instead of reloading
the page, so scroll position, focus and the toolbar survive a mutation.

* ``screen_patch``    -- SSE event that replaces the inner HTML of ``#screen``.
* ``refresh_screen``  -- re-render a screen from the collection and ``screen_patch`` it.
* ``error_response``  -- patch the screen's ``#err`` slot with a unified error fragment.
* ``redirect_response`` -- navigate to another screen (cross-screen moves stay navigations).
* ``is_datastar_request`` -- True when Datastar issued the request (``Datastar-Request``
  header); GET routes use it to return a fragment instead of the full shell page.
"""

from __future__ import annotations

import html
from typing import Any, Callable

from datastar_py.consts import ElementPatchMode
from datastar_py.fastapi import DatastarResponse, ServerSentEventGenerator as SSE
from fastapi import Request

SCREEN_SELECTOR = "#screen"


def is_datastar_request(request: Request) -> bool:
    return request.headers.get("datastar-request", "").lower() == "true"


def screen_patch(body_html: str) -> str:
    """SSE frame replacing the inner HTML of ``#screen`` with ``body_html``."""
    return SSE.patch_elements(
        body_html, selector=SCREEN_SELECTOR, mode=ElementPatchMode.INNER
    )


async def refresh_screen(service: Any, render: Callable[..., str]) -> DatastarResponse:
    """Render ``render(col)`` on the collection thread and morph it into ``#screen``."""
    body = await service.run(render)
    return DatastarResponse(screen_patch(body))


def error_response(message: object) -> DatastarResponse:
    """Patch the ``#err`` slot with the unified, escaped error fragment."""
    err_html = (
        '<div id="err" class="text-error text-sm font-semibold mt-2">'
        f"{html.escape(str(message))}</div>"
    )
    return DatastarResponse(SSE.patch_elements(err_html, selector="#err"))


def redirect_response(path: str) -> DatastarResponse:
    return DatastarResponse(SSE.redirect(path))


__all__ = [
    "SCREEN_SELECTOR",
    "error_response",
    "is_datastar_request",
    "redirect_response",
    "refresh_screen",
    "screen_patch",
]
