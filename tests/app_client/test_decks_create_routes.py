import html
import json
from pathlib import Path

import pytest
from anki.decks import DeckId
from fastapi.testclient import TestClient
from httpx import Response

from ankiweb.app import create_app
from ankiweb.core.app_client.decks import join_emoji
from ankiweb.core.app_client.strings import s
from ankiweb.core.auth import COOKIE, auth_token
from ankiweb.core.config import Settings


@pytest.fixture(autouse=True)
def datastar_request(client: TestClient) -> None:
    client.headers["Datastar-Request"] = "true"


def _signals(response: Response) -> dict[str, object]:
    for line in response.text.splitlines():
        if line.startswith("data: signals "):
            return json.loads(line.removeprefix("data: signals "))
    raise AssertionError("No signal patch")


def _decks(client: TestClient) -> dict[int, str]:
    assert client.portal is not None
    return client.portal.call(
        client.app.state.service.run,
        lambda col: {deck.id: deck.name for deck in col.decks.all_names_and_ids()},
    )


def test_create_renders_searchable_list_toast_and_reset(client: TestClient) -> None:
    response = client.post("/app/decks", json={"newName": "Biology", "newEmoji": "🧬"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    deck_id = next(
        key for key, name in _decks(client).items() if name == "Biology · 🧬"
    )
    assert _decks(client)[deck_id] == join_emoji("Biology", "🧬")
    assert "data: selector #decks-content" in response.text
    assert f'id="deck-{deck_id}"' in response.text
    assert 'id="toast"' in response.text
    assert s("app_decks_created", lang="en") in response.text
    assert _signals(response) == {
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


def test_create_requires_password(tmp_path: Path) -> None:
    password = f"test-{tmp_path.name}"
    settings = Settings(
        collection_path=tmp_path / "auth-decks.anki2", password=password
    )
    with TestClient(create_app(settings)) as client:
        client.headers["Datastar-Request"] = "true"
        response = client.post(
            "/app/decks",
            json={"newName": "Locked", "newEmoji": "📚"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/login"
        client.cookies.set(COOKIE, auth_token(password))
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
    response = client.post("/app/decks", json={"newName": name, "newEmoji": "📚"})
    assert response.status_code == 200
    assert "&lt;b&gt;x&lt;/b&gt;" in response.text
    assert "<b>x</b>" not in response.text
    assert "\\u0024" in html.unescape(response.text)
    decks = _decks(client)
    deck_id = next(
        key for key, stored in decks.items() if stored == join_emoji(name, "📚")
    )
    assert client.portal is not None
    assert client.portal.call(
        client.app.state.service.run, lambda col: col.decks.name(DeckId(deck_id))
    ) == join_emoji(name, "📚")


def test_migration_refresh_renders_split_name_and_emoji(client: TestClient) -> None:
    assert client.portal is not None
    deck_id = client.portal.call(
        client.app.state.service.run,
        lambda col: col.decks.add_normal_deck_with_name("🧬 Biology").id,
    )
    page = client.get("/app/")
    assert "decks/refresh" in page.text
    assert 'id="deck-migrate-region"' in page.text
    assert "decks use the old emoji format" in page.text
    response = client.post("/app/decks/migrate-emoji", json={"migrateIds": [deck_id]})
    assert _signals(response)["migrateDone"] is True
    refreshed = client.get("/app/decks/refresh")
    assert refreshed.status_code == 200
    assert "data: selector #decks-content" in refreshed.text
    assert f'id="deck-{deck_id}"' in refreshed.text
    assert ">🧬</span>" in refreshed.text
    assert ">Biology</h3>" in refreshed.text
    assert "🧬 Biology" not in refreshed.text
    assert _signals(refreshed) == {"migrateDone": False}
