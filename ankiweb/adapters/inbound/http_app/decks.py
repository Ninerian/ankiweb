"""Deck list page and search."""

from collections.abc import Callable
from html import escape
from pathlib import Path
from uuid import uuid4

from datastar_py.consts import ElementPatchMode
from datastar_py.fastapi import DatastarResponse
from datastar_py.fastapi import ServerSentEventGenerator as SSE
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from ankiweb.adapters.inbound.http_app import deck_dialog
from ankiweb.adapters.inbound.http_app.layout import render_app_page
from ankiweb.adapters.inbound.http_shared.templating import render
from ankiweb.core.app_client.deck_languages import (
    LANGUAGES,
    DeckLanguageError,
    LanguageErrorKind,
)
from ankiweb.core.app_client.decks import DeckNameError, DeckRow, deck_rows
from ankiweb.core.app_client.emoji_picker import EMOJI_GROUPS
from ankiweb.core.app_client.lang import ResolvedLang
from ankiweb.core.app_client.strings import s
from ankiweb.core.i18n import tr
from ankiweb.core.ports import CollectionPort


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
    if error.kind == LanguageErrorKind.SAME:
        language = s(f"app_lang_{src}", lang=catalog_lang)
        return s("app_decks_lang_same", lang=catalog_lang, language=language)
    if error.kind == LanguageErrorKind.INCOMPLETE:
        key = "app_decks_lang_missing_dst" if src else "app_decks_lang_missing_src"
        return s(key, lang=catalog_lang)
    return s("app_decks_lang_pick", lang=catalog_lang)


# ECMAScript String.trim() whitespace, deliberately not Python's broader strip().
_JS_TRIM = (
    "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)


def _filter_rows(rows: list[DeckRow], query: str) -> list[DeckRow]:
    # Match the former JS query trim/lower against Python-lowered display names.
    # lower(), unlike casefold(), preserves e.g. the distinction between ß and ss.
    needle = query.strip(_JS_TRIM).lower()
    return [row for row in rows if needle in row.name.lower()]


def _render_decks(
    rows: list[DeckRow],
    lang: ResolvedLang,
    *,
    fragment: str = "page",
    created_id: int = 0,
    query: str = "",
) -> str:
    return render(
        "app/decks.html.jinja",
        app_lang=lang,
        rows=rows,
        matches=_filter_rows(rows, query),
        LANGUAGES=LANGUAGES,
        emoji_groups=EMOJI_GROUPS,
        fragment=fragment,
        created_id=created_id,
        q=query,
    )


def results_patch(
    rows: list[DeckRow], lang: ResolvedLang, query: str, *, created_id: int = 0
):
    """Render the currently filtered list, independently of dialog drafts."""
    return SSE.patch_elements(
        _render_decks(
            rows, lang, fragment="results", created_id=created_id, query=query
        ),
        selector="#deck-results",
    )


def search_form_patch(lang: ResolvedLang, query: str = ""):
    """Replace the search form so resetting also resets its live input value."""
    return SSE.patch_elements(
        _render_decks([], lang, fragment="search", query=query),
        selector="#deck-search-form",
        mode=ElementPatchMode.REPLACE,
    )


def toast_patch(message: str):
    """Use a fresh keyed child to restart repeated toast animations."""
    html = (
        '<div id="toast" class="toast toast-top toast-center pointer-events-none z-50" '
        'role="status" aria-live="polite">'
        f'<div id="deck-toast-{uuid4().hex}" class="alert deck-toast">'
        f"{escape(message)}</div></div>"
    )
    return SSE.patch_elements(html, selector="#toast")


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

    _add_search_route(router, get_service, lang)


def _add_search_route(
    router: APIRouter, get_service: Callable[[], CollectionPort], lang: ResolvedLang
) -> None:

    @router.get("/decks/search")
    async def search(request: Request) -> DatastarResponse:
        fields = await deck_dialog.read_fields(request)
        rows = await get_service().run(deck_rows)
        raw_created = request.headers.get("X-Deck-Created", "")
        created_id = (
            int(raw_created)
            if raw_created.isascii()
            and raw_created.isdecimal()
            and len(raw_created) <= 19
            else 0
        )
        return DatastarResponse(
            results_patch(rows, lang, fields.get("q", ""), created_id=created_id)
        )
