from http.cookies import SimpleCookie
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response

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

        for path in ("/deckbrowser", "/application", "/appx"):
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
            expected = (
                "Wrong password. Try again!"
                if login_path == "/app/login"
                else "Email or password was incorrect"
            )
            assert expected in response.text
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


@pytest.mark.parametrize(
    ("login_path", "destination"), [("/login", "/"), ("/app/login", "/app/")]
)
@pytest.mark.parametrize("datastar", [False, True])
@pytest.mark.parametrize(
    ("password", "incorrect"),
    [(" secret ", "secret"), ("  ", ""), ("secret", " secret ")],
)
def test_login_preserves_password_whitespace(
    tmp_path: Path,
    login_path: str,
    destination: str,
    datastar: bool,
    password: str,
    incorrect: str,
) -> None:
    app = create_app(Settings(collection_path=tmp_path / "c.anki2", password=password))
    with TestClient(app) as client:
        headers = {"Datastar-Request": "true"} if datastar else {}
        rejected = client.post(
            login_path,
            headers=headers,
            data=None if datastar else {"password": incorrect},
            json={"password": incorrect} if datastar else None,
            follow_redirects=False,
        )
        assert rejected.status_code == (200 if datastar else 401)
        assert "location" not in rejected.headers
        assert "window.location" not in rejected.text
        assert COOKIE not in rejected.cookies
        assert COOKIE not in client.cookies

        accepted = client.post(
            login_path,
            headers=headers,
            data=None if datastar else {"password": password},
            json={"password": password} if datastar else None,
            follow_redirects=False,
        )
        if datastar:
            assert accepted.status_code == 200
            assert accepted.headers["content-type"].startswith("text/event-stream")
            assert f"window.location = '{destination}'" in accepted.text
            assert "location" not in accepted.headers
        else:
            assert accepted.status_code == 303
            assert accepted.headers["location"] == destination
        assert accepted.cookies.get(COOKIE) == auth_token(password)
        assert client.get("/app/", follow_redirects=False).status_code == 200


@pytest.mark.parametrize("cookie_state", ["missing", "invalid"])
@pytest.mark.parametrize("datastar", [False, True])
@pytest.mark.parametrize("path", ["/app", "/app/", "/app/ping", "/app/add?deck=1"])
def test_app_guard_redirects_by_request_protocol(
    tmp_path: Path, cookie_state: str, datastar: bool, path: str
) -> None:
    app = create_app(
        Settings(collection_path=tmp_path / "c.anki2", password=f"test-{tmp_path.name}")
    )
    with TestClient(app) as client:
        if cookie_state == "invalid":
            client.cookies.set(COOKIE, "invalid")
        headers = {"Datastar-Request": "true"} if datastar else {}
        response = client.get(path, headers=headers, follow_redirects=False)
        if datastar:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert "event: datastar-patch-elements" in response.text
            assert "window.location = '/app/login'" in response.text
            assert "location" not in response.headers
        else:
            assert response.status_code == 303
            assert response.headers["location"] == "/app/login"
        assert "app_sid" not in response.cookies


@pytest.mark.parametrize("datastar", [False, True])
def test_app_prefix_neighbor_keeps_legacy_guard(tmp_path: Path, datastar: bool) -> None:
    app = create_app(
        Settings(collection_path=tmp_path / "c.anki2", password=f"test-{tmp_path.name}")
    )
    with TestClient(app) as client:
        headers = {"Datastar-Request": "true"} if datastar else {}
        response = client.get("/appx", headers=headers, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"


@pytest.mark.parametrize("login_path", ["/login", "/app/login"])
def test_logout_invalidates_shared_cookie_even_with_app_session(
    tmp_path: Path, login_path: str
) -> None:
    password = f"test-{tmp_path.name}"
    app = create_app(Settings(collection_path=tmp_path / "c.anki2", password=password))
    with TestClient(app) as client:
        response = client.post(
            login_path, data={"password": password}, follow_redirects=False
        )
        assert response.cookies.get(COOKIE) == auth_token(password)
        assert client.get("/deckbrowser", follow_redirects=False).status_code == 200
        assert client.get("/app/", follow_redirects=False).status_code == 200
        client.cookies.set("app_sid", "not-an-authentication-cookie")
        logout = client.get("/logout", follow_redirects=False)
        assert logout.status_code == 303
        assert logout.headers["location"] == "/login"
        assert not client.cookies.get(COOKIE)
        assert client.cookies.get("app_sid") == "not-an-authentication-cookie"
        legacy = client.get("/deckbrowser", follow_redirects=False)
        app_page = client.get("/app/", follow_redirects=False)
        assert legacy.status_code == 303 and legacy.headers["location"] == "/login"
        assert (
            app_page.status_code == 303 and app_page.headers["location"] == "/app/login"
        )


@pytest.mark.parametrize("scheme", ["http", "https"])
@pytest.mark.parametrize("datastar", [False, True])
def test_legacy_and_app_login_issue_identical_auth_cookie(
    tmp_path: Path, scheme: str, datastar: bool
) -> None:
    password = f"test-{tmp_path.name}"
    app = create_app(Settings(collection_path=tmp_path / "c.anki2", password=password))
    cookies = []
    for path in ("/login", "/app/login"):
        with TestClient(app, base_url=f"{scheme}://testserver") as client:
            if datastar:
                response = client.post(
                    path,
                    json={"password": password},
                    headers={"Datastar-Request": "true"},
                    follow_redirects=False,
                )
            else:
                response = client.post(
                    path, data={"password": password}, follow_redirects=False
                )
            _assert_auth_cookie(response, secure=scheme == "https", password=password)
            cookies.append(
                next(
                    h
                    for h in response.headers.get_list("set-cookie")
                    if h.startswith(f"{COOKIE}=")
                )
            )
    assert cookies[0] == cookies[1]
