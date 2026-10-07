from __future__ import annotations

import logging
from collections.abc import Callable

from datastar_py.fastapi import (
    DatastarResponse,
    ReadSignals,
)
from datastar_py.fastapi import (
    ServerSentEventGenerator as SSE,
)
from fastapi import APIRouter

from ankiweb.adapters.inbound.http_datastar.common import (
    error_response,
    redirect_response,
    refresh_screen,
)
from ankiweb.adapters.inbound.http_shared import templating

logger = logging.getLogger(__name__)

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


def render_deck_list(col) -> str:
    tree = col.sched.deck_due_tree()
    current_id = col.decks.get_current_id()
    children = tree.children if tree is not None else []
    return templating.render(
        "deckbrowser_list.html.jinja",
        children=children,
        current_id=current_id,
    )


def make_deckbrowser_routes(get_service: Callable) -> APIRouter:
    router = APIRouter(prefix="/deckbrowser")

    @router.post("/open/{did}")
    async def open_deck(did: int):
        service = get_service()
        await service.run_op(
            lambda col: col.decks.set_current(did), initiator="deckbrowser"
        )
        return redirect_response("/overview")
    @router.post("/select/{did}")
    async def select_deck(did: int):
        service = get_service()
        await service.run_op(
            lambda col: col.decks.set_current(did), initiator="deckbrowser"
        )
        return await refresh_screen(
            service, render_deckbrowser_html, selector="#deckbrowser-page"
        )

    @router.post("/collapse/{did}")
    async def collapse_deck(did: int):
        service = get_service()

        def toggle(col):
            from anki.decks import DeckCollapseScope

            collapsed = bool(col.decks.get(did).get("collapsed", False))
            return col.decks.set_collapsed(
                did, not collapsed, DeckCollapseScope.REVIEWER
            )

        await service.run_op(toggle, initiator="deckbrowser")
        return await refresh_screen(
            service, render_deck_list, selector="main.deck-list"
        )

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
            return await refresh_screen(
                service, render_deckbrowser_html, selector="#deckbrowser-page"
            )
        return DatastarResponse()

    @router.post("/rename/{did}")
    async def rename_deck(did: int, payload: ReadSignals):
        service = get_service()
        newname = ""
        if payload and isinstance(payload, dict):
            newname = str(payload.get("name", "")).strip()
        if not newname:
            return DatastarResponse()

        def do_rename(col):
            return col.decks.rename(did, newname)

        try:
            await service.run_op(do_rename, initiator="deckbrowser")
        except Exception as exc:
            logger.exception("Failed to rename deck %s", did)
            return error_response(exc)
        return DatastarResponse(SSE.execute_script("window.location.reload()"))

    @router.post("/delete/{did}")
    async def delete_deck(did: int):
        service = get_service()

        def do_delete(col):
            return col.decks.remove([did])

        try:
            await service.run_op(do_delete, initiator="deckbrowser")
        except Exception as exc:
            logger.exception("Failed to delete deck %s", did)
            return error_response(exc)
        return DatastarResponse(SSE.execute_script("window.location.reload()"))


    return router
