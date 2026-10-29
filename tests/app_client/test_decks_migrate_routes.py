from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ankiweb.app import create_app
from ankiweb.core.config import Settings


def _seed(client: TestClient, name: str) -> int:
    assert client.portal is not None
    return client.portal.call(
        client.app.state.service.run,
        lambda col: col.decks.add_normal_deck_with_name(name).id,
    )


def _name(client: TestClient, deck_id: int) -> str:
    assert client.portal is not None
    return client.portal.call(
        client.app.state.service.run, lambda col: col.decks.name(deck_id)
    )


def test_preview_and_apply(client: TestClient) -> None:
    deck_id = _seed(client, "🧬 '\" <b>Bio</b>")
    preview = client.get("/app/decks/migrate-emoji")
    assert preview.status_code == 200
    assert 'id="deck-migrate-region"' in preview.text
    assert "&#39;&#34; &lt;b&gt;Bio&lt;/b&gt;" in preview.text
    assert "<b>Bio</b>" not in preview.text
    assert 'class="modal modal-bottom"' in preview.text
    assert "checked" in preview.text
    response = client.post(
        "/app/decks/migrate-emoji",
        json={"migrateIds": [deck_id]},
        headers={"Datastar-Request": "true"},
    )
    assert response.status_code == 200
    assert "event: datastar-patch-elements" in response.text
    assert "event: datastar-patch-signals" in response.text
    assert '"migrateDone":true' in response.text.replace(" ", "")
    assert _name(client, deck_id) == "'\" <b>Bio</b> · 🧬"
    assert "decks use the old emoji format" not in response.text


@pytest.mark.parametrize("ids", [None, [], "invalid", [True], ["1"], [-1], [2**63]])
def test_invalid_selection_returns_sse_error(client: TestClient, ids) -> None:
    deck_id = _seed(client, "🧬 Bio")
    response = client.post(
        "/app/decks/migrate-emoji",
        json={"migrateIds": ids},
        headers={"Datastar-Request": "true"},
    )
    assert response.status_code == 200
    assert "event: datastar-patch-signals" in response.text
    assert "migrateError" in response.text
    assert _name(client, deck_id) == "🧬 Bio"


def test_password_gate(tmp_path: Path) -> None:
    password = f"test-{tmp_path.name}"
    settings = Settings(collection_path=tmp_path / "auth.anki2", password=password)
    with TestClient(create_app(settings)) as client:
        for response in (
            client.get("/app/decks/migrate-emoji", follow_redirects=False),
            client.post(
                "/app/decks/migrate-emoji",
                json={"migrateIds": [1]},
                follow_redirects=False,
            ),
        ):
            assert response.status_code == 303
            assert response.headers["location"] == "/login"


def test_cross_site_post_is_rejected(client: TestClient) -> None:
    deck_id = _seed(client, "🧬 Bio")
    response = client.post(
        "/app/decks/migrate-emoji",
        json={"migrateIds": [deck_id]},
        headers={
            "Origin": "https://evil.example",
            "Sec-Fetch-Site": "cross-site",
            "Datastar-Request": "true",
        },
    )
    assert response.status_code == 403
    assert _name(client, deck_id) == "🧬 Bio"
