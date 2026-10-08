import anki.lang
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from ankiweb.app import create_app
from ankiweb.core.auth import COOKIE, auth_token
from ankiweb.core.config import Settings


def _client(tmp_path: Path, password: str = "") -> TestClient:
    return TestClient(
        create_app(Settings(collection_path=tmp_path / "c.anki2", password=password))
    )


def test_open_when_no_password(tmp_path: Path):
    with _client(tmp_path) as c:
        assert c.get("/deckbrowser", follow_redirects=False).status_code == 200
        assert c.get("/tools", follow_redirects=False).status_code == 200


def test_from_env_reads_password(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ANKIWEB_COLLECTION", str(tmp_path / "c.anki2"))
    monkeypatch.setenv("ANKIWEB_PASSWORD", "hunter2")
    assert Settings.from_env().password == "hunter2"


def test_gate_redirects_when_password_set(tmp_path: Path):
    with _client(tmp_path, "secret") as c:
        r = c.get("/deckbrowser", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"
        # /healthz and /login stay reachable
        assert c.get("/healthz").status_code == 200
        assert c.get("/login", follow_redirects=False).status_code == 200
        # an asset/RPC path is gated too
        assert c.get("/_anki/js/reviewer.js", follow_redirects=False).status_code == 303


def test_login_wrong_password(tmp_path: Path):
    with _client(tmp_path, "secret") as c:
        r = c.post("/login", data={"password": "nope"}, follow_redirects=False)
        assert r.status_code == 401
        assert "password" in r.text.lower() or "密码" in r.text


def test_login_correct_unlocks(tmp_path: Path):
    with _client(tmp_path, "secret") as c:
        r = c.post("/login", data={"password": "secret"}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/"
        assert r.cookies.get(COOKIE) == auth_token("secret")
        # the client now carries the session cookie -> protected page loads
        assert c.get("/deckbrowser", follow_redirects=False).status_code == 200


def test_login_datastar_wrong_password(tmp_path: Path):
    with _client(tmp_path, "secret") as c:
        r = c.post(
            "/login",
            json={"password": "bad"},
            headers={"datastar-request": "true"},
            follow_redirects=False,
        )
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")
        assert "Email or password was incorrect" in r.text


def test_login_localized_to_active_language(tmp_path: Path):
    with _client(tmp_path, "secret") as c:
        anki.lang.set_lang("de")
        page = c.get("/login").text
        assert "Passwort" in page and "Anmelden" in page
        assert "Password" not in page
        # the Datastar error signal and the no-JS 401 page share the same localized text
        sse = c.post(
            "/login",
            json={"password": "bad"},
            headers={"datastar-request": "true"},
        ).text
        form = c.post("/login", data={"password": "bad"})
        assert form.status_code == 401
        assert "falsch" in sse and "falsch" in form.text


def test_login_datastar_correct_unlocks(tmp_path: Path):
    with _client(tmp_path, "secret") as c:
        r = c.post(
            "/login",
            json={"password": "secret"},
            headers={"datastar-request": "true"},
            follow_redirects=False,
        )
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")
        assert "window.location" in r.text and "'/'" in r.text
        assert r.cookies.get(COOKIE) == auth_token("secret")
        assert c.get("/deckbrowser", follow_redirects=False).status_code == 200

def test_bad_cookie_still_gated(tmp_path: Path):
    with _client(tmp_path, "secret") as c:
        c.cookies.set(COOKIE, "garbage")
        assert c.get("/deckbrowser", follow_redirects=False).status_code == 303


def test_logout_clears_session(tmp_path: Path):
    with _client(tmp_path, "secret") as c:
        c.post("/login", data={"password": "secret"})
        assert c.get("/deckbrowser", follow_redirects=False).status_code == 200
        c.get("/logout", follow_redirects=False)
        assert c.get("/deckbrowser", follow_redirects=False).status_code == 303


def test_ws_rejected_without_cookie(tmp_path: Path):
    with (
        _client(tmp_path, "secret") as c,
        pytest.raises(WebSocketDisconnect),
        c.websocket_connect("/ws?context=browser") as ws,
    ):
        ws.receive_json()

def test_ws_ok_with_cookie(tmp_path: Path):
    with _client(tmp_path, "secret") as c:
        c.cookies.set(COOKIE, auth_token("secret"))
        with c.websocket_connect("/ws?context=browser"):
            pass  # accepted, no rejection


def test_ws_open_when_no_password(tmp_path: Path):
    with _client(tmp_path) as c, c.websocket_connect("/ws?context=browser"):
        pass
