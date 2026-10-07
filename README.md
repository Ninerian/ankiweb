# ankiweb

> ⚠️ **Unofficial, personal, single-user project — not affiliated with Anki/Ankitects.**
> This is an independent, community browser port of [Anki](https://apps.ankiweb.net),
> intended to be run by **one user on their own machine**. It is **NOT** affiliated with,
> endorsed by, or connected to Ankitects Pty Ltd, and it is **NOT** the official **AnkiWeb**
> sync service at apps.ankiweb.net. "Anki" and "AnkiWeb" are names of that upstream
> project/service. This is a hobby/personal implementation provided as-is, with no warranty,
> under AGPL-3.0-or-later (see [LICENSE](LICENSE) and [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)).

A **browser port of Anki desktop + AnkiConnect**, built on the official `anki` Python
package (pylib) + FastAPI. It serves Anki's real study UI in a browser and re-implements
the full AnkiConnect HTTP API — for a single user, on your own machine.

**Frontend architecture: Jinja + Datastar components, styled with Tailwind CSS 4 + daisyUI 5**
(theming comes only from daisyUI's built-in `light`/`dark` themes; see `shell_src/app.css`). Anki desktop's frontend was migrated
from the vendored compiled SvelteKit SPA pages to a lightweight, reactive Jinja + Datastar
architecture. Reusable components live under `ankiweb/adapters/inbound/http_shared/templates/components/`
(with an interactive gallery at `/dev/components` when `ANKIWEB_DEV=1`), while page templates
reside under `ankiweb/adapters/inbound/http_shared/templates/pages/`. Minimal JS bundles
in `shell_src/bundles/` are built via `npm run build`. Vendored SvelteKit bundles are no longer
served; only core static assets (reviewer.js, MathJax, jQuery) are retained under `/_anki/`.

**Scope:** everything in the desktop study/edit/manage flow + the AnkiConnect API.
**Out of scope (by design):** sync (AnkiWeb) and add-ons/plugins.

---

## Screenshots

**Deck browser** — your full deck tree (including nested decks), counts, and the always-present
top toolbar. Anki's home screen, in a browser tab.

![Deck browser](docs/images/home.png)

**Studying** — the real Anki reviewer (`reviewer.js` + MathJax) drives the card; ankiweb adds a
card-action bar (mark · bury · suspend · set due · reset · delete · undo · flags) and keyboard
shortcuts.

![Reviewer](docs/images/reviewer.png)

**Browse & edit** — search, a deck/tag sidebar, the results table, and Anki's real `editor.js`
embedded live in the detail pane (with Fields… / Cards… / Preview).

![Browser](docs/images/browser.png)

**Reused, not rewritten** — where Anki ships a compiled SvelteKit page, ankiweb serves the
vendored build and wires it to the backend. Here's the full Deck Options screen, unchanged:

![Deck options](docs/images/deck_options.png)

**Manage Note Types** — list / add / rename / delete note types, with links into the field and
card-template editors (one of the Tools-menu screens ankiweb rebuilds for the web):

![Manage note types](docs/images/notetypes.png)

---

## Requirements

- Python **3.12**
- `anki==26.9.2` (pinned — the vendored frontend must match this version; the exact upstream
  Anki/AnkiConnect commits this port was built against are recorded in [UPSTREAM.md](UPSTREAM.md))
- Node.js (only to build the ~2 KB shell bundle)
- [uv](https://docs.astral.sh/uv/) for Python package and environment management.

## Setup

```bash
uv sync --extra dev

# 1. Vendor Anki's compiled frontend (downloads the aqt 26.9.2 wheel, extracts
#    _aqt/data/web/ into ankiweb/web_assets/ — gitignored). Required on every fresh checkout.
uv run python tools/fetch_web_assets.py

# 2. Vendor/refresh the Datastar frontend bundle (downloads datastar.js into
#    ankiweb/shell/static/ — tracked in git, but re-run this to update the pinned version).
uv run python tools/fetch_datastar.py

# 3. Build the shell: the bridge bundle (shell_src/bootstrap.ts -> ankiweb/shell/static/bootstrap.js)
#    and the Tailwind CSS 4 + daisyUI 5 stylesheet (shell_src/app.css -> ankiweb/shell/static/app.css).
#    Re-run after changing any template, route module or shell source (Tailwind scans them for classes).
npm install && npm run build

# 4. (optional) for the Playwright integration tests
uv run python -m playwright install chromium
```

Steps 1-3 are also available as one command after `npm install`: `npm run setup`
(runs fetch_web_assets.py, fetch_datastar.py, then the shell build in order).

## Run

```bash
uv run python -m ankiweb
```

This starts **two servers in one process**:

| Port | Serves | Default | Configure with |
|------|--------|---------|----------------|
| **Web UI + WebSocket** | the browser study/edit UI and the `/ws` bridge (WS shares this port) | `127.0.0.1:8000` | `ANKIWEB_HOST` / `ANKIWEB_PORT` |
| **AnkiConnect HTTP API** | `POST /` JSON API for AnkiConnect clients (+ Swagger docs at [`/docs`](#api-docs-swagger)) | `127.0.0.1:8765` | `ANKIWEB_AC_HOST` / `ANKIWEB_AC_PORT` (or `ankiconnect.json`) |

Open <http://127.0.0.1:8000> in a browser. The AnkiConnect port defaults to **8765** on
purpose — existing AnkiConnect clients/scripts work unchanged.

## Docker

Prefer a container? A multi-stage `Dockerfile` and `docker-compose.yml` following Docker
best practices (non-root user, healthcheck, persistent volume, minimal capabilities) are
included:

```bash
docker compose up --build -d
```

Then open <http://127.0.0.1:8000>. See [DOCKER.md](DOCKER.md) for the full setup,
configuration reference, data-persistence/backup instructions, and the AGPL
source-URL obligation when hosting for other users.

## Configuration

All settings have safe localhost defaults; override via environment variables:

| Variable | Default | Meaning |
|----------|---------|---------|
| `ANKIWEB_COLLECTION` | `~/.local/share/ankiweb/collection.anki2` | Path to the `.anki2` collection. The parent directory is created automatically; a fresh collection is created if the file doesn't exist. |
| `ANKIWEB_HOST` | `127.0.0.1` | Web UI bind address (`0.0.0.0` to listen on all interfaces). |
| `ANKIWEB_PORT` | `8000` | Web UI port. |
| `ANKIWEB_ALLOWED_HOSTS` | *(empty)* | Comma-separated extra `Host` header values accepted past the DNS-rebinding guard (see **LAN access**). `*` disables the check. |
| `ANKIWEB_AC_HOST` | `127.0.0.1` | AnkiConnect bind address (overrides `ankiconnect.json`). |
| `ANKIWEB_AC_PORT` | `8765` | AnkiConnect port (overrides `ankiconnect.json`). |
| `ANKIWEB_AC_KEY` | *(none)* | AnkiConnect `apiKey` (overrides `ankiconnect.json`). |
| `ANKIWEB_IMPORT_TMP_DIR` | `<collection dir>/import-tmp` | Where uploaded import/image files are staged before the backend reads them. |
| `ANKIWEB_LANG` | *(empty → English)* | UI language, an Anki locale code (e.g. `zh-CN`, `ja`, `de`, `fr`). Chosen at startup — there is no in-app switcher; changing it means changing this var and restarting. See **Language** below. |
| `ANKIWEB_PASSWORD` | *(empty → no password)* | If set, the web UI requires this password (a `/login` page sets a session cookie). Empty = open, the default. The AnkiConnect API keeps its own `ANKIWEB_AC_KEY`. |
| `ANKIWEB_SOURCE_URL` | *(empty)* | AGPL §13 Corresponding-Source location for this deployment, shown on the `/about` page (only relevant if you run it as a public network service). |

**`ankiconnect.json`** (optional) lives next to the collection file and uses AnkiConnect's
own keys; environment variables override it:

```json
{ "webBindAddress": "127.0.0.1", "webBindPort": 8765, "apiKey": null,
  "webCorsOriginList": ["http://localhost"], "ignoreOriginList": [] }
```

### LAN access

To reach the UI from another device, bind to all interfaces **and** allow your host
(the Web UI has a DNS-rebinding guard that only permits localhost by default):

```bash
ANKIWEB_HOST=0.0.0.0 ANKIWEB_ALLOWED_HOSTS=192.168.1.50:8000 \
  uv run python -m ankiweb
```

`ANKIWEB_ALLOWED_HOSTS` accepts the value with or without a port (`192.168.1.50` matches
any port), multiple comma-separated hosts, or `*` to turn the check off (only on a trusted
network). It covers both HTTP and the WebSocket bridge.

### Language

Set `ANKIWEB_LANG` to any Anki locale code to run the whole UI in that language — both the
reused Anki frontend (graphs / deck options / reviewer / editor …) and ankiweb's own
hand-written screens (deck browser, browser, Add, Preferences, etc.):

```bash
ANKIWEB_LANG=zh-CN uv run python -m ankiweb
```

The language is fixed at startup (it's applied before the collection is opened); there is
no in-app language switcher, so to change it you set `ANKIWEB_LANG` and restart. Empty or an
unknown code falls back to English. Accepts both `zh-CN` and `zh_CN` forms.

### Password

By default the web UI is open (no login) — it's a single-user, local-first app. To require a
password, set `ANKIWEB_PASSWORD`:

```bash
ANKIWEB_PASSWORD=mysecret uv run python -m ankiweb
```

Visitors then get a `/login` page; the correct password sets an httponly session cookie and
unlocks the UI (and the `/ws` bridge). `/logout` clears it. This gates the **web app only**;
the AnkiConnect HTTP API (port 8765) is controlled separately by `ANKIWEB_AC_KEY`. It's a
light gate for LAN use, not a hardened auth system — serve over HTTPS if it matters.

### API docs (Swagger)

The AnkiConnect server publishes interactive OpenAPI docs at
<http://127.0.0.1:8765/docs> (schema at `/openapi.json`). Every action has a standard
Pydantic request schema and a documented `POST /actions/<name>` route you can call straight
from the page ("Try it out"), e.g. `POST /actions/findCards` with body
`{"query": "deck:French is:due"}`.

These typed routes are an **additive convenience layer** — the canonical AnkiConnect contract
is unchanged: real clients still `POST /` with `{"action", "version", "params"}`, and the
`/actions/*` routes call the exact same dispatcher, so behavior never diverges. When
`ANKIWEB_AC_KEY` is set, send it as the `X-API-Key` header (use the **Authorize** button in
Swagger); the canonical `POST /` keeps reading the key from the request body as upstream does.

**Extra actions (ankiweb-original).** A few actions that are *not* part of AnkiConnect live
under a separate `/extra_actions/<name>` namespace — documented in `/docs` (tagged
`extra_actions`) and callable there, but deliberately **unknown to the canonical `POST /`**
dispatcher (so the root surface stays byte-identical to upstream). Currently:

- `POST /extra_actions/deleteModel` `{ "modelName": "MyType" }` (or `{ "modelId": 1234 }`) —
  delete an entire note type (the reverse of `createModel`). Returns `true`; **errors** if any
  note still uses it, if the type isn't found, or if it's the only remaining note type. The
  same `X-API-Key` gate applies.
- `POST /extra_actions/extendCardLimits` `{ "deck": "MyDeck", "new": 10, "review": -5 }` —
  temporarily add to (or subtract from) today's new/review card limits for a deck (the API form
  of Custom Study's "Increase today's … card limit"; negative reduces, deltas accumulate).
  Identify the deck by `deck` name or `deckId`. Returns the deck's resulting counts.
- `POST /extra_actions/getNotifyConfig` `{}` — read the [Deck push notifications](#deck-push-notifications-extras)
  config + live status.
- `POST /extra_actions/setNotifyConfig` `{ "enabled": true, "url": "https://…", "poll_sec": 30 }`
  — modify that config from outside (instead of the web form). Send only the fields you want to
  change (`enabled`/`url`/`token`/`poll_sec`/`retry_sec`/`scope`, plus optional `resync: true`);
  omitted fields keep their value. Takes effect live; returns the resulting config + status.

### Deck push notifications (Extras)

An **ankiweb-original** feature (not part of the Anki/AnkiConnect port): ankiweb can POST to an
endpoint of yours whenever a deck's study counts change — i.e. its `new_count`, `learn_count`,
or `review_count` moves (including bucket shifts that keep the total). Useful for a study
bot/agent that should react without polling.

Configure it live at **Extras ▾ → Push notifications** (`/notify`) — no env vars, no restart.
Settings persist to a `notify.json` sidecar next to the collection. Fields:

| field | meaning |
|---|---|
| Enabled | master on/off |
| POST URL | where to send notifications |
| Token | sent as `Authorization: Bearer <token>` (omitted if empty) |
| Poll interval (sec) | how often the deck state is refreshed (one `deck_due_tree()` call — scales to thousands of decks) |
| Retry interval (sec) | how often a failed POST is resent |
| Scope | which decks to watch in a nested tree: **Leaf only** (default — last-level decks with no subdecks) or **All levels** (every deck; a parent's counts then include its subdecks) |

The notifier is active only when *enabled* and a URL and both intervals (> 0) are set. Decks are
identified by **full name** (`A::B::C`); counts are the same as `getDeckStats` (respect daily
limits). A deck notifies whenever its `(new_count, learn_count, review_count)` tuple changes —
any of the three, even if the total stays the same (the payload's `learnable` field is simply
`total > 0`, for convenience). With *All levels*, a parent's counts are the subdeck rollup;
*Leaf only* reports just the bottom-level decks. On start, on enable, on a URL/scope change, or
when you click *Save & re-push all*, every deck with nonzero counts (in scope) is pushed once so
your receiver syncs; always-empty decks stay silent.

**Request** ankiweb sends:

```
POST <url>
Authorization: Bearer <token>          # omitted when token is empty
Content-Type: application/json

{ "source": "ankiweb",
  "ts": 1780500000,                     # epoch seconds
  "changes": [
    { "deck": "英语词汇::单词", "deckId": 1780005159378, "learnable": true,
      "new_count": 12, "learn_count": 3, "review_count": 40 } ] }
```

**Success** = HTTP `200` **and** a JSON body with `ok` exactly `true`. Anything else (non-200,
missing/false `ok`, non-JSON, timeout, connection error) is treated as a failure and retried
every *retry interval* until it succeeds. While a notification is unacknowledged, further deck
changes are coalesced — the resend always carries the **latest** counts, and a deck that
reverts to its last acknowledged counts sends nothing. Deleted/renamed decks drop silently.

### Night mode

Toggle with the 🌙 button in the top toolbar (persisted in `localStorage`); it switches the
daisyUI theme (`data-theme="light"` / `"dark"`) and themes the server-rendered pages and threads `#night` into links to the SvelteKit pages so those
render dark too.

### Navigation & Transport Boundaries

Every server-rendered screen has an always-present top toolbar — **Decks · Add · Browse ·
Stats** (Anki's main-window toolbar, minus Sync) plus the night-mode toggle.

Navigation follows the Tao of Datastar:
- Pure page navigation uses standard native links (`<a href="...">`), letting the browser handle keyboard activation, new tabs, URL history, and document lifecycles naturally. Cancel in Preferences, Fields, Card Layout, Custom Study, and Filtered Deck discards the local draft without submitting signals. Back to Decks, Custom Study (including the finished-deck page), and Create Filtered Deck likewise navigate directly by GET, without a preliminary navigation POST.
- Deckbrowser and Overview options links resolve the normal or filtered options destination while rendering, using the displayed deck's ID and type. They do not re-resolve the globally current deck when clicked.
- Deck Options **Close** is a native `/deckbrowser` link. An unmodified primary click with unsaved changes opens an accessible native `<dialog>` styled with DaisyUI. **Keep editing**, Escape, or a backdrop click closes the dialog without changing the draft; **Discard changes and close** navigates by GET without saving. Modified and middle clicks retain native link behavior, leaving the original tab and its draft intact. No close-confirmation request or `window.location` navigation is needed.
- Package import keeps the native dialog, modal box, title, and header **Close**
  control outside the Datastar replacement target. Completion replaces only the
  options and import actions with results, including error results. The header
  Close button, Escape, and backdrop dismiss the dialog without navigating away;
  successful import results remain available until dismissed.
  Only the content pane scrolls, keeping Close visible in short viewports.
- Actions with side effects remain POST: opening a deck selects it, starting study initializes the timebox, and Save/Submit applies or validates changes. Actions that navigate return whole-document Datastar SSE redirects (`common.redirect_response(url)` via `SSE.redirect(target)`); in-page mutations update targeted fragments without soft-routing layers or client router shims. The ten obsolete pure-navigation POST handlers have been removed, with no compatibility aliases.
- Remaining full-page reload endpoints: notetype mutating endpoints (`/notetypes/rename/{ntid}`, `/notetypes/add/{base_ntid}`, `/notetypes/delete/{ntid}`) and deck description save (`/overview/setdesc`) remain explicit deferred Phase 3 reloads. Deckbrowser rename/delete endpoints (`/deckbrowser/rename/{did}`, `/deckbrowser/delete/{did}`) also retain full reloads in Phase 5 without prior explicit deferral. No soft routing is introduced.

#### Transport Responsibilities & Entrypoints

| Layer / Channel | Transport & Format | Responsibilities & Entrypoints | State Authority & Lifecycle |
|---|---|---|---|
| **Datastar Views & In-Page Actions** | HTTP `POST`/`GET`, Datastar SSE (`text/event-stream`), JSON signals | Fragment morphs, signal patches, dialog workflows (`/deckbrowser`, `/overview`, `/browse`, `/preferences`, `/custom-study`, `/filtered-deck`, `/fields`, `/card-layout`, `/notetypes`, `/change-notetype`, `/image-occlusion`). | Request signals (e.g. `$selectedCids`, form drafts) are the source of truth for mutations. Responses patch targeted elements or signals directly. |
| **Modern Note Editor & Add** | HTTP `GET`/`POST`, Datastar SSE signals & elements | Rich editor routes (`GET /edit`, `GET /add`) and in-place field/tag saves: `POST /editor/save-field`, `POST /editor/blur-field`, `POST /editor/save-tags`, `POST /editor/toggle-collapse`, `POST /editor/toggle-sticky`. | Field contents live in Datastar signals (`field_val_<idx>`, `nid`, `tags_str`; `tags` is a template value); field blur triggers collection mutation and broadcasts `opchanges` across the hub. Does not require WebSocket for saves. |
| **Native Reviewer & Bridge Commands** | WebSocket `/ws?context=reviewer`, JSON frames | Upstream desktop reviewer compatibility and timing: `pycmd` commands (`show`, `ans`, `ease1`..`ease4`, `replay`, `play:<side>:<idx>`, `typed:<val>`, `decks`, `mark`, `setflag:<0-4>`, `buryc`, `buryn`, `suspendc`, `suspendn`, `setdue:<spec>`, `forget`, `deletenote`, `undo`, `cardinfo`, `edit`, `starttimer`). | Server manages `ReviewerSession` (timer, queued cards, scheduling states). Drives DOM via bridge push calls (`_showQuestion`, `_showAnswer`, `ankiwebSetAnswerBar`). |
| **Reviewer Controls & Audio Runtime** | DOM events, WebSocket commands, HTML5 Audio | Show answer button (`#ansbut` / `.ansbut`), QA element (`#qa`), answer container (`#ankiweb-answer`), ease buttons (`.ease[data-ease='1']`..`[data-ease='4']`), mark/flag (`#_mark`, `#_flag`), type-in (`#typeans`), replay button (`.replay-button`). Replay calls `pycmd('play:<side>:<idx>')` over `/ws?context=reviewer`. Audio files dispatched via push call `ankiwebPlayAudio` and played sequentially via browser `new Audio(...)`. | Audio playback is a client browser runtime side effect over static files; no WebSocket audio streaming. |
| **MathJax Typesetting & Editor Overlay** | Static assets (`GET /_anki/...`), client DOM custom element | `/_anki/js/mathjax.js`, `/_anki/js/vendor/mathjax/tex-chtml-full.js`, CHTML glyph fonts (cached 1 year). In editor, `<anki-mathjax>` custom element handles inline preview and modal edits; saved delimiters convert to `\[...\]` / `\(...\)`. | Local in-browser rendering runtime; completely decoupled from WebSocket traffic. |
| **Browser Iframe Integration** | DOM `postMessage` (`ankiwebLoadNid`) | On single row selection in `/browse`, `#detail` embeds or reuses `<iframe id="editor-frame" class="editor-frame" src="/edit?nid=X">`. Subsequent selections post `{type: 'ankiwebLoadNid', nid: X}` to that same iframe element; its `/edit` listener navigates `window.location.href` to `/edit?nid=X`, replacing the iframe document but retaining the element. | Selection changes navigate the iframe to the newly selected note. Background `/browse/refresh` preserves the current iframe element and document. For `/browse/select`, a script checks the currently selected rows before loading a regular-note iframe; selection-specific `#detail[data-selected-cids="..."]` selectors guard Image Occlusion and empty/multiple element patches. |
| **Cross-Screen Opchanges Refresh** | WebSocket push `{"type":"opchanges","flags":{...},"initiator":str}` | `service.run_op` broadcasts collection changes through `BridgeHub.broadcast_opchanges`. Handled in `shell_src/bootstrap.ts`: screens with `window.__ankiwebOnOpchanges` (e.g. `/browse` re-querying via Datastar `POST /browse/refresh`) preserve the live editor iframe element/document, selection, focus, and search drafts; default screens reload on relevant flags. | Server collection ops emit flags; HTTP response owner handles its own local mutation response while remote contexts refresh selectively. |
| **Selection State & BridgeHub Mirror** | Datastar `$selectedCids` signal vs. `hub.ui_state.selected_card_ids` | Datastar browser actions (`POST /browse/suspend`, `POST /browse/setdue`, etc.) submit `$selectedCids` directly. Selection updates `hub.ui_state.selected_card_ids` and `selected_note_ids` as a mirror for legacy bridge consumers and external AnkiConnect `gui*` actions. | Submitted `$selectedCids` is authoritative for Datastar HTTP mutations; those handlers never infer their selection from the cached mirror. |
| **Backend Protobuf RPC** | HTTP `POST /_anki/{method}` (binary protobuf) | Direct binary bridge to Rust backend or custom handlers (`ankiweb/core/rpc/dispatch.py`), including `updateDeckConfigs`, `changeNotetype`, image occlusion mutations, and FSRS computations. | Direct request-response over `application/binary`; bypasses WebSocket bridge. |
| **External AnkiConnect API** | HTTP `POST /` (JSON-RPC) & typed REST `POST /actions/{name}` | External client automation (Yomitan, integrations). Interacts with `CollectionService` and reads `hub.ui_state` to coordinate with live UI. | Operates on dedicated port (`8765` by default) independent of browser session lifecycles. |

#### Shared Datastar Response Helpers (`http_datastar.common`)

Response construction across Datastar screens standardizes on concrete helpers in `ankiweb/adapters/inbound/http_datastar/common.py`:
- `elements_response(elements: str, selector: str | None = None) -> DatastarResponse`: emits `SSE.patch_elements` preserving default SDK outer patch semantics and target selector behavior.
- `signals_response(signals: dict[str, SignalValue]) -> DatastarResponse`: emits `SSE.patch_signals`, preserving all JSON value types (including `False`, `0`, `""`, and `None`) without truthy filtering or extra validation.
- `redirect_response(location: str) -> DatastarResponse`: emits `SSE.redirect(location)` to trigger whole-document native browser navigation.
- `refresh_screen(service: CollectionPort | Any, render: Callable[..., str], selector: str | None = None) -> DatastarResponse`: runs renderer on collection thread and reuses `elements_response`.
- `error_response(message: object) -> DatastarResponse`: reuses `signals_response({"error": str(message)})`.

Heterogeneous, multi-event streams (e.g. ordered multi-signal patches, scripts, custom patch modes, or guarded multi-target streams) continue to invoke `ServerSentEventGenerator` directly without synthetic wrappers.

### Form state (Datastar 1.0.4)

Preferences, Custom Study, Fields, and Card Layout bind editable values to Datastar
signals and submit them directly with `@post(...)`; saving does not scrape the DOM
or construct a separate JavaScript payload. Custom Study's tag selectors use native
multi-select array bindings. Preferences derives its unsaved-change indicator from
the current signal values, so restoring the original values clears the indicator.

Fields and Card Layout keep a local, uncommitted draft: `fieldDraft` or `layoutDraft`
contains a stable-keyed `rows` map, an `order` array, and a monotonic `nextId` counter.
Fields tracks the sort field by `sortKey`; Card Layout stores styling in
`layoutDraft.css`. The HTTP save handlers resolve the ordered records from these
signals. Moving a row does not change its identity or binding; deleting the selected
sort field selects the first remaining field.

Small local helpers still clone, remove, and move row/block markup because Datastar
has no built-in list renderer. These helpers never read input values or serialize
form data, and row operations require no server requests. Only **Save** applies the
draft to the collection; **Cancel** discards it. Card Layout's **Preview** continues
to use the saved collection state, not the uncommitted draft. Anki's editor/reviewer
WebSocket and `pycmd` bridges are unchanged.

### Browser selection and actions

The card Browser keeps its selection in the numeric `selectedCids` signal array.
Single clicks, Ctrl/Cmd toggles, Shift ranges, highlighting, selection counts, and
action availability share that state. Shift-click without an anchor selects one
card. Searches and successful mutations reset the selection and stale details.

Deck and tag sidebar entries have real `/browse?q=...` links. Anki's search builder
escapes literal names, and the server URL-encodes the query, including quotes,
wildcards, Unicode, and URL-special characters. All deck and tag clicks perform
native browser navigation, keeping the address bar, search query, and browser
history (back/forward) in sync. Native modified or middle clicks open new tabs
while preserving the original tab. Links can be copied and bookmarked. The search
form and browser actions remain Datastar-powered, while the obsolete
`/browse/searchdeck/{did}` and `/browse/searchtag` handlers are removed.

Browser action requests submit `selectedCids` directly; the cached bridge selection
is only a mirror for legacy consumers, never the authority for an HTTP mutation.
`query` is the editable search draft; `browserQuery` is the applied filter used when
refreshing results after an action. Due dates, deck changes, tags, and note deletion
use bound native dialog forms. Validation errors preserve the selection and input;
Cancel/Escape make no changes before submission. While a mutation is pending, close
controls are disabled rather than implying that a committed operation can be undone.

Detail responses are guarded against obsolete selections. Image Occlusion and
empty/multiple selections use SSE element patches with selection-specific targets;
regular notes reuse the live editor iframe through its existing `postMessage`
bridge. A new note selection reuses the iframe element but the `ankiwebLoadNid`
listener navigates its document to that note's `/edit?nid=X` URL. Background
`POST /browse/refresh` instead patches rows, match count, and visible-ID metadata;
it preserves the iframe element **and current document**, field focus, selection,
action inputs, and unsubmitted search draft. The edited card stays open even if
its changed content no longer matches the applied filter. Explicit searches and
successful browser actions still reset the detail
pane. Card Info and other page changes remain native links and backend redirects,
with no soft-navigation layer.

## Architecture

ankiweb follows a **Ports & Adapters (hexagonal)** layout — see
[`docs/superpowers/specs/2026-09-12-ankiweb-hexagonal-architecture-design.md`](docs/superpowers/specs/2026-09-12-ankiweb-hexagonal-architecture-design.md)
for the full design (diagrams, ports table, scope decisions) and
[`docs/superpowers/plans/2026-09-12-ankiweb-hexagonal-architecture-migration.md`](docs/superpowers/plans/2026-09-12-ankiweb-hexagonal-architecture-migration.md)
for the migration that built it.

- **`anki` pylib** owns the collection, scheduler (v3), and the Rust backend (protobuf).
- **`ankiweb/core/`** — the framework-free application core; never imports from
  `ankiweb/adapters/` (enforced by `tests/test_architecture_boundaries.py`).
  - **`ports.py`** — the seven `typing.Protocol`s at the core/adapter seam (one outbound
    `CollectionPort` plus `NotificationTransportPort`/`ConfigStorePort`/`ClockPort`; three
    inbound `BridgeCommandPort`/`AnkiConnectDispatchPort`/`BackendRpcPort`).
  - **`bridge/`** — `BridgeHub`, `UiState`: the `pycmd` command dispatcher the WebSocket
    adapter calls into.
  - **`ankiconnect_actions/`** — the ≈120 AnkiConnect action handlers (`actions/`,
    `extra_actions/`), the `ACTIONS`/`ACTION_SPECS` registry, and `Runtime`.
  - **`rpc/`** — `dispatch_backend_rpc`: the passthrough/custom/concurrent routing decision
    for `/_anki/{method}`, plus the passthrough method lists and custom handlers.
  - **`notify/engine.py`**, **`auth.py`**, **`i18n.py`**, **`config.py`**,
    **`op_changes.py`** — pure supporting modules.
- **`ankiweb/adapters/outbound/`** — `anki_collection_adapter.py` (`CollectionService`,
  the single-worker serialized wrapper around the one `Collection`; an auxiliary pool runs
  the thread-safe Rust calls that must be concurrent, e.g. FSRS compute/simulate); the
  notifier's `httpx_notification_adapter.py` + `json_config_store.py`.
- **`ankiweb/adapters/inbound/`** — one package per integration pattern:
  - **`ws_bridge/`** — the WebSocket `/ws` `pycmd` bridge the screens use to talk to the
    server (the desktop `pycmd`/`bridgeCommand` shim, in `shell_src/bootstrap.ts`).
  - **`http_ankiconnect/`** — the typed AnkiConnect REST surface + CORS.
  - **`http_screens/`** — the bridge-backed screens (reviewer, editor, add) that mount
    Anki's real `reviewer.js` / `editor.js`.
  - **`http_datastar/`** — the ten Datastar SSR/SSE screens (deck browser, overview,
    browser, card layout, custom study, filtered deck, fields, notetypes, preferences,
    tools); each route calls `CollectionPort` directly (no dedicated inbound port — see the
    spec's Scope section for why).
  - **`http_shared/`** — routing/templating infrastructure shared by every screen (routes,
    Jinja templating, page shell, about, export, preview, congrats, type-answer, notify).
  - **`rpc_passthrough/`** — the thin `POST /_anki/{method}` FastAPI route over
    `core/rpc/dispatch.py`, used by reviewer.js and backend operations.
  - **`http_pages/`** — pure Jinja + Datastar page routers (graphs, deck options, card info,
    change notetype, image occlusion, import, editor/add).
- **`ankiweb/assets.py`** — serves static assets under `/_anki/...` (reviewer.js, MathJax, fonts).
- **`ankiweb/app.py`**, **`ankiweb/ankiconnect/app.py`**, **`ankiweb/__main__.py`** —
  composition roots: wire adapters to core and run the Web app + AnkiConnect app as two
  uvicorn servers on a shared collection + bridge hub.

## Test

```bash
uv sync --extra dev      # project dependencies and test tools in .venv
uvx ruff check .         # lint all Python sources and tests
uvx pyright              # type-check using the project's .venv
uv run pytest            # full suite (Playwright tests skip if chromium absent)
```

Integration tests use Playwright + real Chromium against a live uvicorn server; install the
browser once with `python -m playwright install chromium`.

Pyright's Python 3.12 environment is configured in `pyproject.toml`; run these commands
from the repository root so imports resolve against the installed project dependencies.

## Project layout

```
ankiweb/            the application package (core, adapters/{inbound,outbound}, assets, ankiconnect)
shell_src/          the TS pycmd-bridge shell (compiled to ankiweb/shell/static/bootstrap.js)
tools/              fetch_web_assets.py (vendor the frontend), build_shell.mjs (build the shell)
tests/              pytest suite (backend + bridge + Playwright integration)
docs/superpowers/   design specs + implementation plans
```

## License

ankiweb is licensed under the **GNU Affero General Public License, version 3 or later
(AGPL-3.0-or-later)** — see [LICENSE](LICENSE).

It is a **derivative/combined work**: it links the **Anki** Python library (`anki`,
AGPL-3.0-or-later) at runtime, bundles and serves Anki's compiled frontend, and
re-implements the **AnkiConnect** HTTP API (Copyright 2016–2021 Alex Yatskov,
GPL-3.0-or-later) by closely following its source. Per GPLv3 §13 / AGPLv3 §13 these combine,
and the project as a whole is distributed under AGPL-3.0-or-later. Upstream copyrights and
the permissive sub-licenses of vendored components (MathJax/Apache-2.0, jQuery/MIT,
protobuf.js/BSD-3, etc.) are credited in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md);
the GPL-3.0 text covering the AnkiConnect-derived code is in
[LICENSES/GPL-3.0-or-later.txt](LICENSES/GPL-3.0-or-later.txt).

### Source code (AGPL §13)

Because ankiweb is a network service, every user interacting with it over a network is
entitled to its Corresponding Source. The running app exposes a **Source** link (the top
toolbar → `/about`). Set **`ANKIWEB_SOURCE_URL`** to where your deployed source lives so that
link points at the exact running version; the pinned Anki/aqt 26.9.2 source is at
<https://github.com/ankitects/anki> and AnkiConnect at <https://github.com/FooSoft/anki-connect>.

Copyright (C) 2026 tsc. Anki © Ankitects Pty Ltd and contributors. AnkiConnect © 2016–2021
Alex Yatskov.

> **Naming note:** "ankiweb" collides with Anki's own **AnkiWeb** sync service and trademark.
> The AGPL covers the code but grants no trademark rights; consider renaming before any public
> release to avoid implying endorsement.
