from __future__ import annotations

from ankiweb.adapters.inbound.http_shared import templating


def render_export_html(col) -> str:
    decks = col.decks.all_names_and_ids(
        skip_empty_default=False, include_filtered=False
    )
    return templating.render("export.html.jinja", decks=decks)
