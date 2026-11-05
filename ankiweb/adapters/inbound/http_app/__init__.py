from collections.abc import Callable

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from ankiweb.adapters.inbound.http_app.decks import add_decks_routes
from ankiweb.adapters.inbound.http_app.edit import build_edit_router
from ankiweb.adapters.inbound.http_app.layout import render_app_page
from ankiweb.adapters.inbound.http_app.login import add_login_routes
from ankiweb.adapters.inbound.http_app.origin_guard import reject_cross_site_writes
from ankiweb.adapters.inbound.http_app.review import make_review_router
from ankiweb.adapters.inbound.http_shared.templating import render
from ankiweb.core.app_client.lang import resolve_lang
from ankiweb.core.config import Settings
from ankiweb.core.ports import CollectionPort


def build_app_router(
    get_service: Callable[[], CollectionPort], settings: Settings
) -> APIRouter:
    router = APIRouter(prefix="/app", dependencies=[Depends(reject_cross_site_writes)])
    lang = resolve_lang(settings)
    static_dir = settings.shell_dir / "static"
    add_login_routes(router, settings, lang, static_dir)
    router.include_router(make_review_router(get_service, settings))

    @router.get("/ping", response_class=HTMLResponse)
    def ping() -> str:
        body = render("app/ping.html.jinja", app_lang=lang)
        return render_app_page(
            "AnkiWeb", body, active="", static_dir=static_dir, lang=lang
        )

    add_decks_routes(router, get_service, lang, static_dir)
    router.include_router(build_edit_router(get_service, settings))
    return router
