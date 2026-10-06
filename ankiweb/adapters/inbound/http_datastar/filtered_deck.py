from __future__ import annotations

import logging
from collections.abc import Callable
from typing import cast

from datastar_py.fastapi import (
    DatastarResponse,
    ReadSignals,
)
from fastapi import APIRouter

from ankiweb.adapters.inbound.http_datastar.common import (
    error_response,
    redirect_response,
)
from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.core.i18n import tr

logger = logging.getLogger(__name__)

def render_filtered_deck_html(col, deck_id: int) -> str:
    g = col.sched.get_or_create_filtered_deck(deck_id)
    cfg = g.config
    labels = list(col.sched.filtered_deck_order_labels())
    terms = list(cfg.search_terms)
    t0 = terms[0] if terms else None
    t1 = terms[1] if len(terms) > 1 else None
    is_edit = g.id != 0

    name = g.name
    search1 = t0.search if t0 else ""
    limit1 = t0.limit if t0 else 100
    order1 = t0.order if t0 else 0
    has2 = t1 is not None
    search2 = t1.search if t1 else ""
    limit2 = t1.limit if t1 else 20
    order2 = t1.order if t1 else 5
    resched = bool(cfg.reschedule)
    allow_empty = bool(g.allow_empty)
    oklabel = tr.actions_rebuild() if is_edit else tr.decks_build()
    heading = f"{tr.studying_edit() if is_edit else 'Create'} Filtered Deck"
    did = g.id
    preview_again = cfg.preview_again_secs
    preview_hard = cfg.preview_hard_secs
    preview_good = cfg.preview_good_secs
    initial_signals = {
        "error": "",
        "id": did,
        "name": name,
        "allow_empty": allow_empty,
        "resched": resched,
        "preview_again": preview_again,
        "preview_hard": preview_hard,
        "preview_good": preview_good,
        "search1": search1,
        "limit1": limit1,
        "order1": order1,
        "second": has2,
        "search2": search2,
        "limit2": limit2,
        "order2": order2,
    }

    return templating.render(
        "filtered_deck.html.jinja",
        did=did,
        initial_signals=initial_signals,
        name=name,
        heading=heading,
        labels=labels,
        search1=search1,
        limit1=limit1,
        order1=order1,
        has2=has2,
        search2=search2,
        limit2=limit2,
        order2=order2,
        resched=resched,
        allow_empty=allow_empty,
        preview_again=preview_again,
        preview_hard=preview_hard,
        preview_good=preview_good,
        oklabel=oklabel,
    )


def make_filtered_deck_routes(get_service: Callable) -> APIRouter:
    router = APIRouter(prefix="/filtered-deck")

    @router.post("/submit")
    async def submit(payload: ReadSignals):
        service = get_service()
        if not payload or not isinstance(payload, dict):
            return DatastarResponse()
        p = payload

        def build_and_run(col):
            import anki.decks_pb2 as dp

            g = col.sched.get_or_create_filtered_deck(int(p.get("id", 0)))
            g.name = p.get("name", g.name)
            g.allow_empty = bool(p.get("allow_empty"))
            cfg = g.config
            cfg.reschedule = bool(p.get("reschedule"))
            cfg.preview_again_secs = int(p.get("preview_again", 0))
            cfg.preview_hard_secs = int(p.get("preview_hard", 0))
            cfg.preview_good_secs = int(p.get("preview_good", 0))
            del cfg.delays[:]
            terms = [
                dp.Deck.Filtered.SearchTerm(
                    search=p.get("search1", ""),
                    limit=int(p.get("limit1", 100)),
                    order=cast(dp.Deck.Filtered.SearchTerm.Order.ValueType, int(p.get("order1", 0))),
                )
            ]
            if p.get("second"):
                terms.append(
                    dp.Deck.Filtered.SearchTerm(
                        search=p.get("search2", ""),
                        limit=int(p.get("limit2", 20)),
                        order=cast(dp.Deck.Filtered.SearchTerm.Order.ValueType, int(p.get("order2", 5))),
                    )
                )
            del cfg.search_terms[:]
            cfg.search_terms.extend(terms)
            out = col.sched.add_or_update_filtered_deck(g)
            col.decks.set_current(out.id)
            return out

        try:
            await service.run_op(build_and_run, initiator="filtereddeck")
        except Exception as e:
            logger.exception("Failed to build filtered deck")
            from anki.errors import FilteredDeckError

            msg = (
                str(e)
                if isinstance(e, FilteredDeckError)
                else "Could not build the filtered deck."
            )
            return error_response(msg)

        return redirect_response("/overview")

    return router
