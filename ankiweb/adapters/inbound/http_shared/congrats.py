from __future__ import annotations
from ankiweb.core.i18n import tr
from ankiweb.core.html_sanitize import sanitize_html
from ankiweb.adapters.inbound.http_shared import templating

SECOND = 1.0
MINUTE = 60.0 * SECOND
HOUR = 60.0 * MINUTE
DAY = 24.0 * HOUR
MONTH = (365.0 * DAY) / 12
YEAR = 365.0 * DAY


def _natural_unit(secs: float) -> str:
    secs = abs(secs)
    if secs < MINUTE:
        return "seconds"
    elif secs < HOUR:
        return "minutes"
    elif secs < DAY:
        return "hours"
    elif secs < MONTH:
        return "days"
    elif secs < YEAR:
        return "months"
    else:
        return "years"


def _unit_seconds(unit: str) -> float:
    if unit == "seconds":
        return SECOND
    elif unit == "minutes":
        return MINUTE
    elif unit == "hours":
        return HOUR
    elif unit == "days":
        return DAY
    elif unit == "months":
        return MONTH
    elif unit == "years":
        return YEAR
    return SECOND


def _build_next_learn_msg(info) -> str:
    secs_until = info.secs_until_next_learn
    if secs_until >= 86_400:
        return ""
    unit = _natural_unit(secs_until)
    amount = int(round(secs_until / _unit_seconds(unit)))
    next_learn_due = tr.scheduling_next_learn_due(amount=amount, unit=unit)
    remaining = tr.scheduling_learn_remaining(remaining=info.learn_remaining)
    return f"{next_learn_due} {remaining}"


def _bridge_link(command: str, label: str) -> str:
    if command == "unbury":
        return f'<a href="#" data-on:click__prevent="@post(\'/overview/unbury\')">{label}</a>'
    elif command == "customStudy":
        return f'<a href="#" data-on:click__prevent="@post(\'/overview/studymore\')">{label}</a>'
    return f'<a href="#">{label}</a>'


def render_congrats_html(col) -> str:
    info = col.sched.congratulations_info()

    next_learn_msg = _build_next_learn_msg(info)
    today_reviews = (
        tr.scheduling_today_review_limit_reached() if info.review_remaining else ""
    )
    today_new = (
        tr.scheduling_today_new_limit_reached() if info.new_remaining else ""
    )

    show_buried = bool(
        info.bridge_commands_supported
        and (info.have_sched_buried or info.have_user_buried)
    )
    buried_msg = ""
    if show_buried:
        unbury_them = _bridge_link("unbury", tr.scheduling_unbury_them())
        buried_msg = tr.scheduling_buried_cards_found(unbury_them=unbury_them)

    show_custom_study = bool(
        info.bridge_commands_supported and not info.is_filtered_deck
    )
    custom_study_msg = ""
    if show_custom_study:
        custom_study = _bridge_link("customStudy", tr.scheduling_custom_study())
        custom_study_msg = tr.scheduling_how_to_custom_study(custom_study=custom_study)

    raw_desc = info.deck_description
    if not raw_desc:
        try:
            deck = col.decks.current()
            raw_desc = deck.get("desc", "")
            if raw_desc and deck.get("md"):
                raw_desc = col.render_markdown(raw_desc)
        except Exception:
            raw_desc = ""
    sanitized_desc = sanitize_html(raw_desc) if raw_desc else ""

    return templating.render(
        "congrats.html.jinja",
        congrats=tr.scheduling_congratulations_finished(),
        next_learn_msg=next_learn_msg,
        review_remaining=info.review_remaining,
        today_reviews=today_reviews,
        new_remaining=info.new_remaining,
        today_new=today_new,
        show_buried=show_buried,
        buried_msg=buried_msg,
        show_custom_study=show_custom_study,
        custom_study_msg=custom_study_msg,
        deck_description=sanitized_desc,
    )
