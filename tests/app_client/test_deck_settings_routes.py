import re
from collections.abc import Callable, Iterator
from html import unescape
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
from ankiweb.core.app_client.deck_languages import (
    LanguagePair,
    read_marker,
    strip_marker,
)
from ankiweb.core.app_client.strings import s
from ankiweb.core.auth import COOKIE, auth_token
from ankiweb.core.config import Settings


class _Elements(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.ids: dict[str, dict[str, str | None]] = {}
        self.names: dict[str, list[dict[str, str | None]]] = {}
        self.texts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        values = dict(attrs)
        if values.get("id"):
            self.ids[cast(str, values["id"])] = values
        if values.get("name"):
            self.names.setdefault(cast(str, values["name"]), []).append(values)

    def handle_data(self, data: str) -> None:
        self.texts.append(data)


def _parse(fragment: str) -> _Elements:
    parser = _Elements()
    parser.feed(fragment)
    return parser


def _fragment(response: Response, selector: str) -> str:
    for event in response.text.split("\n\n"):
        if f"data: selector {selector}\n" in event:
            return "\n".join(
                line.removeprefix("data: elements ")
                for line in event.splitlines()
                if line.startswith("data: elements ")
            )
    raise AssertionError(f"No patch for {selector}")


def _run[T](client: TestClient, fn: Callable[[Collection], T]) -> T:
    assert client.portal is not None
    return client.portal.call(cast(FastAPI, client.app).state.service.run, fn)


def _seed(client: TestClient, name: str = "Study") -> int:
    return _run(
        client, lambda col: col.decks.add_normal_deck_with_name(f"{name} · 📚").id
    )


def _stored(client: TestClient, deck_id: int) -> dict | None:
    return _run(client, lambda col: col.decks.get(DeckId(deck_id), default=False))


def _snapshot(client: TestClient) -> tuple:
    def snapshot(col: Collection) -> tuple:
        assert col.db is not None
        return (
            tuple(
                sorted((d["id"], d["name"], d.get("desc", "")) for d in col.decks.all())
            ),
            tuple(col.db.all("select id, did from cards order by id")),
        )

    return _run(client, snapshot)


def _open(
    client: TestClient, deck_id: int, action: str
) -> tuple[Response, str, _Elements]:
    response = client.get(
        f"/app/decks/{deck_id}/{action}",
        headers={"Datastar-Request": "true"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "datastar-patch-signals" not in response.text
    html = _fragment(response, "#deck-dialog-host")
    elements = _parse(html)
    assert "dialog" in elements.tags
    token = elements.ids["deck-dialog"]["data-token"]
    assert token is not None and re.fullmatch(r"[0-9a-f]{16}", token)
    assert any(field.get("value") == token for field in elements.names["token"])
    return response, token, elements


def _payload(
    token: str,
    name: str = "Study",
    *,
    emoji: str = "📚",
    mode: str = "langs",
    src: str = "de",
    dst: str = "es",
) -> dict[str, str]:
    return {
        "token": token,
        "name": name,
        "emoji": emoji,
        "mode": mode,
        "src": src,
        "dst": dst,
    }


def _post(
    client: TestClient, deck_id: int | str, action: str, data: dict[str, str]
) -> Response:
    return client.post(
        f"/app/decks/{deck_id}/{action}",
        data=data,
        headers={"Datastar-Request": "true"},
    )


def _assert_closed(response: Response, token: str) -> None:
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert f'#deck-dialog[data-token="{token}"]' in unescape(response.text)
    assert ".close()" in response.text
    assert "datastar-patch-signals" not in response.text
    assert "#deck-results" not in response.text
    assert "#deck-search-form" not in response.text
    assert "ankiweb:decks-refresh" in response.text
    assert "created:0" in response.text
    assert response.text.index("#toast") < response.text.index(".close()")
    assert response.text.index(".close()") < response.text.index(
        "ankiweb:decks-refresh"
    )


def _assert_error(response: Response, token: str, message: str) -> None:
    assert response.status_code == 200
    assert (
        f'data: selector #deck-dialog[data-token="{token}"] #set-error' in response.text
    )
    assert message in unescape(response.text)
    assert "#deck-results" not in response.text
    assert "#toast" not in response.text
    assert "ankiweb:decks-refresh" not in response.text
    assert "datastar-patch-signals" not in response.text


@pytest.mark.parametrize(
    "name",
    [
        'It\'s "Q" \\ <b>x</b> & $x',
        'a"><img src=x onerror=alert(1)>$z',
    ],
)
def test_hostile_names_are_escaped_in_settings_delete_and_list(
    client: TestClient, name: str
) -> None:
    deck_id = _seed(client, name)
    page = _parse(client.get("/app/").text)
    assert "b" not in page.tags and "img" not in page.tags
    assert name in cast(str, page.ids[f"deck-menu-button-{deck_id}"]["aria-label"])

    opened, token, settings = _open(client, deck_id, "settings")
    assert "b" not in settings.tags and "img" not in settings.tags
    assert any(field.get("value") == name for field in settings.names["name"])
    assert "&lt;" in _fragment(opened, "#deck-dialog-host")
    confirmation, _, delete = _open(client, deck_id, "delete")
    assert "b" not in delete.tags and "img" not in delete.tags
    assert name in "".join(delete.texts)
    assert "&lt;" in _fragment(confirmation, "#deck-dialog-host")
    _, token, _ = _open(client, deck_id, "settings")

    changed = f"{name}!"
    saved = _post(
        client,
        deck_id,
        "settings",
        _payload(token, changed, mode="none", src="", dst=""),
    )
    _assert_closed(saved, token)
    stored = _stored(client, deck_id)
    assert stored is not None and stored["name"] == f"{changed} · 📚"
    result = _parse(
        _fragment(client.get("/app/decks/search", params={"q": ""}), "#deck-results")
    )
    assert "b" not in result.tags and "img" not in result.tags
    assert changed in cast(str, result.ids[f"deck-menu-button-{deck_id}"]["aria-label"])


def test_settings_open_and_save_preserve_description_and_rename_descendants(
    client: TestClient,
) -> None:
    deck_id = _seed(client, "Zebra")
    alpha_id = _seed(client, "Alpha")

    def seed(col: Collection) -> int:
        deck = col.decks.get(DeckId(deck_id), default=False)
        assert deck is not None
        deck["desc"] = "<!--ankiweb:lang=de>es-->Keep <b>description</b>"
        col.decks.update_dict(deck)
        return col.decks.add_normal_deck_with_name("Zebra · 📚::Child").id

    child_id = _run(client, seed)
    _, token, dialog = _open(client, deck_id, "settings")
    assert dialog.ids["deck-settings-form"]
    for field in ("token", "name", "emoji", "mode", "src", "dst"):
        assert field in dialog.names
    assert "q" not in dialog.names
    assert any(field.get("value") == "Zebra" for field in dialog.names["name"])
    assert any(field.get("value") == "📚" for field in dialog.names["emoji"])
    saved = _post(
        client,
        deck_id,
        "settings",
        _payload(token, "Aardvark", emoji="🧬", src="fr", dst="it"),
    )
    _assert_closed(saved, token)
    assert s("app_decks_saved", lang="en") in _fragment(saved, "#toast")
    deck = _stored(client, deck_id)
    child = _stored(client, child_id)
    assert deck is not None and deck["name"] == "Aardvark · 🧬"
    assert read_marker(deck["desc"]) == LanguagePair("fr", "it")
    assert strip_marker(deck["desc"]) == "Keep <b>description</b>"
    assert child is not None and child["name"] == "Aardvark · 🧬::Child"
    results = _parse(
        _fragment(client.get("/app/decks/search", params={"q": ""}), "#deck-results")
    )
    ids = list(results.ids)
    assert ids.index(f"deck-{deck_id}") < ids.index(f"deck-{alpha_id}")

    _, token, _ = _open(client, deck_id, "settings")
    removed = _post(
        client,
        deck_id,
        "settings",
        _payload(token, "Aardvark", emoji="🧬", mode="none", src="", dst=""),
    )
    _assert_closed(removed, token)
    deck = _stored(client, deck_id)
    assert deck is not None and deck["desc"] == "Keep <b>description</b>"


def test_delete_confirmation_counts_descendants_and_removes_cards(
    client: TestClient,
) -> None:
    deck_id = _seed(client)

    def seed(col: Collection) -> tuple[int, int]:
        child = col.decks.add_normal_deck_with_name("Study · 📚::Child").id
        grandchild = col.decks.add_normal_deck_with_name(
            "Study · 📚::Child::Grandchild"
        ).id
        model = col.models.by_name("Basic")
        assert model is not None
        for index, target in enumerate((deck_id, child, grandchild)):
            note = col.new_note(model)
            note["Front"] = f"Card {index}"
            note["Back"] = "Answer"
            col.add_note(note, DeckId(target))
        return child, grandchild

    child, grandchild = _run(client, seed)
    _, token, dialog = _open(client, deck_id, "delete")
    assert s("app_decks_delete_body", lang="en", deck="Study", cards=3) in "".join(
        dialog.texts
    )
    assert "deck-delete-form" in dialog.ids
    assert "q" not in dialog.names
    assert _stored(client, deck_id) is not None
    deleted = _post(client, deck_id, "delete", {"token": token})
    _assert_closed(deleted, token)
    assert s("app_decks_deleted", lang="en") in _fragment(deleted, "#toast")
    assert all(_stored(client, value) is None for value in (deck_id, child, grandchild))
    assert "no-decks" in _parse(client.get("/app/").text).ids

    def count(col: Collection) -> int:
        assert col.db is not None
        return col.db.scalar("select count() from cards")

    assert _run(client, count) == 0


@pytest.mark.parametrize(
    ("mode", "src", "dst", "key", "language"),
    [
        ("langs", "de", "de", "app_decks_lang_same", "German"),
        ("langs", "", "es", "app_decks_lang_missing_src", ""),
        ("langs", "de", "", "app_decks_lang_missing_dst", ""),
        ("langs", "", "", "app_decks_lang_missing_src", ""),
        ("langs", "xx", "es", "app_decks_lang_pick", ""),
        ("wrong", "de", "es", "app_decks_lang_pick", ""),
    ],
)
def test_language_errors_leave_dialog_and_collection_unchanged(
    client: TestClient,
    mode: str,
    src: str,
    dst: str,
    key: str,
    language: str,
) -> None:
    deck_id = _seed(client)
    _, token, _ = _open(client, deck_id, "settings")
    before = _snapshot(client)
    response = _post(
        client, deck_id, "settings", _payload(token, mode=mode, src=src, dst=dst)
    )
    expected = s(key, lang="en", **({"language": language} if language else {}))
    _assert_error(response, token, expected)
    assert _snapshot(client) == before


@pytest.mark.parametrize(
    ("name", "emoji", "kind"),
    [
        ("", "📚", "empty"),
        ("x" * 41, "📚", "too_long"),
        ("Parent::Child", "📚", "invalid"),
        ("Study", "invalid", "invalid"),
        ("Other", "📚", "taken"),
    ],
)
def test_invalid_names_and_emoji_do_not_write(
    client: TestClient,
    name: str,
    emoji: str,
    kind: str,
) -> None:
    deck_id = _seed(client)
    _seed(client, "Other")
    _, token, _ = _open(client, deck_id, "settings")
    before = _snapshot(client)
    response = _post(client, deck_id, "settings", _payload(token, name, emoji=emoji))
    _assert_error(response, token, s(f"app_decks_name_{kind}", lang="en"))
    assert _snapshot(client) == before


@pytest.mark.parametrize("field", ["name", "emoji", "mode", "src", "dst"])
def test_missing_settings_fields_are_not_defaulted(
    client: TestClient, field: str
) -> None:
    deck_id = _seed(client)
    _, token, _ = _open(client, deck_id, "settings")
    payload = _payload(token, "Changed")
    del payload[field]
    before = _snapshot(client)
    response = _post(client, deck_id, "settings", payload)
    assert response.status_code == 200 and response.content == b""
    assert _snapshot(client) == before


@pytest.mark.parametrize("action", ["settings", "delete"])
@pytest.mark.parametrize(
    "token",
    ["", "abc", "0" * 15, "0" * 17, "A" * 16, '1234567890123456"] #toast, #x["'],
)
def test_invalid_or_missing_dialog_token_cannot_mutate(
    client: TestClient,
    action: str,
    token: str,
) -> None:
    deck_id = _seed(client)
    _open(client, deck_id, action)
    before = _snapshot(client)
    data = _payload(token, "Changed") if action == "settings" else {"token": token}
    for payload in (
        data,
        {key: value for key, value in data.items() if key != "token"},
    ):
        response = _post(client, deck_id, action, payload)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.content == b""
        assert _snapshot(client) == before


def test_reopened_dialogs_have_distinct_tokens_and_late_patches_stay_scoped(
    client: TestClient,
) -> None:
    deck_id = _seed(client)
    _, first, _ = _open(client, deck_id, "settings")
    _, second, _ = _open(client, deck_id, "settings")
    assert first != second
    error = _post(client, deck_id, "settings", _payload(first, ""))
    _assert_error(error, first, s("app_decks_name_empty", lang="en"))
    assert second not in error.text
    saved = _post(client, deck_id, "settings", _payload(first, "Changed"))
    _assert_closed(saved, first)
    assert second not in unescape(saved.text)


@pytest.mark.parametrize("action", ["settings", "delete"])
def test_json_signal_payloads_are_not_accepted_as_native_forms(
    client: TestClient, action: str
) -> None:
    deck_id = _seed(client)
    _, token, _ = _open(client, deck_id, action)
    before = _snapshot(client)
    data = _payload(token, "Changed") if action == "settings" else {"token": token}
    response = client.post(
        f"/app/decks/{deck_id}/{action}",
        json=data,
        headers={"Datastar-Request": "true"},
    )
    assert response.status_code == 200
    assert _snapshot(client) == before
    assert "#deck-results" not in response.text
    assert ".close()" not in response.text


@pytest.mark.parametrize("action", ["settings", "delete"])
def test_form_posts_reject_duplicate_fields_query_fallback_and_uploads(
    client: TestClient,
    action: str,
) -> None:
    deck_id = _seed(client)
    _, token, _ = _open(client, deck_id, action)
    payload = _payload(token, "Changed") if action == "settings" else {"token": token}
    path = f"/app/decks/{deck_id}/{action}"
    before = _snapshot(client)
    headers = {"Datastar-Request": "true"}

    for field in payload:
        body = urlencode([*payload.items(), (field, payload[field])])
        response = client.post(
            path,
            content=body,
            headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 200 and response.content == b""
        assert _snapshot(client) == before

    for field in payload:
        body = {key: value for key, value in payload.items() if key != field}
        response = client.post(
            path, params={field: payload[field]}, data=body, headers=headers
        )
        assert response.status_code == 200 and response.content == b""
        assert _snapshot(client) == before

    response = client.post(
        path,
        data=payload,
        files={"attachment": ("deck.txt", b"data", "text/plain")},
        headers=headers,
    )
    assert response.status_code == 200 and response.content == b""
    assert _snapshot(client) == before

    for content_type, body in (
        ("text/plain", urlencode(payload)),
        ("multipart/form-data", "malformed"),
    ):
        response = client.post(
            path, content=body, headers={**headers, "Content-Type": content_type}
        )
        assert response.status_code == 200 and response.content == b""
        assert _snapshot(client) == before


def test_missing_child_filtered_and_protected_roots_are_rejected(
    client: TestClient,
) -> None:
    root = _seed(client)

    def seed(col: Collection) -> tuple[int, int]:
        child = col.decks.add_normal_deck_with_name("Study · 📚::Child").id
        model = col.models.by_name("Basic")
        assert model is not None
        note = col.new_note(model)
        note["Front"] = "Filtered card"
        note["Back"] = "Answer"
        col.add_note(note, DeckId(root))
        filtered = col.sched.get_or_create_filtered_deck(deck_id=DeckId(0))
        filtered.name = "Filtered"
        filtered.config.search_terms[0].search = 'deck:"Study · 📚"'
        return child, col.sched.add_or_update_filtered_deck(filtered).id

    child, filtered = _run(client, seed)
    _, settings_token, _ = _open(client, root, "settings")
    _, delete_token, _ = _open(client, root, "delete")
    before = _snapshot(client)
    for deck_id in (
        "0",
        "-1",
        "invalid",
        "9" * 100,
        str(2**63),
        "\uff11\uff12",
        "987654321",
        str(child),
        str(filtered),
    ):
        for action in ("settings", "delete"):
            opened = client.get(
                f"/app/decks/{deck_id}/{action}", headers={"Datastar-Request": "true"}
            )
            assert s("app_decks_not_found", lang="en") in _fragment(opened, "#toast")
            assert "#deck-dialog-host" not in opened.text
        saved = _post(client, deck_id, "settings", _payload(settings_token, "Changed"))
        _assert_error(saved, settings_token, s("app_decks_not_found", lang="en"))
        deleted = _post(client, deck_id, "delete", {"token": delete_token})
        assert s("app_decks_not_found", lang="en") in unescape(deleted.text)
        assert "#deck-results" not in deleted.text
        assert _snapshot(client) == before
    _, _, default_settings = _open(client, 1, "settings")
    assert "deck-settings-form" in default_settings.ids
    opened = client.get("/app/decks/1/delete", headers={"Datastar-Request": "true"})
    assert s("app_decks_protected", lang="en") in _fragment(opened, "#toast")
    deleted = _post(client, 1, "delete", {"token": delete_token})
    assert s("app_decks_protected", lang="en") in unescape(deleted.text)
    assert "#deck-results" not in deleted.text
    assert _snapshot(client) == before


def test_save_and_delete_refresh_the_current_filtered_results(
    client: TestClient,
) -> None:
    renamed = _seed(client, "Removed")
    remaining = _seed(client, "Remaining")
    _, token, _ = _open(client, renamed, "settings")
    saved = _post(
        client,
        renamed,
        "settings",
        _payload(token, "Changed", mode="none", src="", dst=""),
    )
    _assert_closed(saved, token)
    result = _parse(
        _fragment(
            client.get("/app/decks/search", params={"q": "removed"}), "#deck-results"
        )
    )
    assert f"deck-{renamed}" not in result.ids and f"deck-{remaining}" not in result.ids
    assert "empty-state" in result.ids

    _, token, _ = _open(client, renamed, "delete")
    deleted = _post(client, renamed, "delete", {"token": token})
    _assert_closed(deleted, token)
    result = _parse(
        _fragment(
            client.get("/app/decks/search", params={"q": "remaining"}), "#deck-results"
        )
    )
    assert f"deck-{remaining}" in result.ids and f"deck-{renamed}" not in result.ids


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
    ],
)
def test_origin_guard_covers_both_writes_and_allows_safe_gets(
    client: TestClient,
    headers: dict[str, str],
) -> None:
    deck_id = _seed(client)
    _, settings_token, _ = _open(client, deck_id, "settings")
    _, delete_token, _ = _open(client, deck_id, "delete")
    before = _snapshot(client)
    for action, payload in (
        ("settings", _payload(settings_token, "Attack")),
        ("delete", {"token": delete_token}),
    ):
        response = client.post(
            f"/app/decks/{deck_id}/{action}", data=payload, headers=headers
        )
        assert response.status_code == 403
        assert _snapshot(client) == before
        opened = client.get(f"/app/decks/{deck_id}/{action}", headers=headers)
        assert opened.status_code == 200
        _fragment(opened, "#deck-dialog-host")


def test_password_gate_covers_every_settings_and_delete_route(tmp_path: Path) -> None:
    password = f"test-{tmp_path.name}"
    settings = Settings(
        collection_path=tmp_path / "auth-decks.anki2", password=password
    )
    with TestClient(create_app(settings)) as client:
        deck_id = _seed(client)
        before = _snapshot(client)
        requests = (
            ("GET", "settings"),
            ("POST", "settings"),
            ("GET", "delete"),
            ("POST", "delete"),
        )
        for method, action in requests:
            path = f"/app/decks/{deck_id}/{action}"
            data = (
                _payload("0" * 16, "Changed")
                if action == "settings"
                else {"token": "0" * 16}
            )
            response = client.request(
                method,
                path,
                data=data if method == "POST" else None,
                headers={"Datastar-Request": "true"},
                follow_redirects=False,
            )
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert "window.location = '/app/login'" in response.text
            response = client.request(
                method,
                path,
                data=data if method == "POST" else None,
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert response.headers["location"] == "/app/login"
            assert _snapshot(client) == before
        client.cookies.set(COOKIE, auth_token(password))
        _, token, _ = _open(client, deck_id, "settings")
        saved = _post(client, deck_id, "settings", _payload(token, "Changed"))
        _assert_closed(saved, token)
        stored = _stored(client, deck_id)
        assert stored is not None and stored["name"] == "Changed · 📚"


@pytest.fixture
def reset_anki_language() -> Iterator[None]:
    yield
    anki.lang.set_lang("en")


@pytest.mark.parametrize("locale", ["en", "de"])
def test_messages_and_errors_are_localized(
    tmp_path: Path, locale: str, reset_anki_language: None
) -> None:
    settings = Settings(collection_path=tmp_path / f"{locale}.anki2", lang=locale)
    with TestClient(create_app(settings)) as client:
        deck_id = _seed(client)
        _, token, _ = _open(client, deck_id, "settings")
        expected = s(
            "app_decks_lang_same", lang=locale, language=s("app_lang_de", lang=locale)
        )
        error = _post(client, deck_id, "settings", _payload(token, src="de", dst="de"))
        _assert_error(error, token, expected)
        saved = _post(client, deck_id, "settings", _payload(token, "Changed"))
        assert s("app_decks_saved", lang=locale) in _fragment(saved, "#toast")
        _, token, _ = _open(client, deck_id, "delete")
        deleted = _post(client, deck_id, "delete", {"token": token})
        assert s("app_decks_deleted", lang=locale) in _fragment(deleted, "#toast")
        missing = client.get(
            f"/app/decks/{deck_id}/settings", headers={"Datastar-Request": "true"}
        )
        assert s("app_decks_not_found", lang=locale) in _fragment(missing, "#toast")


def test_save_and_delete_broadcast_as_app_operations(client: TestClient) -> None:
    deck_id = _seed(client)
    broadcasts: list[tuple[dict, str | None]] = []
    cast(FastAPI, client.app).state.service.subscribe(
        lambda flags, initiator: broadcasts.append((flags, initiator))
    )
    _, token, _ = _open(client, deck_id, "settings")
    saved = _post(client, deck_id, "settings", _payload(token, "Renamed"))
    _assert_closed(saved, token)
    assert any(initiator == "app" and flags["deck"] for flags, initiator in broadcasts)
    broadcasts.clear()
    _, token, _ = _open(client, deck_id, "delete")
    deleted = _post(client, deck_id, "delete", {"token": token})
    _assert_closed(deleted, token)
    assert any(initiator == "app" and flags["deck"] for flags, initiator in broadcasts)


def test_repeated_toasts_have_fresh_children(client: TestClient) -> None:
    deck_id = _seed(client)
    toast_ids: list[str] = []
    for name in ("First", "Second"):
        _, token, _ = _open(client, deck_id, "settings")
        response = _post(client, deck_id, "settings", _payload(token, name))
        toast = _parse(_fragment(response, "#toast"))
        assert s("app_decks_saved", lang="en") in "".join(toast.texts)
        assert toast.ids["toast"]["role"] == "status"
        assert toast.ids["toast"]["aria-live"] == "polite"
        (child,) = [
            element_id
            for element_id in toast.ids
            if element_id.startswith("deck-toast-")
        ]
        toast_ids.append(child)
    assert toast_ids[0] != toast_ids[1]

    deleted_toasts: list[str] = []
    for target in (deck_id, _seed(client, "Extra")):
        _, token, _ = _open(client, target, "delete")
        response = _post(client, target, "delete", {"token": token})
        toast = _parse(_fragment(response, "#toast"))
        assert s("app_decks_deleted", lang="en") in "".join(toast.texts)
        (child,) = [
            element_id
            for element_id in toast.ids
            if element_id.startswith("deck-toast-")
        ]
        deleted_toasts.append(child)
    assert deleted_toasts[0] != deleted_toasts[1]
