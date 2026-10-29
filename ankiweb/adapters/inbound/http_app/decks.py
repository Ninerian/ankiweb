"""Deck list page and deck creation."""

import json
from collections.abc import Callable
from dataclasses import dataclass

from datastar_py.fastapi import DatastarResponse, ReadSignals
from datastar_py.fastapi import ServerSentEventGenerator as SSE
from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from ankiweb.adapters.inbound.http_app.layout import render_app_page
from ankiweb.adapters.inbound.http_shared.templating import render
from ankiweb.core.app_client.decks import DeckNameError, DeckRow, create_deck, deck_rows
from ankiweb.core.app_client.emoji_picker import EMOJI_GROUPS
from ankiweb.core.app_client.lang import ResolvedLang
from ankiweb.core.app_client.strings import s
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


def _render_decks(
    rows: list[DeckRow],
    lang: ResolvedLang,
    *,
    fragment: str = "page",
    created_id: int = 0,
) -> str:
    return render(
        "app/decks.html.jinja",
        app_lang=lang,
        views=_views(rows),
        no_match=_no_match(rows),
        emoji_groups=EMOJI_GROUPS,
        js_literal=_js_literal,
        fragment=fragment,
        created_id=created_id,
    )


def add_decks_routes(
    router: APIRouter, get_service: Callable[[], CollectionPort], lang: ResolvedLang
) -> None:
    """Attach GET /app/ and the /app redirect to the router prefixed with /app."""

    @router.get("", include_in_schema=False)
    def app_root() -> RedirectResponse:
        return RedirectResponse("/app/", status_code=307)

    @router.get("/", response_class=HTMLResponse)
    async def decks(response: Response) -> str:
        # Counts change while studying; never reuse on back-navigation.
        response.headers["Cache-Control"] = "no-store"
        rows = await get_service().run(deck_rows)
        body = _render_decks(rows, lang)
        return render_app_page(
            tr.actions_decks(),
            body,
            active="decks",
            scripts=("/shell/static/app/decks.js",),
            lang=lang,
        )

    @router.post("/decks")
    async def create(payload: ReadSignals = None) -> DatastarResponse:
        name = payload.get("newName") if isinstance(payload, dict) else None
        emoji = payload.get("newEmoji") if isinstance(payload, dict) else None
        try:
            if not isinstance(name, str) or not isinstance(emoji, str):
                raise DeckNameError("invalid")
            service = get_service()
            row = await service.run_op(
                lambda col: create_deck(col, name, emoji), initiator="app"
            )
        except DeckNameError as error:
            message = s(f"app_decks_name_{error.kind}", lang=lang.catalog_lang)
            return DatastarResponse(SSE.patch_signals({"newError": message}))

        rows = await service.run(deck_rows)
        return DatastarResponse(
            [
                SSE.patch_elements(
                    _render_decks(
                        rows, lang, fragment="content", created_id=row.deck_id
                    ),
                    selector="#decks-content",
                ),
                SSE.patch_elements(
                    _render_decks(rows, lang, fragment="toast", created_id=row.deck_id),
                    selector="#toast",
                ),
                SSE.patch_signals(
                    {
                        "q": "",
                        "newName": "",
                        "newEmoji": "📚",
                        "newError": "",
                        "newOpen": False,
                    }
                ),
            ]
        )
