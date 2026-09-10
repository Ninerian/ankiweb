from __future__ import annotations
from ankiweb.screens import templating
from ankiweb.screens.congrats import render_congrats_html


def make_overview_handler(service, hub):
    async def handler(arg: str):
        if arg == "study":
            await service.run(lambda col: col.startTimebox())
            await hub.push_call("overview", "ankiwebNavigate", ["/reviewer"])
        elif arg == "decks":
            await hub.push_call("overview", "ankiwebNavigate", ["/deckbrowser"])
        elif arg == "unbury":
            def unbury(col):
                from anki.scheduler.base import UnburyDeck
                return col.sched.unbury_deck(col.decks.get_current_id(), UnburyDeck.Mode.ALL)
            await service.run_op(unbury, initiator="overview")
            await hub.push_call("overview", "ankiwebReload", [])
        elif arg in ("refresh", "empty"):
            did = await service.run(lambda col: col.decks.get_current_id())
            is_dyn = await service.run(lambda col: bool(col.decks.get(did).get("dyn")))
            if is_dyn:  # rebuild/empty raise FilteredDeckError on a normal deck
                if arg == "refresh":
                    await service.run_op(lambda col: col.sched.rebuild_filtered_deck(did),
                                         initiator="overview")
                else:
                    await service.run_op(lambda col: col.sched.empty_filtered_deck(did),
                                         initiator="overview")
                await hub.push_call("overview", "ankiwebReload", [])
        elif arg == "studymore":
            await hub.push_call("overview", "ankiwebNavigate", ["/custom-study"])
        elif arg == "opts":
            did = await service.run(lambda col: col.decks.get_current_id())
            is_dyn = await service.run(lambda col: bool(col.decks.get(did).get("dyn")))
            path = (f"/filtered-deck/{did}") if is_dyn else (f"/deck-options/{did}")
            await hub.push_call("overview", "ankiwebNavigate", [path])
        elif arg.startswith("setdesc:"):
            import json
            try:
                p = json.loads(arg[len("setdesc:"):])
            except Exception:
                return None

            def save_desc(col):
                did = col.decks.get_current_id()
                d = col.decks.get(did)
                d["desc"] = p.get("desc", "")
                d["md"] = bool(p.get("md", False))
                return col.decks.update_dict(d)

            await service.run_op(save_desc, initiator="overview")
            await hub.push_call("overview", "ankiwebReload", [])
        return None

    return handler


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
        "overview.html",
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
