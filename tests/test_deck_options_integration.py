import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from anki.collection import Collection

from ankiweb.app import create_app
from ankiweb.core.config import Settings

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright


@pytest.fixture
def live_server_dopts(tmp_path: Path):
    col_path = tmp_path / "d.anki2"
    col = Collection(str(col_path))
    try:
        nt = col.models.by_name("Basic")
        assert nt is not None
        n = col.new_note(nt)
        n["Front"] = "x"
        n["Back"] = "y"
        did = col.decks.id("Default")
        assert did is not None
        col.add_note(n, did)
    finally:
        col.close()
    settings = Settings(collection_path=col_path, port=8131)
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings), host="127.0.0.1", port=8131, log_level="warning"
        )
    )
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("server did not start")
        time.sleep(0.05)
    yield "http://127.0.0.1:8131", did
    server.should_exit = True
    t.join(timeout=5)


def test_deck_options_page_boots(live_server_dopts):
    url, did = live_server_dopts
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{url}/deck-options/{did}")
        page.wait_for_selector("#presetSelector", timeout=10000)
        page.wait_for_selector(".tab-pane", timeout=10000)
        assert not errors, errors
        # Concrete assertion: Preset selector exists and Daily limits section rendered
        assert page.locator("#presetSelector").is_visible()
        assert page.locator("button.tab", has_text="Daily Limits").is_visible()
        browser.close()


def test_dirty_close_cancel_escape_and_discard_preserve_new_cards_value(
    live_server_dopts,
):
    url, did = live_server_dopts
    options_url = f"{url}/deck-options/{did}"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(options_url)

        new_per_day = page.locator('[data-bind="cfg.new_per_day"]')
        expect(new_per_day).to_be_visible()
        original = new_per_day.input_value()
        changed = "1" if original != "1" else "2"
        new_per_day.fill(changed)
        expect(new_per_day).to_have_value(changed)

        close_link = page.get_by_role("link", name="Close")
        discard_link = page.get_by_role("link", name="Discard changes and close")
        close_dialog = page.get_by_role("dialog", name="Unsaved changes")

        close_link.click()
        expect(close_dialog).to_be_visible()
        close_dialog.get_by_role("button", name="Keep editing").click()
        expect(close_dialog).not_to_be_visible()
        expect(page).to_have_url(options_url)
        expect(new_per_day).to_have_value(changed)

        close_link.click()
        expect(close_dialog).to_be_visible()
        page.keyboard.press("Escape")
        expect(close_dialog).not_to_be_visible()
        expect(page).to_have_url(options_url)
        expect(new_per_day).to_have_value(changed)

        close_link.click()
        expect(close_dialog).to_be_visible()
        discard_link.click()
        expect(page).to_have_url(f"{url}/deckbrowser")

        page.goto(options_url)
        expect(new_per_day).to_have_value(original)
        browser.close()


def test_clean_close_and_modified_close_keep_native_navigation(live_server_dopts):
    url, did = live_server_dopts
    options_url = f"{url}/deck-options/{did}"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(options_url)

        close_link = page.get_by_role("link", name="Close")
        close_link.click()
        expect(page).to_have_url(f"{url}/deckbrowser")

        page.goto(options_url)
        new_per_day = page.locator('[data-bind="cfg.new_per_day"]')
        expect(new_per_day).to_be_visible()
        original = new_per_day.input_value()
        changed = "1" if original != "1" else "2"
        new_per_day.fill(changed)
        expect(new_per_day).to_have_value(changed)

        close_dialog = page.get_by_role("dialog", name="Unsaved changes")
        modifier = "Meta" if sys.platform == "darwin" else "Control"
        with page.context.expect_page() as page_info:
            close_link.click(modifiers=[modifier])
        new_tab = page_info.value

        expect(new_tab).to_have_url(f"{url}/deckbrowser")
        expect(page).to_have_url(options_url)
        expect(new_per_day).to_have_value(changed)
        expect(close_dialog).not_to_be_visible()
        new_tab.close()
        browser.close()
