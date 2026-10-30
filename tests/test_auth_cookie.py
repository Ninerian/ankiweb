from http.cookies import SimpleCookie
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from ankiweb.app import create_app
from ankiweb.core.auth import COOKIE, auth_token
from ankiweb.core.config import Settings


def _assert_auth_cookie(response: Response, secure: bool, password: str) -> None:
    headers = [
        value
        for value in response.headers.get_list("set-cookie")
        if value.startswith(f"{COOKIE}=")
    ]
    assert len(headers) == 1
    attributes = [part.strip().lower() for part in headers[0].split(";")[1:]]
    assert attributes.count("secure") == int(secure)

    cookies = SimpleCookie()
    cookies.load(headers[0])
    cookie = cookies[COOKIE]
    assert cookie.value == auth_token(password)
    assert bool(cookie["secure"]) is secure
    assert cookie["httponly"]
    assert cookie["samesite"].lower() == "lax"
    assert cookie["path"] == "/"
    assert cookie["max-age"] == str(30 * 86400)


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_form_login_cookie_secure_matches_request_scheme(
    tmp_path: Path, scheme: str
) -> None:
    password = f"test-{tmp_path.name}"
    app = create_app(Settings(collection_path=tmp_path / "c.anki2", password=password))
    with TestClient(app, base_url=f"{scheme}://testserver") as client:
        response = client.post(
            "/login", data={"password": password}, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        _assert_auth_cookie(response, secure=scheme == "https", password=password)
        assert client.get("/deckbrowser", follow_redirects=False).status_code == 200


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_datastar_login_cookie_secure_matches_request_scheme(
    tmp_path: Path, scheme: str
) -> None:
    password = f"test-{tmp_path.name}"
    app = create_app(Settings(collection_path=tmp_path / "c.anki2", password=password))
    with TestClient(app, base_url=f"{scheme}://testserver") as client:
        response = client.post(
            "/login",
            json={"password": password},
            headers={"datastar-request": "true"},
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        assert "window.location" in response.text and "'/'" in response.text
        _assert_auth_cookie(response, secure=scheme == "https", password=password)
        assert client.get("/deckbrowser", follow_redirects=False).status_code == 200
