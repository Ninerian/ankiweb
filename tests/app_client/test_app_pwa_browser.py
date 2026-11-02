"""Exercise the app journey and PWA in Chromium against a live server."""

import json
import re
import shutil
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from anki.collection import Collection
from fastapi import Request
from fastapi.responses import Response

from ankiweb.app import create_app
from ankiweb.core.config import Settings

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page, expect, sync_playwright


@pytest.fixture
def journey_deck(tmp_path: Path) -> int:
    # The shared live_app fixture opens this path after this fixture finishes.
    col = Collection(str(tmp_path / "live.anki2"))
    try:
        deck_id = col.decks.id("Journey deck")
        model = col.models.by_name("Basic")
        assert deck_id is not None and model is not None
        for index in range(3):
            note = col.new_note(model)
            note["Front"] = f"Journey question {index}"
            note["Back"] = f"Journey answer {index}"
            col.add_note(note, deck_id)
        return deck_id
    finally:
        col.close()


@pytest.fixture
def journey_app(journey_deck: int, request: pytest.FixtureRequest) -> tuple[str, int]:
    # Start the server only after the seeded collection has been closed.
    return request.getfixturevalue("live_app"), journey_deck


@pytest.fixture
def page() -> Iterator[Page]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": 375, "height": 812}, locale="en-US"
        )
        try:
            yield context.new_page()
        finally:
            context.close()
            browser.close()


@pytest.fixture
def versioned_app(tmp_path: Path) -> Iterator[tuple[str, Path, threading.Event]]:
    settings = Settings(
        collection_path=tmp_path / "versioned.anki2", shell_dir=tmp_path / "shell"
    )
    source = Settings(collection_path=tmp_path / "unused.anki2").shell_dir / "static"
    static = settings.shell_dir / "static"
    shutil.copytree(source, static)
    css = static / "app-client.css"
    original_css = css.read_text(encoding="utf-8")
    css.write_text(
        original_css + "\nbody { --pwa-test-build: v1; }\n", encoding="utf-8"
    )
    install = static / "app" / "install.js"
    install.write_text(
        install.read_text(encoding="utf-8") + "\nwindow.__pwaTestScript = 'v1';\n",
        encoding="utf-8",
    )

    app = create_app(settings)
    hold_worker = threading.Event()
    worker_v1 = ""

    @app.middleware("http")
    async def cache_and_hold_worker(request: Request, call_next):
        if request.url.path == "/app/service-worker.js" and hold_worker.is_set():
            return Response(
                worker_v1,
                media_type="application/javascript",
                headers={
                    "Cache-Control": "no-cache",
                    "Service-Worker-Allowed": "/app/",
                },
            )
        response = await call_next(request)
        if request.url.path == "/shell/static/app-client.css":
            response.headers["Cache-Control"] = "public, max-age=3600"
        return response

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        base = f"http://127.0.0.1:{listener.getsockname()[1]}"
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
            worker = httpx.get(f"{base}/app/service-worker.js", timeout=10)
            worker.raise_for_status()
            worker_v1 = worker.text
            yield base, css, hold_worker
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError("server did not stop")


def _app_css(page: Page) -> str:
    return (
        page.locator('link[href^="/shell/static/app-client.css"]').get_attribute("href")
        or ""
    )


def _build_marker(page: Page) -> str:
    return page.locator("body").evaluate(
        "(body) => getComputedStyle(body).getPropertyValue('--pwa-test-build').trim()"
    )


def _seed_http_cache(page: Page, base: str, css_url: str) -> None:
    outside = page.context.new_page()
    try:
        outside.goto(f"{base}/healthz")
        cached = outside.evaluate(
            """async url => {
              const response = await fetch(url, {cache: 'reload'});
              return {body: await response.text(),
                      cacheControl: response.headers.get('cache-control')};
            }""",
            css_url,
        )
        assert "--pwa-test-build: v1" in cached["body"]
        assert "max-age=3600" in cached["cacheControl"]
        assert "--pwa-test-build: v1" in outside.evaluate(
            "async url => (await fetch(url)).text()", css_url
        )
    finally:
        outside.close()


def _wait_for_app_worker(page: Page) -> None:
    page.wait_for_function(
        """() => {
          const worker = navigator.serviceWorker.controller;
          return worker?.state === 'activated' &&
            worker.scriptURL === new URL('/app/service-worker.js', location.origin).href;
        }"""
    )
    registration = page.evaluate(
        """async () => {
          const registration = await navigator.serviceWorker.getRegistration('/app/');
          return {
            activeScriptURL: registration?.active?.scriptURL ?? null,
            scope: registration?.scope ?? null,
            origin: location.origin,
          };
        }"""
    )
    assert registration["activeScriptURL"] == (
        f"{registration['origin']}/app/service-worker.js"
    )
    assert registration["scope"] == f"{registration['origin']}/app/"


def test_study_add_and_study_new_card(page: Page, journey_app: tuple[str, int]) -> None:
    base, deck_id = journey_app
    page.goto(f"{base}/app/")
    deck = page.locator(f"#deck-{deck_id}")
    new_count = deck.get_by_text(re.compile(r"^\d+ new$", re.IGNORECASE))
    expect(new_count).to_have_text(re.compile(r"^3 new$", re.IGNORECASE))

    deck.get_by_role("link", name="Learn Journey deck").click()
    expect(page).to_have_url(f"{base}/app/review?deck={deck_id}")
    seen: set[str] = set()
    for index in range(3):
        question = page.locator("#card-q")
        expect(question).to_contain_text("Journey question")
        question_text = question.inner_text()
        seen.add(question_text)
        page.locator("#btn-show-ans").click()
        page.locator("#ease-4").click()
        expect(page.locator("#streak-count")).to_have_text(str(index + 1))
        if index < 2:
            expect(question).not_to_have_text(question_text)
    assert len(seen) == 3
    expect(page.locator("#session-complete")).to_be_visible()

    page.locator("#hud-progress").get_by_role("link", name="Back to decks").click()
    expect(page).to_have_url(f"{base}/app/")
    expect(new_count).to_have_text(re.compile(r"^0 new$", re.IGNORECASE))
    deck.get_by_role("link", name="Edit / Add").click()
    expect(page).to_have_url(f"{base}/app/add?deck={deck_id}")

    front = page.get_by_label("Front (Question / Prompt)", exact=True)
    front.fill("New journey card")
    front.press("Enter")
    back = page.get_by_label("Back (Answer / Meaning)", exact=True)
    expect(back).to_be_visible()
    back.fill("New journey answer")
    back.press("Enter")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(page.locator("#added-cards")).to_contain_text("New journey card")
    page.get_by_role("button", name="Done", exact=True).click()
    summary = page.get_by_role("dialog")
    expect(summary).to_be_visible()
    summary.get_by_role("link", name="Start studying", exact=True).click()
    expect(page).to_have_url(f"{base}/app/review?deck={deck_id}")
    expect(page.locator("#card-q")).to_contain_text("New journey card")


def test_app_script_updates_before_worker_upgrade(
    page: Page, versioned_app: tuple[str, Path, threading.Event]
) -> None:
    base, css, hold_worker = versioned_app
    install = css.parent / "app" / "install.js"
    page.goto(f"{base}/app/")
    _wait_for_app_worker(page)
    hold_worker.set()

    script_response = re.compile(r"/shell/static/app/install\.js(?:\?.*)?$")
    with page.expect_response(script_response) as first_response:
        page.reload()
    assert first_response.value.from_service_worker
    assert page.evaluate("window.__pwaTestScript") == "v1"
    assert _build_marker(page) == "v1"
    assert page.evaluate(
        """async () => {
          const script = document.querySelector(
            'script[src^="/shell/static/app/install.js"]'
          );
          return !!(await caches.match(script.src));
        }"""
    )
    old_caches = page.evaluate("() => caches.keys()")
    assert any(name.startswith("ankiweb-app-") for name in old_caches)
    css_v1 = css.read_text(encoding="utf-8")
    js_v1 = install.read_text(encoding="utf-8")
    js_v2 = js_v1.replace(
        "window.__pwaTestScript = 'v1';", "window.__pwaTestScript = 'v2';"
    )
    assert js_v2 != js_v1
    install.write_text(js_v2, encoding="utf-8")

    with page.expect_response(script_response) as second_response:
        page.goto(f"{base}/app/")
    assert page.evaluate("window.__pwaTestScript") == "v2"
    assert second_response.value.from_service_worker
    assert _build_marker(page) == "v1"
    assert css.read_text(encoding="utf-8") == css_v1
    assert page.evaluate("() => caches.keys()") == old_caches


def test_versioned_assets_update_without_losing_draft(
    page: Page, versioned_app: tuple[str, Path, threading.Event]
) -> None:
    base, css, hold_worker = versioned_app
    page.goto(f"{base}/app/")
    _wait_for_app_worker(page)
    assert _build_marker(page) == "v1"
    old_app_caches = [
        name
        for name in page.evaluate("() => caches.keys()")
        if name.startswith("ankiweb-app-")
    ]
    assert len(old_app_caches) == 1
    old_cache = old_app_caches[0]
    css_v1 = css.read_text(encoding="utf-8")
    css_v2 = css_v1.replace("--pwa-test-build: v1", "--pwa-test-build: v2")
    assert css_v1 != css_v2

    # Keep the actual v1 worker installed while the deployed assets change.
    hold_worker.set()
    css.write_text(css_v2, encoding="utf-8")
    offline = httpx.get(f"{base}/app/offline", timeout=10)
    offline.raise_for_status()
    expected_css = re.search(
        r"/shell/static/app-client\.css(?:\?v=[0-9a-f]{12})?", offline.text
    )
    assert expected_css is not None
    css.write_text(css_v1, encoding="utf-8")
    _seed_http_cache(page, base, expected_css.group())
    css.write_text(css_v2, encoding="utf-8")
    page.goto(f"{base}/app/add?deck=1")
    _wait_for_app_worker(page)
    assert _build_marker(page) == "v2"
    css_v2_url = _app_css(page)
    front = page.get_by_label("Front (Question / Prompt)", exact=True)
    front.fill("unsaved draft")

    # Poison the browser HTTP cache for the v2 URL from outside worker scope.
    # Installation must bypass that fresh max-age response, not seed it offline.
    css.write_text(css_v1, encoding="utf-8")
    try:
        _seed_http_cache(page, base, css_v2_url)
    finally:
        css.write_text(css_v2, encoding="utf-8")

    # Drain any load-time check against v1, then resume the still-open document.
    page.evaluate(
        """async () => {
          const registration = await navigator.serviceWorker.getRegistration('/app/');
          await registration.update();
          window.__oldWorker = navigator.serviceWorker.controller;
        }"""
    )
    hold_worker.clear()
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_function(
        "() => navigator.serviceWorker.controller !== window.__oldWorker && "
        "navigator.serviceWorker.controller?.state === 'activated'"
    )
    _wait_for_app_worker(page)
    expect(front).to_have_value("unsaved draft")
    assert old_cache not in page.evaluate("() => caches.keys()")
    other_page = page.context.new_page()
    try:
        other_page.goto(f"{base}/app/")
        assert _build_marker(other_page) == "v2"
        expect(front).to_have_value("unsaved draft")

        page.context.set_offline(True)
        response = other_page.goto(f"{base}/app/")
        assert response is not None and response.status == 200
        expect(other_page.get_by_role("heading", name="You're offline")).to_be_visible()
        assert _build_marker(other_page) == "v2"
    finally:
        page.context.set_offline(False)
        other_page.close()


def test_worker_controls_app_and_offline_retry(page: Page, live_app: str) -> None:
    page.goto(f"{live_app}/app/")
    expect(page.get_by_role("heading", name="My Decks")).to_be_visible()
    _wait_for_app_worker(page)

    page.context.set_offline(True)
    try:
        response = page.goto(f"{live_app}/app/")
        assert response is not None and response.status == 200
        expect(page.get_by_role("heading", name="You're offline")).to_be_visible()
        expect(page.get_by_role("heading", name="My Decks")).to_have_count(0)
        retry = page.get_by_role("link", name="Try again")
        expect(retry).to_have_attribute("href", "/app/")
        page.context.set_offline(False)
        retry.click()
        expect(page).to_have_url(f"{live_app}/app/")
        expect(page.get_by_role("heading", name="My Decks")).to_be_visible()
    finally:
        page.context.set_offline(False)


def test_chromium_reports_app_installable(page: Page, live_app: str) -> None:
    page.goto(f"{live_app}/app/")
    _wait_for_app_worker(page)
    session = page.context.new_cdp_session(page)
    try:
        installability = session.send("Page.getInstallabilityErrors")
        manifest = session.send("Page.getAppManifest")
        assert installability["installabilityErrors"] == []
        assert manifest["errors"] == []
        assert manifest["url"] == f"{live_app}/app/manifest.webmanifest"
        data = json.loads(manifest["data"])
        assert data["id"] == data["scope"] == data["start_url"] == "/app/"
    finally:
        session.detach()
