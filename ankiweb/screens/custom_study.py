from __future__ import annotations
import json
from ankiweb.i18n import tr
from ankiweb.screens import templating


def render_custom_study_html(col) -> str:
    did = col.decks.get_current_id()
    d = col.sched.custom_study_defaults(did)
    avail_new = d.available_new + d.available_new_in_children
    avail_rev = d.available_review + d.available_review_in_children

    radios = [
        (1, tr.custom_study_increase_todays_new_card_limit()),
        (2, tr.custom_study_increase_todays_review_card_limit()),
        (3, tr.custom_study_review_forgotten_cards()),
        (4, tr.custom_study_review_ahead()),
        (5, tr.custom_study_preview_new_cards()),
        (6, tr.custom_study_study_by_card_state_or_tag()),
    ]

    kinds = [
        (1, tr.custom_study_new_cards_only()),
        (0, tr.custom_study_due_cards_only()),
        (2, tr.custom_study_all_review_cards_in_random_order()),
        (3, tr.custom_study_all_cards_in_random_order_dont()),
    ]
    tags = [t.name for t in d.tags]

    # per-radio config: [label, default, suffix, min]
    cfg = {
        1: [tr.custom_study_increase_todays_new_card_limit_by(), d.extend_new or 0, tr.custom_study_cards(), -9999],
        2: [tr.custom_study_increase_todays_review_limit_by(), d.extend_review or 0, tr.custom_study_cards(), -9999],
        3: [tr.custom_study_review_cards_forgotten_in_last(), 1, tr.scheduling_days(), 1],
        4: [tr.custom_study_review_ahead_by(), 1, tr.scheduling_days(), 1],
        5: [tr.custom_study_preview_new_cards_added_in_the(), 1, tr.scheduling_days(), 1],
        6: [tr.custom_study_select(), 100, tr.custom_study_cards_from_the_deck(), 1],
    }

    return templating.render(
        "custom_study.html.jinja",
        radios=radios,
        kinds=kinds,
        tags=tags,
        avail_new=avail_new,
        avail_rev=avail_rev,
        spin_default=cfg[1][1],
        cfg_json=json.dumps(cfg),
    )


def make_custom_study_handler(service, hub):
    async def handler(arg: str):
        cmd, _, rest = arg.partition(":")
        if cmd == "cancel":
            await hub.push_call("customstudy", "ankiwebNavigate", ["/overview"])
            return None
        if cmd != "submit":
            return None
        try:
            p = json.loads(rest)
        except Exception:
            return None
        radio = int(p.get("radio", 1))
        value = int(p.get("value", 0))

        def build_and_run(col):
            import anki.scheduler_pb2 as sp
            did = col.decks.get_current_id()
            req = sp.CustomStudyRequest(deck_id=did)
            if radio == 1:
                req.new_limit_delta = value
            elif radio == 2:
                req.review_limit_delta = value
            elif radio == 3:
                req.forgot_days = value
            elif radio == 4:
                req.review_ahead_days = value
            elif radio == 5:
                req.preview_days = value
            elif radio == 6:
                req.cram.kind = int(p.get("cram_kind", 1))
                req.cram.card_limit = value
                req.cram.tags_to_include.extend(p.get("include", []))
                req.cram.tags_to_exclude.extend(p.get("exclude", []))
            return col.sched.custom_study(req)

        try:
            await service.run_op(build_and_run, initiator="customstudy")
        except Exception as e:
            from anki.errors import CustomStudyError
            msg = str(e) if isinstance(e, CustomStudyError) else "Could not create a custom study session."
            await hub.push_call("customstudy", "ankiwebCustomStudyError", [msg])
            return None
        await hub.push_call("customstudy", "ankiwebNavigate", ["/overview"])
        return None

    return handler
