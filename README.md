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
| **Web UI (HTTP/Datastar + reviewer WebSocket)** | Browser UI over HTTP; the `/ws` bridge shares the UI port and the active native reviewer opts into it | `127.0.0.1:8000` | `ANKIWEB_HOST` / `ANKIWEB_PORT` |
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
- Browse's **Change Notetype** action is a native GET link to `/change-notetype?cids=<comma-separated positive card IDs>`, generated by the backend from the canonical selected card IDs. The server resolves each requested card and derives its current note type; no `nids` query or old/new-notetype path is used. With no selected cards, the link is disabled and has no usable destination; the BridgeHub selection mirror is not used to build it.
- **Change Notetype** stacks its Current/New controls on mobile and keeps mapping controls within the viewport. **Cancel** is a native `/browse` link, including on an invalid-selection page. Target and field/template mapping changes are previews; only **Save** converts notes.
- **Fields** uses labeled groups on mobile, keeps controls within the viewport, and clears the bottom navigation. Fields links carry a local `return_to` target: **Cancel** discards the local draft, while **Save** persists it before returning there. An embedded editor returns to the current top-level view, preserving its query and fragment rather than navigating back to the iframe URL. Without a usable return context, Fields falls back to `/notetypes`.
- **Card Layout** keeps a validated same-app return target (including query and fragment) for native Cancel and Save; editor, Add, and embedded Browse capture the top-level URL, while manager links return to `/notetypes`. Mobile form clearance keeps the footer actions reachable above the fixed dock.
- Deckbrowser and Overview options links resolve the normal or filtered options destination while rendering, using the displayed deck's ID and type. They do not re-resolve the globally current deck when clicked.
- Deck Options **Close** is a native `/deckbrowser` link. An unmodified primary click with unsaved changes opens an accessible native `<dialog>` styled with DaisyUI. **Keep editing**, Escape, or a backdrop click closes the dialog without changing the draft; **Discard changes and close** navigates by GET without saving. Modified and middle clicks retain native link behavior, leaving the original tab and its draft intact. No close-confirmation request or `window.location` navigation is needed.
- Package import keeps the native dialog, modal box, title, and header **Close**
  control outside the Datastar replacement target. Completion replaces only the
  options and import actions with results, including error results. The header
  Close button, Escape, and backdrop dismiss the dialog without navigating away;
  successful import results remain available until dismissed.
  Only the content pane scrolls, keeping Close visible in short viewports.
  Both the modal and standalone package import reuse `backend_progress` while the
  Datastar request is pending, hiding the options and import actions. The server
  streams real `latest_progress.importing` stage messages and note/media counters
  through the concurrent backend path while the collection worker imports. Anki
  supplies text rather than a total/percentage here, so the component shows its
  indeterminate spinner without fabricated percentages. Success and error results
  replace the indicator.
- Actions with side effects remain POST: opening a deck selects it, starting study initializes the timebox, and Save/Submit applies or validates changes. Actions that navigate return whole-document Datastar SSE redirects (`common.redirect_response(url)` via `SSE.redirect(target)`); in-page mutations update targeted fragments without soft-routing layers or client router shims. The ten obsolete pure-navigation POST handlers have been removed, with no compatibility aliases.
- Remaining full-page reload endpoints: notetype mutating endpoints (`/notetypes/rename/{ntid}`, `/notetypes/add/{base_ntid}`, `/notetypes/delete/{ntid}`) and deck description save (`/overview/setdesc`) remain explicit deferred Phase 3 reloads. Deckbrowser rename/delete endpoints (`/deckbrowser/rename/{did}`, `/deckbrowser/delete/{did}`) also retain full reloads in Phase 5 without prior explicit deferral. No soft routing is introduced.

#### Transport Responsibilities & Entrypoints

| Layer / Channel | Transport & Format | Responsibilities & Entrypoints | State Authority & Lifecycle |
|---|---|---|---|
| **Datastar Views & In-Page Actions** | HTTP `POST`/`GET`, Datastar SSE (`text/event-stream`), JSON signals | Fragment morphs, signal patches, and dialog workflows (`/deckbrowser`, `/overview`, `/browse`, `/preferences`, `/custom-study`, `/filtered-deck`, `/fields`, `/card-layout`, `/notetypes`, `/change-notetype`, `/image-occlusion`). `/browse` uses server-rendered HTML, native GET search/navigation, and server-returned HTML updates. | These routes use the default disabled shell bridge and open no WebSocket. Collection changes from other clients do not trigger automatic refreshes or reloads. Other views use request signals (e.g. form drafts) as mutation state. `/browse` submits a stateless hidden `#browser-state` form (`browserQuery`, repeated `selectedCids`, `selectionAnchor`) for canonical request state; the backend computes selection, counters, disabled states, and links. Only `_browserBusy` is transient browser signal state. |
| **Modern Note Editor & Add** | HTTP `GET`/`POST`, Datastar SSE signals & elements | Rich editor routes (`GET /edit`, `GET /add`) and in-place field/tag saves: `POST /editor/save-field`, `POST /editor/blur-field`, `POST /editor/save-tags`, `POST /editor/toggle-collapse`, `POST /editor/toggle-sticky`. | Field contents live in Datastar signals (`field_val_<idx>`, `nid`, `tags_str`; `tags` is a template value). Collection changes still broadcast `opchanges` through BridgeHub for connected legacy clients. After successful field-blur or tag persistence, an embedded `/edit` frame sends same-origin `ankiweb:editor-saved` to its parent; `/browse` accepts only its current editor frame, same origin, and expected type, then dispatches the existing serialized `ankiweb:browser-refresh` flow. This local handoff uses no WebSocket or polling. |
| **Native Reviewer & Bridge Commands** | WebSocket `/ws?context=reviewer`, JSON frames | The active native reviewer explicitly opts into the shell bridge for upstream desktop compatibility and timing: `pycmd` commands (`show`, `ans`, `ease1`..`ease4`, `replay`, `play:<side>:<idx>`, `typed:<val>`, `decks`, `mark`, `setflag:<0-4>`, `buryc`, `buryn`, `suspendc`, `suspendn`, `setdue:<spec>`, `forget`, `deletenote`, `undo`, `starttimer`). Card Info and Edit use native navigation links. | Server manages `ReviewerSession` (timer, queued cards, scheduling states). Drives DOM via bridge push calls (`_showQuestion`, `_showAnswer`, `ankiwebSetAnswerBar`). Other Datastar routes keep the shared shell bridge disabled by default. |
| **Reviewer Controls & Audio Runtime** | DOM events, WebSocket commands, HTML5 Audio | Show answer button (`#ansbut` / `.ansbut`), QA element (`#qa`), answer container (`#ankiweb-answer`), ease buttons (`.ease[data-ease='1']`..`[data-ease='4']`), mark/flag (`#_mark`, `#_flag`), type-in (`#typeans`), replay button (`.replay-button`), action wrapper (`#reviewer-actions-bar`), Card Info link (`#reviewer-card-info`), and Edit link (`#reviewer-card-edit`). `i`/`e` activate those native links. Replay calls `pycmd('play:<side>:<idx>')` over `/ws?context=reviewer`. Audio files dispatched via push call `ankiwebPlayAudio` and played sequentially via browser `new Audio(...)`. | Audio playback is a client browser runtime side effect over static files; no WebSocket audio streaming. |
| **MathJax Typesetting & Editor Overlay** | Static assets (`GET /_anki/...`), client DOM custom element | `/_anki/js/mathjax.js`, `/_anki/js/vendor/mathjax/tex-chtml-full.js`, CHTML glyph fonts (cached 1 year). In editor, `<anki-mathjax>` custom element handles inline preview and modal edits; saved delimiters convert to `\[...\]` / `\(...\)`. | Local in-browser rendering runtime; completely decoupled from WebSocket traffic. |
| **Browser Iframe Integration** | Server-rendered HTML and iframe `src` | The backend renders `/browse` `#detail` from selection intent; regular notes use a stable `<iframe id="editor-frame" class="editor-frame" src="/edit?nid=X">`, while Image Occlusion uses its server-rendered detail. Selection changes update the frame `src`; there is no client selection guard. | Selection and detail are backend-computed, including mobile detail opening. Background refresh omits detail unless a selected card was deleted, in which case canonical detail is cleared. |
| **BridgeHub Opchanges (Legacy WebSocket API)** | WebSocket push `{"type":"opchanges","flags":{...},"initiator":str}` | `service.run_op` continues broadcasting collection changes through `BridgeHub.broadcast_opchanges` to connected clients. Datastar pages do not subscribe to opchanges. | External or remote collection changes no longer automatically refresh or reload socketless Datastar pages. The server-side bridge API remains available to legacy clients; no polling or replacement persistent SSE transport is used. |
| **Same-Tab Embedded Editor Refresh** | Same-origin `postMessage` (`ankiweb:editor-saved`) and local DOM event | After successful field-blur or tag persistence, the embedded `/edit` frame notifies its parent. `/browse` accepts only messages from the current `#editor-frame` with the same origin and expected type, then dispatches `ankiweb:browser-refresh` to its existing serialized `POST /browse/refresh` flow. | Only the current parent tab refreshes; failed saves do not notify. This local handoff is not a cross-tab channel or persistent transport. |
| **Selection State & BridgeHub Mirror** | Browser hidden form (`browserQuery`, repeated `selectedCids`, `selectionAnchor`) vs. `hub.ui_state.selected_card_ids` | Browser intent and mutation requests submit form state; the backend computes canonical selection, anchor/range, counters, action availability, and links. Canonical selection requests update the hub mirror for legacy bridge consumers and external AnkiConnect `gui*` actions. | The browser form/request and server-computed state are authoritative. `hub.ui_state.selected_card_ids` and `selected_note_ids` are mirrors only and never supply fallback selection for browser HTTP mutations. |
| **Backend Protobuf RPC** | HTTP `POST /_anki/{method}` (binary protobuf) | Direct binary bridge to Rust backend or custom handlers (`ankiweb/core/rpc/dispatch.py`), including `updateDeckConfigs`, `changeNotetype`, image occlusion mutations, and FSRS computations. | Direct request-response over `application/binary`; bypasses WebSocket bridge. |
| **External AnkiConnect API** | HTTP `POST /` (JSON-RPC) & typed REST `POST /actions/{name}` | External client automation (Yomitan, integrations). Interacts with `CollectionService` and reads `hub.ui_state` to coordinate with live UI. GUI navigation push calls still require a connected bridge client and are not delivered to socketless Datastar pages. | Operates on dedicated port (`8765` by default) independent of browser session lifecycles. |

Reviewer navigation links are server-rendered for the selected card at each `_show_next`. The card-info URL is `/card-info/{cid}` and the edit URL is `/edit?nid={nid}`. The resulting action-bar HTML is the fourth argument to the existing `_showQuestion` push; its registered bridge wrapper updates `#reviewer-actions-bar` before passing the question to Anki's renderer. The initial no-card markup keeps both anchors disabled without `href` attributes, so a previous card destination is never active. The `i` and `e` keyboard shortcuts click these same native links. Their navigation is not sent as `cardinfo` or `edit` `pycmd` commands.

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
draft to the collection; **Cancel** discards it. Card Layout's **Preview** is a native
GET link to `/preview/{nid}` for an existing note of the selected type; when none is
available, Preview is unavailable with an inline hint to add a note. Preview uses the
saved collection state and never submits the uncommitted draft. Modern editor and Add
routes use HTTP/Datastar and do not open WebSockets. The active native reviewer opts
into the WebSocket bridge for commands; reviewer Card Info/Edit navigation uses the
native links described above.

### Browser selection and actions

The Browser has no client-side business-selection signal. Its stateless hidden
`#browser-state` form carries the applied `browserQuery`, repeated `selectedCids`,
and `selectionAnchor`; the backend computes selection, anchor/ranges, counts,
action availability, and links from each intent. Clicking a row selects that card
and opens its note in the editor. Row checkboxes add or remove cards without
replacing the remaining selection; the header checkbox selects or clears all
currently rendered result rows. Checkboxes, highlighting, selection counts, and
action availability stay synchronized. Card Info is available only when exactly
one card is selected; bulk actions use all selected cards. Ctrl/Cmd toggles and
Shift ranges remain available. Shift-click without an anchor selects one card.
Searches and successful mutations reset the selection and stale details.

`browser.html.jinja` composes flat partials: `browser_state` contains the hidden
form; `browser_search` and `browser_sidebar` provide native search/navigation;
`browser_selection`, `browser_rows`, and `browser_results` render backend-provided
selection and results; `browser_actions` and `browser_dialogs` render actions and
dialogs; `browser_detail_shell` hosts selected detail; `browser_runtime` handles
transient busy/refresh wiring, and `browser_styles` supplies presentation.

On mobile, row and select-all checkboxes stay visible with 44×44-pixel tap targets.
Checkbox taps change the selection without opening the editor; tapping the card's
text still opens its note in the mobile editor dialog.

On desktop, the selected-card count has its own reserved row below the action menus, so the
toolbar and results keep their positions when the selection changes or clears. On mobile (<768px),
the selection count renders as a compact badge (e.g. `2/38`) directly in the table header beside
“Alle auswählen”, avoiding vertical layout shifting in the action bar.
Actions use three dropdowns at every screen width: **Learning** (suspend, restore,
reset progress, and due date), **Manage** (deck and tags), and **Cards** (Card Info,
note type, and deletion). Each trigger has a chevron that rotates when open.
Menus remain openable without a selection; unavailable entries stay visible but
disabled, including all actions while a mutation is pending. Only one menu opens
at a time. Outside clicks close it; Escape closes it and returns focus to its trigger.

The **Decks** and **Tags** sidebar sections expand and collapse independently via
their keyboard-accessible headings. Both start expanded. Folding a section also
works inside the mobile sidebar dialog without closing the dialog itself.

Deck and tag sidebar entries are real `/browse?q=...` links. Anki's search builder
escapes literal names, and the server URL-encodes the query, including quotes,
wildcards, Unicode, and URL-special characters. Search uses native `GET /browse?q=...`
navigation, so the address bar and browser history (including back/forward) stay
in sync; modified or middle clicks open new tabs, and links can be copied or
bookmarked. Each navigation loads a new document. UI-only detail-fold state is
document-local and resets on navigation; it is not stored or history-intercepted.
Browser action requests submit the hidden form's `browserQuery`, repeated
`selectedCids`, and `selectionAnchor`; the backend is authoritative for selection
and state. The BridgeHub selection is only a mirror for legacy consumers, never a
fallback for an HTTP mutation. Dialogs open and close through `GET
/browse/dialog/{action}` and `GET /browse/dialog/close`; mutation forms submit their
values, deck, or tag with the current state. Validation errors keep the active
dialog, selection, and input values intact. Cancel/Escape make no changes before
submission. While a mutation is pending, close controls are disabled rather than
implying that a committed operation can be undone.

`#detail` is rendered from backend selection. Regular notes use the stable editor
iframe with `src="/edit?nid=X"`; Image Occlusion and mobile detail opening are also
selected by backend intent, not client-side selection logic. `POST /browse/refresh`
updates results while omitting detail, search, and dialog inputs, so the current
detail and user-entered state stay open; if the selected card was deleted, the
canonical detail is cleared. The edited card stays open even if its changed
content no longer matches the applied filter. A transient root busy state
serializes refreshes and interactions to prevent stale responses from overwriting
newer state. Explicit native searches and successful browser actions still reset
the detail pane. Card Info and other page changes remain native links and backend
redirects, with no soft-navigation layer.

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
  - **`ws_bridge/`** — the WebSocket `/ws` `pycmd` bridge; the active native reviewer opts in through the desktop shim in `shell_src/bootstrap.ts`. Generic server-side bridge APIs remain available to legacy clients.
  - **`http_ankiconnect/`** — the typed AnkiConnect REST surface + CORS.
  - **`http_screens/`** — reviewer and legacy screen handlers/templates. The active `/edit` and `/add` routes use HTTP/Datastar handlers under `http_pages`.
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
uv sync --extra dev
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run complexipy
uv run pytest
```

The project configuration for Ruff, ty, and Complexipy is in `pyproject.toml`. ty automatically discovers the
repository's `.venv`; run these commands from the repository root so it can resolve the project
and its installed dependencies. For migration guidance, see [ty's guide for users coming from
mypy or Pyright](https://docs.astral.sh/ty/coming-from-mypy-or-pyright/).

Ruff includes security rules; exact-rule exceptions are limited to documented test fixtures in
`pyproject.toml`. The AnkiConnect `skipHash` MD5 is a non-security compatibility checksum;
dynamic SQL binds user-supplied values rather than interpolating them.
Asset downloads use HTTP(S)-only clients with finite timeouts. Run generators from the
repository root with `uv run python tools/<script>.py` to use the project's dependencies.

Complexipy checks cognitive complexity in `ankiweb`, `tests`, and `tools`, using the default
threshold of 15. Functions above the threshold, including existing ones, are reported and cause a
nonzero exit. See the [Complexipy usage guide](https://complexipy.com/usage-guide/).
Use `uv run complexipy --suggest-refactors` for recommendations. Keep extracted helpers within
the same limit; preserve behavior rather than adding suppressions or raising the threshold.

Apply Python formatting with `uv run ruff format .`. Before committing Python changes, run
the lint, formatting, and type checks above against the whole repository.
Re-run the complete block after changing Ruff's rule categories or preview settings.

For VS Code, install the `astral-sh.ty` and `charliermarsh.ruff` extensions. Workspace settings
use ty instead of Pylance, with Ruff formatting and lint fixes on explicit save.

Playwright integration tests use real Chromium against a live uvicorn server. Install the browser
once with `uv run python -m playwright install chromium`.

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
