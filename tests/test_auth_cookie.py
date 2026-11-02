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


@pytest.mark.parametrize(
    ("login_path", "destination"), [("/login", "/"), ("/app/login", "/app/")]
)
@pytest.mark.parametrize("scheme", ["http", "https"])
def test_form_login_cookie_secure_matches_request_scheme(
    tmp_path: Path, scheme: str, login_path: str, destination: str
) -> None:
    password = f"test-{tmp_path.name}"
    app = create_app(Settings(collection_path=tmp_path / "c.anki2", password=password))
    with TestClient(app, base_url=f"{scheme}://testserver") as client:
        response = client.post(
            login_path, data={"password": password}, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == destination
        _assert_auth_cookie(response, secure=scheme == "https", password=password)
        assert client.get("/deckbrowser", follow_redirects=False).status_code == 200
        assert client.get("/app/", follow_redirects=False).status_code == 200


@pytest.mark.parametrize(
    ("login_path", "destination"), [("/login", "/"), ("/app/login", "/app/")]
)
@pytest.mark.parametrize("scheme", ["http", "https"])
def test_datastar_login_cookie_secure_matches_request_scheme(
    tmp_path: Path, scheme: str, login_path: str, destination: str
) -> None:
    password = f"test-{tmp_path.name}"
    app = create_app(Settings(collection_path=tmp_path / "c.anki2", password=password))
    with TestClient(app, base_url=f"{scheme}://testserver") as client:
        response = client.post(
            login_path,
            json={"password": password},
            headers={"datastar-request": "true"},
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        assert f"window.location = '{destination}'" in response.text
        _assert_auth_cookie(response, secure=scheme == "https", password=password)
        assert client.get("/deckbrowser", follow_redirects=False).status_code == 200
        assert client.get("/app/", follow_redirects=False).status_code == 200


@pytest.mark.parametrize("cookie_state", ["absent", "expired"])
def test_app_redirects_to_scoped_login_without_a_live_cookie(
    tmp_path: Path, cookie_state: str
) -> None:
    password = f"test-{tmp_path.name}"
    app = create_app(Settings(collection_path=tmp_path / "c.anki2", password=password))
    with TestClient(app) as client:
        if cookie_state == "expired":
            login = client.post(
                "/app/login", data={"password": password}, follow_redirects=False
            )
            assert login.status_code == 303
            assert client.get("/app/ping", follow_redirects=False).status_code == 200
            cookie = next(
                cookie for cookie in client.cookies.jar if cookie.name == COOKIE
            )
            cookie.expires = 1
            assert cookie.is_expired()

        for path in (
            "/app",
            "/app/",
            "/app/add?deck=1",
            "/app/review?deck=1",
            "/app/unknown/nested?next=https://evil.example",
        ):
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 303
            assert response.headers["location"] == "/app/login"
            assert COOKIE not in response.request.headers.get("cookie", "")

        response = client.post("/app/add/preview", json={}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/app/login"

        for path in ("/deckbrowser", "/application"):
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 303
            assert response.headers["location"] == "/login"


@pytest.mark.parametrize("login_path", ["/login", "/app/login"])
def test_login_form_is_reachable_without_a_cookie_and_submits_to_its_own_path(
    tmp_path: Path, login_path: str
) -> None:
    app = create_app(
        Settings(collection_path=tmp_path / "c.anki2", password=f"test-{tmp_path.name}")
    )
    with TestClient(app) as client:
        response = client.get(login_path, follow_redirects=False)
        assert response.status_code == 200
        assert f'action="{login_path}"' in response.text
        assert f"@post('{login_path}')" in response.text
        assert COOKIE not in response.cookies


@pytest.mark.parametrize("login_path", ["/login", "/app/login"])
@pytest.mark.parametrize("datastar", [False, True])
def test_failed_login_stays_on_its_own_path_and_remains_unauthenticated(
    tmp_path: Path, login_path: str, datastar: bool
) -> None:
    app = create_app(
        Settings(collection_path=tmp_path / "c.anki2", password=f"test-{tmp_path.name}")
    )
    with TestClient(app) as client:
        if datastar:
            response = client.post(
                login_path,
                json={"password": "wrong"},
                headers={"datastar-request": "true"},
                follow_redirects=False,
            )
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            assert "datastar-patch-signals" in response.text
            assert '"error"' in response.text
            assert "window.location" not in response.text
        else:
            response = client.post(
                login_path, data={"password": "wrong"}, follow_redirects=False
            )
            assert response.status_code == 401
            assert f'action="{login_path}"' in response.text
            assert f"@post('{login_path}')" in response.text
            assert "incorrect" in response.text.lower()
        assert "location" not in response.headers
        assert COOKIE not in response.cookies
        protected = client.get("/app/", follow_redirects=False)
        assert protected.status_code == 303
        assert protected.headers["location"] == "/app/login"


@pytest.mark.parametrize(
    ("login_path", "destination"), [("/login", "/"), ("/app/login", "/app/")]
)
@pytest.mark.parametrize("datastar", [False, True])
def test_login_ignores_next_query_parameter(
    tmp_path: Path, login_path: str, destination: str, datastar: bool
) -> None:
    password = f"test-{tmp_path.name}"
    app = create_app(Settings(collection_path=tmp_path / "c.anki2", password=password))
    with TestClient(app) as client:
        for next_url in (
            "https://evil.example/steal",
            "//evil.example/steal",
            "/\\evil.example",
            "%2F%2Fevil.example",
            "/deckbrowser",
        ):
            if datastar:
                response = client.post(
                    f"{login_path}?next={next_url}",
                    json={"password": password},
                    headers={"datastar-request": "true"},
                    follow_redirects=False,
                )
                assert response.status_code == 200
                assert f"window.location = '{destination}'" in response.text
                assert "evil.example" not in response.text
            else:
                response = client.post(
                    f"{login_path}?next={next_url}",
                    data={"password": password},
                    follow_redirects=False,
                )
                assert response.status_code == 303
                assert response.headers["location"] == destination
