import threading
import time
import pytest
import uvicorn
from pathlib import Path
from anki.collection import Collection
from ankiweb.core.config import Settings
from ankiweb.app import create_app

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright


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
