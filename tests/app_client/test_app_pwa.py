import json
import re
import shutil
import subprocess  # noqa: S404 - runs a fixed Bun test harness
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ankiweb.adapters.inbound.http_app.pwa import (
    APP_THEME_COLOR_DARK,
    APP_THEME_COLOR_LIGHT,
)
from ankiweb.app import create_app
from ankiweb.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]
SOURCE_CSS = ROOT / "shell_src/app-client.css"
BUN = shutil.which("bun")


class _Head(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("link", "meta"):
            self.tags.append((tag, dict(attrs)))


def test_pwa_assets_are_public_but_app_remains_password_protected(
    tmp_path: Path,
) -> None:
    password = f"test-{tmp_path.name}"
    settings = Settings(collection_path=tmp_path / "private.anki2", password=password)
    with TestClient(create_app(settings)) as client:
        for path in (
            "/app/manifest.webmanifest",
            "/app/service-worker.js",
            "/app/offline",
            "/manifest.webmanifest",
            "/service-worker.js",
        ):
            assert client.get(path, follow_redirects=False).status_code == 200, path
        assert client.get("/healthz", follow_redirects=False).status_code == 200
        assert client.get("/login", follow_redirects=False).status_code == 200
        assert client.get("/app/login", follow_redirects=False).status_code == 200
        logout = client.get("/logout", follow_redirects=False)
        assert logout.status_code == 303 and logout.headers["location"] == "/login"
        assert (
            client.get("/shell/static/datastar.js", follow_redirects=False).status_code
            == 200
        )
        for path in ("/app/", "/app/review", "/app/add?deck=1"):
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 303, path
            assert response.headers["location"] == "/app/login"

        offline = client.get("/app/offline")
        assert "text/html" in offline.headers["content-type"]
        assert "/shell/static/app-client.css" in offline.text
        assert 'href="/app/"' in offline.text


def test_manifest_identities_and_icon_assets(client: TestClient) -> None:
    response = client.get("/app/manifest.webmanifest")
    assert response.status_code == 200
    assert response.headers["content-type"].split(";")[0] == "application/manifest+json"
    manifest = response.json()
    assert manifest["name"] == "AnkiWeb"
    assert manifest["short_name"] == "Anki"
    assert manifest["id"] == manifest["scope"] == manifest["start_url"] == "/app/"
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"] == manifest["background_color"]
    assert manifest["theme_color"] == APP_THEME_COLOR_LIGHT

    old = client.get("/manifest.webmanifest")
    assert old.status_code == 200
    old_manifest = old.json()
    assert old_manifest["id"] == old_manifest["scope"] == old_manifest["start_url"]
    assert old_manifest["scope"] == "/"
    assert {icon["sizes"] for icon in manifest["icons"]} == {"192x192", "512x512"}
    for icon in manifest["icons"] + old_manifest["icons"]:
        assert icon["type"] == "image/png"
        assert "maskable" in icon["purpose"].split()
        icon_path = (
            ROOT / "ankiweb/shell/static" / icon["src"].removeprefix("/shell/static/")
        )
        assert icon_path.is_file()
        image = client.get(icon["src"])
        assert image.status_code == 200
        assert image.headers["content-type"].split(";")[0] == "image/png"
        assert image.content.startswith(b"\x89PNG\r\n\x1a\n")
        size = int(icon["sizes"].split("x")[0])
        assert int.from_bytes(image.content[16:20], "big") == size
        assert int.from_bytes(image.content[20:24], "big") == size


def test_worker_headers_and_layout_registration_match(client: TestClient) -> None:
    page = client.get("/app/")
    assert page.status_code == 200
    head = _Head()
    head.feed(page.text)
    assert any(
        tag == "link"
        and attrs.get("rel") == "manifest"
        and attrs.get("href") == "/app/manifest.webmanifest"
        for tag, attrs in head.tags
    )
    registration = re.search(
        r'navigator\.serviceWorker\.register\(\s*["\']([^"\']+)["\']\s*,\s*'
        r'\{\s*scope\s*:\s*["\']([^"\']+)["\']\s*\}',
        page.text,
    )
    assert registration is not None
    path, scope = registration.groups()
    assert path == "/app/service-worker.js"
    assert scope == "/app/"
    worker = client.get(path)
    assert worker.status_code == 200
    assert worker.headers["service-worker-allowed"] == scope
    assert "no-cache" in worker.headers["cache-control"].lower()
    assert "javascript" in worker.headers["content-type"]
    old_worker = client.get("/service-worker.js")
    assert old_worker.status_code == 200
    assert old_worker.headers["service-worker-allowed"] == "/"


def test_theme_metadata_matches_source_css(client: TestClient) -> None:
    css = SOURCE_CSS.read_text(encoding="utf-8")
    source_colors = {}
    for theme in ("light", "dark"):
        block = re.search(
            rf'@plugin\s+"daisyui/theme"\s*\{{\s*name:\s*"aw-{theme}";([^}}]+)\}}',
            css,
        )
        assert block is not None
        value = re.search(r"--color-base-100:\s*(#[0-9a-fA-F]{6})\s*;", block.group(1))
        assert value is not None
        source_colors[theme] = value.group(1).lower()
    assert source_colors == {
        "light": APP_THEME_COLOR_LIGHT,
        "dark": APP_THEME_COLOR_DARK,
    }

    page = client.get("/app/")
    assert page.status_code == 200
    head = _Head()
    head.feed(page.text)
    theme_meta = {
        attrs.get("media"): attrs.get("content")
        for tag, attrs in head.tags
        if tag == "meta" and attrs.get("name") == "theme-color"
    }
    assert theme_meta == {
        f"(prefers-color-scheme: {theme})": color
        for theme, color in source_colors.items()
    }


# Execute the actual HTTP-served worker, not a separately maintained implementation.
_WORKER_HARNESS = r"""
import assert from "node:assert/strict";

const origin = "http://example.test";
const listeners = new Map();
const stores = new Map();
const calls = new Map();
let online = true;
let authorized = true;
let cssVersion = "css-v1";
let jsVersion = "js-v1";
let skipped = false;
let claimed = false;
const NativeRequest = globalThis.Request;
globalThis.Request = class extends NativeRequest {
  constructor(input, options) {
    super(typeof input === "string" ? new URL(input, origin) : input, options);
  }
};

const key = (request) =>
  new URL(typeof request === "string" ? request : request.url, origin).href;

const cacheFor = (entries) => ({
  async match(request) {
    const hit = entries.get(key(request));
    return hit && hit.clone();
  },
  async put(request, response) { entries.set(key(request), response.clone()); },
  async addAll(requests) {
    for (const request of requests) {
      const response = await fetch(request);
      if (!response.ok) throw new Error("precache failed");
      entries.set(key(request), response.clone());
    }
  },
});
globalThis.caches = {
  async open(name) {
    if (!stores.has(name)) stores.set(name, new Map());
    return cacheFor(stores.get(name));
  },
  async keys() { return [...stores.keys()]; },
  async delete(name) { return stores.delete(name); },
  async match(request) {
    for (const entries of stores.values()) {
      const hit = await cacheFor(entries).match(request);
      if (hit) return hit;
    }
  },
};
globalThis.self = {
  location: new URL(origin),
  addEventListener(type, handler) { listeners.set(type, handler); },
  async skipWaiting() { skipped = true; },
  clients: { async claim() { claimed = true; } },
};
globalThis.fetch = async (request) => {
  const url = new URL(key(request));
  if (url.pathname === "/app/offline" ||
      url.pathname.startsWith("/shell/static/app")) {
    assert.equal(request.cache, "reload");
  }
  calls.set(url.pathname, (calls.get(url.pathname) || 0) + 1);
  if (!online) throw new Error("network offline");
  if (url.pathname === "/app/offline") return new Response("public offline fallback");
  if (url.pathname === "/shell/static/app-client.css") return new Response(cssVersion);
  if (url.pathname === "/shell/static/app/install.js") return new Response(jsVersion);
  if (url.pathname === "/shell/static/app/unavailable.js") {
    return new Response("error", {status: 503});
  }
  if (url.pathname.startsWith("/app/")) {
    return authorized
      ? new Response("private authenticated HTML " + url.pathname)
      : new Response("login", {status: 303, headers: {Location: "/app/login"}});
  }
  return new Response("other");
};

eval(__APP_WORKER_SOURCE__);
assert.ok(listeners.has("install"));
assert.ok(listeners.has("activate"));
assert.ok(listeners.has("fetch"));

async function lifecycle(type) {
  let pending;
  listeners.get(type)({waitUntil(promise) { pending = promise; }});
  assert.ok(pending, `${type} must wait for completion`);
  await pending;
}
async function dispatch(path, method = "GET", mode = "same-origin") {
  let pending;
  const request = mode === "navigate"
    ? {url: new URL(path, origin).href, method, mode}
    : new Request(new URL(path, origin), {method, mode});
  listeners.get("fetch")({request, respondWith(promise) { pending = promise; }});
  return pending === undefined ? undefined : await pending;
}

await caches.open("ankiweb-app-obsolete");
await caches.open("ankiweb-shell-v1");
await caches.open("ankiweb-shell-obsolete");
await caches.open("ankiweb-shell");
await caches.open("unrelated-cache");
await lifecycle("install");
assert.equal(skipped, true);
assert.equal(calls.get("/app/offline"), 1);
assert.equal(calls.get("/shell/static/app-client.css"), 1);
await lifecycle("activate");
assert.equal(claimed, true);
assert.equal(stores.has("ankiweb-app-obsolete"), false);
assert.equal(stores.has("ankiweb-shell-v1"), true);
assert.equal(stores.has("ankiweb-shell-obsolete"), true);
assert.equal(stores.has("ankiweb-shell"), true);
assert.equal(stores.has("unrelated-cache"), true);
const appCaches = [...stores.keys()].filter((name) => name.startsWith("ankiweb-app-"));
assert.equal(appCaches.length, 1);
const appCacheName = appCaches[0];
const appCache = stores.get(appCacheName);

const appListeners = new Map(listeners);
listeners.clear();
eval(__LEGACY_WORKER_SOURCE__);
assert.ok(listeners.has("activate"));
claimed = false;
await lifecycle("activate");
assert.equal(claimed, true);
assert.equal(stores.has("ankiweb-shell-obsolete"), false);
assert.equal(stores.has("ankiweb-shell-v1"), true);
assert.equal(stores.has("ankiweb-shell"), true);
assert.equal(stores.has("unrelated-cache"), true);
assert.equal(stores.get(appCacheName), appCache);
assert.equal(
  await (await cacheFor(appCache).match("/app/offline")).text(),
  "public offline fallback"
);
listeners.clear();
for (const [type, handler] of appListeners) listeners.set(type, handler);

const precachedCss = [...appCache.keys()].find(
  (url) => new URL(url).pathname === "/shell/static/app-client.css"
);
assert.ok(precachedCss);
assert.match(new URL(precachedCss).search, /^\?v=[0-9a-f]{12}$/);
cssVersion = "css-v2";
assert.equal(await (await dispatch(precachedCss)).text(), "css-v1");
assert.equal(
  await (await dispatch("/shell/static/app-client.css?v=new-version")).text(), "css-v2"
);
assert.equal(calls.get("/shell/static/app-client.css"), 2);
assert.equal(await (await dispatch("/shell/static/app/install.js")).text(), "js-v1");
jsVersion = "js-v2";
assert.equal(await (await dispatch("/shell/static/app/install.js")).text(), "js-v1");
assert.equal(calls.get("/shell/static/app/install.js"), 1);
assert.equal((await dispatch("/shell/static/app/unavailable.js")).status, 503);
assert.equal((await dispatch("/shell/static/app/unavailable.js")).status, 503);
assert.equal(calls.get("/shell/static/app/unavailable.js"), 2);

assert.equal(
  await (await dispatch("/app/", "GET", "navigate")).text(),
  "private authenticated HTML /app/"
);
assert.equal(
  await (await dispatch("/app/review?deck=1", "GET", "navigate")).text(),
  "private authenticated HTML /app/review"
);
authorized = false;
const revoked = await dispatch("/app/", "GET", "navigate");
assert.equal(revoked.status, 303);
assert.equal(await revoked.text(), "login");
assert.equal(calls.get("/app/"), 2);
online = false;
assert.equal(
  await (await dispatch("/app/review?deck=1", "GET", "navigate")).text(),
  "public offline fallback"
);
assert.equal(await dispatch("/app/review", "POST", "navigate"), undefined);
assert.equal(await dispatch("/shell/static/app/install.js", "POST"), undefined);
assert.equal(await dispatch("/shell/static/other.js"), undefined);
assert.equal(await dispatch("/app/review", "GET", "same-origin"), undefined);
assert.equal(
  await dispatch("https://another.test/shell/static/app/install.js"), undefined
);

for (const entries of stores.values()) {
  for (const [url, response] of entries) {
    const path = new URL(url).pathname;
    assert.notEqual(path, "/app/");
    assert.notEqual(path, "/app/review");
    assert.ok(!(await response.clone().text()).includes("private authenticated HTML"));
  }
}
"""


@pytest.mark.skipif(BUN is None, reason="bun is required to execute the service worker")
def test_actual_worker_cache_and_offline_behavior(
    client: TestClient, tmp_path: Path
) -> None:
    response = client.get("/app/service-worker.js")
    assert response.status_code == 200
    legacy_response = client.get("/service-worker.js")
    assert legacy_response.status_code == 200
    script = _WORKER_HARNESS.replace(
        "__APP_WORKER_SOURCE__", json.dumps(response.text), 1
    ).replace("__LEGACY_WORKER_SOURCE__", json.dumps(legacy_response.text), 1)
    harness = tmp_path / "worker-test.mjs"
    harness.write_text(script, encoding="utf-8")
    assert BUN is not None
    completed = subprocess.run(  # noqa: S603 - fixed executable and local test harness
        [BUN, str(harness)], capture_output=True, text=True, timeout=30, check=False
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
