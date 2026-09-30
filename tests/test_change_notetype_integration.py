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
def live_server_cnt(tmp_path: Path):
    col_path = tmp_path / "c.anki2"
    col = Collection(str(col_path))
    try:
        basic_nt = col.models.by_name("Basic")
        assert basic_nt is not None
        old = basic_nt["id"]
        m = col.models.get(old)
        assert m is not None
        n = col.new_note(m)
        n["Front"] = "x"
        n["Back"] = "y"
        did = col.decks.id("Default")
        assert did is not None
        col.add_note(n, did)
    finally:
        col.close()
    settings = Settings(collection_path=col_path, port=8132)
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings), host="127.0.0.1", port=8132, log_level="warning"
        )
    )
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("server did not start")
        time.sleep(0.05)
    yield "http://127.0.0.1:8132", old
    server.should_exit = True
    t.join(timeout=5)


def test_change_notetype_page_boots(live_server_cnt):
    url, old = live_server_cnt
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{url}/change-notetype/{old}")
        page.wait_for_selector("#target-notetype-select", timeout=10000)
        page.wait_for_selector("#change-notetype-save-btn", timeout=10000)
        assert not errors, errors
        # Verify concrete page content rendered
        assert page.locator("#target-notetype-select").is_visible()
        assert page.locator("#change-notetype-save-btn").is_visible()
        browser.close()
