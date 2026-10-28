import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path

import pytest
from anki.cards import CardId
from anki.collection import Collection
from conftest import parse_datastar_events
from fastapi.testclient import TestClient

from ankiweb.app import create_app
from ankiweb.core.app_client import study
from ankiweb.core.config import Settings


@pytest.fixture
def client(client: TestClient) -> TestClient:
    client.headers["Datastar-Request"] = "true"
    return client


def run(client, fn):
    assert client.portal is not None
    return client.portal.call(client.app.state.service.run, fn)


def seed(client, count=3, front=None):
    def add(col: Collection):
        deck = col.decks.id("Route review")
        model = col.models.by_name("Basic")
        assert deck is not None and model is not None
        ids = []
        for number in range(count):
            note = col.new_note(model)
            note["Front"] = front if front is not None else f"Question {number}"
            note["Back"] = f"Answer {number}"
            col.add_note(note, deck)
            ids.append(int(note.cards()[0].id))
        return int(deck), ids

    return run(client, add)


def open_review(client, deck):
    response = client.get("/app/review", params={"deck": deck})
    assert response.status_code == 200
    match = re.search(r"cardId:\s*(\d+)", response.text)
    assert match
    return response, int(match.group(1))


def next_card(response):
    for line in response.text.splitlines():
        if line.startswith("data: signals "):
            return int(json.loads(line.removeprefix("data: signals "))["cardId"])
    raise AssertionError("missing signal patch")


class _ElementText(HTMLParser):
    def __init__(self, element_id: str) -> None:
        super().__init__()
        self.element_id = element_id
        self.tag: str | None = None
        self.depth = 0
        self.parts: list[str] = []
        self.found = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.depth and tag == self.tag:
            self.depth += 1
        elif not self.found and dict(attrs).get("id") == self.element_id:
            self.found = True
            self.tag = tag
            self.depth = 1

    def handle_endtag(self, tag: str) -> None:
        if self.depth and tag == self.tag:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.parts.append(data)


def _element_text(response, element_id: str) -> str | None:
    parser = _ElementText(element_id)
    if response.headers["content-type"].startswith("text/event-stream"):
        for event_type, data in parse_datastar_events(response.text):
            if event_type == "datastar-patch-elements":
                fragment = "\n".join(
                    line.removeprefix("elements ")
                    for line in data.splitlines()
                    if line.startswith("elements ")
                )
                parser.feed(fragment)
    else:
        parser.feed(response.text)
    parser.close()
    return "".join(parser.parts).strip() if parser.found else None


def answer(client, card, ease=4):
    return client.post("/app/review/answer", json={"cardId": card, "ease": ease})


def test_get_renders_both_sides_and_interval_labels_and_no_store(client):
    deck, _ = seed(client)
    page, card = open_review(client, deck)
    assert card
    assert page.headers["cache-control"] == "no-store"
    assert page.cookies.get("app_sid")
    assert "HttpOnly" in page.headers["set-cookie"]
    assert "Question 0" in page.text and "Answer 0" in page.text
    assert 'id="answer-box"' in page.text
    assert all(f'id="ease-{n}"' in page.text for n in range(1, 5))
    assert "\u2068" not in page.text and "\u2069" not in page.text
    assert "/ws" not in page.text and "/_anki/" not in page.text


def test_answer_patches_all_targets_broadcasts_and_records_time(client):
    deck, _ = seed(client)
    _, card = open_review(client, deck)
    broadcasts = []
    client.app.state.service.subscribe(
        lambda flags, initiator: broadcasts.append((flags, initiator))
    )
    time.sleep(0.05)
    response = answer(client, card, 3)
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "datastar-patch-elements" in response.text
    for target in ("#stage", "#bar", "#hud-progress", "#sheet"):
        assert f"selector {target}" in response.text
    assert "datastar-patch-signals" in response.text
    assert next_card(response) != card
    assert run(client, lambda col: col.db.scalar("select count() from revlog")) == 1
    assert run(client, lambda col: col.db.scalar("select time from revlog")) >= 40
    assert any(
        initiator == "app" and any(flags.values()) for flags, initiator in broadcasts
    )


def test_invalid_decks_redirect_without_starting(client):
    for query in (
        "",
        "?deck=nope",
        "?deck=0",
        "?deck=-1",
        "?deck=9999999999999999999",
        "?deck=999999999999999999",
    ):
        response = client.get("/app/review" + query, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/app/"
        assert response.headers["cache-control"] == "no-store"


def test_bad_commands_and_stale_tabs_are_rejected(client):
    deck, _ = seed(client)
    _, card = open_review(client, deck)
    for ease in (0, 5):
        assert answer(client, card, ease).status_code == 422
    assert (
        client.post(
            "/app/review/answer", json={"cardId": card, "ease": "3"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/app/review/answer", json={"cardId": card + 1, "ease": 4}
        ).status_code
        == 409
    )
    assert (
        client.post("/app/review/action/undo", json={"cardId": card + 1}).status_code
        == 409
    )
    assert (
        client.post("/app/review/action/mark", json={"cardId": card + 1}).status_code
        == 409
    )
    assert (
        client.post(
            "/app/review/due", json={"cardId": card + 1, "spec": "3"}
        ).status_code
        == 409
    )
    assert (
        client.post("/app/review/action/nope", json={"cardId": card}).status_code == 404
    )
    assert (
        client.post(
            "/app/review/action/flag", json={"cardId": card, "flag": 5}
        ).status_code
        == 422
    )
    assert run(client, lambda col: col.db.scalar("select count() from revlog")) == 0


def test_last_answer_completes_and_fresh_session_is_empty(client):
    deck, _ = seed(client, count=1)
    _, card = open_review(client, deck)
    response = answer(client, card, 4)
    assert response.status_code == 200
    assert 'id="session-complete"' in response.text
    assert "Flawless!" in response.text and "Reviewed" in response.text
    assert "selector #stage" in response.text and "selector #bar" in response.text
    assert 'id="current-card"' not in response.text
    assert "Study again" not in response.text
    assert run(client, lambda col: col.db.scalar("select count() from revlog")) == 1
    client.cookies.clear()
    page, next_id = open_review(client, deck)
    assert next_id == 0
    assert "No cards due" in page.text and "Flawless!" not in page.text
    assert _element_text(page, "streak-count") == "1"


def test_empty_queue_is_not_a_completed_session(client):
    deck, _ = seed(client, count=0)
    page, card = open_review(client, deck)
    assert card == 0
    assert "No cards due" in page.text
    assert "Flawless!" not in page.text and "Reviewed" not in page.text


def test_undo_restores_card_and_revlog_and_does_not_count_rating(client):
    deck, _ = seed(client, count=2)
    _, first = open_review(client, deck)
    rated = answer(client, first, 4)
    second = next_card(rated)
    response = client.post("/app/review/action/undo", json={"cardId": second})
    assert response.status_code == 200
    assert next_card(response) == first
    assert run(client, lambda col: col.db.scalar("select count() from revlog")) == 0
    rated_again = answer(client, first, 4)
    final = answer(client, next_card(rated_again), 4)
    assert "Flawless!" in final.text
    assert re.search(r'id="sc-reviewed"[^>]*>2<', final.text)


def test_new_start_resets_session_tally_but_streak_is_daily(client):
    deck, _ = seed(client, count=2)
    _, card = open_review(client, deck)
    assert answer(client, card, 4).status_code == 200
    page, card = open_review(client, deck)
    assert _element_text(page, "streak-count") == "1"
    completed = answer(client, card, 4)
    assert _element_text(completed, "streak-count") == "2"
    assert _element_text(completed, "sc-reviewed") == "1"


def test_again_displays_reset_toast_even_without_a_prior_streak(client):
    deck, _ = seed(client, count=2)
    _, card = open_review(client, deck)
    response = answer(client, card, 1)
    assert response.status_code == 200
    assert "Streak Reset!" in response.text
    assert 'id="streak-count">0<' in response.text


def test_intervening_mark_undo_preserves_session_tally(client):
    deck, _ = seed(client, count=3)
    _, first = open_review(client, deck)
    second = next_card(answer(client, first, 4))
    marked = client.post("/app/review/action/mark", json={"cardId": second})
    assert next_card(marked) == second
    assert '"revealed"' not in next(
        line for line in marked.text.splitlines() if line.startswith("data: signals ")
    )
    undone = client.post("/app/review/action/undo", json={"cardId": second})
    assert next_card(undone) == second
    assert run(client, lambda col: col.db.scalar("select count() from revlog")) == 1
    third = next_card(answer(client, second, 4))
    completed = answer(client, third, 4)
    assert re.search(r'id="sc-reviewed"[^>]*>3<', completed.text)


@pytest.mark.parametrize(
    "action", ["mark", "flag", "bury", "suspend", "forget", "delete"]
)
def test_card_actions_execute_and_broadcast(client, action):
    deck, _ = seed(client, count=2)
    _, card = open_review(client, deck)
    broadcasts = []
    client.app.state.service.subscribe(
        lambda flags, initiator: broadcasts.append((flags, initiator))
    )
    response = client.post(
        f"/app/review/action/{action}", json={"cardId": card, "flag": 1}
    )
    assert response.status_code == 200 and "datastar-patch-elements" in response.text
    assert any(
        initiator == "app" and any(flags.values()) for flags, initiator in broadcasts
    )
    if action == "delete":
        assert (
            run(
                client,
                lambda col: col.db.scalar(
                    "select count() from cards where id = ?", card
                ),
            )
            == 0
        )
    elif action == "mark":
        assert run(
            client, lambda col: col.get_card(CardId(card)).note().has_tag("marked")
        )
    elif action == "flag":
        assert run(client, lambda col: col.get_card(CardId(card)).user_flag()) == 1
    elif action in ("bury", "suspend"):
        assert run(client, lambda col: col.get_card(CardId(card)).queue) < 0


def test_due_validation_and_info_redirect(client):
    deck, _ = seed(client)
    _, card = open_review(client, deck)
    bad = client.post("/app/review/due", json={"cardId": card, "spec": "not a date"})
    assert bad.status_code == 200 and "datastar-patch-signals" in bad.text
    assert '"error"' in bad.text
    info = client.get(f"/app/review/info/{card}", follow_redirects=False)
    assert info.status_code == 303 and info.headers["location"] == f"/card-info/{card}"
    ok = client.post("/app/review/due", json={"cardId": card, "spec": "3"})
    assert ok.status_code == 200 and next_card(ok) != card


def test_nothing_to_undo_is_a_toast(client, monkeypatch):
    deck, _ = seed(client)
    _, card = open_review(client, deck)

    def empty(*args):
        raise study.NothingToUndo()

    monkeypatch.setattr(study, "undo", empty)
    result = client.post("/app/review/action/undo", json={"cardId": card})
    assert result.status_code == 200 and "Nothing to undo" in result.text


def test_hostile_note_html_is_not_executable_or_in_summary(client):
    deck, _ = seed(client, count=1, front="<script>alert(1)</script><b>hello</b>")
    page, card = open_review(client, deck)
    assert "<script>alert(1)</script>" not in page.text
    completed = answer(client, card, 4)
    assert "alert(1)" not in completed.text


def test_review_inherits_password_gate(tmp_path: Path):
    password = f"test-{tmp_path.name}"
    app = create_app(
        Settings(collection_path=tmp_path / "private.anki2", password=password)
    )
    with TestClient(app) as client:
        for method, url in (
            ("GET", "/app/review?deck=1"),
            ("POST", "/app/review/answer"),
        ):
            response = client.request(method, url, follow_redirects=False)
            assert (
                response.status_code == 303 and response.headers["location"] == "/login"
            )
