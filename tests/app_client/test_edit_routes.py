import json
import logging
import re
from collections.abc import Iterator
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

    page = client.get(f"/app/edit?deck={deck_id}")
    assert page.status_code == 200
    assert '<html lang="en" dir="ltr">' in page.text
    assert "Deck &lt;img src=x onerror=&#34;x&#34;&gt;" in page.text
    assert "<img src=x" not in page.text
    assert "/shell/static/app/edit.js" in page.text
    assert (
        'data-signals="{step: 1, ...JSON.parse(el.dataset.initialFields)' in page.text
    )
    assert "data-initial-fields=" in page.text
    assert "_editSaved: false" in page.text
    for name in ("front", "back", "hint", "example"):
        assert f'id="input-{name}"' in page.text
        assert f"data-bind:{name}" in page.text
    for name in ("preview", "btn-next", "btn-add", "added-cards"):
        assert f'id="{name}"' in page.text
    for step in (1, 2, 3):
        assert f'data-show="$step === {step}" style="display:none"' in page.text
    assert "/app/edit/preview" in page.text
    assert f"/app/edit/commit?deck={deck_id}" in page.text
    assert "data-indicator:saving" in page.text
    assert 'data-attr:disabled="$saving"' in page.text
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
    assert "set-cookie" not in client.get(f"/app/edit?deck={deck_id}").headers


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
def test_edit_page_rejects_missing_or_unknown_deck(
    client: TestClient, query: str
) -> None:
    response = client.get(f"/app/edit{query}", follow_redirects=False)
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


def test_edit_routes_follow_password_gate(tmp_path: Path) -> None:
    password = f"test-{tmp_path.name}"
    settings = Settings(collection_path=tmp_path / "auth-edit.anki2", password=password)
    with TestClient(create_app(settings)) as client:
        for response in (
            client.get("/app/edit?deck=1", follow_redirects=False),
            client.post("/app/edit/preview", json={}, follow_redirects=False),
            client.post("/app/edit/commit?deck=1", json={}, follow_redirects=False),
            client.post("/app/edit/card/1?deck=1", follow_redirects=False),
        ):
            assert response.status_code == 303
            assert response.headers["location"] == "/app/login"
            assert "app_sid" not in response.cookies
        client.cookies.set(COOKIE, auth_token(password))
        assert client.get("/app/edit?deck=1").status_code == 200
        assert client.post("/app/edit/preview", json={}).status_code == 200
        assert client.post("/app/edit/commit?deck=1", json={}).status_code == 200


@pytest.mark.parametrize(
    ("method", "url", "status"),
    [
        ("GET", "/app/add?deck=1", 404),
        ("POST", "/app/add/preview", 405),
        ("POST", "/app/add/commit?deck=1", 405),
        ("POST", "/app/add/edit/1?deck=1", 405),
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
    response = client.post("/app/edit/preview", json=payload)
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
        "/app/edit/preview", json={"example": "*<img src=x onerror=alert(1)>*"}
    )
    assert "<mark>&lt;img src=x onerror=alert(1)&gt;</mark>" in response.text
    assert "<img src=x" not in response.text


def test_preview_omits_empty_optional_fields(client: TestClient) -> None:
    response = client.post(
        "/app/edit/preview", json={"front": "Question", "back": "Answer"}
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
    preview = client.post("/app/edit/preview", json=payload)
    committed = client.post("/app/edit/commit?deck=1", json=payload)
    assert preview.status_code == committed.status_code == 200
    assert _signals(committed)["count"] == 1

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
            response = client.get("/app/edit?deck=1")
            preview = client.post("/app/edit/preview", json={"front": "Frage"})
            first = client.post(
                "/app/edit/commit?deck=1", json={"front": "Frage", "back": "Antwort"}
            )
            duplicate = client.post(
                "/app/edit/commit?deck=1", json={"front": "Frage", "back": "Antwort"}
            )
            second = client.post(
                "/app/edit/commit?deck=1", json={"front": "Zweite", "back": "Antwort"}
            )
            for index in range(3, 6):
                last = client.post(
                    "/app/edit/commit?deck=1",
                    json={"front": f"Frage {index}", "back": "Antwort"},
                )
            reloaded = client.get("/app/edit?deck=1")
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
    assert _signals(duplicate) == {
        "error": "Eine Karte mit dieser Vorderseite existiert bereits."
    }


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
            text.split('id="deck-cards"', 1)[1],
        )
    ]


class _TextResponse(Protocol):
    @property
    def text(self) -> str: ...


def _signals(response: _TextResponse) -> dict[str, object]:
    for line in response.text.splitlines():
        if line.startswith("data: signals "):
            return json.loads(line.removeprefix("data: signals "))
    raise AssertionError("No Datastar signal patch")


def _notes(client: TestClient) -> list[NoteId]:
    assert client.portal is not None
    return client.portal.call(
        cast(FastAPI, client.app).state.service.run, lambda col: col.find_notes("")
    )


def test_commit_persists_escaped_note_and_patches_session_cards(
    client: TestClient,
) -> None:
    assert client.portal is not None
    service = cast(FastAPI, client.app).state.service
    deck_id = client.portal.call(service.run, lambda col: col.decks.id("Commit deck"))
    assert deck_id is not None
    assert client.get(f"/app/edit?deck={deck_id}").status_code == 200
    values = {
        "front": '<img src=x onerror="alert(1)"> &\nQuestion',
        "back": "<script>alert(1)</script> & answer",
        "hint": "<b>hint</b> &",
        "example": "A *word* & <img src=x onerror=alert(1)>",
    }

    response = client.post(
        f"/app/edit/commit?deck={deck_id}",
        json={**values, "step": 3, "nid": 0, "count": 999},
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
    signals = _signals(response)
    assert signals.pop("_editSaved", False) is False
    assert signals == {
        "front": "",
        "back": "",
        "hint": "",
        "example": "",
        "step": 1,
        "nid": 0,
        "learned": False,
        "progressReset": False,
        "count": 1,
        "deckCount": 1,
        "error": "",
    }

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

    page = client.get(f"/app/edit?deck={deck_id}")
    assert "count: 1" in page.text
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
        {"front": 42, "back": "Answer"},
        {"front": "Question", "back": "Answer", "hint": None},
    ],
)
def test_commit_rejects_invalid_fields_without_resetting_form(
    client: TestClient, values: dict
) -> None:
    response = client.post("/app/edit/commit?deck=1", json=values)
    assert response.status_code == 200
    assert _signals(response) == {"error": "Front and back are required"}
    assert "datastar-patch-elements" not in response.text
    assert _notes(client) == []


def test_commit_rejects_malformed_json_without_resetting_form(
    client: TestClient,
) -> None:
    response = client.post(
        "/app/edit/commit?deck=1",
        content="{",
        headers={"content-type": "application/json"},
    )
    assert _signals(response) == {"error": "Front and back are required"}
    assert _notes(client) == []


def test_duplicate_commit_keeps_form_and_one_note(client: TestClient) -> None:
    payload = {"front": "Hund", "back": "dog"}
    assert _signals(client.post("/app/edit/commit?deck=1", json=payload))["count"] == 1
    response = client.post("/app/edit/commit?deck=1", json=payload)
    assert _signals(response) == {"error": "A card with this front already exists."}
    assert "datastar-patch-elements" not in response.text
    assert len(_notes(client)) == 1
    assert "count: 1" in client.get("/app/edit?deck=1").text


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
def test_commit_rejects_invalid_deck(client: TestClient, query: str) -> None:
    response = client.post(
        f"/app/edit/commit{query}",
        json={"front": "Question", "back": "Answer"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/app/"
    assert "app_sid" not in response.cookies
    assert _notes(client) == []


def test_session_count_is_scoped_but_pile_is_deck_wide(client: TestClient) -> None:
    assert client.portal is not None
    service = cast(FastAPI, client.app).state.service
    other_deck = client.portal.call(service.run, lambda col: col.decks.id("Other"))
    assert other_deck is not None
    first = client.post("/app/edit/commit?deck=1", json={"front": "A", "back": "a"})
    assert _signals(first)["count"] == 1
    first_nid = _notes(client)[0]
    session_a = client.cookies.get("app_sid")
    assert session_a

    second = client.post(
        f"/app/edit/commit?deck={other_deck}", json={"front": "B", "back": "b"}
    )
    assert _signals(second)["count"] == 1
    assert _badge(second.text) == "1 card"
    assert ">B</span>" in second.text
    assert ">A</span>" not in second.text
    assert ">A</span>" in client.get("/app/edit?deck=1").text
    other_page = client.get(f"/app/edit?deck={other_deck}")
    assert ">B</span>" in other_page.text
    assert _badge(other_page.text) == "1 card"
    assert ">A</span>" not in other_page.text
    denied = client.post(
        f"/app/edit/commit?deck={other_deck}",
        json={"nid": first_nid, "front": "Changed", "back": "changed"},
    )
    assert denied.status_code == 404
    assert _signals(denied) == {"error": "Could not add the card. Please try again."}
    assert len(_notes(client)) == 2
    assert ">A</span>" in client.get("/app/edit?deck=1").text

    client.cookies.clear()
    empty_page = client.get("/app/edit?deck=1")
    assert "count: 0" in empty_page.text
    assert "deckCount: 1" in empty_page.text
    assert ">A</span>" in _pile(empty_page.text)
    assert f'data-note-id="{first_nid}"' in empty_page.text
    assert _badge(empty_page.text) == "1 card"
    edited = client.post(
        "/app/edit/commit?deck=1",
        json={"nid": first_nid, "front": "Changed", "back": "changed"},
    )
    assert edited.status_code == 200
    assert _signals(edited)["count"] == 0
    assert _signals(edited)["deckCount"] == 1
    assert ">Changed</span>" in _pile(edited.text)
    third = client.post("/app/edit/commit?deck=1", json={"front": "C", "back": "c"})
    assert _signals(third)["count"] == 1
    assert _signals(third)["deckCount"] == 2
    assert _badge(third.text) == "2 cards"
    assert ">C</span>" in _pile(third.text)
    assert ">Changed</span>" in _pile(third.text)

    client.cookies.clear()
    client.cookies.set("app_sid", session_a)
    page = client.get("/app/edit?deck=1")
    assert "count: 1" in page.text
    assert "deckCount: 2" in page.text
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
    page = client.get("/app/edit?deck=1")
    assert "count: 0" in page.text
    assert "deckCount: 6" in page.text
    assert _badge(page.text) == "6 cards"
    assert _stack_ids(page.text) == list(reversed(note_ids[-5:]))
    assert _list_ids(page.text) == note_ids
    assert other_id not in _list_ids(page.text)

    updated = client.post(
        "/app/edit/commit?deck=1",
        json={"nid": note_ids[0], "front": "Updated existing", "back": "Answer"},
    )
    assert _signals(updated)["count"] == 0
    assert _signals(updated)["deckCount"] == 6
    assert _stack_ids(updated.text) == list(reversed(note_ids[-5:]))
    assert _list_ids(updated.text) == note_ids
    assert "Updated existing" in updated.text

    added = client.post(
        "/app/edit/commit?deck=1", json={"front": "New", "back": "Answer"}
    )
    added_id = _stack_ids(added.text)[0]
    assert _signals(added)["count"] == 1
    assert _signals(added)["deckCount"] == 7
    assert _stack_ids(added.text) == [added_id, *reversed(note_ids[-4:])]
    assert _list_ids(added.text) == [*note_ids, added_id]


@pytest.mark.parametrize("nid", [1, -1, "1", True, None])
def test_commit_rejects_unowned_or_invalid_note_id(
    client: TestClient, nid: object
) -> None:
    response = client.post(
        "/app/edit/commit?deck=1",
        json={"nid": nid, "front": "Question", "back": "Answer"},
    )
    assert _signals(response) == {"error": "Could not add the card. Please try again."}
    assert _notes(client) == []


def test_commit_failure_preserves_form_signals(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args, **kwargs):
        raise ValueError("private backend detail")

    monkeypatch.setattr("ankiweb.adapters.inbound.http_app.edit.add_vocab_note", fail)
    response = client.post(
        "/app/edit/commit?deck=1", json={"front": "Question", "back": "Answer"}
    )
    assert _signals(response) == {"error": "Could not add the card. Please try again."}
    assert "private backend detail" not in response.text
    assert "datastar-patch-elements" not in response.text
    assert _notes(client) == []


def test_commit_does_not_hide_programming_errors(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("programming error")

    monkeypatch.setattr("ankiweb.adapters.inbound.http_app.edit.add_vocab_note", fail)
    with pytest.raises(RuntimeError, match="programming error"):
        client.post(
            "/app/edit/commit?deck=1", json={"front": "Question", "back": "Answer"}
        )


def test_deck_stack_shows_latest_five_and_counts_all(client: TestClient) -> None:
    for index in range(6):
        response = client.post(
            "/app/edit/commit?deck=1",
            json={"front": f"Front {index}", "back": f"Back {index}"},
        )
        assert _signals(response)["count"] == index + 1
    pile = _pile(response.text)
    assert _signals(response)["deckCount"] == 6
    assert "Front 0" not in pile
    for index in range(1, 6):
        assert f"Front {index}" in pile
    assert pile.index("Front 5") < pile.index("Front 4")
    assert "Front 0" in response.text
    assert _badge(response.text) == "6 cards"
    assert response.text.count("add-stack-badge") == 1
    page = client.get("/app/edit?deck=1")
    assert "count: 6" in page.text
    assert "deckCount: 6" in page.text
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
    page = client.get("/app/edit?deck=1")
    assert "count: 5" in page.text
    assert "deckCount: 5" in page.text
    assert _badge(page.text) == "5 cards"
    assert "Front 0" in _pile(page.text)
    assert "Front 5" not in _pile(page.text)


def test_added_cards_span_query_batches(client: TestClient) -> None:
    for index in range(33):
        response = client.post(
            "/app/edit/commit?deck=1",
            json={"front": f"Batch {index}", "back": "Answer"},
        )
    assert _signals(response)["count"] == 33
    page = client.get("/app/edit?deck=1")
    assert "count: 33" in page.text
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
        response = client.post(
            f"/app/edit/commit?deck={deck}", json={"front": front, "back": "Answer"}
        )
        match = re.search(r'data-note-id="(\d+)"', _pile(response.text))
        assert match is not None
        return NoteId(int(match.group(1)))

    first = add(1, "First")
    add(other_deck, "Other")
    last = add(1, "Last")
    client.portal.call(service.run, lambda col: col.remove_notes([last]))

    page = client.get("/app/edit?deck=1")
    assert "count: 1" in page.text
    assert "deckCount: 1" in page.text
    assert ">First</span>" in page.text
    assert ">Last</span>" not in page.text
    other_page = client.get(f"/app/edit?deck={other_deck}")
    assert "count: 1" in other_page.text
    assert ">Other</span>" in other_page.text

    response = client.post(
        "/app/edit/commit?deck=1", json={"front": "New", "back": "Answer"}
    )
    assert _signals(response)["count"] == 2
    assert _signals(response)["deckCount"] == 2
    assert ">New</span>" in response.text
    assert ">First</span>" in response.text
    assert ">Last</span>" not in response.text
    client.portal.call(service.run, lambda col: col.remove_notes([first]))
    assert "count: 1" in client.get("/app/edit?deck=1").text
    assert ">Other</span>" in client.get(f"/app/edit?deck={other_deck}").text


def test_changed_note_types_are_excluded_from_deck_stack(
    client: TestClient,
) -> None:
    assert client.portal is not None
    service = cast(FastAPI, client.app).state.service
    other_deck = client.portal.call(service.run, lambda col: col.decks.id("Other"))
    assert other_deck is not None
    note_ids = []
    for index in range(7):
        response = client.post(
            "/app/edit/commit?deck=1",
            json={"front": f"Front {index}", "back": f"Back {index}"},
        )
        assert _signals(response)["count"] == index + 1
        match = re.search(r'data-note-id="(\d+)"', _pile(response.text))
        assert match is not None
        note_ids.append(NoteId(int(match.group(1))))
    original_sid = client.cookies.get("app_sid")
    assert original_sid
    other = client.post(
        f"/app/edit/commit?deck={other_deck}",
        json={"front": "Other deck", "back": "Answer"},
    )
    assert _signals(other)["count"] == 1

    client.cookies.clear()
    separate = client.post(
        "/app/edit/commit?deck=1", json={"front": "Other session", "back": "Answer"}
    )
    assert _signals(separate)["count"] == 1
    separate_nid = _stack_ids(separate.text)[0]
    separate_sid = client.cookies.get("app_sid")
    assert separate_sid and separate_sid != original_sid

    client.portal.call(
        service.run, lambda col: _change_note_type(col, [note_ids[0], note_ids[5]])
    )
    client.cookies.clear()
    client.cookies.set("app_sid", original_sid)
    page = client.get("/app/edit?deck=1")
    assert page.status_code == 200
    assert "count: 5" in page.text
    assert "deckCount: 6" in page.text
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
    other_page = client.get(f"/app/edit?deck={other_deck}")
    assert "count: 1" in other_page.text
    assert ">Other deck</span>" in other_page.text

    saved = client.post(
        "/app/edit/commit?deck=1", json={"front": "Front 7", "back": "Back 7"}
    )
    assert saved.status_code == 200
    assert _signals(saved)["count"] == 6
    assert _signals(saved)["deckCount"] == 7
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
    assert "count: 6" in client.get("/app/edit?deck=1").text

    client.cookies.clear()
    client.cookies.set("app_sid", separate_sid)
    separate_page = client.get("/app/edit?deck=1")
    assert "count: 1" in separate_page.text
    assert ">Other session</span>" in separate_page.text
    assert "deckCount: 7" in separate_page.text
    assert ">Front 7</span>" in _pile(separate_page.text)


def test_added_stack_does_not_hide_incompatible_vocab_model(
    client: TestClient,
) -> None:
    assert client.portal is not None
    client.post("/app/edit/commit?deck=1", json={"front": "First", "back": "Answer"})

    def break_model(col: Collection) -> None:
        model = col.models.by_name(NOTETYPE_NAME)
        assert model is not None
        model["css"] = "body { color: red; }"
        col.models.update_dict(model)

    client.portal.call(cast(FastAPI, client.app).state.service.run, break_model)
    with pytest.raises(ValueError, match="incompatible"):
        client.get("/app/edit?deck=1")
    response = client.post(
        "/app/edit/commit?deck=1", json={"front": "Second", "back": "Answer"}
    )
    assert _signals(response) == {"error": "Could not add the card. Please try again."}
    assert "datastar-patch-elements" not in response.text
    assert len(_notes(client)) == 1


def test_added_note_follows_card_moved_between_decks(client: TestClient) -> None:
    assert client.portal is not None
    service = cast(FastAPI, client.app).state.service
    other_deck = client.portal.call(service.run, lambda col: col.decks.id("Other"))
    assert other_deck is not None
    client.post("/app/edit/commit?deck=1", json={"front": "Moved", "back": "Answer"})
    nid = _notes(client)[0]

    def move(col: Collection, deck: DeckId) -> None:
        card_ids = [card.id for card in col.get_note(nid).cards()]
        col.set_deck(card_ids, deck)

    client.portal.call(service.run, lambda col: move(col, other_deck))
    source_page = client.get("/app/edit?deck=1")
    assert "count: 0" in source_page.text
    assert "deckCount: 0" in source_page.text
    assert ">Moved</span>" not in _pile(source_page.text)
    other_page = client.get(f"/app/edit?deck={other_deck}")
    assert "count: 1" in other_page.text
    assert "deckCount: 1" in other_page.text
    assert ">Moved</span>" in _pile(other_page.text)

    client.portal.call(service.run, lambda col: move(col, DeckId(1)))
    other_page = client.get(f"/app/edit?deck={other_deck}")
    assert "count: 0" in other_page.text
    assert "deckCount: 0" in other_page.text
    assert ">Moved</span>" not in _pile(other_page.text)
    page = client.get("/app/edit?deck=1")
    assert "count: 1" in page.text
    assert "deckCount: 1" in page.text
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
    first = client.post("/app/edit/commit?deck=1", json=values)
    assert _signals(first)["count"] == 1
    assert "data-ts=" in _pile(first.text)
    nid = _notes(client)[0]
    client.post("/app/edit/commit?deck=1", json={"front": "Second", "back": "Two"})
    before_ids = set(_notes(client))
    sid = client.cookies.get("app_sid")

    edit = client.post(f"/app/edit/card/{nid}?deck=1")
    assert edit.status_code == 200
    assert edit.headers["content-type"].startswith("text/event-stream")
    loaded = _signals(edit)
    assert isinstance(loaded.pop("editLoaded"), int)
    assert loaded == {
        **values,
        "nid": nid,
        "step": 1,
        "error": "",
        "learned": False,
        "progressReset": False,
        "editOriginal": values,
    }
    assert "set-cookie" not in edit.headers

    unchanged = client.post("/app/edit/commit?deck=1", json={**values, "nid": nid})
    assert unchanged.status_code == 200
    assert _signals(unchanged)["count"] == 2
    assert _signals(unchanged)["_editSaved"] is True
    assert set(_notes(client)) == before_ids
    assert "animate-slide-to-added" not in _pile(unchanged.text)
    assert "data-ts=" not in _pile(unchanged.text)

    updated = {**values, "front": "Updated <front> &\n*yes*"}
    response = client.post("/app/edit/commit?deck=1", json={**updated, "nid": nid})
    assert response.status_code == 200
    assert _signals(response) == {
        "front": "",
        "back": "",
        "hint": "",
        "example": "",
        "step": 1,
        "nid": 0,
        "learned": False,
        "_editSaved": True,
        "progressReset": False,
        "count": 2,
        "deckCount": 2,
        "error": "",
    }
    assert response.text.rfind("event: datastar-patch-elements") < response.text.rfind(
        "event: datastar-patch-signals"
    )
    assert response.text.index("Second") < response.text.index("Updated")
    assert "animate-slide-to-added" not in _pile(response.text)
    assert "data-ts=" not in _pile(response.text)
    assert "&lt;front&gt; &amp;" in response.text
    assert set(_notes(client)) == before_ids
    assert client.cookies.get("app_sid") == sid
    assert "set-cookie" not in response.headers
    reloaded = _signals(client.post(f"/app/edit/card/{nid}?deck=1"))
    assert isinstance(reloaded.pop("editLoaded"), int)
    assert reloaded == {
        **updated,
        "nid": nid,
        "step": 1,
        "error": "",
        "learned": False,
        "progressReset": False,
        "editOriginal": updated,
    }
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
    client.post("/app/edit/commit?deck=1", json={"front": "First", "back": "One"})
    nid = _notes(client)[0]
    client.post("/app/edit/commit?deck=1", json={"front": "Second", "back": "Two"})
    duplicate = client.post(
        "/app/edit/commit?deck=1",
        json={"nid": nid, "front": "Second", "back": "Changed"},
    )
    assert _signals(duplicate) == {"error": "A card with this front already exists."}
    assert "datastar-patch-elements" not in duplicate.text
    invalid = client.post(
        "/app/edit/commit?deck=1", json={"nid": nid, "front": " ", "back": "Changed"}
    )
    assert _signals(invalid) == {"error": "Front and back are required"}
    assert "datastar-patch-elements" not in invalid.text
    assert len(_notes(client)) == 2
    loaded = _signals(client.post(f"/app/edit/card/{nid}?deck=1"))
    assert isinstance(loaded.pop("editLoaded"), int)
    assert loaded == {
        "front": "First",
        "back": "One",
        "hint": "",
        "example": "",
        "nid": nid,
        "step": 1,
        "error": "",
        "learned": False,
        "progressReset": False,
        "editOriginal": {"front": "First", "back": "One", "hint": "", "example": ""},
    }


def test_update_failure_preserves_form_and_note(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.post("/app/edit/commit?deck=1", json={"front": "First", "back": "One"})
    nid = _notes(client)[0]

    def fail(*args, **kwargs):
        raise ValueError("private backend detail")

    monkeypatch.setattr("ankiweb.core.app_client.note_editing.update_vocab_note", fail)
    response = client.post(
        "/app/edit/commit?deck=1",
        json={"nid": nid, "front": "Changed", "back": "Changed"},
    )
    assert _signals(response) == {"error": "Could not add the card. Please try again."}
    assert "private backend detail" not in response.text
    assert "datastar-patch-elements" not in response.text
    assert _signals(client.post(f"/app/edit/card/{nid}?deck=1"))["front"] == "First"
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
    created = client.post("/app/edit/commit?deck=1", json=_RESET_ORIGINAL)
    assert _signals(created)["count"] == 1
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
        assert client.get("/app/edit?deck=1").status_code == 200
        sid = client.cookies.get("app_sid")
        assert sid
        nid, cid = _seed_learned_edit(client)
        learned_page = client.get("/app/edit?deck=1")
        assert _stack_ids(learned_page.text) == [nid]
        assert _list_ids(learned_page.text) == [nid]
        assert f", {learned_label}" in learned_page.text
        before = _reset_snapshot(client, nid, cid)
        edit = client.post(f"/app/edit/card/{nid}?deck=1")
        loaded = _signals(edit)
        assert isinstance(loaded.pop("editLoaded"), int)
        assert loaded == {
            **_RESET_ORIGINAL,
            "nid": nid,
            "step": 1,
            "error": "",
            "learned": True,
            "progressReset": False,
            "editOriginal": _RESET_ORIGINAL,
        }
        calls, failure = _fail_scheduler_once(client, monkeypatch, nid)
        unchanged = client.post(
            "/app/edit/commit?deck=1", json={**_RESET_ORIGINAL, "nid": nid}
        )
        assert _signals(unchanged)["progressReset"] is False
        assert _signals(unchanged)["_editSaved"] is True
        assert f", {learned_label}" in unchanged.text
        assert calls == []
        assert _reset_snapshot(client, nid, cid) == before
        assert _signals(client.post(f"/app/edit/card/{nid}?deck=1"))["learned"] is True
        submitted = {**_RESET_UPDATED, "nid": nid, "step": 3, "learned": True}
        with caplog.at_level(
            logging.ERROR, logger="ankiweb.adapters.inbound.http_app.edit"
        ):
            response = client.post("/app/edit/commit?deck=1", json=submitted)
        assert calls == [([cid], True)]
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert _signals(response) == {"error": message}
        assert "datastar-patch-elements" not in response.text
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
        page_after = client.get("/app/edit?deck=1")
        assert "count: 1" in page_after.text
        assert "Changed &lt;front&gt;" in _pile(page_after.text)
        assert client.cookies.get("app_sid") == sid
        client.cookies.clear()

    with TestClient(create_app(settings)) as client:
        assert _reset_pending(client) == marker
        assert _reset_snapshot(client, nid, cid) == (fields, schedule)
        reopened = client.post(f"/app/edit/card/{nid}?deck=1")
        fresh_sid = client.cookies.get("app_sid")
        assert fresh_sid and fresh_sid != sid
        reopened_signals = _signals(reopened)
        assert reopened_signals["learned"] is True
        assert {key: reopened_signals[key] for key in _RESET_UPDATED} == _RESET_UPDATED
        assert _reset_pending(client) == marker
        retry = client.post("/app/edit/commit?deck=1", json=submitted)
        assert retry.status_code == 200
        assert _signals(retry)["progressReset"] is True
        assert _signals(retry)["_editSaved"] is True
        assert _signals(retry)["count"] == 0
        assert _signals(retry)["deckCount"] == 1
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
        unchanged = client.post("/app/edit/commit?deck=1", json=submitted)
        assert _signals(unchanged)["progressReset"] is False
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
        assert _signals(client.post(f"/app/edit/card/{nid}?deck=1"))["learned"] is True
        calls, _ = _fail_scheduler_once(client, monkeypatch, nid)
        submitted = {**_RESET_UPDATED, "nid": nid, "step": 3}
        failed = client.post("/app/edit/commit?deck=1", json=submitted)
        assert _signals(failed) == {"error": message}
        _assert_reset_marker(_reset_pending(client), nid)
        retry = client.post("/app/edit/commit?deck=1", json=submitted)
        assert retry.status_code == 200
        assert _signals(retry)["progressReset"] is True
        assert _signals(retry)["_editSaved"] is True
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
        assert _signals(client.post(f"/app/edit/card/{nid}?deck=1"))["learned"] is True
        calls, _ = _fail_scheduler_once(client, monkeypatch, nid)
        failure = _reject_reset_config(monkeypatch, clear=False)
        with caplog.at_level(
            logging.ERROR, logger="ankiweb.adapters.inbound.http_app.edit"
        ):
            response = client.post(
                "/app/edit/commit?deck=1", json={**_RESET_UPDATED, "nid": nid}
            )
        assert response.status_code == 200
        assert _signals(response) == {"error": message}
        assert "datastar-patch-elements" not in response.text
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
        response = client.post(
            "/app/edit/commit?deck=1", json={**_RESET_UPDATED, "nid": nid}
        )
        assert _signals(response) == {"error": message}
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
        response = client.post("/app/edit/commit?deck=1", json=submitted)
        assert _signals(response) == {"error": message}
        assert calls == [([cid], True)]
        _assert_reset_marker(_reset_pending(client), nid)
        fields, reset = _reset_snapshot(client, nid, cid)
        assert fields == [escape_field(value) for value in _RESET_UPDATED.values()]
        assert reset[:2] == (0, 0)
        assert reset[5:] == (0, 0)
        loaded = _signals(client.post(f"/app/edit/card/{nid}?deck=1"))
        assert loaded["learned"] is False
        retry = client.post("/app/edit/commit?deck=1", json=submitted)
        assert _signals(retry)["progressReset"] is True
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
                client.post(
                    "/app/edit/commit?deck=1",
                    json={**_RESET_UPDATED, "nid": nid},
                )
        marker = _reset_pending(client)
        _assert_reset_marker(marker, nid)
        assert _reset_snapshot(client, nid, cid) == before
        unchanged = client.post(
            "/app/edit/commit?deck=1", json={**_RESET_ORIGINAL, "nid": nid}
        )
        assert _signals(unchanged)["progressReset"] is False
        assert _reset_pending(client) == marker
        assert _reset_snapshot(client, nid, cid) == before
        recovered = client.post(
            "/app/edit/commit?deck=1", json={**_RESET_UPDATED, "nid": nid}
        )
        assert _signals(recovered)["progressReset"] is True
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
            response = client.post(
                "/app/edit/commit?deck=1", json={**_RESET_UPDATED, "nid": nid}
            )
        assert response.status_code == 200
        assert _signals(response) == {"error": message}
        assert "datastar-patch-elements" not in response.text
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
    client.post("/app/edit/commit?deck=1", json={"front": "First", "back": "One"})
    nid = _notes(client)[0]
    original_sid = client.cookies.get("app_sid")
    assert original_sid
    client.cookies.clear()
    edit = client.post(f"/app/edit/card/{nid}?deck=1")
    assert edit.status_code == 200
    assert _signals(edit)["front"] == "First"
    assert edit.headers["content-type"].startswith("text/event-stream")
    assert "app_sid" in edit.cookies
    assert "HttpOnly" in edit.headers["set-cookie"]
    new_sid = client.cookies.get("app_sid")
    assert new_sid and new_sid != original_sid
    update = client.post(
        "/app/edit/commit?deck=1",
        json={"nid": nid, "front": "Changed", "back": "Changed"},
    )
    assert update.status_code == 200
    assert _signals(update)["count"] == 0
    assert client.cookies.get("app_sid") == new_sid
    client.cookies.clear()
    client.cookies.set("app_sid", original_sid)
    assert _signals(client.post(f"/app/edit/card/{nid}?deck=1"))["front"] == "Changed"
    assert len(_notes(client)) == 1


def test_edit_missing_note_returns_localized_error_and_session_cookie(
    tmp_path: Path,
) -> None:
    settings = Settings(collection_path=tmp_path / "de-edit.anki2", lang="de_DE")
    try:
        with TestClient(create_app(settings)) as client:
            response = client.post("/app/edit/card/123456789?deck=1")
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
    client.post("/app/edit/commit?deck=1", json={"front": "First", "back": "One"})
    nid = _notes(client)[0]
    client.cookies.clear()
    response = client.post(
        "/app/edit/commit?deck=1",
        json={"nid": nid, "front": "Changed", "back": "Changed"},
    )
    assert response.status_code == 200
    assert _signals(response)["count"] == 0
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
    client.post("/app/edit/commit?deck=1", json={"front": "Moved", "back": "One"})
    nid = _notes(client)[0]

    def move(col: Collection) -> None:
        col.set_deck([card.id for card in col.get_note(nid).cards()], other_deck)

    client.portal.call(service.run, move)
    assert client.post(f"/app/edit/card/{nid}?deck=1").status_code == 404
    denied = client.post(
        "/app/edit/commit?deck=1",
        json={"nid": nid, "front": "Changed", "back": "One"},
    )
    assert denied.status_code == 404
    assert _signals(client.post(f"/app/edit/card/{nid}?deck={other_deck}"))[
        "front"
    ] == ("Moved")
    updated = client.post(
        f"/app/edit/commit?deck={other_deck}",
        json={"nid": nid, "front": "Changed", "back": "One"},
    )
    assert _signals(updated)["count"] == 1
    assert set(_notes(client)) == {nid}
    client.portal.call(service.run, lambda col: col.remove_notes([nid]))
    assert client.post(f"/app/edit/card/{nid}?deck={other_deck}").status_code == 404
    stale = client.post(
        f"/app/edit/commit?deck={other_deck}",
        json={"nid": nid, "front": "Stale", "back": "One"},
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
    client.post("/app/edit/commit?deck=1", json={"front": "Typed", "back": "One"})
    nid = _notes(client)[0]

    client.portal.call(
        cast(FastAPI, client.app).state.service.run,
        lambda col: _change_note_type(col, [nid]),
    )
    assert client.post(f"/app/edit/card/{nid}?deck=1").status_code in (404, 409)
    response = client.post(
        "/app/edit/commit?deck=1",
        json={"nid": nid, "front": "Changed", "back": "Changed"},
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

    saved = client.post(
        "/app/edit/commit?deck=1", json={"front": "New", "back": "Answer"}
    )
    assert _signals(saved)["count"] == 1
    assert ">New</span>" in saved.text
    assert ">Typed</span>" not in saved.text
    page = client.get("/app/edit?deck=1")
    assert "count: 1" in page.text
    assert ">New</span>" in page.text
    assert ">Typed</span>" not in page.text


@pytest.mark.parametrize("query", ["", "?deck=nope", "?deck=999999999"])
def test_edit_rejects_invalid_deck(client: TestClient, query: str) -> None:
    response = client.post(f"/app/edit/card/1{query}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/app/"
    assert "app_sid" not in response.cookies
