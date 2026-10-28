"""Card creation page and server-rendered preview."""

from collections.abc import Callable

from anki.collection import Collection
from anki.decks import DeckId
from datastar_py.fastapi import DatastarResponse
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from ankiweb.adapters.inbound.http_app.layout import render_app_page
from ankiweb.adapters.inbound.http_app.session import get_session
from ankiweb.adapters.inbound.http_datastar.common import elements_response
from ankiweb.adapters.inbound.http_shared.templating import render
from ankiweb.core.app_client.lang import resolve_lang
from ankiweb.core.app_client.vocab import (
    NOTETYPE_NAME,
    ensure_vocab_model,
    escape_field,
    highlight_example,
)
from ankiweb.core.config import Settings
from ankiweb.core.i18n import tr
from ankiweb.core.ports import CollectionPort


def _deck_name(col: Collection, deck_id: int) -> str | None:
    deck = col.decks.get(DeckId(deck_id), default=False)
    if deck is None:
        return None
    ensure_vocab_model(col)
    return deck["name"]


def build_add_router(
    get_service: Callable[[], CollectionPort], settings: Settings
) -> APIRouter:
    router = APIRouter()
    lang = resolve_lang(settings)

    @router.get("/add")
    async def add_page(request: Request) -> Response:
        raw_deck = request.query_params.get("deck", "")
        try:
            deck_id = int(raw_deck)
        except ValueError:
            return RedirectResponse("/app/", status_code=303)
        if not 0 < deck_id < 2**63:
            return RedirectResponse("/app/", status_code=303)
        deck_name = await get_service().run(lambda col: _deck_name(col, deck_id))
        if deck_name is None:
            return RedirectResponse("/app/", status_code=303)
        body = render(
            "app/add.html.jinja",
            app_lang=lang,
            deck_id=deck_id,
            note_type=NOTETYPE_NAME,
            deck_name=deck_name,
            preview={},
        )
        response = HTMLResponse(
            render_app_page(
                tr.actions_add(),
                body,
                active="add",
                scripts=("/shell/static/app/add.js",),
                lang=lang,
            )
        )
        get_session(request, response)
        return response

    @router.post("/add/preview")
    async def preview(request: Request) -> DatastarResponse:
        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {}
        values = {
            key: value if isinstance(value := payload.get(key), str) else ""
            for key in ("front", "back", "hint", "example")
        }
        example_html = highlight_example(escape_field(values["example"]))
        fragment = render(
            "app/add.html.jinja",
            app_lang=lang,
            preview_only=True,
            preview=values,
            example_html=example_html,
        )
        return elements_response(fragment)

    return router
