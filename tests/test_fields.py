from pathlib import Path

import pytest
from conftest import parse_datastar_events
from fastapi.testclient import TestClient

from ankiweb.adapters.inbound.http_screens.editor import editor_links_js
from ankiweb.app import create_app
from ankiweb.core.config import Settings


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(collection_path=tmp_path / "c.anki2"))) as c:
        yield c


def _basic_id(col):
    return col.models.by_name("Basic")["id"]


def _field_names(col, ntid):
    return [f["name"] for f in col.models.get(ntid)["flds"]]


def _make_field_draft_payload(ntid: int, fields: list[dict], sort_key: str | None = None) -> dict:
    rows = {}
    order = []
    for idx, field in enumerate(fields):
        key = field.get("key", f"f{idx}")
        order.append(key)
        row = {
            "name": field.get("name", ""),
            "font": field.get("font", "Arial"),
            "size": field.get("size", 20),
            "rtl": field.get("rtl", False),
            "description": field.get("description", ""),
        }
        if field.get("orig") is not None:
            row["orig"] = field["orig"]
        rows[key] = row
    resolved_sort_key = sort_key if sort_key is not None else (order[0] if order else "")
    return {
        "notetypeId": ntid,
        "fieldDraft": {
            "rows": rows,
            "order": order,
            "nextId": len(order),
            "sortKey": resolved_sort_key,
        },
    }


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
    payload = _make_field_draft_payload(
        ntid,
        [
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
    )
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
    payload = _make_field_draft_payload(
        ntid,
        [
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
    )
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
    payload = _make_field_draft_payload(
        ntid,
        [
            {
                "orig": 0,
                "name": "Front",
                "font": "Arial",
                "size": 20,
                "rtl": False,
                "description": "",
            },
        ],
    )
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
    payload = _make_field_draft_payload(
        ntid,
        [
            {
                "key": "f1",
                "orig": 1,
                "name": "Back",
                "font": "Arial",
                "size": 20,
                "rtl": False,
                "description": "",
            },
            {
                "key": "f0",
                "orig": 0,
                "name": "Front",
                "font": "Arial",
                "size": 20,
                "rtl": False,
                "description": "",
            },
        ],
        sort_key="f1",
    )
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
    payload = _make_field_draft_payload(
        ntid,
        [
            {
                "key": "f0",
                "orig": 0,
                "name": "Front",
                "font": "Arial",
                "size": 20,
                "rtl": False,
                "description": "",
            },
            {
                "key": "f1",
                "orig": 1,
                "name": "Back",
                "font": "Arial",
                "size": 20,
                "rtl": False,
                "description": "",
            },
        ],
        sort_key="f1",
    )
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
    payload = _make_field_draft_payload(
        ntid,
        [
            {
                "key": "f0",
                "orig": 0,
                "name": "Front",
                "font": "Courier",
                "size": 28,
                "rtl": True,
                "description": "d1",
            },
            {
                "key": "f1",
                "orig": 1,
                "name": "Back",
                "font": "Arial",
                "size": 20,
                "rtl": False,
                "description": "",
            },
        ],
        sort_key="f0",
    )
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
    payload = _make_field_draft_payload(ntid, [])
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



def test_save_reordered_edited_added_row_with_sort_selection(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    payload = _make_field_draft_payload(
        ntid,
        [
            {
                "key": "f2",
                "orig": None,
                "name": "CustomSort",
                "font": "Courier",
                "size": 24,
                "rtl": True,
                "description": "extra desc",
            },
            {
                "key": "f0",
                "orig": 0,
                "name": "FrontRenamed",
                "font": "Helvetica",
                "size": 18,
                "rtl": False,
                "description": "front desc",
            },
        ],
        sort_key="f2",
    )
    r = client.post(
        "/fields/savefields", json=payload, headers={"Datastar-Request": "true"}
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location = '/deckbrowser'" in data for _, data in events)

    m = client.portal.call(client.app.state.service.run, lambda col: col.models.get(ntid))
    names = [f["name"] for f in m["flds"]]
    assert names == ["CustomSort", "FrontRenamed"]
    assert m["sortf"] == 0
    assert m["flds"][0]["font"] == "Courier"
    assert m["flds"][0]["size"] == 24
    assert m["flds"][0]["rtl"] is True
    assert m["flds"][0]["description"] == "extra desc"
    assert m["flds"][1]["font"] == "Helvetica"
    assert m["flds"][1]["size"] == 18
    assert m["flds"][1]["description"] == "front desc"


def test_cancel_does_not_persist_uncommitted_changes(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    before_names = client.portal.call(
        client.app.state.service.run, lambda col: _field_names(col, ntid)
    )
    before_sortf = client.portal.call(
        client.app.state.service.run, lambda col: col.models.get(ntid)["sortf"]
    )

    # Navigating away without posting savefields leaves fields unchanged
    after_names = client.portal.call(
        client.app.state.service.run, lambda col: _field_names(col, ntid)
    )
    after_sortf = client.portal.call(
        client.app.state.service.run, lambda col: col.models.get(ntid)["sortf"]
    )
    assert after_names == before_names
    assert after_sortf == before_sortf
