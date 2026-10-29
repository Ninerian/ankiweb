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
        page.wait_for_load_state("networkidle")
        opener = page.locator("#btn-new-deck")
        sheet = page.locator("#deck-sheet")
        name = page.locator("#deck-name")
        submit = page.locator("#btn-create-deck")
        opener.click()
        expect(sheet).to_have_attribute("aria-hidden", "false")
        expect(name).to_be_focused()
        expect(submit).to_be_disabled()
        dna = page.get_by_role("radio", name="🧬")
        dna.locator("..").click()
        expect(dna).to_be_checked()
        page.get_by_role("tab", name="Nature").click()
        page.get_by_role("tab", name="Study").click()
        expect(dna).to_be_checked()
        name.fill("Biology")
        if scheme == "light":
            page.screenshot(
                path=str(
                    Path(__file__).resolve().parents[2]
                    / "design/reviewer-redesign/screenshot-decks-new-deck.png"
                )
            )
        name.press("Enter")
        expect(sheet).to_have_attribute("aria-hidden", "true")
        expect(opener).to_be_focused()
        expect(page.locator("#toast")).to_contain_text("Deck created")
        expect(page.locator("article h3").filter(has_text="Biology")).to_be_visible()

        opener.click()
        name.fill("biology")
        submit.click()
        expect(page.locator("#deck-name-error")).to_contain_text("already exists")
        expect(sheet).to_have_attribute("aria-hidden", "false")
        name.fill("")
        expect(submit).to_be_disabled()
        name.fill("📚")
        assert problems == []
        expect(sheet).to_have_attribute("aria-hidden", "false")
        expect(submit).to_be_enabled()
        submit.click()
        expect(page.locator("#deck-name-error")).to_contain_text("valid deck name")
        name.fill("Biology two")
        dna.locator("..").click()
        expect(dna).to_be_checked()
        submit.click()
        expect(sheet).to_have_attribute("aria-hidden", "true")
        expect(opener).to_be_focused()
        expect(
            page.locator("article h3").filter(has_text="Biology two")
        ).to_be_visible()

        search = page.locator("#deck-search")
        search.fill("biology two")
        expect(page.locator("#empty-state")).to_be_hidden()
        expect(page.locator("article:visible h3")).to_have_text(["Biology two"])
        search.fill("Fresh deck")
        empty_button = page.locator("#empty-new-deck")
        expect(empty_button).to_be_visible()
        empty_button.click()
        expect(name).to_have_value("Fresh deck")
        page.keyboard.press("Escape")
        expect(sheet).to_have_attribute("aria-hidden", "true")
        expect(empty_button).to_be_focused()
        search.fill("x" * 45)
        empty_button.click()
        expect(name).to_have_value("x" * 40)
        page.keyboard.press("Escape")
        expect(empty_button).to_be_focused()
        search.fill("")
        assert page.evaluate("document.documentElement.scrollWidth") == 375
        context.close()
    assert problems == []

    def stored(col: Collection):
        found = [
            deck
            for deck in col.decks.all_names_and_ids()
            if deck.name.startswith("Biology")
        ]
        return [
            (col.decks.name(DeckId(deck.id)), col.find_cards(f'deck:"{deck.name}"'))
            for deck in found
        ]

    saved = asyncio.run(service.run(stored))
    assert sorted(name for name, _ in saved) == ["Biology two · 🧬", "Biology · 🧬"]
    assert all(cards == [] for _, cards in saved)


def test_migration_refreshes_the_visible_list(
    create_server: tuple[str, CollectionPort], tmp_path: Path
) -> None:
    base, service = create_server
    deck_id = asyncio.run(
        service.run(lambda col: col.decks.add_normal_deck_with_name("🧬 Legacy").id)
    )
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(tmp_path / "migration-profile"),
            headless=True,
            viewport={"width": 375, "height": 812},
        )
        page = context.pages[0]
        page.goto(f"{base}/app/")
        page.get_by_role("button", name="Review changes").click()
        page.get_by_role("button", name="Rename", exact=True).click()
        row = page.locator(f"#deck-{deck_id}")
        expect(row.locator("h3")).to_have_text("Legacy")
        expect(row.locator("span").first).to_have_text("🧬")
        context.close()
