"""Card creation page, preview, and per-session additions."""

import logging
from collections.abc import Callable
from itertools import islice
from json import JSONDecodeError

from anki.collection import Collection
from anki.decks import DeckId
from anki.errors import AnkiException
from anki.notes import NoteId
from datastar_py.fastapi import DatastarResponse
from datastar_py.fastapi import ServerSentEventGenerator as SSE
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from ankiweb.adapters.inbound.http_app.layout import render_app_page
from ankiweb.adapters.inbound.http_app.session import get_session
from ankiweb.adapters.inbound.http_datastar.common import (
    elements_response,
    error_response,
)
from ankiweb.adapters.inbound.http_shared.templating import render
from ankiweb.core.app_client.lang import resolve_lang
from ankiweb.core.app_client.strings import s
from ankiweb.core.app_client.study import StudySession
from ankiweb.core.app_client.vocab import (
    NOTETYPE_NAME,
    DuplicateNote,
    add_vocab_note,
    ensure_vocab_model,
    escape_field,
    highlight_example,
    read_vocab_note,
)
from ankiweb.core.config import Settings
from ankiweb.core.i18n import tr
from ankiweb.core.ports import CollectionPort

logger = logging.getLogger(__name__)


def _parse_deck(request: Request) -> int | None:
    try:
        deck_id = int(request.query_params.get("deck", ""))
    except ValueError:
        return None
    return deck_id if 0 < deck_id < 2**63 else None


def _with_session_cookie(response: Response, cookie_response: Response) -> Response:
    if "set-cookie" in cookie_response.headers:
        response.headers.append("set-cookie", cookie_response.headers["set-cookie"])
    return response


def _commit_values(payload: dict) -> dict[str, str] | None:
    values: dict[str, str] = {}
    for key in ("front", "back", "hint", "example"):
        value = payload.get(key, "")
        if not isinstance(value, str):
            return None
        values[key] = value
    if not values["front"].strip() or not values["back"].strip():
        return None
    return values


def _deck_name(col: Collection, deck_id: int) -> str | None:
    deck = col.decks.get(DeckId(deck_id), default=False)
    if deck is None:
        return None
    ensure_vocab_model(col)
    return deck["name"]


class _AddRoutes:
    def __init__(
        self, get_service: Callable[[], CollectionPort], settings: Settings
    ) -> None:
        self.get_service = get_service
        self.lang = resolve_lang(settings)

    def added_cards(
        self, col: Collection, session: StudySession, deck_id: int
    ) -> tuple[list[dict[str, str | int]], int]:
        ids = session.added_note_ids
        if not ids:
            return [], 0
        db = col.db
        if db is None:
            raise RuntimeError("Collection database is not available")

        present: set[int] = set()
        in_deck: set[int] = set()
        for start in range(0, len(ids), 32):
            batch = ids[start : start + 32]
            rows = db.all(
                "select n.id, exists(select 1 from cards c where c.nid = n.id "
                "and c.did = ?) from notes n where n.id in ("
                "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
                "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                deck_id,
                *batch,
                *([None] * (32 - len(batch))),
            )
            for nid, matches in rows:
                present.add(nid)
                if matches:
                    in_deck.add(nid)

        if len(present) != len(ids):
            ids[:] = [nid for nid in ids if nid in present]
        recent_ids = list(islice((nid for nid in reversed(ids) if nid in in_deck), 4))
        cards = [
            {"nid": nid, **read_vocab_note(col, NoteId(nid))}
            for nid in reversed(recent_ids)
        ]
        return cards, len(in_deck)

    async def add_page(self, request: Request) -> Response:
        deck_id = _parse_deck(request)
        if deck_id is None:
            return RedirectResponse("/app/", status_code=303)
        deck_name = await self.get_service().run(lambda col: _deck_name(col, deck_id))
        if deck_name is None:
            return RedirectResponse("/app/", status_code=303)
        cookie_response = Response()
        session = get_session(request, cookie_response)
        cards, count = await self.get_service().run(
            lambda col: self.added_cards(col, session, deck_id)
        )
        body = render(
            "app/add.html.jinja",
            app_lang=self.lang,
            deck_id=deck_id,
            note_type=NOTETYPE_NAME,
            deck_name=deck_name,
            cards=cards,
            count=count,
            preview={},
        )
        response = HTMLResponse(
            render_app_page(
                tr.actions_add(),
                body,
                active="add",
                scripts=("/shell/static/app/add.js",),
                lang=self.lang,
            )
        )
        return _with_session_cookie(response, cookie_response)

    async def preview(self, request: Request) -> DatastarResponse:
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
            app_lang=self.lang,
            preview_only=True,
            preview=values,
            example_html=example_html,
        )
        return elements_response(fragment)

    async def commit(self, request: Request) -> Response:
        deck_id = _parse_deck(request)
        if deck_id is None:
            return RedirectResponse("/app/", status_code=303)
        try:
            exists = await self.get_service().run(
                lambda col: col.decks.get(DeckId(deck_id), default=False) is not None
            )
        except AnkiException:
            logger.exception("Failed to validate add deck")
            return error_response(s("app_add_save_failed", lang=self.lang.catalog_lang))
        if not exists:
            return RedirectResponse("/app/", status_code=303)
        values = await self.commit_input(request)
        if isinstance(values, Response):
            return values
        return await self.save(request, deck_id, values)

    async def commit_input(self, request: Request) -> dict[str, str] | Response:
        try:
            payload = await request.json()
        except (JSONDecodeError, UnicodeDecodeError):
            payload = None
        if not isinstance(payload, dict):
            return error_response(
                s("app_add_both_required", lang=self.lang.catalog_lang)
            )
        nid = payload.get("nid", 0)
        if not isinstance(nid, int) or isinstance(nid, bool) or nid != 0:
            return error_response(s("app_add_save_failed", lang=self.lang.catalog_lang))
        values = _commit_values(payload)
        if values is None:
            return error_response(
                s("app_add_both_required", lang=self.lang.catalog_lang)
            )
        return values

    def add_card(
        self,
        col: Collection,
        session: StudySession,
        deck_id: int,
        values: dict[str, str],
    ) -> tuple[list[dict[str, str | int]], int] | None:
        if col.decks.get(DeckId(deck_id), default=False) is None:
            return None
        cards, count = self.added_cards(col, session, deck_id)
        note_id = add_vocab_note(
            col,
            DeckId(deck_id),
            values["front"],
            values["back"],
            values["hint"],
            values["example"],
        )
        session.added_note_ids.append(note_id)
        cards.append({"nid": note_id, **values})
        if len(cards) > 4:
            del cards[0]
        return cards, count + 1

    async def save(
        self, request: Request, deck_id: int, values: dict[str, str]
    ) -> Response:
        cookie_response = Response()
        session = get_session(request, cookie_response)

        try:
            result = await self.get_service().run(
                lambda col: self.add_card(col, session, deck_id, values)
            )
        except DuplicateNote:
            return _with_session_cookie(
                error_response(s("app_add_duplicate", lang=self.lang.catalog_lang)),
                cookie_response,
            )
        except (AnkiException, ValueError):
            logger.exception("Failed to add vocabulary note")
            return _with_session_cookie(
                error_response(s("app_add_save_failed", lang=self.lang.catalog_lang)),
                cookie_response,
            )
        if result is None:
            return RedirectResponse("/app/", status_code=303)
        cards, count = result

        fragment = render(
            "app/_add_added_cards.html.jinja",
            app_lang=self.lang,
            cards=cards,
            count=count,
        )
        hud = render(
            "app/add.html.jinja", app_lang=self.lang, hud_only=True, count=count
        )
        response = DatastarResponse(
            [
                SSE.patch_elements(fragment),
                SSE.patch_elements(hud),
                SSE.patch_signals(
                    {
                        "front": "",
                        "back": "",
                        "hint": "",
                        "example": "",
                        "step": 1,
                        "nid": 0,
                        "count": count,
                        "error": "",
                    }
                ),
            ]
        )
        return _with_session_cookie(response, cookie_response)


def build_add_router(
    get_service: Callable[[], CollectionPort], settings: Settings
) -> APIRouter:
    routes = _AddRoutes(get_service, settings)
    router = APIRouter()
    router.add_api_route("/add", routes.add_page, methods=["GET"])
    router.add_api_route("/add/preview", routes.preview, methods=["POST"])
    router.add_api_route("/add/commit", routes.commit, methods=["POST"])
    return router
