from collections.abc import Callable

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from ankiweb.adapters.inbound.http_app.layout import render_app_page
from ankiweb.adapters.inbound.http_shared.templating import render
from ankiweb.core.ports import CollectionPort


def build_app_router(get_service: Callable[[], CollectionPort]) -> APIRouter:
    router = APIRouter(prefix="/app")

    @router.get("/ping", response_class=HTMLResponse)
    def ping() -> str:
        return render_app_page("AnkiWeb", render("app/ping.html.jinja"), active="")

    return router
