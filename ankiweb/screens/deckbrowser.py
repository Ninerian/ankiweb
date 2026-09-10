from __future__ import annotations
from ankiweb.screens import templating


def render_deckbrowser_html(col) -> str:
    tree = col.sched.deck_due_tree()
    current_id = col.decks.get_current_id()
    children = tree.children if tree is not None else []
    return templating.render(
        "deckbrowser.html",
        children=children,
        current_id=current_id,
        studied_today=col.studied_today(),
    )


def make_deckbrowser_handler(service, hub):
    """Returns an async bridge handler(arg) for the 'deckbrowser' context."""
    async def handler(arg: str):
        cmd, _, rest = arg.partition(":")
        if cmd == "open" or cmd == "select":
            did = int(rest)
            await service.run_op(lambda col: col.decks.set_current(did), initiator="deckbrowser")
            if cmd == "open":
                await hub.push_call("deckbrowser", "ankiwebNavigate", ["/overview"])
            else:
                await hub.push_call("deckbrowser", "ankiwebReload", [])
        elif cmd == "collapse":
            did = int(rest)

            def toggle(col):
                from anki.decks import DeckCollapseScope
                # Read persisted state from the deck dict, NOT the due-tree node:
                # deck_due_tree() prunes empty decks, so a node may be missing.
                collapsed = bool(col.decks.get(did).get("collapsed", False))
                return col.decks.set_collapsed(did, not collapsed, DeckCollapseScope.REVIEWER)

            await service.run_op(toggle, initiator="deckbrowser")
            await hub.push_call("deckbrowser", "ankiwebReload", [])
        elif cmd == "create":
            name = rest.strip()
            if name:
                await service.run_op(
                    lambda col: col.decks.add_normal_deck_with_name(name),
                    initiator="deckbrowser",
                )
                await hub.push_call("deckbrowser", "ankiwebReload", [])
        elif cmd == "opts":
            did = int(rest)
            is_dyn = await service.run(lambda col: bool(col.decks.get(did).get("dyn")))
            path = (f"/filtered-deck/{did}") if is_dyn else (f"/deck-options/{did}")
            await hub.push_call("deckbrowser", "ankiwebNavigate", [path])
        elif cmd == "createfiltered":
            await hub.push_call("deckbrowser", "ankiwebNavigate", ["/filtered-deck"])
        return None

    return handler
