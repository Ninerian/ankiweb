"""App login routes using the shared authentication cookie."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ankiweb.adapters.inbound.http_app.layout import render_app_page
from ankiweb.adapters.inbound.http_datastar.common import redirect_response
from ankiweb.adapters.inbound.http_shared.login import (
    datastar_login,
    form_login,
    is_authenticated,
    is_datastar_login,
    wrong_password_text,
)
from ankiweb.adapters.inbound.http_shared.templating import render, tr_clean
from ankiweb.core.app_client.lang import ResolvedLang
from ankiweb.core.config import Settings
from ankiweb.core.i18n import tr


def add_login_routes(
    router: APIRouter, settings: Settings, lang: ResolvedLang, static_dir: Path
) -> None:
    """Attach app login routes to the existing guarded app router."""

    def login_page(error_text: str = "", status_code: int = 200) -> HTMLResponse:
        body = render("app/login.html.jinja", app_lang=lang, error_text=error_text)
        return HTMLResponse(
            render_app_page(
                tr_clean(tr.sync_log_in_button()),
                body,
                active="",
                static_dir=static_dir,
                lang=lang,
                show_error_toast=False,
            ),
            status_code=status_code,
        )

    @router.get("/login", response_class=HTMLResponse)
    def login_form(request: Request) -> Response:
        if is_authenticated(request, settings):
            return RedirectResponse("/app/", status_code=303)
        return login_page()

    @router.post("/login")
    async def login_submit(request: Request) -> Response:
        datastar = is_datastar_login(request, None)
        if is_authenticated(request, settings):
            if datastar:
                return redirect_response("/app/")
            return RedirectResponse("/app/", status_code=303)
        if datastar:
            return await datastar_login(request, None, settings, "/app/")
        return await form_login(
            request,
            settings,
            "/app/",
            lambda: login_page(wrong_password_text(), status_code=401),
        )
