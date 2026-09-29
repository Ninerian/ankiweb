import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from ankiweb.core.config import Settings
from ankiweb.app import create_app


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(collection_path=tmp_path / "c.anki2"))) as c:
        yield c


def test_graphs_shell_injects_browsersearch_bridge(client):
    r = client.get("/graphs")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    # SPA still boots
    assert "_app/immutable/entry" in r.text
    # bridge script tag present
    assert "/shell/static/spa_bridge.js" in r.text
    bridge_r = client.get("/shell/static/spa_bridge.js")
    assert bridge_r.status_code == 200
    # bridge present + maps browserSearch -> /browse?q=
    assert "browserSearch:" in bridge_r.text
    assert "/browse?q=" in bridge_r.text

def test_browse_q_prefills_and_searches(client):
    def seed(col):
        other = col.decks.id("Other")
        n1 = col.new_note(col.models.by_name("Basic"))
        n1["Front"] = "defaultword"
        n1["Back"] = "x"
        col.add_note(n1, col.decks.id("Default"))
        n2 = col.new_note(col.models.by_name("Basic"))
        n2["Front"] = "otherword"
        n2["Back"] = "x"
        col.add_note(n2, other)

    client.portal.call(client.app.state.service.run, seed)

    r = client.get("/browse?q=deck:Other")
    assert r.status_code == 200
    # input prefilled
    assert 'value="deck:Other"' in r.text
    # SSR baked the query's actual results into the initial page, not just the default/all-cards set
    assert "otherword" in r.text
    assert "defaultword" not in r.text
    assert "1 cards" in r.text


def test_browse_q_empty_default(client):
    r = client.get("/browse")
    assert r.status_code == 200
    assert 'value=""' in r.text


def test_browse_q_html_escaped(client):
    # a query with quotes/brackets must not break the attribute or the inline JS
    r = client.get('/browse?q=front:"a<b>"')
    assert r.status_code == 200
    assert "&lt;b&gt;" in r.text  # escaped in the value attribute
