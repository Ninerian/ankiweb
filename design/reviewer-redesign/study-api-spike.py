"""SPIKE: JSON study API on top of the native reviewer functions.

GET  /api/study/next?deck=<name>  -> queue head + counts + rendered sides + 4 labels
POST /api/study/answer            -> {"cardId": int, "ease": 1..4}
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ankiweb.adapters.inbound.http_screens.reviewer import (
    ReviewerSession,
    answer_current,
    load_question,
    render_answer,
)


class AnswerBody(BaseModel):
    cardId: int
    ease: int


def _card_payload(col, session: ReviewerSession) -> dict | None:
    q = load_question(col, session)
    if q is None:
        return None
    ans = render_answer(col, session)  # also computes the 4 labels from session.states
    card = session.card
    new, learn, review = col.sched.counts(card)
    return {
        "cardId": card.id,
        "deck": col.decks.name(card.did),
        "question": q["q"],
        "answer": ans["a"],
        "labels": ans["labels"],
        "counts": {"new": new, "learning": learn, "review": review},
    }


def build_router(get_service: Callable) -> APIRouter:
    router = APIRouter(prefix="/api/study")
    session = ReviewerSession()

    @router.get("/next")
    async def next_card(deck: str | None = None):
        service = get_service()

        def fn(col):
            if deck is not None:
                did = col.decks.id_for_name(deck)
                if did is None:
                    raise ValueError(f"deck not found: {deck}")
                col.decks.set_current(did)
            return _card_payload(col, session)

        try:
            payload = await service.run(fn)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return payload or {"finished": True}

    @router.post("/answer")
    async def answer(body: AnswerBody):
        service = get_service()
        if not 1 <= body.ease <= 4:
            raise HTTPException(422, "ease must be 1..4")

        def fn(col):
            if session.card is None or session.card.id != body.cardId:
                raise ValueError("card is not the one in flight; call /next first")
            answer_current(col, session, body.ease)
            return _card_payload(col, session)

        try:
            payload = await service.run(fn)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return payload or {"finished": True}

    return router
