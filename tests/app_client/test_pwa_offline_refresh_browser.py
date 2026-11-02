"""Exercise offline-page updates in an installed worker against isolated apps."""

import shutil
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import jinja2
import pytest
import uvicorn
from starlette.types import Receive, Scope, Send

from ankiweb.adapters.inbound.http_app.pwa import build_hash
from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.app import create_app
from ankiweb.core.auth import COOKIE, auth_token
from ankiweb.core.config import Settings

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright


@pytest.fixture
def language_app(tmp_path: Path) -> Iterator[tuple[str, threading.Event, Path, str]]:
    shell = tmp_path / "shell"
    source = Settings(collection_path=tmp_path / "unused.anki2").shell_dir / "static"
    shutil.copytree(source, shell / "static")
    password = f"offline-{tmp_path.name}"
    settings = {
        lang: Settings(
            collection_path=tmp_path / f"{lang}.anki2",
            shell_dir=shell,
            lang=lang,
            password=password,
        )
        for lang in ("en", "de")
    }
    english = create_app(settings["en"])
    german = create_app(settings["de"])
    use_german = threading.Event()

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        # The German app serves only public PWA/static resources after the switch.
        target = (
            german if use_german.is_set() and scope["type"] != "lifespan" else english
        )
        await target(scope, receive, send)

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
            yield base, use_german, shell / "static", password
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError("server did not stop")


@pytest.fixture
def offline_template(
    language_app: tuple[str, threading.Event, Path, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[tuple[str, threading.Event, Path, str], Path]]:
    template = tmp_path / "templates" / "app" / "offline.html.jinja"
    template.parent.mkdir(parents=True)
    original_loader = templating._env.loader
    assert original_loader is not None
    source, _, _ = original_loader.get_source(templating._env, "app/offline.html.jinja")
    template.write_text(source, encoding="utf-8")
    monkeypatch.setattr(
        templating._env,
        "loader",
        jinja2.ChoiceLoader(
            [jinja2.FileSystemLoader(template.parents[1]), original_loader]
        ),
    )
    if templating._env.cache is not None:
        templating._env.cache.clear()
    try:
        yield language_app, template
    finally:
        if templating._env.cache is not None:
            templating._env.cache.clear()


def test_installed_worker_refreshes_localized_offline_page(
    language_app: tuple[str, threading.Event, Path, str],
) -> None:
    base, use_german, static_dir, password = language_app
    asset_version = build_hash(static_dir)
    asset_url = f"/shell/static/app-client.css?v={asset_version}"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(locale="en-US")
        try:
            context.add_cookies(
                [
                    {
                        "name": COOKIE,
                        "value": auth_token(password),
                        "url": base,
                    }
                ]
            )
            page = context.new_page()
            page.goto(f"{base}/app/")
            expect(page.get_by_role("heading", name="My Decks")).to_be_visible()
            page.wait_for_function(
                """() => {
                  const worker = navigator.serviceWorker.controller;
                  return worker?.state === 'activated' &&
                    worker.scriptURL === new URL('/app/service-worker.js', location.origin).href;
                }"""
            )
            old_cache = page.evaluate(
                """async () => {
                  const names = (await caches.keys()).filter(name => name.startsWith('ankiweb-app-'));
                  if (names.length !== 1) throw new Error('expected one app cache');
                  await caches.open('ankiweb-shell-v1');
                  await caches.open('unrelated-cache');
                  return names[0];
                }"""
            )

            context.set_offline(True)
            try:
                response = page.goto(f"{base}/app/review")
                assert response is not None and response.status == 200
                expect(
                    page.get_by_role("heading", name="You're offline")
                ).to_be_visible()
                english_css = page.locator('link[rel="stylesheet"]').get_attribute(
                    "href"
                )
                assert english_css == asset_url
            finally:
                context.set_offline(False)
            page.goto(f"{base}/app/")
            expect(page.get_by_role("heading", name="My Decks")).to_be_visible()

            use_german.set()
            assert build_hash(static_dir) == asset_version

            page.evaluate(
                """async () => {
                  window.offlineRefreshControllerChanged = false;
                  navigator.serviceWorker.addEventListener('controllerchange', () => {
                    window.offlineRefreshControllerChanged = true;
                  }, {once: true});
                  const registration = await navigator.serviceWorker.getRegistration('/app/');
                  if (!registration) throw new Error('app worker not registered');
                  await registration.update();
                }"""
            )
            page.wait_for_function(
                "() => window.offlineRefreshControllerChanged === true && "
                "navigator.serviceWorker.controller?.state === 'activated'"
            )
            cache_info = page.evaluate(
                """async () => {
                  const names = await caches.keys();
                  const appNames = names.filter(name => name.startsWith('ankiweb-app-'));
                  if (appNames.length !== 1) throw new Error('expected one app cache');
                  const cache = await caches.open(appNames[0]);
                  return {names, appName: appNames[0], paths: (await cache.keys()).map(
                    request => new URL(request.url).pathname)};
                }"""
            )
            assert cache_info["appName"] != old_cache
            assert old_cache not in cache_info["names"]
            assert "ankiweb-shell-v1" in cache_info["names"]
            assert "unrelated-cache" in cache_info["names"]
            assert "/app/offline" in cache_info["paths"]
            assert "/app/" not in cache_info["paths"]
            assert "/app/review" not in cache_info["paths"]
            assert all(
                path == "/app/offline" or path.startswith("/shell/static/app")
                for path in cache_info["paths"]
            )

            context.set_offline(True)
            try:
                response = page.goto(f"{base}/app/review")
                assert response is not None and response.status == 200
                expect(
                    page.get_by_role("heading", name="Du bist offline")
                ).to_be_visible()
                expect(
                    page.get_by_role("heading", name="You're offline")
                ).to_have_count(0)
                assert (
                    page.locator('link[rel="stylesheet"]').get_attribute("href")
                    == english_css
                )
            finally:
                context.set_offline(False)
        finally:
            context.close()
            browser.close()


def test_installed_worker_refreshes_changed_offline_template(
    offline_template: tuple[tuple[str, threading.Event, Path, str], Path],
) -> None:
    (base, _, static_dir, password), template = offline_template
    asset_version = build_hash(static_dir)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(locale="en-US")
        try:
            context.add_cookies(
                [{"name": COOKIE, "value": auth_token(password), "url": base}]
            )
            page = context.new_page()
            page.goto(f"{base}/app/")
            expect(page.get_by_role("heading", name="My Decks")).to_be_visible()
            page.wait_for_function(
                """() => {
                  const worker = navigator.serviceWorker.controller;
                  return worker?.state === 'activated' &&
                    worker.scriptURL === new URL('/app/service-worker.js', location.origin).href;
                }"""
            )
            old_cache = page.evaluate(
                """async () => {
                  const names = (await caches.keys()).filter(name => name.startsWith('ankiweb-app-'));
                  if (names.length !== 1) throw new Error('expected one app cache');
                  return names[0];
                }"""
            )

            context.set_offline(True)
            try:
                response = page.goto(f"{base}/app/review")
                assert response is not None and response.status == 200
                expect(
                    page.get_by_role("heading", name="You're offline")
                ).to_be_visible()
                expect(page.get_by_text("Offline page revision two")).to_have_count(0)
                css_url = page.locator('link[rel="stylesheet"]').get_attribute("href")
                assert css_url == f"/shell/static/app-client.css?v={asset_version}"
            finally:
                context.set_offline(False)
            page.goto(f"{base}/app/")
            expect(page.get_by_role("heading", name="My Decks")).to_be_visible()

            template.write_text(
                template.read_text(encoding="utf-8").replace(
                    "</section>", "<p>Offline page revision two</p></section>"
                ),
                encoding="utf-8",
            )
            # Emulate a deployment restarting with a newly rendered template.
            if templating._env.cache is not None:
                templating._env.cache.clear()
            assert build_hash(static_dir) == asset_version
            page.evaluate(
                """async () => {
                  window.offlineRefreshControllerChanged = false;
                  navigator.serviceWorker.addEventListener('controllerchange', () => {
                    window.offlineRefreshControllerChanged = true;
                  }, {once: true});
                  const registration = await navigator.serviceWorker.getRegistration('/app/');
                  if (!registration) throw new Error('app worker not registered');
                  await registration.update();
                }"""
            )
            page.wait_for_function(
                "() => window.offlineRefreshControllerChanged === true && "
                "navigator.serviceWorker.controller?.state === 'activated'"
            )
            app_caches = page.evaluate(
                """async () => (await caches.keys()).filter(
                  name => name.startsWith('ankiweb-app-'))"""
            )
            assert len(app_caches) == 1
            assert old_cache not in app_caches

            context.set_offline(True)
            try:
                response = page.goto(f"{base}/app/review")
                assert response is not None and response.status == 200
                expect(
                    page.get_by_role("heading", name="You're offline")
                ).to_be_visible()
                expect(page.get_by_text("Offline page revision two")).to_be_visible()
                assert (
                    page.locator('link[rel="stylesheet"]').get_attribute("href")
                    == css_url
                )
            finally:
                context.set_offline(False)
        finally:
            context.close()
            browser.close()
