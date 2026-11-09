import html
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import cast
from urllib.parse import urlencode

import anki.lang
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response

from ankiweb.app import create_app
from ankiweb.core.app_client.deck_languages import LanguagePair, read_marker
from ankiweb.core.app_client.decks import join_emoji
from ankiweb.core.app_client.strings import s
from ankiweb.core.auth import COOKIE, auth_token
from ankiweb.core.config import Settings


@pytest.fixture(autouse=True)
def datastar_request(client: TestClient) -> None:
    client.headers["Datastar-Request"] = "true"


class _Dialog(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.token = ""
        self.fields: dict[str, str | None] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "dialog" and values.get("id") == "deck-dialog":
            self.token = values.get("data-token") or ""
        if tag == "input" and values.get("name"):
            self.fields[cast(str, values["name"])] = values.get("value")


def _open(client: TestClient, query: str = "") -> str:
    response = client.get("/app/decks/new", params={"q": query})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "data: selector #deck-dialog-host" in response.text
    dialog = _Dialog()
    dialog.feed(
        "\n".join(
            line.removeprefix("data: elements ")
            for line in response.text.splitlines()
            if line.startswith("data: elements ")
        )
    )
    assert re.fullmatch(r"[0-9a-f]{16}", dialog.token)
    assert dialog.fields["token"] == dialog.token
    return dialog.token


def _payload(token: str, name: str = "Biology", emoji: str = "🧬") -> dict[str, str]:
    return {
        "token": token,
        "name": name,
        "emoji": emoji,
        "mode": "none",
        "src": "",
        "dst": "",
    }


def _decks(client: TestClient) -> dict[int, str]:
    assert client.portal is not None
    return client.portal.call(
        cast(FastAPI, client.app).state.service.run,
        lambda col: {deck.id: deck.name for deck in col.decks.all_names_and_ids()},
    )


def _assert_error(response: Response, token: str, message: str) -> None:
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert (
        f'data: selector #deck-dialog[data-token="{token}"] #new-error' in response.text
    )
    assert message in html.unescape(response.text)
    assert "#deck-results" not in response.text
    assert "#deck-search-form" not in response.text
    assert "#toast" not in response.text
    assert "ankiweb:decks-refresh" not in response.text
    assert "datastar-patch-signals" not in response.text


def test_create_renders_search_reset_toast_and_scoped_close(client: TestClient) -> None:
    token = _open(client)
    before = _decks(client)
    response = client.post("/app/decks", data=_payload(token))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    created = {key: name for key, name in _decks(client).items() if key not in before}
    assert list(created.values()) == ["Biology · 🧬"]
    (deck_id,) = created
    assert "data: selector #deck-results" not in response.text
    assert "data: selector #deck-search-form" in response.text
    assert "data: selector #toast" in response.text
    assert s("app_decks_created", lang="en") in response.text
    assert f'#deck-dialog[data-token="{token}"]' in html.unescape(response.text)
    assert ".close()" in response.text
    assert "ankiweb:decks-refresh" in response.text
    assert f"created:{deck_id}" in response.text
    assert "datastar-patch-signals" not in response.text
    assert response.text.index("#deck-search-form") < response.text.index("#toast")
    assert response.text.index("#toast") < response.text.index(".close()")
    assert response.text.index(".close()") < response.text.index("window.dispatchEvent")
    page = client.get("/app/")
    assert f'id="deck-{deck_id}"' in page.text
    assert "Biology" in html.unescape(page.text)


def test_creating_from_filtered_list_resets_search_without_patching_results(
    client: TestClient,
) -> None:
    token = _open(client, "missing")
    response = client.post("/app/decks", data=_payload(token))
    assert response.status_code == 200
    assert "data: selector #deck-search-form" in response.text
    assert "data: selector #deck-results" not in response.text
    assert "ankiweb:decks-refresh" in response.text
    assert "Biology · 🧬" in _decks(client).values()


def test_prefill_escapes_search_text_in_native_form(client: TestClient) -> None:
    query = '"><img src=x> & $x'
    before = _decks(client)
    response = client.get("/app/decks/new", params={"prefill": "1", "q": query})
    assert response.status_code == 200
    fragment = "\n".join(
        line.removeprefix("data: elements ")
        for line in response.text.splitlines()
        if line.startswith("data: elements ")
    )
    dialog = _Dialog()
    dialog.feed(fragment)
    assert dialog.fields["name"] == query
    assert "<img src=x>" not in fragment
    assert re.fullmatch(r"[0-9a-f]{16}", dialog.token)
    assert _decks(client) == before


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
def test_validation_errors_patch_only_scoped_error_without_writing(
    client: TestClient, name: str, emoji: str, kind: str
) -> None:
    token = _open(client)
    before = _decks(client)
    response = client.post("/app/decks", data=_payload(token, name, emoji))
    _assert_error(response, token, s(f"app_decks_name_{kind}", lang="en"))
    assert _decks(client) == before


@pytest.mark.parametrize(
    ("mode", "src", "dst", "key"),
    [
        ("langs", "de", "de", "app_decks_lang_same"),
        ("langs", "", "es", "app_decks_lang_missing_src"),
        ("langs", "de", "", "app_decks_lang_missing_dst"),
        ("langs", "", "", "app_decks_lang_missing_src"),
        ("langs", "xx", "es", "app_decks_lang_pick"),
        ("wrong", "de", "es", "app_decks_lang_pick"),
    ],
)
def test_invalid_language_choices_do_not_create(
    client: TestClient, mode: str, src: str, dst: str, key: str
) -> None:
    token = _open(client)
    before = _decks(client)
    response = client.post(
        "/app/decks",
        data={**_payload(token), "mode": mode, "src": src, "dst": dst},
    )
    if key == "app_decks_lang_same":
        message = s(key, lang="en", language=s("app_lang_de", lang="en"))
    else:
        message = s(key, lang="en")
    _assert_error(response, token, message)
    assert _decks(client) == before


def test_create_persists_language_pair(client: TestClient) -> None:
    token = _open(client)
    before = _decks(client)
    response = client.post(
        "/app/decks",
        data={**_payload(token), "mode": "langs", "src": "de", "dst": "es"},
    )
    assert response.status_code == 200
    (deck_id,) = set(_decks(client)) - set(before)
    assert client.portal is not None
    deck = client.portal.call(
        cast(FastAPI, client.app).state.service.run,
        lambda col: col.decks.get(deck_id, default=False),
    )
    assert deck is not None
    assert read_marker(deck["desc"]) == LanguagePair("de", "es")


@pytest.mark.parametrize(
    "token", ["", "1", "0" * 15, "0" * 17, "A" * 16, '0"] * { color:red } /*']
)
def test_invalid_token_cannot_create_or_construct_selector(
    client: TestClient, token: str
) -> None:
    before = _decks(client)
    response = client.post("/app/decks", data=_payload(token))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.content == b""
    assert _decks(client) == before


@pytest.mark.parametrize("field", ["token", "name", "emoji", "mode", "src", "dst"])
def test_missing_fields_do_not_write(client: TestClient, field: str) -> None:
    payload = _payload(_open(client))
    missing_value = payload.pop(field)
    before = _decks(client)
    for params in ({}, {field: missing_value}):
        response = client.post("/app/decks", params=params, data=payload)
        assert response.status_code == 200 and response.content == b""
    assert _decks(client) == before


def test_create_rejects_file_uploads(client: TestClient) -> None:
    payload = _payload(_open(client))
    del payload["name"]
    before = _decks(client)
    response = client.post(
        "/app/decks",
        data=payload,
        files={"name": ("name.txt", b"Biology", "text/plain")},
    )
    assert response.status_code == 200 and response.content == b""
    assert _decks(client) == before


@pytest.mark.parametrize("field", ["token", "name", "emoji", "mode", "src", "dst"])
def test_duplicate_form_fields_do_not_write(client: TestClient, field: str) -> None:
    payload = _payload(_open(client))
    body = urlencode([*payload.items(), (field, payload[field])])
    before = _decks(client)
    response = client.post(
        "/app/decks",
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200 and response.content == b""
    assert _decks(client) == before


def test_json_signal_payload_is_not_form_transport(client: TestClient) -> None:
    token = _open(client)
    before = _decks(client)
    response = client.post("/app/decks", json=_payload(token))
    assert response.status_code == 200
    assert response.content == b""
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
            data=_payload("0" * 16, "Locked", "📚"),
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "window.location = '/app/login'" in response.text
        assert "location" not in response.headers
        assert _decks(client) == before

        login = client.post(
            "/app/login", json={"password": password}, follow_redirects=False
        )
        assert login.cookies.get(COOKIE) == auth_token(password)
        token = _open(client)
        assert (
            client.post("/app/decks", data=_payload(token, "Locked", "📚")).status_code
            == 200
        )
        assert "Locked · 📚" in _decks(client).values()


@pytest.mark.parametrize(
    "headers", [{"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}]
)
def test_cross_site_cannot_create_deck(
    client: TestClient, headers: dict[str, str]
) -> None:
    token = _open(client)
    before = _decks(client)
    response = client.post(
        "/app/decks", data=_payload(token, "Attack", "📚"), headers=headers
    )
    assert response.status_code == 403
    assert _decks(client) == before


@pytest.mark.parametrize("lang", ["en", "de"])
def test_validation_uses_app_locale(tmp_path: Path, lang: str) -> None:
    settings = Settings(collection_path=tmp_path / "locale-create.anki2", lang=lang)
    try:
        with TestClient(create_app(settings)) as client:
            client.headers["Datastar-Request"] = "true"
            token = _open(client)
            before = _decks(client)
            response = client.post("/app/decks", data=_payload(token, " ", "📚"))
            _assert_error(response, token, s("app_decks_name_empty", lang=lang))
            assert _decks(client) == before
    finally:
        anki.lang.set_lang("en")


def test_special_characters_are_escaped_in_markup(client: TestClient) -> None:
    name = 'It\'s "Q" \\ <b>x</b> & $x'
    token = _open(client)
    before = _decks(client)
    response = client.post("/app/decks", data=_payload(token, name, "📚"))
    assert response.status_code == 200
    page = client.get("/app/")
    assert "&lt;b&gt;x&lt;/b&gt;" in page.text
    assert "<b>x</b>" not in page.text
    created = {
        key: stored for key, stored in _decks(client).items() if key not in before
    }
    assert list(created.values()) == [join_emoji(name, "📚")]


def test_list_shows_saved_name_for_anki_normalized_input(client: TestClient) -> None:
    token = _open(client)
    before = _decks(client)
    response = client.post("/app/decks", data=_payload(token, ":Bio:", "🧬"))
    assert response.status_code == 200
    assert [name for key, name in _decks(client).items() if key not in before] == [
        "Bio · 🧬"
    ]
    assert ":Bio" not in html.unescape(client.get("/app/").text)


def test_colon_prefixed_duplicate_is_rejected_without_row(client: TestClient) -> None:
    token = _open(client)
    client.post("/app/decks", data=_payload(token, "Bio", "📚"))
    token = _open(client)
    before = _decks(client)
    response = client.post("/app/decks", data=_payload(token, ":Bio", "📚"))
    _assert_error(response, token, s("app_decks_name_taken", lang="en"))
    assert _decks(client) == before
