import asyncio
import re
import socket
import threading
import time
from collections.abc import Iterator
from concurrent.futures import Future
from pathlib import Path
from typing import Literal

import pytest
import uvicorn
from anki.collection import Collection
from fastapi import FastAPI

from ankiweb.app import create_app
from ankiweb.core.config import Settings

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import (
    ConsoleMessage,
    Dialog,
    Locator,
    Page,
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
def live_app(tmp_path: Path) -> Iterator[LiveApp]:
    path = tmp_path / "live.anki2"
    app = create_app(Settings(collection_path=path))
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


def test_wizard_add_reload_and_session_isolation(page: Page, live_app: LiveApp) -> None:
    page.goto(f"{live_app}/app/add?deck=1")
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
    expect(page.locator("#hud-count")).to_contain_text(re.compile(r"1\s+Cards added"))
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
    expect(page.locator("#hud-count")).to_contain_text(re.compile(r"1\s+Cards added"))
    expect(_front(page)).to_have_value("")
    assert live_app.notes() == saved

    # A new session has its own list, but must not remove the persisted note.
    browser = page.context.browser
    assert browser is not None
    isolated = browser.new_context()
    try:
        other = isolated.new_page()
        other.goto(f"{live_app}/app/add?deck=1")
        expect(other.locator("#added-cards")).not_to_contain_text(front)
        assert live_app.notes() == saved
    finally:
        isolated.close()
    assert live_app.persisted_notes() == saved


def test_edit_last_discard_guard_and_round_trip(page: Page, live_app: LiveApp) -> None:
    page.goto(f"{live_app}/app/add?deck=1")
    _front(page).fill("a < b & c")
    _front(page).press("Enter")
    _back(page).fill("first answer")
    page.get_by_text("Hint · Optional", exact=True).click()
    page.get_by_label("Hint", exact=True).fill("hint <one> & two")
    page.get_by_text("Example sentence · Optional", exact=True).click()
    page.get_by_label("Example sentence", exact=True).fill("A *word*\nnext line")
    _back(page).press("Enter")
    expect(page.locator("#preview")).to_contain_text("a < b & c")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(_front(page)).to_have_value("")
    expect(page.locator("#added-cards")).to_contain_text("a < b & c")
    original = live_app.notes()
    assert len(original) == 1
    _front(page).fill("unsaved draft")
    edit = page.locator("#added-cards").get_by_role(
        "button", name="Edit last added card", exact=True
    )
    cancelled = _respond_to_confirm(page, accept=False)
    edit.click()
    assert len(cancelled) == 1
    expect(_front(page)).to_have_value("unsaved draft")
    assert live_app.notes() == original

    accepted = _respond_to_confirm(page, accept=True)
    edit.click()
    assert len(accepted) == 1
    expect(_front(page)).to_have_value("a < b & c")
    _front(page).fill("Updated <front> & text")
    _front(page).press("Enter")
    expect(_back(page)).to_have_value("first answer")
    expect(page.get_by_label("Hint", exact=True)).to_be_visible()
    expect(page.get_by_label("Hint", exact=True)).to_have_value("hint <one> & two")
    expect(page.get_by_label("Example sentence", exact=True)).to_be_visible()
    expect(page.get_by_label("Example sentence", exact=True)).to_have_value(
        "A *word*\nnext line"
    )
    _back(page).fill("updated answer")
    _back(page).press("Enter")
    expect(page.locator("#preview")).to_contain_text("Updated <front> & text")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(_front(page)).to_be_visible()
    expect(page.locator("#added-cards")).to_contain_text("Updated <front> & text")
    expect(page.locator("#hud-count")).to_contain_text(re.compile(r"1\s+Cards added"))
    updated = live_app.notes()
    assert len(updated) == 1
    assert updated[0][0] == original[0][0]
    assert updated[0][1] == [
        "Updated &lt;front&gt; &amp; text",
        "updated answer",
        "hint &lt;one&gt; &amp; two",
        "A *word*<br>next line",
    ]
    page.reload()
    expect(page.locator("#added-cards")).to_contain_text("Updated <front> & text")
    assert live_app.notes() == updated
    assert live_app.persisted_notes() == updated


def test_double_click_add_saves_only_one_note(page: Page, live_app: LiveApp) -> None:
    page.goto(f"{live_app}/app/add?deck=1")
    _to_preview(page, "Double click", "one note")
    page.get_by_role("button", name="Add", exact=True).dblclick()
    expect(_front(page)).to_be_visible()
    expect(page.locator("#hud-count")).to_contain_text(re.compile(r"1\s+Cards added"))
    saved = live_app.notes()
    assert len(saved) == 1
    assert saved[0][1][:2] == ["Double click", "one note"]
    page.reload()
    assert live_app.notes() == saved


def test_required_fields_block_wizard_advancement(
    page: Page, live_app: LiveApp
) -> None:
    page.goto(f"{live_app}/app/add?deck=1")
    page.get_by_role("button", name=re.compile(r"Next: Back")).click()
    expect(page.locator("#app-error")).to_contain_text("Front cannot be empty")
    expect(_front(page)).to_be_visible()
    _front(page).fill("Question")
    _front(page).press("Enter")
    expect(_back(page)).to_be_visible()
    _back(page).press("Enter")
    expect(page.locator("#app-error")).to_contain_text("Back cannot be empty")
    expect(_back(page)).to_be_visible()


def test_duplicate_preserves_preview_and_saved_note(
    page: Page, live_app: LiveApp
) -> None:
    page.goto(f"{live_app}/app/add?deck=1")
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
    page.goto(f"{live_app}/app/add?deck=1")
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
    keep = dialog.get_by_role("button", name="Keep adding more cards", exact=True)
    study = dialog.get_by_role("link", name="Start studying", exact=True)
    expect(study).to_have_attribute("href", "/app/review?deck=1")
    study.focus()
    page.keyboard.press("Tab")
    assert dialog.evaluate("el => el.contains(document.activeElement)")
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()

    done.click()
    expect(dialog).to_be_visible()
    keep.click()
    expect(dialog).not_to_be_visible()
    assert live_app.notes() == saved
    done.click()
    expect(dialog).to_be_visible()
    # Plan 3's review page is not required for testing the navigation target.
    page.route("**/app/review?deck=1", lambda route: route.fulfill(body="Review"))
    study.click()
    expect(page).to_have_url(f"{live_app}/app/review?deck=1")
    assert live_app.notes() == saved


@pytest.mark.parametrize("link_name", ["Exit Creator", "Default"])
def test_exit_and_deck_links_guard_unsaved_text(
    page: Page, live_app: LiveApp, link_name: str
) -> None:
    url = f"{live_app}/app/add?deck=1"
    page.goto(url)
    link = page.locator("#add-wizard header").get_by_role(
        "link", name=link_name, exact=True
    )
    expect(link).to_have_attribute("href", "/app/")
    _front(page).fill("unsaved")
    cancelled = _respond_to_confirm(page, accept=False)
    link.click()
    assert len(cancelled) == 1
    expect(page).to_have_url(url)
    expect(_front(page)).to_have_value("unsaved")
    accepted = _respond_to_confirm(page, accept=True)
    link.click()
    assert len(accepted) == 1
    expect(page).to_have_url(f"{live_app}/app/")


@pytest.mark.parametrize("link_name", ["Exit Creator", "Default"])
def test_clean_exit_and_deck_links_navigate_without_confirmation(
    page: Page, live_app: LiveApp, link_name: str
) -> None:
    page.goto(f"{live_app}/app/add?deck=1")
    link = page.locator("#add-wizard header").get_by_role(
        "link", name=link_name, exact=True
    )
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
    page.goto(f"{live_app}/app/add?deck=1")
    _add(page)
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    assert page.screenshot().startswith(b"\x89PNG\r\n\x1a\n")
    assert errors == []
