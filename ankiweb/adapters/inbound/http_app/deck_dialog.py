"""Transport helpers shared by the deck-list dialogs.

Dialogs are server-rendered ``<dialog id="deck-dialog" data-token="…">`` elements
inside ``#deck-dialog-host``. The browser submits their native ``<form>`` as
form-encoded fields (Datastar ``contentType: 'form'``); no signals carry data. Every
patch aimed at an open dialog is scoped to that dialog's token, so a response that
arrives after the dialog was closed or replaced matches nothing and is dropped.
"""

import re
import secrets

from datastar_py.consts import ElementPatchMode
from datastar_py.fastapi import DatastarResponse
from datastar_py.fastapi import ServerSentEventGenerator as SSE
from fastapi import Request
from starlette.exceptions import HTTPException as StarletteHTTPException

DIALOG_HOST = "#deck-dialog-host"
_TOKEN = re.compile(r"[0-9a-f]{16}")
_FORM_TYPES = ("application/x-www-form-urlencoded", "multipart/form-data")


def new_token() -> str:
    """Identify one rendered dialog instance."""
    return secrets.token_hex(8)


def valid_token(value: object) -> str | None:
    """Return a client-echoed token only if it is safe to put into a selector."""
    return value if isinstance(value, str) and _TOKEN.fullmatch(value) else None


async def read_fields(request: Request) -> dict[str, str]:
    """Query-string and form-body fields as plain strings; the body wins."""
    fields = dict(request.query_params)
    if any(
        kind in request.headers.get("content-type", "").lower() for kind in _FORM_TYPES
    ):
        form = await request.form()
        fields.update(
            (key, value) for key, value in form.items() if isinstance(value, str)
        )
    return fields


def no_patch() -> DatastarResponse:
    """A well-formed, empty event stream (stale or unusable request)."""
    return DatastarResponse(
        [], status_code=200, headers=DatastarResponse.default_headers
    )


def show_dialog(html: str):
    """Show a freshly rendered dialog, replacing any previous one."""
    return SSE.patch_elements(html, selector=DIALOG_HOST, mode=ElementPatchMode.INNER)


def patch_in_dialog(token: object, target_id: str, html: str):
    """Morph ``#target_id`` inside one dialog instance; ``None`` for an unsafe token."""
    safe = valid_token(token)
    if safe is None:
        return None
    return SSE.patch_elements(
        html, selector=f'#deck-dialog[data-token="{safe}"] #{target_id}'
    )


def close_dialog(token: object):
    """Close one dialog instance (native ``close()``, focus is restored by the browser)."""
    safe = valid_token(token)
    if safe is None:
        return None
    return SSE.execute_script(
        f"document.querySelector('#deck-dialog[data-token=\"{safe}\"]')?.close()"
    )


def refresh_decks(created_id: int = 0):
    """Ask the page to re-run its current search (live filter, same URL as typing).

    Mutations never patch the result list themselves: a refresh request shares the
    search URL, so Datastar's same-URL cancellation lets the newest request win.
    """
    return SSE.execute_script(
        "window.dispatchEvent(new CustomEvent('ankiweb:decks-refresh',"
        f"{{detail:{{created:{int(created_id)}}}}}))"
    )


async def form_fields(request: Request) -> dict[str, str] | None:
    """Strict form-POST body: unique plain-string fields, no query fallback.

    ``None`` for any other content type, duplicate field names, file uploads or a
    body the parser rejects.
    """
    if not any(
        kind in request.headers.get("content-type", "").lower() for kind in _FORM_TYPES
    ):
        return None
    try:
        form = await request.form()
    except StarletteHTTPException:
        return None
    fields: dict[str, str] = {}
    for key, value in form.multi_items():
        if key in fields or not isinstance(value, str):
            return None
        fields[key] = value
    return fields
