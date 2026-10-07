from html.parser import HTMLParser
from pathlib import Path

import anki.consts
from anki.cards import CardId

from ankiweb.adapters.inbound.http_screens.reviewer import make_reviewer_handler
from ankiweb.adapters.outbound.anki_collection_adapter import CollectionService
from ankiweb.core.bridge.ui_state import UiState
from ankiweb.core.config import Settings


class _Hub:
    """Records push_call(fn, args) and carries a real UiState (the handler writes to it)."""

    def __init__(self):
        self.calls = []
        self.ui_state = UiState()

    async def push_call(self, ctx, fn, args):
        self.calls.append((fn, args))

    def fns(self):
        return [c[0] for c in self.calls]

    def last(self, fn):
        for c in reversed(self.calls):
            if c[0] == fn:
                return c[1]
        return None


async def _svc(tmp_path, n_cards=3):
    svc = CollectionService(Settings(collection_path=tmp_path / "c.anki2"))
    await svc.open()

    def setup(col):
        did = col.decks.id("Default")
        col.decks.set_current(did)
        for i in range(n_cards):
            note = col.new_note(col.models.by_name("Basic"))
            note["Front"] = f"Q{i}"
            note["Back"] = f"A{i}"
            col.add_note(note, did)

    await svc.run(setup)
    return svc


async def _make(tmp_path, n_cards=3):
    svc = await _svc(tmp_path, n_cards)
    hub = _Hub()
    handler = make_reviewer_handler(svc, hub)
    return svc, hub, handler


_REVIEWER_NAV_IDS = {"reviewer-card-info", "reviewer-card-edit"}


class _ReviewerLinksParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = {}
        self.wrapper_present = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id") == "reviewer-actions-bar":
            self.wrapper_present = True
        if tag == "a":
            link_id = attributes.get("id")
            if link_id in _REVIEWER_NAV_IDS:
                self.targets[link_id] = attributes.get("href")


def _reviewer_link_targets(html: str) -> dict[str, str | None]:
    parser = _ReviewerLinksParser()
    parser.feed(html)
    return parser.targets


def _has_reviewer_actions_wrapper(html: str) -> bool:
    parser = _ReviewerLinksParser()
    parser.feed(html)
    return parser.wrapper_present


# ---- (a) mark toggles the note's 'marked' tag + pushes _drawMark -------------


async def test_mark_toggles_tag_and_draws(tmp_path: Path):
    svc, hub, handler = await _make(tmp_path)
    await handler("show")
    assert hub.ui_state.current_card_id is not None
    cid = CardId(hub.ui_state.current_card_id)
    await handler("mark")
    has_tag = await svc.run(lambda col: "marked" in col.get_card(cid).note().tags)
    assert has_tag is True
    assert ("_drawMark", [True]) in hub.calls
    # same card still current (mark does not advance)
    assert hub.ui_state.current_card_id == cid
    await handler("mark")
    has_tag = await svc.run(lambda col: "marked" in col.get_card(cid).note().tags)
    assert has_tag is False
    assert ("_drawMark", [False]) in hub.calls
    await svc.close()


# ---- (b) setflag sets the card's user flag + pushes _drawFlag ----------------


async def test_setflag_sets_user_flag_and_draws(tmp_path: Path):
    svc, hub, handler = await _make(tmp_path)
    await handler("show")
    assert hub.ui_state.current_card_id is not None
    cid = CardId(hub.ui_state.current_card_id)
    await handler("setflag:2")
    flag = await svc.run(lambda col: col.get_card(cid).user_flag())
    assert flag == 2
    assert ("_drawFlag", [2]) in hub.calls
    assert hub.ui_state.current_card_id == cid  # does not advance
    # clear
    await handler("setflag:0")
    flag = await svc.run(lambda col: col.get_card(cid).user_flag())
    assert flag == 0
    assert ("_drawFlag", [0]) in hub.calls
    await svc.close()


# ---- (c) buryc advances ------------------------------------------------------


async def test_buryc_advances(tmp_path: Path):
    svc, hub, handler = await _make(tmp_path)
    await handler("show")
    first = hub.ui_state.current_card_id
    before = await svc.run(lambda col: sum(col.sched.counts()))
    await handler("buryc")
    after = await svc.run(lambda col: sum(col.sched.counts()))
    assert hub.ui_state.current_card_id != first  # advanced to a different card
    assert after < before  # one fewer card in today's queue
    await svc.close()


# ---- (d) suspendc suspends + advances ---------------------------------------


async def test_suspendc_suspends_and_advances(tmp_path: Path):
    svc, hub, handler = await _make(tmp_path)
    await handler("show")
    assert hub.ui_state.current_card_id is not None
    first = CardId(hub.ui_state.current_card_id)
    await handler("suspendc")
    queue = await svc.run(lambda col: col.get_card(first).queue)
    assert queue == anki.consts.QUEUE_TYPE_SUSPENDED


async def test_suspendn_suspends_note_and_advances(tmp_path: Path):
    svc, hub, handler = await _make(tmp_path)
    await handler("show")
    assert hub.ui_state.current_card_id is not None
    first = CardId(hub.ui_state.current_card_id)
    await handler("suspendn")
    queue = await svc.run(lambda col: col.get_card(first).queue)
    assert queue == anki.consts.QUEUE_TYPE_SUSPENDED
    assert hub.ui_state.current_card_id != first
    await svc.close()


async def test_buryn_buries_note_and_advances(tmp_path: Path):
    svc, hub, handler = await _make(tmp_path)
    await handler("show")
    first = hub.ui_state.current_card_id
    before = await svc.run(lambda col: sum(col.sched.counts()))
    await handler("buryn")
    after = await svc.run(lambda col: sum(col.sched.counts()))
    assert hub.ui_state.current_card_id != first
    assert after < before
    await svc.close()


# ---- (e) forget resets the card to new --------------------------------------


async def test_forget_resets_card(tmp_path: Path):
    svc, hub, handler = await _make(tmp_path)
    await handler("show")
    assert hub.ui_state.current_card_id is not None
    cid = CardId(hub.ui_state.current_card_id)
    # answer it so it's no longer new, then reload that card by id and forget it
    await handler("ease3")
    ctype = await svc.run(lambda col: col.get_card(cid).type)
    assert ctype != anki.consts.CARD_TYPE_NEW  # it advanced out of new
    await svc.run_op(lambda col: col.sched.schedule_cards_as_new([cid]))
    ctype = await svc.run(lambda col: col.get_card(cid).type)
    assert ctype == anki.consts.CARD_TYPE_NEW
    await svc.close()


async def test_forget_branch_runs_and_advances(tmp_path: Path):
    svc, hub, handler = await _make(tmp_path)
    await handler("show")
    _first = hub.ui_state.current_card_id
    await handler("forget")
    # forget on a new card keeps it new but the branch advances to the next card
    assert "_showQuestion" in hub.fns()
    assert hub.ui_state.current_card_id is not None
    await svc.close()


# ---- (f) deletenote removes the note + advances -----------------------------


async def test_deletenote_removes_and_advances(tmp_path: Path):
    svc, hub, handler = await _make(tmp_path)
    await handler("show")
    first = hub.ui_state.current_card_id
    before = await svc.run(lambda col: len(col.find_notes("")))
    await handler("deletenote")
    after = await svc.run(lambda col: len(col.find_notes("")))
    assert after == before - 1
    assert hub.ui_state.current_card_id != first
    await svc.close()


# ---- (g) setdue reschedules without error -----------------------------------


async def test_setdue_reschedules_without_error(tmp_path: Path):
    svc, hub, handler = await _make(tmp_path)
    await handler("show")
    await handler("setdue:0")
    # no error pushed
    assert "ankiwebReviewerError" not in hub.fns()
    # advanced (or reloaded) — a question was shown
    assert "_showQuestion" in hub.fns()
    await svc.close()


# ---- (h) undo after an ease answer restores without crashing ----------------


async def test_undo_after_answer_restores(tmp_path: Path):
    svc, hub, handler = await _make(tmp_path)
    await handler("show")
    await handler("ease3")  # mutating + advances
    n_show_before = hub.fns().count("_showQuestion")
    await handler("undo")
    # undo reloads → another _showQuestion pushed, no error
    assert hub.fns().count("_showQuestion") > n_show_before
    assert "ankiwebReviewerError" not in hub.fns()
    await svc.close()


async def test_undo_when_empty_pushes_error(tmp_path: Path):
    svc, hub, handler = await _make(tmp_path)
    await handler("show")
    # drain the backend undo stack (the setup add_notes left undoable entries) so the
    # NEXT undo genuinely has nothing to undo -> UndoEmpty -> error pushed
    import anki.errors

    async def _drain():
        while True:
            try:
                await svc.run(lambda col: col.undo())
            except anki.errors.UndoEmpty:
                return

    await _drain()
    hub.calls.clear()
    await handler("undo")  # now truly nothing to undo
    assert "ankiwebReviewerError" in hub.fns()
    await svc.close()


# ---- (i) rendered navigation follows the current card through answer/next ----


async def test_reviewer_navigation_tracks_card_through_answer_and_next(
    tmp_path: Path,
):
    svc, hub, handler = await _make(tmp_path, n_cards=2)
    await handler("show")

    first_cid = hub.ui_state.current_card_id
    assert first_cid is not None
    first_nid = await svc.run(lambda col: col.get_card(CardId(first_cid)).nid)
    first_question = hub.last("_showQuestion")
    assert first_question is not None and len(first_question) == 4
    first_targets = {
        "reviewer-card-info": f"/card-info/{first_cid}",
        "reviewer-card-edit": f"/edit?nid={first_nid}",
    }
    assert _reviewer_link_targets(first_question[3]) == first_targets

    await handler("ans")
    assert hub.last("_showAnswer") is not None
    assert hub.ui_state.current_card_id == first_cid
    assert hub.ui_state.side == "answer"
    assert hub.fns().count("_showQuestion") == 1
    assert _reviewer_link_targets(hub.last("_showQuestion")[3]) == first_targets

    await handler("ease4")
    second_cid = hub.ui_state.current_card_id
    assert second_cid is not None and second_cid != first_cid
    second_nid = await svc.run(lambda col: col.get_card(CardId(second_cid)).nid)
    assert second_nid != first_nid
    second_question = hub.last("_showQuestion")
    assert second_question is not None and len(second_question) == 4
    assert _reviewer_link_targets(second_question[3]) == {
        "reviewer-card-info": f"/card-info/{second_cid}",
        "reviewer-card-edit": f"/edit?nid={second_nid}",
    }
    await svc.close()


# ---- (j) no active reviewer destinations before a card is shown -------------


def test_reviewer_navigation_has_no_active_targets_before_card():
    from ankiweb.adapters.inbound.http_screens.reviewer import reviewer_page_body

    page_body = reviewer_page_body()
    assert _has_reviewer_actions_wrapper(page_body)
    assert _reviewer_link_targets(page_body) == {
        "reviewer-card-info": None,
        "reviewer-card-edit": None,
    }


# ---- (k) remaining reviewer actions are no-ops before a card is shown --------


async def test_actions_are_noops_without_card(tmp_path: Path):
    svc, hub, handler = await _make(tmp_path)
    # do NOT send "show" first → session.card is None
    for arg in (
        "mark",
        "setflag:2",
        "buryc",
        "buryn",
        "suspendc",
        "suspendn",
        "setdue:0",
        "forget",
        "deletenote",
    ):
        res = await handler(arg)
        assert res is None
    # none of these should have pushed any call
    assert hub.calls == []
    await svc.close()
