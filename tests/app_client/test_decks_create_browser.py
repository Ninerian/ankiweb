import asyncio
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

import pytest
import uvicorn
from anki.collection import Collection
from anki.decks import DeckId

from ankiweb.app import create_app
from ankiweb.core.config import Settings
from ankiweb.core.ports import CollectionPort

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import ConsoleMessage, expect, sync_playwright


@pytest.fixture
def create_server(tmp_path: Path) -> Iterator[tuple[str, CollectionPort]]:
    app = create_app(Settings(collection_path=tmp_path / "decks-browser.anki2"))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        thread = threading.Thread(
            target=server.run, kwargs={"sockets": [listener]}, daemon=True
        )
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("server did not start")
                time.sleep(0.05)
            yield f"http://127.0.0.1:{port}", app.state.service
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError("server did not stop")


def test_create_first_deck_from_empty_state(
    create_server: tuple[str, CollectionPort], tmp_path: Path
) -> None:
    base, service = create_server
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile-first-deck"),
            headless=True,
            viewport={"width": 375, "height": 812},
        )
        page = context.pages[0]
        page.goto(f"{base}/app/")
        opener = page.locator("#no-decks").get_by_role(
            "button", name="Add your first deck", exact=True
        )
        dialog = page.locator("#deck-dialog")
        name = page.locator("#deck-name")
        submit = page.locator("#btn-create-deck")

        opener.click()
        expect(dialog).to_have_attribute("open", "")
        expect(name).to_be_focused()
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)
        expect(opener).to_be_focused()

        opener.press("Enter")
        expect(dialog).to_have_attribute("open", "")
        name.press_sequentially("First deck")
        dialog.get_by_role("radio", name="No languages").check()
        expect(submit).to_be_enabled()
        submit.click()
        expect(dialog).to_have_count(0)
        expect(page.locator("#no-decks")).to_have_count(0)
        expect(page.get_by_role("heading", name="First deck", level=3)).to_be_visible()
        expect(page.locator("#toast")).to_contain_text("Deck created")
        context.close()

    saved = asyncio.run(
        service.run(lambda col: [deck.name for deck in col.decks.all_names_and_ids()])
    )
    assert "First deck · 📚" in saved


@pytest.mark.parametrize("activation", ["Enter", "Space", "mouse", "touch"])
def test_suggested_flag_can_be_selected_without_losing_keyboard_focus(
    create_server: tuple[str, CollectionPort], tmp_path: Path, activation: str
) -> None:
    base, service = create_server
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(tmp_path / f"profile-flag-{activation}"),
            headless=True,
            viewport={"width": 375, "height": 812},
            has_touch=activation == "touch",
        )
        page = context.pages[0]
        page.goto(f"{base}/app/")
        page.locator("#btn-new-deck").click()
        dialog = page.locator("#deck-dialog")
        page.locator("#deck-name").press_sequentially("French")
        page.locator("#new-src").select_option("de")
        destination = page.locator("#new-dst")
        destination.select_option("fr")
        suggestion = page.locator("#new-flag-suggest")
        expect(suggestion).to_be_visible()
        expect(page.locator("#preview-emoji")).to_have_text("📚")

        if activation in ("Enter", "Space"):
            destination.focus()
            page.keyboard.press("Tab")
            expect(suggestion).to_be_focused()
            page.keyboard.press(activation)
            expect(dialog.get_by_role("tab", name="World")).to_be_focused()
        elif activation == "mouse":
            suggestion.click()
        else:
            suggestion.tap()

        expect(suggestion).to_be_hidden()
        expect(page.locator("#preview-emoji")).to_have_text("🇫🇷")
        expect(dialog.get_by_role("radio", name="🇫🇷")).to_be_checked()
        page.locator("#btn-create-deck").click()
        expect(dialog).to_have_count(0)
        context.close()

    saved = asyncio.run(
        service.run(lambda col: [deck.name for deck in col.decks.all_names_and_ids()])
    )
    assert "French · 🇫🇷" in saved


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_create_decks_in_browser(
    create_server: tuple[str, CollectionPort],
    tmp_path: Path,
    scheme: Literal["light", "dark"],
) -> None:
    base, service = create_server
    problems: list[str] = []
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(tmp_path / f"profile-{scheme}"),
            headless=True,
            viewport={"width": 375, "height": 812},
            color_scheme=scheme,
        )
        page = context.pages[0]

        def on_console(message: ConsoleMessage) -> None:
            if message.type == "error":
                problems.append(message.text)

        page.on("console", on_console)
        page.on("pageerror", lambda error: problems.append(str(error)))
        page.goto(f"{base}/app/")
        opener = page.locator("#btn-new-deck")
        dialog = page.locator("#deck-dialog")
        name = page.locator("#deck-name")
        submit = page.locator("#btn-create-deck")
        opener.click()
        expect(dialog).to_have_attribute("open", "")
        expect(name).to_be_focused()
        dna = dialog.get_by_role("radio", name="🧬")
        dna.locator("..").click()
        dialog.get_by_role("tab", name="Nature").click()
        dialog.get_by_role("tab", name="Study").click()
        expect(dna).to_be_checked()
        name.press_sequentially("Biology")
        dialog.get_by_role("radio", name="No languages").check()
        expect(submit).to_be_enabled()
        name.press("Enter")
        expect(dialog).to_have_count(0)
        expect(opener).to_be_focused()
        expect(page.locator("#toast")).to_contain_text("Deck created")
        expect(page.get_by_role("heading", name="Biology", level=3)).to_be_visible()

        opener.click()
        expect(name).to_have_value("")
        name.press_sequentially("biology")
        dialog.get_by_role("radio", name="No languages").check()
        expect(submit).to_be_enabled()
        submit.click()
        expect(page.locator("#deck-name-error")).to_contain_text("already exists")
        expect(dialog).to_have_attribute("open", "")
        expect(name).to_have_value("biology")
        expect(dialog.get_by_role("radio", name="No languages")).to_be_checked()
        name.press("ControlOrMeta+A")
        page.keyboard.insert_text("📚")
        expect(submit).to_be_enabled()
        submit.click()
        expect(page.locator("#deck-name-error")).to_contain_text("valid deck name")
        expect(name).to_have_value("📚")
        name.press("ControlOrMeta+A")
        name.press_sequentially("Biology two")
        dna.locator("..").click()
        expect(submit).to_be_enabled()
        submit.click()
        expect(dialog).to_have_count(0)
        expect(opener).to_be_focused()
        expect(page.get_by_role("heading", name="Biology two", level=3)).to_be_visible()

        search = page.locator("#deck-search")
        search.press_sequentially("biology two")
        expect(page.locator("article:visible h3")).to_have_text(["Biology two"])
        search.press("ControlOrMeta+A")
        search.press_sequentially("Fresh deck")
        empty_button = page.locator("#empty-new-deck")
        expect(empty_button).to_be_visible()
        empty_button.click()
        expect(name).to_have_value("Fresh deck")
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)
        expect(empty_button).to_be_focused()
        search.press("ControlOrMeta+A")
        search.press_sequentially("x" * 45)
        expect(empty_button).to_be_visible()
        empty_button.click()
        expect(name).to_have_value("x" * 40)
        page.keyboard.press("Escape")
        expect(empty_button).to_be_focused()
        assert page.evaluate("document.documentElement.scrollWidth") == 375
        context.close()
    assert problems == []

    def stored(col: Collection):
        return [
            (col.decks.name(DeckId(deck.id)), col.find_cards(f'deck:"{deck.name}"'))
            for deck in col.decks.all_names_and_ids()
            if deck.id != 1
        ]

    saved = asyncio.run(service.run(stored))
    assert sorted(name for name, _ in saved) == ["Biology two · 🧬", "Biology · 🧬"]
    assert all(cards == [] for _, cards in saved)
