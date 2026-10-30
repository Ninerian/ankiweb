"""Card editor page, preview, and per-session additions."""

import json
import logging
from collections.abc import Callable
from hashlib import blake2s
from itertools import islice
from json import JSONDecodeError
from time import monotonic_ns

import anki.collection  # Initialize before anki.cards to avoid an import cycle.
from anki.cards import CardId
from anki.decks import DeckId
from anki.errors import AnkiException
from anki.models import NotetypeId
from anki.notes import NoteId
from anki.utils import to_json_bytes
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
from ankiweb.core.app_client.decks import split_emoji
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
    update_vocab_note,
)
from ankiweb.core.config import Settings
from ankiweb.core.i18n import tr
from ankiweb.core.ports import CollectionPort

logger = logging.getLogger(__name__)
_PENDING_PROGRESS_RESETS = "ankiweb_pending_progress_resets"
_MAX_PENDING_RESETS = 50
_MAX_PENDING_RESET_BYTES = 4096


class _NoteNotEditable(Exception):
    pass


class _InvalidFields(Exception):
    pass


class _ProgressResetFailed(Exception):
    pass


class _ProgressResetUnrecorded(Exception):
    pass


class _ProgressResetUncleared(Exception):
    pass


def _normalized_fields(values: dict[str, str]) -> tuple[str, ...]:
    return tuple(
        values[key].replace("\r\n", "\n")
        for key in ("front", "back", "hint", "example")
    )


def _fields_fingerprint(values: dict[str, str]) -> str:
    encoded = json.dumps(_normalized_fields(values), ensure_ascii=True).encode("ascii")
    return blake2s(encoded, digest_size=16).hexdigest()


def _pending_resets(col: anki.collection.Collection) -> list[list[int | str]]:
    pending = col.get_config(_PENDING_PROGRESS_RESETS, [])
    if not isinstance(pending, list) or any(
        not isinstance(item, list)
        or len(item) != 3
        or any(
            not isinstance(value, int) or isinstance(value, bool) for value in item[:2]
        )
        or not isinstance(item[2], str)
        for item in pending
    ):
        raise ValueError("Invalid pending progress reset configuration")
    return pending


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


def _editable_note(
    col: anki.collection.Collection, deck_id: int, nid: int
) -> tuple[dict[str, str], list[CardId], bool]:
    if not 0 < nid < 2**63:
        raise _NoteNotEditable
    db = col.db
    if db is None:
        raise RuntimeError("Collection database is not available")
    cards = db.all("select id, type from cards where nid = ? and did = ?", nid, deck_id)
    if not cards:
        raise _NoteNotEditable
    try:
        values = read_vocab_note(col, NoteId(nid))
    except ValueError as exc:
        raise _NoteNotEditable from exc
    return (
        values,
        [CardId(card_id) for card_id, _ in cards],
        any(card_type != 0 for _, card_type in cards),
    )


def _prepare_reset(
    col: anki.collection.Collection,
    deck_id: int,
    nid: int,
    original: dict[str, str],
    values: dict[str, str],
    learned: bool,
    fingerprint: str,
) -> tuple[list[list[int | str]], list[int | str] | None, bool]:
    pending = _pending_resets(col)
    marker = next((item for item in pending if item[:2] == [deck_id, nid]), None)
    if (
        marker is not None
        or not learned
        or _normalized_fields(original) == _normalized_fields(values)
    ):
        return pending, marker, False
    marker = [deck_id, nid, fingerprint]
    updated_pending = [*pending, marker]
    try:
        if (
            len(updated_pending) > _MAX_PENDING_RESETS
            or len(to_json_bytes(updated_pending)) > _MAX_PENDING_RESET_BYTES
        ):
            raise ValueError("Pending progress reset capacity exceeded")
        # Preserve Anki undo history; a DB transaction is unsafe here.
        col.set_config(_PENDING_PROGRESS_RESETS, updated_pending, undoable=False)
    except Exception as exc:
        raise _ProgressResetUnrecorded from exc
    return pending, marker, True


def _update_existing_note(
    col: anki.collection.Collection,
    nid: int,
    values: dict[str, str],
    original: dict[str, str],
    pending: list[list[int | str]],
    created_marker: bool,
) -> bool:
    try:
        return update_vocab_note(
            col,
            NoteId(nid),
            values["front"],
            values["back"],
            values["hint"],
            values["example"],
        )
    except (AnkiException, ValueError):
        if created_marker:
            try:
                persisted = read_vocab_note(col, NoteId(nid))
                if _normalized_fields(persisted) == _normalized_fields(original):
                    col.set_config(_PENDING_PROGRESS_RESETS, pending, undoable=False)
            except Exception:
                logger.exception("Failed to remove unused pending progress reset")
        raise


def _reset_and_clear(
    col: anki.collection.Collection,
    card_ids: list[CardId],
    pending: list[list[int | str]],
    marker: list[int | str],
) -> None:
    try:
        col.sched.schedule_cards_as_new(card_ids, reset_counts=True)
    except Exception as exc:
        raise _ProgressResetFailed from exc
    try:
        col.set_config(
            _PENDING_PROGRESS_RESETS,
            [item for item in pending if item is not marker],
            undoable=False,
        )
    except Exception as exc:
        raise _ProgressResetUncleared from exc


def _edit_note(
    col: anki.collection.Collection,
    deck_id: int,
    nid: int,
    values: dict[str, str] | None,
) -> bool:
    original, card_ids, learned = _editable_note(col, deck_id, nid)
    if values is None:
        raise _InvalidFields
    fingerprint = _fields_fingerprint(original)
    pending, marker, created_marker = _prepare_reset(
        col, deck_id, nid, original, values, learned, fingerprint
    )
    changed = _update_existing_note(col, nid, values, original, pending, created_marker)
    # A marker may precede a crashed note write: unchanged original text
    # is not evidence that an edit completed, so do not reset it.
    progress_reset = marker is not None and (changed or fingerprint != marker[2])
    if progress_reset:
        assert marker is not None
        _reset_and_clear(col, card_ids, pending, marker)
    return progress_reset


def _is_vocab_type(
    col: anki.collection.Collection, mid: int, cache: dict[int, bool]
) -> bool:
    if mid not in cache:
        model = col.models.get(NotetypeId(mid))
        if model is None:
            raise ValueError(f"Note type {mid} is missing")
        cache[mid] = model["name"] == NOTETYPE_NAME
    return cache[mid]


def _record_added_notes(
    col: anki.collection.Collection,
    rows: list[tuple[int, int, int]],
    vocab_types: dict[int, bool],
    present: set[int],
    in_deck: set[int],
) -> None:
    for nid, mid, matches in rows:
        if _is_vocab_type(col, mid, vocab_types):
            present.add(nid)
            if matches:
                in_deck.add(nid)


class _EditRoutes:
    def __init__(
        self, get_service: Callable[[], CollectionPort], settings: Settings
    ) -> None:
        self.get_service = get_service
        self.lang = resolve_lang(settings)

    def added_cards(
        self, col: anki.collection.Collection, session: StudySession, deck_id: int
    ) -> tuple[list[dict[str, str | int]], int]:
        ids = session.added_note_ids
        if not ids:
            return [], 0
        db = col.db
        if db is None:
            raise RuntimeError("Collection database is not available")

        present: set[int] = set()
        in_deck: set[int] = set()
        vocab_types: dict[int, bool] = {}
        for start in range(0, len(ids), 32):
            batch = ids[start : start + 32]
            rows = db.all(
                "select n.id, n.mid, exists(select 1 from cards c where c.nid = n.id "
                "and c.did = ?) from notes n where n.id in ("
                "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
                "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                deck_id,
                *batch,
                *([None] * (32 - len(batch))),
            )
            _record_added_notes(col, rows, vocab_types, present, in_deck)

        if len(present) != len(ids):
            ids[:] = [nid for nid in ids if nid in present]
        recent_ids = list(islice((nid for nid in reversed(ids) if nid in in_deck), 4))
        cards = [
            {"nid": nid, **read_vocab_note(col, NoteId(nid))}
            for nid in reversed(recent_ids)
        ]
        return cards, len(in_deck)

    def deck_cards(
        self, col: anki.collection.Collection, deck_id: int
    ) -> list[dict[str, str | int]]:
        db = col.db
        if db is None:
            raise RuntimeError("Collection database is not available")
        model = ensure_vocab_model(col)
        rows = db.all(
            "select n.id, max(c.type != 0) from notes n "
            "join cards c on c.nid = n.id "
            "where n.mid = ? and c.did = ? group by n.id order by n.id desc",
            model["id"],
            deck_id,
        )
        return [
            {"nid": nid, **read_vocab_note(col, NoteId(nid)), "learned": bool(learned)}
            for nid, learned in rows
        ]

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
        cards, count, deck_cards = await self.get_service().run(
            lambda col: (
                *self.added_cards(col, session, deck_id),
                self.deck_cards(col, deck_id),
            )
        )
        body = render(
            "app/edit.html.jinja",
            app_lang=self.lang,
            deck_id=deck_id,
            note_type=NOTETYPE_NAME,
            deck_emoji=deck_emoji,
            deck_name=deck_name,
            cards=cards,
            count=count,
            deck_cards=deck_cards,
            preview={},
        )
        response = HTMLResponse(
            render_app_page(
                tr.actions_add(),
                body,
                active="edit",
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
            values, _, learned = await self.get_service().run(
                lambda col: _editable_note(col, deck_id, nid)
            )
        except _NoteNotEditable:
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
        original: dict[str, SignalValue] = dict(values)
        response = signals_response(
            {
                **values,
                "nid": nid,
                "step": 1,
                "error": "",
                "learned": learned,
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
    ) -> (
        tuple[list[dict[str, str | int]], int, list[dict[str, str | int]], bool] | None
    ):
        if col.decks.get(DeckId(deck_id), default=False) is None:
            return None
        if nid:
            progress_reset = _edit_note(col, deck_id, nid, values)
            cards, count = self.added_cards(col, session, deck_id)
            return cards, count, self.deck_cards(col, deck_id), progress_reset
        if values is None:
            raise _InvalidFields
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
        return cards, count + 1, self.deck_cards(col, deck_id), False

    async def save(
        self, request: Request, deck_id: int, nid: int, values: dict[str, str] | None
    ) -> Response:
        session, new_session_id = get_session(request)

        try:
            result = await self.get_service().run(
                lambda col: self.add_card(col, session, deck_id, nid, values)
            )
        except _NoteNotEditable:
            response = error_response(
                s("app_add_save_failed", lang=self.lang.catalog_lang)
            )
            response.status_code = 404
            return _with_session_cookie(response, new_session_id)
        except _InvalidFields:
            return _with_session_cookie(
                error_response(s("app_add_both_required", lang=self.lang.catalog_lang)),
                new_session_id,
            )
        except DuplicateNote:
            return _with_session_cookie(
                error_response(s("app_add_duplicate", lang=self.lang.catalog_lang)),
                new_session_id,
            )
        except _ProgressResetFailed:
            logger.exception("Failed to reset learning progress after saving note")
            return _with_session_cookie(
                error_response(
                    s("app_edit_progress_reset_failed", lang=self.lang.catalog_lang)
                ),
                new_session_id,
            )
        except _ProgressResetUnrecorded:
            logger.exception(
                "Failed to record pending learning progress reset before saving note"
            )
            return _with_session_cookie(
                error_response(
                    s("app_edit_progress_reset_unrecorded", lang=self.lang.catalog_lang)
                ),
                new_session_id,
            )
        except _ProgressResetUncleared:
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
        if result is None:
            return RedirectResponse("/app/", status_code=303)
        cards, count, deck_cards, progress_reset = result
        animation_stamp = monotonic_ns() if nid == 0 else None

        fragment = render(
            "app/_edit_added_cards.html.jinja",
            app_lang=self.lang,
            deck_id=deck_id,
            deck_cards=deck_cards,
            cards=cards,
            count=count,
            animation_stamp=animation_stamp,
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
                        "error": "",
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
