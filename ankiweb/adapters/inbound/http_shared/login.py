"""HTTP login helpers shared by the legacy `/login` and the app's `/app/login`.

Both logins set the same `ankiweb_auth` cookie; failure responses may be supplied
by the caller to distinguish app errors from the legacy login.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from datastar_py.fastapi import ReadSignals
from fastapi import Request
from fastapi.responses import RedirectResponse, Response

from ankiweb.adapters.inbound.http_datastar.common import (
    error_response,
    redirect_response,
)
from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.core.auth import COOKIE, auth_token, cookie_ok, password_ok
from ankiweb.core.config import Settings
from ankiweb.core.i18n import tr

logger = logging.getLogger(__name__)


def wrong_password_text() -> str:
    return templating.tr_clean(tr.sync_wrong_pass())


def is_datastar_login(request: Request, payload: ReadSignals) -> bool:
    return bool(
        request.headers.get("datastar-request")
        or "application/json" in request.headers.get("content-type", "")
        or payload
    )


def is_authenticated(request: Request, settings: Settings) -> bool:
    """True when no password is configured or the request carries a valid cookie."""
    return cookie_ok(request.cookies.get(COOKIE), settings.password)


def set_login_cookie(resp, password: str, request: Request):
    resp.set_cookie(
        COOKIE,
        auth_token(password),
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=30 * 86400,
    )
    return resp


def _password_from_mapping(data: dict) -> str:
    val = data.get("password", "")
    return str(val) if val is not None else ""


async def _datastar_login_password(request: Request, payload) -> str:
    pwd_str = ""
    if payload and isinstance(payload, dict):
        pwd_str = _password_from_mapping(payload)
    if not pwd_str:
        try:
            body = await request.json()
            if isinstance(body, dict):
                pwd_str = _password_from_mapping(body)
        except (ValueError, RecursionError):
            logger.warning("Failed to decode JSON body in Datastar login request")
    return pwd_str


async def datastar_login(
    request: Request,
    payload,
    settings: Settings,
    destination: str,
    *,
    render_password_failure: Callable[[str], Response] | None = None,
):
    pwd_str = await _datastar_login_password(request, payload)
    if settings.password and password_ok(pwd_str, settings.password):
        return set_login_cookie(
            redirect_response(destination), settings.password, request
        )
    if render_password_failure is not None:
        return render_password_failure(pwd_str)
    return error_response(wrong_password_text())


async def form_login(
    request: Request,
    settings: Settings,
    destination: str,
    render_failure: Callable[[], Response] | None = None,
    *,
    render_password_failure: Callable[[str], Response] | None = None,
):
    form = await request.form()
    pwd = form.get("password", "")
    pwd_str = pwd if isinstance(pwd, str) else ""
    if settings.password and password_ok(pwd_str, settings.password):
        return set_login_cookie(
            RedirectResponse(destination, status_code=303),
            settings.password,
            request,
        )
    if render_password_failure is not None:
        return render_password_failure(pwd_str)
    if render_failure is None:
        raise TypeError("A failure renderer is required")
    return render_failure()
