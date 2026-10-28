import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

from ankiweb.app import create_app
from ankiweb.core.config import Settings

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page, sync_playwright

ASSET = "/shell/static/probe.css"
READ_ASSET = f"fetch('{ASSET}').then(r => r.text())"


@pytest.fixture
def pwa_server(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    shell = tmp_path / "shell"
    (shell / "static").mkdir(parents=True)
    asset = shell / "static" / "probe.css"
    asset.write_text("build-1")
    settings = Settings(collection_path=tmp_path / "c.anki2", shell_dir=shell)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(create_app(settings), log_level="warning")
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
            yield f"http://127.0.0.1:{port}", asset
        finally:
            server.should_exit = True
            thread.join(timeout=10)


def _controlled_page(page: Page, base: str) -> None:
    page.goto(f"{base}/healthz")
    page.evaluate(
        "navigator.serviceWorker.register('/service-worker.js', {scope: '/'})"
        ".then(() => navigator.serviceWorker.ready)"
    )
    page.wait_for_function("navigator.serviceWorker.controller !== null")


def test_rebuilt_static_asset_is_served_fresh(
    pwa_server: tuple[str, Path],
) -> None:
    base, asset = pwa_server
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        _controlled_page(page, base)
        assert page.evaluate(READ_ASSET) == "build-1"
        asset.write_text("build-2")
        assert page.evaluate(READ_ASSET) == "build-2"
        browser.close()


def test_static_asset_is_served_from_cache_offline(
    pwa_server: tuple[str, Path],
) -> None:
    base, _asset = pwa_server
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context()
        page = context.new_page()
        _controlled_page(page, base)
        assert page.evaluate(READ_ASSET) == "build-1"
        context.set_offline(True)
        assert page.evaluate(READ_ASSET) == "build-1"
        browser.close()
