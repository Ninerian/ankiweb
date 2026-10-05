import os
import tempfile

import pytest
from anki.collection import Collection

from ankiweb.adapters.inbound.http_datastar.overview import render_overview_html
from ankiweb.adapters.inbound.http_shared.congrats import render_congrats_html


@pytest.fixture
def col():
    c = Collection(os.path.join(tempfile.mkdtemp(), "c.anki2"))
    yield c
    c.close()


def test_overview_shows_counts_and_study_button(col):
    n = col.new_note(col.models.by_name("Basic"))
    n["Front"] = "q"
    col.add_note(n, col.decks.id("Default"))
    col.decks.set_current(col.decks.id("Default"))
    html = render_overview_html(col)
    assert "Default" in html  # deck name heading
    assert "Study Now" in html
    assert "@post('/overview/study')" in html
    assert "new-count" in html  # one new card shown


def test_overview_finished_shows_congrats(col):
    # empty Default deck → counts all zero → congrats
    col.decks.set_current(col.decks.id("Default"))
    html = render_overview_html(col)
    assert "Congratulations" in html or "congrats" in html.lower()


def test_congrats_fragment(col):
    html = render_congrats_html(col)
    assert "Congratulations" in html


def test_congrats_states_and_upstream_parity(col):
    did = col.decks.id("Default")
    col.decks.set_current(did)

    # 1. Base empty deck: congrats heading + custom study link
    html = render_congrats_html(col)
    assert "Congratulations!" in html
    assert "container-sm" in html
    assert "--gutter-block: 1rem" in html
    assert "custom study" in html
    assert "@post('/overview/studymore')" in html
    assert "Back to Decks" in html
    assert "data-on-interval__duration.60s" in html

    # 2. Deck description rendered and sanitized
    deck = col.decks.get(did)
    deck["desc"] = "<p>My <b>special</b> deck description</p><script>alert('xss')</script>"
    col.decks.save(deck)
    html_desc = render_congrats_html(col)
    assert 'class="description"' in html_desc
    assert "My <b>special</b> deck description" in html_desc
    assert "<script>" not in html_desc

    # 3. Buried cards: inline unbury link
    n = col.new_note(col.models.by_name("Basic"))
    n["Front"] = "card to bury"
    col.add_note(n, did)
    cards = col.find_cards("")
    col.sched.bury_cards(cards)
    html_buried = render_congrats_html(col)
    assert "@post('/overview/unbury')" in html_buried
    assert "unbury them" in html_buried
