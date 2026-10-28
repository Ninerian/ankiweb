from pathlib import Path

import anki.lang
import pytest
from fastapi.testclient import TestClient

from ankiweb.app import create_app
from ankiweb.core.app_client.vocab import NOTETYPE_NAME, escape_field, highlight_example
from ankiweb.core.auth import COOKIE, auth_token
from ankiweb.core.config import Settings


def test_add_page_initializes_model_and_session(client: TestClient) -> None:
    assert client.portal is not None
    service = client.app.state.service
    deck_id = client.portal.call(
        service.run, lambda col: col.decks.id('Deck <img src=x onerror="x">')
    )
    assert deck_id is not None
    assert (
        client.portal.call(service.run, lambda col: col.models.by_name(NOTETYPE_NAME))
        is None
    )

    page = client.get(f"/app/add?deck={deck_id}")
    assert page.status_code == 200
    assert '<html lang="en" dir="ltr">' in page.text
    assert "Deck &lt;img src=x onerror=&#34;x&#34;&gt;" in page.text
    assert "<img src=x" not in page.text
    assert "/shell/static/app/add.js" in page.text
    assert 'data-signals="{step: 1, front:' in page.text
    for name in ("front", "back", "hint", "example"):
        assert f'id="input-{name}"' in page.text
        assert f"data-bind:{name}" in page.text
    for name in ("preview", "btn-next", "btn-add", "hud-count", "added-cards"):
        assert f'id="{name}"' in page.text
    for step in (1, 2, 3):
        assert f'data-show="$step === {step}" style="display:none"' in page.text
    assert "/app/add/preview" in page.text
    assert "/app/add/commit" not in page.text
    assert "app_sid" in page.cookies
    assert "HttpOnly" in page.headers["set-cookie"]
    assert "SameSite=lax" in page.headers["set-cookie"]
    model = client.portal.call(
        service.run, lambda col: col.models.by_name(NOTETYPE_NAME)
    )
    assert model is not None
    assert [field["name"] for field in model["flds"]] == [
        "Front",
        "Back",
        "Hint",
        "Example",
    ]
    assert "set-cookie" not in client.get(f"/app/add?deck={deck_id}").headers


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?deck=",
        "?deck=nope",
        "?deck=0",
        "?deck=-1",
        "?deck=9223372036854775808",
        "?deck=999999999",
    ],
)
def test_add_page_rejects_missing_or_unknown_deck(
    client: TestClient, query: str
) -> None:
    response = client.get(f"/app/add{query}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/app/"
    assert "app_sid" not in response.cookies
    assert client.portal is not None
    assert (
        client.portal.call(
            client.app.state.service.run, lambda col: col.models.by_name(NOTETYPE_NAME)
        )
        is None
    )


def test_add_routes_follow_password_gate(tmp_path: Path) -> None:
    password = f"test-{tmp_path.name}"
    settings = Settings(collection_path=tmp_path / "auth-add.anki2", password=password)
    with TestClient(create_app(settings)) as client:
        for response in (
            client.get("/app/add?deck=1", follow_redirects=False),
            client.post("/app/add/preview", json={}, follow_redirects=False),
        ):
            assert response.status_code == 303
            assert response.headers["location"] == "/login"
            assert "app_sid" not in response.cookies
        client.cookies.set(COOKIE, auth_token(password))
        assert client.get("/app/add?deck=1").status_code == 200
        assert client.post("/app/add/preview", json={}).status_code == 200


def test_preview_escapes_all_fields_and_highlights_example(client: TestClient) -> None:
    example = "<img src=x onerror=alert(1)> *safe & sound*\n*next*"
    payload = {
        "front": "<img src=x onerror=alert(1)>",
        "back": "<script>alert(1)</script>",
        "hint": "<b>hint</b> & more",
        "example": example,
    }
    response = client.post("/app/add/preview", json=payload)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: datastar-patch-elements" in response.text
    assert 'id="preview"' in response.text
    assert "&lt;img src=x onerror=alert(1)&gt;" in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "&lt;b&gt;hint&lt;/b&gt; &amp; more" in response.text
    assert highlight_example(escape_field(example)) in response.text
    assert "<mark>safe &amp; sound</mark><br><mark>next</mark>" in response.text
    assert "<img src=x" not in response.text
    assert "<script>" not in response.text


def test_preview_never_interprets_highlighted_markup(client: TestClient) -> None:
    response = client.post(
        "/app/add/preview", json={"example": "*<img src=x onerror=alert(1)>*"}
    )
    assert "<mark>&lt;img src=x onerror=alert(1)&gt;</mark>" in response.text
    assert "<img src=x" not in response.text


def test_preview_omits_empty_optional_fields(client: TestClient) -> None:
    response = client.post(
        "/app/add/preview", json={"front": "Question", "back": "Answer"}
    )
    assert response.status_code == 200
    assert "Question" in response.text
    assert "Answer" in response.text
    assert "Hint" not in response.text
    assert "Example sentence" not in response.text


def test_add_page_uses_resolved_language(tmp_path: Path) -> None:
    settings = Settings(collection_path=tmp_path / "de-add.anki2", lang="de_DE")
    try:
        with TestClient(create_app(settings)) as client:
            response = client.get("/app/add?deck=1")
            preview = client.post("/app/add/preview", json={"front": "Frage"})
    finally:
        anki.lang.set_lang("en")
    assert response.status_code == 200
    assert '<html lang="de" dir="ltr">' in response.text
    assert "Vorderseite (Frage / Stichwort)" in response.text
    assert "Kartenvorschau" in preview.text
