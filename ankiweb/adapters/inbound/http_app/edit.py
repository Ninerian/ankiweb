"""Card editor routes and per-session additions.

GET /edit/{deck_id}[/front|back|preview|cards]
GET /edit/{deck_id}/cards/{nid}[/front|back|preview]
POST /edit/{deck_id}/{instance}/{rev}/step/{step}/{via}
POST /edit/{deck_id}/{instance}/{rev}/card/{nid}
POST /edit/{deck_id}/{instance}/{rev}/commit
POST /edit/{deck_id}/{instance}/{rev}/reset
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic_ns

import anki.collection  # Initialize before anki.cards to avoid an import cycle.
from anki.collection_pb2 import OpChanges
from anki.decks import DeckId
from anki.errors import AnkiException
from datastar_py.consts import ElementPatchMode
from datastar_py.fastapi import DatastarResponse
from datastar_py.fastapi import ServerSentEventGenerator as SSE
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from ankiweb.adapters.inbound.http_app import deck_dialog
from ankiweb.adapters.inbound.http_app.edit_form import (
    Draft,
    Projection,
    Step,
    Via,
    View,
    project_form,
    step_error,
)
from ankiweb.adapters.inbound.http_app.layout import render_app_page
from ankiweb.adapters.inbound.http_app.session import get_session, set_session_cookie
from ankiweb.adapters.inbound.http_shared.templating import render
from ankiweb.core.app_client.deck_languages import LANGUAGES, LanguagePair, read_marker
from ankiweb.core.app_client.deck_notes import (
    DeckNote,
    NoteNotEditable,
    added_note_membership,
    deck_notes,
    editable_deck_note,
)
from ankiweb.core.app_client.decks import split_emoji
from ankiweb.core.app_client.lang import resolve_lang
from ankiweb.core.app_client.language_chips import language_chips
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
)
from ankiweb.core.config import Settings
from ankiweb.core.i18n import tr
from ankiweb.core.ports import CollectionPort

logger = logging.getLogger(__name__)


def _parse_id(value: object) -> int | None:
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isdecimal()
        or len(value) > 19
    ):
        return None
    result = int(value)
    return result if 0 < result < 2**63 else None


def _parse_deck(request: Request) -> int | None:
    return _parse_id(request.path_params.get("deck_id"))


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


def _deck_view(
    col: anki.collection.Collection, deck_id: int
) -> tuple[str, str, LanguagePair | None] | None:
    deck = col.decks.get(DeckId(deck_id), default=False)
    if deck is None:
        return None
    ensure_vocab_model(col)
    emoji, name = split_emoji(deck["name"])
    return emoji, name, read_marker(deck.get("desc", ""))


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
    error: Exception | None = None


def _draft(note: DeckNote) -> Draft:
    return Draft(**_note_fields(note), nid=note.nid, learned=note.learned)


def _initial_card(
    col: anki.collection.Collection, deck_id: int, requested_card: int | None
) -> Draft | None:
    if requested_card is None:
        return None
    try:
        note, _ = editable_deck_note(col, deck_id, requested_card)
    except NoteNotEditable:
        return None
    return _draft(note)


def _page_target(
    requested: str | None, requested_card: int | None, segment: str
) -> tuple[View, Step] | None:
    """Map path segments to the initial view and step; ``None`` means redirect."""
    if requested is not None and requested_card is None:
        return None
    if segment == "cards" and requested is None:
        return View.CARDS, Step.FRONT
    try:
        step = Step.from_path(segment)
    except ValueError:
        return None
    if requested_card is None and step != Step.FRONT:
        return None
    return (View.CARD if requested_card else View.EDITOR), step


def _canonical_path(
    deck_id: int, requested_card: int | None, view: View, step: Step
) -> str:
    root = f"/app/edit/{deck_id}"
    if requested_card:
        return f"{root}/cards/{requested_card}/{step.path}"
    return f"{root}/cards" if view == View.CARDS else f"{root}/front"


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
        deck_view = await self.get_service().run(lambda col: _deck_view(col, deck_id))
        if deck_view is None:
            return RedirectResponse("/app/", status_code=303)
        requested = request.path_params.get("nid")
        requested_card = _parse_id(requested) if requested is not None else None
        segment = request.path_params.get("step")
        if segment is None:
            return await self._redirect_bare(deck_id, requested_card)
        target = _page_target(requested, requested_card, segment)
        if target is None:
            return RedirectResponse(f"/app/edit/{deck_id}/front", status_code=303)
        initial_view, step = target
        session, new_session_id = get_session(request)
        count, deck_cards, initial_card = await self.get_service().run(
            lambda col: (
                self.added_count(col, session, deck_id),
                self.deck_cards(col, deck_id),
                _initial_card(col, deck_id, requested_card),
            )
        )
        if requested_card and initial_card is None:
            return RedirectResponse(f"/app/edit/{deck_id}/front", status_code=303)
        if request.url.query:
            return RedirectResponse(
                _canonical_path(deck_id, requested_card, initial_view, step),
                status_code=303,
            )
        response = HTMLResponse(
            self._page(
                deck_id,
                deck_view,
                count,
                deck_cards,
                initial_view,
                project_form(initial_card or Draft(), step),
            )
        )
        return _with_session_cookie(response, new_session_id)

    async def _redirect_bare(
        self, deck_id: int, requested_card: int | None
    ) -> RedirectResponse:
        """Send ``/edit/{deck}`` and ``/cards/{nid}`` to their ``/front`` page."""
        if requested_card:
            note = await self.get_service().run(
                lambda col: _initial_card(col, deck_id, requested_card)
            )
            if note is not None:
                return RedirectResponse(
                    f"/app/edit/{deck_id}/cards/{requested_card}/front", status_code=303
                )
        return RedirectResponse(f"/app/edit/{deck_id}/front", status_code=303)

    def _page(
        self,
        deck_id: int,
        deck_view: tuple[str, str, LanguagePair | None],
        count: int,
        deck_cards: list[dict[str, str | int]],
        initial_view: View,
        projection: Projection,
    ) -> str:
        deck_emoji, deck_name, languages = deck_view
        body = render(
            "app/edit.html.jinja",
            app_lang=self.lang,
            deck_id=deck_id,
            deck_emoji=deck_emoji,
            deck_name=deck_name,
            languages=languages,
            LANGUAGES=LANGUAGES,
            target_chips=language_chips(languages.dst) if languages else (),
            count=count,
            deck_cards=deck_cards,
            initial_view=initial_view,
            instance=deck_dialog.new_token(),
            revision=0,
            projection=projection,
        )
        return render_app_page(
            tr.actions_add(),
            body,
            active="edit",
            static_dir=self.static_dir,
            scripts=("/shell/static/app/edit.js",),
            show_error_toast=False,
            lang=self.lang,
        )

    @staticmethod
    def guard(request: Request) -> tuple[str, int] | None:
        token = deck_dialog.valid_token(request.path_params.get("instance"))
        raw = request.path_params.get("rev", "")
        if token is None or not raw.isascii() or not raw.isdecimal() or len(raw) > 18:
            return None
        return token, int(raw)

    @staticmethod
    def selector(guard: tuple[str, int]) -> str:
        token, revision = guard
        return f'#edit-session[data-instance="{token}"][data-rev="{revision}"]'

    def fragment(
        self, name: str, deck_id: int, projection: Projection, **context
    ) -> str:
        return render(
            "app/edit.html.jinja",
            fragment=name,
            app_lang=self.lang,
            deck_id=deck_id,
            projection=projection,
            **context,
        )

    def patch(self, guard: tuple[str, int], target: str, html: str):
        return SSE.patch_elements(html, selector=f"{self.selector(guard)} #{target}")

    def error(
        self, guard: tuple[str, int], key: str, *, status_code: int = 200
    ) -> DatastarResponse:
        html = self.fragment(
            "error",
            0,
            project_form(Draft()),
            error_message=s(key, lang=self.lang.catalog_lang),
        )
        return DatastarResponse(
            self.patch(guard, "edit-error", html), status_code=status_code
        )

    async def form_context(
        self,
        deck_id: int,
        projection: Projection,
        guard: tuple[str, int],
        *,
        deck_cards: list[dict[str, str | int]] | None = None,
    ) -> dict | None:
        deck_view = await self.get_service().run(lambda col: _deck_view(col, deck_id))
        if deck_view is None:
            return None
        emoji, name, languages = deck_view
        if deck_cards is None:
            deck_cards = await self.get_service().run(
                lambda col: self.deck_cards(col, deck_id)
            )
        return {
            "deck_emoji": emoji,
            "deck_name": name,
            "languages": languages,
            "LANGUAGES": LANGUAGES,
            "target_chips": language_chips(languages.dst) if languages else (),
            "deck_cards": deck_cards,
            "instance": guard[0],
            "revision": guard[1] + 1,
            "reset_from": guard[1],
            "progress_reset": projection.progress_reset,
        }

    async def reset_events(
        self,
        deck_id: int,
        guard: tuple[str, int],
        projection: Projection,
        *,
        deck_cards: list[dict[str, str | int]] | None = None,
        animation_stamp: int | None = None,
    ):
        context = await self.form_context(
            deck_id, projection, guard, deck_cards=deck_cards
        )
        if context is None:
            return []
        html = self.fragment(
            "form", deck_id, projection, animation_stamp=animation_stamp, **context
        )
        return [
            SSE.patch_elements(
                html, selector=self.selector(guard), mode=ElementPatchMode.REPLACE
            )
        ]

    async def step(self, request: Request) -> Response:
        guard = self.guard(request)
        deck_id = _parse_deck(request)
        if guard is None or deck_id is None:
            return deck_dialog.no_patch()
        fields = await deck_dialog.form_fields(request)
        try:
            to = Step.from_path(request.path_params.get("step", ""))
            via = Via(request.path_params.get("via", ""))
            if fields is None:
                raise ValueError
            nid = int(fields["nid"])
            if not 0 <= nid < 2**63:
                raise ValueError
            draft = Draft(
                *(fields[key] for key in ("front", "back", "hint", "example")),
                nid=nid,
            )
        except (ValueError, KeyError):
            return self.error(guard, "app_add_save_failed")
        key = step_error(draft, to, via)
        if key:
            if via == Via.HISTORY:
                html = self.fragment(
                    "error",
                    deck_id,
                    project_form(draft),
                    error_message=s(key, lang=self.lang.catalog_lang),
                )
                return DatastarResponse(
                    [
                        self.patch(guard, "edit-error", html),
                        SSE.execute_script(
                            f"document.querySelector('{self.selector(guard)}') && window.avStepRejected()"
                        ),
                    ]
                )
            return self.error(guard, key)
        projection = project_form(draft, to)
        events = [
            self.patch(guard, target, self.fragment(fragment, deck_id, projection))
            for fragment, target in (
                ("marker", "edit-step"),
                ("steps", "edit-steps"),
                ("actions", "edit-actions"),
                ("preview", "preview"),
                ("error", "edit-error"),
            )
        ]
        events.append(
            SSE.execute_script(
                f"document.querySelector('{self.selector(guard)}') && "
                f"window.avStepApplied('{to.path}', {nid}, {str(via == Via.HISTORY).lower()})"
            )
        )
        if to != Step.PREVIEW:
            focus = "input-front" if to == Step.FRONT else "input-back"
            events.append(
                SSE.execute_script(
                    f"document.querySelector('{self.selector(guard)}') && window.avFocus('{focus}')"
                )
            )
        return DatastarResponse(events)

    async def reset(self, request: Request) -> Response:
        guard, deck_id = self.guard(request), _parse_deck(request)
        if guard is None or deck_id is None:
            return deck_dialog.no_patch()
        if await deck_dialog.form_fields(request) is None:
            return self.error(guard, "app_add_save_failed")
        events = await self.reset_events(deck_id, guard, project_form(Draft()))
        if request.url.path.endswith("/done") and events:
            session, new_session_id = get_session(request)
            count = await self.get_service().run(
                lambda col: self.added_count(col, session, deck_id)
            )
            dialog = render(
                "app/_edit_summary.html.jinja",
                app_lang=self.lang,
                deck_id=deck_id,
                count=count,
            )
            next_guard = (guard[0], guard[1] + 1)
            selector = (
                f"#add-wizard:has({self.selector(next_guard)}"
                f'[data-reset-from="{guard[1]}"]) #edit-dialog-host'
            )
            events.append(
                SSE.patch_elements(
                    dialog, selector=selector, mode=ElementPatchMode.INNER
                )
            )
            return _with_session_cookie(DatastarResponse(events), new_session_id)
        return DatastarResponse(events)

    async def load_card(self, request: Request) -> Response:
        guard, deck_id = self.guard(request), _parse_deck(request)
        nid = _parse_id(request.path_params.get("nid"))
        if guard is None or deck_id is None or nid is None:
            return deck_dialog.no_patch()
        if await deck_dialog.form_fields(request) is None:
            return self.error(guard, "app_add_save_failed")
        _, new_session_id = get_session(request)
        try:
            note, _ = await self.get_service().run(
                lambda col: editable_deck_note(col, deck_id, nid)
            )
        except NoteNotEditable:
            return _with_session_cookie(
                PlainTextResponse(
                    s("app_add_edit_unavailable", lang=self.lang.catalog_lang),
                    status_code=404,
                ),
                new_session_id,
            )
        except AnkiException:
            logger.exception("Failed to load vocabulary note")
            return _with_session_cookie(
                self.error(guard, "app_add_save_failed"), new_session_id
            )
        projection = project_form(_draft(note))
        events = await self.reset_events(deck_id, guard, projection)
        next_guard = (guard[0], guard[1] + 1)
        events.append(
            SSE.execute_script(
                f"document.querySelector('{self.selector(next_guard)}"
                f'[data-reset-from="{guard[1]}"]\') && window.avEditCardLoaded({nid})'
            )
        )
        return _with_session_cookie(DatastarResponse(events), new_session_id)

    async def commit(self, request: Request) -> Response:
        guard, deck_id = self.guard(request), _parse_deck(request)
        if guard is None or deck_id is None:
            return deck_dialog.no_patch()
        fields = await deck_dialog.form_fields(request)
        if fields is None:
            return self.error(guard, "app_add_both_required")
        try:
            nid = int(fields["nid"])
            if not 0 <= nid < 2**63 or not all(
                key in fields for key in ("front", "back", "hint", "example")
            ):
                raise ValueError
        except (KeyError, ValueError):
            return self.error(guard, "app_add_save_failed")
        values = _commit_values(fields)
        if values is None and nid == 0:
            return self.error(guard, "app_add_both_required")
        return await self.save(request, deck_id, nid, values)

    def add_card(
        self,
        col: anki.collection.Collection,
        session: StudySession,
        deck_id: int,
        nid: int,
        values: dict[str, str] | None,
        changes: OpChanges,
    ) -> _SaveResult:
        if col.decks.get(DeckId(deck_id), default=False) is None:
            return _SaveResult(None, [], False, changes)
        if nid:
            fields = VocabFields.from_mapping(values) if values is not None else None
            outcome = edit_deck_note(
                col, deck_id, nid, fields, logger=logger, changes=changes
            )
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

    def save_operation(
        self,
        col: anki.collection.Collection,
        session: StudySession,
        deck_id: int,
        nid: int,
        values: dict[str, str] | None,
    ) -> _SaveResult:
        changes = OpChanges()
        try:
            return self.add_card(col, session, deck_id, nid, values, changes)
        except Exception as exc:
            if not changes.ListFields():
                raise
            # Broadcast completed mutations before the HTTP layer handles the error.
            return _SaveResult(None, [], False, changes, exc)

    async def save(
        self, request: Request, deck_id: int, nid: int, values: dict[str, str] | None
    ) -> Response:
        session, new_session_id = get_session(request)
        guard = self.guard(request)
        assert guard is not None

        try:
            result = await self.get_service().run_op(
                lambda col: self.save_operation(col, session, deck_id, nid, values),
                initiator="app",
            )
            if result.error is not None:
                raise result.error
        except NoteNotEditable:
            response = self.error(guard, "app_add_save_failed", status_code=404)
            return _with_session_cookie(response, new_session_id)
        except InvalidFields:
            return _with_session_cookie(
                self.error(guard, "app_add_both_required"),
                new_session_id,
            )
        except DuplicateNote:
            return _with_session_cookie(
                self.error(guard, "app_add_duplicate"),
                new_session_id,
            )
        except ProgressResetFailed:
            logger.exception("Failed to reset learning progress after saving note")
            return _with_session_cookie(
                self.error(guard, "app_edit_progress_reset_failed"),
                new_session_id,
            )
        except ProgressResetUnrecorded:
            logger.exception(
                "Failed to record pending learning progress reset before saving note"
            )
            return _with_session_cookie(
                self.error(guard, "app_edit_progress_reset_unrecorded"),
                new_session_id,
            )
        except ProgressResetUncleared:
            logger.exception("Failed to clear pending learning progress reset")
            return _with_session_cookie(
                self.error(guard, "app_edit_progress_reset_uncleared"),
                new_session_id,
            )
        except (AnkiException, ValueError):
            logger.exception("Failed to add vocabulary note")
            return _with_session_cookie(
                self.error(guard, "app_add_save_failed"),
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
            "app/_edit_deck_pile.html.jinja",
            app_lang=self.lang,
            deck_id=deck_id,
            deck_cards=deck_cards,
            animation_stamp=animation_stamp,
            pile_animate=nid == 0,
        )
        deck_fragment = render(
            "app/_edit_deck_cards.html.jinja",
            app_lang=self.lang,
            deck_id=deck_id,
            deck_cards=deck_cards,
            progress_reset=progress_reset,
        )

        projection = project_form(Draft(), progress_reset=progress_reset)
        events = [
            SSE.patch_elements(fragment),
            SSE.patch_elements(deck_fragment),
            SSE.patch_elements(
                render("app/_edit_summary_count.html.jinja", count=count)
            ),
        ]
        events.extend(
            await self.reset_events(
                deck_id,
                guard,
                projection,
                deck_cards=deck_cards,
                animation_stamp=animation_stamp,
            )
        )
        next_guard = (guard[0], guard[1] + 1)
        action = "window.avAfterCommit()" if nid else "window.avAnimateCommit()"
        events.append(
            SSE.execute_script(
                f"document.querySelector('{self.selector(next_guard)}"
                f'[data-reset-from="{guard[1]}"]\') && {action}'
            )
        )
        response = DatastarResponse(events)
        return _with_session_cookie(response, new_session_id)


def build_edit_router(
    get_service: Callable[[], CollectionPort], settings: Settings
) -> APIRouter:
    routes = _EditRoutes(get_service, settings)
    router = APIRouter()

    @router.get("/edit")
    async def missing_deck() -> Response:
        return RedirectResponse("/app/", status_code=303)

    router.add_api_route("/edit/{deck_id}", routes.edit_page, methods=["GET"])
    router.add_api_route(
        "/edit/{deck_id}/cards/{nid}", routes.edit_page, methods=["GET"]
    )
    router.add_api_route(
        "/edit/{deck_id}/cards/{nid}/{step}", routes.edit_page, methods=["GET"]
    )
    router.add_api_route("/edit/{deck_id}/{step}", routes.edit_page, methods=["GET"])
    prefix = "/edit/{deck_id}/{instance}/{rev}"
    router.add_api_route(prefix + "/step/{step}/{via}", routes.step, methods=["POST"])
    router.add_api_route(prefix + "/reset", routes.reset, methods=["POST"])
    router.add_api_route(prefix + "/done", routes.reset, methods=["POST"])
    router.add_api_route(prefix + "/commit", routes.commit, methods=["POST"])
    router.add_api_route(prefix + "/card/{nid}", routes.load_card, methods=["POST"])
    return router
