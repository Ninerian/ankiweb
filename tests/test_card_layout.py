import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from ankiweb.config import Settings
from ankiweb.app import create_app
from ankiweb.screens.editor import editor_links_js
from conftest import parse_datastar_events


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(collection_path=tmp_path / "c.anki2"))) as c:
        yield c


def _basic_id(col):
    return col.models.by_name("Basic")["id"]


def _tmpls(col, ntid):
    return col.models.get(ntid)["tmpls"]


def _tmpl_names(col, ntid):
    return [t["name"] for t in _tmpls(col, ntid)]


def _add_note(col, ntid):
    """Add a Basic note so previews / card generation have something to work with."""
    m = col.models.get(ntid)
    note = col.new_note(m)
    note["Front"] = "Hello"
    note["Back"] = "World"
    col.add_note(note, col.decks.id("Default"))
    return note.id


# (a) route renders the Card 1 qfmt/afmt + css textarea + Add card type + Save
def test_card_layout_route_renders(client):
    ntid = client.portal.call(
        client.app.state.service.run,
        lambda col: col.models.by_name("Basic")["id"])
    r = client.get(f"/card-layout/{ntid}")
    assert r.status_code == 200
    assert "Card Types" in r.text
    assert "Front Template" in r.text
    assert "Back Template" in r.text
    assert "Styling" in r.text
    assert "Add Card Type" in r.text
    assert "Save" in r.text


# (b) edit qfmt/afmt persists
def test_edit_qfmt_afmt_persists(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    payload = {
        "notetypeId": ntid,
        "css": "",
        "templates": [
            {"orig": 0, "name": "Card 1", "qfmt": "{{Front}}<hr>custom", "afmt": "{{FrontSide}}<hr id=answer>{{Back}}<br>extra"},
        ],
    }
    r = client.post("/card-layout/savelayout", json=payload, headers={"Datastar-Request": "true"})
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location = '/deckbrowser'" in data for _, data in events)
    t0 = client.portal.call(client.app.state.service.run, lambda col: _tmpls(col, ntid)[0])
    assert t0["qfmt"] == "{{Front}}<hr>custom"
    assert t0["afmt"] == "{{FrontSide}}<hr id=answer>{{Back}}<br>extra"


# (c) edit css persists
def test_edit_css_persists(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    payload = {
        "notetypeId": ntid,
        "css": ".card { font-family: monospace; font-size: 24px; }",
        "templates": [
            {"orig": 0, "name": "Card 1", "qfmt": "{{Front}}", "afmt": "{{FrontSide}}\n\n<hr id=answer>\n\n{{Back}}"},
        ],
    }
    r = client.post("/card-layout/savelayout", json=payload, headers={"Datastar-Request": "true"})
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location = '/deckbrowser'" in data for _, data in events)
    m = client.portal.call(client.app.state.service.run, lambda col: col.models.get(ntid))
    assert ".card { font-family: monospace;" in m["css"]


# (d) rename a template persists
def test_rename_template_persists(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    payload = {
        "notetypeId": ntid,
        "css": "",
        "templates": [
            {"orig": 0, "name": "Recognition", "qfmt": "{{Front}}", "afmt": "{{Back}}"},
        ],
    }
    r = client.post("/card-layout/savelayout", json=payload, headers={"Datastar-Request": "true"})
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location = '/deckbrowser'" in data for _, data in events)
    names = client.portal.call(client.app.state.service.run, lambda col: _tmpl_names(col, ntid))
    assert names == ["Recognition"]


# (e) add a template persists (count up)
def test_add_template_persists(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    before = client.portal.call(client.app.state.service.run, lambda col: len(_tmpls(col, ntid)))
    payload = {
        "notetypeId": ntid,
        "css": "",
        "templates": [
            {"orig": 0, "name": "Card 1", "qfmt": "{{Front}}", "afmt": "{{Back}}"},
            {"orig": None, "name": "Card 2", "qfmt": "{{Back}}", "afmt": "{{Front}}"},
        ],
    }
    r = client.post("/card-layout/savelayout", json=payload, headers={"Datastar-Request": "true"})
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location = '/deckbrowser'" in data for _, data in events)
    after = client.portal.call(client.app.state.service.run, lambda col: len(_tmpls(col, ntid)))
    assert after == before + 1


# (f) reposition swap persists
def test_reposition_persists(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    # first add a second template so there is something to swap
    p1 = {
        "notetypeId": ntid, "css": "",
        "templates": [
            {"orig": 0, "name": "First", "qfmt": "{{Front}}", "afmt": "{{Back}}"},
            {"orig": None, "name": "Second", "qfmt": "{{Back}}", "afmt": "{{Front}}"},
        ],
    }
    client.post("/card-layout/savelayout", json=p1, headers={"Datastar-Request": "true"})
    # swap positions
    p2 = {
        "notetypeId": ntid, "css": "",
        "templates": [
            {"orig": 1, "name": "Second", "qfmt": "{{Back}}", "afmt": "{{Front}}"},
            {"orig": 0, "name": "First", "qfmt": "{{Front}}", "afmt": "{{Back}}"},
        ],
    }
    r = client.post("/card-layout/savelayout", json=p2, headers={"Datastar-Request": "true"})
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location = '/deckbrowser'" in data for _, data in events)
    names = client.portal.call(client.app.state.service.run, lambda col: _tmpl_names(col, ntid))
    assert names == ["Second", "First"]


# (g) delete a template persists (count down)
def test_delete_template_persists(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    # add a second template first
    p1 = {
        "notetypeId": ntid, "css": "",
        "templates": [
            {"orig": 0, "name": "T1", "qfmt": "{{Front}}", "afmt": "{{Back}}"},
            {"orig": None, "name": "T2", "qfmt": "{{Back}}", "afmt": "{{Front}}"},
        ],
    }
    client.post("/card-layout/savelayout", json=p1, headers={"Datastar-Request": "true"})
    before = client.portal.call(client.app.state.service.run, lambda col: len(_tmpls(col, ntid)))
    # drop T2
    p2 = {
        "notetypeId": ntid, "css": "",
        "templates": [
            {"orig": 0, "name": "T1", "qfmt": "{{Front}}", "afmt": "{{Back}}"},
        ],
    }
    r = client.post("/card-layout/savelayout", json=p2, headers={"Datastar-Request": "true"})
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location = '/deckbrowser'" in data for _, data in events)
    after = client.portal.call(client.app.state.service.run, lambda col: len(_tmpls(col, ntid)))
    assert after == before - 1


# (h) deleting all templates -> err fragment + no navigate
def test_delete_all_templates_errors(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    before = client.portal.call(client.app.state.service.run, lambda col: _tmpl_names(col, ntid))
    payload = {
        "notetypeId": ntid,
        "css": "",
        "templates": [],
    }
    r = client.post("/card-layout/savelayout", json=payload, headers={"Datastar-Request": "true"})
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("needs at least one card type" in data for _, data in events)
    assert not any("window.location = '/deckbrowser'" in data for _, data in events)
    after = client.portal.call(client.app.state.service.run, lambda col: _tmpl_names(col, ntid))
    assert after == before


# (i) previewlayout with an existing note -> redirect to /preview/<nid>
def test_previewlayout_navigates(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    nid = client.portal.call(client.app.state.service.run, lambda col: _add_note(col, ntid))
    r = client.post(f"/card-layout/previewlayout/{ntid}")
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any(f"window.location = '/preview/{nid}'" in data for _, data in events)


def test_cancel_navigates(client):
    r = client.post("/card-layout/cancel")
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location = '/deckbrowser'" in data for _, data in events)


# (j) editor_links_js() contains the cards branch + /card-layout/
def test_editor_links_js_has_cards_branch():
    js = editor_links_js()
    assert "'cards'" in js
    assert "/card-layout/" in js
