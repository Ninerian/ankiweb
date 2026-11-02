import re
from http.cookies import SimpleCookie
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.testclient import TestClient

from ankiweb.adapters.inbound.http_app.layout import render_app_page
from ankiweb.adapters.inbound.http_app.session import (
    SessionStore,
    get_session,
    set_session_cookie,
)
from ankiweb.app import create_app
from ankiweb.core.auth import COOKIE, auth_token
from ankiweb.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]
CSS = ROOT / "ankiweb/shell/static/app-client.css"


def _built_css() -> str:
    assert CSS.exists(), "run: npm run build"
    return CSS.read_text(encoding="utf-8")


def test_ping_precedes_media_catch_all(client: TestClient) -> None:
    response = client.get("/app/ping")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert '<h1 class="card-title">AnkiWeb</h1>' in response.text
    assert '<span class="badge">Ready</span>' in response.text
    assert "<button" not in response.text
    assert "/shell/static/app-client.css" in response.text
    assert "set-cookie" not in response.headers


def test_ping_follows_password_gate(tmp_path: Path) -> None:
    password = f"test-{tmp_path.name}"
    app = create_app(
        Settings(collection_path=tmp_path / "auth.anki2", password=password)
    )
    with TestClient(app) as test_client:
        response = test_client.get("/app/ping", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/app/login"
        test_client.cookies.set(COOKIE, auth_token(password))
        assert test_client.get("/app/ping").status_code == 200


def test_layout_is_independent() -> None:
    page = render_app_page(
        "Title", "<main>Content</main>", active="", static_dir=CSS.parent
    )
    for forbidden in (
        "/_anki/",
        "reviewer.js",
        "editor.js",
        "/ws",
        "bootstrap.js",
        "/shell/static/app.css",
        "theme.css",
        "components.css",
        "data-theme",
    ):
        assert forbidden not in page
    assert "/shell/static/app-client.css" in page
    assert '<script type="module" src="/shell/static/datastar.js"></script>' in page
    assert "viewport-fit=cover" in page
    assert "data-signals=\"{error: ''}\"" in page
    assert 'id="app-error"' in page
    assert 'class="toast"' in page
    assert 'class="alert alert-error"' in page
    assert 'data-show="$error"' in page
    assert 'style="display:none"' in page
    assert 'data-text="$error"' in page
    assert "<main>Content</main>" in page


def test_layout_escapes_title_and_loads_extra_scripts() -> None:
    page = render_app_page(
        '<title & "test">',
        "",
        active="",
        static_dir=CSS.parent,
        scripts=(
            "/shell/static/app/add.js",
            "/shell/static/app/nested/other.js",
            "/shell/static/datastar.js",
            "/app/a.js",
        ),
    )
    assert "&lt;title &amp; &#34;test&#34;&gt;" in page
    version = re.search(r"/shell/static/app-client\.css\?v=([0-9a-f]{12})", page)
    assert version is not None
    assert f'/shell/static/app/add.js?v={version.group(1)}"' in page
    assert (
        '<script type="module" src="/shell/static/app/nested/other.js"></script>'
        in page
    )
    assert '<script type="module" src="/shell/static/datastar.js"></script>' in page
    assert '<script type="module" src="/app/a.js"></script>' in page


def test_app_css_build_has_system_themes() -> None:
    css = _built_css()
    assert "aw-light" in css
    assert "aw-dark" in css
    assert "prefers-color-scheme" in css
    assert "data-theme" not in render_app_page("", "", active="", static_dir=CSS.parent)


def test_app_session_cookie_only_set_when_needed() -> None:
    app = FastAPI()

    @app.get("/session")
    def session_route(request: Request, response: Response) -> dict[str, int]:
        session, cookie = get_session(request)
        set_session_cookie(response, cookie)
        return {"session": id(session)}

    with TestClient(app) as client:
        first = client.get("/session")
        cookie = SimpleCookie()
        cookie.load(first.headers["set-cookie"])
        sid = cookie["app_sid"]
        assert sid.value
        assert sid["httponly"]
        assert sid["samesite"].lower() == "lax"
        assert sid["path"] == "/"
        second = client.get("/session")
        assert "set-cookie" not in second.headers
        assert client.cookies.get("app_sid") == sid.value
        assert second.json() == first.json()

        client.cookies.clear()
        client.cookies.set("app_sid", "unknown")
        third = client.get("/session")
        assert third.cookies["app_sid"] != "unknown"
        assert "app_sid=" in third.headers["set-cookie"]
        assert third.json() != first.json()


@pytest.mark.parametrize("kind", ["html", "redirect"])
def test_app_session_cookie_survives_explicit_response(kind: str) -> None:
    app = FastAPI()

    @app.get("/session")
    def session_route(request: Request) -> Response:
        session, cookie = get_session(request)
        if kind == "html":
            result = HTMLResponse("session")
        else:
            result = RedirectResponse("/next")
        result.headers["x-session-id"] = str(id(session))
        set_session_cookie(result, cookie)
        return result

    with TestClient(app) as client:
        first = client.get("/session", follow_redirects=False)
        assert first.status_code == (200 if kind == "html" else 307)
        sid = first.cookies["app_sid"]
        assert sid
        cookie = SimpleCookie()
        cookie.load(first.headers["set-cookie"])
        assert cookie["app_sid"]["httponly"]
        assert cookie["app_sid"]["samesite"].lower() == "lax"
        assert cookie["app_sid"]["path"] == "/"

        second = client.get("/session", follow_redirects=False)
        assert second.headers["x-session-id"] == first.headers["x-session-id"]
        assert client.cookies["app_sid"] == sid
        assert "set-cookie" not in second.headers


def test_session_store_evicts_least_recently_used() -> None:
    store = SessionStore()
    entries = [store.get_or_create(None) for _ in range(8)]
    first_id, first_session, _ = entries[0]
    second_id, second_session, _ = entries[1]
    assert store.get_or_create(first_id) == (first_id, first_session, False)
    new_id, _, created = store.get_or_create(None)
    assert created
    assert new_id not in {entry[0] for entry in entries}
    assert store.get_or_create(first_id) == (first_id, first_session, False)
    replacement_id, replacement, created = store.get_or_create(second_id)
    assert created
    assert replacement_id != second_id
    assert replacement is not second_session


def test_live_app_uses_a_working_ephemeral_port(live_app: str) -> None:
    response = httpx.get(f"{live_app}/app/ping", timeout=10)
    assert response.status_code == 200
