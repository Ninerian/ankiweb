from __future__ import annotations
from anki.sound import AV_REF_RE
from ankiweb.i18n import tr
from ankiweb.screens import templating


def _strip_av(s: str) -> str:
    # preview is static (no reviewer JS) -> drop [anki:play:..] refs so they don't render as text
    return AV_REF_RE.sub("", s or "")


def render_preview_html(col, nid: int) -> str:
    """Read-only preview of every card of a note: each card's rendered question + answer
    (with the card's own CSS), reusing card.render_output(). No scheduling, no mutation."""
    note = col.get_note(nid)
    cards_list = note.cards()
    cards = []
    for c in cards_list:
        o = c.render_output()
        cards.append({
            "template_name": c.template()["name"],
            "question": _strip_av(o.question_and_style()),
            "answer": _strip_av(o.answer_and_style()),
        })
    return templating.render(
        "preview.html.jinja",
        title=tr.actions_preview(),
        cards=cards,
    )
