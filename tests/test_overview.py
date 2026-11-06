import html
import json
import os
import re
import tempfile
from pathlib import Path

import pytest
from anki.collection import Collection
from fastapi.testclient import TestClient

from ankiweb.adapters.inbound.http_datastar.overview import render_overview_html
from ankiweb.adapters.inbound.http_shared.congrats import render_congrats_html
from ankiweb.app import create_app
from ankiweb.core.config import Settings


@pytest.fixture
def col():
    c = Collection(os.path.join(tempfile.mkdtemp(), "c.anki2"))
    yield c
    c.close()


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(collection_path=tmp_path / "c.anki2"))) as c:
        yield c


def _set_description(col, desc, md):
    did = col.decks.id("Default")
    col.decks.set_current(did)
    deck = col.decks.get(did)
    deck["desc"] = desc
    deck["md"] = md
    col.decks.update_dict(deck)
    return did


def _add_card(col):
    did = col.decks.id("Default")
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"] = "front"
    note["Back"] = "back"
    col.add_note(note, did)


def _run(client, fn):
    return client.portal.call(client.app.state.service.run, fn)


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
    assert "Back to Decks" in html
    assert "data-on-interval__duration.60s" in html

    # 2. Deck description rendered and sanitized
    deck = col.decks.get(did)
    deck["desc"] = (
        "<p>My <b>special</b> deck description</p><script>alert('xss')</script>"
    )
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


@pytest.mark.parametrize(
    ("existing", "incoming", "expected"),
    [
        (
            "<!--ankiweb:lang=en>fr-->Original",
            "Edited **text** and more",
            "<!--ankiweb:lang=en>fr-->Edited **text** and more",
        ),
        (
            "<!--ankiweb:lang=en>fr-->Original",
            (
                "<!--ankiweb:lang=de>es-->Before<!--ankiweb:lang=en>fr-->"
                "After<!--ankiweb:lang=xx>yy-->!"
            ),
            "<!--ankiweb:lang=en>fr-->BeforeAfter!",
        ),
        (
            "Unmarked",
            "Before<!--ankiweb:lang=de>es-->After",
            "BeforeAfter",
        ),
        ("Unmarked", "Unchanged **content**", "Unchanged **content**"),
    ],
)
def test_setdesc_preserves_only_existing_marker(client, existing, incoming, expected):
    did = _run(client, lambda col: _set_description(col, existing, False))
    response = client.post(
        "/overview/setdesc",
        json={"desc": incoming, "md": True},
        headers={"Datastar-Request": "true"},
    )
    assert response.status_code == 200
    assert "window.location.reload()" in response.text
    deck = _run(client, lambda col: col.decks.get(did))
    assert deck["desc"] == expected
    assert deck["md"] is True


@pytest.mark.parametrize("invalid", [None, [], {"text": "injected"}, 1])
def test_setdesc_rejects_non_text_without_mutating_deck(client, invalid):
    original = "<!--ankiweb:lang=en>fr-->Original"
    did = _run(client, lambda col: _set_description(col, original, True))
    response = client.post(
        "/overview/setdesc",
        json={"desc": invalid, "md": False},
        headers={"Datastar-Request": "true"},
    )
    assert response.status_code == 204
    deck = _run(client, lambda col: col.decks.get(did))
    assert deck["desc"] == original
    assert deck["md"] is True


def test_setdesc_missing_description_preserves_marker_and_md_request(client):
    did = _run(
        client,
        lambda col: _set_description(col, "<!--ankiweb:lang=en>fr-->Original", True),
    )
    response = client.post(
        "/overview/setdesc",
        json={"md": False},
        headers={"Datastar-Request": "true"},
    )
    assert response.status_code == 200
    deck = _run(client, lambda col: col.decks.get(did))
    assert deck["desc"] == "<!--ankiweb:lang=en>fr-->"
    assert deck.get("md", False) is False


@pytest.mark.parametrize("marked", [False, True])
def test_overview_editor_and_markdown_render_unmarked_description(client, marked):
    text = "Before **world** and <em>more</em>"
    stored = ("<!--ankiweb:lang=en>fr-->" if marked else "") + text
    did = _run(client, lambda col: _set_description(col, stored, True))
    _run(client, _add_card)

    response = client.get("/overview")
    assert response.status_code == 200
    assert "<strong>world</strong>" in response.text
    assert "<em>more</em>" in response.text
    textarea = re.search(
        r'<textarea id="descbox"[^>]*>(.*?)</textarea>', response.text, re.DOTALL
    )
    assert textarea is not None
    assert html.unescape(textarea.group(1)) == text
    signals = re.search(
        r"id=\"descedit\".*?data-signals='([^']*)'", response.text, re.DOTALL
    )
    assert signals is not None
    assert json.loads(html.unescape(signals.group(1)))["desc"] == text
    assert "ankiweb:lang" not in response.text
    assert _run(client, lambda col: col.decks.get(did))["desc"] == stored


@pytest.mark.parametrize("markdown", [False, True])
def test_marked_overview_description_is_safe_and_preserves_content(col, markdown):
    content = (
        "Before **bold** <b>HTML</b> "
        '<a href="javascript:alert(1)" onclick="alert(1)">link</a>'
        "<script>alert(2)</script> After"
    )
    stored = "<!--ankiweb:lang=en>fr-->" + content
    did = _set_description(col, stored, markdown)
    _add_card(col)
    rendered = render_overview_html(col)
    description = rendered.split(
        '<div class="descfont description text-left mb-4">', 1
    )[1].split("</div>", 1)[0]
    assert "Before" in description and "After" in description
    assert "<b>HTML</b>" in description
    if markdown:
        assert "<strong>bold</strong>" in description
    else:
        assert "**bold**" in description
    assert "<script" not in description
    assert "onclick" not in description
    assert "javascript:" not in description
    assert col.decks.get(did)["desc"] == stored


@pytest.mark.parametrize("markdown", [False, True])
def test_marked_congrats_uses_raw_description_safely(col, markdown):
    content = (
        "Before **bold** <b>HTML</b> "
        '<a href="javascript:alert(1)" onclick="alert(1)">link</a>'
        "<script>alert(2)</script> After"
    )
    stored = "<!--ankiweb:lang=en>fr-->" + content
    did = _set_description(col, stored, markdown)
    rendered = render_congrats_html(col)
    assert 'class="description"' in rendered
    assert "Before" in rendered and "After" in rendered
    assert "<b>HTML</b>" in rendered
    if markdown:
        assert "<strong>bold</strong>" in rendered
    else:
        assert "**bold**" in rendered
    assert "<script" not in rendered
    assert "onclick" not in rendered
    assert "javascript:" not in rendered
    assert "ankiweb:lang" not in rendered
    assert col.decks.get(did)["desc"] == stored


@pytest.mark.parametrize("markdown", [False, True])
def test_unmarked_congrats_retains_scheduler_description(col, markdown):
    from ankiweb.core.html_sanitize import sanitize_html

    stored = "Before **bold** and <em>more</em>"
    did = _set_description(col, stored, markdown)
    scheduler_desc = col.sched.congratulations_info().deck_description
    expected = sanitize_html(
        scheduler_desc or (col.render_markdown(stored) if markdown else stored)
    )
    rendered = render_congrats_html(col)
    assert expected in rendered
    assert "Before" in rendered and "<em>more</em>" in rendered
    assert col.decks.get(did)["desc"] == stored
