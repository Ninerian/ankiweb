from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ankiweb.adapters.inbound.http_shared.preview import render_preview_html
from ankiweb.app import create_app
from ankiweb.core.config import Settings


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(collection_path=tmp_path / "c.anki2"))) as c:
        yield c


def _add(client, front="FRONTQ", back="BACKA"):
    def fn(col):
        n = col.new_note(col.models.by_name("Basic"))
        n["Front"] = front
        n["Back"] = back
        col.add_note(n, col.decks.id("Default"))
        return n.id

    return client.portal.call(client.app.state.service.run, fn)


# ---- F4: Preview ----


def test_preview_renders_question_and_answer(client):
    nid = _add(client)
    r = client.get(f"/preview/{nid}")
    assert r.status_code == 200
    assert "FRONTQ" in r.text and "BACKA" in r.text
    assert "Front" in r.text and "Back" in r.text


def test_preview_includes_card_css(temp_collection):
    # render_output().question_and_style embeds the card CSS (<style> block)
    n = temp_collection.new_note(temp_collection.models.by_name("Basic"))
    n["Front"] = "x"
    n["Back"] = "y"
    temp_collection.add_note(n, temp_collection.decks.id("Default"))
    html = render_preview_html(temp_collection, n.id)
    assert "<style" in html  # card styling present


def test_preview_strips_av_refs(temp_collection):
    n = temp_collection.new_note(temp_collection.models.by_name("Basic"))
    n["Front"] = "hi [sound:a.mp3]"
    n["Back"] = "b"
    temp_collection.add_note(n, temp_collection.decks.id("Default"))
    html = render_preview_html(temp_collection, n.id)
    assert "anki:play" not in html  # the [anki:play:..] ref was stripped


# ---- Editor links and navigation (attach, preview, fields, cards) ----


def test_editor_links_and_navigation(client):
    nid = _add(client)
    r = client.get(f"/edit?nid={nid}")
    assert r.status_code == 200
    html = r.text
    # Edit screen has links to Fields, Cards, and Preview
    assert "/fields/" in html and 'id="editor-fields-btn"' in html
    assert "/card-layout/" in html and 'id="editor-cards-btn"' in html
    assert f"/preview/{nid}" in html and 'id="editor-preview-btn"' in html
    assert 'data-editor-command="attach"' in html


def test_add_links_and_navigation(client):
    r = client.get("/add")
    assert r.status_code == 200
    html = r.text
    # Add screen has links to Fields and Cards and media attach button
    assert "/fields/" in html and 'id="editor-fields-btn"' in html
    assert "/card-layout/" in html and 'id="editor-cards-btn"' in html
    assert 'data-editor-command="attach"' in html
