from __future__ import annotations
from typing import Callable
from fastapi import APIRouter
from datastar_py.fastapi import (
    DatastarResponse,
    ServerSentEventGenerator as SSE,
    ReadSignals,
)
from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.adapters.inbound.http_shared.congrats import render_congrats_html


def make_overview_routes(get_service: Callable) -> APIRouter:
    router = APIRouter(prefix="/overview")

    @router.post("/study")
    async def study():
        service = get_service()
        await service.run(lambda col: col.startTimebox())
        return DatastarResponse(SSE.redirect("/reviewer"))

    @router.post("/decks")
    async def decks():
        return DatastarResponse(SSE.redirect("/deckbrowser"))

    @router.post("/unbury")
    async def unbury():
        service = get_service()

        def do_unbury(col):
            from anki.scheduler.base import UnburyDeck

            return col.sched.unbury_deck(
                col.decks.get_current_id(), UnburyDeck.Mode.ALL
            )

        await service.run_op(do_unbury, initiator="overview")
        return DatastarResponse(SSE.execute_script("window.location.reload()"))

    @router.post("/refresh")
    async def refresh():
        service = get_service()
        did = await service.run(lambda col: col.decks.get_current_id())
        is_dyn = await service.run(lambda col: bool(col.decks.get(did).get("dyn")))
        if is_dyn:
            await service.run_op(
                lambda col: col.sched.rebuild_filtered_deck(did), initiator="overview"
            )
            return DatastarResponse(SSE.execute_script("window.location.reload()"))
        return DatastarResponse()

    @router.post("/empty")
    async def empty():
        service = get_service()
        did = await service.run(lambda col: col.decks.get_current_id())
        is_dyn = await service.run(lambda col: bool(col.decks.get(did).get("dyn")))
        if is_dyn:
            await service.run_op(
                lambda col: col.sched.empty_filtered_deck(did), initiator="overview"
            )
            return DatastarResponse(SSE.execute_script("window.location.reload()"))
        return DatastarResponse()

    @router.post("/studymore")
    async def studymore():
        return DatastarResponse(SSE.redirect("/custom-study"))

    @router.post("/opts")
    async def opts():
        service = get_service()
        did = await service.run(lambda col: col.decks.get_current_id())
        is_dyn = await service.run(lambda col: bool(col.decks.get(did).get("dyn")))
        path = f"/filtered-deck/{did}" if is_dyn else f"/deck-options/{did}"
        return DatastarResponse(SSE.redirect(path))

    @router.post("/setdesc")
    async def setdesc(payload: ReadSignals):
        service = get_service()
        if not payload or not isinstance(payload, dict):
            return DatastarResponse()

        p = payload

        def save_desc(col):
            did = col.decks.get_current_id()
            d = col.decks.get(did)
            d["desc"] = p.get("desc", "")
            d["md"] = bool(p.get("md", False))
            return col.decks.update_dict(d)

        await service.run_op(save_desc, initiator="overview")
        return DatastarResponse(SSE.execute_script("window.location.reload()"))

    return router


def render_overview_html(col) -> str:
    deck = col.decks.current()
    new, learn, review = col.sched.counts()
    if new + learn + review == 0:
        # Nothing queued (counts already reflect limits/buried) → finished. Public-API
        # alternative to the private col.sched._is_finished().
        return render_congrats_html(col)

    raw = deck.get("desc", "")
    desc = col.render_markdown(raw) if (raw and deck.get("md")) else raw
    desc_is_markdown = bool(deck.get("md"))

    return templating.render(
        "overview.html.jinja",
        name=deck["name"],
        desc=desc,
        desc_is_markdown=desc_is_markdown,
        raw_desc=raw,
        md_checked=bool(deck.get("md")),
        new=new,
        learn=learn,
        review=review,
        is_dyn=bool(deck.get("dyn")),
        have_buried=col.sched.have_buried(),
    )
