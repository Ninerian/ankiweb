from __future__ import annotations
import json
from ankiweb.i18n import tr
from ankiweb.screens import templating


def render_preferences_html(col) -> str:
    """Server-rendered Preferences form over col.get_preferences()/set_preferences().
    Mirrors the E4/E5 form screens. The 2 INVERSE checkboxes (legacy timezone, show play
    buttons) render the negated proto value; savePrefs() inverts them back."""
    p = col.get_preferences()
    s, r, e, b = p.scheduling, p.reviewing, p.editing, p.backups

    mix_opts = [
        (0, tr.scheduling_mix_new_cards_and_reviews()),
        (1, tr.scheduling_show_new_cards_after_reviews()),
        (2, tr.scheduling_show_new_cards_before_reviews()),
    ]

    return templating.render(
        "preferences.html.jinja",
        s=s,
        r=r,
        e=e,
        b=b,
        mix_opts=mix_opts,
    )

def make_preferences_handler(service, hub):
    async def handler(arg: str):
        cmd, _, rest = arg.partition(":")
        if cmd == "cancel":
            await hub.push_call("preferences", "ankiwebNavigate", ["/deckbrowser"])
            return None
        if cmd != "savePrefs":
            return None
        try:
            p = json.loads(rest)
        except Exception:
            return None

        def apply(col):
            # Merge onto a FRESH get_preferences() and resend all 4 sections — set_preferences
            # writes each present section's scalars wholesale.
            prefs = col.get_preferences()
            s = prefs.scheduling
            s.rollover = int(p["rollover"])
            s.learn_ahead_secs = int(p["learn_ahead_mins"]) * 60  # form is in minutes
            s.new_review_mix = int(p["new_review_mix"])
            s.new_timezone = bool(p["new_timezone"])
            s.day_learn_first = bool(p["day_learn_first"])
            r = prefs.reviewing
            r.hide_audio_play_buttons = bool(p["hide_audio_play_buttons"])
            r.interrupt_audio_when_answering = bool(p["interrupt_audio_when_answering"])
            r.show_remaining_due_counts = bool(p["show_remaining_due_counts"])
            r.show_intervals_on_buttons = bool(p["show_intervals_on_buttons"])
            r.time_limit_secs = int(p["time_limit_mins"]) * 60  # form is in minutes
            r.load_balancer_enabled = bool(p["load_balancer_enabled"])
            r.fsrs_short_term_with_steps_enabled = bool(p["fsrs_short_term_with_steps_enabled"])
            ed = prefs.editing
            ed.adding_defaults_to_current_deck = bool(p["adding_defaults_to_current_deck"])
            ed.paste_images_as_png = bool(p["paste_images_as_png"])
            ed.paste_strips_formatting = bool(p["paste_strips_formatting"])
            ed.default_search_text = str(p["default_search_text"])
            ed.ignore_accents_in_search = bool(p["ignore_accents_in_search"])
            ed.render_latex = bool(p["render_latex"])
            bk = prefs.backups
            bk.daily = int(p["daily"])
            bk.weekly = int(p["weekly"])
            bk.monthly = int(p["monthly"])
            bk.minimum_interval_mins = int(p["minimum_interval_mins"])
            return col.set_preferences(prefs)

        try:
            await service.run_op(apply, initiator="preferences")
        except Exception as exc:
            await hub.push_call("preferences", "ankiwebPrefsError", [str(exc)])
            return None
        await hub.push_call("preferences", "ankiwebNavigate", ["/deckbrowser"])
        return None

    return handler
