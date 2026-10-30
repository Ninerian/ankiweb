import asyncio
import re
import socket
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from itertools import pairwise
from pathlib import Path
from typing import Literal

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


def _to_preview(page: Page, front: str, back: str) -> None:
    _front(page).fill(front)
    _front(page).press("Enter")
    expect(_back(page)).to_be_visible()
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
    page.goto(f"{live_app}/app/edit?deck=1")
    front = "a < b & c"
    _front(page).fill(front)
    _front(page).press("Enter")
    expect(_back(page)).to_be_visible()
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
        other.goto(f"{live_app}/app/edit?deck=1")
        expect(other.locator("#added-cards")).to_contain_text(front)
        expect(other.locator("#added-cards .add-stack-count")).to_have_text("1")
        other.get_by_role("button", name="Done", exact=True).click()
        expect(other.get_by_text("Add a card first.")).to_be_visible()
        assert live_app.notes() == saved
    finally:
        isolated.close()
    assert live_app.persisted_notes() == saved


def test_added_stack_opens_list_and_preserves_draft(
    page: Page, live_app: LiveApp
) -> None:
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/app/edit?deck=1")
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
    page.locator("#edit-cancel").click()
    expect(_front(page)).to_have_value("")
    assert live_app.notes() == original
    assert live_app.persisted_notes() == original


def test_pile_keyboard_badge_and_back_restore_focus(
    page: Page, live_app: LiveApp
) -> None:
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/app/edit?deck=1")
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
    expect(page).to_have_url(f"{live_app}/app/edit?deck=1")
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
    expect(page).to_have_url(f"{live_app}/app/edit?deck=1")
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
        touch_page.goto(f"{live_app}/app/edit?deck=1")
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
    page.goto(f"{live_app}/app/edit?deck=1")
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
    page.goto(f"{live_app}/app/edit?deck=1")
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


def _assert_browse_chrome_fades(page: Page) -> None:
    frames = page.evaluate("window.motionFrames")
    opening = [frame for frame in frames if frame["phase"] == "opening"]
    returning = [frame for frame in frames if frame["phase"] == "returning"]
    assert len(opening) >= 3 and len(returning) >= 3
    assert all(value > 0 for frame in opening for value in frame["height"])
    assert all(all(frame["inert"]) for frame in opening)
    assert all(not frame["doneDisabled"] for frame in opening)
    done_background = page.evaluate("window.doneBackground")
    assert all(frame["doneBackground"] == done_background for frame in opening)
    for index in range(3):
        assert any(0.05 < frame["opacity"][index] < 0.95 for frame in opening)
        assert any(0.05 < frame["opacity"][index] < 0.95 for frame in returning)
        assert opening[0]["opacity"][index] > opening[-1]["opacity"][index]
        assert returning[0]["opacity"][index] < returning[-1]["opacity"][index]


def test_browse_visibly_lifts_stack_and_fades_chrome(
    page: Page, live_app: LiveApp
) -> None:
    _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Motion", "answer"))
    page.emulate_media(reduced_motion="no-preference")
    page.goto(f"{live_app}/app/edit?deck=1")
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
                opacity: [steps, done, footer].map(el => Number(style(el).opacity)),
                height: [steps, footer].map(el => el.getBoundingClientRect().height),
                inert: [steps, done, footer].map(el =>
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
    expect(done).to_have_css("opacity", "0")
    expect(done).to_be_disabled()
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
    page.goto(f"{live_app}/app/edit?deck=1")
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
    url = f"{live_app}/app/edit?deck=1"
    page.goto(url)
    wizard = page.locator("#add-wizard")
    pile = page.locator("#pile")
    back = page.locator("#edit-back")
    cards = page.locator("#deck-cards")
    pile.click()
    expect(wizard).to_have_attribute("data-browse-phase", "opening")
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
    expect(back).to_have_role("button")
    expect(back).not_to_have_attribute("href", re.compile("."))
    expect(back).to_have_attribute("aria-disabled", "true")
    back.focus()
    expect(back).to_be_focused()
    page.keyboard.press("Enter")
    expect(page).to_have_url(url)
    expect(wizard).to_have_attribute("data-browse-phase", "returning")
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
    page.goto(f"{live_app}/app/edit?deck=1")
    pile = page.locator("#pile")
    cards = page.locator("#deck-cards")
    page.evaluate(
        """() => {
          const wizard = document.querySelector('#add-wizard');
          const card = document.querySelector('#added-cards .stacked-card');
          const chrome = [
            document.querySelector('.add-step').parentElement,
            wizard.querySelector('header .review-hud-nav button'),
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
    assert reduced["opacity"] == [0, 0, 0]
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
    page.goto(f"{live_app}/app/edit?deck=1")
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
    page.goto(f"{live_app}/app/edit?deck=1")
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
    expect(opener).to_be_focused()
    page.get_by_role("button", name="Done", exact=True).click()
    expect(page.get_by_text("Add a card first.")).to_be_visible()
    expect(page.get_by_role("dialog")).not_to_be_visible()

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
    page.goto(f"{live_app}/app/edit?deck=1")
    page.locator("#pile").click()
    cards = page.locator("#deck-cards")
    row = cards.locator(f"button[data-note-id='{nid}']")
    url = f"{live_app}/app/edit/card/{nid}?deck=1"
    page.route(url, lambda route: route.fulfill(status=404, body="Unavailable"))
    row.click()
    alert = page.locator("#app-error")
    expect(alert).to_be_visible()
    expect(alert).to_contain_text(error)
    expect(cards).to_be_visible()
    expect(row).to_be_enabled()
    expect(page.locator("#input-front")).not_to_be_visible()
    assert _run(live_app, lambda col: col.get_note(nid)["Front"]) == "Retry card"

    page.unroute(url)
    row.click()
    expect(cards).not_to_be_visible()
    expect(alert).not_to_be_visible()
    expect(page.locator("#input-front")).to_have_value("Retry card")
    expect(page.locator("#input-front")).to_be_focused()


def test_unchanged_and_dirty_edits_guard_discard(page: Page, live_app: LiveApp) -> None:
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/app/edit?deck=1")
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
    page.locator("#edit-cancel").click()
    expect(_front(page)).to_have_value("")
    assert unexpected == []
    pile.click()
    cards.locator(f"button[data-note-id='{first}']").click()
    expect(_front(page)).to_have_value("First")
    _front(page).fill("Temporary change")
    _front(page).fill("First")
    back.click()
    expect(cards).to_be_visible()
    expect(page).to_have_url(f"{live_app}/app/edit?deck=1")
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
    expect(page).to_have_url(f"{live_app}/app/edit?deck=1")
    accepted = _respond_to_confirm(page, accept=True)
    back.click()
    assert len(accepted) == 1
    expect(cards).to_be_visible()
    expect(back).to_have_accessible_name("Back to card editor")
    page.locator("#edit-back").click()
    expect(back).to_be_focused()
    expect(page).to_have_url(f"{live_app}/app/edit?deck=1")
    expect(_front(page)).to_have_value("Changed second")
    rejected = _respond_to_confirm(page, accept=False)
    page.keyboard.press("Escape")
    assert len(rejected) == 1
    expect(_front(page)).to_have_value("Changed second")
    assert live_app.notes() == original
    accepted = _respond_to_confirm(page, accept=True)
    page.keyboard.press("Escape")
    assert len(accepted) == 1
    expect(_front(page)).to_have_value("")
    assert live_app.notes() == original

    pile.click()
    cards.locator(f"button[data-note-id='{first}']").click()
    expect(_front(page)).to_have_value("First")
    _front(page).fill("Changed first")
    rejected = _respond_to_confirm(page, accept=False)
    page.locator("#edit-cancel").click()
    assert len(rejected) == 1
    expect(_front(page)).to_have_value("Changed first")
    accepted = _respond_to_confirm(page, accept=True)
    page.locator("#edit-cancel").click()
    assert len(accepted) == 1
    expect(_front(page)).to_have_value("")
    assert live_app.notes() == original


@pytest.mark.parametrize("key", ["Enter", "Space"])
def test_back_has_button_semantics_and_guards_for_browse_and_edit(
    page: Page, live_app: LiveApp, key: str
) -> None:
    nid = _run(live_app, lambda col: add_vocab_note(col, DeckId(1), "Saved", "answer"))
    page.emulate_media(reduced_motion="reduce")
    url = f"{live_app}/app/edit?deck=1"
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
    expect(page).to_have_url(url)
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
    expect(page).to_have_url(url)
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
    page.goto(f"{live_app}/app/edit?deck=1")
    page.locator("#pile").click()
    cards = page.locator("#deck-cards")
    cards.locator(f"button[data-note-id='{nid}']").click()
    expect(_front(page)).to_have_value("Saved")
    _front(page).fill("Updated")
    _front(page).press("Enter")
    _back(page).press("Enter")

    def fail_update(*args, **kwargs):
        raise ValueError("deterministic update failure")

    with monkeypatch.context() as patch:
        patch.setattr(
            "ankiweb.adapters.inbound.http_app.edit.update_vocab_note", fail_update
        )
        page.locator("#btn-add").click()
        expect(page.locator("#app-error")).to_be_visible()
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
    page.goto(f"{live_app}/app/edit?deck=1")
    _add(page, "First", "one")
    _add(page, "Second", "two")
    first = live_app.notes()[0][0]
    cards = page.locator("#deck-cards")
    page.locator("#pile").click()
    cards.locator(f"button[data-note-id='{first}']").click()
    expect(_front(page)).to_have_value("First")
    _front(page).fill("Second")
    _front(page).press("Enter")
    _back(page).press("Enter")
    page.locator("#btn-add").click()
    expect(page.locator("#app-error")).to_be_visible()
    expect(cards).not_to_be_visible()
    expect(page.locator("#preview")).to_contain_text("Second")
    expect(page.locator("#btn-add")).to_be_enabled()
    assert live_app.notes()[0][1][0] == "First"

    previous = page.get_by_role("button", name="Previous Step")
    previous.click()
    previous.click()
    _front(page).fill("Corrected")
    _front(page).press("Enter")
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
    url = f"{live_app}/app/edit?deck=1"
    page.goto(url)
    page.locator("#pile").click()
    cards = page.locator("#deck-cards")
    cards.locator(f"button[data-note-id='{nid}']").click()
    expect(_front(page)).to_have_value("Saved")
    _front(page).fill("Updated")
    _front(page).press("Enter")
    _back(page).press("Enter")

    pending: list[Route] = []

    def hold_commit(route: Route) -> None:
        pending.append(route)

    unexpected: list[str] = []

    def dismiss_unexpected(dialog: Dialog) -> None:
        unexpected.append(dialog.message)
        dialog.dismiss()

    page.on("dialog", dismiss_unexpected)
    page.route("**/app/edit/commit?deck=1", hold_commit)
    with page.expect_request("**/app/edit/commit?deck=1"):
        page.locator("#btn-add").click()
    back = page.locator("#edit-back")
    expect(back).to_have_attribute("aria-disabled", "true")
    expect(back).to_have_role("button")
    expect(back).not_to_have_attribute("href", re.compile("."))
    back.focus()
    expect(back).to_be_focused()
    page.keyboard.press("Enter")
    expect(page).to_have_url(url)
    page.keyboard.press("Space")
    expect(page).to_have_url(url)
    expect(cards).not_to_be_visible()
    expect(page.locator("#preview")).to_contain_text("Updated")
    expect(page.locator("#btn-add")).to_be_disabled()
    assert unexpected == []
    assert _run(live_app, lambda col: col.get_note(nid)["Front"]) == "Saved"
    assert len(pending) == 1
    with page.expect_request("**/app/edit/commit?deck=1"):
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


@pytest.mark.parametrize(
    ("live_app", "marker", "legend", "warning", "notice"),
    [
        (
            "",
            "Learned",
            "Changing a learned card resets its learning progress.",
            "Changes to this learned card will reset its learning progress.",
            "Learning progress was reset.",
        ),
        (
            "de_DE",
            "Gelernt",
            "Änderungen an gelernten Karten setzen den Lernfortschritt zurück.",
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
    legend: str,
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
    page.goto(f"{live_app}/app/edit?deck=1")
    opener = page.locator("#pile")
    cards = page.locator("#deck-cards")
    opener.click()
    expect(cards.locator("#deck-cards-legend")).to_have_text(legend)
    row = cards.locator(f"button[data-note-id='{nid}']")
    expect(row).to_contain_text(marker)
    row.click()
    front = page.locator("#input-front")
    expect(front).to_have_value("Reviewed")
    expect(front).to_be_focused()
    expect(page.locator("#edit-warning")).to_have_text(warning)
    expect(page.locator("#edit-warning")).to_be_visible()

    front.press("Enter")
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
    page.locator("#edit-cancel").click()
    assert len(accepted) == 1
    expect(front).to_have_value("")
    assert _progress(live_app, nid) == before
    assert _run(live_app, lambda col: col.get_note(nid)["Front"]) == "Reviewed"

    opener.click()
    expect(row).to_contain_text(marker)
    row.click()
    expect(front).to_have_value("Reviewed")
    expect(page.locator("#edit-warning")).to_have_text(warning)
    front.fill("Edited reviewed")
    front.press("Enter")
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
    page.goto(f"{live_app}/app/edit?deck=1")
    page.locator("#pile").click()
    page.locator(f"#deck-cards button[data-note-id='{nid}']").click()
    front = page.locator("#input-front")
    expect(front).to_have_value("Reviewed")
    expect(page.locator("#edit-warning")).to_have_text(warning)
    front.fill("Edited reviewed")
    front.press("Enter")
    page.locator("#input-back").press("Enter")
    page.locator("#btn-add").click()

    expect(page.locator("#app-error")).to_be_visible()
    expect(page.locator("#app-error")).to_have_text(failure)
    expect(page.locator("#edit-cancel")).to_be_visible()
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
        page.locator("#edit-cancel").click()
        assert len(accepted) == 1
        expect(front).to_have_value("")
        assert calls == [([cid], True)]
        assert _progress(live_app, nid) == before
        assert (
            _run(live_app, lambda col: col.get_note(nid)["Front"]) == "Edited reviewed"
        )

        page.context.clear_cookies()
        assert page.context.cookies() == []
        page.goto(f"{live_app}/app/edit?deck=1")
        page.locator("#pile").click()
        page.locator(f"#deck-cards button[data-note-id='{nid}']").click()
        expect(front).to_have_value("Edited reviewed")
        expect(page.locator("#edit-warning")).to_be_visible()
        expect(page.locator("#edit-warning")).to_have_text(warning)
        front.press("Enter")
        expect(page.locator("#input-back")).to_have_value("answer")
        page.locator("#input-back").press("Enter")

    with page.expect_request(
        lambda request: (
            request.method == "POST" and request.url.endswith("/app/edit/commit?deck=1")
        )
    ) as retry:
        page.locator("#btn-add").click()
    retry_payload = retry.value.post_data_json
    assert isinstance(retry_payload, dict)
    assert retry_payload["nid"] == nid
    assert retry_payload["learned"] is True
    assert retry_payload["front"] == "Edited reviewed"
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
    page.goto(f"{live_app}/app/edit?deck=1")
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
        expect(page.locator("#input-back")).to_be_visible()
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
    page.goto(f"{live_app}/app/edit?deck=1")
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
    page.goto(f"{live_app}/app/edit?deck=1")
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
          const transform = new DOMMatrixReadOnly(style.transform);
          const canvas = document.createElement('canvas');
          canvas.width = canvas.height = 1;
          const ctx = canvas.getContext('2d');
          ctx.fillStyle = style.backgroundColor;
          ctx.fillRect(0, 0, 1, 1);
          return {
            top: box.top, bottom: box.bottom, height: el.offsetHeight,
            opacity: Number(style.opacity),
            alpha: ctx.getImageData(0, 0, 1, 1).data[3],
            z: Number(style.zIndex),
            lift: transform.m42, rotation: transform.m12,
            floor: parseFloat(style.bottom), shadow: style.boxShadow,
          };
        })"""
    )
    assert all(card["height"] == 104 for card in geometry)
    assert all(card["opacity"] == 1 and card["alpha"] == 255 for card in geometry)
    assert all(geometry[i]["z"] > geometry[i + 1]["z"] for i in range(4))
    assert [card["lift"] for card in geometry] == [0, -26, -52, -78, -104]
    assert all(card["floor"] == 38 and card["rotation"] != 0 for card in geometry)
    assert all(card["shadow"] != "none" for card in geometry)
    assert (
        page.locator("#add-stage").evaluate("el => getComputedStyle(el).perspective")
        == "1000px"
    )
    for front, behind in pairwise(geometry):
        assert 5 < front["top"] - behind["top"] < 45
        assert behind["bottom"] > front["top"]

    pile_box = page.locator("#pile").bounding_box()
    badge_box = region.locator(".add-stack-badge").bounding_box()
    cue_box = region.locator(".pile-cue").bounding_box()
    assert pile_box is not None and badge_box is not None and cue_box is not None
    assert badge_box["x"] > pile_box["x"] + pile_box["width"] / 2
    assert cue_box["y"] > pile_box["y"] + pile_box["height"] / 2
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def test_required_fields_block_wizard_advancement(
    page: Page, live_app: LiveApp
) -> None:
    page.goto(f"{live_app}/app/edit?deck=1")
    page.get_by_role("button", name=re.compile(r"Next: Back")).click()
    expect(page.locator("#app-error")).to_contain_text("Front cannot be empty")
    expect(_front(page)).to_be_visible()
    _front(page).fill("Question")
    _front(page).press("Enter")
    expect(_back(page)).to_be_visible()
    _back(page).press("Enter")
    expect(page.locator("#app-error")).to_contain_text("Back cannot be empty")
    expect(_back(page)).to_be_visible()


def test_validation_toast_and_optional_fields_keep_add_styles(
    page: Page, live_app: LiveApp
) -> None:
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/app/edit?deck=1")
    page.get_by_role("button", name=re.compile(r"Next: Back")).click()
    alert = page.get_by_role("alert")
    expect(alert).to_contain_text("Front cannot be empty")
    expect(alert).to_be_visible()
    expect(alert).to_have_css("border-top-width", "3px")
    expect(alert).to_have_css("border-top-style", "solid")
    expect(alert).to_have_css("border-top-left-radius", "16px")
    expect(alert).to_have_css("text-align", "center")
    expect(alert).to_have_css("font-weight", "900")
    expect(alert).to_have_css("animation-name", "none")
    expect(page.locator("#app-error")).to_have_css("z-index", "50")
    toast_box = alert.bounding_box()
    footer_box = page.locator("#add-wizard footer").bounding_box()
    assert toast_box is not None and footer_box is not None
    assert toast_box["y"] + toast_box["height"] <= footer_box["y"]

    _front(page).fill("Question")
    _front(page).press("Enter")
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
    page.goto(f"{live_app}/app/edit?deck=1")
    _add(page)
    saved = live_app.notes()
    _to_preview(page, "Hund", "different answer")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(page.locator("#app-error")).to_contain_text(
        "A card with this front already exists."
    )
    expect(page.locator("#preview")).to_contain_text("different answer")
    assert live_app.notes() == saved


def test_finish_guard_dialog_and_study_link(page: Page, live_app: LiveApp) -> None:
    page.goto(f"{live_app}/app/edit?deck=1")
    done = page.get_by_role("button", name="Done", exact=True)
    done.click()
    expect(page.get_by_text("Add a card first.")).to_be_visible()
    expect(page.get_by_role("dialog")).not_to_be_visible()
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
    close = dialog.get_by_role("button", name="Close", exact=True)
    expect(close).to_be_visible()
    close.focus()
    expect(close).to_be_focused()
    page.keyboard.press("Enter")
    expect(dialog).not_to_be_visible()
    expect(page).to_have_url(f"{live_app}/app/edit?deck=1")
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
    assert live_app.notes() == saved
    done.click()
    expect(dialog).to_be_visible()
    # Plan 3's review page is not required for testing the navigation target.
    page.route("**/app/review?deck=1", lambda route: route.fulfill(body="Review"))
    study.click()
    expect(page).to_have_url(f"{live_app}/app/review?deck=1")
    assert live_app.notes() == saved

    page.goto(f"{live_app}/app/edit?deck=1")
    done.click()
    expect(dialog).to_be_visible()
    decks.click()
    expect(page).to_have_url(f"{live_app}/app/")
    assert live_app.notes() == saved


@pytest.mark.parametrize("link_name", ["Exit Creator", "🗂️ Default"])
def test_exit_and_deck_links_guard_unsaved_text(
    page: Page, live_app: LiveApp, link_name: str
) -> None:
    url = f"{live_app}/app/edit?deck=1"
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
    page.goto(f"{live_app}/app/edit?deck=1")
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
    page.goto(f"{live_app}/app/edit?deck=1")
    _add(page)
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    assert page.screenshot().startswith(b"\x89PNG\r\n\x1a\n")
    assert errors == []
