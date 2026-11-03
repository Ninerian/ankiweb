"""Card editor page, preview, and per-session additions."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from json import JSONDecodeError
from time import monotonic_ns

import anki.collection  # Initialize before anki.cards to avoid an import cycle.
from anki.collection_pb2 import OpChanges
from anki.decks import DeckId
from anki.errors import AnkiException
from datastar_py.attributes import SignalValue
from datastar_py.fastapi import DatastarResponse
from datastar_py.fastapi import ServerSentEventGenerator as SSE
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from ankiweb.adapters.inbound.http_app.layout import render_app_page
from ankiweb.adapters.inbound.http_app.session import get_session, set_session_cookie
from ankiweb.adapters.inbound.http_datastar.common import (
    elements_response,
    error_response,
    signals_response,
)
from ankiweb.adapters.inbound.http_shared.templating import render
from ankiweb.core.app_client.deck_notes import (
    DeckNote,
    NoteNotEditable,
    added_note_membership,
    deck_notes,
    editable_deck_note,
)
from ankiweb.core.app_client.decks import split_emoji
from ankiweb.core.app_client.lang import resolve_lang
from ankiweb.core.app_client.note_editing import (
    InvalidFields,
    ProgressResetFailed,
    ProgressResetUncleared,
    ProgressResetUnrecorded,
    edit_deck_note,
)
from ankiweb.core.app_client.strings import s
from ankiweb.core.app_client.study import StudySession
from ankiweb.core.app_client.vocab import (
    DuplicateNote,
    VocabFields,
    add_vocab_note,
    ensure_vocab_model,
    escape_field,
    highlight_example,
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


def _with_session_cookie(response: Response, new_session_id: str | None) -> Response:
    set_session_cookie(response, new_session_id)
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


def _deck_name(col: anki.collection.Collection, deck_id: int) -> tuple[str, str] | None:
    deck = col.decks.get(DeckId(deck_id), default=False)
    if deck is None:
        return None
    ensure_vocab_model(col)
    return split_emoji(deck["name"])


def _note_fields(note: DeckNote) -> dict[str, str]:
    return {
        "front": note.fields.front,
        "back": note.fields.back,
        "hint": note.fields.hint,
        "example": note.fields.example,
    }


def _note_view(note: DeckNote) -> dict[str, str | int]:
    return {"nid": note.nid, **_note_fields(note), "learned": note.learned}


@dataclass
class _SaveResult:
    count: int | None
    deck_cards: list[dict[str, str | int]]
    progress_reset: bool
    changes: OpChanges


def _initial_card(
    col: anki.collection.Collection, deck_id: int, requested_card: str | None
) -> dict[str, str | int | bool] | None:
    if requested_card is None:
        return None
    try:
        note, _ = editable_deck_note(col, deck_id, int(requested_card))
    except (ValueError, NoteNotEditable):
        return None
    return _note_view(note)


class _EditRoutes:
    def __init__(
        self, get_service: Callable[[], CollectionPort], settings: Settings
    ) -> None:
        self.get_service = get_service
        self.lang = resolve_lang(settings)
        self.static_dir = settings.shell_dir / "static"

    def added_count(
        self, col: anki.collection.Collection, session: StudySession, deck_id: int
    ) -> int:
        ids = session.added_note_ids
        present, in_deck = added_note_membership(col, deck_id, ids)

        if len(present) != len(ids):
            ids[:] = [nid for nid in ids if nid in present]
        return len(in_deck)

    def deck_cards(
        self, col: anki.collection.Collection, deck_id: int
    ) -> list[dict[str, str | int]]:
        return [_note_view(note) for note in deck_notes(col, deck_id)]

    async def edit_page(self, request: Request) -> Response:
        deck_id = _parse_deck(request)
        if deck_id is None:
            return RedirectResponse("/app/", status_code=303)
        deck_display = await self.get_service().run(
            lambda col: _deck_name(col, deck_id)
        )
        if deck_display is None:
            return RedirectResponse("/app/", status_code=303)
        deck_emoji, deck_name = deck_display
        session, new_session_id = get_session(request)
        requested_card = request.query_params.get("card")
        count, deck_cards, initial_card = await self.get_service().run(
            lambda col: (
                self.added_count(col, session, deck_id),
                self.deck_cards(col, deck_id),
                _initial_card(col, deck_id, requested_card),
            )
        )
        initial_view = (
            "card"
            if initial_card is not None
            else "cards"
            if requested_card is None and request.query_params.get("view") == "cards"
            else "editor"
        )
        body = render(
            "app/edit.html.jinja",
            app_lang=self.lang,
            deck_id=deck_id,
            deck_emoji=deck_emoji,
            deck_name=deck_name,
            count=count,
            deck_cards=deck_cards,
            initial_view=initial_view,
            initial_card=initial_card,
            pile_animate=False,
            preview={},
        )
        response = HTMLResponse(
            render_app_page(
                tr.actions_add(),
                body,
                active="edit",
                static_dir=self.static_dir,
                scripts=("/shell/static/app/edit.js",),
                lang=self.lang,
            )
        )
        return _with_session_cookie(response, new_session_id)

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
            "app/edit.html.jinja",
            app_lang=self.lang,
            preview_only=True,
            preview=values,
            example_html=example_html,
        )
        return elements_response(fragment)

    async def load_card(self, request: Request, nid: int) -> Response:
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
        _, new_session_id = get_session(request)
        try:
            note, _ = await self.get_service().run(
                lambda col: editable_deck_note(col, deck_id, nid)
            )
        except NoteNotEditable:
            response = PlainTextResponse(
                s("app_add_edit_unavailable", lang=self.lang.catalog_lang),
                status_code=404,
            )
            return _with_session_cookie(response, new_session_id)
        except AnkiException:
            logger.exception("Failed to load vocabulary note")
            return _with_session_cookie(
                error_response(s("app_add_save_failed", lang=self.lang.catalog_lang)),
                new_session_id,
            )
        values = _note_fields(note)
        original: dict[str, SignalValue] = dict(values)
        response = signals_response(
            {
                **values,
                "nid": nid,
                "step": 1,
                "error": "",
                "learned": note.learned,
                "progressReset": False,
                "editOriginal": original,
                "editLoaded": monotonic_ns(),
            }
        )
        return _with_session_cookie(response, new_session_id)

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
        input_data = await self.commit_input(request)
        if isinstance(input_data, Response):
            return input_data
        nid, values = input_data
        return await self.save(request, deck_id, nid, values)

    async def commit_input(
        self, request: Request
    ) -> tuple[int, dict[str, str] | None] | Response:
        try:
            payload = await request.json()
        except (JSONDecodeError, UnicodeDecodeError):
            payload = None
        if not isinstance(payload, dict):
            return error_response(
                s("app_add_both_required", lang=self.lang.catalog_lang)
            )
        nid = payload.get("nid", 0)
        if not isinstance(nid, int) or isinstance(nid, bool) or not 0 <= nid < 2**63:
            return error_response(s("app_add_save_failed", lang=self.lang.catalog_lang))
        values = _commit_values(payload)
        if values is None and nid == 0:
            return error_response(
                s("app_add_both_required", lang=self.lang.catalog_lang)
            )
        return nid, values

    def add_card(
        self,
        col: anki.collection.Collection,
        session: StudySession,
        deck_id: int,
        nid: int,
        values: dict[str, str] | None,
    ) -> _SaveResult:
        if col.decks.get(DeckId(deck_id), default=False) is None:
            return _SaveResult(None, [], False, OpChanges())
        if nid:
            fields = VocabFields.from_mapping(values) if values is not None else None
            outcome = edit_deck_note(col, deck_id, nid, fields, logger=logger)
            count = self.added_count(col, session, deck_id)
            return _SaveResult(
                count,
                self.deck_cards(col, deck_id),
                outcome.progress_reset,
                outcome.changes,
            )
        if values is None:
            raise InvalidFields
        count = self.added_count(col, session, deck_id)
        changes = OpChanges()
        note_id = add_vocab_note(
            col,
            DeckId(deck_id),
            values["front"],
            values["back"],
            values["hint"],
            values["example"],
            changes=changes,
        )
        session.added_note_ids.append(note_id)
        return _SaveResult(count + 1, self.deck_cards(col, deck_id), False, changes)

    async def save(
        self, request: Request, deck_id: int, nid: int, values: dict[str, str] | None
    ) -> Response:
        session, new_session_id = get_session(request)

        try:
            result = await self.get_service().run_op(
                lambda col: self.add_card(col, session, deck_id, nid, values),
                initiator="app",
            )
        except NoteNotEditable:
            response = error_response(
                s("app_add_save_failed", lang=self.lang.catalog_lang)
            )
            response.status_code = 404
            return _with_session_cookie(response, new_session_id)
        except InvalidFields:
            return _with_session_cookie(
                error_response(s("app_add_both_required", lang=self.lang.catalog_lang)),
                new_session_id,
            )
        except DuplicateNote:
            return _with_session_cookie(
                error_response(s("app_add_duplicate", lang=self.lang.catalog_lang)),
                new_session_id,
            )
        except ProgressResetFailed:
            logger.exception("Failed to reset learning progress after saving note")
            return _with_session_cookie(
                error_response(
                    s("app_edit_progress_reset_failed", lang=self.lang.catalog_lang)
                ),
                new_session_id,
            )
        except ProgressResetUnrecorded:
            logger.exception(
                "Failed to record pending learning progress reset before saving note"
            )
            return _with_session_cookie(
                error_response(
                    s("app_edit_progress_reset_unrecorded", lang=self.lang.catalog_lang)
                ),
                new_session_id,
            )
        except ProgressResetUncleared:
            logger.exception("Failed to clear pending learning progress reset")
            return _with_session_cookie(
                error_response(
                    s("app_edit_progress_reset_uncleared", lang=self.lang.catalog_lang)
                ),
                new_session_id,
            )
        except (AnkiException, ValueError):
            logger.exception("Failed to add vocabulary note")
            return _with_session_cookie(
                error_response(s("app_add_save_failed", lang=self.lang.catalog_lang)),
                new_session_id,
            )
        if result.count is None:
            return RedirectResponse("/app/", status_code=303)
        count, deck_cards, progress_reset = (
            result.count,
            result.deck_cards,
            result.progress_reset,
        )
        animation_stamp = monotonic_ns() if nid == 0 else None

        fragment = render(
            "app/_edit_added_cards.html.jinja",
            app_lang=self.lang,
            deck_id=deck_id,
            deck_cards=deck_cards,
            count=count,
            animation_stamp=animation_stamp,
            pile_animate=nid == 0,
        )
        deck_fragment = render(
            "app/_edit_deck_cards.html.jinja",
            app_lang=self.lang,
            deck_id=deck_id,
            deck_cards=deck_cards,
        )

        response = DatastarResponse(
            [
                SSE.patch_elements(fragment),
                SSE.patch_elements(deck_fragment),
                SSE.patch_signals(
                    {
                        "front": "",
                        "back": "",
                        "hint": "",
                        "example": "",
                        "step": 1,
                        "nid": 0,
                        "learned": False,
                        "progressReset": progress_reset,
                        "count": count,
                        "deckCount": len(deck_cards),
                        "error": "",
                        **({"_editSaved": True} if nid else {}),
                    }
                ),
            ]
        )
        return _with_session_cookie(response, new_session_id)


def build_edit_router(
    get_service: Callable[[], CollectionPort], settings: Settings
) -> APIRouter:
    routes = _EditRoutes(get_service, settings)
    router = APIRouter()
    router.add_api_route("/edit", routes.edit_page, methods=["GET"])
    router.add_api_route("/edit/preview", routes.preview, methods=["POST"])
    router.add_api_route("/edit/commit", routes.commit, methods=["POST"])
    router.add_api_route("/edit/card/{nid}", routes.load_card, methods=["POST"])
    return router
