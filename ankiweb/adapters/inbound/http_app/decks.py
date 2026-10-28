"""Deck list page: GET /app/ (and /app redirecting to it)."""

import json
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

from ankiweb.adapters.inbound.http_app.layout import render_app_page
from ankiweb.adapters.inbound.http_shared.templating import render
from ankiweb.core.app_client.decks import DeckRow, deck_rows
from ankiweb.core.app_client.lang import ResolvedLang
from ankiweb.core.i18n import tr
from ankiweb.core.ports import CollectionPort

_QUERY = "$q.trim().toLowerCase()"


@dataclass(frozen=True)
class DeckView:
    row: DeckRow
    show: str


def _js_literal(value: object) -> str:
    """Encode a value as a JS literal that Datastar's `$signal` rewriting skips."""
    return json.dumps(value).replace("$", "\\u0024")


def _views(rows: list[DeckRow]) -> list[DeckView]:
    return [
        DeckView(row, f"{_js_literal(row.name.lower())}.includes({_QUERY})")
        for row in rows
    ]


def _no_match(rows: list[DeckRow]) -> str:
    names = _js_literal([row.name.lower() for row in rows])
    return f"{_QUERY} !== '' && !{names}.some(n => n.includes({_QUERY}))"


def add_decks_routes(
    router: APIRouter, get_service: Callable[[], CollectionPort], lang: ResolvedLang
) -> None:
    """Attach GET /app/ and the /app redirect to the router prefixed with /app."""

    @router.get("", include_in_schema=False)
    def app_root() -> RedirectResponse:
        return RedirectResponse("/app/", status_code=307)

    @router.get("/", response_class=HTMLResponse)
    async def decks() -> str:
        rows = await get_service().run(deck_rows)
        body = render(
            "app/decks.html.jinja",
            app_lang=lang,
            views=_views(rows),
            no_match=_no_match(rows),
        )
        return render_app_page(tr.actions_decks(), body, active="decks", lang=lang)
