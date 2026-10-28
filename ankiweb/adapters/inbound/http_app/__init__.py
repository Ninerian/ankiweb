from collections.abc import Callable

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from ankiweb.adapters.inbound.http_app.decks import add_decks_routes
from ankiweb.adapters.inbound.http_app.layout import render_app_page
from ankiweb.adapters.inbound.http_shared.templating import render
from ankiweb.core.app_client.lang import resolve_lang
from ankiweb.core.config import Settings
from ankiweb.core.ports import CollectionPort


def build_app_router(
    get_service: Callable[[], CollectionPort], settings: Settings
) -> APIRouter:
    router = APIRouter(prefix="/app")
    lang = resolve_lang(settings)

    @router.get("/ping", response_class=HTMLResponse)
    def ping() -> str:
        body = render("app/ping.html.jinja", app_lang=lang)
        return render_app_page("AnkiWeb", body, active="", lang=lang)

    add_decks_routes(router, get_service, lang)
    return router
