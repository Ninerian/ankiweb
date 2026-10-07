import threading
import time
from pathlib import Path

import pytest
import uvicorn
from anki.collection import Collection

from ankiweb.app import create_app
from ankiweb.core.config import Settings

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright


@pytest.fixture
def live_server_cs(tmp_path: Path):
    col_path = tmp_path / "c.anki2"
    col = Collection(str(col_path))
    try:
        did = col.decks.id("Default")
        assert did is not None
        col.decks.set_current(did)
        for i in range(3):
            nt = col.models.by_name("Basic")
            assert nt is not None
            n = col.new_note(nt)
            n["Front"] = f"f{i}"
            n["Back"] = f"b{i}"
            col.add_note(n, did)
    finally:
        col.close()
    settings = Settings(collection_path=col_path, port=8133)
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings), host="127.0.0.1", port=8133, log_level="warning"
        )
    )
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("server did not start")
        time.sleep(0.05)
    yield "http://127.0.0.1:8133"
    server.should_exit = True
    t.join(timeout=5)


def test_custom_study_form_submits_and_navigates(live_server_cs):
    url = live_server_cs
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{url}/custom-study")
        page.wait_for_selector("#go", timeout=10000)
        assert "Custom Study" in page.inner_text("body")
        page.check("input[name='r'][value='6']")
        page.click("#go")
        page.wait_for_url("**/overview", timeout=10000)
        assert not errors, errors
        browser.close()
