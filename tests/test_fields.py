import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from ankiweb.config import Settings
from ankiweb.app import create_app
from ankiweb.adapters.inbound.http_screens.editor import editor_links_js
from conftest import parse_datastar_events


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(collection_path=tmp_path / "c.anki2"))) as c:
        yield c


def _basic_id(col):
    return col.models.by_name("Basic")["id"]


def _field_names(col, ntid):
    return [f["name"] for f in col.models.get(ntid)["flds"]]


# (a) route renders Front + Back + "Add Field" + "Save"
def test_fields_route_renders(client):
    ntid = client.portal.call(
        client.app.state.service.run, lambda col: col.models.by_name("Basic")["id"]
    )
    r = client.get(f"/fields/{ntid}")
    assert r.status_code == 200
    assert "Front" in r.text
    assert "Back" in r.text
    assert "Add Field" in r.text
    assert "Save" in r.text


# (b) rename Front -> Q persists
def test_rename_field_persists(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    payload = {
        "notetypeId": ntid,
        "sortf": 0,
        "fields": [
            {
                "orig": 0,
                "name": "Q",
                "font": "Arial",
                "size": 20,
                "rtl": False,
                "description": "",
            },
            {
                "orig": 1,
                "name": "Back",
                "font": "Arial",
                "size": 20,
                "rtl": False,
                "description": "",
            },
        ],
    }
    r = client.post(
        "/fields/savefields", json=payload, headers={"Datastar-Request": "true"}
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location = '/deckbrowser'" in data for _, data in events)
    names = client.portal.call(
        client.app.state.service.run, lambda col: _field_names(col, ntid)
    )
    assert names == ["Q", "Back"]


# (c) add a field persists
def test_add_field_persists(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    payload = {
        "notetypeId": ntid,
        "sortf": 0,
        "fields": [
            {
                "orig": 0,
                "name": "Front",
                "font": "Arial",
                "size": 20,
                "rtl": False,
                "description": "",
            },
            {
                "orig": 1,
                "name": "Back",
                "font": "Arial",
                "size": 20,
                "rtl": False,
                "description": "",
            },
            {
                "orig": None,
                "name": "Extra",
                "font": "Arial",
                "size": 20,
                "rtl": False,
                "description": "",
            },
        ],
    }
    r = client.post(
        "/fields/savefields", json=payload, headers={"Datastar-Request": "true"}
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location = '/deckbrowser'" in data for _, data in events)
    names = client.portal.call(
        client.app.state.service.run, lambda col: _field_names(col, ntid)
    )
    assert names == ["Front", "Back", "Extra"]


# (d) delete a field persists (count drops)
def test_delete_field_persists(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    before = client.portal.call(
        client.app.state.service.run, lambda col: len(col.models.get(ntid)["flds"])
    )
    payload = {
        "notetypeId": ntid,
        "sortf": 0,
        "fields": [
            {
                "orig": 0,
                "name": "Front",
                "font": "Arial",
                "size": 20,
                "rtl": False,
                "description": "",
            },
        ],
    }
    r = client.post(
        "/fields/savefields", json=payload, headers={"Datastar-Request": "true"}
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location = '/deckbrowser'" in data for _, data in events)
    after = client.portal.call(
        client.app.state.service.run, lambda col: len(col.models.get(ntid)["flds"])
    )
    assert after == before - 1


# (e) reposition swap persists new order
def test_reposition_persists(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    payload = {
        "notetypeId": ntid,
        "sortf": 0,
        "fields": [
            {
                "orig": 1,
                "name": "Back",
                "font": "Arial",
                "size": 20,
                "rtl": False,
                "description": "",
            },
            {
                "orig": 0,
                "name": "Front",
                "font": "Arial",
                "size": 20,
                "rtl": False,
                "description": "",
            },
        ],
    }
    r = client.post(
        "/fields/savefields", json=payload, headers={"Datastar-Request": "true"}
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location = '/deckbrowser'" in data for _, data in events)
    names = client.portal.call(
        client.app.state.service.run, lambda col: _field_names(col, ntid)
    )
    assert names == ["Back", "Front"]


# (f) sortf change persists
def test_sortf_persists(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    payload = {
        "notetypeId": ntid,
        "sortf": 1,
        "fields": [
            {
                "orig": 0,
                "name": "Front",
                "font": "Arial",
                "size": 20,
                "rtl": False,
                "description": "",
            },
            {
                "orig": 1,
                "name": "Back",
                "font": "Arial",
                "size": 20,
                "rtl": False,
                "description": "",
            },
        ],
    }
    r = client.post(
        "/fields/savefields", json=payload, headers={"Datastar-Request": "true"}
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location = '/deckbrowser'" in data for _, data in events)
    sortf = client.portal.call(
        client.app.state.service.run, lambda col: col.models.get(ntid)["sortf"]
    )
    assert sortf == 1


# (g) font/size/rtl/description persist
def test_field_attrs_persist(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    payload = {
        "notetypeId": ntid,
        "sortf": 0,
        "fields": [
            {
                "orig": 0,
                "name": "Front",
                "font": "Courier",
                "size": 28,
                "rtl": True,
                "description": "d1",
            },
            {
                "orig": 1,
                "name": "Back",
                "font": "Arial",
                "size": 20,
                "rtl": False,
                "description": "",
            },
        ],
    }
    r = client.post(
        "/fields/savefields", json=payload, headers={"Datastar-Request": "true"}
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location = '/deckbrowser'" in data for _, data in events)
    f0 = client.portal.call(
        client.app.state.service.run, lambda col: col.models.get(ntid)["flds"][0]
    )
    assert f0["font"] == "Courier"
    assert f0["size"] == 28
    assert f0["rtl"] is True
    assert f0["description"] == "d1"


# (h) deleting ALL fields -> err fragment returned + NO navigation
def test_delete_all_fields_errors(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    before = client.portal.call(
        client.app.state.service.run, lambda col: _field_names(col, ntid)
    )
    payload = {
        "notetypeId": ntid,
        "sortf": 0,
        "fields": [],
    }
    r = client.post(
        "/fields/savefields", json=payload, headers={"Datastar-Request": "true"}
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("needs at least one field" in data for _, data in events)
    assert not any("window.location = '/deckbrowser'" in data for _, data in events)
    after = client.portal.call(
        client.app.state.service.run, lambda col: _field_names(col, ntid)
    )
    assert after == before


# (i) editor.py editor_links_js() string contains 'fields' branch and /fields/
def test_editor_links_js_has_fields_branch():
    js = editor_links_js()
    assert "'fields'" in js
    assert "/fields/" in js


def test_cancel_navigates(client):
    r = client.post("/fields/cancel")
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location = '/deckbrowser'" in data for _, data in events)
