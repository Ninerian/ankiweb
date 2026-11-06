import json
from collections.abc import Callable, Iterator
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal, Protocol, cast

import anki.lang
import pytest
from anki.collection import Collection
from anki.decks import DeckId
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ankiweb.app import create_app
from ankiweb.core.app_client.deck_languages import (
    LanguagePair,
    read_marker,
    strip_marker,
)
from ankiweb.core.app_client.strings import s
from ankiweb.core.auth import COOKIE, auth_token
from ankiweb.core.config import Settings


class _TextResponse(Protocol):
    @property
    def text(self) -> str: ...


class _Elements(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.ids: dict[str, dict[str, str | None]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        values = dict(attrs)
        if values.get("id"):
            self.ids[cast(str, values["id"])] = values


def _fragment(response: _TextResponse, selector: str) -> str:
    for event in response.text.split("\n\n"):
        if f"data: selector {selector}\n" in event:
            return "\n".join(
                line.removeprefix("data: elements ")
                for line in event.splitlines()
                if line.startswith("data: elements ")
            )
    raise AssertionError(f"No patch for {selector}")


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


def _parse(fragment: str) -> _Elements:
    parser = _Elements()
    parser.feed(fragment)
    return parser


@pytest.mark.parametrize(
    "name",
    [
        'It\'s "Q" \\ <b>x</b> & $x',
        'a"><img src=x onerror=alert(1)>$z',
    ],
)
def test_user_names_are_safe_in_list_settings_delete_and_signals(
    client: TestClient, name: str
) -> None:
    client.headers["Datastar-Request"] = "true"
    before = _decks(client)
    create = client.post(
        "/app/decks",
        json={
            "newName": name,
            "newEmoji": "📚",
            "newMode": "none",
            "newSrc": "",
            "newDst": "",
        },
    )
    assert create.status_code == 200
    created = {key: value for key, value in _decks(client).items() if key not in before}
    assert list(created.values()) == [f"{name} · 📚"]
    (deck_id,) = created

    def assert_list_safe(response: _TextResponse, expected: str) -> None:
        fragment = _fragment(response, "#decks-content")
        elements = _parse(fragment)
        assert "b" not in elements.tags and "img" not in elements.tags
        row = elements.ids[f"deck-{deck_id}"]
        expression = cast(str, row["data-show"])
        literal, _ = json.JSONDecoder().raw_decode(expression)
        assert literal == expected.lower()
        assert "\\u0024" in expression
        assert "\\u003c" in expression
        assert expected in cast(
            str, elements.ids[f"deck-menu-button-{deck_id}"]["aria-label"]
        )
        empty = cast(str, elements.ids["empty-state"]["data-show"])
        names, _ = json.JSONDecoder().raw_decode(empty.split("&& !", 1)[1])
        assert expected.lower() in names

    assert_list_safe(create, name)
    settings = client.get(f"/app/decks/{deck_id}/settings")
    assert settings.status_code == 200
    fragment = _fragment(settings, "#deck-settings-body")
    elements = _parse(fragment)
    assert "b" not in elements.tags and "img" not in elements.tags
    assert elements.ids["set-name"]["value"] == name
    data_signals = cast(str, elements.ids["deck-settings-body"]["data-signals"])
    encoded = data_signals.split("setName: ", 1)[1]
    decoded, _ = json.JSONDecoder().raw_decode(encoded)
    assert decoded == name
    assert "\\u0024" in encoded and "\\u003c" in encoded
    if "&" in name:
        assert "\\u0026" in encoded
    signals = _signals(settings)
    assert signals["setName"] == name and signals["baseName"] == name

    confirm = client.get(f"/app/decks/{deck_id}/delete")
    assert confirm.status_code == 200
    delete_html = _fragment(confirm, "#deck-delete-body")
    parsed_delete = _parse(delete_html)
    assert "b" not in parsed_delete.tags and "img" not in parsed_delete.tags
    assert "&lt;" in delete_html and "&gt;" in delete_html

    changed = f"{name}!"
    save = client.post(
        f"/app/decks/{deck_id}/settings",
        json={
            "setName": changed,
            "setEmoji": "📚",
            "setMode": "none",
            "setSrc": "",
            "setDst": "",
        },
    )
    assert save.status_code == 200
    assert _decks(client)[deck_id] == f"{changed} · 📚"
    assert_list_safe(save, changed)


def _run[T](client: TestClient, fn: Callable[[Collection], T]) -> T:
    assert client.portal is not None
    return client.portal.call(cast(FastAPI, client.app).state.service.run, fn)


def _create_payload(
    name: str = "Study", mode: str = "langs", src: str = "de", dst: str = "es"
) -> dict[str, str]:
    return {
        "newName": name,
        "newEmoji": "📚",
        "newMode": mode,
        "newSrc": src,
        "newDst": dst,
    }


def _settings_payload(
    name: str = "Study", mode: str = "langs", src: str = "de", dst: str = "es"
) -> dict[str, str]:
    return {
        "setName": name,
        "setEmoji": "📚",
        "setMode": mode,
        "setSrc": src,
        "setDst": dst,
    }


def _create(client: TestClient, name: str = "Study") -> int:
    client.headers["Datastar-Request"] = "true"
    before = _decks(client)
    response = client.post("/app/decks", json=_create_payload(name))
    assert response.status_code == 200 and "#decks-content" in response.text
    added = set(_decks(client)) - set(before)
    assert len(added) == 1
    return added.pop()


def _stored(client: TestClient, deck_id: int) -> dict | None:
    return _run(client, lambda col: col.decks.get(DeckId(deck_id), default=False))


def _snapshot(client: TestClient) -> tuple:
    def snapshot(col: Collection) -> tuple:
        assert col.db is not None
        return (
            tuple(
                sorted(
                    (deck["id"], deck["name"], deck.get("desc", ""))
                    for deck in col.decks.all()
                )
            ),
            tuple(col.db.all("select id, did from cards order by id")),
        )

    return _run(client, snapshot)


@pytest.mark.parametrize(
    ("mode", "src", "dst", "pair"),
    [
        ("langs", "de", "es", LanguagePair("de", "es")),
        ("none", "", "", None),
    ],
)
def test_creation_persists_language_selection(
    client: TestClient, mode: str, src: str, dst: str, pair: LanguagePair | None
) -> None:
    client.headers["Datastar-Request"] = "true"
    before = _decks(client)
    response = client.post(
        "/app/decks", json=_create_payload(mode=mode, src=src, dst=dst)
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    (deck_id,) = set(_decks(client)) - set(before)
    stored = _stored(client, deck_id)
    assert stored is not None
    assert read_marker(stored["desc"]) == pair
    assert strip_marker(stored["desc"]) == ""
    assert 'id="deck-' + str(deck_id) + '"' in _fragment(response, "#decks-content")
    assert _signals(response) == {
        "q": "",
        "newName": "",
        "newEmoji": "📚",
        "newMode": "langs",
        "newSrc": "",
        "newDst": "",
        "newError": "",
        "newOpen": False,
    }
    assert s("app_decks_created", lang="en") in _fragment(response, "#toast")


def test_settings_reads_and_atomically_updates_deck_and_search(
    client: TestClient,
) -> None:
    deck_id = _create(client, "Zebra")
    _create(client, "Alpha")

    def seed(col: Collection) -> int:
        deck = col.decks.get(DeckId(deck_id), default=False)
        assert deck is not None
        deck["desc"] = "<!--ankiweb:lang=de>es-->Keep <b>description</b>"
        col.decks.update_dict(deck)
        return col.decks.add_normal_deck_with_name("Zebra · 📚::Child").id

    child_id = _run(client, seed)
    response = client.get(f"/app/decks/{deck_id}/settings")
    assert response.status_code == 200
    body = _fragment(response, "#deck-settings-body")
    assert f"/app/decks/{deck_id}/settings" in body
    signals = _signals(response)
    assert signals == {
        "setId": deck_id,
        "setName": "Zebra",
        "setEmoji": "📚",
        "setMode": "langs",
        "setSrc": "de",
        "setDst": "es",
        "baseName": "Zebra",
        "baseEmoji": "📚",
        "baseMode": "langs",
        "baseSrc": "de",
        "baseDst": "es",
        "setEmojiGroup": "study",
        "saving": False,
        "setError": "",
        "setOpen": True,
    }
    payload = _settings_payload("Aardvark", "langs", "fr", "it")
    payload["setEmoji"] = "🧬"
    saved = client.post(f"/app/decks/{deck_id}/settings", json=payload)
    assert saved.status_code == 200
    assert _signals(saved) == {"setError": "", "setOpen": False}
    assert s("app_decks_saved", lang="en") in _fragment(saved, "#toast")
    deck = _stored(client, deck_id)
    child = _stored(client, child_id)
    assert deck is not None and deck["name"] == "Aardvark · 🧬"
    assert read_marker(deck["desc"]) == LanguagePair("fr", "it")
    assert strip_marker(deck["desc"]) == "Keep <b>description</b>"
    assert child is not None and child["name"] == "Aardvark · 🧬::Child"
    content = _fragment(saved, "#decks-content")
    parsed = _parse(content)
    no_match = cast(str, parsed.ids["empty-state"]["data-show"])
    names, _ = json.JSONDecoder().raw_decode(no_match.split("&& !", 1)[1])
    assert names == ["aardvark", "alpha"]
    assert "zebra" not in no_match
    assert "q" not in _signals(saved)

    remove_pair = client.post(
        f"/app/decks/{deck_id}/settings",
        json={**_settings_payload("Aardvark", "none", "", ""), "setEmoji": "🧬"},
    )
    assert _signals(remove_pair)["setOpen"] is False
    deck = _stored(client, deck_id)
    assert deck is not None and deck["desc"] == "Keep <b>description</b>"


def test_delete_confirmation_counts_descendants_then_renders_empty_state(
    client: TestClient,
) -> None:
    deck_id = _create(client)

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

    child_id, grandchild_id = _run(client, seed)
    confirmation = client.get(f"/app/decks/{deck_id}/delete")
    assert confirmation.status_code == 200
    body = _fragment(confirmation, "#deck-delete-body")
    assert s("app_decks_delete_body", lang="en", deck="Study", cards=3) in body
    assert _signals(confirmation) == {"delOpen": True}
    assert _stored(client, deck_id) is not None
    deleted = client.post(f"/app/decks/{deck_id}/delete")
    assert deleted.status_code == 200
    assert _signals(deleted) == {"delOpen": False}
    assert s("app_decks_deleted", lang="en") in _fragment(deleted, "#toast")
    assert 'id="no-decks"' in _fragment(deleted, "#decks-content")
    assert all(
        _stored(client, value) is None for value in (deck_id, child_id, grandchild_id)
    )

    def card_count(col: Collection) -> int:
        assert col.db is not None
        return col.db.scalar("select count() from cards")

    assert _run(client, card_count) == 0


@pytest.mark.parametrize("operation", ["create", "settings"])
def test_all_consumed_signal_types_are_strict_and_invalid_json_is_safe(
    client: TestClient, operation: str
) -> None:
    deck_id = _create(client)
    before = _snapshot(client)
    prefix = "new" if operation == "create" else "set"
    path = "/app/decks" if operation == "create" else f"/app/decks/{deck_id}/settings"
    base = _create_payload("Other") if operation == "create" else _settings_payload()
    expected = {f"{prefix}Error": s("app_decks_name_invalid", lang="en")}
    for suffix in ("Name", "Emoji", "Mode", "Src", "Dst"):
        field = prefix + suffix
        for invalid in (None, 42, True, [], {}):
            payload = {**base, field: invalid}
            response = client.post(path, json=payload)
            assert response.status_code == 200
            assert _signals(response) == expected
            assert "datastar-patch-elements" not in response.text
            assert _snapshot(client) == before
        payload = dict(base)
        del payload[field]
        assert _signals(client.post(path, json=payload)) == expected
        assert _snapshot(client) == before
    for value in ([], None, "text", 7):
        response = client.post(path, json=value)
        assert response.status_code == 200 and _signals(response) == expected
        assert _snapshot(client) == before
    malformed = client.post(
        path, content=b"{", headers={"Content-Type": "application/json"}
    )
    assert malformed.status_code == 200 and _signals(malformed) == expected
    assert _snapshot(client) == before


@pytest.mark.parametrize("operation", ["create", "settings"])
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
    operation: str,
    mode: str,
    src: str,
    dst: str,
    key: str,
    language: str,
) -> None:
    deck_id = _create(client)
    before = _snapshot(client)
    path = "/app/decks" if operation == "create" else f"/app/decks/{deck_id}/settings"
    payload = (
        _create_payload("Other", mode, src, dst)
        if operation == "create"
        else _settings_payload("Study", mode, src, dst)
    )
    response = client.post(path, json=payload)
    expected = s(key, lang="en", **({"language": language} if language else {}))
    assert response.status_code == 200
    assert _signals(response) == {
        ("newError" if operation == "create" else "setError"): expected
    }
    assert "datastar-patch-elements" not in response.text
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
def test_settings_name_and_emoji_errors_do_not_write(
    client: TestClient, name: str, emoji: str, kind: str
) -> None:
    deck_id = _create(client)
    _create(client, "Other")
    before = _snapshot(client)
    response = client.post(
        f"/app/decks/{deck_id}/settings",
        json={**_settings_payload(name), "setEmoji": emoji},
    )
    assert _signals(response) == {"setError": s(f"app_decks_name_{kind}", lang="en")}
    assert "datastar-patch-elements" not in response.text
    assert _snapshot(client) == before


def test_missing_child_filtered_and_protected_roots_are_rejected(
    client: TestClient,
) -> None:
    root = _create(client)

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
    before = _snapshot(client)
    for deck_id in (
        "0",
        "-1",
        "invalid",
        "9" * 100,
        "987654321",
        str(child),
        str(filtered),
    ):
        for action in ("settings", "delete"):
            response = client.get(f"/app/decks/{deck_id}/{action}")
            assert response.status_code == 200
            assert s("app_decks_not_found", lang="en") in _fragment(response, "#toast")
            assert f"#deck-{action}-body" not in response.text
        response = client.post(
            f"/app/decks/{deck_id}/settings", json=_settings_payload("Renamed")
        )
        assert _signals(response) == {"setError": s("app_decks_not_found", lang="en")}
        response = client.post(f"/app/decks/{deck_id}/delete")
        assert s("app_decks_not_found", lang="en") in _fragment(response, "#toast")
        assert _snapshot(client) == before
    for method in (client.get, client.post):
        response = method("/app/decks/1/delete")
        assert response.status_code == 200
        assert s("app_decks_protected", lang="en") in _fragment(response, "#toast")
        assert "#decks-content" not in response.text
        assert _snapshot(client) == before
    assert _stored(client, root) is not None


def test_deleting_one_deck_recomputes_search_without_resetting_query(
    client: TestClient,
) -> None:
    removed = _create(client, "Removed")
    remaining = _create(client, "Remaining")
    response = client.post(f"/app/decks/{removed}/delete")
    content = _fragment(response, "#decks-content")
    parsed = _parse(content)
    assert f"deck-{removed}" not in parsed.ids
    assert f"deck-{remaining}" in parsed.ids
    expression = cast(str, parsed.ids["empty-state"]["data-show"])
    names, _ = json.JSONDecoder().raw_decode(expression.split("&& !", 1)[1])
    assert names == ["remaining"]
    assert _signals(response) == {"delOpen": False}


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
    ],
)
def test_foreign_origins_cannot_create_update_or_delete(
    client: TestClient, headers: dict[str, str]
) -> None:
    deck_id = _create(client)
    before = _snapshot(client)
    for path, payload in (
        ("/app/decks", _create_payload("Attack")),
        (f"/app/decks/{deck_id}/settings", _settings_payload("Attack")),
        (f"/app/decks/{deck_id}/delete", {}),
    ):
        response = client.post(path, json=payload, headers=headers)
        assert response.status_code == 403
        assert _snapshot(client) == before


def test_password_gate_covers_all_deck_dialog_routes(tmp_path: Path) -> None:
    password = f"test-{tmp_path.name}"
    settings = Settings(
        collection_path=tmp_path / "auth-decks.anki2", password=password
    )
    with TestClient(create_app(settings)) as client:
        deck_id = _run(
            client, lambda col: col.decks.add_normal_deck_with_name("Study").id
        )
        before = _snapshot(client)
        requests = (
            ("GET", f"/app/decks/{deck_id}/settings", None),
            ("POST", f"/app/decks/{deck_id}/settings", _settings_payload("Changed")),
            ("GET", f"/app/decks/{deck_id}/delete", None),
            ("POST", f"/app/decks/{deck_id}/delete", None),
            ("POST", "/app/decks", _create_payload("Other")),
        )
        for method, path, payload in requests:
            response = client.request(
                method,
                path,
                json=payload,
                headers={"Datastar-Request": "true"},
                follow_redirects=False,
            )
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert "window.location = '/app/login'" in response.text
            response = client.request(
                method, path, json=payload, follow_redirects=False
            )
            assert response.status_code == 303
            assert response.headers["location"] == "/app/login"
            assert _snapshot(client) == before
        client.cookies.set(COOKIE, auth_token(password))
        client.headers["Datastar-Request"] = "true"
        response = client.get(f"/app/decks/{deck_id}/settings")
        assert _signals(response)["setOpen"] is True
        response = client.post(
            f"/app/decks/{deck_id}/settings", json=_settings_payload("Changed")
        )
        assert _signals(response)["setOpen"] is False
        stored = _stored(client, deck_id)
        assert stored is not None and stored["name"] == "Changed · 📚"


@pytest.fixture
def reset_anki_language() -> Iterator[None]:
    yield
    anki.lang.set_lang("en")


@pytest.mark.parametrize("locale", ["en", "de"])
def test_dynamic_language_messages_and_errors_are_localized(
    tmp_path: Path, locale: str, reset_anki_language: None
) -> None:
    settings = Settings(collection_path=tmp_path / f"{locale}.anki2", lang=locale)
    with TestClient(create_app(settings)) as client:
        deck_id = _create(client)
        html = unescape(
            _fragment(
                client.get(f"/app/decks/{deck_id}/settings"), "#deck-settings-body"
            )
        )
        sentence = s("app_decks_lang_same", lang=locale, language="\x1f")
        before, after = sentence.split("\x1f")
        start = html.index(before)
        end = html.index(after, start + len(before))
        assert "data-text=" in html[start:end]
        assert f'"de": "{s("app_lang_de", lang=locale)}"' in html[start:end]
        expected = s(
            "app_decks_lang_same",
            lang=locale,
            language=s("app_lang_de", lang=locale),
        )
        for path, payload, signal in (
            ("/app/decks", _create_payload("Other", "langs", "de", "de"), "newError"),
            (
                f"/app/decks/{deck_id}/settings",
                _settings_payload("Study", "langs", "de", "de"),
                "setError",
            ),
        ):
            response = client.post(path, json=payload)
            assert _signals(response) == {signal: expected}


def test_mutations_broadcast_as_app_operations(client: TestClient) -> None:
    broadcasts: list[tuple[dict, str | None]] = []
    cast(FastAPI, client.app).state.service.subscribe(
        lambda flags, initiator: broadcasts.append((flags, initiator))
    )
    deck_id = _create(client)
    assert any(initiator == "app" and flags["deck"] for flags, initiator in broadcasts)
    broadcasts.clear()
    response = client.post(
        f"/app/decks/{deck_id}/settings", json=_settings_payload("Renamed")
    )
    assert _signals(response)["setOpen"] is False
    assert any(initiator == "app" and flags["deck"] for flags, initiator in broadcasts)
    broadcasts.clear()
    response = client.post(f"/app/decks/{deck_id}/delete")
    assert _signals(response)["delOpen"] is False
    assert any(initiator == "app" and flags["deck"] for flags, initiator in broadcasts)


@pytest.mark.parametrize("motion", ["reduce", "no-preference"])
def test_repeated_deck_toasts_remain_visible(
    live_app: str, motion: Literal["reduce", "no-preference"]
) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            context = browser.new_context(
                locale="en-US",
                reduced_motion=motion,
                viewport={"width": 375, "height": 812},
            )
            page = context.new_page()
            page.goto(f"{live_app}/app/")
            page.wait_for_load_state("networkidle")
            active_page = page

            def open_menu(name: str, action: str) -> None:
                active_page.get_by_role(
                    "button", name=s("app_decks_menu_open", lang="en", deck=name)
                ).click()
                active_page.get_by_role(
                    "menuitem", name=s(action, lang="en"), exact=True
                ).click()

            def consume_toast(key: str) -> None:
                region = active_page.locator("#toast")
                toast = region.get_by_text(s(key, lang="en"), exact=True)
                playwright.expect(region).to_have_attribute("role", "status")
                playwright.expect(region).to_have_attribute("aria-live", "polite")
                playwright.expect(toast).to_be_visible()
                # Advance the real toast's animation before the next operation.
                toast.evaluate(
                    "(el) => el.getAnimations().forEach((animation) => animation.finish())"
                )
                if motion == "reduce":
                    playwright.expect(toast).to_be_hidden()
                else:
                    playwright.expect(toast).to_be_visible()

            create_sheet = page.locator("#deck-sheet")
            create_name = page.locator("#deck-name")
            for deck_name in ("Toast deck", "Toast extra"):
                page.locator("#btn-new-deck").click()
                playwright.expect(create_sheet).to_have_attribute(
                    "aria-hidden", "false"
                )
                playwright.expect(create_name).to_be_focused()
                create_name.fill(deck_name)
                create_sheet.get_by_role("radio", name="No languages").check()
                playwright.expect(page.locator("#btn-create-deck")).to_be_enabled()
                page.locator("#btn-create-deck").click()
                playwright.expect(create_sheet).to_have_attribute("aria-hidden", "true")
                playwright.expect(
                    page.get_by_role("heading", name=deck_name, level=3)
                ).to_be_visible()
                consume_toast("app_decks_created")

            for old_name, new_name in (
                ("Toast deck", "Toast one"),
                ("Toast one", "Toast two"),
            ):
                open_menu(old_name, "app_decks_settings")
                sheet = page.locator("#deck-settings-sheet")
                name = sheet.locator("#set-name")
                save = sheet.locator("#deck-settings-save")
                playwright.expect(sheet).to_have_attribute("aria-hidden", "false")
                playwright.expect(name).to_have_value(old_name)
                playwright.expect(name).to_be_focused()
                name.fill(new_name)
                playwright.expect(save).to_be_enabled()
                save.click()
                playwright.expect(sheet).to_have_attribute("aria-hidden", "true")
                playwright.expect(
                    page.get_by_role("heading", name=new_name, level=3)
                ).to_be_visible()
                consume_toast("app_decks_saved")

            stale_page = context.new_page()
            stale_page.goto(f"{live_app}/app/")
            stale_page.wait_for_load_state("networkidle")

            for deck_name in ("Toast two", "Toast extra"):
                open_menu(deck_name, "app_decks_delete")
                delete_sheet = page.locator("#deck-delete-sheet")
                playwright.expect(delete_sheet).to_have_attribute(
                    "aria-hidden", "false"
                )
                delete_sheet.locator("#deck-delete-confirm").click()
                playwright.expect(delete_sheet).to_have_attribute("aria-hidden", "true")
                playwright.expect(
                    page.get_by_role("heading", name=deck_name, level=3)
                ).to_have_count(0)
                consume_toast("app_decks_deleted")

            active_page = stale_page
            for action, endpoint in (
                ("app_decks_settings", "settings"),
                ("app_decks_delete", "delete"),
            ):
                with active_page.expect_response(
                    lambda response, endpoint=endpoint: (
                        response.request.method == "GET"
                        and response.url.split("?", 1)[0].endswith(f"/{endpoint}")
                    )
                ) as response:
                    open_menu("Toast two", action)
                response.value.finished()
                consume_toast("app_decks_not_found")
        finally:
            browser.close()
