# Research: FastPWA and alternatives for making ankiweb installable

**Question**: What does `FastPWA` (https://pypi.org/project/FastPWA/) do, can ankiweb use it, and are there better options?
**Scope**: research only. No project file was changed. FastPWA was installed only in a throwaway virtual environment outside the repo (since deleted); the project `.venv` still has FastAPI 0.141.1 and no `fastpwa`.
**Legend**: **belegt** = read in source or observed in a run; **[INFERENCE]** = my conclusion; **ungeprüft** = not tested.

---

## 1. Short answer

1. **Do not add FastPWA as a dependency.** It solves the part of the PWA task that is almost trivial (a manifest and a service worker, about 60 lines) and is built around a model that does not fit ankiweb (§4). **[INFERENCE]**
2. **A clean install of `fastpwa==0.5.3` does not import** (`ModuleNotFoundError: daomodel`), and it pins `fastapi~=0.139.2`, below this repo's 0.141.1 (§3). Both were observed.
3. **I found no maintained Python package that is a better fit.** The ones that exist are for other frameworks or are abandoned (§5). **[INFERENCE]** based on a limited search.
4. The recommended path is to **write the manifest route, the service worker and a few `<link>`/`<meta>` tags directly in ankiweb**, as `RESEARCH-pwa.md` scenario 1 or 2 already describes. The hard blockers (HTTPS, icons, a design for the service worker) are the same with or without a library.

## 2. What FastPWA does (belegt, read from the 0.5.3 wheel)

| Feature | How |
|---|---|
| Manifest | `GET {prefix}{title}.webmanifest`, a pydantic `Manifest` (name, short_name, start_url, scope, id, `display: standalone`, theme and background colour, icons, shortcuts). `start_url` and `scope` are both the registered route |
| Service worker | `GET {prefix}service-worker.js`, a fixed 60-line script. Network-first for GET; a cached response is served only if it carries `Cache-Control: immutable`, or if the network fails; responses with `no-store` are not cached; non-GET requests pass through |
| Registration | an inline `<script>` in the page head calls `navigator.serviceWorker.register(...)` |
| Icons | **one** icon: the first `favicon.*` found in the mounted static folder, declared with `sizes: "any"` and `purpose: "any maskable"` |
| Pages | `PWA` is a **subclass of `FastAPI`**. It renders its own HTML page from a built-in template (`PAGE_TEMPLATE`) and Jinja files, injecting `global.css`/`index.js`-style assets by file name |
| Extras | an optional API layer through `fast-controller` and `daomodel` (SQLite `database.db`), `include_api_router`, `finalize_api` |

Maturity (belegt, PyPI and GitHub): 0.5.3, released 2026-07-22; first beta 2025-10-01; MIT; no known vulnerabilities listed; repository has 0 stars, 0 forks, 0 issues, one author, no visible commit history through the page I could read. The wheel is 6.8 KB.

## 3. Problems observed when trying it

Run in a throwaway venv with Python 3.12, nothing touched in the repo.

| Check | Result |
|---|---|
| `pip install fastpwa==0.5.3`, then `import fastpwa` | **fails**: `ModuleNotFoundError: No module named 'daomodel'`. `fastpwa/__init__.py` imports `daomodel` unconditionally, but it is not in `Requires-Dist`, not even under the `controller` extra |
| After `pip install daomodel` (pulls in `sqlmodel`, `sqlalchemy`) | `PWA(...)` fails with `AttributeError: 'NoneType' object has no attribute 'data_layer'`: without `fast-controller` the default controller is `None` and is dereferenced |
| `PWA(..., controller=object())` | works. With a static folder containing `index.html` and `favicon.svg`, `GET /app/`, `/app/anki-web.webmanifest` and `/app/service-worker.js` returned 200 with content types `text/html`, `application/json`, `application/javascript` |
| Pinned FastAPI | `fastapi~=0.139.2` means `>=0.139.2,<0.140`. uv downgraded FastAPI to 0.139.2 in the throwaway env; this repo has **0.141.1** and declares `fastapi>=0.115`. Installing FastPWA in the project would conflict or force a downgrade |

The manifest content type is `application/json`; browsers also accept that, but the registered type for manifests is `application/manifest+json` **[INFERENCE]**, not tested in a browser.

## 4. Why it does not fit ankiweb

| Point | Detail |
|---|---|
| Different app model | FastPWA expects to **own the app** (`PWA` replaces `FastAPI`) and its pages. ankiweb builds its own `FastAPI` in `create_app` (`app.py:161`) with its own shell template `shell.html.jinja`, its own middleware (host guard, auth) and a catch-all media router mounted last. A library that wants to be the app object cannot be dropped in |
| Single scope, single icon | The manifest `start_url` and `scope` are the one registered route, and there is **one icon**. Chrome's install criteria need 192 px and 512 px icons (confirmed on `web.dev/articles/install-criteria`, see §6). A single `favicon.svg` with `sizes: "any"` is not what that page describes; whether Chrome accepts it was **not tested** |
| Fixed service worker | The worker is a constant string, so its caching behaviour cannot be configured. **Measured** by running its source under bun with a fake cache and `fetch` (no browser): a response without `Cache-Control` is stored and **served again when the network is down**; `no-store` is never stored (offline gives an error); `immutable` is served from the cache without hitting the network. For ankiweb this means an authenticated page loaded once can later be shown from the cache without a login check, and `/_anki/` RPC GETs would be cached too **[INFERENCE]**, unless the server sends `no-store` where it matters. Whether ankiweb's pages send `Cache-Control` per route was not checked (only `assets.py` sets `max-age`, for assets) |
| Heavy transitive dependencies | Needs `daomodel` (and through it `sqlmodel`/`sqlalchemy`) just to import |
| Project health | One author, no stars, young; a hard import bug in the latest release suggests it is not broadly used **[INFERENCE]** |
| Size of the problem | Everything it contributes for our case fits in one small router. See §6 |

## 5. Alternatives

Searched PyPI (JSON API) and the web.

| Option | What it is | Fit for ankiweb |
|---|---|---|
| `django-pwa` 2.0.1 | Django app: manifest and service worker (last release 2024-09-27) | Wrong framework |
| `flask-pwa` 0.1.0 | Flask extension (one release, 2020-05-02, requires `flask<2`) | Wrong framework, abandoned |
| `starlette-pwa`, `fastapi-pwa`, `pwa-fastapi`, `quart-pwa`, `fasthtml-pwa`, `pwa`, `workbox`, `pwa-builder` | looked up by name on PyPI | **do not exist** (404). Other packages with different names may exist; the search tool returned none |
| `pywebpush` 2.5.0 | Web Push (VAPID) publishing | Only needed for push notifications, which are not part of installability |
| `nicegui`, `python-fasthtml` | full UI frameworks | Would replace the UI stack; not a PWA add-on |
| JavaScript tooling (`create-pwa`, Workbox, `vite-plugin-pwa`) | generators and caching libraries | Relevant only if the client becomes a built SPA; ankiweb's frontend is server-rendered Jinja + Datastar |
| **Own code in ankiweb** | A route for the manifest, a route for the service worker (root scope), icons, `<link rel="manifest">` and `theme-color` in `shell.html.jinja` | Smallest dependency surface; full control over scope, caching and auth |

**[INFERENCE]**: the search showed no better Python library for FastAPI. The result is limited by the search tool and PyPI name guesses; I did not browse PyPI classifiers or "awesome" lists exhaustively.

## 6. What ankiweb needs, and where it goes

From `RESEARCH-pwa.md` (scenario 1, online-only installable shell) plus Chrome's install criteria (web.dev, MDN):

| Need | Own implementation | Notes |
|---|---|---|
| Manifest | a small FastAPI route returning JSON with `name`, `short_name`, `start_url`, `scope`, `display: standalone`, `theme_color`, `background_color`, `icons`, optional `id` | `application/manifest+json` is the standard type |
| Icons | PNG 192 and 512 (and a maskable variant). `ankiweb/web_assets/imgs/favicon.ico` exists; no 192/512 icons were found in the repo | Must be created; design decision |
| `<link rel="manifest">`, `theme-color`, apple-touch-icon | in `shell.html.jinja` head, or in the deck list / study / add pages once those are built | iOS reads apple-touch-icon and the meta tags, not only the manifest |
| Service worker | a route that serves a file **from the root path** so its scope covers the app | Whether the existing static mounts could serve a root-scoped worker is listed as **ungeprüft** in `RESEARCH-pwa.md` §6; a dedicated route avoids the question |
| Service worker behaviour | decide what to cache. Safe minimal choice: precache a small offline page and static shell assets, **never** cache HTML of authenticated pages or `/_anki/`, `/api/` or `/ws` | [INFERENCE]; FastPWA's fixed worker does not make this decision |
| HTTPS | reverse proxy or tunnel | **Required in either case**; FastPWA does not help (see `RESEARCH-pwa.md` §1) |
| Cookie `secure` flag, `ANKIWEB_ALLOWED_HOSTS`, password | already in `RESEARCH-pwa.md` §4 | unchanged |
| Install criteria | Chrome: HTTPS, manifest with name, 192 and 512 icons, `start_url`, `display`, `prefer_related_applications` absent or false, plus the engagement heuristic (one click or tap, 30 seconds on the page). A service worker is **not** in the list (`web.dev/articles/install-criteria`, last updated 2024-09-19, read directly). `RESEARCH-pwa.md` notes that other sources disagree for older versions | iOS is installed manually from the share sheet |

## 7. Conclusion and next step

- **FastPWA**: not recommended. It does not import from a clean install, conflicts with this repo's FastAPI version, assumes it owns the app, and provides little that is hard.
- **Alternatives**: no better Python package found. The most reasonable path is a small own router plus template tags.
- **Next step if pursued**: a spike that adds a manifest route, 192/512 icons, a minimal service worker and `<link>` tags, served behind a local HTTPS proxy, then checks Chrome DevTools "Application / Manifest" for installability errors on an Android device. That also answers the open question about serving a root-scoped worker.

**Not verified**: browser installability of anything (no browser run), whether Chrome accepts a single `sizes: "any"` SVG icon, per-route `Cache-Control` headers of ankiweb's pages, the `application/manifest+json` content-type choice, and every package I could not find by name. The service worker's caching decisions were run under bun with fake `fetch` and `caches`, not in a real browser.
