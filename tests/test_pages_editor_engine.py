from __future__ import annotations
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from ankiweb.core.config import Settings
from ankiweb.app import create_app

@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(collection_path=tmp_path / "editor_engine_test.anki2"))) as c:
        yield c

def test_editor_bundle_built_and_served(client):
    response = client.get("/shell/static/bundles/editor-engine.js")
    assert response.status_code == 200
    assert "window.AnkiwebEditor" in response.text
    assert "attachRichText" in response.text
    assert "insertCloze" in response.text
    assert "bold" in response.text

def test_editor_toolbar_renders_in_page(client):
    # Verify that the toolbar partial is included in editor page
    m = client.portal.call(client.app.state.service.run, lambda col: col.models.by_name("Basic"))
    n = client.portal.call(client.app.state.service.run, lambda col: col.new_note(m))
    n["Front"] = "TestFront"
    n["Back"] = "TestBack"
    nid = client.portal.call(client.app.state.service.run, lambda col: (col.add_note(n, col.decks.id("Default")), n.id)[1])

    r = client.get(f"/edit?nid={nid}")
    assert r.status_code == 200
    assert "editor-toolbar" in r.text
    assert 'data-editor-command="bold"' in r.text
    assert 'data-editor-command="cloze"' in r.text
    assert 'data-editor-command="removeFormat"' in r.text
