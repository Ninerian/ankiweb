import re
from html.parser import HTMLParser
from pathlib import Path
from typing import cast
from urllib.parse import urlencode

import anki.lang
import pytest
from anki.collection import Collection
from anki.decks import DeckId
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response

from ankiweb.app import create_app
from ankiweb.core.app_client.strings import s
from ankiweb.core.auth import COOKIE, auth_token
from ankiweb.core.config import Settings


@pytest.fixture
def client(client: TestClient) -> TestClient:
    client.headers["Datastar-Request"] = "true"
    return client


def _snapshot(client: TestClient) -> tuple:
    assert client.portal is not None

    def snapshot(col: Collection) -> tuple:
        assert col.db is not None
        return (
            tuple(
                sorted(
                    (deck["id"], deck["name"], deck.get("desc", ""))
                    for deck in col.decks.all()
                )
            ),
            tuple(col.db.all("select * from cards order by id")),
            tuple(col.db.all("select * from notes order by id")),
            str(col.undo_status()),
        )

    return client.portal.call(cast(FastAPI, client.app).state.service.run, snapshot)


def _seed_deck(client: TestClient) -> DeckId:
    assert client.portal is not None

    def seed(col: Collection) -> DeckId:
        deck_id = DeckId(col.decks.add_normal_deck_with_name("Original · 📚").id)
        deck = col.decks.get(deck_id, default=False)
        assert deck is not None
        deck["desc"] = "<!--ankiweb:lang=de>fr-->Description"
        col.decks.update_dict(deck)
        return deck_id

    return client.portal.call(cast(FastAPI, client.app).state.service.run, seed)


def _events(response: Response) -> list[tuple[str, list[str]]]:
    events: list[tuple[str, list[str]]] = []
    event = ""
    data: list[str] = []
    for line in response.text.splitlines() + [""]:
        if not line:
            if event:
                events.append((event, data))
            event, data = "", []
        elif line.startswith("event: "):
            event = line.removeprefix("event: ")
        elif line.startswith("data: "):
            data.append(line.removeprefix("data: "))
    return events


def _elements(response: Response) -> str:
    return "\n".join(
        line.removeprefix("elements ")
        for event, data in _events(response)
        if event == "datastar-patch-elements"
        for line in data
        if line.startswith("elements ")
    )


class _Markup(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.text: list[str] = []
        self.ids: dict[str, dict[str, str | None]] = {}
        self.fields: dict[str, str | None] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        values = dict(attrs)
        if values.get("id"):
            self.ids[cast(str, values["id"])] = values
        if tag == "input" and values.get("name"):
            self.fields[cast(str, values["name"])] = values.get("value")

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def _open(client: TestClient, kind: str, deck_id: int = 1) -> str:
    url = "/app/decks/new" if kind == "create" else f"/app/decks/{deck_id}/settings"
    response = client.get(url)
    assert response.status_code == 200
    assert "data: selector #deck-dialog-host" in response.text
    markup = _Markup()
    markup.feed(_elements(response))
    dialog = markup.ids["deck-dialog"]
    token = dialog.get("data-token") or ""
    assert re.fullmatch(r"[0-9a-f]{16}", token)
    assert markup.fields["token"] == token
    return token


def _payload(token: str) -> dict[str, str]:
    return {
        "token": token,
        "name": "  Biology  ",
        "emoji": "🧬",
        "mode": "langs",
        "src": "de",
        "dst": "es",
    }


def _url(kind: str, deck_id: int = 1) -> str:
    return (
        "/app/decks/new/preview"
        if kind == "create"
        else f"/app/decks/{deck_id}/settings/preview"
    )


def _assert_empty_sse(response: Response) -> None:
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.content == b""


def _selectors(response: Response) -> list[str]:
    return [
        line.removeprefix("selector ")
        for _, data in _events(response)
        for line in data
        if line.startswith("selector ")
    ]


@pytest.mark.parametrize("kind", ["create", "settings"])
def test_preview_patches_only_token_scoped_projections_without_writing(
    client: TestClient, kind: str
) -> None:
    deck_id = _seed_deck(client)
    token = _open(client, kind, deck_id)
    before = _snapshot(client)
    response = client.post(_url(kind, deck_id), data=_payload(token))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response)
    assert events and all(event == "datastar-patch-elements" for event, _ in events)
    selectors = _selectors(response)
    prefix = "new" if kind == "create" else "set"
    fragments = {
        "preview",
        "messages",
        "flag-src",
        "flag-dst",
        "swap",
        "name-count",
        "error",
        "submit",
    }
    if kind == "create":
        fragments.add("suggest")
    else:
        fragments.update({"dirty", "name-changed", "emoji-changed", "lang-changed"})
    dialog = f'#deck-dialog[data-token="{token}"]'
    form = "deck-create-form" if kind == "create" else "deck-settings-form"
    expected = {
        f"{dialog} #{prefix}-{fragment}"
        for fragment in fragments
        if fragment != "error"
    }
    expected.add(f"{dialog} #{form}:not([data-submitted]) #{prefix}-error")
    assert set(selectors) == expected
    assert len(selectors) == len(events) == len(fragments)
    markup = _Markup()
    markup.feed(_elements(response))
    assert "input" not in markup.tags and "select" not in markup.tags
    assert "textarea" not in markup.tags and "form" not in markup.tags
    assert "Biology" in "".join(markup.text)
    assert "🇩🇪 DE → 🇪🇸 ES" in "".join(markup.text)
    assert _snapshot(client) == before


def test_create_preview_renders_optional_flag_suggestion(client: TestClient) -> None:
    token = _open(client, "create")
    response = client.post(_url("create"), data={**_payload(token), "emoji": "📚"})
    markup = _Markup()
    markup.feed(_elements(response))
    suggestion = markup.ids["new-flag-suggest"]
    assert "hidden" not in suggestion
    assert suggestion["data-flag"] == "🇪🇸"

    response = client.post(_url("create"), data={**_payload(token), "emoji": "🇪🇸"})
    markup = _Markup()
    markup.feed(_elements(response))
    assert "hidden" in markup.ids["new-flag-suggest"]


@pytest.mark.parametrize(
    ("name", "src", "dst", "disabled"),
    [
        ("Biology", "de", "es", False),
        (" ", "de", "es", True),
        ("Biology", "de", "", True),
        ("Biology", "de", "de", True),
        ("Parent::Child", "de", "es", False),
    ],
)
def test_preview_submit_reflects_content_without_early_domain_validation(
    client: TestClient, name: str, src: str, dst: str, disabled: bool
) -> None:
    token = _open(client, "create")
    response = client.post(
        _url("create"), data={**_payload(token), "name": name, "src": src, "dst": dst}
    )
    markup = _Markup()
    markup.feed(_elements(response))
    assert ("disabled" in markup.ids["btn-create-deck"]) is disabled


@pytest.mark.parametrize("kind", ["create", "settings"])
def test_preview_name_count_uses_utf16_code_units(
    client: TestClient, kind: str
) -> None:
    deck_id = _seed_deck(client)
    token = _open(client, kind, deck_id)
    response = client.post(
        _url(kind, deck_id), data={**_payload(token), "name": "a🧬b"}
    )
    assert "4 / 40" in _elements(response)


def test_settings_preview_uses_stored_baseline_and_renders_dirty_groups(
    client: TestClient,
) -> None:
    deck_id = _seed_deck(client)
    token = _open(client, "settings", deck_id)
    before = _snapshot(client)
    payload = {
        **_payload(token),
        "mode": "none",
        "baseName": "  Biology  ",
        "baseEmoji": "🧬",
        "baseMode": "none",
    }
    response = client.post(_url("settings", deck_id), data=payload)
    markup = _Markup()
    markup.feed(_elements(response))
    text = "".join(markup.text)
    assert "3 " + s("app_decks_changes_many", lang="en") in text
    assert s("app_decks_lang_none_removes", lang="en") in text
    for field in ("name", "emoji", "lang"):
        assert "hidden" not in markup.ids[f"set-{field}-changed"]
    assert _snapshot(client) == before


@pytest.mark.parametrize("kind", ["create", "settings"])
def test_each_dialog_token_scopes_its_own_preview(
    client: TestClient, kind: str
) -> None:
    deck_id = _seed_deck(client)
    first = _open(client, kind, deck_id)
    second = _open(client, kind, deck_id)
    assert first != second
    first_selectors = _selectors(client.post(_url(kind, deck_id), data=_payload(first)))
    second_selectors = _selectors(
        client.post(_url(kind, deck_id), data=_payload(second))
    )
    assert first_selectors
    assert [
        selector.replace(first, second) for selector in first_selectors
    ] == second_selectors


@pytest.mark.parametrize("kind", ["create", "settings"])
def test_preview_escapes_untrusted_draft(client: TestClient, kind: str) -> None:
    deck_id = _seed_deck(client)
    token = _open(client, kind, deck_id)
    attack = '"><img src=x onerror=alert(1)> & $x'
    before = _snapshot(client)
    response = client.post(
        _url(kind, deck_id), data={**_payload(token), "name": attack}
    )
    fragment = _elements(response)
    markup = _Markup()
    markup.feed(fragment)
    assert response.status_code == 200 and _events(response)
    assert "img" not in markup.tags and "<img src=x" not in fragment
    assert attack in "".join(markup.text)
    assert _snapshot(client) == before


@pytest.mark.parametrize("kind", ["create", "settings"])
@pytest.mark.parametrize(
    "bad", ["", "1", "0" * 15, "0" * 17, "A" * 16, '0"] , * { color:red } /*']
)
def test_malformed_tokens_cannot_construct_selectors(
    client: TestClient, kind: str, bad: str
) -> None:
    deck_id = _seed_deck(client)
    before = _snapshot(client)
    response = client.post(_url(kind, deck_id), data=_payload(bad))
    _assert_empty_sse(response)
    assert _snapshot(client) == before


@pytest.mark.parametrize("kind", ["create", "settings"])
@pytest.mark.parametrize("field", ["token", "name", "emoji", "mode", "src", "dst"])
def test_all_form_fields_are_required(
    client: TestClient, kind: str, field: str
) -> None:
    deck_id = _seed_deck(client)
    payload = _payload(_open(client, kind, deck_id))
    missing_value = payload.pop(field)
    before = _snapshot(client)
    _assert_empty_sse(client.post(_url(kind, deck_id), data=payload))
    _assert_empty_sse(
        client.post(_url(kind, deck_id), params={field: missing_value}, data=payload)
    )
    assert _snapshot(client) == before


@pytest.mark.parametrize("kind", ["create", "settings"])
def test_preview_rejects_file_uploads(client: TestClient, kind: str) -> None:
    deck_id = _seed_deck(client)
    payload = _payload(_open(client, kind, deck_id))
    del payload["name"]
    before = _snapshot(client)
    response = client.post(
        _url(kind, deck_id),
        data=payload,
        files={"name": ("name.txt", b"Biology", "text/plain")},
    )
    _assert_empty_sse(response)
    assert _snapshot(client) == before


@pytest.mark.parametrize("kind", ["create", "settings"])
@pytest.mark.parametrize("field", ["token", "name", "emoji", "mode", "src", "dst"])
def test_duplicate_form_fields_are_rejected(
    client: TestClient, kind: str, field: str
) -> None:
    deck_id = _seed_deck(client)
    payload = _payload(_open(client, kind, deck_id))
    body = urlencode([*payload.items(), (field, payload[field])])
    before = _snapshot(client)
    response = client.post(
        _url(kind, deck_id),
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    _assert_empty_sse(response)
    assert _snapshot(client) == before


@pytest.mark.parametrize("kind", ["create", "settings"])
@pytest.mark.parametrize("field", ["mode", "src", "dst"])
@pytest.mark.parametrize("value", ["bogus", 'de"><img src=x onerror=alert(1)>'])
def test_invalid_language_fields_do_not_enter_markup(
    client: TestClient, kind: str, field: str, value: str
) -> None:
    deck_id = _seed_deck(client)
    token = _open(client, kind, deck_id)
    before = _snapshot(client)
    _assert_empty_sse(
        client.post(_url(kind, deck_id), data={**_payload(token), field: value})
    )
    assert _snapshot(client) == before


@pytest.mark.parametrize("kind", ["create", "settings"])
def test_json_signals_are_not_accepted_as_form_fields(
    client: TestClient, kind: str
) -> None:
    deck_id = _seed_deck(client)
    token = _open(client, kind, deck_id)
    before = _snapshot(client)
    _assert_empty_sse(client.post(_url(kind, deck_id), json=_payload(token)))
    assert _snapshot(client) == before


@pytest.mark.parametrize(
    "deck_id", ["0", "-1", "abc", "1.5", str(2**63), "1%22%5D%20%2A"]
)
def test_invalid_settings_ids_do_not_patch_or_write(
    client: TestClient, deck_id: str
) -> None:
    before = _snapshot(client)
    response = client.post(
        f"/app/decks/{deck_id}/settings/preview", data=_payload("0" * 16)
    )
    _assert_empty_sse(response)
    assert _snapshot(client) == before


def test_missing_settings_deck_does_not_preview_or_write(client: TestClient) -> None:
    before = _snapshot(client)
    response = client.post(_url("settings", 2**53), data=_payload("0" * 16))
    assert response.status_code == 200
    assert "#set-preview" not in response.text
    assert _snapshot(client) == before


@pytest.mark.parametrize("lang", ["en", "de"])
@pytest.mark.parametrize("kind", ["create", "settings"])
def test_language_messages_use_app_locale(tmp_path: Path, lang: str, kind: str) -> None:
    settings = Settings(collection_path=tmp_path / "locale-preview.anki2", lang=lang)
    try:
        with TestClient(create_app(settings)) as client:
            client.headers["Datastar-Request"] = "true"
            deck_id = _seed_deck(client)
            token = _open(client, kind, deck_id)
            response = client.post(
                _url(kind, deck_id), data={**_payload(token), "dst": "de"}
            )
            markup = _Markup()
            markup.feed(_elements(response))
            expected = s(
                "app_decks_lang_same", lang=lang, language=s("app_lang_de", lang=lang)
            )
            assert expected in "".join(markup.text)
            assert _events(response)
    finally:
        anki.lang.set_lang("en")


@pytest.mark.parametrize("kind", ["create", "settings"])
@pytest.mark.parametrize(
    "headers", [{"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}]
)
def test_cross_site_preview_is_rejected(
    client: TestClient, headers: dict[str, str], kind: str
) -> None:
    deck_id = _seed_deck(client)
    token = _open(client, kind, deck_id)
    before = _snapshot(client)
    response = client.post(_url(kind, deck_id), data=_payload(token), headers=headers)
    assert response.status_code == 403
    assert _snapshot(client) == before


@pytest.mark.parametrize("kind", ["create", "settings"])
def test_same_origin_preview_is_allowed_without_mutation(
    client: TestClient, kind: str
) -> None:
    deck_id = _seed_deck(client)
    token = _open(client, kind, deck_id)
    before = _snapshot(client)
    response = client.post(
        _url(kind, deck_id),
        data=_payload(token),
        headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
    )
    assert response.status_code == 200 and _events(response)
    assert _snapshot(client) == before


@pytest.mark.parametrize("kind", ["create", "settings"])
@pytest.mark.parametrize("cookie_state", ["missing", "invalid", "expired"])
def test_preview_requires_authentication(
    tmp_path: Path, cookie_state: str, kind: str
) -> None:
    password = f"test-{tmp_path.name}"
    settings = Settings(
        collection_path=tmp_path / "auth-preview.anki2", password=password
    )
    with TestClient(create_app(settings)) as client:
        client.headers["Datastar-Request"] = "true"
        deck_id = _seed_deck(client)
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
        before = _snapshot(client)
        response = client.post(
            _url(kind, deck_id), data=_payload("0" * 16), follow_redirects=False
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "window.location = '/app/login'" in response.text
        assert _snapshot(client) == before
        client.cookies.set(COOKIE, auth_token(password), domain="testserver.local")
        token = _open(client, kind, deck_id)
        authorized = client.post(_url(kind, deck_id), data=_payload(token))
        assert authorized.status_code == 200 and _events(authorized)
        assert _snapshot(client) == before
