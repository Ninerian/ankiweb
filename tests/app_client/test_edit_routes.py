import json
import re
from pathlib import Path
from typing import Protocol, cast

import anki.lang
import pytest
from anki.collection import Collection
from anki.decks import DeckId
from anki.notes import NoteId
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ankiweb.app import create_app
from ankiweb.core.app_client.vocab import NOTETYPE_NAME, escape_field, highlight_example
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
    assert 'data-signals="{step: 1, front:' in page.text
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
            assert response.headers["location"] == "/login"
            assert "app_sid" not in response.cookies
        client.cookies.set(COOKIE, auth_token(password))
        assert client.get("/app/edit?deck=1").status_code == 200
        assert client.post("/app/edit/preview", json={}).status_code == 200
        assert client.post("/app/edit/commit?deck=1", json={}).status_code == 200


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", "/app/add?deck=1"),
        ("POST", "/app/add/preview"),
        ("POST", "/app/add/commit?deck=1"),
        ("POST", "/app/add/edit/1?deck=1"),
    ],
)
def test_old_app_editor_routes_are_absent(
    client: TestClient, method: str, url: str
) -> None:
    assert client.request(method, url, follow_redirects=False).status_code == 404


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
    assert _signals(response) == {
        "front": "",
        "back": "",
        "hint": "",
        "example": "",
        "step": 1,
        "nid": 0,
        "count": 1,
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


def test_added_cards_are_scoped_to_session_and_deck(client: TestClient) -> None:
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
    assert ">B</p>" in second.text
    assert ">A</p>" not in second.text
    assert ">A</p>" in client.get("/app/edit?deck=1").text
    other_page = client.get(f"/app/edit?deck={other_deck}")
    assert ">B</p>" in other_page.text
    assert _badge(other_page.text) == "1 card"
    assert ">A</p>" not in other_page.text
    denied = client.post(
        f"/app/edit/commit?deck={other_deck}",
        json={"nid": first_nid, "front": "Changed", "back": "changed"},
    )
    assert denied.status_code == 404
    assert _signals(denied) == {"error": "Could not add the card. Please try again."}
    assert len(_notes(client)) == 2
    assert ">A</p>" in client.get("/app/edit?deck=1").text

    client.cookies.clear()
    empty_page = client.get("/app/edit?deck=1")
    assert "count: 0" in empty_page.text
    assert ">A</p>" not in empty_page.text
    assert "No cards added yet" in empty_page.text
    assert "add-stack-badge" not in empty_page.text
    denied = client.post(
        "/app/edit/commit?deck=1",
        json={"nid": first_nid, "front": "Changed", "back": "changed"},
    )
    assert denied.status_code == 404
    assert _signals(denied) == {"error": "Could not add the card. Please try again."}
    third = client.post("/app/edit/commit?deck=1", json={"front": "C", "back": "c"})
    assert _signals(third)["count"] == 1
    assert _badge(third.text) == "1 card"
    assert ">C</p>" in third.text
    assert ">A</p>" not in third.text

    client.cookies.clear()
    client.cookies.set("app_sid", session_a)
    page = client.get("/app/edit?deck=1")
    assert "count: 1" in page.text
    assert _badge(page.text) == "1 card"
    assert ">A</p>" in page.text
    assert ">C</p>" not in page.text
    assert len(_notes(client)) == 3


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


def test_added_stack_shows_latest_four_and_counts_all(client: TestClient) -> None:
    for index in range(5):
        response = client.post(
            "/app/edit/commit?deck=1",
            json={"front": f"Front {index}", "back": f"Back {index}"},
        )
        assert _signals(response)["count"] == index + 1
    assert "Front 0" not in response.text
    for index in range(1, 5):
        assert f"Front {index}" in response.text
    assert response.text.index("Front 4") < response.text.index("Front 3")
    assert response.text.index("add-stack-badge") < response.text.index("Front 4")
    assert _badge(response.text) == "5 cards"
    assert response.text.count("add-stack-badge") == 1
    page = client.get("/app/edit?deck=1")
    assert "count: 5" in page.text
    assert _badge(page.text) == "5 cards"
    assert "Front 0" not in page.text
    assert "Front 4" in page.text

    match = re.search(r'data-note-id="(\d+)"', response.text)
    assert match is not None
    assert client.portal is not None
    nid = NoteId(int(match.group(1)))
    client.portal.call(
        cast(FastAPI, client.app).state.service.run, lambda col: col.remove_notes([nid])
    )
    page = client.get("/app/edit?deck=1")
    assert "count: 4" in page.text
    assert _badge(page.text) == "4 cards"
    assert "Front 0" in page.text
    assert "Front 4" not in page.text


def test_added_cards_span_query_batches(client: TestClient) -> None:
    for index in range(33):
        response = client.post(
            "/app/edit/commit?deck=1",
            json={"front": f"Batch {index}", "back": "Answer"},
        )
    assert _signals(response)["count"] == 33
    page = client.get("/app/edit?deck=1")
    assert "count: 33" in page.text
    assert "Batch 28" not in page.text
    for index in range(29, 33):
        assert f"Batch {index}" in page.text


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
        match = re.search(r'data-note-id="(\d+)"', response.text)
        assert match is not None
        return NoteId(int(match.group(1)))

    first = add(1, "First")
    add(other_deck, "Other")
    last = add(1, "Last")
    client.portal.call(service.run, lambda col: col.remove_notes([last]))

    page = client.get("/app/edit?deck=1")
    assert "count: 1" in page.text
    assert ">First</p>" in page.text
    assert ">Last</p>" not in page.text
    other_page = client.get(f"/app/edit?deck={other_deck}")
    assert "count: 1" in other_page.text
    assert ">Other</p>" in other_page.text

    response = client.post(
        "/app/edit/commit?deck=1", json={"front": "New", "back": "Answer"}
    )
    assert _signals(response)["count"] == 2
    assert ">New</p>" in response.text
    assert ">First</p>" in response.text
    assert ">Last</p>" not in response.text
    client.portal.call(service.run, lambda col: col.remove_notes([first]))
    assert "count: 1" in client.get("/app/edit?deck=1").text
    assert ">Other</p>" in client.get(f"/app/edit?deck={other_deck}").text


def test_changed_note_types_are_excluded_from_session_stack(
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
        match = re.search(r'data-note-id="(\d+)"', response.text)
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
    for index in (2, 3, 4, 6):
        assert f">Front {index}</p>" in page.text
    for index in (0, 1, 5):
        assert f">Front {index}</p>" not in page.text
    assert page.text.index(">Front 6</p>") < page.text.index(">Front 4</p>")
    other_page = client.get(f"/app/edit?deck={other_deck}")
    assert "count: 1" in other_page.text
    assert ">Other deck</p>" in other_page.text

    saved = client.post(
        "/app/edit/commit?deck=1", json={"front": "Front 7", "back": "Back 7"}
    )
    assert saved.status_code == 200
    assert _signals(saved)["count"] == 6
    for index in (3, 4, 6, 7):
        assert f">Front {index}</p>" in saved.text
    for index in (0, 1, 2, 5):
        assert f">Front {index}</p>" not in saved.text
    assert "count: 6" in client.get("/app/edit?deck=1").text

    client.cookies.clear()
    client.cookies.set("app_sid", separate_sid)
    separate_page = client.get("/app/edit?deck=1")
    assert "count: 1" in separate_page.text
    assert ">Other session</p>" in separate_page.text
    assert ">Front 7</p>" not in separate_page.text


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
    assert "count: 0" in client.get("/app/edit?deck=1").text
    other_page = client.get(f"/app/edit?deck={other_deck}")
    assert "count: 1" in other_page.text
    assert ">Moved</p>" in other_page.text

    client.portal.call(service.run, lambda col: move(col, DeckId(1)))
    assert "count: 0" in client.get(f"/app/edit?deck={other_deck}").text
    page = client.get("/app/edit?deck=1")
    assert "count: 1" in page.text
    assert ">Moved</p>" in page.text


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
    nid = _notes(client)[0]
    client.post("/app/edit/commit?deck=1", json={"front": "Second", "back": "Two"})
    before_ids = set(_notes(client))
    sid = client.cookies.get("app_sid")

    edit = client.post(f"/app/edit/card/{nid}?deck=1")
    assert edit.status_code == 200
    assert edit.headers["content-type"].startswith("text/event-stream")
    assert _signals(edit) == {**values, "nid": nid, "step": 1, "error": ""}
    assert "set-cookie" not in edit.headers

    unchanged = client.post("/app/edit/commit?deck=1", json={**values, "nid": nid})
    assert unchanged.status_code == 200
    assert _signals(unchanged)["count"] == 2
    assert set(_notes(client)) == before_ids

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
        "count": 2,
        "error": "",
    }
    assert response.text.index("Second") < response.text.index("Updated")
    assert "&lt;front&gt; &amp;" in response.text
    assert set(_notes(client)) == before_ids
    assert client.cookies.get("app_sid") == sid
    assert "set-cookie" not in response.headers
    assert _signals(client.post(f"/app/edit/card/{nid}?deck=1")) == {
        **updated,
        "nid": nid,
        "step": 1,
        "error": "",
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
    assert _signals(client.post(f"/app/edit/card/{nid}?deck=1")) == {
        "front": "First",
        "back": "One",
        "hint": "",
        "example": "",
        "nid": nid,
        "step": 1,
        "error": "",
    }


def test_update_failure_preserves_form_and_note(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.post("/app/edit/commit?deck=1", json={"front": "First", "back": "One"})
    nid = _notes(client)[0]

    def fail(*args, **kwargs):
        raise ValueError("private backend detail")

    monkeypatch.setattr(
        "ankiweb.adapters.inbound.http_app.edit.update_vocab_note", fail
    )
    response = client.post(
        "/app/edit/commit?deck=1",
        json={"nid": nid, "front": "Changed", "back": "Changed"},
    )
    assert _signals(response) == {"error": "Could not add the card. Please try again."}
    assert "private backend detail" not in response.text
    assert "datastar-patch-elements" not in response.text
    assert _signals(client.post(f"/app/edit/card/{nid}?deck=1"))["front"] == "First"
    assert set(_notes(client)) == {nid}


def test_edit_and_update_reject_cross_session_and_preserve_new_cookie(
    client: TestClient,
) -> None:
    client.post("/app/edit/commit?deck=1", json={"front": "First", "back": "One"})
    nid = _notes(client)[0]
    original_sid = client.cookies.get("app_sid")
    assert original_sid
    client.cookies.clear()
    edit = client.post(f"/app/edit/card/{nid}?deck=1")
    assert edit.status_code == 404
    assert edit.text == "This card is unavailable for editing. Please try again."
    assert edit.headers["content-type"].startswith("text/plain")
    assert "app_sid" in edit.cookies
    assert "HttpOnly" in edit.headers["set-cookie"]
    new_sid = client.cookies.get("app_sid")
    assert new_sid and new_sid != original_sid
    update = client.post(
        "/app/edit/commit?deck=1", json={"nid": nid, "front": "", "back": "Changed"}
    )
    assert update.status_code == 404
    assert _signals(update) == {"error": "Could not add the card. Please try again."}
    assert "datastar-patch-elements" not in update.text
    assert client.cookies.get("app_sid") == new_sid
    client.cookies.clear()
    client.cookies.set("app_sid", original_sid)
    assert _signals(client.post(f"/app/edit/card/{nid}?deck=1"))["front"] == "First"
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


def test_unauthorized_update_sets_new_session_cookie(client: TestClient) -> None:
    client.post("/app/edit/commit?deck=1", json={"front": "First", "back": "One"})
    nid = _notes(client)[0]
    client.cookies.clear()
    response = client.post(
        "/app/edit/commit?deck=1",
        json={"nid": nid, "front": "Changed", "back": "Changed"},
    )
    assert response.status_code == 404
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
    assert ">New</p>" in saved.text
    assert ">Typed</p>" not in saved.text
    page = client.get("/app/edit?deck=1")
    assert "count: 1" in page.text
    assert ">New</p>" in page.text
    assert ">Typed</p>" not in page.text


@pytest.mark.parametrize("query", ["", "?deck=nope", "?deck=999999999"])
def test_edit_rejects_invalid_deck(client: TestClient, query: str) -> None:
    response = client.post(f"/app/edit/card/1{query}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/app/"
    assert "app_sid" not in response.cookies
