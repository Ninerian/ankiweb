"""HTTP review flow backed by per-browser study sessions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from anki.collection import Collection
from anki.decks import DeckId
from anki.scheduler.v3 import Scheduler
from datastar_py.attributes import SignalValue
from datastar_py.fastapi import DatastarResponse, ReadSignals
from datastar_py.fastapi import ServerSentEventGenerator as SSE
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from ankiweb.adapters.inbound.http_app.layout import render_app_page
from ankiweb.adapters.inbound.http_app.session import get_session, set_session_cookie
from ankiweb.adapters.inbound.http_datastar.common import error_response
from ankiweb.adapters.inbound.http_shared.templating import render, tr_clean
from ankiweb.core.app_client import study
from ankiweb.core.app_client.completion import CompletionSummary, summarize
from ankiweb.core.app_client.lang import ResolvedLang, resolve_lang
from ankiweb.core.app_client.streak import current_streak
from ankiweb.core.app_client.strings import s
from ankiweb.core.config import Settings
from ankiweb.core.i18n import tr
from ankiweb.core.ports import CollectionPort


@dataclass(frozen=True)
class _Snapshot:
    changes: object
    view: study.CardView | None
    deck_id: int
    progress: dict[str, int]
    streak: int
    streak_before: int | None
    rating: int | None
    summary: CompletionSummary | None
    study_again: bool


def _snapshot(
    col: Collection,
    session: study.StudySession,
    view: study.CardView | None,
    *,
    changes: object = None,
    streak_before: int | None = None,
    rating: int | None = None,
    allow_completion: bool = False,
) -> _Snapshot:
    # Queue counts include learning steps even when no card is available immediately.
    remaining = (
        view.counts.total
        if view is not None
        else study.QueueCounts.from_queue(
            cast(Scheduler, col.sched).get_queued_cards(fetch_limit=1)
        ).total
    )
    total = session.start_total
    done = max(0, min(total, total - remaining))
    completed = allow_completion and view is None and session.reviewed > 0
    if completed:
        done = total
    progress = {
        "done": done,
        "total": total,
        "percent": round(100 * done / total) if total else 0,
    }
    assert session.deck_id is not None
    return _Snapshot(
        changes=changes,
        view=view,
        deck_id=session.deck_id,
        progress=progress,
        streak=current_streak(col),
        streak_before=streak_before,
        rating=rating,
        summary=summarize(session.tally) if completed else None,
        study_again=completed and remaining > 0,
    )


def _context(
    snapshot: _Snapshot, lang: ResolvedLang, request: Request
) -> dict[str, Any]:
    return {
        "request": request,
        "app_lang": lang,
        "view": snapshot.view,
        "deck_id": snapshot.deck_id,
        "progress": snapshot.progress,
        "streak": snapshot.streak,
        "streak_before": snapshot.streak_before,
        "rating": snapshot.rating,
        "summary": snapshot.summary,
        "completed": snapshot.summary is not None,
        "study_again": snapshot.study_again,
    }


def _patch(
    snapshot: _Snapshot, lang: ResolvedLang, request: Request, *, reset_revealed: bool
) -> DatastarResponse:
    ctx = _context(snapshot, lang, request)
    fragments = (
        ("#hud-progress", "app/review.html.jinja", {"fragment": "progress"}),
        ("#stage", "app/_review_stage.html.jinja", {}),
        ("#bar", "app/_review_bar.html.jinja", {}),
        ("#sheet", "app/_review_sheet.html.jinja", {}),
    )
    events = [
        SSE.patch_elements(render(template, **ctx, **extra), selector=selector)
        for selector, template, extra in fragments
    ]
    signals: dict[str, SignalValue] = {
        "dueOpen": False,
        "cardId": snapshot.view.card_id if snapshot.view else 0,
        "sheetOpen": False,
        "error": "",
    }
    if reset_revealed:
        signals["revealed"] = False
    events.append(SSE.patch_signals(signals))
    return DatastarResponse(events)


def _integer(payload: object, key: str) -> int:
    value = payload.get(key) if isinstance(payload, dict) else None
    if type(value) is not int:
        raise HTTPException(status_code=422)
    return value


def _current_card(session: study.StudySession, card_id: int) -> None:
    if session.card is None or session.card.id != card_id:
        raise study.StaleCard()


@dataclass(frozen=True)
class _Command:
    action: str
    card_id: int
    ease: int = 0
    flag: int = 0
    spec: str = ""


def _parse_command(payload: object, action: str) -> _Command:
    card_id = _integer(payload, "cardId")
    if action == "answer":
        ease = _integer(payload, "ease")
        if ease not in (1, 2, 3, 4):
            raise HTTPException(status_code=422)
        return _Command(action, card_id, ease=ease)
    if action == "flag":
        flag = _integer(payload, "flag")
        if flag not in (0, 1, 2, 3, 4):
            raise HTTPException(status_code=422)
        return _Command(action, card_id, flag=flag)
    if action == "due":
        spec = payload.get("spec") if isinstance(payload, dict) else None
        if not isinstance(spec, str):
            raise HTTPException(status_code=422)
        return _Command(action, card_id, spec=spec)
    return _Command(action, card_id)


_HANDLERS: dict[
    str, Callable[[Collection, study.StudySession, _Command], study.StudyStep]
] = {
    "answer": lambda col, session, cmd: study.answer_next(
        col, session, cmd.card_id, cmd.ease
    ),
    "mark": lambda col, session, cmd: study.toggle_mark(col, session, cmd.card_id),
    "flag": lambda col, session, cmd: study.set_flag(
        col, session, cmd.card_id, cmd.flag
    ),
    "bury": lambda col, session, cmd: study.bury(col, session, cmd.card_id),
    "suspend": lambda col, session, cmd: study.suspend(col, session, cmd.card_id),
    "forget": lambda col, session, cmd: study.forget(col, session, cmd.card_id),
    "delete": lambda col, session, cmd: study.delete_note(col, session, cmd.card_id),
    "due": lambda col, session, cmd: study.set_due(col, session, cmd.card_id, cmd.spec),
    "undo": lambda col, session, cmd: study.undo(col, session),
}


def _run_command(
    col: Collection, session: study.StudySession, cmd: _Command
) -> _Snapshot:
    _current_card(session, cmd.card_id)
    before = current_streak(col) if cmd.action in ("answer", "undo") else None
    step = _HANDLERS[cmd.action](col, session, cmd)
    return _snapshot(
        col,
        session,
        step.view,
        changes=step.changes,
        streak_before=before,
        rating=cmd.ease if cmd.action == "answer" else None,
        allow_completion=cmd.action == "answer",
    )


def _deck_id(deck: str | None) -> int | None:
    if deck is None or not deck.isascii() or not deck.isdecimal() or len(deck) > 18:
        return None
    return int(deck) or None


def _begin(
    col: Collection, session: study.StudySession, deck_id: int
) -> _Snapshot | None:
    if col.decks.get(DeckId(deck_id), default=False) is None:
        return None
    return _snapshot(col, session, study.start(col, session, deck_id))


def _make_review_page(
    get_service: Callable[[], CollectionPort], lang: ResolvedLang, static_dir: Path
):
    async def review_page(request: Request, deck: str | None = None) -> Response:
        deck_id = _deck_id(deck)
        if deck_id is None:
            return RedirectResponse(
                "/app/", status_code=303, headers={"Cache-Control": "no-store"}
            )

        session, new_session_id = get_session(request)
        snapshot = await get_service().run(lambda col: _begin(col, session, deck_id))
        if snapshot is None:
            return RedirectResponse(
                "/app/", status_code=303, headers={"Cache-Control": "no-store"}
            )
        body = render(
            "app/review.html.jinja",
            **_context(snapshot, lang, request),
            fragment="page",
        )
        html = render_app_page(
            s("app_review_progress", lang=lang.catalog_lang),
            body,
            active="",
            static_dir=static_dir,
            scripts=("/shell/static/app/card-render.js",),
            lang=lang,
        )
        response = HTMLResponse(html, headers={"Cache-Control": "no-store"})
        set_session_cookie(response, new_session_id)
        return response

    return review_page


async def _execute(
    get_service: Callable[[], CollectionPort],
    lang: ResolvedLang,
    request: Request,
    payload: object,
    action: str,
) -> Response:
    cmd = _parse_command(payload, action)
    session, _ = get_session(request)
    try:
        snapshot = await get_service().run_op(
            lambda col: _run_command(col, session, cmd), initiator="app"
        )
    except study.StaleCard as exc:
        raise HTTPException(status_code=409) from exc
    except study.NothingToUndo:
        return error_response(tr_clean(tr.actions_nothing_to_undo()))
    except ValueError as exc:
        if action == "due":
            return error_response(str(exc) or tr_clean(tr.errors_invalid_input_empty()))
        raise HTTPException(status_code=422) from exc
    return _patch(
        snapshot, lang, request, reset_revealed=action not in ("mark", "flag")
    )


def _make_answer(get_service: Callable[[], CollectionPort], lang: ResolvedLang):
    async def answer(request: Request, payload: ReadSignals = None) -> Response:
        return await _execute(get_service, lang, request, payload, "answer")

    return answer


def _make_action(get_service: Callable[[], CollectionPort], lang: ResolvedLang):
    async def action(
        name: str, request: Request, payload: ReadSignals = None
    ) -> Response:
        if name not in {"mark", "flag", "bury", "suspend", "undo", "forget", "delete"}:
            raise HTTPException(status_code=404)
        return await _execute(get_service, lang, request, payload, name)

    return action


def _make_due(get_service: Callable[[], CollectionPort], lang: ResolvedLang):
    async def due(request: Request, payload: ReadSignals = None) -> Response:
        return await _execute(get_service, lang, request, payload, "due")

    return due


async def _info(card_id: int) -> Response:
    if not 0 < card_id < 10**18:
        raise HTTPException(status_code=404)
    return RedirectResponse(f"/card-info/{card_id}", status_code=303)


def make_review_router(
    get_service: Callable[[], CollectionPort], settings: Settings
) -> APIRouter:
    router = APIRouter(prefix="/review")
    lang = resolve_lang(settings)
    router.add_api_route(
        "",
        _make_review_page(get_service, lang, settings.shell_dir / "static"),
        methods=["GET"],
    )
    router.add_api_route("/answer", _make_answer(get_service, lang), methods=["POST"])
    router.add_api_route(
        "/action/{name}", _make_action(get_service, lang), methods=["POST"]
    )
    router.add_api_route("/due", _make_due(get_service, lang), methods=["POST"])
    router.add_api_route("/info/{card_id}", _info, methods=["GET"])
    return router
