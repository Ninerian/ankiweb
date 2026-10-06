"""Native Reviewer bridge screen and session handler.

Transport boundary:
- Operates over WebSocket `/ws?context=reviewer` handling desktop `pycmd` verbs
  (`show`, `ans`, `ease1`..`ease4`, `replay`, `play:<side>:<idx>`, `mark`, `setflag:`,
  `buryc`, `buryn`, `suspendc`, `suspendn`, `setdue:`, `forget`, `deletenote`, `undo`,
  `cardinfo`, `edit`, `starttimer`).
- Server pushes QA rendering and ease bars (`_showQuestion`, `_showAnswer`,
  `ankiwebSetAnswerBar`) and AV audio filenames (`ankiwebPlayAudio`).
- Audio playback and MathJax rendering are client runtime side effects; no audio or
  typesetting runs over WebSocket frames.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from anki.sound import AV_REF_RE, SoundOrVideoTag

from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.core.i18n import tr

logger = logging.getLogger(__name__)

def render_av_buttons(text: str) -> str:
    """Replace [anki:play:<side>:<N>] refs with inline replay buttons (pycmd('play:..'))."""

    def repl(m):
        ref = m.group(1)  # e.g. "play:q:0"
        return templating.render("reviewer_replay_button.html.jinja", ref=ref)

    return AV_REF_RE.sub(repl, text)


def av_sound_filenames(card, question_side: bool) -> list:
    """Ordered playable filenames for one side (SoundOrVideoTag only; TTS skipped)."""
    tags = card.question_av_tags() if question_side else card.answer_av_tags()
    return [t.filename for t in tags if isinstance(t, SoundOrVideoTag)]


def answer_side_audio(card) -> list:
    """Answer-side REPLAY list: question audio first if replayq, then answer audio."""
    files = []
    if card.replay_question_audio_on_answer_side():
        files += av_sound_filenames(card, True)
    files += av_sound_filenames(card, False)
    return files


@dataclass
class ReviewerSession:
    """Holds the in-flight card (timer started) and its scheduling states between
    show-question, show-answer, and answer. Single-user → one session per reviewer."""

    card: Any = None  # anki.cards.Card with start_timer() already called
    states: Any = None  # SchedulingStates from the queue
    context: Any = None  # SchedulingContext
    type_correct: Any = None  # expected answer string when the card has {{type:Field}}
    type_combining: bool = True
    type_font: str = "Arial"
    type_size: int = 20
    typed_answer: str = ""  # the user's typed value, set by the "typed:" command


def load_question(col, session: ReviewerSession) -> dict | None:
    """Fetch the top queued card into the session, start its timer, render the question.
    Returns {"q","a","bodyclass"} or None when there are no cards left (finished)."""
    queued = col.sched.get_queued_cards(fetch_limit=1)
    if not queued.cards:
        session.card = session.states = session.context = None
        return None
    top = queued.cards[0]
    card = col.get_card(top.card.id)
    card.start_timer()  # REQUIRED: build_answer() later calls card.time_taken()
    session.card = card
    session.states = top.states
    session.context = top.context
    from ankiweb.adapters.inbound.http_shared.type_answer import (
        type_answer_question_filter,
    )

    q = type_answer_question_filter(col, card, session, card.question())
    return {
        "q": render_av_buttons(q),
        "a": render_av_buttons(card.answer()),
        "bodyclass": f"card card{card.ord + 1}",
    }


def render_answer(col, session: ReviewerSession) -> dict:
    """Render the answer side + the 4 ease interval labels [Again, Hard, Good, Easy].
    Always runs the type-answer filter: replaces [[type:...]] with the compare_answer diff
    when type_correct is set, or strips any stray marker when None (no-op for Basic cards)."""
    from ankiweb.adapters.inbound.http_shared.type_answer import (
        type_answer_answer_filter,
    )

    a = type_answer_answer_filter(col, session, session.card.answer())
    return {
        "a": render_av_buttons(a),
        "labels": list(col.sched.describe_next_states(session.states)),
    }


def answer_current(col, session: ReviewerSession, ease: int):
    """Answer the in-flight card with ease 1..4. Returns OpChanges."""
    from anki.scheduler.v3 import CardAnswer

    rating_map = {
        1: CardAnswer.Rating.AGAIN,
        2: CardAnswer.Rating.HARD,
        3: CardAnswer.Rating.GOOD,
        4: CardAnswer.Rating.EASY,
    }
    answer = col.sched.build_answer(
        card=session.card, states=session.states, rating=rating_map[ease]
    )
    return col.sched.answer_card(answer)


def _ease_names() -> tuple:
    """Per-request so the labels follow the active language."""
    return (
        tr.studying_again(),
        tr.studying_hard(),
        tr.studying_good(),
        tr.studying_easy(),
    )


def show_answer_bar() -> str:
    return templating.render("reviewer_show_answer_bar.html.jinja")


def ease_buttons_bar(labels) -> str:
    """labels: 4 interval strings in order [Again, Hard, Good, Easy]."""
    cells = [
        {
            "i": i,
            "name": name,
            "label": labels[i - 1] if i - 1 < len(labels) else "",
        }
        for i, name in enumerate(_ease_names(), start=1)
    ]
    return templating.render("reviewer_ease_buttons_bar.html.jinja", cells=cells)


def reviewer_actions_bar() -> str:
    """A compact bar of card-action buttons (Anki's reviewer 'More' menu), each issuing a
    pycmd handled by make_reviewer_handler. Labels follow the active language via tr (with
    keyless English fallbacks). Set Due / Forget / Delete prompt/confirm client-side."""

    def lbl(key, fallback):
        f = getattr(tr, key, None)
        return f() if f is not None else fallback

    buttons = [
        {"onclick": "pycmd('mark')", "label": lbl("studying_mark_note", "Mark Note")},
        {"onclick": "pycmd('buryc')", "label": lbl("studying_bury_card", "Bury Card")},
        {"onclick": "pycmd('buryn')", "label": lbl("studying_bury_note", "Bury Note")},
        {
            "onclick": "pycmd('suspendc')",
            "label": lbl("actions_suspend_card", "Suspend Card"),
        },
        {
            "onclick": "pycmd('suspendn')",
            "label": lbl("studying_suspend_note", "Suspend Note"),
        },
        {
            "onclick": "ankiwebSetDue()",
            "label": lbl("actions_set_due_date", "Set Due Date"),
        },
        {
            "onclick": "pycmd('forget')",
            "label": lbl("actions_forget_card", "Reset Card"),
        },
        {
            "onclick": "ankiwebDeleteNote()",
            "label": lbl("studying_delete_note", "Delete Note"),
        },
        {
            "onclick": "pycmd('cardinfo')",
            "label": lbl("actions_card_info", "Card Info"),
        },
        {"onclick": "pycmd('undo')", "label": lbl("undo_undo", "Undo")},
    ]
    # Flag buttons 1..4 + a clear (flag 0)
    flag_labels = [
        ("actions_flag_red", "Red"),
        ("actions_flag_orange", "Orange"),
        ("actions_flag_green", "Green"),
        ("actions_flag_blue", "Blue"),
    ]
    for i, (key, fb) in enumerate(flag_labels, start=1):
        buttons.append(
            {"onclick": f"pycmd('setflag:{i}')", "label": f"⚑ {lbl(key, fb)}"}
        )
    buttons.append(
        {"onclick": "pycmd('setflag:0')", "label": lbl("browsing_no_flag", "No Flag")}
    )
    return templating.render("reviewer_actions_bar.html.jinja", buttons=buttons)


def reviewer_page_body() -> str:
    """The reviewer DOM shell + inline script that registers the JS calls the server
    pushes (_showQuestion/_showAnswer from reviewer.js; ankiwebSetAnswerBar for our bar)
    and asks the server for the first card on load."""
    return templating.render(
        "reviewer_page_body.html.jinja",
        actions_bar=reviewer_actions_bar(),
    )


def make_reviewer_handler(service, hub):
    """Bridge handler for the 'reviewer' context. Owns one ReviewerSession."""
    session = ReviewerSession()

    async def _show_next():
        info = await service.run(lambda col: load_question(col, session))
        if info is None:  # finished → overview (which renders Congrats)
            hub.ui_state.current_card_id = None
            hub.ui_state.side = None
            await hub.push_call("reviewer", "ankiwebNavigate", ["/overview"])
            return
        hub.ui_state.current_card_id = session.card.id
        hub.ui_state.side = "question"
        await hub.push_call(
            "reviewer", "_showQuestion", [info["q"], info["a"], info["bodyclass"]]
        )
        await hub.push_call("reviewer", "ankiwebSetAnswerBar", [show_answer_bar()])
        q_files = await service.run(
            lambda col: (
                av_sound_filenames(session.card, True)
                if session.card.autoplay()
                else []
            )
        )
        if q_files:
            await hub.push_call("reviewer", "ankiwebPlayAudio", [q_files])

    async def handler(arg: str):
        if arg == "show":
            await _show_next()
        elif arg == "ans":
            if session.card is None:
                return
            info = await service.run(lambda col: render_answer(col, session))
            await hub.push_call("reviewer", "_showAnswer", [info["a"]])
            await hub.push_call(
                "reviewer", "ankiwebSetAnswerBar", [ease_buttons_bar(info["labels"])]
            )
            hub.ui_state.side = "answer"
            a_files = await service.run(
                lambda col: (
                    av_sound_filenames(session.card, False)
                    if session.card.autoplay()
                    else []
                )
            )
            if a_files:
                await hub.push_call("reviewer", "ankiwebPlayAudio", [a_files])
        elif arg in ("ease1", "ease2", "ease3", "ease4"):
            if session.card is None:
                return
            ease = int(arg[4:])
            await service.run_op(
                lambda col: answer_current(col, session, ease), initiator="reviewer"
            )
            await _show_next()
        elif arg == "edit":
            if session.card is not None:
                nid = await service.run(lambda col: session.card.nid)
                await hub.push_call(
                    "reviewer", "ankiwebNavigate", ["/edit?nid=" + str(nid)]
                )
        elif arg == "starttimer":
            if session.card is not None:
                await service.run(lambda col: session.card.start_timer())
        elif arg == "replay":
            if session.card is not None:
                is_answer = hub.ui_state.side == "answer"
                files = await service.run(
                    lambda col: (
                        answer_side_audio(session.card)
                        if is_answer
                        else av_sound_filenames(session.card, True)
                    )
                )
                if files:
                    await hub.push_call("reviewer", "ankiwebPlayAudio", [files])
        elif arg.startswith("play:"):
            parts = arg.split(":")
            if len(parts) == 3 and session.card is not None:
                side, idx = parts[1], int(parts[2])

                def one(col):
                    tags = (
                        session.card.question_av_tags()
                        if side == "q"
                        else session.card.answer_av_tags()
                    )
                    if 0 <= idx < len(tags) and isinstance(tags[idx], SoundOrVideoTag):
                        return [tags[idx].filename]
                    return []

                files = await service.run(one)
                if files:
                    await hub.push_call("reviewer", "ankiwebPlayAudio", [files])
        elif arg.startswith("typed:"):
            session.typed_answer = arg[len("typed:") :]
        elif arg == "decks":
            await hub.push_call("reviewer", "ankiwebNavigate", ["/deckbrowser"])
        elif arg == "mark":
            if session.card is None:
                return

            state = {}

            def toggle_mark(col):
                n = session.card.note()
                if "marked" in n.tags:
                    n.tags.remove("marked")
                    state["marked"] = False
                else:
                    n.tags.append("marked")
                    state["marked"] = True
                return col.update_note(n, skip_undo_entry=False)

            await service.run_op(toggle_mark, initiator="reviewer")
            await hub.push_call("reviewer", "_drawMark", [state["marked"]])
        elif arg.startswith("setflag:"):
            if session.card is None:
                return
            try:
                flag = int(arg[len("setflag:") :])
            except ValueError:
                return
            if not 0 <= flag <= 4:
                return
            cid = session.card.id
            await service.run_op(
                lambda col: col.set_user_flag_for_cards(flag, [cid]),
                initiator="reviewer",
            )
            await hub.push_call("reviewer", "_drawFlag", [flag])
        elif arg == "buryc":
            if session.card is None:
                return
            cid = session.card.id
            await service.run_op(
                lambda col: col.sched.bury_cards([cid]), initiator="reviewer"
            )
            await _show_next()
        elif arg == "buryn":
            if session.card is None:
                return
            nid = session.card.note().id
            await service.run_op(
                lambda col: col.sched.bury_notes([nid]), initiator="reviewer"
            )
            await _show_next()
        elif arg == "suspendc":
            if session.card is None:
                return
            cid = session.card.id
            await service.run_op(
                lambda col: col.sched.suspend_cards([cid]), initiator="reviewer"
            )
            await _show_next()
        elif arg == "suspendn":
            if session.card is None:
                return

            def suspend_note(col):
                cids = [c.id for c in session.card.note().cards()]
                return col.sched.suspend_cards(cids)

            await service.run_op(suspend_note, initiator="reviewer")
            await _show_next()
        elif arg.startswith("setdue:"):
            if session.card is None:
                return
            spec = arg[len("setdue:") :]
            cid = session.card.id
            try:
                await service.run_op(
                    lambda col: col.sched.set_due_date([cid], spec),
                    initiator="reviewer",
                )
            except Exception as e:  # invalid spec, etc.
                logger.exception("Failed to set due date for card %s", cid)
                await hub.push_call("reviewer", "ankiwebReviewerError", [str(e)])
                return
            await _show_next()
        elif arg == "forget":
            if session.card is None:
                return
            cid = session.card.id
            await service.run_op(
                lambda col: col.sched.schedule_cards_as_new([cid]), initiator="reviewer"
            )
            await _show_next()
        elif arg == "deletenote":
            if session.card is None:
                return
            nid = session.card.note().id
            await service.run_op(
                lambda col: col.remove_notes([nid]), initiator="reviewer"
            )
            await _show_next()
        elif arg == "undo":
            if session.card is None:
                return
            import anki.errors

            try:
                await service.run_op(lambda col: col.undo(), initiator="reviewer")
            except anki.errors.UndoEmpty:
                await hub.push_call(
                    "reviewer", "ankiwebReviewerError", [tr.actions_nothing_to_undo()]
                )
                return
            await _show_next()
        elif arg == "cardinfo":
            if session.card is None:
                return
            cid = session.card.id
            await hub.push_call(
                "reviewer", "ankiwebNavigate", ["/card-info/" + str(cid)]
            )
        # ignore everything else (e.g. reviewer.js emits "updateToolbar" after each render)
        return

    return handler
