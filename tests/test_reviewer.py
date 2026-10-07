import os
import tempfile

import pytest
from anki.collection import Collection

from ankiweb.adapters.inbound.http_screens.reviewer import (
    ReviewerSession,
    answer_current,
    load_question,
    render_answer,
)


@pytest.fixture
def col():
    c = Collection(os.path.join(tempfile.mkdtemp(), "c.anki2"))
    did = c.decks.id("Default")
    assert did is not None
    for i in range(2):
        nt = c.models.by_name("Basic")
        assert nt is not None
        n = c.new_note(nt)
        n["Front"] = f"Q{i}"
        n["Back"] = f"A{i}"
        c.add_note(n, did)
    yield c
    c.close()


def test_load_question_returns_html_and_sets_session(col):
    s = ReviewerSession()
    info = load_question(col, s)
    assert info is not None
    assert "Q0" in info["q"] or "Q1" in info["q"]  # one of the two cards' fronts
    assert info["bodyclass"].startswith("card card")
    assert s.card is not None and s.states is not None


def test_load_question_returns_none_when_finished(col):
    # bury both cards so the queue is empty → finished
    s = ReviewerSession()
    cids = col.find_cards("")
    col.sched.bury_cards(cids)
    assert load_question(col, s) is None
    assert s.card is None


def test_render_answer_has_answer_and_four_labels(col):
    s = ReviewerSession()
    load_question(col, s)
    info = render_answer(col, s)
    assert info is not None
    assert info["a"]  # answer HTML present
    assert len(info["labels"]) == 4  # Again/Hard/Good/Easy interval labels


def test_answer_advances_queue(col):
    s = ReviewerSession()
    load_question(col, s)
    before = col.sched.counts()  # (new, learn, review)
    changes = answer_current(col, s, 3)  # rate Good
    assert changes.study_queues is True
    after = col.sched.counts()
    assert after != before  # answering moved the card


def test_show_answer_bar():
    from ankiweb.adapters.inbound.http_screens.reviewer import show_answer_bar

    html = show_answer_bar()
    assert "Show Answer" in html
    assert "ankiwebShowAnswer()" in html


def test_ease_buttons_bar():
    from ankiweb.adapters.inbound.http_screens.reviewer import ease_buttons_bar

    html = ease_buttons_bar(["<1m", "<6m", "<10m", "3d"])
    for name in ("Again", "Hard", "Good", "Easy"):
        assert name in html
    for i in (1, 2, 3, 4):
        assert f"pycmd('ease{i}')" in html
    assert "3d" in html  # easy interval label rendered


def test_reviewer_page_body_loads_qa_and_registers():
    from ankiweb.adapters.inbound.http_screens.reviewer import reviewer_page_body

    body = reviewer_page_body()
    assert "id='qa'" in body or 'id="qa"' in body
    assert "ankiweb-answer" in body
    assert "registerCalls" in body
    assert "_showQuestion" in body
    assert "pycmd('show')" in body


def test_render_av_buttons_and_filenames():
    from ankiweb.adapters.inbound.http_screens.reviewer import render_av_buttons

    html = render_av_buttons("X [anki:play:q:0] Y [anki:play:a:1] Z")
    assert "[anki:play" not in html
    assert html.count("replay-button") == 2
    assert "pycmd('play:q:0')" in html and "pycmd('play:a:1')" in html


def test_reviewer_body_registers_audio_player():
    from ankiweb.adapters.inbound.http_screens.reviewer import reviewer_page_body

    body = reviewer_page_body()
    assert "ankiwebPlayAudio" in body
    assert "Audio(" in body or "new Audio" in body


def test_reviewer_body_has_shortcuts_guarded():
    from ankiweb.adapters.inbound.http_screens.reviewer import reviewer_page_body

    body = reviewer_page_body()
    assert "keydown" in body
    assert "typeans" in body  # the input guard
    assert "ease" in body  # digit -> ease mapping


