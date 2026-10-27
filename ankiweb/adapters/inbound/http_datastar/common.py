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

import re
import unicodedata
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from urllib.parse import SplitResult, quote, urlsplit, urlunsplit

from datastar_py.attributes import SignalValue
from datastar_py.fastapi import DatastarResponse
from datastar_py.fastapi import ServerSentEventGenerator as SSE

if TYPE_CHECKING:
    from ankiweb.core.ports import CollectionPort


def _url_origin(url: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return None

    scheme = parsed.scheme.lower()
    hostname = parsed.hostname
    if (
        scheme not in ("http", "https")
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None

    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, hostname.casefold(), port


def _normalize_return_url(target: str) -> str:
    encoded = quote(target, safe="/:?#[]@!$&()*+,;=-._~%")
    return re.sub(r"%(?![0-9A-Fa-f]{2})", "%25", encoded)


def _same_origin_return_url(
    target: str, request_url: str | None, parsed: SplitResult
) -> str | None:
    if request_url is None:
        return None
    target_origin = _url_origin(target)
    if target_origin is None or target_origin != _url_origin(request_url):
        return None
    path = urlunsplit(("", "", parsed.path or "/", parsed.query, parsed.fragment))
    return safe_return_url(path)


def safe_return_url(target: object, *, request_url: str | None = None) -> str | None:
    """Return a safe same-app path, optionally reducing a same-origin Referer."""
    if (
        not isinstance(target, str)
        or not target
        or "\\" in target
        or any(unicodedata.category(char) == "Cc" for char in target)
        or target.startswith("//")
    ):
        return None

    try:
        parsed = urlsplit(target)
    except ValueError:
        return None

    has_origin = bool(parsed.scheme or parsed.netloc)
    if request_url is not None and not has_origin:
        return None
    if has_origin:
        return _same_origin_return_url(target, request_url, parsed)

    if not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return None
    return _normalize_return_url(target)


def elements_response(elements: str, selector: str | None = None) -> DatastarResponse:
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
    "safe_return_url",
    "signals_response",
]
