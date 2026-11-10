import asyncio
import re
import socket
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

import pytest
import uvicorn
from anki.cards import CardId
from anki.collection import Collection
from anki.consts import MODEL_STD, CardQueue, CardType
from anki.decks import DeckId
from anki.notes import NoteId
from anki.scheduler.v3 import Scheduler
from fastapi import FastAPI

from ankiweb.app import create_app
from ankiweb.core.app_client.deck_languages import LanguagePair, apply_marker
from ankiweb.core.app_client.vocab import add_vocab_note
from ankiweb.core.config import Settings

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import (
    ConsoleMessage,
    Dialog,
    Locator,
    Page,
    Route,
    expect,
    sync_playwright,
)


@pytest.fixture
def page() -> Iterator[Page]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--mute-audio"])
        context = browser.new_context(viewport={"width": 375, "height": 812})
        try:
            yield context.new_page()
        finally:
            context.close()
            browser.close()


def _snapshot(col: Collection) -> list[tuple[int, list[str], int]]:
    notes = []
    for nid in sorted(col.find_notes("")):
        note = col.get_note(nid)
        notes.append(
            (
                nid,
                [note[field] for field in ("Front", "Back", "Hint", "Example")],
                note.cards()[0].did,
            )
        )
    return notes


class LiveApp:
    def __init__(
        self,
        url: str,
        path: Path,
        app: FastAPI,
        server: uvicorn.Server,
        thread: threading.Thread,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.url = url
        self.path = path
        self.app = app
        self.server = server
        self.thread = thread
        self.loop = loop

    def __str__(self) -> str:
        return self.url

    def notes(self) -> list[tuple[int, list[str], int]]:
        return asyncio.run_coroutine_threadsafe(
            self.app.state.service.run(_snapshot), self.loop
        ).result(timeout=10)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            raise RuntimeError("server did not stop")

    def persisted_notes(self) -> list[tuple[int, list[str], int]]:
        self.stop()
        col = Collection(str(self.path))
        try:
            return _snapshot(col)
        finally:
            col.close()


@pytest.fixture
def live_app(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[LiveApp]:
    path = tmp_path / "live.anki2"
    app = create_app(Settings(collection_path=path, lang=getattr(request, "param", "")))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    loop_ready: Future[asyncio.AbstractEventLoop] = Future()

    async def serve(listener: socket.socket) -> None:
        loop_ready.set_result(asyncio.get_running_loop())
        await server.serve(sockets=[listener])

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        thread = threading.Thread(
            target=lambda: asyncio.run(serve(listener)), daemon=True
        )
        thread.start()
        loop = loop_ready.result(timeout=10)
        live = LiveApp(f"http://127.0.0.1:{port}", path, app, server, thread, loop)
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("server did not start")
                time.sleep(0.05)
            yield live
        finally:
            live.stop()


def _front(page: Page) -> Locator:
    return page.get_by_label("Front (Question / Prompt)", exact=True)


def _back(page: Page) -> Locator:
    return page.get_by_label("Back (Answer / Meaning)", exact=True)


def _wait_for_back(page: Page) -> None:
    back = page.locator("#input-back")
    expect(back).to_be_visible()
    expect(back).to_be_editable()


def _to_preview(page: Page, front: str, back: str) -> None:
    _front(page).fill(front)
    _front(page).press("Enter")
    _wait_for_back(page)
    _back(page).fill(back)
    _back(page).press("Enter")
    expect(page.get_by_role("button", name="Add", exact=True)).to_be_visible()
    expect(page.locator("#preview")).to_contain_text(front)
    expect(page.locator("#preview")).to_contain_text(back)


def _add(page: Page, front: str = "Hund", back: str = "dog") -> None:
    _to_preview(page, front, back)
    page.get_by_role("button", name="Add", exact=True).click()
    expect(_front(page)).to_be_visible()
    expect(_front(page)).to_have_value("")
    expect(page.locator("#added-cards")).to_contain_text(front)


def _respond_to_confirm(page: Page, *, accept: bool) -> list[str]:
    messages: list[str] = []

    def respond(dialog: Dialog) -> None:
        assert dialog.type == "confirm"
        messages.append(dialog.message)
        if accept:
            dialog.accept()
        else:
            dialog.dismiss()

    page.once("dialog", respond)
    return messages


def _run[T](live_app: LiveApp, operation: Callable[[Collection], T]) -> T:
    return asyncio.run_coroutine_threadsafe(
        live_app.app.state.service.run(operation), live_app.loop
    ).result(timeout=10)


def _progress(live_app: LiveApp, nid: NoteId) -> tuple[int, ...]:
    def snapshot(col: Collection) -> tuple[int, ...]:
        card = col.get_note(nid).cards()[0]
        return (
            card.type,
            card.queue,
            card.due,
            card.ivl,
            card.factor,
            card.reps,
            card.lapses,
        )

    return _run(live_app, snapshot)


def test_wizard_add_reload_and_session_isolation(page: Page, live_app: LiveApp) -> None:
    page.goto(f"{live_app}/app/edit/1/front")
    front = "a < b & c"
    _front(page).fill(front)
    _front(page).press("Enter")
    _wait_for_back(page)
    _back(page).fill("Answer & meaning")
    page.get_by_text("Hint · Optional", exact=True).click()
    page.get_by_label("Hint", exact=True).fill("noun <feminine>")
    page.get_by_text("Example sentence · Optional", exact=True).click()
    example = page.get_by_label("Example sentence", exact=True)
    example.fill("A *word*")
    example.press("Shift+Enter")
    example.press_sequentially("Second line 😀")
    expect(example).to_have_value("A *word*\nSecond line 😀")
    _back(page).press("Enter")
    preview = page.locator("#preview")
    expect(preview).to_contain_text(front)
    expect(preview.locator("mark")).to_have_text("word")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(_front(page)).to_be_visible()
    expect(_front(page)).to_have_value("")
    expect(_back(page)).to_have_value("")
    expect(page.get_by_label("Hint", exact=True)).to_have_value("")
    expect(page.get_by_label("Example sentence", exact=True)).to_have_value("")
    expect(page.get_by_role("button", name="Add", exact=True)).not_to_be_visible()
    expect(page.locator("#deck-cards")).not_to_be_visible()
    expect(page.locator("#added-cards .add-stack-count")).to_have_text("1")
    expect(page.locator("#added-cards")).to_contain_text(front)
    saved = live_app.notes()
    assert len(saved) == 1
    assert saved[0][1] == [
        "a &lt; b &amp; c",
        "Answer &amp; meaning",
        "noun &lt;feminine&gt;",
        "A *word*<br>Second line 😀",
    ]
    assert saved[0][2] == 1

    page.reload()
    expect(page.locator("#added-cards")).to_contain_text(front)
    expect(page.locator("#added-cards .add-stack-count")).to_have_text("1")
    expect(_front(page)).to_have_value("")
    assert live_app.notes() == saved

    # A new session sees the persisted deck, but has no session additions.
    browser = page.context.browser
    assert browser is not None
    isolated = browser.new_context()
    try:
        other = isolated.new_page()
        other.goto(f"{live_app}/app/edit/1/front")
        expect(other.locator("#added-cards")).to_contain_text(front)
        expect(other.locator("#added-cards .add-stack-count")).to_have_text("1")
        other.get_by_role("button", name="Done", exact=True).click()
        expect(other).to_have_url(f"{live_app}/app/edit/1/front")
        summary = other.get_by_role("dialog")
        expect(summary).to_be_visible()
        expect(summary.locator("#summary-count")).to_have_text("0")
        assert live_app.notes() == saved
    finally:
        isolated.close()
    assert live_app.persisted_notes() == saved


def test_added_stack_opens_list_and_preserves_draft(
    page: Page, live_app: LiveApp
) -> None:
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/app/edit/1/front")
    _add(page, "a < b & c", "first answer")
    original = live_app.notes()
    nid = original[0][0]
    pile = page.locator("#pile")
    cards = page.locator("#deck-cards")
    expect(pile).to_have_attribute("aria-controls", "deck-cards")
    expect(pile).to_have_attribute("aria-expanded", "false")

    _front(page).fill("unsaved draft")
    _front(page).press("Enter")
    _back(page).fill("draft answer")
    cancelled = _respond_to_confirm(page, accept=False)
    pile.click()
    assert len(cancelled) == 1
    expect(cards).not_to_be_visible()
    expect(_front(page)).to_have_value("unsaved draft")
    expect(_back(page)).to_have_value("draft answer")

    accepted = _respond_to_confirm(page, accept=True)
    pile.click()
    assert len(accepted) == 1
    expect(cards).to_be_visible()
    expect(pile).to_have_attribute("aria-expanded", "true")
    expect(cards.locator(f"button[data-note-id='{nid}']")).to_contain_text("a < b & c")
    expect(_front(page)).to_have_value("unsaved draft")
    expect(_back(page)).to_have_value("draft answer")

    page.keyboard.press("Escape")
    expect(cards).not_to_be_visible()
    expect(pile).to_have_attribute("aria-expanded", "false")
    expect(pile).to_be_focused()
    expect(_back(page)).to_be_visible()
    expect(_front(page)).to_have_value("unsaved draft")
    expect(_back(page)).to_have_value("draft answer")

    accepted = _respond_to_confirm(page, accept=True)
    pile.click()
    assert len(accepted) == 1
    cards.locator(f"button[data-note-id='{nid}']").click()
    expect(_front(page)).to_have_value("a < b & c")
    expect(_front(page)).to_be_focused()
    expect(_back(page)).to_have_value("first answer")
    page.locator("#edit-back").click()
    expect(cards).to_be_visible()
    expect(cards.locator(f"button[data-note-id='{nid}']")).to_contain_text("a < b & c")
    assert live_app.notes() == original
    assert live_app.persisted_notes() == original


def test_pile_keyboard_badge_and_back_restore_focus(
    page: Page, live_app: LiveApp
) -> None:
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/app/edit/1/front")
    expect(page.locator("#pile")).to_be_disabled()
    expect(page.locator("#added-cards .stacked-card")).to_have_count(0)
    expect(page.locator("#added-cards .add-stack-badge")).to_have_count(0)
    expect(page.locator("#deck-cards")).not_to_be_visible()
    _add(page)
    pile = page.locator("#pile")
    cards = page.locator("#deck-cards")

    pile.focus()
    page.keyboard.press("Enter")
    expect(cards).to_be_visible()
    expect(cards).to_be_focused()
    expect(cards).to_have_accessible_name("Choose a card to edit")
    title_box = page.locator("#deck-cards-title").bounding_box()
    assert title_box is not None
    assert title_box["width"] <= 1 and title_box["height"] <= 1
    expect(cards.get_by_role("button", name="Back to new card")).to_have_count(0)
    expect(cards.get_by_role("button")).to_have_count(1)
    expect(page.locator("#edit-back")).to_have_accessible_name("Back to card editor")
    expect(page).to_have_url(f"{live_app}/app/edit/1/cards")
    expect(pile).to_have_attribute("aria-expanded", "true")
    page.keyboard.press("Escape")
    expect(cards).not_to_be_visible()
    expect(pile).to_be_focused()

    page.keyboard.press("Space")
    expect(cards).to_be_visible()
    expect(cards).to_be_focused()
    page.locator("#edit-back").click()
    expect(cards).not_to_be_visible()
    expect(pile).to_be_focused()
    expect(page).to_have_url(f"{live_app}/app/edit/1/front")
    expect(page.locator("#edit-back")).to_have_accessible_name("Exit Creator")
    expect(pile).to_have_attribute("aria-expanded", "false")

    badge = page.locator("#added-cards .add-stack-badge").bounding_box()
    pile_box = pile.bounding_box()
    assert badge is not None and pile_box is not None
    pile.click(
        position={
            "x": badge["x"] - pile_box["x"] + badge["width"] / 2,
            "y": badge["y"] - pile_box["y"] + badge["height"] / 2,
        }
    )
    expect(cards).to_be_visible()
    expect(cards).to_be_focused()
    page.keyboard.press("Escape")
    expect(pile).to_be_focused()


def test_pile_supports_touch_with_existing_and_new_cards(
    page: Page, live_app: LiveApp
) -> None:
    old_nid = _run(
        live_app,
        lambda col: add_vocab_note(col, DeckId(1), "Old card", "Old answer"),
    )
    browser = page.context.browser
    assert browser is not None
    context = browser.new_context(
        has_touch=True, viewport={"width": 509, "height": 904}
    )
    try:
        touch_page = context.new_page()
        touch_page.emulate_media(reduced_motion="reduce")
        touch_page.goto(f"{live_app}/app/edit/1/front")
        cards = touch_page.locator("#deck-cards")
        back = touch_page.locator("#edit-back")
        pile = touch_page.locator("#pile")
        badge = touch_page.locator("#added-cards .add-stack-badge")

        expect(badge.locator(".add-stack-count")).to_have_text("1")
        expect(pile).to_be_visible()
        pile.tap()
        expect(cards).to_be_visible()
        expect(cards).to_be_focused()
        expect(cards.locator("button[data-note-id]")).to_have_count(1)
        expect(cards.locator(f"button[data-note-id='{old_nid}']")).to_contain_text(
            "Old card"
        )
        back.tap()
        expect(cards).not_to_be_visible()
        expect(pile).to_be_focused()

        _to_preview(touch_page, "Session card", "Session answer")
        touch_page.get_by_role("button", name="Add", exact=True).tap()
        expect(_front(touch_page)).to_have_value("")
        expect(badge.locator(".add-stack-count")).to_have_text("2")

        pile.tap()
        expect(cards).to_be_visible()
        expect(cards).to_be_focused()
        expect(cards.locator("button[data-note-id]")).to_have_count(2)
        expect(cards).to_contain_text("Session card")
        back.tap()
        expect(cards).not_to_be_visible()
        expect(pile).to_be_focused()
        expect(pile).to_have_attribute("aria-expanded", "false")

        badge_box = badge.bounding_box()
        pile_box = pile.bounding_box()
        assert badge_box is not None and pile_box is not None
        pile.tap(
            position={
                "x": badge_box["x"] - pile_box["x"] + badge_box["width"] / 2,
                "y": badge_box["y"] - pile_box["y"] + badge_box["height"] / 2,
            }
        )
        expect(cards).to_be_visible()
        expect(cards).to_be_focused()
        back.tap()
        expect(cards).not_to_be_visible()
        expect(pile).to_be_focused()
    finally:
        context.close()


def test_pile_pointer_swipe_requires_upward_threshold(
    page: Page, live_app: LiveApp
) -> None:
    _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Swipe card", "answer"))
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/app/edit/1/front")
    cards = page.locator("#deck-cards")
    pile = page.locator("#pile")
    cue = page.locator(".pile-cue").bounding_box()
    assert cue is not None
    x = cue["x"] + cue["width"] / 2
    y = cue["y"] + cue["height"] / 2

    def drag(dx: int, dy: int) -> None:
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + dx, y + dy, steps=4)
        page.mouse.up()

    drag(0, -28)
    expect(cards).not_to_be_visible()
    expect(pile).to_have_attribute("aria-expanded", "false")
    drag(45, -30)
    expect(cards).not_to_be_visible()
    expect(pile).to_have_attribute("aria-expanded", "false")
    drag(0, -29)
    expect(cards).to_be_visible()
    expect(cards.get_by_role("button", name=re.compile("Swipe card"))).to_be_visible()
    page.locator("#edit-back").click()
    expect(cards).not_to_be_visible()
    expect(pile).to_be_focused()


def test_touch_swipe_scrubs_and_settles_without_extra_history(
    page: Page, live_app: LiveApp
) -> None:
    _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Drag card", "answer"))
    browser = page.context.browser
    assert browser is not None
    context = browser.new_context(
        has_touch=True, viewport={"width": 375, "height": 812}
    )
    try:
        touch_page = context.new_page()
        touch_page.emulate_media(reduced_motion="no-preference")
        editor_url = f"{live_app}/app/edit/1/front"
        touch_page.goto(f"{live_app}/app/")
        touch_page.goto(editor_url)
        wizard = touch_page.locator("#add-wizard")
        cards = touch_page.locator("#deck-cards")
        pile = touch_page.locator("#pile")
        cue = touch_page.locator(".pile-cue").bounding_box()
        assert cue is not None
        x = cue["x"] + cue["width"] / 2
        y = cue["y"] + cue["height"] / 2
        client = context.new_cdp_session(touch_page)
        touch_page.evaluate(
            """() => {
              const wizard = document.querySelector('#add-wizard');
              const stack = document.querySelector('#added-cards');
              window.swipePointerEvents = {pointerdown: 0, pointermove: 0, pointerup: 0, pointercancel: 0};
              window.pileReturnFrames = [];
              for (const type of Object.keys(window.swipePointerEvents)) {
                document.addEventListener(type, event => {
                  if (event.pointerType === 'touch') window.swipePointerEvents[type]++;
                });
              }
              document.addEventListener('pointerup', event => {
                if (event.pointerType !== 'touch' || wizard.dataset.browseDrag !== 'settling' ||
                    window.pileReturnFrames.length) return;
                const sample = () => {
                  window.pileReturnFrames.push(new DOMMatrixReadOnly(getComputedStyle(stack).transform).m42);
                  if (wizard.hasAttribute('data-browse-drag')) requestAnimationFrame(sample);
                };
                requestAnimationFrame(sample);
              });
            }"""
        )
        pointer_events = {
            "touchStart": "pointerdown",
            "touchMove": "pointermove",
            "touchEnd": "pointerup",
            "touchCancel": "pointercancel",
        }
        pointer_counts = dict.fromkeys(pointer_events.values(), 0)

        def touch(kind: str, distance: int = 0) -> None:
            points = (
                []
                if kind in ("touchEnd", "touchCancel")
                else [{"x": x, "y": y - distance}]
            )
            client.send(
                "Input.dispatchTouchEvent", {"type": kind, "touchPoints": points}
            )
            pointer = pointer_events[kind]
            pointer_counts[pointer] += 1
            touch_page.wait_for_function(
                "([type, count]) => window.swipePointerEvents[type] >= count",
                arg=[pointer, pointer_counts[pointer]],
            )

        def pile_y() -> float:
            return touch_page.locator("#added-cards").evaluate(
                "el => new DOMMatrixReadOnly(getComputedStyle(el).transform).m42"
            )

        touch("touchStart")
        touch("touchMove", 8)
        first = pile_y()
        touch("touchMove", 20)
        second = pile_y()
        touch("touchMove", 8)
        returned = pile_y()
        assert first == pytest.approx(-8, abs=1)
        assert second == pytest.approx(-20, abs=1)
        assert returned == pytest.approx(-8, abs=1)
        touch("touchEnd")
        expect(wizard).to_have_attribute("data-browse-phase", "closed")
        touch_page.wait_for_function(
            "() => !document.querySelector('#add-wizard').hasAttribute('data-browse-drag')"
        )
        assert pile_y() == pytest.approx(0, abs=1)
        return_frames = touch_page.evaluate("window.pileReturnFrames")
        assert any(-7.5 < value < -0.5 for value in return_frames)
        expect(touch_page).to_have_url(editor_url)

        touch("touchStart")
        touch("touchMove", 20)
        touch("touchCancel")
        touch_page.wait_for_function(
            "() => !document.querySelector('#add-wizard').hasAttribute('data-browse-drag')"
        )
        expect(cards).not_to_be_visible()
        assert pile_y() == pytest.approx(0, abs=1)
        expect(touch_page).to_have_url(editor_url)

        _front(touch_page).fill("Unsaved")
        messages = _respond_to_confirm(touch_page, accept=False)
        touch("touchStart")
        touch("touchMove", 28)
        touch("touchEnd")
        assert messages
        touch_page.wait_for_function(
            "() => !document.querySelector('#add-wizard').hasAttribute('data-browse-drag')"
        )
        expect(cards).not_to_be_visible()
        expect(_front(touch_page)).to_have_value("Unsaved")
        assert pile_y() == pytest.approx(0, abs=1)
        expect(touch_page).to_have_url(editor_url)

        # A tap during a canceled swipe's return must also settle if discard is rejected.
        touch("touchStart")
        touch("touchMove", 20)
        touch("touchEnd")
        expect(wizard).to_have_attribute("data-browse-drag", "settling")
        messages = _respond_to_confirm(touch_page, accept=False)
        touch("touchStart")
        touch("touchEnd")
        touch_page.wait_for_function(
            "() => !document.querySelector('#add-wizard').hasAttribute('data-browse-drag')"
        )
        assert messages
        expect(cards).not_to_be_visible()
        expect(_front(touch_page)).to_have_value("Unsaved")
        assert pile_y() == pytest.approx(0, abs=1)
        expect(touch_page).to_have_url(editor_url)

        # Back during the swipe-driven opening must clear its settling state.
        _front(touch_page).fill("")
        touch_page.evaluate(
            """() => document.addEventListener('pointerup', () => {
              window.openingBeforeBack = document.querySelector('#add-wizard').dataset.browsePhase;
              history.back();
            }, {once: true})"""
        )
        touch("touchStart")
        touch("touchMove", 28)
        touch("touchEnd")
        assert touch_page.evaluate("window.openingBeforeBack") == "opening"
        expect(touch_page).to_have_url(editor_url)
        expect(wizard).to_have_attribute("data-browse-phase", "closed")
        touch_page.wait_for_function(
            "() => !document.querySelector('#add-wizard').hasAttribute('data-browse-drag')"
        )
        expect(cards).not_to_be_visible()
        expect(pile).to_be_focused()
        assert pile_y() == pytest.approx(0, abs=1)

        _front(touch_page).fill("")
        touch("touchStart")
        touch("touchMove", 28)
        touch("touchEnd")
        expect(wizard).to_have_attribute("data-browse-phase", "open")
        expect(cards).to_be_visible()
        expect(
            cards.get_by_role("button", name=re.compile("Drag card"))
        ).to_be_visible()
        expect(cards).to_be_focused()
        expect(touch_page).to_have_url(f"{editor_url.removesuffix('/front')}/cards")
        touch_page.go_back()
        expect(touch_page).to_have_url(editor_url)
        expect(wizard).to_have_attribute("data-browse-phase", "closed")
        expect(pile).to_be_focused()
        touch_page.go_back()
        expect(touch_page).to_have_url(f"{live_app}/app/")
    finally:
        context.close()


def _assert_swipe_drag_samples(
    initial: dict, samples: list[dict], distance: Callable[[dict, dict], float]
) -> dict:
    first, middle, _, furthest, reversed_frame = samples
    for index in range(2):
        rows = [sample["rows"][index] for sample in samples]
        assert f"Unfold card {index + 1}" in rows[3]["text"]
        assert all(
            row["displayed"] and row["width"] > 30 and row["height"] > 20
            for row in rows
        )
        assert all(row["opacity"] > 0 for row in rows)
        assert (
            rows[0]["opacity"]
            < rows[1]["opacity"]
            < rows[2]["opacity"]
            < rows[3]["opacity"]
        )
        assert rows[4]["opacity"] == pytest.approx(rows[1]["opacity"], abs=0.03)
        # Intersect against every clipping ancestor, not just the element's box.
        assert all(
            row["visibleArea"] > 100 and row["textArea"] > 20
            for row in (rows[0], rows[1], rows[3])
        )
        assert rows[3]["background"] not in ("transparent", "rgba(0, 0, 0, 0)")
        assert rows[3]["border"] > 0
    assert distance(*furthest["rows"]) > distance(*first["rows"]) + 10
    assert distance(*reversed_frame["rows"]) == pytest.approx(
        distance(*middle["rows"]), abs=3
    )
    _assert_swipe_drag_chrome(initial, samples)
    return reversed_frame


def _assert_swipe_drag_chrome(initial: dict, samples: list[dict]) -> None:
    first, middle, further, furthest, reversed_frame = samples
    for element in ("pileCard", "cue"):
        opacities = [sample[element]["visualOpacity"] for sample in samples]
        assert (
            initial[element]["visualOpacity"]
            > opacities[0]
            > opacities[1]
            > opacities[2]
            > opacities[3]
        )
        assert opacities[4] == pytest.approx(opacities[1], abs=0.03)
    assert (
        first["editor"]["opacity"]
        > middle["editor"]["opacity"]
        > further["editor"]["opacity"]
        > furthest["editor"]["opacity"]
    )
    assert reversed_frame["editor"]["opacity"] == pytest.approx(
        middle["editor"]["opacity"], abs=0.03
    )
    assert furthest["editor"]["y"] < first["editor"]["y"] - 20
    assert reversed_frame["editor"]["y"] == pytest.approx(middle["editor"]["y"], abs=3)


def _assert_swipe_return_chrome(
    initial: dict, restored: dict, reversed_frame: dict, returned: list[dict]
) -> None:
    for element in ("pileCard", "cue"):
        assert restored[element]["displayed"]
        assert restored[element]["visualOpacity"] == pytest.approx(
            initial[element]["visualOpacity"], abs=0.02
        )
        assert any(
            reversed_frame[element]["visualOpacity"] + 0.01
            < item[element]["visualOpacity"]
            < initial[element]["visualOpacity"] - 0.01
            for item in returned
        )


def _assert_swipe_open_chrome(before: dict, boundary: dict, final: dict) -> None:
    for element in ("pileCard", "cue"):
        assert boundary["after"][element]["visualOpacity"] == pytest.approx(
            boundary["before"][element]["visualOpacity"], abs=0.03
        )
        opacities = [
            before[element]["visualOpacity"],
            *(item[element]["visualOpacity"] for item in boundary["frames"]),
            final[element]["visualOpacity"],
        ]
        assert opacities[-1] == pytest.approx(0, abs=0.02)
        assert any(0.02 < value < opacities[0] - 0.02 for value in opacities[1:-1])
        assert all(-0.03 <= a - b < 0.25 for a, b in pairwise(opacities))


def _assert_swipe_open_rows(
    before: dict,
    final: dict,
    samples: list[dict],
    boundary: dict,
    distance: Callable[[dict, dict], float],
) -> None:
    for index in range(2):
        start = before["rows"][index]
        end = final["rows"][index]
        assert distance(start, end) > 10
        drag_distances = [
            distance(sample["rows"][index], end) for sample in samples[:4]
        ]
        assert all(a > b + 1 for a, b in pairwise(drag_distances))
        assert (
            distance(
                boundary["before"]["rows"][index], boundary["after"]["rows"][index]
            )
            < 3
        )
        assert boundary["after"]["rows"][index]["opacity"] == pytest.approx(
            boundary["before"]["rows"][index]["opacity"], abs=0.03
        )
        _assert_swipe_open_row_frames(boundary, start, end, index, distance)


def _assert_swipe_open_row_frames(
    boundary: dict,
    start: dict,
    end: dict,
    index: int,
    distance: Callable[[dict, dict], float],
) -> None:
    distances = [distance(item["rows"][index], end) for item in boundary["frames"]]
    assert all(a >= b - 12 for a, b in pairwise(distances))
    assert all(
        item["rows"][index]["displayed"] and item["rows"][index]["visibleArea"] > 100
        for item in boundary["frames"]
    )
    assert any(
        0.1 * distance(start, end) < value < 0.9 * distance(start, end)
        for value in distances
    )
    assert all(
        item["rows"][index]["opacity"] >= start["opacity"] - 0.03
        for item in boundary["frames"]
    )


def test_touch_swipe_previews_real_cards_and_unwinds_or_opens(
    page: Page, live_app: LiveApp
) -> None:
    ids = _run(
        live_app,
        lambda col: [
            add_vocab_note(col, DeckId(1), f"Unfold card {i}", f"Answer {i}")
            for i in range(1, 11)
        ],
    )
    browser = page.context.browser
    assert browser is not None
    context = browser.new_context(
        has_touch=True, viewport={"width": 375, "height": 812}
    )
    try:
        touch_page = context.new_page()
        touch_page.emulate_media(reduced_motion="no-preference")
        editor_url = f"{live_app}/app/edit/1/front"
        touch_page.goto(f"{live_app}/app/")
        touch_page.goto(editor_url)
        cards = touch_page.locator("#deck-cards")
        pile = touch_page.locator("#pile")
        expect(pile).to_be_enabled()
        expect(cards).not_to_be_visible()
        cue = touch_page.locator(".pile-cue").bounding_box()
        assert cue is not None
        x = cue["x"] + cue["width"] / 2
        y = cue["y"] + cue["height"] / 2
        client = context.new_cdp_session(touch_page)
        touch_page.evaluate(
            """ids => {
              const rows = ids.map(id =>
                document.querySelector(`#deck-cards button[data-note-id="${id}"]`));
              const editor = document.querySelector('#add-editor');
              const pileCard = document.querySelector('#added-cards .stacked-card');
              const cue = document.querySelector('.pile-cue');
              const list = document.querySelector('#deck-cards');
              const measure = el => {
                const rect = el.getBoundingClientRect();
                let left = Math.max(0, rect.left), right = Math.min(innerWidth, rect.right);
                let top = Math.max(0, rect.top), bottom = Math.min(innerHeight, rect.bottom);
                let opacity = 1, displayed = true;
                for (let node = el; node; node = node.parentElement) {
                  const style = getComputedStyle(node);
                  opacity *= Number(style.opacity);
                  displayed &&= style.display !== 'none' && style.visibility === 'visible';
                  if (node !== el && /(auto|scroll|hidden|clip)/.test(style.overflow)) {
                    const clip = node.getBoundingClientRect();
                    left = Math.max(left, clip.left); right = Math.min(right, clip.right);
                    top = Math.max(top, clip.top); bottom = Math.min(bottom, clip.bottom);
                  }
                }
                return {
                  x: rect.left + rect.width / 2, y: rect.top + rect.height / 2,
                  width: rect.width, height: rect.height, opacity, displayed,
                  visualOpacity: displayed ? opacity : 0,
                  visibleArea: Math.max(0, right - left) * Math.max(0, bottom - top)
                };
              };
              window.swipeFrame = () => ({
                rows: rows.map(row => ({
                  ...measure(row),
                  text: row.textContent,
                  textArea: measure(row.querySelector('[dir="auto"]')).visibleArea,
                  background: getComputedStyle(row).backgroundColor,
                  border: parseFloat(getComputedStyle(row).borderTopWidth)
                })),
                editor: measure(editor), pileCard: measure(pileCard), cue: measure(cue),
                stage: measure(document.querySelector('#add-stage')),
                listDisplayed: getComputedStyle(list).display !== 'none'
              });
              window.swipeEvents = {pointerdown: 0, pointermove: 0, pointerup: 0};
              for (const type of Object.keys(window.swipeEvents)) {
                document.addEventListener(type, event => {
                  if (event.pointerType === 'touch') window.swipeEvents[type]++;
                });
              }
              window.recordSwipeRelease = () => {
                window.releaseFrames = [];
                document.addEventListener('pointerup', event => {
                  if (event.pointerType !== 'touch') return;
                  window.beforeRelease = window.swipeFrame();
                  document.addEventListener('pointerup', () => {
                    window.afterRelease = window.swipeFrame();
                  }, {once: true});
                  const record = () => {
                    window.releaseFrames.push(window.swipeFrame());
                    if (window.recordingRelease) requestAnimationFrame(record);
                  };
                  window.recordingRelease = true;
                  requestAnimationFrame(record);
                }, {capture: true, once: true});
              };
            }""",
            [int(ids[0]), int(ids[1])],
        )
        events = {
            "touchStart": "pointerdown",
            "touchMove": "pointermove",
            "touchEnd": "pointerup",
        }
        counts = dict.fromkeys(events.values(), 0)

        def touch(kind: str, distance: int = 0) -> None:
            points = [] if kind == "touchEnd" else [{"x": x, "y": y - distance}]
            client.send(
                "Input.dispatchTouchEvent", {"type": kind, "touchPoints": points}
            )
            event = events[kind]
            counts[event] += 1
            touch_page.wait_for_function(
                "([type, count]) => window.swipeEvents[type] >= count",
                arg=[event, counts[event]],
            )

        def frame() -> dict:
            return touch_page.evaluate(
                "() => new Promise(resolve => requestAnimationFrame(() => resolve(window.swipeFrame())))"
            )

        def distance(first: dict, second: dict) -> float:
            return (
                (first["x"] - second["x"]) ** 2 + (first["y"] - second["y"]) ** 2
            ) ** 0.5

        initial = frame()
        editor_start = initial["editor"]
        history_length = touch_page.evaluate("history.length")
        touch("touchStart")
        samples = []
        for drag in (8, 18, 30, 40, 18):
            touch("touchMove", drag)
            samples.append(frame())
            expect(touch_page).to_have_url(editor_url)
            assert touch_page.evaluate("history.length") == history_length
            assert touch_page.evaluate("window.swipeEvents.pointerup") == 0
            for dimension in ("x", "y", "width", "height"):
                assert samples[-1]["stage"][dimension] == pytest.approx(
                    initial["stage"][dimension], abs=1
                )
            expect(pile).to_have_attribute("aria-expanded", "false")
            expect(cards).to_have_attribute("aria-hidden", "true")
            assert cards.evaluate("el => !!el.closest('[inert]')")
            expect(
                touch_page.get_by_role("button", name=re.compile("Unfold card [12]"))
            ).to_have_count(0)

        reversed_frame = _assert_swipe_drag_samples(initial, samples, distance)
        assert cards.evaluate(
            """el => {
              const row = el.querySelector('button');
              row.focus();
              const rect = row.getBoundingClientRect();
              const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
              return !el.contains(document.activeElement) && !el.contains(hit);
            }"""
        )

        touch_page.evaluate("window.recordSwipeRelease()")
        touch("touchEnd")
        expect(cards).not_to_be_visible()
        touch_page.evaluate("window.recordingRelease = false")
        returned = touch_page.evaluate("window.releaseFrames")
        assert any(
            item["listDisplayed"]
            and 0.01
            < item["rows"][0]["opacity"]
            < reversed_frame["rows"][0]["opacity"] - 0.01
            for item in returned
        )
        restored = frame()
        assert restored["editor"]["opacity"] == pytest.approx(
            editor_start["opacity"], abs=0.02
        )
        assert restored["editor"]["y"] == pytest.approx(editor_start["y"], abs=2)
        _assert_swipe_return_chrome(initial, restored, reversed_frame, returned)
        expect(touch_page).to_have_url(editor_url)
        assert touch_page.evaluate("history.length") == history_length
        expect(pile).to_have_attribute("aria-expanded", "false")

        touch("touchStart")
        touch("touchMove", 28)
        before = frame()
        touch_page.evaluate("window.recordSwipeRelease()")
        touch("touchEnd")
        expect(touch_page).to_have_url(f"{editor_url.removesuffix('/front')}/cards")
        expect(cards).to_be_visible()
        expect(cards).to_be_focused()
        touch_page.wait_for_function(
            """() => window.releaseFrames.length >= 2 &&
              window.swipeFrame().rows.every(row => row.opacity > 0.99)"""
        )
        final = frame()
        touch_page.evaluate("window.recordingRelease = false")
        boundary = touch_page.evaluate(
            "({before: window.beforeRelease, after: window.afterRelease, frames: window.releaseFrames})"
        )
        _assert_swipe_open_chrome(before, boundary, final)
        _assert_swipe_open_rows(before, final, samples, boundary, distance)
        expect(pile).to_have_attribute("aria-expanded", "true")
        rows = cards.locator("button[data-note-id]")
        expect(rows).to_have_count(10)
        last = cards.locator(f"button[data-note-id='{ids[-1]}']")
        last.scroll_into_view_if_needed()
        assert cards.locator("ul").evaluate("el => el.scrollTop") > 0
        last.click()
        expect(_front(touch_page)).to_have_value("Unfold card 10")
        expect(_front(touch_page)).to_be_focused()
        touch_page.go_back()
        expect(touch_page).to_have_url(f"{editor_url.removesuffix('/front')}/cards")
        expect(cards).to_be_focused()
        touch_page.go_back()
        expect(touch_page).to_have_url(editor_url)
        expect(pile).to_be_focused()
        touch_page.go_back()
        expect(touch_page).to_have_url(f"{live_app}/app/")
    finally:
        context.close()


@pytest.mark.parametrize("second_distance", [3, 14], ids=["tap", "further-drag"])
def test_touch_regrab_of_returning_pile_opens_without_a_snap(
    page: Page, live_app: LiveApp, second_distance: int
) -> None:
    _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Regrab", "answer"))
    browser = page.context.browser
    assert browser is not None
    context = browser.new_context(
        has_touch=True, viewport={"width": 375, "height": 812}
    )
    try:
        touch_page = context.new_page()
        touch_page.emulate_media(reduced_motion="no-preference")
        editor_url = f"{live_app}/app/edit/1/front"
        touch_page.goto(editor_url)
        cue = touch_page.locator(".pile-cue").bounding_box()
        assert cue is not None
        x = cue["x"] + cue["width"] / 2
        y = cue["y"] + cue["height"] / 2
        client = context.new_cdp_session(touch_page)
        touch_page.evaluate(
            """() => {
              window.touchCounts = {pointerdown: 0, pointermove: 0, pointerup: 0};
              for (const type of Object.keys(window.touchCounts)) {
                document.addEventListener(type, event => {
                  if (event.pointerType === 'touch') window.touchCounts[type]++;
                });
              }
              const measure = () => {
                const editor = document.querySelector('#add-editor');
                const pile = document.querySelector('#added-cards');
                return {
                  editorY: editor.getBoundingClientRect().y,
                  editorOpacity: Number(getComputedStyle(editor).opacity),
                  pileY: new DOMMatrixReadOnly(getComputedStyle(pile).transform).m42
                };
              };
              window.freezePileReturn = () => {
                document.addEventListener('pointerup', () => {
                  const freeze = () => {
                    if (measure().pileY >= -20) {
                      for (const animation of document.getAnimations()) {
                        if (animation instanceof CSSTransition) animation.pause();
                      }
                      window.pileReturnFrozen = true;
                    } else {
                      requestAnimationFrame(freeze);
                    }
                  };
                  requestAnimationFrame(freeze);
                }, {once: true});
              };
              window.recordRegrabRelease = () => {
                document.addEventListener('pointerup', event => {
                  if (event.pointerType !== 'touch') return;
                  window.beforeRegrabRelease = measure();
                  document.addEventListener('pointerup', () => {
                    window.afterRegrabRelease = measure();
                  }, {once: true});
                }, {capture: true, once: true});
              };
            }"""
        )
        events = {
            "touchStart": "pointerdown",
            "touchMove": "pointermove",
            "touchEnd": "pointerup",
        }
        counts = dict.fromkeys(events.values(), 0)

        def touch(kind: str, distance: int = 0) -> None:
            points = [] if kind == "touchEnd" else [{"x": x, "y": y - distance}]
            client.send(
                "Input.dispatchTouchEvent", {"type": kind, "touchPoints": points}
            )
            event = events[kind]
            counts[event] += 1
            touch_page.wait_for_function(
                "([type, count]) => window.touchCounts[type] >= count",
                arg=[event, counts[event]],
            )

        touch("touchStart")
        touch("touchMove", 26)
        # Freeze the visible return partway through so regrab starts at a known
        # position regardless of the speed of browser automation.
        touch_page.evaluate("window.freezePileReturn()")
        touch("touchEnd")
        touch_page.wait_for_function("() => window.pileReturnFrozen === true")
        touch("touchStart")
        touch("touchMove", second_distance)
        touch_page.evaluate("window.recordRegrabRelease()")
        touch("touchEnd")

        boundary = touch_page.evaluate(
            "({before: window.beforeRegrabRelease, after: window.afterRegrabRelease})"
        )
        assert boundary["before"]["pileY"] < -10
        assert boundary["after"]["pileY"] == pytest.approx(
            boundary["before"]["pileY"], abs=1
        )
        assert boundary["after"]["editorY"] == pytest.approx(
            boundary["before"]["editorY"], abs=2
        )
        assert boundary["after"]["editorOpacity"] == pytest.approx(
            boundary["before"]["editorOpacity"], abs=0.03
        )
        cards = touch_page.locator("#deck-cards")
        expect(touch_page).to_have_url(f"{editor_url.removesuffix('/front')}/cards")
        expect(cards.get_by_role("button", name=re.compile("Regrab"))).to_be_visible()
        expect(cards).to_be_focused()
    finally:
        context.close()


@pytest.mark.parametrize("terminal_event", ["pointerup", "pointercancel"])
def test_history_open_during_touch_drag_finishes_after_pointer_ends(
    page: Page, live_app: LiveApp, terminal_event: str
) -> None:
    _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "History drag", "answer"))
    browser = page.context.browser
    assert browser is not None
    context = browser.new_context(
        has_touch=True, viewport={"width": 375, "height": 812}
    )
    try:
        touch_page = context.new_page()
        touch_page.emulate_media(reduced_motion="no-preference")
        editor_url = f"{live_app}/app/edit/1/front"
        touch_page.goto(editor_url)
        pile = touch_page.locator("#pile")
        cards = touch_page.locator("#deck-cards")
        pile.tap()
        expect(cards).to_be_focused()
        touch_page.go_back()
        expect(touch_page).to_have_url(editor_url)
        expect(pile).to_be_focused()
        cue = touch_page.locator(".pile-cue").bounding_box()
        assert cue is not None
        x = cue["x"] + cue["width"] / 2
        y = cue["y"] + cue["height"] / 2
        client = context.new_cdp_session(touch_page)
        touch_page.evaluate(
            """terminal => {
              document.addEventListener('pointermove', event => {
                if (event.pointerType === 'touch') {
                  window.activeTouch = {
                    pointerId: event.pointerId, pointerType: event.pointerType,
                    clientX: event.clientX, clientY: event.clientY,
                    isPrimary: true, bubbles: true
                  };
                }
              });
              window.addEventListener('popstate', () => requestAnimationFrame(() => {
                window.expandedAtInterruption =
                  document.querySelector('#pile').getAttribute('aria-expanded');
                window.opacityAtInterruption =
                  Number(getComputedStyle(document.querySelector('#add-editor')).opacity);
                document.dispatchEvent(new PointerEvent(terminal, window.activeTouch));
                window.interrupted = true;
              }), {once: true});
            }""",
            terminal_event,
        )
        client.send(
            "Input.dispatchTouchEvent",
            {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]},
        )
        client.send(
            "Input.dispatchTouchEvent",
            {"type": "touchMove", "touchPoints": [{"x": x, "y": y - 18}]},
        )
        touch_page.wait_for_function("() => !!window.activeTouch")
        touch_page.evaluate("history.forward()")
        touch_page.wait_for_function("() => window.interrupted === true")
        assert touch_page.evaluate("window.expandedAtInterruption") == "true"
        assert touch_page.evaluate("window.opacityAtInterruption") > 0
        client.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})

        expect(touch_page).to_have_url(f"{editor_url.removesuffix('/front')}/cards")
        expect(
            cards.get_by_role("button", name=re.compile("History drag"))
        ).to_be_visible()
        expect(cards).to_be_focused()
        touch_page.locator("#edit-back").tap()
        expect(touch_page).to_have_url(editor_url)
        expect(pile).to_be_focused()
    finally:
        context.close()


@pytest.mark.parametrize("open_method", ["enter", "tap", "forward"])
def test_reopening_while_swipe_return_is_in_progress_reverses(
    page: Page, live_app: LiveApp, open_method: str
) -> None:
    _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Return", "answer"))
    browser = page.context.browser
    assert browser is not None
    context = browser.new_context(
        has_touch=True, viewport={"width": 375, "height": 812}
    )
    try:
        touch_page = context.new_page()
        touch_page.emulate_media(reduced_motion="no-preference")
        editor_url = f"{live_app}/app/edit/1/front"
        touch_page.goto(editor_url)
        pile = touch_page.locator("#pile")
        cards = touch_page.locator("#deck-cards")
        wizard = touch_page.locator("#add-wizard")

        # Create a forward entry and return to the fully settled editor.
        pile.tap()
        expect(cards).to_be_focused()
        touch_page.go_back()
        expect(wizard).to_have_attribute("data-browse-phase", "closed")
        expect(pile).to_be_focused()
        cue = touch_page.locator(".pile-cue").bounding_box()
        assert cue is not None
        x = cue["x"] + cue["width"] / 2
        y = cue["y"] + cue["height"] / 2
        client = context.new_cdp_session(touch_page)
        touch_page.evaluate(
            """method => {
              const stack = document.querySelector('#added-cards');
              const editor = document.querySelector('#add-editor');
              const row = document.querySelector('#deck-cards .browse-card');
              const measure = () => ({
                pileY: new DOMMatrixReadOnly(getComputedStyle(stack).transform).m42,
                editorOpacity: Number(getComputedStyle(editor).opacity),
                rowOpacity: Number(getComputedStyle(row).opacity)
              });
              const transitions = () => [stack, editor, row].flatMap(element =>
                element.getAnimations().filter(animation => animation instanceof CSSTransition)
              );
              const seek = (animations, fraction) => {
                for (const animation of animations) {
                  animation.currentTime = animation.effect.getComputedTiming().endTime * fraction;
                }
              };
              document.addEventListener('pointermove', event => {
                if (event.pointerType === 'touch') window.returnSwipeMoved = true;
              });
              document.addEventListener('pointerup', event => {
                if (event.pointerType !== 'touch') return;
                // Pause and seek the real return transitions to an intermediate
                // rendered frame, independent of automation and frame timing.
                measure();
                const animations = transitions();
                for (const animation of animations) animation.pause();
                seek(animations, 0.35);
                window.beforeReopen = measure();
                window.returnFrozen = true;
              }, {once: true});
              const recordOpen = () => {
                window.afterReopen = measure();
                const animations = transitions();
                for (const animation of animations) animation.pause();
                seek(animations, 0.25);
                window.openEarly = measure();
                seek(animations, 0.75);
                window.openLate = measure();
                for (const animation of animations) animation.play();
                window.reopenRecorded = true;
              };
              if (method === 'forward') {
                window.addEventListener('popstate', recordOpen, {once: true});
              } else {
                document.addEventListener('click', event => {
                  if (event.target.closest('#pile')) recordOpen();
                }, {once: true});
              }
            }""",
            open_method,
        )
        client.send(
            "Input.dispatchTouchEvent",
            {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]},
        )
        client.send(
            "Input.dispatchTouchEvent",
            {"type": "touchMove", "touchPoints": [{"x": x, "y": y - 26}]},
        )
        touch_page.wait_for_function("() => window.returnSwipeMoved === true")
        client.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        touch_page.wait_for_function("() => window.returnFrozen === true")
        expect(wizard).to_have_attribute("data-browse-drag", "settling")

        if open_method == "forward":
            touch_page.evaluate("history.forward()")
        elif open_method == "tap":
            pile.tap()
        else:
            pile.press("Enter")
        touch_page.wait_for_function("() => window.reopenRecorded === true")
        frames = touch_page.evaluate(
            """() => ({
              before: window.beforeReopen, after: window.afterReopen,
              early: window.openEarly, late: window.openLate
            })"""
        )
        assert -25 < frames["before"]["pileY"] < -1
        assert 0 < frames["before"]["rowOpacity"] < 1
        for key in ("pileY", "editorOpacity", "rowOpacity"):
            assert frames["after"][key] == pytest.approx(
                frames["before"][key], abs=1 if key == "pileY" else 0.03
            )
        assert frames["late"]["pileY"] < frames["early"]["pileY"] - 2
        assert frames["late"]["editorOpacity"] < frames["early"]["editorOpacity"] - 0.05
        assert frames["late"]["rowOpacity"] > frames["early"]["rowOpacity"] + 0.05
        expect(touch_page).to_have_url(f"{editor_url.removesuffix('/front')}/cards")
        expect(wizard).to_have_attribute("data-browse-phase", "open")
        expect(cards.get_by_role("button", name=re.compile("Return"))).to_be_visible()
        expect(cards).to_be_focused()
    finally:
        context.close()


def test_reopening_during_swipe_return_animates_editor_out(
    page: Page, live_app: LiveApp
) -> None:
    _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Reopen", "answer"))
    browser = page.context.browser
    assert browser is not None
    context = browser.new_context(
        has_touch=True, viewport={"width": 375, "height": 812}
    )
    try:
        touch_page = context.new_page()
        touch_page.emulate_media(reduced_motion="no-preference")
        editor_url = f"{live_app}/app/edit/1/front"
        touch_page.goto(editor_url)
        cue = touch_page.locator(".pile-cue").bounding_box()
        assert cue is not None
        x = cue["x"] + cue["width"] / 2
        y = cue["y"] + cue["height"] / 2
        client = context.new_cdp_session(touch_page)
        touch_page.evaluate(
            """() => {
              document.addEventListener('pointermove', event => {
                if (event.pointerType === 'touch') window.firstSwipeMoved = true;
              });
              document.addEventListener('pointerup', event => {
                if (event.pointerType === 'touch') history.back();
              }, {once: true});
              window.addEventListener('popstate', () => {
                window.firstReturnNavigated = true;
                // Reopen as soon as the pile finishes returning, before the
                // longer editor return finishes.
                const reopen = () => {
                  const pile = document.querySelector('#added-cards');
                  const y = new DOMMatrixReadOnly(getComputedStyle(pile).transform).m42;
                  if (Math.abs(y) >= 0.5 || pile.getAnimations().length) {
                    requestAnimationFrame(reopen);
                    return;
                  }
                  window.reopenFrames = [];
                  window.addEventListener('popstate', () => {
                    const sample = () => {
                      const editor = document.querySelector('#add-editor');
                      const style = getComputedStyle(editor);
                      if (style.display === 'none') return;
                      window.reopenFrames.push(Number(style.opacity));
                      requestAnimationFrame(sample);
                    };
                    requestAnimationFrame(sample);
                  }, {once: true});
                  history.forward();
                };
                requestAnimationFrame(reopen);
              }, {once: true});
            }"""
        )
        client.send(
            "Input.dispatchTouchEvent",
            {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]},
        )
        client.send(
            "Input.dispatchTouchEvent",
            {"type": "touchMove", "touchPoints": [{"x": x, "y": y - 28}]},
        )
        touch_page.wait_for_function("() => window.firstSwipeMoved === true")
        client.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        touch_page.wait_for_function("() => window.firstReturnNavigated === true")
        cards = touch_page.locator("#deck-cards")
        expect(touch_page).to_have_url(f"{editor_url.removesuffix('/front')}/cards")
        expect(cards.get_by_role("button", name=re.compile("Reopen"))).to_be_visible()
        expect(cards).to_be_focused()
        opacities = touch_page.evaluate("window.reopenFrames")
        assert len(opacities) >= 2
        assert max(opacities) > 0.9
        assert min(opacities) < 0.8
    finally:
        context.close()


def test_long_card_list_does_not_overflow_page_during_touch_drag(
    page: Page, live_app: LiveApp
) -> None:
    _run(
        live_app,
        lambda col: [
            add_vocab_note(col, DeckId(1), f"Long list {i}", f"Answer {i}")
            for i in range(40)
        ],
    )
    browser = page.context.browser
    assert browser is not None
    context = browser.new_context(
        has_touch=True, viewport={"width": 375, "height": 812}
    )
    try:
        touch_page = context.new_page()
        touch_page.emulate_media(reduced_motion="no-preference")
        touch_page.goto(f"{live_app}/app/edit/1/front")
        cue = touch_page.locator(".pile-cue").bounding_box()
        assert cue is not None
        x = cue["x"] + cue["width"] / 2
        y = cue["y"] + cue["height"] / 2
        client = context.new_cdp_session(touch_page)
        touch_page.evaluate(
            """() => {
              window.touchMoves = 0;
              document.addEventListener('pointermove', event => {
                if (event.pointerType === 'touch') window.touchMoves++;
              });
            }"""
        )
        document_size = """() => {
          const el = document.documentElement;
          return {width: el.scrollWidth, height: el.scrollHeight,
                  viewportWidth: el.clientWidth, viewportHeight: el.clientHeight};
        }"""
        initial = touch_page.evaluate(document_size)
        assert initial["width"] <= initial["viewportWidth"]
        client.send(
            "Input.dispatchTouchEvent",
            {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]},
        )
        for count, distance in enumerate((8, 18, 30, 40), start=1):
            client.send(
                "Input.dispatchTouchEvent",
                {"type": "touchMove", "touchPoints": [{"x": x, "y": y - distance}]},
            )
            touch_page.wait_for_function(
                "count => window.touchMoves >= count", arg=count
            )
            size = touch_page.evaluate(document_size)
            assert size["width"] <= initial["viewportWidth"]
            assert size["height"] <= initial["height"]
        client.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        cards = touch_page.locator("#deck-cards")
        expect(cards).to_be_focused()
        last = cards.get_by_role("button", name=re.compile("Long list 39"))
        last.scroll_into_view_if_needed()
        expect(last).to_be_visible()
    finally:
        context.close()


def test_browse_fans_and_folds_with_bounded_stagger(
    page: Page, live_app: LiveApp
) -> None:
    _run(
        live_app,
        lambda col: [
            add_vocab_note(col, DeckId(1), f"Fan {i}", f"Answer {i}") for i in range(15)
        ],
    )
    page.emulate_media(reduced_motion="no-preference")
    page.goto(f"{live_app}/app/edit/1/front")
    wizard = page.locator("#add-wizard")
    pile = page.locator("#pile")
    cards = page.locator("#deck-cards")
    expect(wizard).to_have_attribute("data-browse-phase", "closed")
    page.evaluate(
        """() => {
          window.browsePhases = [];
          window.browseAnimations = [];
          const wizard = document.querySelector('#add-wizard');
          new MutationObserver(() => window.browsePhases.push(wizard.dataset.browsePhase))
            .observe(wizard, {attributes: true, attributeFilter: ['data-browse-phase']});
          document.addEventListener('animationstart', event => {
            if (event.target.id === 'add-editor' || event.target.matches('.browse-card')) {
              window.browseAnimations.push({
                target: event.target.id || 'row', name: event.animationName
              });
            }
          });
        }"""
    )
    pile.click()
    expect(wizard).to_have_attribute("data-browse-phase", "open")
    expect(cards).to_be_visible()
    rows = cards.locator("button[data-note-id]")
    expect(rows).to_have_count(15)
    assert page.evaluate(
        """() => {
          const ids = [...document.querySelectorAll('[id]')].map(el => el.id);
          return new Set(ids).size === ids.length;
        }"""
    )
    page.wait_for_function(
        "() => window.browseAnimations.some(event => event.target === 'row')"
    )
    delays = rows.evaluate_all(
        """rows => rows.map(row => {
          const delay = getComputedStyle(row).animationDelay.split(',')[0];
          return delay.endsWith('ms') ? parseFloat(delay) : parseFloat(delay) * 1000;
        })"""
    )
    assert max(delays) <= 250
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    page.locator("#edit-back").click()
    expect(wizard).to_have_attribute("data-browse-phase", "closed")
    expect(cards).not_to_be_visible()
    expect(page.locator("#add-editor")).to_be_visible()
    expect(pile).to_be_focused()
    phases = page.evaluate("window.browsePhases")
    phases = [
        phase for i, phase in enumerate(phases) if i == 0 or phase != phases[i - 1]
    ]
    assert phases == ["opening", "open", "closing", "returning", "closed"]
    animations = page.evaluate("window.browseAnimations")
    editor_animations = [
        event["name"] for event in animations if event["target"] == "add-editor"
    ]
    row_animations = {event["name"] for event in animations if event["target"] == "row"}
    assert len(set(editor_animations)) >= 2
    assert len(row_animations) >= 2
    pile.click()
    expect(wizard).to_have_attribute("data-browse-phase", "open")
    page.wait_for_function(
        "() => [...document.querySelectorAll('#deck-cards .browse-card')]"
        ".every(row => getComputedStyle(row).opacity === '1')"
    )
    tops = rows.evaluate_all("rows => rows.map(row => row.getBoundingClientRect().top)")
    assert all(first < second for first, second in pairwise(tops))
    rows.nth(0).click()
    expect(wizard).to_have_attribute("data-browse-phase", "closed")
    expect(cards).not_to_be_visible()
    expect(_front(page)).to_have_value("Fan 0")
    expect(_front(page)).to_be_focused()
    phases = page.evaluate("window.browsePhases")
    phases = [
        phase for i, phase in enumerate(phases) if i == 0 or phase != phases[i - 1]
    ]
    assert phases[-5:] == ["opening", "open", "closing", "returning", "closed"]


def _assert_browse_chrome_opacity(
    opening: list[dict[str, Any]], returning: list[dict[str, Any]]
) -> None:
    for index in range(2):
        assert any(0.05 < frame["opacity"][index] < 0.95 for frame in opening)
        assert any(0.05 < frame["opacity"][index] < 0.95 for frame in returning)
        assert opening[0]["opacity"][index] > opening[-1]["opacity"][index]
        assert returning[0]["opacity"][index] < returning[-1]["opacity"][index]


def _assert_browse_chrome_fades(page: Page) -> None:
    frames = page.evaluate("window.motionFrames")
    opening = [frame for frame in frames if frame["phase"] == "opening"]
    returning = [frame for frame in frames if frame["phase"] == "returning"]
    assert len(opening) >= 3 and len(returning) >= 3
    assert all(value > 0 for frame in opening for value in frame["height"])
    assert all(all(frame["inert"]) for frame in opening)
    assert all(not frame["doneDisabled"] for frame in opening)
    assert all(
        frame["doneOpacity"] == 1 and not frame["doneInert"] for frame in opening
    )
    done_background = page.evaluate("window.doneBackground")
    assert all(frame["doneBackground"] == done_background for frame in opening)
    _assert_browse_chrome_opacity(opening, returning)


def test_browse_visibly_lifts_stack_and_fades_chrome(
    page: Page, live_app: LiveApp
) -> None:
    _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Motion", "answer"))
    page.emulate_media(reduced_motion="no-preference")
    page.goto(f"{live_app}/app/edit/1/front")
    wizard = page.locator("#add-wizard")
    pile = page.locator("#pile")
    cards = page.locator("#deck-cards")
    steps = page.locator("#add-wizard .add-step")
    footer = page.locator("#add-wizard footer")
    done = page.locator("#add-wizard header button").filter(
        has_text=re.compile(r"^Done$")
    )
    expect(steps).to_have_count(3)
    page.evaluate(
        """() => {
          const wizard = document.querySelector('#add-wizard');
          const pileCard = document.querySelector('#added-cards .stacked-card');
          const steps = document.querySelector('.add-step').parentElement;
          const footer = wizard.querySelector('footer');
          const done = wizard.querySelector('header .review-hud-nav button');
          const row = document.querySelector('#deck-cards button[data-note-id]');
          const center = el => {
            const rect = el.getBoundingClientRect();
            return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2};
          };
          window.doneBackground = getComputedStyle(done).backgroundColor;
          window.motionStart = center(pileCard);
          window.motionFrames = [];
          const sample = () => {
            const phase = wizard.dataset.browsePhase;
            if (phase !== 'closed') {
              const style = el => getComputedStyle(el);
              window.motionFrames.push({
                phase, pile: center(pileCard), row: center(row),
                rowOpacity: Number(style(row).opacity),
                doneBackground: style(done).backgroundColor,
                doneDisabled: done.disabled,
                doneOpacity: Number(style(done).opacity),
                doneInert: !!done.closest('[inert]'),
                opacity: [steps, footer].map(el => Number(style(el).opacity)),
                height: [steps, footer].map(el => el.getBoundingClientRect().height),
                inert: [steps, footer].map(el =>
                  el.matches(':disabled') || !!el.closest('[inert]')),
              });
            }
            requestAnimationFrame(sample);
          };
          requestAnimationFrame(sample);
        }"""
    )
    pile.click()
    expect(wizard).to_have_attribute("data-browse-phase", "open")
    expect(cards).to_be_focused()
    expect(steps.first).to_be_hidden()
    expect(footer).to_be_hidden()
    expect(done).to_have_css("opacity", "1")
    expect(done).to_be_enabled()
    page.wait_for_function(
        """() => window.motionFrames.filter(frame =>
          frame.phase === 'open' && frame.rowOpacity > 0.9).length >= 2"""
    )
    page.locator("#edit-back").click()
    expect(wizard).to_have_attribute("data-browse-phase", "closed")
    expect(pile).to_be_focused()
    expect(steps.first).to_be_visible()
    expect(footer).to_be_visible()
    expect(done).to_have_css("opacity", "1")

    frames = page.evaluate("window.motionFrames")
    start = page.evaluate("window.motionStart")
    opening = [frame for frame in frames if frame["phase"] == "opening"]
    opened = [frame for frame in frames if frame["phase"] == "open"]
    assert len(opening) >= 3 and len(opened) >= 2
    pile_y = [frame["pile"]["y"] for frame in opening]
    assert min(pile_y) < start["y"] - 20
    assert len({round(y) for y in pile_y}) >= 3
    _assert_browse_chrome_fades(page)
    # The first list frame starts at the last visible pile position, despite reflow.
    assert abs(opened[0]["row"]["x"] - opening[-1]["pile"]["x"]) < 80
    assert abs(opened[0]["row"]["y"] - opening[-1]["pile"]["y"]) < 80
    assert min(frame["row"]["y"] for frame in opened) < opened[0]["row"]["y"] - 10


def test_add_animates_stack_but_edit_does_not_append_or_animate(
    page: Page, live_app: LiveApp
) -> None:
    page.emulate_media(reduced_motion="no-preference")
    page.goto(f"{live_app}/app/edit/1/front")
    page.evaluate(
        """() => {
          window.stackAnimations = [];
          document.addEventListener('animationstart', event => {
            if (event.target.matches('.stacked-card')) {
              window.stackAnimations.push(event.animationName);
            }
          });
        }"""
    )
    _add(page, "Original card", "answer")
    page.wait_for_function("() => window.stackAnimations.length > 0")
    nid = live_app.notes()[0][0]
    original_events = page.evaluate("window.stackAnimations.slice()")
    page.locator("#pile").click()
    page.locator(f"#deck-cards button[data-note-id='{nid}']").click()
    expect(_front(page)).to_have_value("Original card")
    _front(page).fill("Edited card")
    _front(page).press("Enter")
    _wait_for_back(page)
    _back(page).press("Enter")
    page.locator("#btn-add").click()
    expect(page.locator("#deck-cards")).to_be_visible()
    expect(page.locator("#deck-cards")).to_be_focused()
    expect(page.locator(f"#deck-cards button[data-note-id='{nid}']")).to_contain_text(
        "Edited card"
    )
    stack = page.locator("#added-cards .stacked-card")
    expect(stack).to_have_count(1)
    expect(stack).to_contain_text("Edited card")
    expect(page.locator("#added-cards .add-stack-count")).to_have_text("1")
    page.evaluate(
        """() => new Promise(resolve =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)))"""
    )
    assert page.evaluate("window.stackAnimations") == original_events
    assert [note[0] for note in live_app.notes()] == [nid]


def test_back_interrupts_opening_and_is_blocked_while_closing(
    page: Page, live_app: LiveApp
) -> None:
    _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Interrupt", "answer"))
    page.emulate_media(reduced_motion="no-preference")
    url = f"{live_app}/app/edit/1/front"
    page.goto(url)
    wizard = page.locator("#add-wizard")
    pile = page.locator("#pile")
    back = page.locator("#edit-back")
    cards = page.locator("#deck-cards")
    done = page.get_by_role("button", name="Done", exact=True)
    pile.click()
    expect(wizard).to_have_attribute("data-browse-phase", "opening")
    done.evaluate("el => el.click()")
    expect(page).to_have_url(url.removesuffix("/front") + "/cards")
    expect(page.locator("#add-summary")).not_to_be_visible()
    expect(back).to_have_role("button")
    expect(back).not_to_have_attribute("href", re.compile("."))
    back.click()
    expect(wizard).to_have_attribute("data-browse-phase", "closed")
    expect(cards).not_to_be_visible()
    expect(page).to_have_url(url)
    expect(pile).to_be_focused()

    pile.click()
    expect(wizard).to_have_attribute("data-browse-phase", "open")
    back.click()
    expect(wizard).to_have_attribute("data-browse-phase", "closing")
    done.evaluate("el => el.click()")
    expect(page.locator("#add-summary")).not_to_be_visible()
    expect(back).to_have_role("button")
    expect(back).not_to_have_attribute("href", re.compile("."))
    expect(back).to_have_attribute("aria-disabled", "true")
    back.focus()
    expect(back).to_be_focused()
    page.keyboard.press("Enter")
    expect(page).to_have_url(url)
    expect(wizard).to_have_attribute("data-browse-phase", "returning")
    done.evaluate("el => el.click()")
    expect(page.locator("#add-summary")).not_to_be_visible()
    expect(pile).to_be_focused()
    expect(back).to_have_attribute("aria-disabled", "true")
    expect(back).not_to_have_attribute("href", re.compile("."))
    back.focus()
    expect(back).to_be_focused()
    page.keyboard.press("Space")
    expect(page).to_have_url(url)
    expect(wizard).to_have_attribute("data-browse-phase", "closed")
    expect(cards).not_to_be_visible()
    expect(back).to_be_focused()


def test_reduced_motion_browse_pick_and_close_are_usable(
    page: Page, live_app: LiveApp
) -> None:
    nid = _run(
        live_app, lambda col: add_vocab_note(col, DeckId(1), "Still card", "answer")
    )
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/app/edit/1/front")
    pile = page.locator("#pile")
    cards = page.locator("#deck-cards")
    page.evaluate(
        """() => {
          const wizard = document.querySelector('#add-wizard');
          const card = document.querySelector('#added-cards .stacked-card');
          const chrome = [
            document.querySelector('.add-step').parentElement,
            wizard.querySelector('footer')
          ];
          window.reducedStart = card.getBoundingClientRect().y;
          window.reducedOpening = null;
          new MutationObserver(() => {
            if (wizard.dataset.browsePhase === 'opening') {
              window.reducedOpening = {
                y: card.getBoundingClientRect().y,
                opacity: chrome.map(el => Number(getComputedStyle(el).opacity))
              };
            }
          }).observe(wizard, {attributes: true, attributeFilter: ['data-browse-phase']});
        }"""
    )
    pile.click()
    row = cards.locator(f"button[data-note-id='{nid}']")
    expect(row).to_be_visible()
    reduced = page.evaluate("window.reducedOpening")
    assert reduced is not None
    assert abs(reduced["y"] - page.evaluate("window.reducedStart")) < 1
    assert reduced["opacity"] == [0, 0]
    duration = row.evaluate(
        """el => {
          const value = getComputedStyle(el).animationDuration.split(',')[0];
          return value.endsWith('ms') ? parseFloat(value) : parseFloat(value) * 1000;
        }"""
    )
    assert duration <= 1
    page.keyboard.press("Escape")
    expect(cards).not_to_be_visible()
    expect(pile).to_be_focused()
    pile.click()
    row.click()
    expect(cards).not_to_be_visible()
    expect(_front(page)).to_have_value("Still card")
    expect(_front(page)).to_be_focused()


def _add_unsupported_basic_note(col: Collection, vocab_note_id: NoteId) -> None:
    vocab_id = col.get_note(vocab_note_id).mid
    other_model = next(
        model
        for model in col.models.all()
        if model["id"] != vocab_id
        and model["type"] == MODEL_STD
        and len(model["flds"]) >= 2
        and model["tmpls"]
    )
    note = col.new_note(other_model)
    for index in range(len(note.fields)):
        note.fields[index] = "Unsupported basic" if index == 0 else "Basic answer"
    col.add_note(note, DeckId(1))
    assert note.cards()


def _seed_deck_list_notes(col: Collection) -> list[NoteId]:
    ids = [
        add_vocab_note(
            col,
            DeckId(1),
            f"History {index}",
            f"Answer {index}",
            "hint <one>" if index == 2 else "",
            "A *word*\nnext line" if index == 2 else "",
        )
        for index in range(5)
    ]
    other_deck = col.decks.id("Other")
    assert other_deck is not None
    add_vocab_note(col, other_deck, "Other deck card", "Other answer")
    _add_unsupported_basic_note(col, ids[0])
    return ids


@pytest.mark.parametrize(
    ("live_app", "unit", "label"),
    [
        ("", "cards", "cards in this deck. Tap or swipe up to edit."),
        (
            "de_DE",
            "Karten",
            "Karten in diesem Stapel. Zum Bearbeiten tippen oder nach oben wischen.",
        ),
    ],
    indirect=["live_app"],
)
def test_deck_list_includes_previous_sessions_and_edits_in_place(
    page: Page, live_app: LiveApp, unit: str, label: str
) -> None:
    ids = _run(live_app, _seed_deck_list_notes)
    before_ids = _run(live_app, lambda col: sorted(col.find_notes("")))
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/app/edit/1/front")
    pile = page.locator("#pile")
    badge = page.locator("#added-cards .add-stack-badge")
    stack = page.locator("#added-cards .stacked-card")
    expect(badge.locator(".add-stack-count")).to_have_text("5")
    expect(badge.locator(".add-stack-unit")).to_have_text(unit)
    expect(pile).to_have_accessible_name(f"5 {label}")
    expect(stack).to_have_count(5)
    assert stack.evaluate_all(
        "cards => cards.map(card => Number(card.dataset.noteId))"
    ) == list(reversed(ids))
    pile.click()
    cards = page.locator("#deck-cards")
    expect(cards).to_be_visible()
    expect(cards).to_be_focused()
    expect(page.locator("#edit-back")).to_have_accessible_name(
        "Back to card editor" if unit == "cards" else "Zurück zum Karteneditor"
    )
    expect(cards.locator("button[data-note-id]")).to_have_count(5)
    assert (
        cards.locator("button[data-note-id]").evaluate_all(
            "rows => rows.map(row => Number(row.dataset.noteId))"
        )
        == ids
    )
    for index, nid in enumerate(ids):
        expect(cards.locator(f"button[data-note-id='{nid}']")).to_contain_text(
            f"History {index}"
        )
    expect(cards).not_to_contain_text("Other deck card")
    expect(cards).not_to_contain_text("Unsupported basic")
    page.locator("#edit-back").click()
    expect(cards).not_to_be_visible()
    expect(pile).to_be_focused()

    page.locator("#input-front").fill("Session card")
    page.locator("#input-front").press("Enter")
    page.locator("#input-back").fill("Session answer")
    page.locator("#input-back").press("Enter")
    page.locator("#btn-add").click()
    expect(page.locator("#input-front")).to_have_value("")
    expect(badge.locator(".add-stack-count")).to_have_text("6")
    expect(pile).to_have_accessible_name(f"6 {label}")
    stack_ids = stack.evaluate_all(
        "cards => cards.map(card => Number(card.dataset.noteId))"
    )
    assert stack_ids[1:] == list(reversed(ids[1:]))
    pile.click()
    expect(cards.locator("button[data-note-id]")).to_have_count(6)
    cards.locator(f"button[data-note-id='{ids[2]}']").click()
    expect(cards).not_to_be_visible()
    front = page.locator("#input-front")
    expect(front).to_have_value("History 2")
    expect(front).to_be_focused()
    expect(page.locator("#edit-back")).to_have_accessible_name(
        "Back to cards" if unit == "cards" else "Zurück zu den Karten"
    )
    expect(page.locator("#edit-warning")).not_to_be_visible()
    front.fill("Edited historical card")
    front.press("Enter")
    _wait_for_back(page)
    expect(page.locator("#input-back")).to_have_value("Answer 2")
    expect(page.locator("#input-hint")).to_have_value("hint <one>")
    expect(page.locator("#input-example")).to_have_value("A *word*\nnext line")
    page.locator("#input-back").press("Enter")
    page.locator("#btn-add").click()
    expect(cards).to_be_visible()
    expect(cards).to_be_focused()
    expect(cards.locator(f"button[data-note-id='{ids[2]}']")).to_contain_text(
        "Edited historical card"
    )
    expect(front).to_have_value("")
    expect(badge.locator(".add-stack-count")).to_have_text("6")
    assert (
        stack.evaluate_all("cards => cards.map(card => Number(card.dataset.noteId))")
        == stack_ids
    )
    expect(page.locator(f"#added-cards [data-note-id='{ids[2]}']")).to_contain_text(
        "Edited historical card"
    )
    expect(page.locator("#added-cards")).to_contain_text("Session card")
    assert _run(live_app, lambda col: col.get_note(ids[2])["Front"]) == (
        "Edited historical card"
    )
    after_ids = _run(live_app, lambda col: sorted(col.find_notes("")))
    assert len(after_ids) == len(before_ids) + 1
    assert set(before_ids).issubset(after_ids)
    expect(cards.locator(f"button[data-note-id='{ids[2]}']")).to_contain_text(
        "Edited historical card"
    )
    assert (
        cards.locator("button[data-note-id]").evaluate_all(
            "rows => rows.map(row => Number(row.dataset.noteId))"
        )[:5]
        == ids
    )


def test_empty_session_list_reopens_after_edit_and_selects_another_card(
    page: Page, live_app: LiveApp
) -> None:
    ids = _run(
        live_app,
        lambda col: [
            add_vocab_note(col, DeckId(1), front, back)
            for front, back in [
                ("First existing", "first answer"),
                ("Second existing", "second answer"),
            ]
        ],
    )
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/app/edit/1/front")
    opener = page.locator("#pile")
    cards = page.locator("#deck-cards")
    front = page.locator("#input-front")

    opener.click()
    cards.locator(f"button[data-note-id='{ids[0]}']").click()
    expect(cards).not_to_be_visible()
    expect(front).to_have_value("First existing")
    expect(front).to_be_focused()
    front.fill("Edited existing")
    front.press("Enter")
    _wait_for_back(page)
    page.locator("#input-back").press("Enter")
    page.locator("#btn-add").click()
    expect(cards).to_be_visible()
    expect(cards).to_be_focused()
    expect(front).to_have_value("")
    assert (
        _run(live_app, lambda col: col.get_note(ids[0])["Front"]) == "Edited existing"
    )
    expect(page.locator("#added-cards .add-stack-count")).to_have_text("2")
    page.locator("#edit-back").click()
    expect(cards).not_to_be_visible()
    expect(page).to_have_url(f"{live_app}/app/edit/1/front")
    expect(opener).to_be_focused()
    page.get_by_role("button", name="Done", exact=True).click()
    summary = page.get_by_role("dialog")
    expect(summary).to_be_visible()
    expect(summary.locator("#summary-count")).to_have_text("0")
    page.keyboard.press("Escape")
    expect(summary).not_to_be_visible()
    expect(page.get_by_role("button", name="Done", exact=True)).to_be_focused()

    opener.click()
    expect(cards).to_be_visible()
    expect(cards.locator(f"button[data-note-id='{ids[0]}']")).to_be_visible()
    expect(cards.locator(f"button[data-note-id='{ids[0]}']")).to_contain_text(
        "Edited existing"
    )
    second = cards.locator(f"button[data-note-id='{ids[1]}']")
    expect(second).to_be_visible()
    second.click()
    expect(cards).not_to_be_visible()
    expect(front).to_have_value("Second existing")
    expect(front).to_be_focused()
    expect(page.locator("#input-back")).to_have_value("second answer")


@pytest.mark.parametrize(
    ("live_app", "error"),
    [
        ("", "This card is unavailable for editing. Please try again."),
        ("de_DE", "Diese Karte kann nicht bearbeitet werden. Bitte erneut versuchen."),
    ],
    indirect=["live_app"],
)
def test_failed_card_load_keeps_list_open_and_can_retry(
    page: Page, live_app: LiveApp, error: str
) -> None:
    nid = _run(
        live_app, lambda col: add_vocab_note(col, DeckId(1), "Retry card", "answer")
    )
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/app/edit/1/front")
    page.locator("#pile").click()
    cards = page.locator("#deck-cards")
    row = cards.locator(f"button[data-note-id='{nid}']")
    url = f"{live_app}/app/edit/1/*/*/card/{nid}"
    page.route(url, lambda route: route.fulfill(status=404, body="Unavailable"))
    row.click()
    alert = page.locator("#edit-error")
    expect(alert).to_be_visible()
    expect(alert).to_contain_text(error)
    expect(cards).to_be_visible()
    expect(page).to_have_url(f"{live_app}/app/edit/1/cards")
    expect(row).to_be_enabled()
    expect(page.locator("#input-front")).not_to_be_visible()
    assert _run(live_app, lambda col: col.get_note(nid)["Front"]) == "Retry card"

    page.unroute(url)
    row.click()
    expect(cards).not_to_be_visible()
    expect(alert).not_to_be_visible()
    expect(page).to_have_url(f"{live_app}/app/edit/1/cards/{nid}/front")
    expect(page.locator("#input-front")).to_have_value("Retry card")
    expect(page.locator("#input-front")).to_be_focused()


def test_browser_back_traverses_card_list_editor_and_decks(
    page: Page, live_app: LiveApp
) -> None:
    nid = _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Saved", "answer"))
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    cards_url = f"{editor_url.removesuffix('/front')}/cards"
    card_url = f"{editor_url.removesuffix('/front')}/cards/{nid}/front"
    page.goto(f"{live_app}/app/")
    page.goto(editor_url)
    cards = page.locator("#deck-cards")
    expect(_front(page)).to_have_value("")

    page.locator("#pile").click()
    expect(page).to_have_url(cards_url)
    expect(cards).to_be_visible()
    cards.locator(f"button[data-note-id='{nid}']").click()
    expect(page).to_have_url(card_url)
    expect(_front(page)).to_have_value("Saved")
    expect(_back(page)).to_have_value("answer")

    page.go_back()
    expect(page).to_have_url(cards_url)
    expect(cards).to_be_visible()
    expect(cards.locator(f"button[data-note-id='{nid}']")).to_contain_text("Saved")
    page.go_back()
    expect(page).to_have_url(editor_url)
    expect(cards).not_to_be_visible()
    expect(_front(page)).to_be_visible()
    expect(_front(page)).to_have_value("")
    page.go_back()
    expect(page).to_have_url(f"{live_app}/app/")


def test_reload_dirty_card_rejected_back_preserves_history(
    page: Page, live_app: LiveApp
) -> None:
    nid = _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Saved", "answer"))
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    cards_url = f"{editor_url.removesuffix('/front')}/cards"
    card_url = f"{editor_url.removesuffix('/front')}/cards/{nid}/front"
    page.goto(f"{live_app}/app/")
    page.goto(editor_url)
    page.locator("#pile").click()
    cards = page.locator("#deck-cards")
    cards.locator(f"button[data-note-id='{nid}']").click()
    expect(_front(page)).to_have_value("Saved")
    page.reload()
    expect(_front(page)).to_have_value("Saved")
    _front(page).fill("Unsaved")
    page.evaluate(
        "() => { window.historyPops = []; window.addEventListener('popstate', () => window.historyPops.push(location.href)); }"
    )
    rejected = _respond_to_confirm(page, accept=False)
    page.go_back()
    page.wait_for_function("() => window.historyPops.length >= 2")
    assert len(rejected) == 1
    expect(page).to_have_url(card_url)
    expect(_front(page)).to_have_value("Unsaved")

    accepted = _respond_to_confirm(page, accept=True)
    page.go_back()
    expect(page).to_have_url(cards_url)
    expect(cards).to_be_visible()
    expect(page.locator("#edit-session")).to_have_attribute("data-nid", "0")
    assert len(accepted) == 1
    page.go_back()
    expect(page).to_have_url(editor_url)
    expect(_front(page)).to_have_value("")
    page.go_forward()
    expect(page).to_have_url(cards_url)
    expect(cards.locator(f"button[data-note-id='{nid}']")).to_contain_text("Saved")
    page.go_forward()
    expect(page).to_have_url(card_url)
    expect(_front(page)).to_have_value("Saved")
    expect(cards).not_to_be_visible()
    page.go_back()
    expect(page).to_have_url(cards_url)
    expect(cards).to_be_visible()
    expect(page.locator("#edit-session")).to_have_attribute("data-nid", "0")
    page.go_back()
    expect(page).to_have_url(editor_url)
    page.go_back()
    expect(page).to_have_url(f"{live_app}/app/")


def test_reload_list_keeps_back_and_rejected_forward_usable(
    page: Page, live_app: LiveApp
) -> None:
    _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Saved", "answer"))
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    cards_url = f"{editor_url.removesuffix('/front')}/cards"
    page.goto(f"{live_app}/app/")
    page.goto(editor_url)
    page.locator("#pile").click()
    expect(page).to_have_url(cards_url)
    page.reload()
    expect(page.locator("#deck-cards")).to_be_visible()
    page.go_back()
    expect(page).to_have_url(editor_url)
    _front(page).fill("Unsaved")
    page.evaluate(
        "() => { window.historyPops = []; window.addEventListener('popstate', () => window.historyPops.push(location.href)); }"
    )
    rejected = _respond_to_confirm(page, accept=False)
    page.go_forward()
    page.wait_for_function("() => window.historyPops.length >= 2")
    assert len(rejected) == 1
    expect(page).to_have_url(editor_url)
    expect(_front(page)).to_have_value("Unsaved")
    accepted = _respond_to_confirm(page, accept=True)
    page.go_forward()
    expect(page).to_have_url(cards_url)
    expect(page.locator("#deck-cards")).to_contain_text("Saved")
    assert len(accepted) == 1
    page.go_back()
    expect(page).to_have_url(editor_url)
    page.go_back()
    expect(page).to_have_url(f"{live_app}/app/")


def test_browser_forward_reloads_each_card_from_list(
    page: Page, live_app: LiveApp
) -> None:
    ids = _run(
        live_app,
        lambda col: [
            add_vocab_note(col, DeckId(1), front, back)
            for front, back in [("First", "first answer"), ("Second", "second answer")]
        ],
    )
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    cards_url = f"{editor_url.removesuffix('/front')}/cards"
    page.goto(editor_url)
    page.locator("#pile").click()
    cards = page.locator("#deck-cards")
    expect(cards).to_be_visible()

    for nid, front, back in zip(
        ids, ("First", "Second"), ("first answer", "second answer"), strict=True
    ):
        cards.locator(f"button[data-note-id='{nid}']").click()
        expect(page).to_have_url(
            f"{editor_url.removesuffix('/front')}/cards/{nid}/front"
        )
        expect(_front(page)).to_have_value(front)
        page.go_back()
        expect(page).to_have_url(cards_url)
        expect(cards).to_be_visible()
        with page.expect_request(f"{live_app}/app/edit/1/*/*/card/{nid}") as request:
            page.go_forward()
        assert request.value.method == "POST"
        expect(page).to_have_url(
            f"{editor_url.removesuffix('/front')}/cards/{nid}/front"
        )
        expect(cards).not_to_be_visible()
        expect(_front(page)).to_have_value(front)
        expect(_back(page)).to_have_value(back)
        page.go_back()
        expect(page).to_have_url(cards_url)
        expect(cards).to_be_visible()


def test_history_card_load_blocks_reverse_navigation_until_complete(
    page: Page, live_app: LiveApp
) -> None:
    nid = _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Saved", "answer"))
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    cards_url = f"{editor_url.removesuffix('/front')}/cards"
    card_url = f"{editor_url.removesuffix('/front')}/cards/{nid}/front"
    page.goto(editor_url)
    page.locator("#pile").click()
    cards = page.locator("#deck-cards")
    row = cards.locator(f"button[data-note-id='{nid}']")
    row.click()
    expect(_front(page)).to_have_value("Saved")
    page.go_back()
    expect(page).to_have_url(cards_url)
    expect(cards).to_be_visible()

    pending: list[Route] = []
    load_url = f"{live_app}/app/edit/1/*/*/card/{nid}"

    def hold_load(route: Route) -> None:
        pending.append(route)

    page.route(load_url, hold_load)
    with page.expect_request(load_url):
        page.go_forward()
    expect(page).to_have_url(card_url)
    expect(row).to_be_disabled()
    row.evaluate("(row) => row.click()")
    assert len(pending) == 1
    page.evaluate(
        "() => { window.historyPops = []; window.addEventListener('popstate', () => window.historyPops.push(location.href)); }"
    )
    page.go_back()
    page.wait_for_function("() => window.historyPops.length >= 2")
    expect(page).to_have_url(card_url)
    expect(cards).to_be_visible()
    assert len(pending) == 1
    pending[0].continue_()
    expect(cards).not_to_be_visible()
    expect(_front(page)).to_have_value("Saved")
    expect(_back(page)).to_have_value("answer")
    expect(page).to_have_url(card_url)

    page.go_back()
    expect(page).to_have_url(cards_url)
    expect(cards).to_be_visible()
    expect(row).to_be_enabled()


def test_failed_history_card_load_restores_usable_editor(
    page: Page, live_app: LiveApp
) -> None:
    nid = _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Saved", "answer"))
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    page.goto(editor_url)
    page.locator("#pile").click()
    cards = page.locator("#deck-cards")
    row = cards.locator(f"button[data-note-id='{nid}']")
    row.click()
    expect(_front(page)).to_have_value("Saved")
    page.go_back()
    expect(cards).to_be_visible()
    load_url = f"{live_app}/app/edit/1/*/*/card/{nid}"
    page.route(load_url, lambda route: route.fulfill(status=404, body="Unavailable"))
    page.go_forward()
    expect(page.locator("#edit-error")).to_be_visible()
    expect(page).to_have_url(editor_url)
    expect(_front(page)).to_be_visible()
    expect(_front(page)).to_have_value("")
    page.unroute(load_url)
    page.locator("#pile").click()
    expect(row).to_be_enabled()
    row.click()
    expect(_front(page)).to_have_value("Saved")
    expect(page).to_have_url(f"{editor_url.removesuffix('/front')}/cards/{nid}/front")


def test_history_card_error_patch_restores_editor_and_next_card_url(
    page: Page, live_app: LiveApp
) -> None:
    first, second = _run(
        live_app,
        lambda col: [
            add_vocab_note(col, DeckId(1), front, back)
            for front, back in [("First", "first answer"), ("Second", "second answer")]
        ],
    )
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    cards_url = f"{editor_url.removesuffix('/front')}/cards"
    page.goto(editor_url)
    page.locator("#pile").click()
    cards = page.locator("#deck-cards")
    cards.locator(f"button[data-note-id='{first}']").click()
    expect(page).to_have_url(f"{editor_url.removesuffix('/front')}/cards/{first}/front")
    expect(_front(page)).to_have_value("First")
    page.go_back()
    expect(page).to_have_url(cards_url)
    expect(cards).to_be_visible()

    load_url = f"{live_app}/app/edit/1/*/*/card/{first}"

    def fail_load(route: Route) -> None:
        parts = urlsplit(route.request.url).path.split("/")
        instance, revision = parts[4:6]
        selector = f'#edit-session[data-instance="{instance}"][data-rev="{revision}"] #edit-error'
        route.fulfill(
            status=200,
            content_type="text/event-stream",
            body=(
                "event: datastar-patch-elements\n"
                f"data: selector {selector}\n"
                'data: elements <div id="edit-error" role="alert">'
                "Could not add the card. Please try again.</div>\n\n"
            ),
        )

    page.route(load_url, fail_load)
    with page.expect_request(load_url) as request:
        page.go_forward()
    assert request.value.method == "POST"
    alert = page.locator("#edit-error")
    expect(alert).to_be_visible()
    expect(alert).to_contain_text("Could not add the card. Please try again.")
    expect(page).to_have_url(editor_url)
    expect(cards).not_to_be_visible()
    expect(_front(page)).to_be_visible()
    expect(_front(page)).to_have_value("")

    page.unroute(load_url)
    page.locator("#pile").click()
    expect(page).to_have_url(cards_url)
    row = cards.locator(f"button[data-note-id='{second}']")
    expect(row).to_be_enabled()
    row.click()
    expect(cards).not_to_be_visible()
    expect(alert).not_to_be_visible()
    expect(_front(page)).to_have_value("Second")
    expect(_front(page)).to_be_focused()
    expect(_back(page)).to_have_value("second answer")
    expect(page).to_have_url(
        f"{editor_url.removesuffix('/front')}/cards/{second}/front"
    )


def test_forward_card_load_clears_previous_card_error(
    page: Page, live_app: LiveApp
) -> None:
    first, second = _run(
        live_app,
        lambda col: [
            add_vocab_note(col, DeckId(1), front, back)
            for front, back in [("First", "first answer"), ("Second", "second answer")]
        ],
    )
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    cards_url = f"{editor_url.removesuffix('/front')}/cards"
    page.goto(editor_url)
    page.locator("#pile").click()
    cards = page.locator("#deck-cards")
    cards.locator(f"button[data-note-id='{first}']").click()
    expect(page).to_have_url(f"{editor_url.removesuffix('/front')}/cards/{first}/front")
    expect(_front(page)).to_have_value("First")
    page.go_back()
    expect(page).to_have_url(cards_url)
    expect(cards).to_be_visible()

    second_url = f"{live_app}/app/edit/1/*/*/card/{second}"
    page.route(second_url, lambda route: route.fulfill(status=404, body="Unavailable"))
    second_row = cards.locator(f"button[data-note-id='{second}']")
    second_row.click()
    alert = page.locator("#edit-error")
    expect(alert).to_be_visible()
    expect(alert).to_contain_text(
        "This card is unavailable for editing. Please try again."
    )
    expect(page).to_have_url(cards_url)
    expect(second_row).to_be_enabled()
    page.unroute(second_url)

    with page.expect_request(f"{live_app}/app/edit/1/*/*/card/{first}") as request:
        page.go_forward()
    assert request.value.method == "POST"
    expect(alert).not_to_be_visible()
    expect(page).to_have_url(f"{editor_url.removesuffix('/front')}/cards/{first}/front")
    expect(cards).not_to_be_visible()
    expect(_front(page)).to_have_value("First")
    expect(_front(page)).to_be_focused()
    expect(_back(page)).to_have_value("first answer")


def test_unrelated_failed_preview_does_not_cancel_history_card_load(
    page: Page, live_app: LiveApp
) -> None:
    nid = _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Saved", "answer"))
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    cards_url = f"{editor_url.removesuffix('/front')}/cards"
    card_url = f"{editor_url.removesuffix('/front')}/cards/{nid}/front"
    page.goto(editor_url)
    page.locator("#pile").click()
    cards = page.locator("#deck-cards")
    cards.locator(f"button[data-note-id='{nid}']").click()
    expect(page).to_have_url(card_url)
    expect(_front(page)).to_have_value("Saved")

    previews: list[Route] = []
    preview_url = f"{live_app}/app/edit/1/*/*/step/preview/*"

    def hold_preview(route: Route) -> None:
        previews.append(route)

    page.route(preview_url, hold_preview)
    _front(page).press("Enter")
    _wait_for_back(page)
    expect(page.locator("#btn-next")).to_contain_text("Preview")
    page.evaluate(
        """() => {
          window.previewFinished = false;
          document.addEventListener('datastar-fetch', event => {
            if (event.detail.el.id === 'edit-step-request' && event.detail.type === 'finished')
              window.previewFinished = true;
          });
        }"""
    )
    with page.expect_request(preview_url):
        _back(page).press("Enter")
    assert len(previews) == 1
    page.evaluate("history.go(-2)")
    expect(page).to_have_url(cards_url)
    expect(cards).to_be_visible()

    loads: list[Route] = []
    load_url = f"{live_app}/app/edit/1/*/*/card/{nid}"

    def hold_load(route: Route) -> None:
        loads.append(route)
        page.evaluate("() => { window.historyLoadHeld = true; }")

    page.route(load_url, hold_load)
    with page.expect_request(load_url):
        page.go_forward()
    page.wait_for_function("() => window.historyLoadHeld === true")
    assert len(loads) == 1
    previews[0].fulfill(status=404, body="Unavailable")
    page.wait_for_function("() => window.previewFinished")
    expect(page).to_have_url(card_url)
    expect(cards).to_be_visible()
    expect(page.locator("#edit-error")).not_to_be_visible()

    loads[0].continue_()
    expect(cards).not_to_be_visible()
    expect(_front(page)).to_have_value("Saved")
    expect(_front(page)).to_be_focused()
    expect(_back(page)).to_have_value("answer")
    expect(page).to_have_url(card_url)


def test_history_navigation_closes_summary_and_focuses_destination(
    page: Page, live_app: LiveApp
) -> None:
    nid = _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Saved", "answer"))
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    page.goto(editor_url)
    _add(page, "Session addition", "answer")
    page.locator("#pile").click()
    cards = page.locator("#deck-cards")
    cards.locator(f"button[data-note-id='{nid}']").click()
    expect(_front(page)).to_have_value("Saved")
    page.get_by_role("button", name="Done", exact=True).click()
    summary = page.get_by_role("dialog")
    expect(summary).to_be_visible()
    expect(summary.locator("#summary-keep-adding")).to_be_focused()
    expect(page.locator("#edit-session")).to_have_attribute("data-nid", "0")
    page.go_back()
    expect(page).to_have_url(f"{editor_url.removesuffix('/front')}/cards")
    expect(summary).not_to_be_visible()
    expect(cards).to_be_visible()
    expect(cards).to_be_focused()
    page.go_forward()
    expect(page).to_have_url(editor_url)
    expect(summary).not_to_be_visible()
    expect(cards).not_to_be_visible()
    expect(page.locator("#pile")).to_be_focused()


def test_rejected_forward_preserves_previous_history_entry(
    page: Page, live_app: LiveApp
) -> None:
    nid = _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Saved", "answer"))
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    page.goto(f"{live_app}/app/")
    page.goto(editor_url)
    page.locator("#pile").click()
    page.locator(f"#deck-cards button[data-note-id='{nid}']").click()
    expect(_front(page)).to_have_value("Saved")
    page.go_back()
    expect(page.locator("#deck-cards")).to_be_visible()
    expect(page.locator("#edit-session")).to_have_attribute("data-nid", "0")
    page.go_back()
    expect(page).to_have_url(editor_url)
    expect(_front(page)).to_be_visible()
    _front(page).fill("Unsaved")
    page.evaluate(
        "() => { window.historyPops = []; window.addEventListener('popstate', () => window.historyPops.push(location.href)); }"
    )
    rejected = _respond_to_confirm(page, accept=False)
    page.go_forward()
    page.wait_for_function("() => window.historyPops.length >= 2")
    expect(page).to_have_url(editor_url)
    assert len(rejected) == 1
    expect(_front(page)).to_have_value("Unsaved")
    page.go_back()
    expect(page).to_have_url(f"{live_app}/app/")


def test_browser_back_during_list_opening_finishes_at_editor(
    page: Page, live_app: LiveApp
) -> None:
    nid = _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Saved", "answer"))
    page.emulate_media(reduced_motion="no-preference")
    editor_url = f"{live_app}/app/edit/1/front"
    page.goto(editor_url)
    wizard = page.locator("#add-wizard")
    cards = page.locator("#deck-cards")
    page.locator("#pile").click()
    expect(cards).to_be_visible()
    cards.locator(f"button[data-note-id='{nid}']").click()
    expect(_front(page)).to_have_value("Saved")
    expect(wizard).to_have_attribute("data-browse-phase", "closed")

    page.go_back()
    expect(page).to_have_url(f"{editor_url.removesuffix('/front')}/cards")
    expect(wizard).to_have_attribute("data-browse-phase", "opening")
    page.go_back()
    expect(page).to_have_url(editor_url)
    expect(wizard).to_have_attribute("data-browse-phase", "closed")
    expect(cards).not_to_be_visible()
    expect(_front(page)).to_be_visible()
    expect(_front(page)).to_have_value("")


def test_done_while_editing_keeps_url_and_editor_in_sync(
    page: Page, live_app: LiveApp
) -> None:
    nid = _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Saved", "answer"))
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    card_url = f"{editor_url.removesuffix('/front')}/cards/{nid}/front"
    page.goto(editor_url)
    _add(page, "Session addition", "answer")
    original = live_app.notes()
    page.locator("#pile").click()
    page.locator(f"#deck-cards button[data-note-id='{nid}']").click()
    expect(page).to_have_url(card_url)
    expect(_front(page)).to_have_value("Saved")
    _front(page).fill("Unsaved edit")
    done = page.get_by_role("button", name="Done", exact=True)
    rejected = _respond_to_confirm(page, accept=False)
    done.click()
    assert len(rejected) == 1
    expect(page).to_have_url(card_url)
    expect(_front(page)).to_have_value("Unsaved edit")
    expect(page.get_by_role("dialog")).not_to_be_visible()

    accepted = _respond_to_confirm(page, accept=True)
    done.click()
    assert len(accepted) == 1
    summary = page.get_by_role("dialog")
    expect(summary).to_be_visible()
    expect(page).to_have_url(editor_url)
    page.keyboard.press("Escape")
    expect(summary).not_to_be_visible()
    expect(_front(page)).to_be_visible()
    expect(_front(page)).to_have_value("")
    expect(page.locator("#edit-back")).to_have_accessible_name("Exit Creator")
    page.reload()
    expect(page).to_have_url(editor_url)
    expect(_front(page)).to_have_value("")
    assert live_app.notes() == original


def test_direct_card_list_reload_and_ui_back(page: Page, live_app: LiveApp) -> None:
    nid = _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Listed", "answer"))
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    cards_url = f"{editor_url.removesuffix('/front')}/cards"
    page.goto(cards_url)
    cards = page.locator("#deck-cards")
    expect(cards).to_be_visible()
    expect(cards.locator(f"button[data-note-id='{nid}']")).to_contain_text("Listed")
    page.reload()
    expect(page).to_have_url(cards_url)
    expect(cards).to_be_visible()
    expect(cards.locator(f"button[data-note-id='{nid}']")).to_contain_text("Listed")
    page.locator("#edit-back").click()
    expect(page).to_have_url(editor_url)
    expect(cards).not_to_be_visible()
    expect(_front(page)).to_have_value("")


def test_direct_card_reload_and_ui_back_to_list(page: Page, live_app: LiveApp) -> None:
    nid = _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Direct", "answer"))
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    page.goto(f"{editor_url.removesuffix('/front')}/cards/{nid}/front")
    expect(page).to_have_url(f"{editor_url.removesuffix('/front')}/cards/{nid}/front")
    expect(_front(page)).to_be_visible()
    expect(_front(page)).to_have_value("Direct")
    expect(_back(page)).to_have_value("answer")
    expect(page.locator("#edit-back")).to_have_accessible_name("Back to cards")
    page.reload()
    expect(_front(page)).to_have_value("Direct")
    expect(_back(page)).to_have_value("answer")

    page.locator("#edit-back").click()
    expect(page).to_have_url(f"{editor_url.removesuffix('/front')}/cards")
    cards = page.locator("#deck-cards")
    expect(cards).to_be_visible()
    expect(cards.locator(f"button[data-note-id='{nid}']")).to_contain_text("Direct")
    page.locator("#edit-back").click()
    expect(page).to_have_url(editor_url)
    expect(_front(page)).to_be_visible()
    expect(_front(page)).to_have_value("")


@pytest.mark.parametrize(
    "state",
    [
        None,
        {"avEdit": True, "avIndex": -1},
        {"avEdit": True, "avIndex": "2"},
        {"avEdit": True, "avIndex": 999999},
        {"avEdit": False, "avIndex": 0},
    ],
)
def test_invalid_history_state_on_direct_card_keeps_navigation_usable(
    page: Page, live_app: LiveApp, state: dict | None
) -> None:
    nid = _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Direct", "answer"))
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    page.goto(f"{editor_url.removesuffix('/front')}/cards/{nid}/front")
    expect(_front(page)).to_have_value("Direct")
    page.evaluate("(state) => history.replaceState(state, '', location.href)", state)
    page.reload()
    expect(_front(page)).to_have_value("Direct")
    page.locator("#edit-back").click()
    expect(page).to_have_url(f"{editor_url.removesuffix('/front')}/cards")
    expect(page.locator("#deck-cards")).to_contain_text("Direct")
    page.locator("#edit-back").click()
    expect(page).to_have_url(editor_url)
    expect(_front(page)).to_have_value("")


def test_reload_preserves_saved_list_navigation(page: Page, live_app: LiveApp) -> None:
    nid = _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Saved", "answer"))
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    cards_url = f"{editor_url.removesuffix('/front')}/cards"
    page.goto(editor_url)
    page.locator("#pile").click()
    page.locator(f"#deck-cards button[data-note-id='{nid}']").click()
    expect(_front(page)).to_have_value("Saved")
    # Simulate the duplicate list entry with the current history state.
    page.evaluate(
        "(url) => history.replaceState({avEdit: true, avIndex: 2, avEditorIndex: 0}, '', url)",
        cards_url,
    )
    page.reload()
    expect(page.locator("#deck-cards")).to_be_visible()
    page.locator("#edit-back").click()
    expect(page).to_have_url(editor_url)
    expect(_front(page)).to_have_value("")
    page.go_forward()
    expect(page).to_have_url(cards_url)
    expect(page.locator("#deck-cards")).to_contain_text("Saved")


def test_direct_card_preserves_special_fields_without_executing_them(
    page: Page, live_app: LiveApp
) -> None:
    front = "C:\\"
    back = 'a; b ${window.directLinkInjected = true} <b>"quotes"</b>\nsecond'
    hint = "O'Reilly \\"
    example = "`$front`; </textarea> & more"

    def seed(col: Collection) -> NoteId:
        nid = add_vocab_note(col, DeckId(1), front, back, hint, example)
        card = col.get_note(nid).cards()[0]
        card.type = CardType(2)
        card.queue = CardQueue(2)
        col.update_card(card)
        return nid

    nid = _run(live_app, seed)
    page.emulate_media(reduced_motion="reduce")
    requests: list[str] = []
    page.on(
        "request",
        lambda request: (
            requests.append(request.url) if request.method == "POST" else None
        ),
    )
    editor_url = f"{live_app}/app/edit/1/front"
    page.goto(f"{editor_url.removesuffix('/front')}/cards/{nid}/front")
    for visit in range(2):
        expect(_front(page)).to_have_value(front)
        expect(_back(page)).to_have_value(back)
        expect(page.locator("#input-hint")).to_have_value(hint)
        expect(page.locator("#input-example")).to_have_value(example)
        expect(page.locator("#edit-warning")).to_be_visible()
        assert page.evaluate("window.directLinkInjected") is None
        if visit == 0:
            page.reload()
    assert requests == []
    _front(page).fill("Changed")
    rejected = _respond_to_confirm(page, accept=False)
    page.locator("#edit-back").click()
    assert len(rejected) == 1
    expect(_front(page)).to_have_value("Changed")
    _front(page).fill(front)
    page.locator("#edit-back").click()
    expect(page).to_have_url(f"{editor_url.removesuffix('/front')}/cards")
    expect(page.locator("#deck-cards")).to_be_visible()
    page.locator(f"#deck-cards button[data-note-id='{nid}']").click()
    expect(_front(page)).to_have_value(front)
    expect(page.locator("#edit-back")).to_have_attribute("aria-disabled", "false")
    _front(page).fill("Changed again")
    page.evaluate(
        "() => { window.historyPops = []; window.addEventListener('popstate', () => window.historyPops.push(location.href)); }"
    )
    rejected = _respond_to_confirm(page, accept=False)
    page.go_back()
    page.wait_for_function("() => window.historyPops.length >= 2")
    assert len(rejected) == 1
    expect(page).to_have_url(f"{editor_url.removesuffix('/front')}/cards/{nid}/front")
    expect(_front(page)).to_have_value("Changed again")
    accepted = _respond_to_confirm(page, accept=True)
    page.go_back()
    expect(page).to_have_url(f"{editor_url.removesuffix('/front')}/cards")
    expect(page.locator("#deck-cards")).to_be_visible()
    assert len(accepted) == 1


@pytest.mark.parametrize("card", ["not-a-note", "999999999999999"])
def test_invalid_direct_card_opens_plain_editor(
    page: Page, live_app: LiveApp, card: str
) -> None:
    _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Saved", "answer"))
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    page.goto(f"{editor_url.removesuffix('/front')}/cards/{card}/front")
    expect(page).to_have_url(editor_url)
    expect(page.locator("#deck-cards")).not_to_be_visible()
    expect(_front(page)).to_be_visible()
    expect(_front(page)).to_have_value("")
    expect(_back(page)).to_have_value("")
    expect(page.locator("#edit-back")).to_have_accessible_name("Exit Creator")


def test_save_returns_to_list_without_duplicate_browser_back(
    page: Page, live_app: LiveApp
) -> None:
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    cards_url = f"{editor_url.removesuffix('/front')}/cards"
    page.goto(f"{live_app}/app/")
    page.goto(editor_url)
    _add(page, "Saved", "answer")
    nid = NoteId(live_app.notes()[0][0])
    page.locator("#pile").click()
    cards = page.locator("#deck-cards")
    expect(page).to_have_url(cards_url)
    cards.locator(f"button[data-note-id='{nid}']").click()
    expect(page).to_have_url(f"{editor_url.removesuffix('/front')}/cards/{nid}/front")
    expect(_front(page)).to_have_value("Saved")
    _front(page).fill("Updated")
    _front(page).press("Enter")
    _wait_for_back(page)
    _back(page).press("Enter")
    page.locator("#btn-add").click()
    expect(page).to_have_url(cards_url)
    expect(cards).to_be_visible()
    expect(cards.locator(f"button[data-note-id='{nid}']")).to_contain_text("Updated")
    assert _run(live_app, lambda col: col.get_note(nid)["Front"]) == "Updated"

    page.go_back()
    expect(page).to_have_url(editor_url)
    expect(_front(page)).to_be_visible()
    expect(_front(page)).to_have_value("")
    expect(page.locator("#added-cards")).to_contain_text("Updated")
    page.get_by_role("button", name="Done", exact=True).click()
    summary = page.get_by_role("dialog")
    expect(summary).to_be_visible()
    expect(summary.locator("#summary-count")).to_have_text("1")
    page.keyboard.press("Escape")
    expect(summary).not_to_be_visible()
    page.go_forward()
    expect(page).to_have_url(cards_url)
    expect(cards.locator(f"button[data-note-id='{nid}']")).to_contain_text("Updated")
    page.go_forward()
    expect(page).to_have_url(cards_url)
    expect(cards).to_be_visible()
    page.locator("#edit-back").click()
    expect(page).to_have_url(editor_url)
    expect(_front(page)).to_have_value("")
    page.go_back()
    expect(page).to_have_url(f"{live_app}/app/")


def test_save_direct_card_back_and_forward_remain_usable(
    page: Page, live_app: LiveApp
) -> None:
    nid = _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Direct", "answer"))
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    cards_url = f"{editor_url.removesuffix('/front')}/cards"
    page.goto(f"{live_app}/app/")
    page.goto(f"{editor_url.removesuffix('/front')}/cards/{nid}/front")
    expect(_front(page)).to_have_value("Direct")
    _front(page).fill("Updated direct")
    _front(page).press("Enter")
    _wait_for_back(page)
    _back(page).press("Enter")
    page.locator("#btn-add").click()
    expect(page).to_have_url(cards_url)
    expect(page.locator("#deck-cards")).to_contain_text("Updated direct")
    page.go_back()
    expect(page).to_have_url(f"{live_app}/app/")
    page.go_forward()
    expect(page).to_have_url(cards_url)
    expect(page.locator("#deck-cards")).to_contain_text("Updated direct")
    page.locator("#edit-back").click()
    expect(page).to_have_url(editor_url)
    expect(_front(page)).to_have_value("")


@pytest.mark.parametrize("direct_list", [False, True])
def test_list_back_after_consecutive_saved_cards(
    page: Page, live_app: LiveApp, direct_list: bool
) -> None:
    ids = _run(
        live_app,
        lambda col: [
            add_vocab_note(col, DeckId(1), front, "answer")
            for front in ("First", "Second")
        ],
    )
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    page.goto(f"{live_app}/app/")
    page.goto(
        f"{editor_url.removesuffix('/front')}/cards" if direct_list else editor_url
    )
    if not direct_list:
        page.locator("#pile").click()
    cards = page.locator("#deck-cards")
    expect(cards).to_be_visible()
    for nid, original in zip(ids, ("First", "Second"), strict=True):
        row = cards.locator(f"button[data-note-id='{nid}']")
        row.click()
        expect(_front(page)).to_have_value(original)
        expect(page.locator("#edit-back")).to_have_attribute("aria-disabled", "false")
        _front(page).fill(f"{original} updated")
        _front(page).press("Enter")
        _wait_for_back(page)
        _back(page).press("Enter")
        page.locator("#btn-add").click()
        expect(page).to_have_url(f"{editor_url.removesuffix('/front')}/cards")
        expect(cards).to_be_visible()
        expect(row).to_contain_text(f"{original} updated")

    page.reload()
    expect(cards).to_be_visible()
    if not direct_list:
        page.go_back()
        expect(page).to_have_url(editor_url)
        expect(_front(page)).to_have_value("")
        page.go_forward()
        expect(page).to_have_url(f"{editor_url.removesuffix('/front')}/cards")
        expect(cards).to_contain_text("First updated")
        expect(cards).to_contain_text("Second updated")
        page.go_forward()
        expect(page).to_have_url(f"{editor_url.removesuffix('/front')}/cards")
        expect(cards).to_be_visible()

    page.locator("#edit-back").click()
    expect(page).to_have_url(editor_url)
    expect(cards).not_to_be_visible()
    expect(_front(page)).to_have_value("")
    expect(page.locator("#pile")).to_be_focused()
    assert [
        _run(live_app, lambda col, nid=nid: col.get_note(nid)["Front"]) for nid in ids
    ] == [
        "First updated",
        "Second updated",
    ]


def test_unchanged_and_dirty_edits_guard_discard(page: Page, live_app: LiveApp) -> None:
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/app/edit/1/front")
    _add(page, "First", "first answer")
    _add(page, "Second", "second answer")
    original = live_app.notes()
    first, second = (note[0] for note in original)
    pile = page.locator("#pile")
    cards = page.locator("#deck-cards")
    back = page.locator("#edit-back")
    pile.click()
    cards.locator(f"button[data-note-id='{first}']").click()
    expect(_front(page)).to_have_value("First")
    expect(_front(page)).to_be_focused()
    expect(back).to_have_accessible_name("Back to cards")

    unexpected: list[str] = []

    def dismiss_unexpected(dialog: Dialog) -> None:
        unexpected.append(dialog.message)
        dialog.dismiss()

    page.on("dialog", dismiss_unexpected)
    back.click()
    expect(cards).to_be_visible()
    expect(page).to_have_url(f"{live_app}/app/edit/1/cards")
    assert unexpected == []
    cards.locator(f"button[data-note-id='{first}']").click()
    expect(_front(page)).to_have_value("First")
    _front(page).fill("Temporary change")
    _front(page).fill("First")
    back.click()
    expect(cards).to_be_visible()
    expect(page).to_have_url(f"{live_app}/app/edit/1/cards")
    cards.locator(f"button[data-note-id='{second}']").click()
    expect(_front(page)).to_have_value("Second")
    page.remove_listener("dialog", dismiss_unexpected)
    assert unexpected == []

    _front(page).fill("Changed second")
    rejected = _respond_to_confirm(page, accept=False)
    back.click()
    assert len(rejected) == 1
    expect(cards).not_to_be_visible()
    expect(_front(page)).to_have_value("Changed second")
    expect(page).to_have_url(f"{live_app}/app/edit/1/cards/{second}/front")
    accepted = _respond_to_confirm(page, accept=True)
    back.click()
    assert len(accepted) == 1
    expect(cards).to_be_visible()
    expect(back).to_have_accessible_name("Back to card editor")
    expect(page).to_have_url(f"{live_app}/app/edit/1/cards")
    expect(cards.locator(f"button[data-note-id='{second}']")).to_contain_text("Second")

    cards.locator(f"button[data-note-id='{first}']").click()
    expect(_front(page)).to_have_value("First")
    _front(page).fill("Changed first")
    rejected = _respond_to_confirm(page, accept=False)
    page.go_back()
    expect(page).to_have_url(f"{live_app}/app/edit/1/cards/{first}/front")
    assert len(rejected) == 1
    expect(_front(page)).to_have_value("Changed first")
    expect(cards).not_to_be_visible()
    accepted = _respond_to_confirm(page, accept=True)
    page.go_back()
    expect(page).to_have_url(f"{live_app}/app/edit/1/cards")
    assert len(accepted) == 1
    expect(cards).to_be_visible()
    expect(cards.locator(f"button[data-note-id='{first}']")).to_contain_text("First")

    cards.locator(f"button[data-note-id='{first}']").click()
    expect(_front(page)).to_have_value("First")
    _front(page).fill("Changed with Escape")
    rejected = _respond_to_confirm(page, accept=False)
    page.keyboard.press("Escape")
    assert len(rejected) == 1
    expect(page).to_have_url(f"{live_app}/app/edit/1/cards/{first}/front")
    expect(_front(page)).to_have_value("Changed with Escape")
    accepted = _respond_to_confirm(page, accept=True)
    page.keyboard.press("Escape")
    assert len(accepted) == 1
    expect(page).to_have_url(f"{live_app}/app/edit/1/cards")
    expect(cards).to_be_visible()
    expect(cards.locator(f"button[data-note-id='{first}']")).to_contain_text("First")
    back.click()
    expect(page).to_have_url(f"{live_app}/app/edit/1/front")
    expect(_front(page)).to_have_value("")
    assert live_app.notes() == original


@pytest.mark.parametrize("key", ["Enter", "Space"])
def test_back_has_button_semantics_and_guards_for_browse_and_edit(
    page: Page, live_app: LiveApp, key: str
) -> None:
    nid = _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Saved", "answer"))
    page.emulate_media(reduced_motion="reduce")
    url = f"{live_app}/app/edit/1/front"
    page.goto(url)
    pile = page.locator("#pile")
    cards = page.locator("#deck-cards")
    back = page.locator("#edit-back")

    pile.click()
    expect(cards).to_be_focused()
    expect(back).to_have_role("button")
    expect(back).not_to_have_attribute("href", re.compile("."))
    back.click(button="middle")
    back.click(button="right")
    expect(cards).to_be_visible()
    expect(page).to_have_url(f"{url.removesuffix('/front')}/cards")
    assert len(page.context.pages) == 1
    back.focus()
    page.keyboard.press(key)
    expect(cards).not_to_be_visible()
    expect(pile).to_be_focused()

    pile.click()
    cards.locator(f"button[data-note-id='{nid}']").click()
    expect(_front(page)).to_have_value("Saved")
    _front(page).fill("Unsaved edit")
    expect(back).to_have_role("button")
    expect(back).not_to_have_attribute("href", re.compile("."))
    back.click(button="middle")
    back.click(button="right")
    expect(_front(page)).to_have_value("Unsaved edit")
    expect(cards).not_to_be_visible()
    expect(page).to_have_url(f"{url.removesuffix('/front')}/cards/{nid}/front")
    assert len(page.context.pages) == 1
    rejected = _respond_to_confirm(page, accept=False)
    back.focus()
    page.keyboard.press(key)
    assert len(rejected) == 1
    expect(_front(page)).to_have_value("Unsaved edit")
    accepted = _respond_to_confirm(page, accept=True)
    back.focus()
    page.keyboard.press(key)
    assert len(accepted) == 1
    expect(cards).to_be_visible()
    expect(cards).to_be_focused()
    expect(cards.locator(f"button[data-note-id='{nid}']")).to_contain_text("Saved")


def test_failed_edit_save_stays_in_editor_and_can_retry(
    page: Page, live_app: LiveApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    nid = _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Saved", "answer"))
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/app/edit/1/front")
    page.locator("#pile").click()
    cards = page.locator("#deck-cards")
    cards.locator(f"button[data-note-id='{nid}']").click()
    expect(_front(page)).to_have_value("Saved")
    _front(page).fill("Updated")
    _front(page).press("Enter")
    _wait_for_back(page)
    _back(page).press("Enter")

    def fail_update(*args, **kwargs):
        raise ValueError("deterministic update failure")

    with monkeypatch.context() as patch:
        patch.setattr(
            "ankiweb.core.app_client.note_editing.update_vocab_note_with_changes",
            fail_update,
        )
        page.locator("#btn-add").click()
        expect(page.locator("#edit-error")).to_be_visible()
    expect(cards).not_to_be_visible()
    expect(page.locator("#preview")).to_contain_text("Updated")
    expect(page.locator("#btn-add")).to_be_enabled()
    assert _run(live_app, lambda col: col.get_note(nid)["Front"]) == "Saved"

    page.locator("#btn-add").click()
    expect(cards).to_be_visible()
    expect(cards).to_be_focused()
    expect(cards.locator(f"button[data-note-id='{nid}']")).to_contain_text("Updated")
    assert [note[0] for note in live_app.notes()] == [nid]


def test_invalid_edit_stays_in_editor_until_corrected(
    page: Page, live_app: LiveApp
) -> None:
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/app/edit/1/front")
    _add(page, "First", "one")
    _add(page, "Second", "two")
    first = live_app.notes()[0][0]
    cards = page.locator("#deck-cards")
    page.locator("#pile").click()
    cards.locator(f"button[data-note-id='{first}']").click()
    expect(_front(page)).to_have_value("First")
    _front(page).fill("Second")
    _front(page).press("Enter")
    _wait_for_back(page)
    _back(page).press("Enter")
    page.locator("#btn-add").click()
    expect(page.locator("#edit-error")).to_be_visible()
    expect(cards).not_to_be_visible()
    expect(page.locator("#preview")).to_contain_text("Second")
    expect(page.locator("#btn-add")).to_be_enabled()
    assert live_app.notes()[0][1][0] == "First"

    previous = page.get_by_role("button", name="Previous Step")
    previous.click()
    expect(_back(page)).to_be_visible()
    previous.click()
    _front(page).fill("Corrected")
    _front(page).press("Enter")
    _wait_for_back(page)
    _back(page).press("Enter")
    page.locator("#btn-add").click()
    expect(cards).to_be_visible()
    expect(cards).to_be_focused()
    expect(cards.locator(f"button[data-note-id='{first}']")).to_contain_text(
        "Corrected"
    )


def test_back_does_not_leave_existing_card_while_saving(
    page: Page, live_app: LiveApp
) -> None:
    nid = _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Saved", "answer"))
    page.emulate_media(reduced_motion="reduce")
    url = f"{live_app}/app/edit/1/front"
    page.goto(url)
    page.locator("#pile").click()
    cards = page.locator("#deck-cards")
    cards.locator(f"button[data-note-id='{nid}']").click()
    expect(_front(page)).to_have_value("Saved")
    _front(page).fill("Updated")
    _front(page).press("Enter")
    _wait_for_back(page)
    _back(page).press("Enter")

    pending: list[Route] = []

    def hold_commit(route: Route) -> None:
        pending.append(route)

    unexpected: list[str] = []

    def dismiss_unexpected(dialog: Dialog) -> None:
        unexpected.append(dialog.message)
        dialog.dismiss()

    page.on("dialog", dismiss_unexpected)
    page.route("**/app/edit/1/*/*/commit", hold_commit)
    with page.expect_request("**/app/edit/1/*/*/commit"):
        page.locator("#btn-add").click()
    back = page.locator("#edit-back")
    expect(back).to_have_attribute("aria-disabled", "true")
    expect(back).to_have_role("button")
    expect(back).not_to_have_attribute("href", re.compile("."))
    expect(page.locator("#edit-session")).to_have_attribute("inert", "")
    back.evaluate("el => el.click()")
    page.keyboard.press("Enter")
    expect(page).to_have_url(f"{url.removesuffix('/front')}/cards/{nid}/preview")
    page.keyboard.press("Space")
    expect(page).to_have_url(f"{url.removesuffix('/front')}/cards/{nid}/preview")
    page.evaluate(
        "() => { window.historyPops = []; window.addEventListener('popstate', () => window.historyPops.push(location.href)); }"
    )
    page.go_back()
    page.wait_for_function("() => window.historyPops.length >= 2")
    expect(page).to_have_url(f"{url.removesuffix('/front')}/cards/{nid}/preview")
    expect(cards).not_to_be_visible()
    expect(page.locator("#preview")).to_contain_text("Updated")
    expect(page.locator("#btn-add")).to_be_disabled()
    assert unexpected == []
    assert _run(live_app, lambda col: col.get_note(nid)["Front"]) == "Saved"
    assert len(pending) == 1
    with page.expect_request("**/app/edit/1/*/*/commit"):
        pending[0].abort()
    expect(cards).not_to_be_visible()
    expect(page.locator("#preview")).to_contain_text("Updated")
    expect(page.locator("#btn-add")).to_be_disabled()
    assert _run(live_app, lambda col: col.get_note(nid)["Front"]) == "Saved"
    assert len(pending) == 2
    pending[1].continue_()
    expect(cards).to_be_visible()
    expect(cards).to_be_focused()
    expect(cards.locator(f"button[data-note-id='{nid}']")).to_contain_text("Updated")
    assert _run(live_app, lambda col: col.get_note(nid)["Front"]) == "Updated"
    expect(page).to_have_url(f"{url.removesuffix('/front')}/cards")
    page.go_back()
    expect(page).to_have_url(url)
    expect(_front(page)).to_have_value("")


@pytest.mark.parametrize(
    ("live_app", "marker", "warning", "notice"),
    [
        (
            "",
            "Learned",
            "Changes to this learned card will reset its learning progress.",
            "Learning progress was reset.",
        ),
        (
            "de_DE",
            "Gelernt",
            "Änderungen an dieser gelernten Karte setzen den Lernfortschritt zurück.",
            "Der Lernfortschritt wurde zurückgesetzt.",
        ),
    ],
    indirect=["live_app"],
)
@pytest.mark.parametrize("card_type", [1, 2])
def test_learned_edit_warns_and_only_changed_save_resets_progress(
    page: Page,
    live_app: LiveApp,
    marker: str,
    warning: str,
    notice: str,
    card_type: int,
) -> None:
    def seed(col: Collection) -> NoteId:
        nid = add_vocab_note(col, DeckId(1), "Reviewed", "answer")
        card = col.get_note(nid).cards()[0]
        card.type = CardType(card_type)
        card.queue = CardQueue(card_type)
        card.due = int(time.time()) + 600 if card_type == 1 else col.sched.today + 7
        card.ivl = 21
        card.factor = 2500
        card.reps = 8
        card.lapses = 2
        col.update_card(card)
        return nid

    nid = _run(live_app, seed)
    before = _progress(live_app, nid)
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/app/edit/1/front")
    opener = page.locator("#pile")
    cards = page.locator("#deck-cards")
    opener.click()
    row = cards.locator(f"button[data-note-id='{nid}']")
    expect(row).to_contain_text(marker)
    row.click()
    front = page.locator("#input-front")
    expect(front).to_have_value("Reviewed")
    expect(front).to_be_focused()
    expect(page.locator("#edit-warning")).to_have_text(warning)
    expect(page.locator("#edit-warning")).to_be_visible()

    front.press("Enter")
    _wait_for_back(page)
    expect(page.locator("#input-back")).to_have_value("answer")
    page.locator("#input-back").press("Enter")
    page.locator("#btn-add").click()
    expect(cards).to_be_visible()
    expect(cards).to_be_focused()
    expect(row).to_contain_text("Reviewed")
    expect(page.locator("#deck-progress-reset-notice")).not_to_be_visible()
    expect(cards).not_to_have_accessible_description(re.compile(re.escape(notice)))
    assert _progress(live_app, nid) == before

    expect(row).to_contain_text(marker)
    row.click()
    expect(front).to_have_value("Reviewed")
    front.fill("Cancelled reviewed")
    accepted = _respond_to_confirm(page, accept=True)
    page.locator("#edit-back").click()
    assert len(accepted) == 1
    expect(cards).to_be_visible()
    expect(page).to_have_url(f"{live_app}/app/edit/1/cards")
    assert _progress(live_app, nid) == before
    assert _run(live_app, lambda col: col.get_note(nid)["Front"]) == "Reviewed"

    expect(row).to_contain_text(marker)
    row.click()
    expect(front).to_have_value("Reviewed")
    expect(page.locator("#edit-warning")).to_have_text(warning)
    front.fill("Edited reviewed")
    front.press("Enter")
    _wait_for_back(page)
    page.locator("#input-back").press("Enter")
    page.locator("#btn-add").click()
    expect(cards).to_be_visible()
    expect(cards).to_be_focused()
    status = page.locator("#deck-progress-reset-notice")
    expect(status).to_have_role("status")
    expect(status).to_have_text(notice)
    expect(status).to_be_visible()
    expect(cards).to_have_accessible_description(re.compile(re.escape(notice)))
    after = _progress(live_app, nid)
    assert after[0] == 0
    assert after[5:] == (0, 0)
    assert _run(live_app, lambda col: col.get_note(nid)["Front"]) == "Edited reviewed"
    assert _run(live_app, lambda col: len(col.find_notes(""))) == 1
    expect(page.locator("#added-cards .add-stack-count")).to_have_text("1")
    expect(row).to_contain_text("Edited reviewed")
    expect(row).not_to_contain_text(marker)

    row.click()
    expect(front).to_have_value("Edited reviewed")
    front.press("Enter")
    _wait_for_back(page)
    page.locator("#input-back").press("Enter")
    page.locator("#btn-add").click()
    expect(cards).to_be_visible()
    expect(cards).to_be_focused()
    expect(status).not_to_be_visible()
    expect(cards).not_to_have_accessible_description(re.compile(re.escape(notice)))


def _seed_reviewed_note(col: Collection) -> NoteId:
    nid = add_vocab_note(col, DeckId(1), "Reviewed", "answer")
    card = col.get_note(nid).cards()[0]
    card.type = CardType(2)
    card.queue = CardQueue(2)
    card.due = col.sched.today + 7
    card.ivl = 21
    card.factor = 2500
    card.reps = 8
    card.lapses = 2
    col.update_card(card)
    return nid


def test_front_description_tracks_learned_selection_history_and_reset(
    page: Page, live_app: LiveApp
) -> None:
    learned = _run(live_app, _seed_reviewed_note)
    unlearned = _run(
        live_app, lambda col: add_vocab_note(col, DeckId(1), "New card", "answer")
    )
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    cards_url = f"{editor_url.removesuffix('/front')}/cards"
    help_text = "What will you test?"
    warning = "Changes to this learned card will reset its learning progress."
    front = page.locator("#input-front")
    cards = page.locator("#deck-cards")
    pile = page.locator("#pile")

    page.goto(editor_url)
    expect(front).to_have_accessible_description(help_text)
    expect(page.locator("#edit-warning")).not_to_be_visible()
    pile.click()
    expect(cards).to_be_visible()
    cards.locator(f"button[data-note-id='{learned}']").click()
    expect(front).to_have_value("Reviewed")
    expect(front).to_be_focused()
    expect(front).to_have_accessible_description(f"{help_text} {warning}")
    expect(page.get_by_role("note")).to_have_text(warning)

    page.go_back()
    expect(page).to_have_url(cards_url)
    expect(cards).to_be_focused()
    page.go_forward()
    expect(front).to_have_value("Reviewed")
    expect(front).to_be_focused()
    expect(front).to_have_accessible_description(f"{help_text} {warning}")

    page.go_back()
    expect(cards).to_be_visible()
    cards.locator(f"button[data-note-id='{unlearned}']").click()
    expect(front).to_have_value("New card")
    expect(front).to_be_focused()
    expect(front).to_have_accessible_description(help_text)
    expect(page.locator("#edit-warning")).not_to_be_visible()

    page.locator("#edit-back").click()
    expect(cards).to_be_visible()
    page.locator("#edit-back").click()
    expect(page).to_have_url(editor_url)
    expect(pile).to_be_focused()
    expect(front).to_have_value("")
    expect(front).to_have_accessible_description(help_text)

    pile.click()
    cards.locator(f"button[data-note-id='{learned}']").click()
    expect(front).to_have_accessible_description(f"{help_text} {warning}")
    front.fill("Edited reviewed")
    front.press("Enter")
    _wait_for_back(page)
    page.locator("#input-back").press("Enter")
    page.locator("#btn-add").click()
    expect(cards).to_be_visible()
    row = cards.locator(f"button[data-note-id='{learned}']")
    expect(row).to_contain_text("Edited reviewed")
    row.click()
    expect(front).to_have_value("Edited reviewed")
    expect(front).to_be_focused()
    expect(front).to_have_accessible_description(help_text)
    expect(page.locator("#edit-warning")).not_to_be_visible()


@pytest.mark.parametrize(
    ("live_app", "help_text", "warning"),
    [
        (
            "",
            "What will you test?",
            "Changes to this learned card will reset its learning progress.",
        ),
        (
            "de_DE",
            "Was möchtest du abfragen?",
            "Änderungen an dieser gelernten Karte setzen den Lernfortschritt zurück.",
        ),
    ],
    indirect=["live_app"],
)
def test_direct_learned_card_front_description_survives_reload(
    page: Page, live_app: LiveApp, help_text: str, warning: str
) -> None:
    nid = _run(live_app, _seed_reviewed_note)
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/app/edit/1/cards/{nid}/front")
    front = page.locator("#input-front")
    for reload_page in (False, True):
        if reload_page:
            page.reload()
        expect(front).to_have_value("Reviewed")
        expect(front).to_have_accessible_description(f"{help_text} {warning}")
        expect(page.get_by_role("note")).to_have_text(warning)
        front.focus()
        expect(front).to_be_focused()


@pytest.mark.parametrize("retry_mode", ["same_session", "reopen"])
@pytest.mark.parametrize(
    ("live_app", "failure", "warning", "notice"),
    [
        (
            "",
            (
                "The note text was saved, but learning progress was not reset. "
                "Please try saving again."
            ),
            "Changes to this learned card will reset its learning progress.",
            "Learning progress was reset.",
        ),
        (
            "de_DE",
            (
                "Der Kartentext wurde gespeichert, aber der Lernfortschritt wurde "
                "nicht zurückgesetzt. Bitte erneut speichern."
            ),
            "Änderungen an dieser gelernten Karte setzen den Lernfortschritt zurück.",
            "Der Lernfortschritt wurde zurückgesetzt.",
        ),
    ],
    indirect=["live_app"],
)
def test_learned_edit_partial_save_can_retry_progress_reset(
    page: Page,
    live_app: LiveApp,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    warning: str,
    notice: str,
    retry_mode: str,
) -> None:
    nid = _run(live_app, _seed_reviewed_note)
    cid = _run(live_app, lambda col: col.get_note(nid).cards()[0].id)
    before = _progress(live_app, nid)
    scheduler_class = _run(live_app, lambda col: type(col.sched))
    original_reset = scheduler_class.schedule_cards_as_new
    calls: list[tuple[list[CardId], bool]] = []

    def fail_once(
        scheduler: Scheduler, card_ids: list[CardId], *, reset_counts: bool
    ) -> None:
        calls.append((card_ids, reset_counts))
        if len(calls) == 1:
            raise RuntimeError("deterministic scheduler failure")
        original_reset(scheduler, card_ids, reset_counts=reset_counts)

    monkeypatch.setattr(scheduler_class, "schedule_cards_as_new", fail_once)
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/app/edit/1/front")
    page.locator("#pile").click()
    page.locator(f"#deck-cards button[data-note-id='{nid}']").click()
    front = page.locator("#input-front")
    expect(front).to_have_value("Reviewed")
    expect(page.locator("#edit-warning")).to_have_text(warning)
    front.fill("Edited reviewed")
    front.press("Enter")
    _wait_for_back(page)
    page.locator("#input-back").press("Enter")
    page.locator("#btn-add").click()

    expect(page.locator("#edit-error")).to_be_visible()
    expect(page.locator("#edit-error")).to_have_text(failure)
    expect(page.locator("#edit-back")).to_be_visible()
    expect(page.locator("#edit-warning")).to_be_visible()
    expect(page.locator("#edit-warning")).to_have_text(warning)
    expect(front).to_have_value("Edited reviewed")
    expect(page.locator("#preview")).to_contain_text("Edited reviewed")
    expect(page.locator("#deck-cards")).not_to_be_visible()
    expect(page.locator("#progress-reset-notice")).not_to_be_visible()
    assert _run(live_app, lambda col: col.get_note(nid)["Front"]) == "Edited reviewed"
    assert _progress(live_app, nid) == before
    assert calls == [([cid], True)]

    if retry_mode == "reopen":
        accepted = _respond_to_confirm(page, accept=True)
        page.locator("#edit-back").click()
        assert len(accepted) == 1
        expect(page.locator("#deck-cards")).to_be_visible()
        assert calls == [([cid], True)]
        assert _progress(live_app, nid) == before
        assert (
            _run(live_app, lambda col: col.get_note(nid)["Front"]) == "Edited reviewed"
        )

        page.context.clear_cookies()
        assert page.context.cookies() == []
        page.goto(f"{live_app}/app/edit/1/front")
        page.locator("#pile").click()
        page.locator(f"#deck-cards button[data-note-id='{nid}']").click()
        expect(front).to_have_value("Edited reviewed")
        expect(page.locator("#edit-warning")).to_be_visible()
        expect(page.locator("#edit-warning")).to_have_text(warning)
        front.press("Enter")
        _wait_for_back(page)
        expect(page.locator("#input-back")).to_have_value("answer")
        page.locator("#input-back").press("Enter")

    with page.expect_request(
        lambda request: (
            request.method == "POST" and urlsplit(request.url).path.endswith("/commit")
        )
    ) as retry:
        page.locator("#btn-add").click()
    retry_payload = parse_qs(retry.value.post_data or "")
    assert retry_payload["nid"] == [str(nid)]
    assert retry_payload["front"] == ["Edited reviewed"]
    cards = page.locator("#deck-cards")
    expect(cards).to_be_visible()
    expect(cards).to_be_focused()
    expect(cards.locator(f"button[data-note-id='{nid}']")).to_contain_text(
        "Edited reviewed"
    )
    status = page.locator("#deck-progress-reset-notice")
    expect(status).to_have_role("status")
    expect(status).to_have_text(notice)
    expect(status).to_be_visible()
    expect(cards).to_have_accessible_description(re.compile(re.escape(notice)))
    expect(front).to_have_value("")
    assert calls == [([cid], True), ([cid], True)]
    after = _progress(live_app, nid)
    assert after[0] == 0
    assert after[5:] == (0, 0)
    assert _run(live_app, lambda col: col.get_note(nid)["Front"]) == "Edited reviewed"
    assert _run(live_app, lambda col: len(col.find_notes(""))) == 1


@pytest.mark.parametrize(
    ("live_app", "unit", "done", "summary_label"),
    [
        ("", "cards", "Done", "Cards added"),
        ("de_DE", "Karten", "Fertig", "Hinzugefügte Karten"),
    ],
    indirect=["live_app"],
)
def test_deck_badge_and_session_summary_count_different_cards(
    page: Page, live_app: LiveApp, unit: str, done: str, summary_label: str
) -> None:
    _run(
        live_app,
        lambda col: [
            add_vocab_note(col, DeckId(1), f"Previous {i}", f"Answer {i}")
            for i in range(2)
        ],
    )
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/app/edit/1/front")
    region = page.locator("#added-cards")
    badge = region.locator(".add-stack-badge")
    count = badge.locator(".add-stack-count")
    pile = page.locator("#pile")
    expect(count).to_have_text("2")
    expect(badge.locator(".add-stack-unit")).to_have_text(unit)
    expect(badge).to_have_attribute("aria-hidden", "true")
    expect(pile).to_have_accessible_name(re.compile(r"^2 "))

    for index in range(1, 4):
        front = f"Question {index}"
        page.locator("#input-front").fill(front)
        page.locator("#input-front").press("Enter")
        _wait_for_back(page)
        page.locator("#input-back").fill(f"Answer {index}")
        page.locator("#input-back").press("Enter")
        expect(page.locator("#preview")).to_contain_text(front)
        page.locator("#btn-add").click()
        expect(region).to_contain_text(front)
        expect(count).to_have_text(str(index + 2))
        expect(pile).to_have_accessible_name(re.compile(rf"^{index + 2} "))
        expect(page.locator("#input-front")).to_have_value("")

    expect(region.locator(".stacked-card")).to_have_count(5)
    saved = live_app.notes()
    assert len(saved) == 5
    page.get_by_role("button", name=done, exact=True).click()
    summary = page.get_by_role("dialog")
    expect(summary).to_be_visible()
    expect(summary).to_contain_text(summary_label)
    expect(summary.locator("p span")).to_have_text("3")
    page.reload()
    expect(count).to_have_text("5")
    expect(pile).to_have_accessible_name(re.compile(r"^5 "))
    expect(region.locator(".stacked-card")).to_have_count(5)
    assert live_app.notes() == saved


def test_double_click_add_saves_only_one_note(page: Page, live_app: LiveApp) -> None:
    page.goto(f"{live_app}/app/edit/1/front")
    _to_preview(page, "Double click", "one note")
    page.get_by_role("button", name="Add", exact=True).dblclick()
    expect(_front(page)).to_be_visible()
    expect(page.locator("#added-cards .add-stack-count")).to_have_text("1")
    saved = live_app.notes()
    assert len(saved) == 1
    assert saved[0][1][:2] == ["Double click", "one note"]
    page.reload()
    assert live_app.notes() == saved


def test_five_card_floor_stack_is_opaque_stepped_and_does_not_overflow(
    page: Page, live_app: LiveApp
) -> None:
    ids = _run(
        live_app,
        lambda col: [
            add_vocab_note(col, DeckId(1), f"Floor {i}", f"Answer {i}")
            for i in range(6)
        ],
    )
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/app/edit/1/front")
    region = page.locator("#added-cards")
    cards = region.locator(".stacked-card")
    expect(cards).to_have_count(5)
    assert cards.evaluate_all(
        "els => els.map(el => Number(el.dataset.noteId))"
    ) == list(reversed(ids[-5:]))
    geometry = cards.evaluate_all(
        """els => els.map(el => {
          const box = el.getBoundingClientRect();
          const style = getComputedStyle(el);
          const canvas = document.createElement('canvas');
          canvas.width = canvas.height = 1;
          const ctx = canvas.getContext('2d');
          ctx.fillStyle = style.backgroundColor;
          ctx.fillRect(0, 0, 1, 1);
          return {
            left: box.left, right: box.right, top: box.top, bottom: box.bottom,
            width: box.width, height: box.height,
            opacity: Number(style.opacity),
            alpha: ctx.getImageData(0, 0, 1, 1).data[3],
            z: Number(style.zIndex),
          };
        })"""
    )
    assert all(card["opacity"] == 1 and card["alpha"] == 255 for card in geometry)
    assert all(geometry[i]["z"] > geometry[i + 1]["z"] for i in range(4))
    for front, behind in pairwise(geometry):
        assert behind["top"] < front["top"] < behind["bottom"]
        assert behind["left"] < front["right"] and front["left"] < behind["right"]

    stack_left = min(card["left"] for card in geometry)
    stack_right = max(card["right"] for card in geometry)
    stack_top = min(card["top"] for card in geometry)
    stack_bottom = max(card["bottom"] for card in geometry)
    assert all(card["width"] > 0 and card["height"] > 0 for card in geometry)

    pile_box = page.locator("#pile").bounding_box()
    badge = region.locator(".add-stack-badge")
    expect(badge).to_be_visible()
    expect(badge.locator(".add-stack-count")).to_have_text("6")
    badge_box = badge.bounding_box()
    editor_box = page.locator("#add-editor").bounding_box()
    cue_box = region.locator(".pile-cue").bounding_box()
    assert pile_box is not None and badge_box is not None and editor_box is not None
    assert cue_box is not None
    badge_center_x = badge_box["x"] + badge_box["width"] / 2
    badge_center_y = badge_box["y"] + badge_box["height"] / 2
    assert (stack_left + stack_right) / 2 < badge_center_x < stack_right
    assert badge_center_y < (stack_top + stack_bottom) / 2
    assert badge_box["y"] + badge_box["height"] > stack_top
    assert (
        badge_box["x"] + badge_box["width"] <= editor_box["x"]
        or editor_box["x"] + editor_box["width"] <= badge_box["x"]
        or badge_box["y"] + badge_box["height"] <= editor_box["y"]
        or editor_box["y"] + editor_box["height"] <= badge_box["y"]
    )
    assert cue_box["y"] > pile_box["y"] + pile_box["height"] / 2
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def test_required_fields_block_wizard_advancement(
    page: Page, live_app: LiveApp
) -> None:
    page.goto(f"{live_app}/app/edit/1/front")
    page.get_by_role("button", name=re.compile(r"Next: Back")).click()
    expect(page.locator("#edit-error")).to_contain_text("Front cannot be empty")
    expect(_front(page)).to_be_visible()
    _front(page).fill("Question")
    expect(page.locator("#edit-error")).to_be_hidden()
    expect(page.locator("#edit-error")).to_be_empty()
    _front(page).press("Enter")
    _wait_for_back(page)
    _back(page).press("Enter")
    expect(page.locator("#edit-error")).to_contain_text("Back cannot be empty")
    expect(_back(page)).to_be_visible()


def test_new_editor_request_clears_previous_error_while_pending(
    page: Page, live_app: LiveApp
) -> None:
    page.goto(f"{live_app}/app/edit/1/front")
    next_button = page.locator("#btn-next")
    alert = page.locator("#edit-error")
    next_button.click()
    expect(alert).to_contain_text("Front cannot be empty")

    pending: list[Route] = []
    url = "**/app/edit/1/*/*/step/back/next"
    page.route(url, lambda route: pending.append(route))  # noqa: PLW0108
    with page.expect_request(url):
        next_button.click()
    expect(alert).to_be_hidden()
    expect(alert).to_be_empty()
    assert len(pending) == 1
    pending[0].continue_()
    expect(alert).to_contain_text("Front cannot be empty")


def test_validation_toast_and_optional_fields_keep_add_styles(
    page: Page, live_app: LiveApp
) -> None:
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/app/edit/1/front")
    page.get_by_role("button", name=re.compile(r"Next: Back")).click()
    alert = page.get_by_role("alert")
    expect(alert).to_contain_text("Front cannot be empty")
    expect(alert).to_be_visible()
    message = alert.locator(".alert")
    expect(message).to_have_css("border-top-width", "3px")
    expect(message).to_have_css("border-top-style", "solid")
    expect(message).to_have_css("border-top-left-radius", "16px")
    expect(message).to_have_css("text-align", "center")
    expect(message).to_have_css("font-weight", "900")
    expect(message).to_have_css("animation-name", "none")
    expect(page.locator("#edit-error")).to_have_css("z-index", "50")
    toast_box = message.bounding_box()
    footer_box = page.locator("#add-wizard footer").bounding_box()
    assert toast_box is not None and footer_box is not None
    assert toast_box["y"] + toast_box["height"] <= footer_box["y"]

    _front(page).fill("Question")
    _front(page).press("Enter")
    _wait_for_back(page)
    editor_style = page.locator("#add-editor").evaluate(
        """el => ({
            background: getComputedStyle(el).backgroundColor,
            border: getComputedStyle(el).borderTopColor
        })"""
    )
    for label, field in (
        ("Hint · Optional", "Hint"),
        ("Example sentence · Optional", "Example sentence"),
    ):
        summary = page.get_by_text(label, exact=True)
        details = summary.locator("..")
        expect(details).to_have_css("margin-top", "10px")
        expect(details).to_have_css("border-top-style", "solid")
        assert (
            details.evaluate("el => parseFloat(getComputedStyle(el).borderTopWidth)")
            > 0
        )
        expect(details).to_have_css("border-top-color", editor_style["border"])
        expect(details).to_have_css("background-color", editor_style["background"])
        expect(details).to_have_css("border-top-left-radius", "10px")
        expect(page.get_by_label(field, exact=True)).not_to_be_visible()
        summary.click()
        expect(page.get_by_label(field, exact=True)).to_be_visible()


def test_duplicate_preserves_preview_and_saved_note(
    page: Page, live_app: LiveApp
) -> None:
    page.goto(f"{live_app}/app/edit/1/front")
    _add(page)
    saved = live_app.notes()
    _to_preview(page, "Hund", "different answer")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(page.locator("#edit-error")).to_contain_text(
        "A card with this front already exists."
    )
    expect(page.locator("#preview")).to_contain_text("different answer")
    assert live_app.notes() == saved


def test_finish_clean_empty_session_opens_summary(
    page: Page, live_app: LiveApp
) -> None:
    page.goto(f"{live_app}/app/edit/1/front")
    page.get_by_role("button", name="Done", exact=True).click()
    expect(page).to_have_url(f"{live_app}/app/edit/1/front")
    summary = page.get_by_role("dialog")
    expect(summary).to_be_visible()
    expect(summary).to_have_attribute("open", "")
    assert summary.evaluate("el => el.matches(':modal')")
    expect(summary.locator("#summary-count")).to_have_text("0")
    page.keyboard.press("Escape")
    expect(summary).not_to_be_visible()
    expect(page.locator("#edit-done")).to_be_focused()
    assert live_app.notes() == []


def test_finish_from_clean_card_list_without_session_additions_opens_summary(
    page: Page, live_app: LiveApp
) -> None:
    _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Existing", "answer"))
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/app/edit/1/front")
    page.locator("#pile").click()
    expect(page.locator("#deck-cards")).to_be_visible()
    page.get_by_role("button", name="Done", exact=True).click()
    expect(page).to_have_url(f"{live_app}/app/edit/1/cards")
    summary = page.get_by_role("dialog")
    expect(summary).to_be_visible()
    expect(summary.locator("#summary-count")).to_have_text("0")
    assert len(live_app.notes()) == 1

    cards = page.locator("#deck-cards")
    cards_url = f"{live_app}/app/edit/1/cards"
    page.keyboard.down("Escape")
    expect(summary).not_to_be_visible()
    expect(cards).to_be_visible()
    expect(page).to_have_url(cards_url)

    page.keyboard.down("Escape")
    page.keyboard.up("Escape")
    expect(summary).not_to_be_visible()
    expect(cards).to_be_visible()
    expect(page).to_have_url(cards_url)

    page.keyboard.press("Escape")
    expect(cards).not_to_be_visible()
    expect(page).to_have_url(f"{live_app}/app/edit/1/front")


@pytest.mark.parametrize("session_added", [False, True])
def test_finish_from_card_list_guards_draft_and_preserves_focus(
    page: Page, live_app: LiveApp, session_added: bool
) -> None:
    _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Existing", "answer"))
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    cards_url = f"{editor_url.removesuffix('/front')}/cards"
    page.goto(editor_url)
    if session_added:
        _add(page, "Session addition", "answer")
    saved = live_app.notes()
    _front(page).fill("unfinished draft")
    accepted = _respond_to_confirm(page, accept=True)
    page.locator("#pile").click()
    assert len(accepted) == 1
    cards = page.locator("#deck-cards")
    done = page.get_by_role("button", name="Done", exact=True)
    summary = page.locator("#add-summary")
    expect(cards).to_be_visible()
    expect(done).to_be_visible()
    expect(done).to_be_enabled()
    expect(page).to_have_url(cards_url)

    cancelled = _respond_to_confirm(page, accept=False)
    done.click()
    assert len(cancelled) == 1
    expect(page).to_have_url(cards_url)
    expect(cards).to_be_visible()
    expect(_front(page)).to_have_value("unfinished draft")
    expect(summary).not_to_be_visible()

    accepted = _respond_to_confirm(page, accept=True)
    done.click()
    assert len(accepted) == 1

    expect(page).to_have_url(cards_url)
    expect(cards).to_be_visible()
    expect(summary).to_be_visible()
    expect(summary.locator("#summary-count")).to_have_text(
        "1" if session_added else "0"
    )
    expect(summary.get_by_role("button", name="Close", exact=True)).to_have_count(0)
    decks = summary.get_by_role("link", name="Back to decks", exact=True)
    study = summary.get_by_role("link", name="Start studying", exact=True)
    expect(decks).to_be_focused()
    summary.focus()
    page.keyboard.press("Tab")
    expect(decks).to_be_focused()
    summary.focus()
    page.keyboard.press("Shift+Tab")
    expect(study).to_be_focused()
    page.keyboard.press("Escape")
    expect(summary).not_to_be_visible()
    expect(cards).to_be_visible()
    expect(page).to_have_url(cards_url)
    expect(done).to_be_focused()

    done.click()
    expect(summary).to_be_visible()
    summary.locator(".modal-backdrop").click(position={"x": 5, "y": 5})
    expect(summary).not_to_be_visible()
    expect(cards).to_be_visible()
    expect(done).to_be_focused()
    done.click()
    expect(summary).to_be_visible()
    page.go_back()
    expect(summary).not_to_be_visible()
    expect(page).to_have_url(editor_url)
    expect(cards).not_to_be_visible()
    expect(page.locator("#pile")).to_be_focused()
    assert live_app.notes() == saved


def test_finish_empty_session_confirms_unsaved_draft(
    page: Page, live_app: LiveApp
) -> None:
    page.goto(f"{live_app}/app/edit/1/front")
    _front(page).fill("unfinished card")
    done = page.get_by_role("button", name="Done", exact=True)
    cancelled = _respond_to_confirm(page, accept=False)
    done.click()
    assert len(cancelled) == 1
    expect(_front(page)).to_have_value("unfinished card")
    expect(page.get_by_role("dialog")).not_to_be_visible()

    accepted = _respond_to_confirm(page, accept=True)
    done.click()
    assert len(accepted) == 1
    expect(page).to_have_url(f"{live_app}/app/edit/1/front")
    summary = page.get_by_role("dialog")
    expect(summary).to_be_visible()
    expect(summary.locator("#summary-count")).to_have_text("0")
    page.keyboard.press("Escape")
    expect(summary).not_to_be_visible()
    expect(_front(page)).to_have_value("")
    expect(done).to_be_focused()
    assert live_app.notes() == []


def test_finish_guard_dialog_and_study_link(page: Page, live_app: LiveApp) -> None:
    page.goto(f"{live_app}/app/edit/1/front")
    done = page.get_by_role("button", name="Done", exact=True)
    _add(page)
    saved = live_app.notes()
    _front(page).fill("unfinished card")

    cancelled = _respond_to_confirm(page, accept=False)
    done.click()
    assert len(cancelled) == 1
    expect(_front(page)).to_have_value("unfinished card")
    expect(page.get_by_role("dialog")).not_to_be_visible()
    accepted = _respond_to_confirm(page, accept=True)
    done.click()
    assert len(accepted) == 1
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    expect(dialog).to_have_attribute("aria-modal", "true")
    expect(dialog).to_contain_text("1")
    decks = dialog.get_by_role("link", name="Back to decks", exact=True)
    expect(decks).to_have_attribute("href", "/app/")
    study = dialog.get_by_role("link", name="Start studying", exact=True)
    expect(study).to_have_attribute("href", "/app/review?deck=1")
    expect(dialog.get_by_role("button", name="Close", exact=True)).to_have_count(0)
    expect(decks).to_be_focused()
    page.keyboard.press("Shift+Tab")
    expect(study).to_be_focused()
    page.keyboard.press("Tab")
    expect(decks).to_be_focused()
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()
    expect(page).to_have_url(f"{live_app}/app/edit/1/front")
    expect(_front(page)).to_be_visible()
    expect(done).to_be_focused()
    assert live_app.notes() == saved

    done.click()
    expect(dialog).to_be_visible()
    study.focus()
    page.keyboard.press("Tab")
    assert dialog.evaluate("el => el.contains(document.activeElement)")
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()

    done.click()
    expect(dialog).to_be_visible()
    dialog.locator(".modal-backdrop").click(position={"x": 5, "y": 5})
    expect(dialog).not_to_be_visible()
    expect(done).to_be_focused()
    assert live_app.notes() == saved
    done.click()
    expect(dialog).to_be_visible()
    # Plan 3's review page is not required for testing the navigation target.
    page.route("**/app/review?deck=1", lambda route: route.fulfill(body="Review"))
    study.click()
    expect(page).to_have_url(f"{live_app}/app/review?deck=1")
    assert live_app.notes() == saved

    page.goto(f"{live_app}/app/edit/1/front")
    done.click()
    expect(dialog).to_be_visible()
    decks.click()
    expect(page).to_have_url(f"{live_app}/app/")
    assert live_app.notes() == saved


@pytest.mark.parametrize("link_name", ["Exit Creator", "🗂️ Default"])
def test_exit_and_deck_links_guard_unsaved_text(
    page: Page, live_app: LiveApp, link_name: str
) -> None:
    url = f"{live_app}/app/edit/1/front"
    page.goto(url)
    _front(page).fill("unsaved")
    link = page.locator("#add-wizard header").get_by_role(
        "button" if link_name == "Exit Creator" else "link",
        name=link_name,
        exact=True,
    )
    if link_name == "Exit Creator":
        expect(link).not_to_have_attribute("href", re.compile("."))
    else:
        expect(link).to_have_attribute("href", "/app/")
    cancelled = _respond_to_confirm(page, accept=False)
    link.click()
    assert len(cancelled) == 1
    expect(page).to_have_url(url)
    expect(_front(page)).to_have_value("unsaved")
    accepted = _respond_to_confirm(page, accept=True)
    link.click()
    assert len(accepted) == 1
    expect(page).to_have_url(f"{live_app}/app/")


@pytest.mark.parametrize("link_name", ["Exit Creator", "🗂️ Default"])
def test_clean_exit_and_deck_links_navigate_without_confirmation(
    page: Page, live_app: LiveApp, link_name: str
) -> None:
    page.goto(f"{live_app}/app/edit/1/front")
    link = page.locator("#add-wizard header").get_by_role(
        "link", name=link_name, exact=True
    )
    expect(link).to_have_attribute("href", "/app/")
    link.click()
    expect(page).to_have_url(f"{live_app}/app/")


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_mobile_layout_and_browser_errors(
    page: Page, live_app: LiveApp, scheme: Literal["light", "dark"]
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def record_console(message: ConsoleMessage) -> None:
        if message.type == "error":
            errors.append(message.text)

    page.on("console", record_console)
    page.emulate_media(color_scheme=scheme)
    page.goto(f"{live_app}/app/edit/1/front")
    _add(page)
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    assert page.screenshot().startswith(b"\x89PNG\r\n\x1a\n")
    assert errors == []


def _seed_language_deck(col: Collection, name: str, pair: LanguagePair) -> DeckId:
    deck_id = DeckId(col.decks.add_normal_deck_with_name(name).id)
    deck = col.decks.get(deck_id, default=False)
    assert deck is not None
    deck["desc"] = apply_marker(deck["desc"], pair)
    col.decks.update_dict(deck)
    return deck_id


def _browser_errors(page: Page) -> list[str]:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def record_console(message: ConsoleMessage) -> None:
        if message.type == "error":
            errors.append(message.text)

    page.on("console", record_console)
    return errors


def test_language_chips_edit_selection_and_save(page: Page, live_app: LiveApp) -> None:
    deck_id = _run(
        live_app,
        lambda col: _seed_language_deck(
            col, "Spanish German", LanguagePair("es", "de")
        ),
    )
    errors = _browser_errors(page)
    page.goto(f"{live_app}/app/edit/{deck_id}/front")
    front = page.locator("#input-front")
    chips = page.locator("#add-chips-front")
    counter = page.locator('[data-counter-for="front"]')
    expect(page.locator("label[for='input-front']")).to_have_text(
        "Front (Question / Prompt) · 🇩🇪 German"
    )
    expect(front).to_have_attribute("lang", "de")
    expect(chips).to_have_attribute("lang", "de")

    front.fill("Stra")
    front.press("ArrowLeft")
    front.press("ArrowLeft")
    chips.get_by_role("button", name="ß", exact=True).click()
    expect(front).to_have_value("Stßra")
    expect(front).to_be_focused()
    assert front.evaluate("el => [el.selectionStart, el.selectionEnd]") == [3, 3]
    expect(counter).to_have_text("5")

    front.press("Shift+ArrowLeft")
    front.press("Shift+ArrowLeft")
    chips.get_by_role("button", name="ä", exact=True).click()
    expect(front).to_have_value("Sära")
    expect(front).to_be_focused()
    assert front.evaluate("el => [el.selectionStart, el.selectionEnd]") == [2, 2]
    expect(counter).to_have_text("4")

    front.press("Home")
    chips.get_by_role("button", name="der", exact=True).click()
    expect(front).to_have_value("der Sära")
    expect(front).to_be_focused()
    assert front.evaluate("el => [el.selectionStart, el.selectionEnd]") == [4, 4]
    expect(counter).to_have_text("8")

    page.locator("#btn-next").click()
    back = page.locator("#input-back")
    expect(back).to_be_visible()
    expect(page.locator("label[for='input-back']")).to_have_text(
        "Back (Answer / Meaning) · 🇪🇸 Spanish"
    )
    expect(back).to_have_attribute("lang", "es")
    back.fill("answer")
    back.press("Enter")
    expect(page.locator("#preview")).to_contain_text("der Sära")
    page.locator("#btn-add").click()
    expect(front).to_have_value("")
    saved = live_app.persisted_notes()
    assert len(saved) == 1
    assert saved[0][1] == ["der Sära", "answer", "", ""]
    assert saved[0][2] == deck_id
    assert errors == []


def test_editor_without_language_pair_keeps_legacy_chips(
    page: Page, live_app: LiveApp
) -> None:
    errors = _browser_errors(page)
    page.goto(f"{live_app}/app/edit/1/front")
    expect(page.locator("label[for='input-front']")).to_have_text(
        "Front (Question / Prompt)"
    )
    front = page.locator("#input-front")
    expect(front).not_to_have_attribute("lang", re.compile(".+"))
    chips = page.locator(".add-chips").filter(
        has=page.locator("button[data-target='input-front']")
    )
    expect(chips.locator("button")).to_have_text(
        ["der", "die", "das", "ä", "ö", "ü", "ß"]
    )
    expect(page.locator("#add-chips-front")).to_have_count(0)
    front.fill("word")
    page.locator("#btn-next").click()
    expect(page.locator("label[for='input-back']")).to_have_text(
        "Back (Answer / Meaning)"
    )
    assert errors == []


def test_arabic_attached_chip_and_french_mobile_layout(
    page: Page, live_app: LiveApp
) -> None:
    arabic, french = _run(
        live_app,
        lambda col: (
            _seed_language_deck(col, "German Arabic", LanguagePair("de", "ar")),
            _seed_language_deck(col, "German French", LanguagePair("de", "fr")),
        ),
    )
    errors = _browser_errors(page)
    page.goto(f"{live_app}/app/edit/{arabic}/front")
    front = page.locator("#input-front")
    chips = page.locator("#add-chips-front")
    expect(chips).to_have_attribute("lang", "ar")
    front.fill("كتاب")
    front.press("Home")
    chips.get_by_role("button", name="ال", exact=True).click()
    expect(front).to_have_value("الكتاب")
    expect(front).to_be_focused()
    assert front.evaluate("el => [el.selectionStart, el.selectionEnd]") == [2, 2]

    front.fill("")
    page.goto(f"{live_app}/app/edit/{french}/front")
    french_chips = page.locator("#add-chips-front")
    expect(french_chips).to_have_attribute("lang", "fr")
    expect(french_chips.get_by_role("button", name="Ÿ", exact=True)).to_be_visible()
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    assert errors == []


def test_character_counts_use_utf16_for_loaded_and_edited_values(
    page: Page, live_app: LiveApp
) -> None:
    nid = _run(
        live_app,
        lambda col: add_vocab_note(col, DeckId(1), "😀a", "b😀", "😀", "😀😀"),
    )
    page.goto(f"{live_app}/app/edit/1/cards/{nid}/front")
    for field, count in (
        ("front", "3"),
        ("back", "3"),
        ("hint", "2"),
        ("example", "4"),
    ):
        expect(page.locator(f'[data-counter-for="{field}"]')).to_have_text(count)
    _front(page).fill("😀😀x")
    expect(page.locator('[data-counter-for="front"]')).to_have_text("5")
    _front(page).press("Enter")
    _wait_for_back(page)
    _back(page).fill("😀😀")
    expect(page.locator('[data-counter-for="back"]')).to_have_text("4")


def test_two_tabs_share_session_counts_but_not_drafts(
    page: Page, live_app: LiveApp
) -> None:
    url = f"{live_app}/app/edit/1/front"
    page.goto(url)
    other = page.context.new_page()
    other.goto(url)
    assert page.locator("#edit-session").get_attribute("data-instance") != (
        other.locator("#edit-session").get_attribute("data-instance")
    )
    _front(other).fill("Second tab")
    _add(page, "First tab", "first answer")
    expect(_front(other)).to_have_value("Second tab")
    _to_preview(other, "Second tab", "second answer")
    other.get_by_role("button", name="Add", exact=True).click()
    expect(_front(other)).to_have_value("")
    expect(other.locator("#added-cards .add-stack-count")).to_have_text("2")
    other.get_by_role("button", name="Done", exact=True).click()
    expect(other.locator("#summary-count")).to_have_text("2")
    page.reload()
    expect(page.locator("#added-cards .add-stack-count")).to_have_text("2")
    page.get_by_role("button", name="Done", exact=True).click()
    expect(page.locator("#summary-count")).to_have_text("2")
    assert len(live_app.notes()) == 2
    other.close()


@pytest.mark.parametrize("target_step", [2, 3])
def test_late_step_is_dropped_after_switching_cards(
    page: Page, live_app: LiveApp, target_step: int
) -> None:
    nid = _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Saved", "answer"))
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/app/edit/1/front")
    _front(page).fill("Draft")
    if target_step == 3:
        _front(page).press("Enter")
        _wait_for_back(page)
        expect(page.locator("#btn-next")).to_contain_text("Preview")
        _back(page).fill("draft answer")
    pending: list[tuple[Route, Any]] = []

    def hold_preview(route: Route) -> None:
        pending.append((route, route.fetch()))

    step_url = f"**/app/edit/1/*/*/step/{'back' if target_step == 2 else 'preview'}/*"
    page.route(step_url, hold_preview)
    page.evaluate(
        """() => {
          window.stepFinished = false;
          let started = false;
          document.addEventListener('datastar-fetch', event => {
            if (event.detail.el.id !== 'edit-step-request') return;
            if (event.detail.type === 'started') started = true;
            if (started && event.detail.type === 'finished') window.stepFinished = true;
          });
        }"""
    )
    with page.expect_request(step_url):
        (_front(page) if target_step == 2 else _back(page)).press("Enter")
    accepted = _respond_to_confirm(page, accept=True)
    page.locator("#pile").click()
    assert len(accepted) == 1
    page.locator(f"#deck-cards button[data-note-id='{nid}']").click()
    expect(_front(page)).to_have_value("Saved")
    expect(_front(page)).to_be_focused()
    expect(page.locator("#edit-step")).to_have_attribute("data-step", "1")
    assert len(pending) == 1
    route, response = pending[0]
    route.fulfill(response=response)
    page.wait_for_function("() => window.stepFinished")
    expect(_front(page)).to_have_value("Saved")
    expect(_front(page)).to_be_visible()
    expect(_front(page)).to_be_focused()
    expect(_back(page)).to_have_value("answer")
    expect(page.locator("#edit-step")).to_have_attribute("data-step", "1")
    expect(page.locator("#edit-error")).not_to_be_visible()


def test_history_navigation_during_pending_step_preserves_draft(
    page: Page, live_app: LiveApp
) -> None:
    _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Saved", "answer"))
    page.emulate_media(reduced_motion="reduce")
    editor_url = f"{live_app}/app/edit/1/front"
    page.goto(editor_url)
    _front(page).fill("Draft")
    pending: list[tuple[Route, Any]] = []

    def hold_step(route: Route) -> None:
        pending.append((route, route.fetch()))

    step_url = "**/app/edit/1/*/*/step/back/*"
    page.route(step_url, hold_step)
    page.evaluate(
        """() => {
          window.stepFinished = false;
          let started = false;
          document.addEventListener('datastar-fetch', event => {
            if (event.detail.el.id !== 'edit-step-request') return;
            if (event.detail.type === 'started') started = true;
            if (started && event.detail.type === 'finished') window.stepFinished = true;
          });
        }"""
    )
    with page.expect_request(step_url):
        _front(page).press("Enter")
    accepted = _respond_to_confirm(page, accept=True)
    page.locator("#pile").click()
    assert len(accepted) == 1
    expect(page).to_have_url(f"{editor_url.removesuffix('/front')}/cards")
    page.go_back()
    expect(page).to_have_url(editor_url)
    expect(_front(page)).to_be_visible()
    assert len(pending) == 1
    route, response = pending[0]
    route.fulfill(response=response)
    page.wait_for_function("() => window.stepFinished")
    expect(_front(page)).to_have_value("Draft")
    expect(page.locator("#edit-step")).to_have_attribute("data-step", "1")
    accepted = _respond_to_confirm(page, accept=True)
    page.go_forward()
    expect(page).to_have_url(f"{editor_url.removesuffix('/front')}/cards")
    assert len(accepted) == 1
    page.go_back()
    expect(page).to_have_url(editor_url)
    expect(_front(page)).to_have_value("Draft")
    expect(page.locator("#edit-step")).to_have_attribute("data-step", "1")


def test_typing_during_pending_step_does_not_corrupt_fields(
    page: Page, live_app: LiveApp
) -> None:
    errors = _browser_errors(page)
    page.goto(f"{live_app}/app/edit/1/front")
    pending: list[tuple[Route, Any]] = []

    def hold_step(route: Route) -> None:
        pending.append((route, route.fetch()))

    step_url = "**/app/edit/1/*/*/step/back/*"
    page.route(step_url, hold_step)
    page.evaluate(
        """() => {
          window.stepFinished = false;
          document.addEventListener('datastar-fetch', event => {
            if (event.detail.el.id === 'edit-step-request' && event.detail.type === 'finished')
              window.stepFinished = true;
          });
        }"""
    )
    _front(page).fill("Question")
    with page.expect_request(step_url):
        _front(page).press("Enter")
    page.keyboard.type("answer", delay=20)
    assert len(pending) == 1
    route, response = pending[0]
    route.fulfill(response=response)
    page.wait_for_function("() => window.stepFinished")
    expect(_back(page)).to_be_visible()
    expect(_front(page)).to_have_value("Question")
    expect(_back(page)).to_have_value("")
    assert errors == []


def test_saving_makes_form_inert_and_prevents_duplicate_save(
    page: Page, live_app: LiveApp
) -> None:
    page.goto(f"{live_app}/app/edit/1/front")
    _to_preview(page, "Question", "Answer")
    pending: list[Route] = []

    def hold_commit(route: Route) -> None:
        pending.append(route)

    commit_url = "**/app/edit/1/*/*/commit"
    page.route(commit_url, hold_commit)
    with page.expect_request(commit_url):
        page.locator("#btn-add").click()
    session = page.locator("#edit-session")
    expect(session).to_have_attribute("inert", "")
    expect(page.locator("#btn-add")).to_be_disabled()
    page.keyboard.press("Tab")
    assert not session.evaluate("el => el.contains(document.activeElement)")
    page.keyboard.type("unexpected")
    expect(_front(page)).to_have_value("Question")
    expect(_back(page)).to_have_value("Answer")
    assert len(pending) == 1
    assert live_app.notes() == []
    pending[0].continue_()
    expect(_front(page)).to_have_value("")
    assert len(live_app.notes()) == 1


def test_step_urls_and_browser_history_preserve_draft(
    page: Page, live_app: LiveApp
) -> None:
    base = f"{live_app}/app/edit/1"
    page.goto(f"{base}/front")
    _front(page).fill("Question")
    _front(page).press("Enter")
    _wait_for_back(page)
    expect(page).to_have_url(f"{base}/back")
    _back(page).fill("Answer")
    _back(page).press("Enter")
    expect(page.locator("#preview")).to_contain_text("Answer")
    expect(page).to_have_url(f"{base}/preview")

    page.go_back()
    _wait_for_back(page)
    expect(page).to_have_url(f"{base}/back")
    expect(_front(page)).to_have_value("Question")
    expect(_back(page)).to_have_value("Answer")
    page.go_back()
    expect(_front(page)).to_be_visible()
    expect(page).to_have_url(f"{base}/front")
    expect(_front(page)).to_have_value("Question")
    page.go_forward()
    _wait_for_back(page)
    expect(page).to_have_url(f"{base}/back")
    page.go_forward()
    expect(page.locator("#preview")).to_contain_text("Question")
    expect(page.locator("#preview")).to_contain_text("Answer")
    expect(page).to_have_url(f"{base}/preview")


def test_forward_to_preview_revalidates_current_draft(
    page: Page, live_app: LiveApp
) -> None:
    base = f"{live_app}/app/edit/1"
    page.goto(f"{base}/front")
    _to_preview(page, "Question", "Answer")
    expect(page).to_have_url(f"{base}/preview")
    page.go_back()
    _wait_for_back(page)
    expect(page).to_have_url(f"{base}/back")
    _back(page).fill("")
    page.go_forward()
    expect(page.locator("#edit-error")).to_contain_text("Front and back are required")
    expect(page).to_have_url(f"{base}/back")
    expect(_back(page)).to_be_visible()
    expect(_front(page)).to_have_value("Question")
    expect(_back(page)).to_have_value("")


def test_reload_new_card_back_step_redirects_to_front(
    page: Page, live_app: LiveApp
) -> None:
    base = f"{live_app}/app/edit/1"
    page.goto(f"{base}/front")
    _front(page).fill("Question")
    _front(page).press("Enter")
    _wait_for_back(page)
    expect(page).to_have_url(f"{base}/back")
    page.reload()
    expect(page).to_have_url(f"{base}/front")
    expect(_front(page)).to_be_visible()
    expect(_front(page)).to_have_value("")


def test_direct_card_preview_renders_saved_note(page: Page, live_app: LiveApp) -> None:
    nid = _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Saved", "answer"))
    url = f"{live_app}/app/edit/1/cards/{nid}/preview"
    page.goto(url)
    expect(page).to_have_url(url)
    expect(page.locator("#preview")).to_be_visible()
    expect(page.locator("#preview")).to_contain_text("Saved")
    expect(page.locator("#preview")).to_contain_text("answer")
    expect(page.locator("#btn-add")).to_have_text("Save changes")


def test_list_back_returns_to_prior_step_without_duplicate_entries(
    page: Page, live_app: LiveApp
) -> None:
    _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Saved", "answer"))
    page.emulate_media(reduced_motion="reduce")
    base = f"{live_app}/app/edit/1"
    page.goto(f"{base}/front")
    _front(page).fill("Draft")
    _front(page).press("Enter")
    _wait_for_back(page)
    _back(page).fill("Draft answer")
    accepted = _respond_to_confirm(page, accept=True)
    page.locator("#pile").click()
    assert len(accepted) == 1
    expect(page).to_have_url(f"{base}/cards")
    expect(page.locator("#deck-cards")).to_be_visible()
    page.locator("#edit-back").click()
    _wait_for_back(page)
    expect(page).to_have_url(f"{base}/back")
    expect(_front(page)).to_have_value("Draft")
    expect(_back(page)).to_have_value("Draft answer")
    page.go_back()
    expect(page).to_have_url(f"{base}/front")
    expect(_front(page)).to_have_value("Draft")
    page.go_forward()
    _wait_for_back(page)
    expect(page).to_have_url(f"{base}/back")
    accepted = _respond_to_confirm(page, accept=True)
    page.go_forward()
    expect(page).to_have_url(f"{base}/cards")
    assert len(accepted) == 1
    expect(page.locator("#deck-cards")).to_be_visible()


def test_browser_back_after_add_reaches_previous_page(
    page: Page, live_app: LiveApp
) -> None:
    errors = _browser_errors(page)
    page.goto(f"{live_app}/app/")
    page.goto(f"{live_app}/app/edit/1/front")
    _add(page, "Added", "answer")
    expect(page).to_have_url(f"{live_app}/app/edit/1/front")
    page.go_back()
    expect(page).to_have_url(f"{live_app}/app/")
    assert errors == []


def test_direct_editor_routes_redirect_to_valid_views(
    page: Page, live_app: LiveApp
) -> None:
    nid = _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Saved", "answer"))
    base = f"{live_app}/app/edit/1"
    for path, target in (
        (base, f"{base}/front"),
        (f"{base}/back", f"{base}/front"),
        (f"{base}/preview", f"{base}/front"),
        (f"{base}/invalid-step", f"{base}/front"),
        (f"{base}/cards/invalid-id", f"{base}/front"),
        (f"{base}/cards/{nid}", f"{base}/cards/{nid}/front"),
        (f"{base}/cards/{nid}/invalid-step", f"{base}/front"),
        (f"{live_app}/app/edit/invalid-deck/front", f"{live_app}/app/"),
    ):
        page.goto(path)
        expect(page).to_have_url(target)
