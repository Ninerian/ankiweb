from __future__ import annotations
from typing import Callable
from fastapi import APIRouter
from datastar_py.fastapi import DatastarResponse, ServerSentEventGenerator as SSE, ReadSignals
from ankiweb.screens import templating


def render_deckbrowser_html(col) -> str:
    tree = col.sched.deck_due_tree()
    current_id = col.decks.get_current_id()
    children = tree.children if tree is not None else []
    return templating.render(
        "deckbrowser.html.jinja",
        children=children,
        current_id=current_id,
        studied_today=col.studied_today(),
    )


def make_deckbrowser_routes(get_service: Callable) -> APIRouter:
    router = APIRouter(prefix="/deckbrowser")

    @router.post("/open/{did}")
    async def open_deck(did: int):
        service = get_service()
        await service.run_op(lambda col: col.decks.set_current(did), initiator="deckbrowser")
        return DatastarResponse(SSE.redirect("/overview"))

    @router.post("/select/{did}")
    async def select_deck(did: int):
        service = get_service()
        await service.run_op(lambda col: col.decks.set_current(did), initiator="deckbrowser")
        return DatastarResponse(SSE.execute_script("window.location.reload()"))

    @router.post("/collapse/{did}")
    async def collapse_deck(did: int):
        service = get_service()

        def toggle(col):
            from anki.decks import DeckCollapseScope
            collapsed = bool(col.decks.get(did).get("collapsed", False))
            return col.decks.set_collapsed(did, not collapsed, DeckCollapseScope.REVIEWER)

        await service.run_op(toggle, initiator="deckbrowser")
        return DatastarResponse(SSE.execute_script("window.location.reload()"))

    @router.post("/create")
    async def create_deck(payload: ReadSignals):
        service = get_service()
        name = ""
        if payload and isinstance(payload, dict):
            name = str(payload.get("name", "")).strip()
        if name:
            await service.run_op(
                lambda col: col.decks.add_normal_deck_with_name(name),
                initiator="deckbrowser",
            )
            return DatastarResponse(SSE.execute_script("window.location.reload()"))
        return DatastarResponse()

    @router.post("/opts/{did}")
    async def opts_deck(did: int):
        service = get_service()
        is_dyn = await service.run(lambda col: bool(col.decks.get(did).get("dyn")))
        path = f"/filtered-deck/{did}" if is_dyn else f"/deck-options/{did}"
        return DatastarResponse(SSE.redirect(path))

    @router.post("/createfiltered")
    async def create_filtered():
        return DatastarResponse(SSE.redirect("/filtered-deck"))

    return router
