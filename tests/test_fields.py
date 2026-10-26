import json
from html.parser import HTMLParser
from pathlib import Path

import pytest
from conftest import parse_datastar_events
from fastapi.testclient import TestClient

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

class _FieldsNavigationParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.return_url: str | None = None
        self.cancel_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form" and attributes.get("id") == "ff":
            signals = attributes.get("data-signals")
            assert signals is not None
            self.return_url = json.loads(signals)["returnUrl"]
        elif tag == "a" and attributes.get("id") == "fields-cancel-btn":
            self.cancel_href = attributes.get("href")


def _field_navigation(content: str) -> tuple[str, str]:
    parser = _FieldsNavigationParser()
    parser.feed(content)
    assert parser.return_url is not None
    assert parser.cancel_href is not None
    return parser.return_url, parser.cancel_href


def _assert_redirected_to(response, destination: str) -> None:
    events = parse_datastar_events(response.text)
    assert any(destination in data for _, data in events)


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
    assert _field_navigation(r.text) == ("/notetypes", "/notetypes")


def test_explicit_return_to_preserves_query_and_takes_precedence(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    destination = "/browse?q=dog&sort=desc#row-2"
    response = client.get(
        f"/fields/{ntid}",
        params={"return_to": destination},
        headers={"referer": "http://testserver/edit?nid=123"},
    )

    assert response.status_code == 200
    assert _field_navigation(response.text) == (destination, destination)


def test_same_origin_referer_supplies_return_context(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    destination = "/browse?q=dog&sort=desc"
    response = client.get(
        f"/fields/{ntid}",
        headers={"referer": f"http://testserver{destination}"},
    )

    assert response.status_code == 200
    assert _field_navigation(response.text) == (destination, destination)


def test_cross_origin_referer_falls_back_to_notetypes(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    response = client.get(
        f"/fields/{ntid}",
        headers={"referer": "https://outside.example/browse?q=dog"},
    )

    assert response.status_code == 200
    assert _field_navigation(response.text) == ("/notetypes", "/notetypes")


@pytest.mark.parametrize(
    "destination",
    [
        "https://outside.example/browse",
        "//outside.example/browse",
        r"/\outside.example/browse",
        "/browse?q=dog\r\nLocation: https://outside.example",
    ],
)
def test_unsafe_return_to_falls_back_to_notetypes(client, destination):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    response = client.get(
        f"/fields/{ntid}", params={"return_to": destination}
    )

    assert response.status_code == 200
    assert _field_navigation(response.text) == ("/notetypes", "/notetypes")

@pytest.mark.parametrize(
    "destination",
    [
        "https://outside.example/browse",
        "//outside.example/browse",
        r"/\outside.example/browse",
        "/browse?q=dog\r\nLocation: https://outside.example",
    ],
)
def test_unsafe_return_url_falls_back_while_save_persists(client, destination):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    payload = _make_field_draft_payload(
        ntid,
        [
            {"orig": 0, "name": "SavedWithUnsafeReturn"},
            {"orig": 1, "name": "Back"},
        ],
    )
    payload["returnUrl"] = destination
    response = client.post(
        "/fields/savefields", json=payload, headers={"Datastar-Request": "true"}
    )

    assert response.status_code == 200
    _assert_redirected_to(response, "/notetypes")
    names = client.portal.call(
        client.app.state.service.run, lambda col: _field_names(col, ntid)
    )
    assert names == ["SavedWithUnsafeReturn", "Back"]


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
    _assert_redirected_to(r, "/notetypes")
    names = client.portal.call(
        client.app.state.service.run, lambda col: _field_names(col, ntid)
    )
    assert names == ["Q", "Back"]

def test_save_uses_return_url_and_persists_changes(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    payload = _make_field_draft_payload(
        ntid,
        [
            {"orig": 0, "name": "ReturnContextFront"},
            {"orig": 1, "name": "Back"},
        ],
    )
    destination = "/browse?q=updated&sort=desc#fields"
    payload["returnUrl"] = destination

    response = client.post(
        "/fields/savefields", json=payload, headers={"Datastar-Request": "true"}
    )

    assert response.status_code == 200
    _assert_redirected_to(response, destination)
    names = client.portal.call(
        client.app.state.service.run, lambda col: _field_names(col, ntid)
    )
    assert names == ["ReturnContextFront", "Back"]

def test_return_context_normalizes_unsafe_url_characters(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    destination = "/browse?q=O'Brien&html=</script>&escaped=%2F&broken=%G1"
    normalized_destination = (
        "/browse?q=O%27Brien&html=%3C/script%3E&escaped=%2F&broken=%25G1"
    )

    fields_page = client.get(
        f"/fields/{ntid}", params={"return_to": destination}
    )
    assert fields_page.status_code == 200
    assert _field_navigation(fields_page.text) == (
        normalized_destination,
        normalized_destination,
    )

    payload = _make_field_draft_payload(
        ntid,
        [
            {"orig": 0, "name": "EscapedReturnFront"},
            {"orig": 1, "name": "Back"},
        ],
    )
    payload["returnUrl"] = destination
    response = client.post(
        "/fields/savefields", json=payload, headers={"Datastar-Request": "true"}
    )
    assert response.status_code == 200
    events = parse_datastar_events(response.text)
    assert any(normalized_destination in data for _, data in events)
    names = client.portal.call(
        client.app.state.service.run, lambda col: _field_names(col, ntid)
    )
    assert names == ["EscapedReturnFront", "Back"]

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
    _assert_redirected_to(r, "/notetypes")
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
    _assert_redirected_to(r, "/notetypes")
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
    _assert_redirected_to(r, "/notetypes")
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
    _assert_redirected_to(r, "/notetypes")
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
    _assert_redirected_to(r, "/notetypes")
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
    assert not any("window.location" in data for _, data in events)
    after = client.portal.call(
        client.app.state.service.run, lambda col: _field_names(col, ntid)
    )
    assert after == before


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
    _assert_redirected_to(r, "/notetypes")

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


def test_cancel_returns_to_context_without_persisting_changes(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    before_names = client.portal.call(
        client.app.state.service.run, lambda col: _field_names(col, ntid)
    )
    before_sortf = client.portal.call(
        client.app.state.service.run, lambda col: col.models.get(ntid)["sortf"]
    )

    fields_page = client.get(f"/fields/{ntid}", params={"return_to": "/notetypes"})
    assert fields_page.status_code == 200
    _return_url, cancel_href = _field_navigation(fields_page.text)
    assert cancel_href == "/notetypes"
    assert client.get(cancel_href).status_code == 200

    after_names = client.portal.call(
        client.app.state.service.run, lambda col: _field_names(col, ntid)
    )
    after_sortf = client.portal.call(
        client.app.state.service.run, lambda col: col.models.get(ntid)["sortf"]
    )
    assert after_names == before_names
    assert after_sortf == before_sortf
