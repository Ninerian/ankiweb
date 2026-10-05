from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from ankiweb.app import create_app
from ankiweb.core.config import Settings


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(collection_path=tmp_path / "c.anki2"))) as c:
        assert c.portal is not None
        app = cast(Any, c.app)
        c.portal.call(app.state.service.run, _seed)
        yield c


def _seed(col):
    n = col.new_note(col.models.by_name("Basic"))
    n["Front"] = "CapitalFrance"
    n["Back"] = "Paris"
    n.tags = ["geo"]
    col.add_note(n, col.decks.id("Default"))


def _nid(client):
    assert client.portal is not None
    return client.portal.call(
        client.app.state.service.run, lambda col: next(iter(col.find_notes("")))
    )

def _drain_call(ws, fn, tries=6):
    for _ in range(tries):
        m = ws.receive_json()
        if m["type"] == "call" and m["fn"] == fn:
            return m["args"]
    raise AssertionError(f"no {fn} frame")


def test_edit_route_renders(client):
    nid = _nid(client)
    r = client.get(f"/edit?nid={nid}")
    assert r.status_code == 200
    assert "route-editor" in r.text
    assert f"window.__ankiwebEditNid = {nid}" in r.text


def test_editor_load_pushes_note(client):
    nid = _nid(client)
    with client.websocket_connect("/ws?context=editor") as ws:
        ws.send_json({"type": "cmd", "id": None, "ctx": "editor", "arg": f"load:{nid}"})
        data = _drain_call(ws, "ankiwebLoadNote")[0]
        assert data["nid"] == nid
        assert data["notetypeId"] is not None
        assert data["initial"] is True

def test_editor_blur_saves_field(client):
    nid = _nid(client)
    with client.websocket_connect("/ws?context=editor") as ws:
        ws.send_json({"type": "cmd", "id": None, "ctx": "editor", "arg": f"load:{nid}"})
        _drain_call(ws, "ankiwebLoadNote")
        ws.send_json(
            {"type": "cmd", "id": None, "ctx": "editor", "arg": f"blur:1:{nid}:Lyon"}
        )
        ws.send_json({"type": "cmd", "id": None, "ctx": "editor", "arg": f"load:{nid}"})
        data = _drain_call(ws, "ankiwebLoadNote")[0]
        assert data["nid"] == nid
    assert client.portal is not None
    assert (
        client.portal.call(
            client.app.state.service.run, lambda col: col.get_note(nid).fields[1]
        )
        == "Lyon"
    )


def test_editor_key_saves_field(client):
    nid = _nid(client)
    with client.websocket_connect("/ws?context=editor") as ws:
        ws.send_json({"type": "cmd", "id": None, "ctx": "editor", "arg": f"load:{nid}"})
        _drain_call(ws, "ankiwebLoadNote")
        ws.send_json(
            {"type": "cmd", "id": None, "ctx": "editor", "arg": f"key:0:{nid}:Berlin"}
        )
        ws.send_json({"type": "cmd", "id": None, "ctx": "editor", "arg": f"load:{nid}"})
        data = _drain_call(ws, "ankiwebLoadNote")[0]
        assert data["nid"] == nid


def test_editor_blur_munges_bare_br(client):
    nid = _nid(client)
    with client.websocket_connect("/ws?context=editor") as ws:
        ws.send_json({"type": "cmd", "id": None, "ctx": "editor", "arg": f"load:{nid}"})
        _drain_call(ws, "ankiwebLoadNote")
        ws.send_json(
            {"type": "cmd", "id": None, "ctx": "editor", "arg": f"blur:1:{nid}:<br>"}
        )
        ws.send_json({"type": "cmd", "id": None, "ctx": "editor", "arg": f"load:{nid}"})
        data = _drain_call(ws, "ankiwebLoadNote")[0]
        assert data["nid"] == nid


def test_editor_savetags(client):
    nid = _nid(client)
    with client.websocket_connect("/ws?context=editor") as ws:
        ws.send_json({"type": "cmd", "id": None, "ctx": "editor", "arg": f"load:{nid}"})
        _drain_call(ws, "ankiwebLoadNote")
        ws.send_json(
            {"type": "cmd", "id": None, "ctx": "editor", "arg": 'saveTags:["x","y"]'}
        )
        ws.send_json({"type": "cmd", "id": None, "ctx": "editor", "arg": f"load:{nid}"})
        data = _drain_call(ws, "ankiwebLoadNote")[0]
        assert data["nid"] == nid


def test_upload_media_stores_and_returns_name(client):
    r = client.post(
        "/upload_media", files={"file": ("x.png", b"\x89PNG-bytes", "image/png")}
    )
    assert r.status_code == 200
    fname = r.json()["filename"]
    assert fname.endswith(".png")
    assert client.portal is not None
    assert client.portal.call(
        client.app.state.service.run, lambda col: col.media.have(fname)
    )


def test_upload_media_derives_extension_from_mime(client):
    r = client.post("/upload_media", files={"file": ("noext", b"data", "image/jpeg")})
    assert r.json()["filename"].endswith(".jpg")


def test_editor_body_has_paste_handler(client):
    from ankiweb.adapters.inbound.http_screens.editor import editor_page_body

    body = editor_page_body(1)
    assert ("addEventListener('paste'" in body) or ('addEventListener("paste"' in body)
    assert (
        "stopImmediatePropagation" in body
        and "pasteHTML" in body
        and "/upload_media" in body
    )
