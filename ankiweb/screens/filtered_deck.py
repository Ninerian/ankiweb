from __future__ import annotations
import json
from ankiweb.i18n import tr
from ankiweb.screens import templating


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

    return templating.render(
        "filtered_deck.html.jinja",
        did=g.id,
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
        preview_again=cfg.preview_again_secs,
        preview_hard=cfg.preview_hard_secs,
        preview_good=cfg.preview_good_secs,
        oklabel=oklabel,
    )


def make_filtered_deck_handler(service, hub):
    async def handler(arg: str):
        cmd, _, rest = arg.partition(":")
        if cmd == "cancel":
            await hub.push_call("filtereddeck", "ankiwebNavigate", ["/overview"])
            return None
        if cmd != "submit":
            return None
        try:
            p = json.loads(rest)
        except Exception:
            return None

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
            terms = [dp.Deck.Filtered.SearchTerm(
                search=p.get("search1", ""), limit=int(p.get("limit1", 100)),
                order=int(p.get("order1", 0)))]
            if p.get("second"):
                terms.append(dp.Deck.Filtered.SearchTerm(
                    search=p.get("search2", ""), limit=int(p.get("limit2", 20)),
                    order=int(p.get("order2", 5))))
            del cfg.search_terms[:]
            cfg.search_terms.extend(terms)
            out = col.sched.add_or_update_filtered_deck(g)
            col.decks.set_current(out.id)
            return out

        try:
            await service.run_op(build_and_run, initiator="filtereddeck")
        except Exception as e:
            from anki.errors import FilteredDeckError
            msg = str(e) if isinstance(e, FilteredDeckError) else "Could not build the filtered deck."
            await hub.push_call("filtereddeck", "ankiwebFilteredDeckError", [msg])
            return None
        await hub.push_call("filtereddeck", "ankiwebNavigate", ["/overview"])
        return None

    return handler
