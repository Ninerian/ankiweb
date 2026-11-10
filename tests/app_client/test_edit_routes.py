import json
import logging
import re
from collections.abc import Iterator
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol, cast

import anki.collection
import anki.lang
import pytest
from anki.cards import CardId
from anki.collection import Collection
from anki.decks import DeckId
from anki.notes import NoteId
from anki.scheduler.v3 import Scheduler
from anki.scheduler_pb2 import CardAnswer
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ankiweb.app import create_app
from ankiweb.core.app_client.vocab import (
    NOTETYPE_NAME,
    add_vocab_note,
    escape_field,
    highlight_example,
)
from ankiweb.core.auth import COOKIE, auth_token
from ankiweb.core.config import Settings


def test_edit_page_initializes_model_and_session(client: TestClient) -> None:
    assert client.portal is not None
    service = cast(FastAPI, client.app).state.service
    deck_id = client.portal.call(
        service.run, lambda col: col.decks.id('Deck <img src=x onerror="x">')
    )
    assert deck_id is not None
    assert (
        client.portal.call(service.run, lambda col: col.models.by_name(NOTETYPE_NAME))
        is None
    )

    page = client.get(f"/app/edit/{deck_id}/front")
    assert page.status_code == 200
    assert '<html lang="en" dir="ltr">' in page.text
    assert "Deck &lt;img src=x onerror=&#34;x&#34;&gt;" in page.text
    assert "<img src=x" not in page.text
    assert "/shell/static/app/edit.js" in page.text
    assert re.search(r'data-instance="[0-9a-f]{16}"\s+data-rev="0"', page.text)
    for name in ("front", "back", "hint", "example"):
        assert f'id="input-{name}"' in page.text
        assert f'name="{name}"' in page.text
    for name in ("preview", "btn-next", "added-cards"):
        assert f'id="{name}"' in page.text
    for step in (1, 2, 3):
        assert f'data-step-section="{step}"' in page.text
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
    assert "set-cookie" not in client.get(f"/app/edit/{deck_id}/front").headers


def test_editor_form_contains_only_draft_fields(client: TestClient) -> None:
    page = client.get("/app/edit/1/front")
    form = re.search(r'<form\s+id="edit-form".*?</form>', page.text, re.DOTALL)
    assert form is not None
    html = form.group()
    assert re.search(r'<input\s+type="hidden"\s+name="nid"\s+value="0"', html)
    for name in ("front", "back", "hint", "example"):
        assert re.search(rf'<textarea\s+id="input-{name}"\s+name="{name}"', html)
    assert 'id="preview"' in html
    for outside in ("<header", 'id="edit-actions"', 'id="pile"'):
        index = page.text.index(outside, page.text.index('id="edit-session"'))
        assert index < form.start() or index >= form.end()


@pytest.mark.parametrize(
    "deck", ["nope", "0", "-1", "9223372036854775808", "999999999"]
)
def test_edit_page_rejects_missing_or_unknown_deck(
    client: TestClient, deck: str
) -> None:
    response = client.get(f"/app/edit/{deck}/front", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/app/"
    assert "app_sid" not in response.cookies
    assert client.portal is not None
    assert (
        client.portal.call(
            cast(FastAPI, client.app).state.service.run,
            lambda col: col.models.by_name(NOTETYPE_NAME),
        )
        is None
    )


@pytest.mark.parametrize(
    ("url", "target"),
    [
        ("/app/edit", "/app/"),
        ("/app/edit?deck=1", "/app/"),
        ("/app/edit/1", "/app/edit/1/front"),
        ("/app/edit/1/back", "/app/edit/1/front"),
        ("/app/edit/1/preview", "/app/edit/1/front"),
        ("/app/edit/1/invalid", "/app/edit/1/front"),
        ("/app/edit/1/cards/nope/front", "/app/edit/1/front"),
        ("/app/edit/1/cards/0/front", "/app/edit/1/front"),
        ("/app/edit/1/cards/9223372036854775808/front", "/app/edit/1/front"),
        ("/app/edit/1/cards/999999999/front", "/app/edit/1/front"),
        ("/app/edit/1/front?view=cards", "/app/edit/1/front"),
        ("/app/edit/1/cards?card=1", "/app/edit/1/cards"),
    ],
)
def test_editor_url_redirects(client: TestClient, url: str, target: str) -> None:
    response = client.get(url, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == target


def test_direct_card_urls_render_selected_step_and_redirect_invalid(
    client: TestClient,
) -> None:
    values = {
        "front": "Question",
        "back": "Answer",
        "hint": "Hint",
        "example": "*word*",
    }
    _post(client, "/app/edit/1/commit", values=values)
    nid = _notes(client)[0]
    root = f"/app/edit/1/cards/{nid}"
    redirect = client.get(root, follow_redirects=False)
    assert redirect.status_code == 303
    assert redirect.headers["location"] == f"{root}/front"
    invalid = client.get(f"{root}/bogus", follow_redirects=False)
    assert invalid.status_code == 303
    assert invalid.headers["location"] == "/app/edit/1/front"
    for step, number in (("front", "1"), ("back", "2"), ("preview", "3")):
        page = client.get(f"{root}/{step}")
        assert page.status_code == 200
        assert f'data-initial-step="{step}"' in page.text
        assert f'data-step="{number}"' in page.text
        assert 'data-initial-view="card"' in page.text
        assert "Question" in page.text and "Answer" in page.text
        if step == "preview":
            assert "<mark>word</mark>" in page.text
    query = client.get(f"{root}/preview?view=cards", follow_redirects=False)
    assert query.status_code == 303
    assert query.headers["location"] == f"{root}/preview"


def test_edit_routes_follow_password_gate(tmp_path: Path) -> None:
    password = f"test-{tmp_path.name}"
    settings = Settings(collection_path=tmp_path / "auth-edit.anki2", password=password)
    with TestClient(create_app(settings)) as client:
        for response in (
            client.get("/app/edit/1/front", follow_redirects=False),
            _post(
                client,
                "/app/edit/1/step/preview/next",
                values={},
                follow_redirects=False,
            ),
            _post(client, "/app/edit/1/commit", values={}, follow_redirects=False),
            _post(client, "/app/edit/1/card/1", follow_redirects=False),
        ):
            assert response.status_code == 303
            assert response.headers["location"] == "/app/login"
            assert "app_sid" not in response.cookies
        client.cookies.set(COOKIE, auth_token(password))
        assert client.get("/app/edit/1/front").status_code == 200
        assert (
            _post(client, "/app/edit/1/step/preview/next", values={}).status_code == 200
        )
        assert _post(client, "/app/edit/1/commit", values={}).status_code == 200


@pytest.mark.parametrize(
    ("method", "url", "status"),
    [
        ("GET", "/app/add?deck=1", 404),
        ("POST", "/app/add/preview", 405),
        ("POST", "/app/add/commit?deck=1", 405),
        ("POST", "/app/add/edit/1?deck=1", 405),
        ("POST", "/app/edit/commit?deck=1", 405),
        ("POST", "/app/edit/preview?deck=1", 405),
        ("POST", "/app/edit/card/1?deck=1", 405),
    ],
)
def test_old_app_editor_routes_are_absent(
    client: TestClient, method: str, url: str, status: int
) -> None:
    previous_sid = client.cookies.get("app_sid")
    response = client.request(method, url, follow_redirects=False)
    # The GET media catchall returns 405 for POST, not an editor route.
    assert response.status_code == status
    assert "location" not in response.headers
    assert 'id="added-cards"' not in response.text
    assert "datastar-patch" not in response.text
    assert "app_sid" not in response.cookies
    assert client.cookies.get("app_sid") == previous_sid


def test_preview_escapes_all_fields_and_highlights_example(client: TestClient) -> None:
    example = "<img src=x onerror=alert(1)> *safe & sound*\n*next*"
    payload = {
        "front": "<img src=x onerror=alert(1)>",
        "back": "<script>alert(1)</script>",
        "hint": "<b>hint</b> & more",
        "example": example,
    }
    response = _post(client, "/app/edit/1/step/preview/next", values=payload)
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
    response = _post(
        client,
        "/app/edit/1/step/preview/next",
        values={"front": "Q", "back": "A", "example": "*<img src=x onerror=alert(1)>*"},
    )
    assert "<mark>&lt;img src=x onerror=alert(1)&gt;</mark>" in response.text
    assert "<img src=x" not in response.text


def test_preview_omits_empty_optional_fields(client: TestClient) -> None:
    response = _post(
        client,
        "/app/edit/1/step/preview/next",
        values={"front": "Question", "back": "Answer"},
    )
    assert response.status_code == 200
    assert "Question" in response.text
    assert "Answer" in response.text
    assert "Hint" not in response.text
    assert "Example sentence" not in response.text


def test_preview_matches_saved_example_after_client_highlighting(
    client: TestClient,
) -> None:
    example = 'Say *<b> & "x"*.\nThen *<img src=x onerror=alert(1)>*.'
    payload = {"front": "Question", "back": "Answer", "example": example}
    preview = _post(client, "/app/edit/1/step/preview/next", values=payload)
    committed = _post(client, "/app/edit/1/commit", values=payload)
    assert preview.status_code == committed.status_code == 200
    assert _summary(committed.text) == 1

    ids = _notes(client)
    assert len(ids) == 1
    assert client.portal is not None

    def saved_example(col: Collection) -> tuple[str, str]:
        note = col.get_note(ids[0])
        return note["Example"], note.cards()[0].answer()

    stored, answer = client.portal.call(
        cast(FastAPI, client.app).state.service.run, saved_example
    )
    assert stored == (
        'Say *&lt;b&gt; &amp; "x"*.<br>Then *&lt;img src=x onerror=alert(1)&gt;*.'
    )
    assert f'<div class="av-example">{stored}</div>' in answer

    # The planned client highlights text within each line, after Anki renders it.
    rendered = "<br>".join(
        re.sub(r"\*([^*]+)\*", r"<mark>\1</mark>", line)
        for line in stored.split("<br>")
    )
    assert rendered == (
        'Say <mark>&lt;b&gt; &amp; "x"</mark>.<br>'
        "Then <mark>&lt;img src=x onerror=alert(1)&gt;</mark>."
    )
    assert f'<p class="av-example">{rendered}</p>' in preview.text
    assert "<img src=x" not in preview.text
    assert "<img src=x" not in answer


def test_edit_page_uses_resolved_language(tmp_path: Path) -> None:
    settings = Settings(collection_path=tmp_path / "de-edit.anki2", lang="de_DE")
    try:
        with TestClient(create_app(settings)) as client:
            response = client.get("/app/edit/1/front")
            preview = _post(
                client,
                "/app/edit/1/step/preview/next",
                values={"front": "Frage", "back": "Antwort"},
            )
            first = _post(
                client,
                "/app/edit/1/commit",
                values={"front": "Frage", "back": "Antwort"},
            )
            duplicate = _post(
                client,
                "/app/edit/1/commit",
                values={"front": "Frage", "back": "Antwort"},
            )
            second = _post(
                client,
                "/app/edit/1/commit",
                values={"front": "Zweite", "back": "Antwort"},
            )
            for index in range(3, 6):
                last = _post(
                    client,
                    "/app/edit/1/commit",
                    values={"front": f"Frage {index}", "back": "Antwort"},
                )
            reloaded = client.get("/app/edit/1/front")
    finally:
        anki.lang.set_lang("en")
    assert response.status_code == 200
    assert '<html lang="de" dir="ltr">' in response.text
    assert "Vorderseite (Frage / Stichwort)" in response.text
    assert "Kartenvorschau" in preview.text
    assert _badge(first.text) == "1 Karte"
    assert _badge(second.text) == "2 Karten"
    assert _badge(last.text) == "5 Karten"
    assert _badge(reloaded.text) == "5 Karten"
    _assert_error(duplicate, "Eine Karte mit dieser Vorderseite existiert bereits.")


def _badge(text: str) -> str:
    count = re.search(r'class="add-stack-count"[^>]*>(\d+)</text>', text)
    unit = re.search(r"<textPath[^>]*>([^<]+)</textPath>", text)
    assert count is not None and unit is not None
    return f"{count.group(1)} {unit.group(1)}"


def _pile(text: str) -> str:
    """Keep pile assertions separate from the following deck-wide list."""
    assert 'id="deck-cards"' in text
    return text.split('id="deck-cards"', 1)[0]


def _stack_ids(text: str) -> list[int]:
    return [
        int(nid)
        for nid in re.findall(
            r'class="stacked-card\b[^"]*"[^>]*data-note-id="(\d+)"', _pile(text)
        )
    ]


def _list_ids(text: str) -> list[int]:
    return [
        int(nid)
        for nid in re.findall(
            r'class="browse-card\b[^"]*"[^>]*data-note-id="(\d+)"',
            text.split('id="deck-cards"', 1)[1].split("event: ", 1)[0],
        )
    ]


class _TextResponse(Protocol):
    @property
    def text(self) -> str: ...


# Requests are independently guarded; tests that model tabs use page-issued tokens.
_TOKEN = "0123456789abcdef"  # noqa: S105 - opaque test instance id


def _post(
    client: TestClient,
    url: str,
    *,
    values: dict | None = None,
    content: str | None = None,
    headers: dict | None = None,
    follow_redirects: bool = True,
):
    prefix, deck, action = url.removeprefix("/app/edit/").partition("/")
    assert deck and action
    url = f"/app/edit/{prefix}/{_TOKEN}/0/{action}"
    if content is not None:
        return client.post(
            url, content=content, headers=headers, follow_redirects=follow_redirects
        )
    form = {"front": "", "back": "", "hint": "", "example": "", "nid": "0"}
    form.update(values or {})
    return client.post(
        url, data=form, headers=headers, follow_redirects=follow_redirects
    )


def _summary(text: str) -> int:
    match = re.search(r'id="summary-count"[^>]*>\s*(\d+)', text)
    assert match is not None
    return int(match.group(1))


def _deck_count(text: str) -> int:
    if 'class="add-stack-count"' not in text:
        assert _list_ids(text) == []
        return 0
    return int(_badge(text).split()[0])


def _progress_reset(text: str) -> bool:
    return 'id="progress-reset-notice"' in text


def _assert_error(response: _TextResponse, message: str) -> None:
    assert (
        f'#edit-session[data-instance="{_TOKEN}"][data-rev="0"] #edit-error'
        in response.text
    )
    assert message in unescape(response.text)
    assert "datastar-patch-signals" not in response.text
    assert 'id="edit-form"' not in response.text


def _form(response: _TextResponse) -> tuple[dict[str, str], dict[str, str | None]]:
    text = "\n".join(
        line.removeprefix("data: elements ")
        for line in response.text.splitlines()
        if line.startswith("data: elements ")
    )
    parser = _FormParser()
    parser.feed(text)
    assert parser.attrs
    return parser.values, parser.attrs


class _FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.attrs: dict[str, str | None] = {}
        self.values: dict[str, str] = {}
        self.current: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = dict(attrs)
        if tag == "div" and data.get("id") == "edit-session":
            self.attrs = data
        if tag == "textarea" and data.get("name"):
            self.current = str(data["name"])
            self.values[self.current] = ""

    def handle_data(self, data: str) -> None:
        if self.current is not None:
            self.values[self.current] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "textarea":
            self.current = None


def _notes(client: TestClient) -> list[NoteId]:
    assert client.portal is not None
    return client.portal.call(
        cast(FastAPI, client.app).state.service.run, lambda col: col.find_notes("")
    )


def test_done_patches_guarded_dialog_with_session_count(client: TestClient) -> None:
    client.get("/app/edit/1/front")
    _post(client, "/app/edit/1/commit", values={"front": "One", "back": "Answer"})

    reset = _post(client, "/app/edit/1/reset")
    assert 'id="add-summary"' not in reset.text
    done = _post(client, "/app/edit/1/done")
    assert 'id="add-summary"' in done.text
    assert 'data-init="el.showModal()"' in done.text
    assert "#edit-dialog-host" in done.text
    assert 'data-reset-from="0"' in done.text
    assert _summary(done.text) == 1


def test_commit_persists_escaped_note_and_patches_session_cards(
    client: TestClient,
) -> None:
    assert client.portal is not None
    service = cast(FastAPI, client.app).state.service
    deck_id = client.portal.call(service.run, lambda col: col.decks.id("Commit deck"))
    assert deck_id is not None
    assert client.get(f"/app/edit/{deck_id}/front").status_code == 200
    values = {
        "front": '<img src=x onerror="alert(1)"> &\nQuestion',
        "back": "<script>alert(1)</script> & answer",
        "hint": "<b>hint</b> &",
        "example": "A *word* & <img src=x onerror=alert(1)>",
    }

    response = _post(
        client,
        f"/app/edit/{deck_id}/commit",
        values={**values, "step": 3, "nid": 0, "count": 999},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: datastar-patch-elements" in response.text
    assert 'id="added-cards"' in response.text
    assert _badge(response.text) == "1 card"
    assert "&lt;img src=x onerror=&#34;alert(1)&#34;&gt; &amp;" in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; answer" in response.text
    assert "&lt;b&gt;hint&lt;/b&gt; &amp;" in response.text
    assert "*word* &amp; &lt;img src=x onerror=alert(1)&gt;" in response.text
    assert "<img src=x" not in response.text
    assert "<script>" not in response.text
    reset, attrs = _form(response)
    assert reset == dict.fromkeys(values, "")
    assert attrs["data-nid"] == "0"
    assert attrs["data-rev"] == "1"
    assert _summary(response.text) == 1
    assert _deck_count(response.text) == 1
    assert "window.avAnimateCommit()" in response.text

    ids = _notes(client)
    assert len(ids) == 1

    def saved(col: Collection) -> tuple[str, list[str], list[DeckId]]:
        note = col.get_note(ids[0])
        model = note.note_type()
        assert model is not None
        return (
            model["name"],
            [note[key] for key in ("Front", "Back", "Hint", "Example")],
            [card.did for card in note.cards()],
        )

    name, fields, decks = client.portal.call(service.run, saved)
    assert name == NOTETYPE_NAME
    assert fields == [escape_field(values[key]) for key in values]
    assert decks == [deck_id]

    page = client.get(f"/app/edit/{deck_id}/front")
    assert _summary(page.text) == 1
    assert _badge(page.text) == "1 card"
    assert "&lt;img src=x onerror=&#34;alert(1)&#34;&gt;" in page.text
    assert "<img src=x" not in page.text


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"front": "", "back": "Answer"},
        {"front": " \n", "back": "Answer"},
        {"front": "Question", "back": " "},
    ],
)
def test_commit_rejects_invalid_fields_without_resetting_form(
    client: TestClient, values: dict
) -> None:
    response = _post(client, "/app/edit/1/commit", values=values)
    assert response.status_code == 200
    _assert_error(response, "Front and back are required")
    assert 'id="edit-form"' not in response.text
    assert _notes(client) == []


def test_commit_rejects_malformed_json_without_resetting_form(
    client: TestClient,
) -> None:
    response = _post(
        client,
        "/app/edit/1/commit",
        content="{",
        headers={"content-type": "application/json"},
    )
    _assert_error(response, "Front and back are required")
    assert _notes(client) == []


def test_duplicate_commit_keeps_form_and_one_note(client: TestClient) -> None:
    payload = {"front": "Hund", "back": "dog"}
    assert _summary(_post(client, "/app/edit/1/commit", values=payload).text) == 1
    response = _post(client, "/app/edit/1/commit", values=payload)
    _assert_error(response, "A card with this front already exists.")
    assert 'id="edit-form"' not in response.text
    assert len(_notes(client)) == 1
    assert _summary(client.get("/app/edit/1/front").text) == 1


@pytest.mark.parametrize(
    "deck", ["nope", "0", "-1", "9223372036854775808", "999999999"]
)
def test_commit_rejects_invalid_deck(client: TestClient, deck: str) -> None:
    response = _post(
        client,
        f"/app/edit/{deck}/commit",
        values={"front": "Question", "back": "Answer"},
        follow_redirects=False,
    )
    if deck == "999999999":
        assert response.status_code == 303
        assert response.headers["location"] == "/app/"
    else:
        assert response.status_code == 200
        assert "datastar-patch" not in response.text
    assert "app_sid" not in response.cookies
    assert _notes(client) == []


def test_session_count_is_scoped_but_pile_is_deck_wide(client: TestClient) -> None:
    assert client.portal is not None
    service = cast(FastAPI, client.app).state.service
    other_deck = client.portal.call(service.run, lambda col: col.decks.id("Other"))
    assert other_deck is not None
    first = _post(client, "/app/edit/1/commit", values={"front": "A", "back": "a"})
    assert _summary(first.text) == 1
    first_nid = _notes(client)[0]
    session_a = client.cookies.get("app_sid")
    assert session_a

    second = _post(
        client,
        f"/app/edit/{other_deck}/commit",
        values={"front": "B", "back": "b"},
    )
    assert _summary(second.text) == 1
    assert _badge(second.text) == "1 card"
    assert ">B</span>" in second.text
    assert ">A</span>" not in second.text
    assert ">A</span>" in client.get("/app/edit/1/front").text
    other_page = client.get(f"/app/edit/{other_deck}/front")
    assert ">B</span>" in other_page.text
    assert _badge(other_page.text) == "1 card"
    assert ">A</span>" not in other_page.text
    denied = _post(
        client,
        f"/app/edit/{other_deck}/commit",
        values={"nid": first_nid, "front": "Changed", "back": "changed"},
    )
    assert denied.status_code == 404
    _assert_error(denied, "Could not add the card. Please try again.")
    assert len(_notes(client)) == 2
    assert ">A</span>" in client.get("/app/edit/1/front").text

    client.cookies.clear()
    empty_page = client.get("/app/edit/1/front")
    assert _summary(empty_page.text) == 0
    assert _deck_count(empty_page.text) == 1
    assert ">A</span>" in _pile(empty_page.text)
    assert f'data-note-id="{first_nid}"' in empty_page.text
    assert _badge(empty_page.text) == "1 card"
    edited = _post(
        client,
        "/app/edit/1/commit",
        values={"nid": first_nid, "front": "Changed", "back": "changed"},
    )
    assert edited.status_code == 200
    assert _summary(edited.text) == 0
    assert _deck_count(edited.text) == 1
    assert ">Changed</span>" in _pile(edited.text)
    third = _post(client, "/app/edit/1/commit", values={"front": "C", "back": "c"})
    assert _summary(third.text) == 1
    assert _deck_count(third.text) == 2
    assert _badge(third.text) == "2 cards"
    assert ">C</span>" in _pile(third.text)
    assert ">Changed</span>" in _pile(third.text)

    client.cookies.clear()
    client.cookies.set("app_sid", session_a)
    page = client.get("/app/edit/1/front")
    assert _summary(page.text) == 1
    assert _deck_count(page.text) == 2
    assert _badge(page.text) == "2 cards"
    assert ">Changed</span>" in _pile(page.text)
    assert ">C</span>" in _pile(page.text)
    assert len(_notes(client)) == 3


def test_preexisting_deck_cards_render_before_any_session_additions(
    client: TestClient,
) -> None:
    assert client.portal is not None
    service = cast(FastAPI, client.app).state.service

    def seed(col: Collection) -> tuple[list[NoteId], NoteId]:
        other_deck = col.decks.id("Other")
        assert other_deck is not None
        note_ids = [
            add_vocab_note(col, DeckId(1), f"Existing {index}", "Answer")
            for index in range(6)
        ]
        other_id = add_vocab_note(col, other_deck, "Other deck", "Answer")
        return note_ids, other_id

    note_ids, other_id = client.portal.call(service.run, seed)
    page = client.get("/app/edit/1/front")
    assert _summary(page.text) == 0
    assert _deck_count(page.text) == 6
    assert _badge(page.text) == "6 cards"
    assert _stack_ids(page.text) == list(reversed(note_ids[-5:]))
    assert _list_ids(page.text) == note_ids
    assert other_id not in _list_ids(page.text)

    updated = _post(
        client,
        "/app/edit/1/commit",
        values={"nid": note_ids[0], "front": "Updated existing", "back": "Answer"},
    )
    assert _summary(updated.text) == 0
    assert _deck_count(updated.text) == 6
    assert _stack_ids(updated.text) == list(reversed(note_ids[-5:]))
    assert _list_ids(updated.text) == note_ids
    assert "Updated existing" in updated.text

    added = _post(
        client, "/app/edit/1/commit", values={"front": "New", "back": "Answer"}
    )
    added_id = _stack_ids(added.text)[0]
    assert _summary(added.text) == 1
    assert _deck_count(added.text) == 7
    assert _stack_ids(added.text) == [added_id, *reversed(note_ids[-4:])]
    assert _list_ids(added.text) == [*note_ids, added_id]


@pytest.mark.parametrize("nid", [1, -1, "1", True, None])
def test_commit_rejects_unowned_or_invalid_note_id(
    client: TestClient, nid: object
) -> None:
    response = _post(
        client,
        "/app/edit/1/commit",
        values={"nid": nid, "front": "Question", "back": "Answer"},
    )
    _assert_error(response, "Could not add the card. Please try again.")
    assert _notes(client) == []


def test_commit_failure_preserves_form(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args, **kwargs):
        raise ValueError("private backend detail")

    monkeypatch.setattr("ankiweb.adapters.inbound.http_app.edit.add_vocab_note", fail)
    response = _post(
        client,
        "/app/edit/1/commit",
        values={"front": "Question", "back": "Answer"},
    )
    _assert_error(response, "Could not add the card. Please try again.")
    assert "private backend detail" not in response.text
    assert 'id="edit-form"' not in response.text
    assert _notes(client) == []


def test_commit_does_not_hide_programming_errors(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("programming error")

    monkeypatch.setattr("ankiweb.adapters.inbound.http_app.edit.add_vocab_note", fail)
    with pytest.raises(RuntimeError, match="programming error"):
        _post(
            client,
            "/app/edit/1/commit",
            values={"front": "Question", "back": "Answer"},
        )


def test_deck_stack_shows_latest_five_and_counts_all(client: TestClient) -> None:
    for index in range(6):
        response = _post(
            client,
            "/app/edit/1/commit",
            values={"front": f"Front {index}", "back": f"Back {index}"},
        )
        assert _summary(response.text) == index + 1
    pile = _pile(response.text)
    assert _deck_count(response.text) == 6
    assert "Front 0" not in pile
    for index in range(1, 6):
        assert f"Front {index}" in pile
    assert pile.index("Front 5") < pile.index("Front 4")
    assert "Front 0" in response.text
    assert _badge(response.text) == "6 cards"
    assert _pile(response.text).count("add-stack-badge") == 1
    page = client.get("/app/edit/1/front")
    assert _summary(page.text) == 6
    assert _deck_count(page.text) == 6
    assert _badge(page.text) == "6 cards"
    assert "Front 0" not in _pile(page.text)
    assert "Front 5" in _pile(page.text)

    match = re.search(r'data-note-id="(\d+)"', _pile(response.text))
    assert match is not None
    assert client.portal is not None
    nid = NoteId(int(match.group(1)))
    client.portal.call(
        cast(FastAPI, client.app).state.service.run, lambda col: col.remove_notes([nid])
    )
    page = client.get("/app/edit/1/front")
    assert _summary(page.text) == 5
    assert _deck_count(page.text) == 5
    assert _badge(page.text) == "5 cards"
    assert "Front 0" in _pile(page.text)
    assert "Front 5" not in _pile(page.text)


def test_added_cards_span_query_batches(client: TestClient) -> None:
    for index in range(33):
        response = _post(
            client,
            "/app/edit/1/commit",
            values={"front": f"Batch {index}", "back": "Answer"},
        )
    assert _summary(response.text) == 33
    page = client.get("/app/edit/1/front")
    assert _summary(page.text) == 33
    assert "Batch 27" not in _pile(page.text)
    for index in range(28, 33):
        assert f"Batch {index}" in _pile(page.text)


def test_deleted_notes_are_removed_without_losing_other_decks(
    client: TestClient,
) -> None:
    assert client.portal is not None
    service = cast(FastAPI, client.app).state.service
    other_deck = client.portal.call(service.run, lambda col: col.decks.id("Other"))
    assert other_deck is not None

    def add(deck: int, front: str) -> NoteId:
        response = _post(
            client,
            f"/app/edit/{deck}/commit",
            values={"front": front, "back": "Answer"},
        )
        match = re.search(r'data-note-id="(\d+)"', _pile(response.text))
        assert match is not None
        return NoteId(int(match.group(1)))

    first = add(1, "First")
    add(other_deck, "Other")
    last = add(1, "Last")
    client.portal.call(service.run, lambda col: col.remove_notes([last]))

    page = client.get("/app/edit/1/front")
    assert _summary(page.text) == 1
    assert _deck_count(page.text) == 1
    assert ">First</span>" in page.text
    assert ">Last</span>" not in page.text
    other_page = client.get(f"/app/edit/{other_deck}/front")
    assert _summary(other_page.text) == 1
    assert ">Other</span>" in other_page.text

    response = _post(
        client, "/app/edit/1/commit", values={"front": "New", "back": "Answer"}
    )
    assert _summary(response.text) == 2
    assert _deck_count(response.text) == 2
    assert ">New</span>" in response.text
    assert ">First</span>" in response.text
    assert ">Last</span>" not in response.text
    client.portal.call(service.run, lambda col: col.remove_notes([first]))
    assert _summary(client.get("/app/edit/1/front").text) == 1
    assert ">Other</span>" in client.get(f"/app/edit/{other_deck}/front").text


def test_changed_note_types_are_excluded_from_deck_stack(
    client: TestClient,
) -> None:
    assert client.portal is not None
    service = cast(FastAPI, client.app).state.service
    other_deck = client.portal.call(service.run, lambda col: col.decks.id("Other"))
    assert other_deck is not None
    note_ids = []
    for index in range(7):
        response = _post(
            client,
            "/app/edit/1/commit",
            values={"front": f"Front {index}", "back": f"Back {index}"},
        )
        assert _summary(response.text) == index + 1
        match = re.search(r'data-note-id="(\d+)"', _pile(response.text))
        assert match is not None
        note_ids.append(NoteId(int(match.group(1))))
    original_sid = client.cookies.get("app_sid")
    assert original_sid
    other = _post(
        client,
        f"/app/edit/{other_deck}/commit",
        values={"front": "Other deck", "back": "Answer"},
    )
    assert _summary(other.text) == 1

    client.cookies.clear()
    separate = _post(
        client,
        "/app/edit/1/commit",
        values={"front": "Other session", "back": "Answer"},
    )
    assert _summary(separate.text) == 1
    separate_nid = _stack_ids(separate.text)[0]
    separate_sid = client.cookies.get("app_sid")
    assert separate_sid and separate_sid != original_sid

    client.portal.call(
        service.run, lambda col: _change_note_type(col, [note_ids[0], note_ids[5]])
    )
    client.cookies.clear()
    client.cookies.set("app_sid", original_sid)
    page = client.get("/app/edit/1/front")
    assert page.status_code == 200
    assert _summary(page.text) == 5
    assert _deck_count(page.text) == 6
    assert _list_ids(page.text) == [
        *(note_ids[index] for index in (1, 2, 3, 4, 6)),
        separate_nid,
    ]
    for index in (2, 3, 4, 6):
        assert f">Front {index}</span>" in _pile(page.text)
    for index in (0, 1, 5):
        assert f">Front {index}</span>" not in _pile(page.text)
    pile = _pile(page.text)
    assert ">Other session</span>" in pile
    assert pile.index(">Other session</span>") < pile.index(">Front 6</span>")
    assert pile.index(">Front 6</span>") < pile.index(">Front 4</span>")
    other_page = client.get(f"/app/edit/{other_deck}/front")
    assert _summary(other_page.text) == 1
    assert ">Other deck</span>" in other_page.text

    saved = _post(
        client, "/app/edit/1/commit", values={"front": "Front 7", "back": "Back 7"}
    )
    assert saved.status_code == 200
    assert _summary(saved.text) == 6
    assert _deck_count(saved.text) == 7
    assert _list_ids(saved.text) == [
        *(note_ids[index] for index in (1, 2, 3, 4, 6)),
        separate_nid,
        _stack_ids(saved.text)[0],
    ]
    for index in (3, 4, 6, 7):
        assert f">Front {index}</span>" in _pile(saved.text)
    for index in (0, 1, 2, 5):
        assert f">Front {index}</span>" not in _pile(saved.text)
    assert ">Other session</span>" in _pile(saved.text)
    assert _summary(client.get("/app/edit/1/front").text) == 6

    client.cookies.clear()
    client.cookies.set("app_sid", separate_sid)
    separate_page = client.get("/app/edit/1/front")
    assert _summary(separate_page.text) == 1
    assert ">Other session</span>" in separate_page.text
    assert _deck_count(separate_page.text) == 7
    assert ">Front 7</span>" in _pile(separate_page.text)


def test_added_stack_does_not_hide_incompatible_vocab_model(
    client: TestClient,
) -> None:
    assert client.portal is not None
    _post(client, "/app/edit/1/commit", values={"front": "First", "back": "Answer"})

    def break_model(col: Collection) -> None:
        model = col.models.by_name(NOTETYPE_NAME)
        assert model is not None
        model["css"] = "body { color: red; }"
        col.models.update_dict(model)

    client.portal.call(cast(FastAPI, client.app).state.service.run, break_model)
    with pytest.raises(ValueError, match="incompatible"):
        client.get("/app/edit/1/front")
    response = _post(
        client, "/app/edit/1/commit", values={"front": "Second", "back": "Answer"}
    )
    _assert_error(response, "Could not add the card. Please try again.")
    assert 'id="edit-form"' not in response.text
    assert len(_notes(client)) == 1


def test_added_note_follows_card_moved_between_decks(client: TestClient) -> None:
    assert client.portal is not None
    service = cast(FastAPI, client.app).state.service
    other_deck = client.portal.call(service.run, lambda col: col.decks.id("Other"))
    assert other_deck is not None
    _post(client, "/app/edit/1/commit", values={"front": "Moved", "back": "Answer"})
    nid = _notes(client)[0]

    def move(col: Collection, deck: DeckId) -> None:
        card_ids = [card.id for card in col.get_note(nid).cards()]
        col.set_deck(card_ids, deck)

    client.portal.call(service.run, lambda col: move(col, other_deck))
    source_page = client.get("/app/edit/1/front")
    assert _summary(source_page.text) == 0
    assert _deck_count(source_page.text) == 0
    assert ">Moved</span>" not in _pile(source_page.text)
    other_page = client.get(f"/app/edit/{other_deck}/front")
    assert _summary(other_page.text) == 1
    assert _deck_count(other_page.text) == 1
    assert ">Moved</span>" in _pile(other_page.text)

    client.portal.call(service.run, lambda col: move(col, DeckId(1)))
    other_page = client.get(f"/app/edit/{other_deck}/front")
    assert _summary(other_page.text) == 0
    assert _deck_count(other_page.text) == 0
    assert ">Moved</span>" not in _pile(other_page.text)
    page = client.get("/app/edit/1/front")
    assert _summary(page.text) == 1
    assert _deck_count(page.text) == 1
    assert ">Moved</span>" in _pile(page.text)


def test_edit_round_trip_updates_in_place_and_keeps_stack_order(
    client: TestClient,
) -> None:
    values = {
        "front": "a < b & c\n*x* 😀",
        "back": 'answer & "quotes"\n<line>',
        "hint": "first < hint",
        "example": "one *word*\n& two",
    }
    first = _post(client, "/app/edit/1/commit", values=values)
    assert _summary(first.text) == 1
    assert "data-ts=" in _pile(first.text)
    nid = _notes(client)[0]
    _post(client, "/app/edit/1/commit", values={"front": "Second", "back": "Two"})
    before_ids = set(_notes(client))
    sid = client.cookies.get("app_sid")

    edit = _post(client, f"/app/edit/1/card/{nid}")
    assert edit.status_code == 200
    assert edit.headers["content-type"].startswith("text/event-stream")
    loaded, attrs = _form(edit)
    assert loaded == values
    assert attrs["data-nid"] == str(nid)
    assert json.loads(str(attrs["data-original"])) == values
    assert 'id="edit-warning"' not in edit.text
    assert f"window.avEditCardLoaded({nid})" in edit.text
    assert "set-cookie" not in edit.headers

    unchanged = _post(client, "/app/edit/1/commit", values={**values, "nid": nid})
    assert unchanged.status_code == 200
    assert _summary(unchanged.text) == 2
    assert "window.avAfterCommit()" in unchanged.text
    assert set(_notes(client)) == before_ids
    assert "animate-slide-to-added" not in _pile(unchanged.text)
    assert "data-ts=" not in _pile(unchanged.text)

    updated = {**values, "front": "Updated <front> &\n*yes*"}
    response = _post(client, "/app/edit/1/commit", values={**updated, "nid": nid})
    assert response.status_code == 200
    reset, attrs = _form(response)
    assert reset == dict.fromkeys(values, "")
    assert attrs["data-nid"] == "0"
    assert _summary(response.text) == 2
    assert _deck_count(response.text) == 2
    assert "window.avAfterCommit()" in response.text
    assert response.text.index("Second") < response.text.index("Updated")
    assert "animate-slide-to-added" not in _pile(response.text)
    assert "data-ts=" not in _pile(response.text)
    assert "&lt;front&gt; &amp;" in response.text
    assert set(_notes(client)) == before_ids
    assert client.cookies.get("app_sid") == sid
    assert "set-cookie" not in response.headers
    reloaded, attrs = _form(_post(client, f"/app/edit/1/card/{nid}"))
    assert reloaded == updated
    assert attrs["data-nid"] == str(nid)
    assert json.loads(str(attrs["data-original"])) == updated
    assert client.portal is not None
    fields = client.portal.call(
        cast(FastAPI, client.app).state.service.run,
        lambda col: [
            col.get_note(nid)[key] for key in ("Front", "Back", "Hint", "Example")
        ],
    )
    assert fields == [escape_field(updated[key]) for key in updated]


def test_edit_duplicate_and_invalid_values_keep_form_and_existing_note(
    client: TestClient,
) -> None:
    _post(client, "/app/edit/1/commit", values={"front": "First", "back": "One"})
    nid = _notes(client)[0]
    _post(client, "/app/edit/1/commit", values={"front": "Second", "back": "Two"})
    duplicate = _post(
        client,
        "/app/edit/1/commit",
        values={"nid": nid, "front": "Second", "back": "Changed"},
    )
    _assert_error(duplicate, "A card with this front already exists.")
    assert 'id="edit-form"' not in duplicate.text
    invalid = _post(
        client,
        "/app/edit/1/commit",
        values={"nid": nid, "front": " ", "back": "Changed"},
    )
    _assert_error(invalid, "Front and back are required")
    assert 'id="edit-form"' not in invalid.text
    assert len(_notes(client)) == 2
    loaded, attrs = _form(_post(client, f"/app/edit/1/card/{nid}"))
    assert loaded == {"front": "First", "back": "One", "hint": "", "example": ""}
    assert attrs["data-nid"] == str(nid)
    assert json.loads(str(attrs["data-original"])) == loaded


def test_update_failure_preserves_form_and_note(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _post(client, "/app/edit/1/commit", values={"front": "First", "back": "One"})
    nid = _notes(client)[0]

    def fail(*args, **kwargs):
        raise ValueError("private backend detail")

    monkeypatch.setattr(
        "ankiweb.core.app_client.note_editing.update_vocab_note_with_changes", fail
    )
    response = _post(
        client,
        "/app/edit/1/commit",
        values={"nid": nid, "front": "Changed", "back": "Changed"},
    )
    _assert_error(response, "Could not add the card. Please try again.")
    assert "private backend detail" not in response.text
    assert 'id="edit-form"' not in response.text
    assert _form(_post(client, f"/app/edit/1/card/{nid}"))[0]["front"] == "First"
    assert set(_notes(client)) == {nid}


_RESET_CONFIG = "ankiweb_pending_progress_resets"
_RESET_FIELDS = ("type", "queue", "due", "ivl", "factor", "reps", "lapses")
_RESET_ORIGINAL = {
    "front": "Original",
    "back": "Answer",
    "hint": "Old hint",
    "example": "Old example",
}
_RESET_UPDATED = {
    "front": "Changed <front>",
    "back": "Changed & answer",
    "hint": "New hint",
    "example": "New *example*",
}


@pytest.fixture(
    params=[
        (
            "en",
            (
                "The note text was saved, but learning progress was not reset. "
                "Please try saving again."
            ),
            (
                "Could not save this edit because the learning progress reset could "
                "not be recorded. Please try later or contact support."
            ),
            (
                "The note text was saved and learning progress was reset, but the "
                "pending reset could not be cleared. Please contact support."
            ),
        ),
        (
            "de_DE",
            (
                "Der Kartentext wurde gespeichert, aber der Lernfortschritt "
                "wurde nicht zurückgesetzt. Bitte erneut speichern."
            ),
            (
                "Die Änderung konnte nicht gespeichert werden, weil das Zurücksetzen "
                "des Lernfortschritts nicht vorgemerkt werden konnte. Bitte später "
                "erneut versuchen oder den Support kontaktieren."
            ),
            (
                "Der Kartentext wurde gespeichert und der Lernfortschritt zurückgesetzt, "
                "aber die ausstehende Zurücksetzung konnte nicht gelöscht werden. "
                "Bitte den Support kontaktieren."
            ),
        ),
    ],
    ids=["en", "de"],
)
def _reset_settings(
    tmp_path: Path, request: pytest.FixtureRequest
) -> Iterator[tuple[Settings, str, str, str]]:
    lang, reset_error, record_error, clear_error = request.param
    try:
        yield (
            Settings(collection_path=tmp_path / "reset-failure.anki2", lang=lang),
            reset_error,
            record_error,
            clear_error,
        )
    finally:
        anki.lang.set_lang("en")


def _reset_pending(client: TestClient) -> object:
    assert client.portal is not None
    service = cast(FastAPI, client.app).state.service
    return (
        client.portal.call(service.run, lambda col: col.get_config(_RESET_CONFIG)) or []
    )


def _assert_reset_marker(value: object, nid: NoteId) -> None:
    assert isinstance(value, list) and len(value) == 1
    marker = value[0]
    assert isinstance(marker, list) and len(marker) == 3
    assert marker[:2] == [1, nid]
    digest = marker[2]
    assert isinstance(digest, str)
    assert re.fullmatch(r"[0-9a-f]{32}", digest)


def _reset_snapshot(
    client: TestClient, nid: NoteId, cid: CardId
) -> tuple[list[str], tuple[int, ...]]:
    def snapshot(col: anki.collection.Collection) -> tuple[list[str], tuple[int, ...]]:
        note = col.get_note(nid)
        card = col.get_card(cid)
        return (
            [note[key] for key in ("Front", "Back", "Hint", "Example")],
            tuple(getattr(card, key) for key in _RESET_FIELDS),
        )

    assert client.portal is not None
    return client.portal.call(cast(FastAPI, client.app).state.service.run, snapshot)


def _seed_learned_edit(client: TestClient) -> tuple[NoteId, CardId]:
    created = _post(client, "/app/edit/1/commit", values=_RESET_ORIGINAL)
    assert _summary(created.text) == 1
    nid = _notes(client)[0]

    def learn(col: Collection) -> CardId:
        cid = col.get_note(nid).cards()[0].id
        scheduler = col.sched
        assert isinstance(scheduler, Scheduler)
        for rating in (CardAnswer.EASY, CardAnswer.AGAIN, CardAnswer.EASY):
            card = col.get_card(cid)
            card.start_timer()
            states = col._backend.get_scheduling_states(cid)
            scheduler.answer_card(
                scheduler.build_answer(card=card, states=states, rating=rating)
            )
        card = col.get_card(cid)
        assert card.type == 2 and card.reps > 0 and card.lapses > 0
        assert card.ivl > 0 and card.factor > 0 and card.due > 0
        return cid

    assert client.portal is not None
    cid = client.portal.call(cast(FastAPI, client.app).state.service.run, learn)
    return nid, cid


def _fail_scheduler_once(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    nid: NoteId,
    *,
    partial: bool = False,
) -> tuple[list[tuple[list[CardId], bool]], RuntimeError]:
    assert client.portal is not None
    service = cast(FastAPI, client.app).state.service
    scheduler_class = client.portal.call(service.run, lambda col: type(col.sched))
    original_reset = scheduler_class.schedule_cards_as_new
    calls: list[tuple[list[CardId], bool]] = []
    failure = RuntimeError("deterministic scheduler failure")

    def fail_once(
        self: Scheduler, card_ids: list[CardId], *, reset_counts: bool
    ) -> None:
        _assert_reset_marker(self.col.get_config(_RESET_CONFIG), nid)
        calls.append((card_ids, reset_counts))
        if len(calls) == 1:
            if partial:
                original_reset(self, card_ids, reset_counts=reset_counts)
            raise failure
        original_reset(self, card_ids, reset_counts=reset_counts)

    monkeypatch.setattr(scheduler_class, "schedule_cards_as_new", fail_once)
    return calls, failure


def _reject_reset_config(
    monkeypatch: pytest.MonkeyPatch, *, clear: bool
) -> RuntimeError:
    original_set_config = Collection.set_config
    failure = RuntimeError("deterministic config failure")

    def reject(
        self: Collection, key: str, value: object, *, undoable: bool = False
    ) -> object:
        if key == _RESET_CONFIG and (value == []) == clear:
            raise failure
        return original_set_config(self, key, value, undoable=undoable)

    monkeypatch.setattr(Collection, "set_config", reject)
    return failure


def _assert_reset_log(
    caplog: pytest.LogCaptureFixture, message: str, cause: Exception
) -> None:
    records = [
        record
        for record in caplog.records
        if record.name == "ankiweb.adapters.inbound.http_app.edit"
        and record.getMessage() == message
    ]
    assert len(records) == 1
    exc_info = records[0].exc_info
    assert isinstance(exc_info, tuple)
    error = exc_info[1]
    assert error is not None
    assert error.__cause__ is cause


def test_learned_edit_reset_failure_survives_reopen_and_retries(
    _reset_settings: tuple[Settings, str, str, str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings, message, _, _ = _reset_settings
    learned_label = "Gelernt" if settings.lang == "de_DE" else "Learned"
    with TestClient(create_app(settings)) as client:
        assert client.get("/app/edit/1/front").status_code == 200
        sid = client.cookies.get("app_sid")
        assert sid
        nid, cid = _seed_learned_edit(client)
        learned_page = client.get("/app/edit/1/front")
        assert _stack_ids(learned_page.text) == [nid]
        assert _list_ids(learned_page.text) == [nid]
        assert f", {learned_label}" in learned_page.text
        before = _reset_snapshot(client, nid, cid)
        edit = _post(client, f"/app/edit/1/card/{nid}")
        loaded, attrs = _form(edit)
        assert loaded == _RESET_ORIGINAL
        assert attrs["data-nid"] == str(nid)
        assert json.loads(str(attrs["data-original"])) == _RESET_ORIGINAL
        assert 'id="edit-warning"' in edit.text
        calls, failure = _fail_scheduler_once(client, monkeypatch, nid)
        unchanged = _post(
            client, "/app/edit/1/commit", values={**_RESET_ORIGINAL, "nid": nid}
        )
        assert _progress_reset(unchanged.text) is False
        assert "window.avAfterCommit()" in unchanged.text
        assert f", {learned_label}" in unchanged.text
        assert calls == []
        assert _reset_snapshot(client, nid, cid) == before
        assert 'id="edit-warning"' in _post(client, f"/app/edit/1/card/{nid}").text
        submitted = {**_RESET_UPDATED, "nid": nid, "step": 3, "learned": True}
        with caplog.at_level(
            logging.ERROR, logger="ankiweb.adapters.inbound.http_app.edit"
        ):
            response = _post(client, "/app/edit/1/commit", values=submitted)
        assert calls == [([cid], True)]
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        _assert_error(response, message)
        assert 'id="edit-form"' not in response.text
        assert "deterministic scheduler failure" not in response.text
        _assert_reset_log(
            caplog, "Failed to reset learning progress after saving note", failure
        )
        fields, schedule = _reset_snapshot(client, nid, cid)
        assert fields == [escape_field(value) for value in _RESET_UPDATED.values()]
        assert schedule == before[1]
        assert _notes(client) == [nid]
        marker = _reset_pending(client)
        _assert_reset_marker(marker, nid)
        assert client.cookies.get("app_sid") == sid
        assert "set-cookie" not in response.headers
        page_after = client.get("/app/edit/1/front")
        assert _summary(page_after.text) == 1
        assert "Changed &lt;front&gt;" in _pile(page_after.text)
        assert client.cookies.get("app_sid") == sid
        client.cookies.clear()

    with TestClient(create_app(settings)) as client:
        assert _reset_pending(client) == marker
        assert _reset_snapshot(client, nid, cid) == (fields, schedule)
        reopened = _post(client, f"/app/edit/1/card/{nid}")
        fresh_sid = client.cookies.get("app_sid")
        assert fresh_sid and fresh_sid != sid
        assert 'id="edit-warning"' in reopened.text
        assert _form(reopened)[0] == _RESET_UPDATED
        assert _reset_pending(client) == marker
        retry = _post(client, "/app/edit/1/commit", values=submitted)
        assert retry.status_code == 200
        assert _progress_reset(retry.text) is True
        assert "window.avAfterCommit()" in retry.text
        assert _summary(retry.text) == 0
        assert _deck_count(retry.text) == 1
        assert _stack_ids(retry.text) == [nid]
        assert _list_ids(retry.text) == [nid]
        assert f", {learned_label}" not in retry.text
        assert calls == [([cid], True)] * 2
        assert _reset_pending(client) == []
        fields, reset = _reset_snapshot(client, nid, cid)
        assert fields == [escape_field(value) for value in _RESET_UPDATED.values()]
        assert reset[:2] == (0, 0)
        assert reset[5:] == (0, 0)
        assert client.cookies.get("app_sid") == fresh_sid
        assert "set-cookie" not in retry.headers
        unchanged = _post(client, "/app/edit/1/commit", values=submitted)
        assert _progress_reset(unchanged.text) is False
        assert calls == [([cid], True)] * 2
        assert _reset_snapshot(client, nid, cid) == (fields, reset)


def test_learned_edit_retry_in_same_session(
    _reset_settings: tuple[Settings, str, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, message, _, _ = _reset_settings
    with TestClient(create_app(settings)) as client:
        nid, cid = _seed_learned_edit(client)
        sid = client.cookies.get("app_sid")
        assert sid
        assert 'id="edit-warning"' in _post(client, f"/app/edit/1/card/{nid}").text
        calls, _ = _fail_scheduler_once(client, monkeypatch, nid)
        submitted = {**_RESET_UPDATED, "nid": nid, "step": 3}
        failed = _post(client, "/app/edit/1/commit", values=submitted)
        _assert_error(failed, message)
        _assert_reset_marker(_reset_pending(client), nid)
        retry = _post(client, "/app/edit/1/commit", values=submitted)
        assert retry.status_code == 200
        assert _progress_reset(retry.text) is True
        assert "window.avAfterCommit()" in retry.text
        assert calls == [([cid], True)] * 2
        assert _reset_pending(client) == []
        fields, reset = _reset_snapshot(client, nid, cid)
        assert fields == [escape_field(value) for value in _RESET_UPDATED.values()]
        assert reset[:2] == (0, 0)
        assert reset[5:] == (0, 0)
        assert client.cookies.get("app_sid") == sid
        assert "set-cookie" not in retry.headers


def test_reset_marker_write_failure_keeps_note_and_schedule(
    _reset_settings: tuple[Settings, str, str, str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings, _, message, _ = _reset_settings
    with TestClient(create_app(settings)) as client:
        nid, cid = _seed_learned_edit(client)
        before = _reset_snapshot(client, nid, cid)
        assert 'id="edit-warning"' in _post(client, f"/app/edit/1/card/{nid}").text
        calls, _ = _fail_scheduler_once(client, monkeypatch, nid)
        failure = _reject_reset_config(monkeypatch, clear=False)
        with caplog.at_level(
            logging.ERROR, logger="ankiweb.adapters.inbound.http_app.edit"
        ):
            response = _post(
                client, "/app/edit/1/commit", values={**_RESET_UPDATED, "nid": nid}
            )
        assert response.status_code == 200
        _assert_error(response, message)
        assert 'id="edit-form"' not in response.text
        assert "deterministic config failure" not in response.text
        assert calls == []
        assert _reset_pending(client) == []
        assert _reset_snapshot(client, nid, cid) == before
        _assert_reset_log(
            caplog,
            "Failed to record pending learning progress reset before saving note",
            failure,
        )


def test_reset_marker_capacity_refusal_keeps_note_and_schedule(
    _reset_settings: tuple[Settings, str, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, _, message, _ = _reset_settings
    with TestClient(create_app(settings)) as client:
        nid, cid = _seed_learned_edit(client)
        before = _reset_snapshot(client, nid, cid)
        pending = [[2, index, "0" * 32] for index in range(50)]
        assert client.portal is not None
        service = cast(FastAPI, client.app).state.service
        client.portal.call(
            service.run, lambda col: col.set_config(_RESET_CONFIG, pending)
        )
        calls, _ = _fail_scheduler_once(client, monkeypatch, nid)
        response = _post(
            client, "/app/edit/1/commit", values={**_RESET_UPDATED, "nid": nid}
        )
        _assert_error(response, message)
        assert calls == []
        assert _reset_pending(client) == pending
        assert _reset_snapshot(client, nid, cid) == before


def test_partial_scheduler_reset_retries_even_when_card_is_new(
    _reset_settings: tuple[Settings, str, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, message, _, _ = _reset_settings
    with TestClient(create_app(settings)) as client:
        nid, cid = _seed_learned_edit(client)
        calls, _ = _fail_scheduler_once(client, monkeypatch, nid, partial=True)
        submitted = {**_RESET_UPDATED, "nid": nid}
        response = _post(client, "/app/edit/1/commit", values=submitted)
        _assert_error(response, message)
        assert calls == [([cid], True)]
        _assert_reset_marker(_reset_pending(client), nid)
        fields, reset = _reset_snapshot(client, nid, cid)
        assert fields == [escape_field(value) for value in _RESET_UPDATED.values()]
        assert reset[:2] == (0, 0)
        assert reset[5:] == (0, 0)
        loaded = _post(client, f"/app/edit/1/card/{nid}")
        assert 'id="edit-warning"' not in loaded.text
        retry = _post(client, "/app/edit/1/commit", values=submitted)
        assert _progress_reset(retry.text) is True
        assert calls == [([cid], True)] * 2
        assert _reset_pending(client) == []


def test_reset_marker_before_note_write_does_not_reset_unchanged_note(
    _reset_settings: tuple[Settings, str, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, _, _, _ = _reset_settings
    with TestClient(create_app(settings)) as client:
        nid, cid = _seed_learned_edit(client)
        before = _reset_snapshot(client, nid, cid)

        def crash_update(*args: object, **kwargs: object) -> None:
            raise RuntimeError("interrupted before note write")

        with monkeypatch.context() as crash_patch:
            crash_patch.setattr(Collection, "update_note", crash_update)
            with pytest.raises(RuntimeError, match="interrupted before note write"):
                _post(
                    client,
                    "/app/edit/1/commit",
                    values={**_RESET_UPDATED, "nid": nid},
                )
        marker = _reset_pending(client)
        _assert_reset_marker(marker, nid)
        assert _reset_snapshot(client, nid, cid) == before
        unchanged = _post(
            client, "/app/edit/1/commit", values={**_RESET_ORIGINAL, "nid": nid}
        )
        assert _progress_reset(unchanged.text) is False
        assert _reset_pending(client) == marker
        assert _reset_snapshot(client, nid, cid) == before
        recovered = _post(
            client, "/app/edit/1/commit", values={**_RESET_UPDATED, "nid": nid}
        )
        assert _progress_reset(recovered.text) is True
        assert _reset_pending(client) == []
        fields, reset = _reset_snapshot(client, nid, cid)
        assert fields == [escape_field(value) for value in _RESET_UPDATED.values()]
        assert reset[:2] == (0, 0)
        assert reset[5:] == (0, 0)


def test_reset_marker_clear_failure_reports_completed_reset(
    _reset_settings: tuple[Settings, str, str, str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings, _, _, message = _reset_settings
    with TestClient(create_app(settings)) as client:
        nid, cid = _seed_learned_edit(client)
        failure = _reject_reset_config(monkeypatch, clear=True)
        with caplog.at_level(
            logging.ERROR, logger="ankiweb.adapters.inbound.http_app.edit"
        ):
            response = _post(
                client, "/app/edit/1/commit", values={**_RESET_UPDATED, "nid": nid}
            )
        assert response.status_code == 200
        _assert_error(response, message)
        assert 'id="edit-form"' not in response.text
        fields, reset = _reset_snapshot(client, nid, cid)
        assert fields == [escape_field(value) for value in _RESET_UPDATED.values()]
        assert reset[:2] == (0, 0)
        assert reset[5:] == (0, 0)
        _assert_reset_marker(_reset_pending(client), nid)
        _assert_reset_log(
            caplog, "Failed to clear pending learning progress reset", failure
        )


def test_edit_and_update_allow_cross_session_and_preserve_new_cookie(
    client: TestClient,
) -> None:
    _post(client, "/app/edit/1/commit", values={"front": "First", "back": "One"})
    nid = _notes(client)[0]
    original_sid = client.cookies.get("app_sid")
    assert original_sid
    client.cookies.clear()
    edit = _post(client, f"/app/edit/1/card/{nid}")
    assert edit.status_code == 200
    assert _form(edit)[0]["front"] == "First"
    assert edit.headers["content-type"].startswith("text/event-stream")
    assert "app_sid" in edit.cookies
    assert "HttpOnly" in edit.headers["set-cookie"]
    new_sid = client.cookies.get("app_sid")
    assert new_sid and new_sid != original_sid
    update = _post(
        client,
        "/app/edit/1/commit",
        values={"nid": nid, "front": "Changed", "back": "Changed"},
    )
    assert update.status_code == 200
    assert _summary(update.text) == 0
    assert client.cookies.get("app_sid") == new_sid
    client.cookies.clear()
    client.cookies.set("app_sid", original_sid)
    assert _form(_post(client, f"/app/edit/1/card/{nid}"))[0]["front"] == "Changed"
    assert len(_notes(client)) == 1


def test_edit_missing_note_returns_localized_error_and_session_cookie(
    tmp_path: Path,
) -> None:
    settings = Settings(collection_path=tmp_path / "de-edit.anki2", lang="de_DE")
    try:
        with TestClient(create_app(settings)) as client:
            response = _post(client, "/app/edit/1/card/123456789")
            assert response.status_code == 404
            assert response.text == (
                "Diese Karte kann nicht bearbeitet werden. Bitte erneut versuchen."
            )
            assert response.headers["content-type"].startswith("text/plain")
            assert "app_sid" in response.cookies
            assert "HttpOnly" in response.headers["set-cookie"]
            assert "SameSite=lax" in response.headers["set-cookie"]
    finally:
        anki.lang.set_lang("en")


def test_cross_session_update_sets_new_session_cookie(client: TestClient) -> None:
    _post(client, "/app/edit/1/commit", values={"front": "First", "back": "One"})
    nid = _notes(client)[0]
    client.cookies.clear()
    response = _post(
        client,
        "/app/edit/1/commit",
        values={"nid": nid, "front": "Changed", "back": "Changed"},
    )
    assert response.status_code == 200
    assert _summary(response.text) == 0
    assert "app_sid" in response.cookies
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    assert set(_notes(client)) == {nid}


def test_edit_and_update_follow_actual_deck_and_reject_deleted_notes(
    client: TestClient,
) -> None:
    assert client.portal is not None
    service = cast(FastAPI, client.app).state.service
    other_deck = client.portal.call(service.run, lambda col: col.decks.id("Other"))
    assert other_deck is not None
    _post(client, "/app/edit/1/commit", values={"front": "Moved", "back": "One"})
    nid = _notes(client)[0]

    def move(col: Collection) -> None:
        col.set_deck([card.id for card in col.get_note(nid).cards()], other_deck)

    client.portal.call(service.run, move)
    assert _post(client, f"/app/edit/1/card/{nid}").status_code == 404
    denied = _post(
        client,
        "/app/edit/1/commit",
        values={"nid": nid, "front": "Changed", "back": "One"},
    )
    assert denied.status_code == 404
    assert _form(_post(client, f"/app/edit/{other_deck}/card/{nid}"))[0]["front"] == (
        "Moved"
    )
    updated = _post(
        client,
        f"/app/edit/{other_deck}/commit",
        values={"nid": nid, "front": "Changed", "back": "One"},
    )
    assert _summary(updated.text) == 1
    assert set(_notes(client)) == {nid}
    client.portal.call(service.run, lambda col: col.remove_notes([nid]))
    assert _post(client, f"/app/edit/{other_deck}/card/{nid}").status_code == 404
    stale = _post(
        client,
        f"/app/edit/{other_deck}/commit",
        values={"nid": nid, "front": "Stale", "back": "One"},
    )
    assert stale.status_code == 404
    assert _notes(client) == []


def _change_note_type(col: Collection, note_ids: list[NoteId]) -> None:
    old = col.get_note(note_ids[0]).note_type()
    new = col.models.by_name("Basic")
    assert old is not None and new is not None
    info = col.models.change_notetype_info(
        old_notetype_id=old["id"], new_notetype_id=new["id"]
    )
    mapping = info.input
    col._backend.change_notetype(
        note_ids=note_ids,
        new_fields=list(mapping.new_fields),
        new_templates=list(mapping.new_templates),
        old_notetype_id=old["id"],
        new_notetype_id=new["id"],
        current_schema=mapping.current_schema,
        old_notetype_name=mapping.old_notetype_name,
        is_cloze=mapping.is_cloze,
    )


def test_edit_and_update_reject_changed_note_type(client: TestClient) -> None:
    assert client.portal is not None
    _post(client, "/app/edit/1/commit", values={"front": "Typed", "back": "One"})
    nid = _notes(client)[0]

    client.portal.call(
        cast(FastAPI, client.app).state.service.run,
        lambda col: _change_note_type(col, [nid]),
    )
    assert _post(client, f"/app/edit/1/card/{nid}").status_code in (404, 409)
    response = _post(
        client,
        "/app/edit/1/commit",
        values={"nid": nid, "front": "Changed", "back": "Changed"},
    )
    assert response.status_code in (404, 409)
    assert set(_notes(client)) == {nid}
    assert (
        client.portal.call(
            cast(FastAPI, client.app).state.service.run,
            lambda col: col.get_note(nid)["Front"],
        )
        == "Typed"
    )

    saved = _post(
        client, "/app/edit/1/commit", values={"front": "New", "back": "Answer"}
    )
    assert _summary(saved.text) == 1
    assert ">New</span>" in saved.text
    assert ">Typed</span>" not in saved.text
    page = client.get("/app/edit/1/front")
    assert _summary(page.text) == 1
    assert ">New</span>" in page.text
    assert ">Typed</span>" not in page.text


@pytest.mark.parametrize("deck", ["nope", "999999999"])
def test_edit_rejects_invalid_deck(client: TestClient, deck: str) -> None:
    response = _post(client, f"/app/edit/{deck}/card/1", follow_redirects=False)
    if deck == "999999999":
        assert response.status_code == 404
    else:
        assert response.status_code == 200
        assert "datastar-patch" not in response.text
        assert "app_sid" not in response.cookies


class _EditorElements(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: dict[str, dict[str, str | None]] = {}
        self.labels: dict[str, str] = {}
        self.chips: list[tuple[dict[str, str | None], dict[str, str | None]]] = []
        self._divs: list[dict[str, str | None]] = []
        self._label: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if element_id := values.get("id"):
            self.ids[element_id] = values
        if tag == "div":
            self._divs.append(values)
        elif tag == "label" and (target := values.get("for")):
            self._label = target
            self.labels[target] = ""
        elif tag == "button" and "add-chip" in (values.get("class") or "").split():
            assert self._divs
            self.chips.append((self._divs[-1], values))

    def handle_data(self, data: str) -> None:
        if self._label is not None:
            self.labels[self._label] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "div":
            self._divs.pop()
        elif tag == "label":
            self._label = None


def _edit_language_deck(
    client: TestClient, name: str, description: str, parent_description: str = ""
) -> int:
    assert client.portal is not None

    def seed(col: Collection) -> int:
        if "::" in name:
            parent_name = name.split("::", maxsplit=1)[0]
            parent_id = DeckId(col.decks.add_normal_deck_with_name(parent_name).id)
            parent = col.decks.get(parent_id, default=False)
            assert parent is not None
            parent["desc"] = parent_description
            col.decks.update_dict(parent)
        deck_id = DeckId(col.decks.add_normal_deck_with_name(name).id)
        deck = col.decks.get(deck_id, default=False)
        assert deck is not None
        deck["desc"] = description
        col.decks.update_dict(deck)
        return deck_id

    return client.portal.call(cast(FastAPI, client.app).state.service.run, seed)


def _edit_elements(html: str) -> _EditorElements:
    elements = _EditorElements()
    elements.feed(html)
    return elements


def _chips_for(
    elements: _EditorElements, target: str
) -> list[tuple[dict[str, str | None], dict[str, str | None]]]:
    return [
        (row, chip) for row, chip in elements.chips if chip["data-target"] == target
    ]


def test_edit_language_pair_renders_target_chips_and_neutral_fields(
    client: TestClient,
) -> None:
    deck_id = _edit_language_deck(client, "Spanish", "<!--ankiweb:lang=de>es-->")
    response = client.get(f"/app/edit/{deck_id}/front")
    assert response.status_code == 200
    elements = _edit_elements(response.text)
    assert elements.labels["input-front"] == "Front (Question / Prompt) · 🇪🇸 Spanish"
    assert elements.labels["input-back"] == "Back (Answer / Meaning) · 🇩🇪 German"
    assert elements.ids["input-front"]["lang"] == "es"
    assert elements.ids["input-back"]["lang"] == "de"
    assert elements.ids["add-chips-front"]["lang"] == "es"
    assert elements.ids["input-front"]["placeholder"] == "e.g. a word or phrase"
    assert elements.ids["input-back"]["placeholder"] == "e.g. its meaning"
    assert (
        elements.ids["input-example"]["placeholder"]
        == "e.g. a sentence with the *key word*"
    )
    front_chips = _chips_for(elements, "input-front")
    assert front_chips
    assert all(row.get("id") == "add-chips-front" for row, _ in front_chips)
    values = [chip["data-value"] for _, chip in front_chips]
    assert "ñ" in values
    assert "der " not in values
    assert not _chips_for(elements, "input-back")
    assert {chip["data-target"] for _, chip in elements.chips} == {
        "input-front",
        "input-hint",
    }
    assert [chip["data-value"] for _, chip in _chips_for(elements, "input-hint")] == [
        "Noun ",
        "Verb ",
        "Adj ",
        "(Plural:) ",
    ]


def test_edit_german_target_has_articles_with_spaces_and_sharp_s(
    client: TestClient,
) -> None:
    deck_id = _edit_language_deck(client, "German", "<!--ankiweb:lang=es>de-->")
    response = client.get(f"/app/edit/{deck_id}/front")
    assert response.status_code == 200
    elements = _edit_elements(response.text)
    assert elements.labels["input-front"] == "Front (Question / Prompt) · 🇩🇪 German"
    assert elements.labels["input-back"] == "Back (Answer / Meaning) · 🇪🇸 Spanish"
    assert elements.ids["input-front"]["lang"] == "de"
    assert elements.ids["input-back"]["lang"] == "es"
    assert elements.ids["add-chips-front"]["lang"] == "de"
    values = [chip["data-value"] for _, chip in _chips_for(elements, "input-front")]
    assert values[:3] == ["der ", "die ", "das "]
    assert "ß" in values
    assert "ẞ" in values


def test_edit_korean_target_has_no_front_chip_row(client: TestClient) -> None:
    deck_id = _edit_language_deck(client, "Korean", "<!--ankiweb:lang=en>ko-->")
    response = client.get(f"/app/edit/{deck_id}/front")
    assert response.status_code == 200
    elements = _edit_elements(response.text)
    assert elements.labels["input-front"] == "Front (Question / Prompt) · 🇰🇷 Korean"
    assert elements.labels["input-back"] == "Back (Answer / Meaning) · 🇬🇧 English"
    assert elements.ids["input-front"]["lang"] == "ko"
    assert elements.ids["input-back"]["lang"] == "en"
    assert "add-chips-front" not in elements.ids
    assert not _chips_for(elements, "input-front")
    assert len(_chips_for(elements, "input-hint")) == 4


@pytest.mark.parametrize(
    ("name", "description", "parent_description"),
    [
        ("No marker", "", ""),
        ("Invalid marker", "<!--ankiweb:lang=de>de-->", ""),
        ("Parent::Child", "", "<!--ankiweb:lang=de>es-->"),
    ],
)
def test_edit_without_own_valid_pair_preserves_original_editor(
    client: TestClient, name: str, description: str, parent_description: str
) -> None:
    deck_id = _edit_language_deck(client, name, description, parent_description)
    response = client.get(f"/app/edit/{deck_id}/front")
    assert response.status_code == 200
    elements = _edit_elements(response.text)
    assert elements.labels["input-front"] == "Front (Question / Prompt)"
    assert elements.labels["input-back"] == "Back (Answer / Meaning)"
    assert "lang" not in elements.ids["input-front"]
    assert "lang" not in elements.ids["input-back"]
    assert elements.ids["input-front"]["placeholder"] == "e.g. die Herausforderung"
    assert elements.ids["input-back"]["placeholder"] == "e.g. the challenge"
    assert (
        elements.ids["input-example"]["placeholder"]
        == "e.g. Das ist eine *Herausforderung*."
    )
    assert "add-chips-front" not in elements.ids
    front_chips = _chips_for(elements, "input-front")
    assert all(
        row.get("class") == "add-chips" and "id" not in row for row, _ in front_chips
    )
    assert [chip["data-value"] for _, chip in front_chips] == [
        "der ",
        "die ",
        "das ",
        "ä",
        "ö",
        "ü",
        "ß",
    ]
    assert not _chips_for(elements, "input-back")
    assert [chip["data-value"] for _, chip in _chips_for(elements, "input-hint")] == [
        "Noun ",
        "Verb ",
        "Adj ",
        "(Plural:) ",
    ]


def test_edit_apostrophe_chip_is_escaped_and_preserves_its_value(
    client: TestClient,
) -> None:
    deck_id = _edit_language_deck(client, "French", "<!--ankiweb:lang=en>fr-->")
    response = client.get(f"/app/edit/{deck_id}/front")
    assert response.status_code == 200
    assert 'data-value="l&#39;"' in response.text
    elements = _edit_elements(response.text)
    assert "l'" in [
        chip["data-value"] for _, chip in _chips_for(elements, "input-front")
    ]


def test_edit_language_names_follow_german_ui_language(tmp_path: Path) -> None:
    settings = Settings(
        collection_path=tmp_path / "de-language-edit.anki2", lang="de_DE"
    )
    try:
        with TestClient(create_app(settings)) as client:
            deck_id = _edit_language_deck(
                client, "Spanish", "<!--ankiweb:lang=de>es-->"
            )
            response = client.get(f"/app/edit/{deck_id}/front")
    finally:
        anki.lang.set_lang("en")
    assert response.status_code == 200
    elements = _edit_elements(response.text)
    assert (
        elements.labels["input-front"]
        == "Vorderseite (Frage / Stichwort) · 🇪🇸 Spanisch"
    )
    assert (
        elements.labels["input-back"] == "Rückseite (Antwort / Bedeutung) · 🇩🇪 Deutsch"
    )
    assert elements.ids["input-front"]["lang"] == "es"
    assert elements.ids["input-back"]["lang"] == "de"


@pytest.mark.parametrize(
    ("to", "via", "front", "back", "error"),
    [
        ("1", "chip", "", "", ""),
        ("2", "next", "\u00a0", "", "Front cannot be empty!"),
        ("2", "chip", "\ufeff", "", "Front cannot be empty!"),
        ("2", "next", "\u180e", "", ""),
        ("2", "next", "\u0085", "", ""),
        ("3", "next", "", "back", "Front cannot be empty!"),
        ("3", "next", "front", "\ufeff", "Back cannot be empty!"),
        ("3", "chip", "front", "\u00a0", "Front and back are required"),
        ("3", "chip", "\u180e", "back", ""),
    ],
)
def test_step_validation_uses_ecmascript_trim(
    client: TestClient, to: str, via: str, front: str, back: str, error: str
) -> None:
    step_path = {"1": "front", "2": "back", "3": "preview"}[to]
    response = _post(
        client,
        f"/app/edit/1/step/{step_path}/{via}",
        values={"front": front, "back": back},
    )
    assert response.status_code == 200
    if error:
        _assert_error(response, error)
        assert "#edit-step\n" not in response.text
    else:
        assert f'data-step="{to}"' in response.text
        assert (
            f'#edit-session[data-instance="{_TOKEN}"][data-rev="0"] #edit-step'
            in response.text
        )
        assert 'id="edit-form"' not in response.text


def test_history_preview_validates_before_applying(client: TestClient) -> None:
    invalid = _post(
        client,
        "/app/edit/1/step/preview/history",
        values={"front": "Question", "back": ""},
    )
    _assert_error(invalid, "Front and back are required")
    assert "window.avStepRejected()" in invalid.text
    assert 'id="edit-step"' not in invalid.text
    valid = _post(
        client,
        "/app/edit/1/step/preview/history",
        values={"front": "Question", "back": "Answer"},
    )
    assert 'data-step="3"' in valid.text
    assert "window.avStepApplied('preview', 0, true)" in valid.text
    assert 'id="edit-form"' not in valid.text


@pytest.mark.parametrize(("front", "saved"), [("\ufeff", True), ("\u0085", False)])
def test_commit_validation_keeps_python_strip_semantics(
    client: TestClient, front: str, saved: bool
) -> None:
    response = _post(
        client, "/app/edit/1/commit", values={"front": front, "back": "Answer"}
    )
    if saved:
        assert _summary(response.text) == 1
        assert len(_notes(client)) == 1
    else:
        _assert_error(response, "Front and back are required")
        assert _notes(client) == []


@pytest.mark.parametrize(
    "route",
    ["step/back/next", "card/1", "commit", "reset"],
)
@pytest.mark.parametrize(
    "guard",
    [
        "bad/0",
        "0123456789abcdef/-1",
        "0123456789abcdef/１２",  # noqa: RUF001 - fullwidth digits
        "0123456789abcdef/9999999999999999999",
    ],
)
def test_missing_or_invalid_guard_returns_empty_stream(
    client: TestClient, route: str, guard: str
) -> None:
    response = client.post(
        f"/app/edit/1/{guard}/{route}",
        data={
            "front": "Question",
            "back": "Answer",
            "hint": "",
            "example": "",
            "nid": "0",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "datastar-patch" not in response.text
    assert "app_sid" not in response.cookies
    assert _notes(client) == []


def _flat(sse_text: str) -> str:
    """SSE patch text with data-line prefixes and whitespace runs collapsed."""
    return re.sub(r"\s+", " ", sse_text.replace("data: elements ", " "))


def test_old_revision_and_other_tab_cannot_match_fragment_selectors(
    client: TestClient,
) -> None:
    pages = [client.get("/app/edit/1/front") for _ in range(2)]
    tokens = []
    for page in pages:
        match = re.search(r'data-instance="([0-9a-f]{16})"\s+data-rev="0"', page.text)
        assert match is not None
        tokens.append(match.group(1))
    assert tokens[0] != tokens[1]
    form = {"front": "Old", "back": "Answer", "hint": "", "example": "", "nid": "0"}
    response = client.post(f"/app/edit/1/{tokens[0]}/2/step/preview/next", data=form)
    selectors = re.findall(
        r"^data: selector (#edit-session.+)$", response.text, re.MULTILINE
    )
    assert len(selectors) == 5
    assert all(
        f'#edit-session[data-instance="{tokens[0]}"][data-rev="2"] ' in s
        for s in selectors
    )
    assert all(f'data-instance="{tokens[1]}"' not in s for s in selectors)
    assert all('data-rev="3"' not in s for s in selectors)
    assert 'id="edit-form"' not in response.text
    reset = client.post(f"/app/edit/1/{tokens[0]}/2/reset", data=form)
    assert (
        f'data: selector #edit-session[data-instance="{tokens[0]}"][data-rev="2"]'
        in reset.text
    )
    assert f'data-instance="{tokens[0]}" data-rev="3" data-reset-from="2"' in _flat(
        reset.text
    )
    _post(client, "/app/edit/1/commit", values=form)
    nid = _notes(client)[0]
    loaded = client.post(f"/app/edit/1/{tokens[0]}/2/card/{nid}", data=form)
    assert (
        f'data: selector #edit-session[data-instance="{tokens[0]}"][data-rev="2"]'
        in loaded.text
    )
    assert f'data-instance="{tokens[0]}" data-rev="3" data-reset-from="2"' in _flat(
        loaded.text
    )
    assert f"window.avEditCardLoaded({nid})" in loaded.text
    assert (
        f'#edit-session[data-instance="{tokens[0]}"][data-rev="3"][data-reset-from="2"]'
        in loaded.text
    )


@pytest.mark.parametrize("field", ["front", "back", "hint", "example", "nid"])
def test_missing_form_field_is_rejected(client: TestClient, field: str) -> None:
    form = {
        "front": "Question",
        "back": "Answer",
        "hint": "",
        "example": "",
        "nid": "0",
    }
    del form[field]
    response = client.post(f"/app/edit/1/{_TOKEN}/0/commit", data=form)
    _assert_error(response, "Could not add the card. Please try again.")
    assert _notes(client) == []


@pytest.mark.parametrize("route", ["commit", "step/back/next"])
def test_duplicate_and_uploaded_form_fields_are_rejected(
    client: TestClient, route: str
) -> None:
    url = f"/app/edit/1/{_TOKEN}/0/{route}"
    message = (
        "Front and back are required"
        if route.startswith("commit")
        else "Could not add the card. Please try again."
    )
    duplicate = client.post(
        url,
        content="front=Question&front=Other&back=Answer&hint=&example=&nid=0",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    upload = client.post(
        url,
        data={"back": "Answer", "hint": "", "example": "", "nid": "0"},
        files={"front": ("front.txt", b"Question", "text/plain")},
    )
    _assert_error(duplicate, message)
    _assert_error(upload, message)
    assert _notes(client) == []


def test_rendered_counters_use_utf16_code_units(client: TestClient) -> None:
    values = {"front": "a😀", "back": "🧑‍🚀", "hint": "😀😀", "example": "x"}
    _post(client, "/app/edit/1/commit", values=values)
    nid = _notes(client)[0]
    loaded = _post(client, f"/app/edit/1/card/{nid}")
    for field, count in {"front": 3, "back": 5, "hint": 4, "example": 1}.items():
        assert f'data-counter-for="{field}">{count}</span>' in loaded.text
    assert _form(loaded)[0] == values


def test_claimed_learned_and_counts_do_not_override_collection(
    client: TestClient,
) -> None:
    nid, cid = _seed_learned_edit(client)
    response = _post(
        client,
        "/app/edit/1/commit",
        values={
            **_RESET_UPDATED,
            "nid": nid,
            "learned": "false",
            "count": "999",
            "deckCount": "999",
            "progressReset": "false",
        },
    )
    assert _summary(response.text) == 1
    assert _deck_count(response.text) == 1
    assert _progress_reset(response.text)
    fields, schedule = _reset_snapshot(client, nid, cid)
    assert fields == [escape_field(value) for value in _RESET_UPDATED.values()]
    assert schedule[:2] == (0, 0)
    assert schedule[5:] == (0, 0)
