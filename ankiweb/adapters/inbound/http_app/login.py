"""App login routes using the shared authentication cookie."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ankiweb.adapters.inbound.http_app.layout import render_app_page
from ankiweb.adapters.inbound.http_datastar.common import (
    redirect_response,
    signals_response,
)
from ankiweb.adapters.inbound.http_shared.login import (
    datastar_login,
    form_login,
    is_authenticated,
    is_datastar_login,
)
from ankiweb.adapters.inbound.http_shared.templating import render, tr_clean
from ankiweb.core.app_client.lang import ResolvedLang
from ankiweb.core.app_client.strings import s
from ankiweb.core.config import Settings
from ankiweb.core.i18n import tr


def add_login_routes(
    router: APIRouter, settings: Settings, lang: ResolvedLang, static_dir: Path
) -> None:
    """Attach app login routes to the existing guarded app router."""

    def login_page(
        error_text: str = "", error_kind: str = "", status_code: int = 200
    ) -> HTMLResponse:
        body = render(
            "app/login.html.jinja",
            app_lang=lang,
            error_text=error_text,
            error_kind=error_kind,
        )
        return HTMLResponse(
            render_app_page(
                tr_clean(tr.sync_log_in_button()),
                body,
                active="",
                static_dir=static_dir,
                scripts=("/shell/static/app/login.js",),
                lang=lang,
                show_error_toast=False,
            ),
            status_code=status_code,
        )

    def failure_details(password: str) -> tuple[str, str]:
        kind = "empty" if password == "" else "wrong"
        return s(f"app_login_error_{kind}", lang=lang.catalog_lang), kind

    def form_failure(password: str) -> HTMLResponse:
        text, kind = failure_details(password)
        return login_page(text, kind, status_code=401)

    def datastar_failure(password: str) -> Response:
        text, kind = failure_details(password)
        return signals_response({"error": text, "errorKind": kind})

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
            return await datastar_login(
                request,
                None,
                settings,
                "/app/",
                render_password_failure=datastar_failure,
            )
        return await form_login(
            request,
            settings,
            "/app/",
            render_password_failure=form_failure,
        )
