import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

import pytest
import uvicorn
from anki.collection import Collection

from ankiweb.app import create_app
from ankiweb.core.config import Settings

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import ConsoleMessage, expect, sync_playwright

DECKS = (
    "German B1 Vocab · 🇩🇪",
    "Spanish A2 · 🇪🇸",
    "Biology Cells · 🧬",
    "History 1900s · 🏛️",
    "Chemistry Basics · ⚗️",
)


@pytest.fixture
def decks_server(tmp_path: Path) -> Iterator[tuple[str, dict[str, int]]]:
    path = tmp_path / "browser.anki2"
    col = Collection(str(path))
    try:
        model = col.models.by_name("Basic")
        assert model is not None
        for name in DECKS:
            deck_id = col.decks.id(name)
            assert deck_id is not None
            note = col.new_note(model)
            note["Front"] = name
            col.add_note(note, deck_id)
        ids = {node.name: node.deck_id for node in col.sched.deck_due_tree().children}
    finally:
        col.close()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                create_app(Settings(collection_path=path)), log_level="warning"
            )
        )
        thread = threading.Thread(
            target=server.run, kwargs={"sockets": [listener]}, daemon=True
        )
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if time.monotonic() > deadline:
                    raise RuntimeError("server did not start")
                time.sleep(0.05)
            yield f"http://127.0.0.1:{port}", ids
        finally:
            server.should_exit = True
            thread.join(timeout=10)


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_deck_list_search_and_links(
    decks_server: tuple[str, dict[str, int]], scheme: Literal["light", "dark"]
) -> None:
    base, ids = decks_server
    problems: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(
            viewport={"width": 375, "height": 812}, color_scheme=scheme
        )

        def on_console(message: ConsoleMessage) -> None:
            if message.type == "error":
                problems.append(message.text)

        page.on("console", on_console)
        page.on("pageerror", lambda e: problems.append(str(e)))
        page.goto(f"{base}/app/")
        page.wait_for_selector("#deck-search")
        page.wait_for_load_state("networkidle")
        assert page.locator("article:visible").count() == 5

        requests: list[str] = []
        page.on("request", lambda r: requests.append(r.url))
        page.fill("#deck-search", "bio")
        page.wait_for_function(
            "document.querySelectorAll('article:not([style*=none])').length === 1"
        )
        assert page.locator("article:visible h3").all_inner_texts() == ["Biology Cells"]
        assert not page.locator("#empty-state").is_visible()

        page.fill("#deck-search", "zzz")
        page.wait_for_selector("#empty-state", state="visible")
        assert page.locator("article:visible").count() == 0

        page.fill("#deck-search", "")
        page.wait_for_selector("#empty-state", state="hidden")
        assert page.locator("article:visible").count() == 5
        assert requests == []

        deck_id = ids["German B1 Vocab · 🇩🇪"]
        learn = page.locator(f"#deck-{deck_id} a").first
        assert learn.get_attribute("href") == f"/app/review?deck={deck_id}"
        edit = page.locator(f"#deck-{deck_id}").get_by_role(
            "link", name="Edit", exact=True
        )
        assert edit.get_attribute("href") == f"/app/edit?deck={deck_id}"
        assert page.evaluate("document.documentElement.scrollWidth") == 375
        browser.close()
    assert problems == []


def test_deck_overview_initializes_before_and_after_editor_navigation(
    decks_server: tuple[str, dict[str, int]],
) -> None:
    base, ids = decks_server
    problems: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 375, "height": 812})

        def on_console(message: ConsoleMessage) -> None:
            if message.type == "error":
                problems.append(f"console: {message.text}")

        def check_deck_sheet() -> None:
            page.wait_for_load_state("networkidle")
            opener = page.locator("#btn-new-deck")
            sheet = page.locator("#deck-sheet")
            expect(sheet).to_have_attribute("aria-hidden", "true")
            expect(opener).not_to_be_focused()
            opener.click()
            expect(sheet).to_have_attribute("aria-hidden", "false")
            expect(page.locator("#deck-name")).to_be_focused()
            page.keyboard.press("Escape")
            expect(sheet).to_have_attribute("aria-hidden", "true")
            expect(opener).to_be_focused()

        page.on("console", on_console)
        page.on("pageerror", lambda error: problems.append(f"pageerror: {error}"))
        page.goto(f"{base}/app/")
        check_deck_sheet()
        assert problems == []

        deck_id = ids["German B1 Vocab · 🇩🇪"]
        page.locator(f"#deck-{deck_id}").get_by_role(
            "link", name="Edit", exact=True
        ).click()
        expect(page).to_have_url(f"{base}/app/edit?deck={deck_id}")
        expect(page.locator("#input-front")).to_be_visible()
        page.wait_for_load_state("networkidle")
        assert problems == []

        page.locator("#edit-back").click()
        expect(page).to_have_url(f"{base}/app/")
        check_deck_sheet()
        assert problems == []

        page.goto(f"{base}/app/edit?deck={deck_id}&view=cards")
        cards = page.locator("#deck-cards")
        expect(cards).to_be_visible()
        expect(cards).to_be_focused()
        page.wait_for_load_state("networkidle")
        expect(cards).to_be_focused()
        assert problems == []
        browser.close()
