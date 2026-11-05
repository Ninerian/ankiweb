import html
import json
from pathlib import Path
from typing import Protocol, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ankiweb.app import create_app
from ankiweb.core.app_client.decks import join_emoji
from ankiweb.core.app_client.strings import s
from ankiweb.core.auth import COOKIE, auth_token
from ankiweb.core.config import Settings


class _TextResponse(Protocol):
    @property
    def text(self) -> str: ...


@pytest.fixture(autouse=True)
def datastar_request(client: TestClient) -> None:
    client.headers["Datastar-Request"] = "true"


def _signals(response: _TextResponse) -> dict[str, object]:
    for line in response.text.splitlines():
        if line.startswith("data: signals "):
            return json.loads(line.removeprefix("data: signals "))
    raise AssertionError("No signal patch")


def _decks(client: TestClient) -> dict[int, str]:
    assert client.portal is not None
    return client.portal.call(
        cast(FastAPI, client.app).state.service.run,
        lambda col: {deck.id: deck.name for deck in col.decks.all_names_and_ids()},
    )


def test_create_renders_searchable_list_toast_and_reset(client: TestClient) -> None:
    before = _decks(client)
    response = client.post("/app/decks", json={"newName": "Biology", "newEmoji": "🧬"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    created = {key: name for key, name in _decks(client).items() if key not in before}
    assert list(created.values()) == ["Biology · 🧬"]
    (deck_id,) = created
    assert "data: selector #decks-content" in response.text
    assert f'id="deck-{deck_id}"' in response.text
    assert 'id="toast"' in response.text
    assert s("app_decks_created", lang="en") in response.text
    assert _signals(response) == {
        "q": "",
        "newName": "",
        "newEmoji": "📚",
        "newError": "",
        "newOpen": False,
    }
    assert "biology" in html.unescape(response.text)
    assert 'id="empty-state"' in response.text
    page = client.get("/app/")
    assert f'id="deck-{deck_id}"' in page.text
    assert "biology" in html.unescape(page.text)


@pytest.mark.parametrize(
    ("name", "emoji", "kind"),
    [
        (" ", "📚", "empty"),
        ("x" * 41, "📚", "too_long"),
        ("Parent::Child", "📚", "invalid"),
        ("📚", "📚", "invalid"),
        ("Name", "x", "invalid"),
        ("default", "📚", "taken"),
    ],
)
def test_errors_patch_only_error_without_writing(
    client: TestClient, name: str, emoji: str, kind: str
) -> None:
    before = _decks(client)
    response = client.post("/app/decks", json={"newName": name, "newEmoji": emoji})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert _signals(response) == {"newError": s(f"app_decks_name_{kind}", lang="en")}
    assert "datastar-patch-elements" not in response.text
    assert _decks(client) == before


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"newName": "Name"},
        {"newName": 3, "newEmoji": "📚"},
        {"newName": "Name", "newEmoji": None},
        [],
        None,
    ],
)
def test_invalid_signals_are_rejected(client: TestClient, payload: object) -> None:
    before = _decks(client)
    response = client.post("/app/decks", json=payload)
    assert response.status_code == 200
    assert _signals(response) == {"newError": s("app_decks_name_invalid", lang="en")}
    assert _decks(client) == before


@pytest.mark.parametrize("cookie_state", ["missing", "invalid", "expired"])
def test_create_requires_password(tmp_path: Path, cookie_state: str) -> None:
    password = f"test-{tmp_path.name}"
    settings = Settings(
        collection_path=tmp_path / "auth-decks.anki2", password=password
    )
    with TestClient(create_app(settings)) as client:
        client.headers["Datastar-Request"] = "true"
        if cookie_state != "missing":
            client.cookies.set(
                COOKIE,
                auth_token(password) if cookie_state == "expired" else "invalid",
                domain="testserver.local",
            )
        if cookie_state == "expired":
            cookie = next(c for c in client.cookies.jar if c.name == COOKIE)
            cookie.expires = 1
            assert cookie.is_expired()
        before = _decks(client)
        response = client.post(
            "/app/decks",
            json={"newName": "Locked", "newEmoji": "📚"},
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "event: datastar-patch-elements" in response.text
        assert "window.location = '/app/login'" in response.text
        assert "location" not in response.headers
        assert "app_sid" not in response.cookies
        assert _decks(client) == before

        login = client.post(
            "/app/login", json={"password": password}, follow_redirects=False
        )
        assert login.status_code == 200
        assert login.headers["content-type"].startswith("text/event-stream")
        assert "window.location = '/app/'" in login.text
        assert login.cookies.get(COOKIE) == auth_token(password)
        assert client.get("/app/", follow_redirects=False).status_code == 200
        assert _decks(client) == before
        assert (
            client.post(
                "/app/decks", json={"newName": "Locked", "newEmoji": "📚"}
            ).status_code
            == 200
        )
        assert "Locked · 📚" in _decks(client).values()


def test_foreign_origin_cannot_create_deck(client: TestClient) -> None:
    before = _decks(client)
    response = client.post(
        "/app/decks",
        json={"newName": "Attack", "newEmoji": "📚"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert _decks(client) == before


def test_special_characters_are_escaped_in_markup_and_js(client: TestClient) -> None:
    name = 'It\'s "Q" \\ <b>x</b> & $x'
    before = _decks(client)
    response = client.post("/app/decks", json={"newName": name, "newEmoji": "📚"})
    assert response.status_code == 200
    assert "&lt;b&gt;x&lt;/b&gt;" in response.text
    assert "<b>x</b>" not in response.text
    assert "\\u0024" in html.unescape(response.text)
    created = {
        key: stored for key, stored in _decks(client).items() if key not in before
    }
    assert list(created.values()) == [join_emoji(name, "📚")]


def test_list_shows_saved_name_for_anki_normalized_input(client: TestClient) -> None:
    before = _decks(client)
    response = client.post("/app/decks", json={"newName": ":Bio:", "newEmoji": "🧬"})
    assert response.status_code == 200
    created = [name for key, name in _decks(client).items() if key not in before]
    assert created == ["Bio · 🧬"]
    assert ":Bio" not in html.unescape(response.text)


def test_colon_prefixed_duplicate_is_rejected_without_row(client: TestClient) -> None:
    assert (
        client.post("/app/decks", json={"newName": "Bio", "newEmoji": "📚"}).status_code
        == 200
    )
    before = _decks(client)
    response = client.post("/app/decks", json={"newName": ":Bio", "newEmoji": "📚"})
    assert response.status_code == 200
    assert _signals(response) == {"newError": s("app_decks_name_taken", lang="en")}
    assert "#decks-content" not in response.text
    assert _decks(client) == before


def test_created_row_has_no_leading_colon(client: TestClient) -> None:
    response = client.post("/app/decks", json={"newName": ":Bio2", "newEmoji": "📚"})
    content = response.text.split("data: selector #decks-content")[1]
    assert "Bio2" in content
    assert ":Bio2" not in html.unescape(content)
