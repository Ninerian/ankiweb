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
from ankiweb.core.app_client.deck_languages import (
    LanguagePair,
    apply_marker,
    read_marker,
    strip_marker,
)
from ankiweb.core.app_client.decks import update_deck_settings
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
    ("existing", "incoming", "expected_text", "expected_pair"),
    [
        (
            "<!--ankiweb:lang=en>fr-->Original",
            "Edited **text** and more",
            "Edited **text** and more",
            LanguagePair("en", "fr"),
        ),
        (
            "<!--ankiweb:lang=en>fr-->Original",
            (
                "<!--ankiweb:lang=de>es-->Before<!--ankiweb:lang=en>fr-->"
                "After<!--ankiweb:lang=xx>yy-->!"
            ),
            "BeforeAfter!",
            LanguagePair("en", "fr"),
        ),
        (
            "A<!--ankiweb:lang=en>fr-->B<!--ankiweb:lang=de>es-->C",
            "Edited",
            "Edited",
            LanguagePair("en", "fr"),
        ),
        (
            "Unmarked",
            "Before<!--ankiweb:lang=de>es-->After",
            "BeforeAfter",
            None,
        ),
        ("Unmarked", "Unchanged **content**", "Unchanged **content**", None),
    ],
)
def test_setdesc_preserves_only_existing_marker(
    client, existing, incoming, expected_text, expected_pair
):
    did = _run(client, lambda col: _set_description(col, existing, False))
    response = client.post(
        "/overview/setdesc",
        json={"desc": incoming, "md": True},
        headers={"Datastar-Request": "true"},
    )
    assert response.status_code == 200
    assert "window.location.reload()" in response.text
    deck = _run(client, lambda col: col.decks.get(did))
    assert strip_marker(deck["desc"]) == expected_text
    assert read_marker(deck["desc"]) == expected_pair
    assert deck["desc"].count("<!--ankiweb:lang=") == (
        1 if expected_pair is not None else 0
    )
    assert deck["md"] is True


@pytest.mark.parametrize(
    ("existing", "markdown"),
    [
        ("<!--ankiweb:lang=xx>yy-->\nOriginal", True),
        ("A<!--ankiweb:lang=en>en-->B", True),
        ("A<!--ankiweb:lang=xx>yy-->B<!--ankiweb:lang=de>en-->C", True),
        ("<!--ankiweb:lang=en>fr-->\nOriginal", False),
        (apply_marker("\nOriginal", LanguagePair("en", "fr")), True),
    ],
)
def test_setdesc_unchanged_text_preserves_all_existing_bytes(
    client, existing, markdown
):
    did = _run(client, lambda col: _set_description(col, existing, markdown))
    response = client.post(
        "/overview/setdesc",
        json={"desc": strip_marker(existing), "md": markdown},
        headers={"Datastar-Request": "true"},
    )
    assert response.status_code == 200
    assert _run(client, lambda col: col.decks.get(did))["desc"] == existing


def test_setdesc_unchanged_markdown_migrates_legacy_marker(client):
    text = "\nOriginal **bold**\n"
    existing = "<!--ankiweb:lang=en>fr-->" + text
    did = _run(client, lambda col: _set_description(col, existing, True))
    response = client.post(
        "/overview/setdesc",
        json={"desc": text, "md": True},
        headers={"Datastar-Request": "true"},
    )
    assert response.status_code == 200
    saved = _run(client, lambda col: col.decks.get(did))["desc"]
    assert saved != existing
    assert read_marker(saved) == LanguagePair("en", "fr")
    assert strip_marker(saved) == text
    rendered = _run(client, lambda col: col.render_markdown(saved))
    assert "<strong>bold</strong>" in rendered


@pytest.mark.parametrize("change_text", [False, True])
def test_setdesc_preserves_later_unsupported_marker_with_valid_first(
    client, change_text
):
    existing = (
        "<!--ankiweb:lang=en>fr-->Original"
        "<!--ankiweb:lang=xx>yy-->"
        "<!--ankiweb:lang=de>es-->"
        "<!--ankiweb:lang=en>en-->"
    )
    did = _run(client, lambda col: _set_description(col, existing, True))
    text = "Edited **text**" if change_text else "Original"
    response = client.post(
        "/overview/setdesc",
        json={"desc": text, "md": True},
        headers={"Datastar-Request": "true"},
    )
    assert response.status_code == 200
    saved = _run(client, lambda col: col.decks.get(did))["desc"]
    assert strip_marker(saved) == text
    assert read_marker(saved) == LanguagePair("en", "fr")
    pattern = r"<!--ankiweb:lang=[a-z]{2,3}>[a-z]{2,3}-->"
    assert re.findall(pattern, saved) == [
        "<!--ankiweb:lang=en>fr-->",
        "<!--ankiweb:lang=xx>yy-->",
        "<!--ankiweb:lang=en>en-->",
    ]


@pytest.mark.parametrize("legacy", [False, True])
def test_overview_editor_preserves_leading_description_newline(client, legacy):
    text = "\n\nFirst **line**\n"
    stored = (
        "<!--ankiweb:lang=de>en-->" + text
        if legacy
        else apply_marker(text, LanguagePair("de", "en"))
    )
    did = _run(client, lambda col: _set_description(col, stored, True))
    _run(client, _add_card)
    response = client.get("/overview")
    assert response.status_code == 200
    signals = re.search(
        r"id=\"descedit\".*?data-signals='([^']*)'", response.text, re.DOTALL
    )
    assert signals is not None
    assert json.loads(html.unescape(signals.group(1)))["desc"] == text
    assert "ankiweb:lang" not in response.text
    assert _run(client, lambda col: col.decks.get(did))["desc"] == stored


@pytest.mark.parametrize(
    "existing",
    [
        "<!--ankiweb:lang=xx>yy-->\nOriginal",
        "Original<!--ankiweb:lang=en>en-->",
        "A<!--ankiweb:lang=xx>yy-->B<!--ankiweb:lang=de>en-->C",
    ],
)
def test_setdesc_edits_visible_text_without_losing_unsupported_markers(
    client, existing
):
    did = _run(client, lambda col: _set_description(col, existing, True))
    edited = "\nEdited **text** and <!--foreign:metadata--> details"
    response = client.post(
        "/overview/setdesc",
        json={"desc": edited, "md": True},
        headers={"Datastar-Request": "true"},
    )
    assert response.status_code == 200
    saved = _run(client, lambda col: col.decks.get(did))["desc"]
    assert strip_marker(saved) == edited
    assert read_marker(saved) is None
    pattern = r"<!--ankiweb:lang=[a-z]{2,3}>[a-z]{2,3}-->"
    assert re.findall(pattern, saved) == re.findall(pattern, existing)
    rendered = _run(client, lambda col: col.render_markdown(saved))
    assert "<strong>text</strong>" in rendered
    response = client.post(
        "/overview/setdesc",
        json={"desc": edited, "md": True},
        headers={"Datastar-Request": "true"},
    )
    assert response.status_code == 200
    assert _run(client, lambda col: col.decks.get(did))["desc"] == saved


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hello **world**", "<strong>world</strong>"),
        ("# Heading\n\n- item", "<h1"),
        ("\nHello **world**", "<strong>world</strong>"),
    ],
)
def test_adding_language_pair_keeps_anki_markdown_first_line(col, text, expected):
    from ankiweb.core.app_client.decks import create_deck

    row = create_deck(col, "Study", "📚", None)
    deck = col.decks.get(row.deck_id)
    deck["desc"] = text
    deck["md"] = True
    col.decks.update_dict(deck)
    update_deck_settings(col, row.deck_id, "Study", "📚", LanguagePair("de", "en"))
    saved = col.decks.get(row.deck_id)["desc"]
    assert strip_marker(saved) == text
    assert expected in col.render_markdown(saved)


def test_setdesc_keeps_anki_markdown_first_line_after_edit(client):
    existing = "<!--ankiweb:lang=de>en-->Old text"
    did = _run(client, lambda col: _set_description(col, existing, True))
    text = "New **first line**\n\n# Heading"
    response = client.post(
        "/overview/setdesc",
        json={"desc": text, "md": True},
        headers={"Datastar-Request": "true"},
    )
    assert response.status_code == 200
    saved = _run(client, lambda col: col.decks.get(did))["desc"]
    assert strip_marker(saved) == text
    assert read_marker(saved) == LanguagePair("de", "en")
    rendered = _run(client, lambda col: col.render_markdown(saved))
    assert "<strong>first line</strong>" in rendered
    assert "<h1" in rendered and "Heading</h1>" in rendered


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
    assert strip_marker(deck["desc"]) == ""
    assert read_marker(deck["desc"]) == LanguagePair("en", "fr")
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
