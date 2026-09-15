from __future__ import annotations
from ankiweb.i18n import tr
from ankiweb.adapters.inbound.http_shared import templating


def render_congrats_html(col) -> str:
    """Simple server-rendered finished screen (the real SvelteKit congrats is a later plan)."""
    info = col.sched.congratulations_info()
    learn_remaining_mins = (
        max(1, info.secs_until_next_learn // 60) if info.learn_remaining else None
    )
    show_unbury = bool(info.have_user_buried or info.have_sched_buried)
    return templating.render(
        "congrats.html.jinja",
        heading=tr.scheduling_congratulations_finished(),
        learn_remaining_mins=learn_remaining_mins,
        show_unbury=show_unbury,
    )
