"""Deck list page and deck creation."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from datastar_py.fastapi import DatastarResponse, read_signals
from datastar_py.fastapi import ServerSentEventGenerator as SSE
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from ankiweb.adapters.inbound.http_app.layout import render_app_page
from ankiweb.adapters.inbound.http_shared.templating import render
from ankiweb.core.app_client.deck_languages import LANGUAGES, DeckLanguageError, choose
from ankiweb.core.app_client.decks import DeckNameError, DeckRow, create_deck, deck_rows
from ankiweb.core.app_client.emoji_picker import EMOJI_GROUPS
from ankiweb.core.app_client.lang import ResolvedLang
from ankiweb.core.app_client.strings import s
from ankiweb.core.i18n import tr
from ankiweb.core.ports import CollectionPort

_QUERY = "$q.trim().toLowerCase()"


async def _read_form_signals(request: Request) -> object:
    """Use the Datastar parser but treat malformed JSON as invalid form input."""
    try:
        return await read_signals(request)
    except ValueError:
        return None


FormSignals = Annotated[object, Depends(_read_form_signals)]


def _form_string(value: object) -> str:
    """Reject malformed form signals before passing them to domain functions."""
    if not isinstance(value, str):
        raise DeckNameError("invalid")
    return value


def _deck_error(
    error: DeckNameError | DeckLanguageError, lang: ResolvedLang, *, src: object = ""
) -> str:
    """Translate domain errors for the active deck form or toast."""
    catalog_lang = lang.catalog_lang
    if isinstance(error, DeckNameError):
        key = (
            f"app_decks_{error.kind}"
            if error.kind in {"not_found", "protected"}
            else f"app_decks_name_{error.kind}"
        )
        return s(key, lang=catalog_lang)
    if error.kind == "same":
        language = s(f"app_lang_{src}", lang=catalog_lang)
        return s("app_decks_lang_same", lang=catalog_lang, language=language)
    if error.kind == "incomplete":
        key = "app_decks_lang_missing_dst" if src else "app_decks_lang_missing_src"
        return s(key, lang=catalog_lang)
    return s("app_decks_lang_pick", lang=catalog_lang)


@dataclass(frozen=True)
class DeckView:
    row: DeckRow
    show: str


def _js_literal(value: object) -> str:
    """Encode JSON for Datastar expressions, including HTML-sensitive characters."""
    return (
        json.dumps(value)
        .replace("$", "\\u0024")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


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
        LANGUAGES=LANGUAGES,
        emoji_groups=EMOJI_GROUPS,
        js_literal=_js_literal,
        fragment=fragment,
        created_id=created_id,
    )


def add_decks_routes(
    router: APIRouter,
    get_service: Callable[[], CollectionPort],
    lang: ResolvedLang,
    static_dir: Path,
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
            static_dir=static_dir,
            scripts=("/shell/static/app/decks.js", "/shell/static/app/install.js"),
            lang=lang,
        )

    @router.post("/decks")
    async def create(payload: FormSignals = None) -> DatastarResponse:
        name = payload.get("newName") if isinstance(payload, dict) else None
        emoji = payload.get("newEmoji") if isinstance(payload, dict) else None
        mode = payload.get("newMode") if isinstance(payload, dict) else None
        src = payload.get("newSrc") if isinstance(payload, dict) else None
        dst = payload.get("newDst") if isinstance(payload, dict) else None
        try:
            valid_name = _form_string(name)
            valid_emoji = _form_string(emoji)
            languages = choose(_form_string(mode), _form_string(src), _form_string(dst))
            service = get_service()
            row = await service.run_op(
                lambda col: create_deck(col, valid_name, valid_emoji, languages),
                initiator="app",
            )
        except (DeckNameError, DeckLanguageError) as error:
            return DatastarResponse(
                SSE.patch_signals({"newError": _deck_error(error, lang, src=src)})
            )

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
                        "newMode": "langs",
                        "newSrc": "",
                        "newDst": "",
                        "newError": "",
                        "newOpen": False,
                    }
                ),
            ]
        )
