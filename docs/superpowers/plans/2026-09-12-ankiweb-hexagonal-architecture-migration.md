# ankiweb Hexagonal Architecture Migration — Implementation Plan

> **For agentic workers:** internal restructuring, no wire-format/behavior change. Steps use
> checkbox (`- [ ]`) syntax. Each task ends with the **full test suite green** before starting the
> next — never batch multiple tasks' file moves together. Use `lsp rename_file` for every move
> (rewrites every import automatically); **never** hand-edit an import path after a move.

**Goal:** Restructure `ankiweb` into Ports & Adapters per
`docs/superpowers/specs/2026-09-12-ankiweb-hexagonal-architecture-design.md` — formalize the
seven ports as `typing.Protocol`s, relocate outbound adapters (Anki collection, httpx webhook
POST, JSON config store) and inbound adapters (Datastar screens, bridge-backed screens,
AnkiConnect REST, WS bridge, SvelteKit passthrough) under `ankiweb/adapters/`, consolidate the
pure application core under `ankiweb/core/`, and add an automated test that fails the build if
`ankiweb/core/**` ever imports from `ankiweb/adapters/**`.

**Architecture:** See the spec's three diagrams (structural, dependency-rule, sequence). Summary:
inbound adapters call inbound ports (`BridgeCommandPort`, `AnkiConnectDispatchPort`,
`BackendRpcPort`) implemented by core modules (`BridgeHub`, `dispatch_one`, `core/rpc/dispatch.py`);
those core modules call the one outbound port, `CollectionPort`, implemented by
`adapters/outbound/anki_collection_adapter.py`. The Datastar screens are a fourth inbound
adapter family but call `CollectionPort` directly — see Task 5's note on why they don't get a
dedicated inbound port. The notifier is a second, independent core-to-outbound seam
(`NotificationTransportPort`, `ConfigStorePort`).

**Tech Stack:** Python 3.12, `uv` (already migrated — see
`docs/superpowers/plans/` conda→uv work), `ruff`, `ty`, `wily` (already adopted this session),
`lsp` tool for every rename (`rename_file` for moves, `references` before touching any exported
symbol), `uv run pytest -q` for regression (537 tests at the start of this plan).

**This is a 7-task sequential plan.** Tasks 1–2 touch no file paths (pure additive/behavioral
seam work). Tasks 3–5 are pure `lsp rename_file` moves, zero logic changes, ordered
smallest-blast-radius first — Task 4 moves the WS bridge, AnkiConnect REST, the bridge-backed
screens, and shared screen infra; Task 5 moves the 10 Datastar screens (deferred out of Task 4
deliberately — see Task 4's note). Tasks 6–7 finish the RPC dispatch extraction and core
consolidation. Each task is independently valuable and shippable — stopping after any task
leaves the app fully working.

---

## Task 1: `ankiweb/core/ports.py` — define the seven Protocols, prove three fit today

**Why first:** two of the seven ports (`BridgeCommandPort`, `AnkiConnectDispatchPort`) already
match their current implementer's call shape exactly — proving that in `ty` before any file
moves de-risks the rest of the plan (if the shapes didn't fit, better to find out before, not
during, a physical move). `BackendRpcPort` is declared here too but not proven — it needs a real
extraction (Task 6) before anything satisfies it.

**Files:** New `ankiweb/core/__init__.py`, `ankiweb/core/ports.py`; new
`tests/test_ports_contract.py`.

- [ ] **Step 1 — create the package + ports module:**

```python
# ankiweb/core/ports.py
"""Ports (Cockburn hexagonal architecture): the Protocols ankiweb's application core depends
on (outbound) and is called through (inbound). See
docs/superpowers/specs/2026-09-12-ankiweb-hexagonal-architecture-design.md.

No FastAPI/Starlette/httpx/anki imports here — that is the entire point of this module."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Generic, Protocol, TypeVar

T = TypeVar("T")


# --------------------------------------------------------------------------- outbound ports
class CollectionPort(Protocol):
    """The one seam between ankiweb's core and the `anki` pylib / Rust backend."""

    async def open(self) -> None: ...
    async def close(self) -> None: ...
    async def run(self, fn: Callable[[Any], T]) -> T: ...
    async def run_op(
        self, fn: Callable[[Any], T], initiator: str | None = None
    ) -> T: ...
    async def backend_raw(self, method: str, data: bytes) -> bytes: ...
    async def backend_raw_concurrent(self, method: str, data: bytes) -> bytes: ...
    def subscribe(self, cb: Callable[[Any, str | None], Any]) -> None: ...
    async def emit(self, changes: Any, initiator: str | None) -> None: ...


class NotificationTransportPort(Protocol):
    """Send one webhook POST; returns (status_code, parsed_json_body_or_None)."""

    async def __call__(
        self, url: str, headers: dict[str, str], json: dict
    ) -> tuple[int, Any]: ...


class ConfigStorePort(Protocol[T]):
    """Load/save a small JSON-backed config value at a path."""

    def load(self, path: Any) -> T: ...
    def save(self, value: T, path: Any) -> None: ...


class ClockPort(Protocol):
    def __call__(self) -> float: ...


# --------------------------------------------------------------------------- inbound ports
class BridgeCommandPort(Protocol):
    """What the WebSocket adapter calls into on the core (BridgeHub today)."""

    async def dispatch_cmd(self, ctx: str, arg: str) -> Any: ...
    async def push_call(self, ctx: str, fn: str, args: list) -> None: ...
    async def push_eval(self, ctx: str, js: str) -> None: ...
    def register(self, ctx: str, ws: Any) -> None: ...
    def unregister(self, ctx: str, ws: Any) -> None: ...


class AnkiConnectDispatchPort(Protocol):
    """What the AnkiConnect REST adapter calls into on the core (dispatch_one today)."""

    async def __call__(
        self, rt: Any, req: dict, actions: dict | None = None
    ) -> Any: ...


class BackendRpcPort(Protocol):
    """What the SvelteKit passthrough adapter calls into on the core. Raises LookupError
    for an unknown method — the adapter maps that to HTTP 404."""

    async def __call__(
        self, method: str, body: bytes, hub: Any, service: CollectionPort
    ) -> bytes: ...
```

- [ ] **Step 2 — static proof test** `tests/test_ports_contract.py`:

```python
"""Static-typing proof that today's classes already satisfy ankiweb.core.ports Protocols,
with ZERO shape changes. `ty check` is the real verifier here; pytest only guards against the
module being deleted or the imports rotting."""
from __future__ import annotations
from ankiweb.core.ports import (
    CollectionPort,
    BridgeCommandPort,
    AnkiConnectDispatchPort,
)
from ankiweb.collection_service import CollectionService
from ankiweb.bridge.hub import BridgeHub
from ankiweb.ankiconnect.dispatch import dispatch_one


def _proves_collection_port(svc: CollectionService) -> CollectionPort:
    return svc  # ty FAILS here if CollectionService stops satisfying CollectionPort


def _proves_bridge_command_port(hub: BridgeHub) -> BridgeCommandPort:
    return hub


def _proves_ankiconnect_dispatch_port() -> AnkiConnectDispatchPort:
    return dispatch_one


def test_ports_module_importable():
    assert CollectionPort is not None and BridgeCommandPort is not None
```

- [ ] **Step 3 — verify:**
  - `uvx ty check ankiweb tests/test_ports_contract.py` → 0 diagnostics (this is the load-bearing
    check for this task — if `CollectionService`/`BridgeHub`/`dispatch_one` don't structurally
    satisfy their Protocols, `ty` reports exactly where).
  - `ruff check ankiweb tests` → 0 diagnostics; `ruff format --check ankiweb tests` → clean.
  - `uv run pytest tests/test_ports_contract.py -v` → 1 passed.
  - `uv run pytest -q` → 537 passed (no existing test touched — this task is purely additive).
- [ ] **Step 4 — commit:** `git add ankiweb/core tests/test_ports_contract.py && git commit -m
  "feat(architecture): define core.ports Protocols, prove 3/7 fit today"`.

---

## Task 2: Notifier outbound seam — `NotificationTransportPort` + `ConfigStorePort`

**Why second:** `ankiweb/notifier.py` is the single highest-complexity file (wily cyclomatic
complexity 76) precisely because its pure diff/payload logic, shared state, async runner, **and**
raw `httpx` client are one file. This task extracts the one real I/O method (`_http_post`) and
gives `NotifyConfig` persistence an injected seam — no directory moves yet (that is Task 7); this
task is pure behavior-preserving extraction inside existing files plus two new adapter files.

**Grounded fact (verified by `grep` across `ankiweb/` and `tests/`):** exactly **one** call site
relies on `DeckNotifier(post=None)`'s default (`ankiweb/__main__.py:37`) — every test already
injects a fake `post=`. Exactly **one** test (`test_state_update_persists_and_signals`) calls
`NotifierState.update()` and therefore needs a real `save`; the other 8 `NotifierState(...)` call
sites either never call `.update()` or assign `.config` directly, so they are unaffected by
dropping `NotifyConfig`'s own file I/O.

**Files:** New `ankiweb/adapters/outbound/__init__.py`,
`ankiweb/adapters/outbound/httpx_notification_adapter.py`,
`ankiweb/adapters/outbound/json_config_store.py`; modify `ankiweb/notifier.py`, `ankiweb/__main__.py`;
modify `tests/test_notifier.py` (one test).

- [ ] **Step 1 — failing/characterization test first.** Add to `tests/test_notifier.py`:

```python
def test_state_update_persists_via_injected_store(tmp_path):
    from ankiweb.adapters.outbound import json_config_store

    state = NotifierState(tmp_path / "notify.json", store=json_config_store)
    state.update(NotifyConfig(enabled=True, url="http://x", poll_sec=1, retry_sec=1))
    reloaded = json_config_store.load(tmp_path / "notify.json")
    assert reloaded.enabled and reloaded.url == "http://x"
```

- [ ] **Step 2 — run** `uv run pytest tests/test_notifier.py -k persists_via_injected_store -v`
  → FAIL (`ModuleNotFoundError: ankiweb.adapters`, `TypeError: unexpected keyword 'store'`).
- [ ] **Step 3 — implement the two outbound adapters:**

```python
# ankiweb/adapters/outbound/httpx_notification_adapter.py
"""httpx implementation of ankiweb.core.ports.NotificationTransportPort."""
from __future__ import annotations
from typing import Any
import httpx


async def post(url: str, headers: dict[str, str], json: dict) -> tuple[int, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(url, json=json, headers=headers)
    try:
        body = r.json()
    except Exception:
        body = None
    return r.status_code, body
```

```python
# ankiweb/adapters/outbound/json_config_store.py
"""Filesystem-JSON implementation of ankiweb.core.ports.ConfigStorePort, for NotifyConfig.
Module-level `load`/`save` functions structurally satisfy ConfigStorePort (a module is a valid
Protocol instance) — no wrapper class needed."""
from __future__ import annotations
import json
from pathlib import Path
from ankiweb.notifier import NotifyConfig  # moves to ankiweb.core.notify.engine in Task 7


def load(path: Path) -> NotifyConfig:
    try:
        data = json.loads(Path(path).read_text())
        if not isinstance(data, dict):
            return NotifyConfig()
        scope = str(data.get("scope", "leaf"))
        return NotifyConfig(
            enabled=bool(data.get("enabled", False)),
            url=str(data.get("url", "") or ""),
            token=str(data.get("token", "") or ""),
            poll_sec=float(data.get("poll_sec", 60.0) or 0),
            retry_sec=float(data.get("retry_sec", 30.0) or 0),
            scope=scope if scope in ("leaf", "all") else "leaf",
        )
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return NotifyConfig()


def save(value: NotifyConfig, path: Path) -> None:
    Path(path).write_text(
        json.dumps(
            {
                "enabled": value.enabled,
                "url": value.url,
                "token": value.token,
                "poll_sec": value.poll_sec,
                "retry_sec": value.retry_sec,
                "scope": value.scope,
            },
            indent=2,
        )
    )
```

- [ ] **Step 4 — modify `ankiweb/notifier.py`:**
  - Delete `NotifyConfig.load` and `NotifyConfig.save` (their bodies just moved verbatim above).
  - `NotifierState.__init__` gains `store: Any | None = None` (typed `ConfigStorePort[NotifyConfig]
    | None` once imported — core may reference the Protocol type, never a concrete adapter
    import); when `config is None`, use `store.load(path)` **only if `store` was given**, else
    fall back to the pure default `NotifyConfig()` (no disk I/O without an injected store):
  ```python
  def __init__(self, config_path, config=None, store=None):
      self.config_path = Path(config_path)
      self._store = store
      if config is not None:
          self.config = config
      elif store is not None:
          self.config = store.load(self.config_path)
      else:
          self.config = NotifyConfig()
      self.status = NotifyStatus()
      self.changed = asyncio.Event()
      self.resync_pending = False

  def update(self, config: NotifyConfig) -> None:
      self.config = config
      if self._store is not None:
          self._store.save(config, self.config_path)
      self.changed.set()
  ```
  - `DeckNotifier.__init__`: drop the `post=None` default and the now-dead `_http_post` method —
    `post` becomes a required parameter (`post: Callable[[str, dict, dict], Awaitable[tuple[int,
    Any]]]`), matching every test's existing call already.
- [ ] **Step 5 — update the one production call site,** `ankiweb/__main__.py`:
  ```python
  from ankiweb.adapters.outbound import json_config_store
  from ankiweb.adapters.outbound.httpx_notification_adapter import post as http_post
  ...
  notifier_state = NotifierState(
      settings.collection_path.parent / "notify.json", store=json_config_store
  )
  ...
  notifier = DeckNotifier(
      notifier_state, fetch=lambda: service.run(snapshot), post=http_post
  )
  ```
  And `ankiweb/app.py`'s lifespan default-notifier branch gains the same `store=json_config_store`
  keyword (its `DeckNotifier` is constructed in `__main__.py` only — `app.py` only needs the
  `NotifierState` default to keep loading real config from disk when no notifier is injected).
- [ ] **Step 6 — run to verify pass:**
  `uv run pytest tests/test_notifier.py -v` (all notifier tests, including the new one) → PASS.
  Regression: `uv run pytest tests/test_notifier.py tests/ankiconnect/test_extra_actions.py -q`
  (the extra_actions test also constructs `NotifierState` — confirm unaffected).
  `ruff check ankiweb tests && ruff format --check ankiweb tests && uvx ty check ankiweb` → clean.
  Full suite: `uv run pytest -q` → 537 passed (net one new test → 538).
- [ ] **Step 7 — commit:** `git add -A && git commit -m
  "refactor(notifier): extract httpx + JSON-config outbound adapters behind ports"`.

**Deliberate scope note:** `ankiweb/ankiconnect/config.py`'s `AnkiConnectConfig.load` (env-var +
`ankiconnect.json` merge) is a one-shot startup resolution, not a runtime port call repeated
during request handling — forcing it through `ConfigStorePort` would be ceremony without benefit
(same "refuse needless abstractions" reasoning as the spec's Scope section). Left as-is.

---

## Task 3: Move `CollectionService` → `adapters/outbound/anki_collection_adapter.py`

**Files:** `ankiweb/collection_service.py` → `ankiweb/adapters/outbound/anki_collection_adapter.py`
(rename only — zero body changes; it already structurally satisfies `CollectionPort` per Task 1).

- [ ] **Step 1 —** `lsp references` on `CollectionService` and `op_changes_to_flags` first, to
  confirm the full call-site list matches expectation (screens/*, ankiconnect/actions/*,
  anki_rpc/*, app.py, ankiconnect/app.py, __main__.py, tests/*).
- [ ] **Step 2 —** `lsp rename_file` `ankiweb/collection_service.py` →
  `ankiweb/adapters/outbound/anki_collection_adapter.py` (rewrites every import automatically).
- [ ] **Step 3 — verify:** `ruff check ankiweb tests && uvx ty check ankiweb` → clean (catches any
  import the rename tool couldn't resolve, e.g. a string-based import). `uv run pytest -q` → full
  suite green, same count as Task 2's end state.
- [ ] **Step 4 — commit:** `git add -A && git commit -m
  "refactor(architecture): move CollectionService to adapters/outbound/anki_collection_adapter"`.

---

## Task 4: Move WS bridge, AnkiConnect REST, bridge-backed screens, and shared screen infra

**Files:** `ankiweb/bridge/ws.py` → `ankiweb/adapters/inbound/ws_bridge/ws.py`;
`ankiweb/ankiconnect/rest.py` + `cors.py` → `ankiweb/adapters/inbound/http_ankiconnect/`;
12 files under `ankiweb/screens/` → `ankiweb/adapters/inbound/http_screens/` (`reviewer.py`,
`editor.py`, `add.py`) and `ankiweb/adapters/inbound/http_shared/` (`routes.py`, `templating.py`,
`page.py`, `about.py`, `export.py`, `preview.py`, `congrats.py`, `type_answer.py`, `notify.py`).

**Deliberately deferred:** the 10 Datastar-driven screens (`deckbrowser.py`, `overview.py`,
`browser.py`, `card_layout.py`, `custom_study.py`, `filtered_deck.py`, `fields.py`,
`notetypes.py`, `preferences.py`, `tools.py`) stay at their current `ankiweb/screens/*.py` paths
until Task 5 — that task moves them as their own distinct adapter category, so moving them here
first would mean touching `routes.py`'s imports for them twice.

- [ ] **Step 1 —** `lsp references` on `build_router` (from `bridge/ws.py`) and
  `build_screen_router`/`register_screen_handlers` (from `screens/routes.py`) to confirm the
  composition-root call sites (`app.py`) that need to keep working unchanged.
- [ ] **Step 2 — move the smallest adapter first:** `lsp rename_file`
  `ankiweb/bridge/ws.py` → `ankiweb/adapters/inbound/ws_bridge/ws.py`.
  Verify: `ruff check ankiweb tests && uvx ty check ankiweb` clean; regression
  `uv run pytest tests/test_ws_roundtrip.py tests/test_ws_hardening.py -q` → PASS.
- [ ] **Step 3 — move the AnkiConnect REST adapter:** `lsp rename_file`
  `ankiweb/ankiconnect/rest.py` → `ankiweb/adapters/inbound/http_ankiconnect/rest.py`, then
  `ankiweb/ankiconnect/cors.py` → `ankiweb/adapters/inbound/http_ankiconnect/cors.py`.
  Verify: `uvx ty check ankiweb`; regression
  `uv run pytest tests/ankiconnect/test_app.py tests/ankiconnect/test_cors.py -q` → PASS.
- [ ] **Step 4 — move the remaining 12 screen files (largest, do last within this task):** for
  each of `routes.py`, `templating.py`, `page.py`, `reviewer.py`, `editor.py`, `add.py`,
  `about.py`, `export.py`, `preview.py`, `congrats.py`, `type_answer.py`, `notify.py`,
  `lsp rename_file` to `ankiweb/adapters/inbound/http_screens/<name>.py` (`reviewer.py`,
  `editor.py`, `add.py`) or `ankiweb/adapters/inbound/http_shared/<name>.py` (the other 9).
  Do this as one batch of renames (`routes.py` imports all of them, plus the 10 Datastar screens
  still at their original path — update `routes.py`'s imports for those 10 to stay pointed at
  `ankiweb.screens.<name>` for now; Task 5 repoints them); run the verification only after every
  file has moved.
- [ ] **Step 5 — verify:** `ruff check ankiweb tests && ruff format --check ankiweb tests &&
  uvx ty check ankiweb` → clean. Full suite: `uv run pytest -q` → all passing, same count.
- [ ] **Step 6 — commit:** `git add -A && git commit -m
  "refactor(architecture): move screens/ws/rest inbound adapters under adapters/inbound"`.

---

## Task 5: Move the 10 Datastar-driven screens to `adapters/inbound/http_datastar/`

**Why a separate task, and why no dedicated port:** the spec categorizes Datastar screen
routers as their own inbound adapter, distinct from the bridge-backed screens (Task 4) and the
SvelteKit passthrough (Task 6) — they're a genuinely different integration pattern (HTTP+SSE via
`datastar_py`, no WebSocket, no vendored JS bundle). Unlike `BridgeCommandPort`/
`AnkiConnectDispatchPort`/`BackendRpcPort` — each of which funnels many distinct actions through
ONE shared dispatch entrypoint that benefits from a Protocol boundary — each Datastar route is
already its own small, independent FastAPI handler calling `CollectionPort` directly. Wrapping
that in a further `ScreenActionPort` abstraction and extracting ~45 action functions out of 10
files into a new `core/screen_actions/` package is a substantially larger, separately-decidable
piece of work that was not requested here and would not change any external behavior — this task
is scoped to the move only, matching Task 3's zero-logic-change pattern. Revisit a dedicated
port only if a concrete need (e.g. testing screen actions without HTTP) shows up later.

**Files:** `ankiweb/screens/{deckbrowser,overview,browser,card_layout,custom_study,`
`filtered_deck,fields,notetypes,preferences,tools}.py` (10 files, rename only — zero body
changes) → `ankiweb/adapters/inbound/http_datastar/<same-name>.py`.

- [ ] **Step 1 —** `lsp references` on each `make_<x>_routes` factory (10 total) to confirm the
  only caller is `routes.py`'s `build_screen_router` (now at
  `ankiweb/adapters/inbound/http_shared/routes.py` per Task 4) — no other module reaches into a
  screen file directly.
- [ ] **Step 2 — move all 10 files:** `lsp rename_file` each of `deckbrowser.py`, `overview.py`,
  `browser.py`, `card_layout.py`, `custom_study.py`, `filtered_deck.py`, `fields.py`,
  `notetypes.py`, `preferences.py`, `tools.py` from `ankiweb/screens/` to
  `ankiweb/adapters/inbound/http_datastar/`. Do this as one batch (like Task 4's screen move) —
  `routes.py` imports all 10, so a half-moved state would leave broken imports mid-task; run
  verification only after every file has moved.
- [ ] **Step 3 — verify:** `ruff check ankiweb tests && ruff format --check ankiweb tests &&
  uvx ty check ankiweb` → clean. Full regression: `uv run pytest -q` → 538 passed (same count as
  Task 4's end state — this task is a pure move, no new tests, no behavior change).
- [ ] **Step 4 — commit:** `git add -A && git commit -m
  "refactor(architecture): move Datastar screens to adapters/inbound/http_datastar"`.

---

## Task 6: Extract `core/rpc/dispatch.py` from `anki_rpc/__init__.py`; move the RPC package

**Why this shape:** `anki_rpc/__init__.py`'s route handler mixes FastAPI `Request`/`Response`
plumbing with the actual passthrough/concurrent/custom branch decision — the latter is core
routing logic with no framework dependency once extracted.

**Files:** New `ankiweb/core/rpc/__init__.py`, `ankiweb/core/rpc/dispatch.py`; move
`ankiweb/anki_rpc/passthrough.py` → `ankiweb/core/rpc/passthrough.py`, `ankiweb/anki_rpc/handlers.py`
→ `ankiweb/core/rpc/custom_handlers.py`; new thin adapter
`ankiweb/adapters/inbound/rpc_passthrough/route.py`; delete `ankiweb/anki_rpc/__init__.py`'s body
(package becomes the adapter's home, or removed once the route moves — see Step 4).

- [ ] **Step 1 — failing test first,** add to `tests/test_anki_rpc.py`:
  ```python
  async def test_dispatch_backend_rpc_raises_lookup_error_for_unknown_method(service):
      from ankiweb.core.rpc.dispatch import dispatch_backend_rpc

      with pytest.raises(LookupError):
          await dispatch_backend_rpc("totallyUnknownMethod", b"", hub=None, service=service)
  ```
- [ ] **Step 2 — run** → FAIL (`ModuleNotFoundError: ankiweb.core.rpc`).
- [ ] **Step 3 — implement** `ankiweb/core/rpc/dispatch.py` (the branch logic extracted verbatim
  from today's `anki_rpc/__init__.py`, framework-free):
  ```python
  from __future__ import annotations
  from ankiweb.core.rpc.passthrough import PASSTHROUGH, CONCURRENT, camel_to_snake
  from ankiweb.core.rpc.custom_handlers import CUSTOM


  async def dispatch_backend_rpc(method: str, body: bytes, hub, service) -> bytes:
      """Route one /_anki/<method> call. Raises LookupError for an unknown method — the
      inbound adapter maps that to HTTP 404; any other exception maps to HTTP 500."""
      snake = camel_to_snake(method)
      if method in CUSTOM:
          return await CUSTOM[method](service, body, hub)
      if snake in CONCURRENT:
          return await service.backend_raw_concurrent(snake, body)
      if snake in PASSTHROUGH:
          return await service.backend_raw(snake, body)
      raise LookupError(f"unknown backend RPC method: {method}")
  ```
- [ ] **Step 4 — move the two data/use-case modules:** `lsp rename_file`
  `ankiweb/anki_rpc/passthrough.py` → `ankiweb/core/rpc/passthrough.py`;
  `ankiweb/anki_rpc/handlers.py` → `ankiweb/core/rpc/custom_handlers.py` (update the internal
  `CUSTOM = {...}` dict's registration to match — the rename tool updates imports, not dict
  literals referencing the old module name in comments; do a final `grep -n "anki_rpc"
  ankiweb/core/rpc/custom_handlers.py` sanity check).
- [ ] **Step 5 — rewrite the adapter route** `ankiweb/adapters/inbound/rpc_passthrough/route.py`
  (new file; the old `ankiweb/anki_rpc/__init__.py`'s FastAPI shell, now calling the core
  function and translating `LookupError`/other exceptions to HTTP status codes):
  ```python
  from __future__ import annotations
  from fastapi import APIRouter, Request
  from fastapi.responses import Response, PlainTextResponse
  from ankiweb.core.rpc.dispatch import dispatch_backend_rpc

  BINARY = "application/binary"


  def build_router(get_service, get_hub=None) -> APIRouter:
      router = APIRouter()

      @router.post("/_anki/{method}")
      async def rpc(method: str, request: Request) -> Response:
          if request.headers.get("content-type") != BINARY:
              return PlainTextResponse("bad content type", status_code=403)
          body = await request.body()
          service = get_service()
          hub = get_hub() if get_hub is not None else None
          try:
              out = await dispatch_backend_rpc(method, body, hub, service)
          except LookupError:
              return PlainTextResponse("not found", status_code=404)
          except Exception as exc:
              return PlainTextResponse(str(exc), status_code=500)
          if not out:
              return Response(status_code=204)
          return Response(content=bytes(out), media_type=BINARY)

      return router
  ```
  Delete `ankiweb/anki_rpc/__init__.py`; `lsp references` on `ankiweb.anki_rpc.build_router`
  first to confirm `ankiweb/app.py` is the only importer, then update that one import to
  `ankiweb.adapters.inbound.rpc_passthrough.route`.
- [ ] **Step 6 — verify:** `ruff check ankiweb tests && uvx ty check ankiweb` → clean.
  `uv run pytest tests/test_anki_rpc.py -v` → PASS (including the new LookupError test).
  Full regression: `uv run pytest -q` → all green.
- [ ] **Step 7 — commit:** `git add -A && git commit -m
  "refactor(architecture): extract core/rpc dispatch from anki_rpc, thin FastAPI adapter route"`.

---

## Task 7: Consolidate the remaining core, add the boundary fitness test, update docs

**Files:** Move `ankiweb/bridge/hub.py`, `ui_state.py`, `protocol.py` →
`ankiweb/core/bridge/`; `ankiweb/ankiconnect/actions/*`, `extra_actions/*`, `registry.py`,
`runtime.py` → `ankiweb/core/ankiconnect_actions/` (keeping the `actions`/`extra_actions`
sub-split); `ankiweb/auth.py`, `i18n.py`, `config.py`, `notifier.py` → `ankiweb/core/` (notifier
splits into `core/notify/engine.py` + `core/notify/config.py` per the spec's target layout,
`NotifyConfig` losing its now-removed `.load`/`.save`). New
`tests/test_architecture_boundaries.py`. Modify `README.md`'s Architecture section.

- [ ] **Step 1 — move the bridge package:** `lsp rename_file` each of `ankiweb/bridge/hub.py`,
  `ankiweb/bridge/ui_state.py`, `ankiweb/bridge/protocol.py` into `ankiweb/core/bridge/`.
  Verify: `uvx ty check ankiweb`; regression `uv run pytest tests/test_bridge_hub.py
  tests/test_ui_state.py tests/test_ws_roundtrip.py -q` → PASS.
- [ ] **Step 2 — move the AnkiConnect use-case layer:** `lsp rename_file` every file under
  `ankiweb/ankiconnect/actions/` and `ankiweb/ankiconnect/extra_actions/`, plus `registry.py` and
  `runtime.py`, into `ankiweb/core/ankiconnect_actions/actions/` and
  `ankiweb/core/ankiconnect_actions/extra_actions/` (registry.py/runtime.py at the
  `ankiconnect_actions/` level). Verify: `uvx ty check ankiweb`; regression
  `uv run pytest tests/ankiconnect -q` → PASS (the largest single regression slice — ~180 tests).
- [ ] **Step 3 — move the small pure modules:** `lsp rename_file` `ankiweb/auth.py` →
  `ankiweb/core/auth.py`, `ankiweb/i18n.py` → `ankiweb/core/i18n.py`, `ankiweb/config.py` →
  `ankiweb/core/config.py`. Verify: `uvx ty check ankiweb`; `uv run pytest -q` → full suite green
  (these are imported nearly everywhere, so this is the highest-import-count single move — lean
  on `ty`'s import-resolution check before running pytest).
- [ ] **Step 4 — split and move the notifier:** `lsp rename_file` `ankiweb/notifier.py` →
  `ankiweb/core/notify/engine.py` (one move; `NotifyConfig`/`NotifyStatus`/`NotifierState`/
  `DeckNotifier`/the pure functions all travel together — splitting `NotifyConfig` into its own
  `core/notify/config.py` file is optional polish, not required for the dependency rule, since
  both are already framework-free after Task 2). Update
  `ankiweb/adapters/outbound/json_config_store.py`'s `from ankiweb.notifier import NotifyConfig`
  to `from ankiweb.core.notify.engine import NotifyConfig` (`lsp rename_file` handles this
  automatically as part of the move). Verify: `uv run pytest tests/test_notifier.py -q` → PASS.
- [ ] **Step 5 — the boundary fitness test,** `tests/test_architecture_boundaries.py`:
  ```python
  """Architecture fitness test: ankiweb.core must never import ankiweb.adapters. This is the
  automated enforcement of the hexagonal dependency rule from
  docs/superpowers/specs/2026-09-12-ankiweb-hexagonal-architecture-design.md."""
  from __future__ import annotations
  import ast
  from pathlib import Path

  CORE = Path(__file__).resolve().parent.parent / "ankiweb" / "core"


  def _imported_top_level_modules(path: Path) -> set[str]:
      tree = ast.parse(path.read_text())
      names = set()
      for node in ast.walk(tree):
          if isinstance(node, ast.Import):
              names.update(a.name for a in node.names)
          elif isinstance(node, ast.ImportFrom) and node.module:
              names.add(node.module)
      return names


  def test_core_never_imports_adapters():
      violations = []
      for py_file in CORE.rglob("*.py"):
          for mod in _imported_top_level_modules(py_file):
              if mod.startswith("ankiweb.adapters") or mod == "ankiweb.adapters":
                  violations.append(f"{py_file.relative_to(CORE.parent.parent)} imports {mod}")
      assert not violations, "core -> adapters import(s) found:\n" + "\n".join(violations)
  ```
  Run: `uv run pytest tests/test_architecture_boundaries.py -v` → PASS (proves Tasks 1–7 actually
  achieved the dependency rule, not just moved files around).
- [ ] **Step 6 — update `README.md`'s Architecture section** to describe the new layout (replace
  the current flat bullet list with the ports/adapters/core breakdown), linking the new spec.
- [ ] **Step 7 — full regression + all tools:**
  `ruff check ankiweb tests && ruff format --check ankiweb tests` → clean.
  `uvx ty check ankiweb` → clean.
  `uv run pytest -q` → full suite green (540: the 537 original + one new test each from Task 2
  and Task 6, plus this task's boundary fitness test).
  `uvx wily build ankiweb && uvx wily rank ankiweb cyclomatic.complexity` → confirm
  `ankiweb/notifier.py`'s successor (`core/notify/engine.py`) and the AnkiConnect action files no
  longer top the ranking by a wide margin relative to their new, smaller, single-responsibility
  siblings (informational — not a hard gate; the point was decoupling, not a complexity-number
  target).
- [ ] **Step 8 — commit:** `git add -A && git commit -m
  "refactor(architecture): consolidate ankiweb.core, add boundary fitness test, update README"`.

---

## Acceptance criteria (whole plan)

- Every one of the original 537 tests still passes, unmodified in assertions (only the one
  `NotifierState`/`DeckNotifier` signature-driven test edit from Task 2, plus one new test each
  added in Tasks 2 and 6, plus the Task 7 boundary fitness test).
- `ruff check`, `ruff format --check`, and `uvx ty check ankiweb` are clean after every task, not
  just at the end.
- `tests/test_architecture_boundaries.py` passes, mechanically enforcing "core never imports
  adapters" for all future changes, not just the state at the end of this migration.
- No HTTP route, WebSocket message shape, AnkiConnect JSON envelope, or protobuf passthrough
  format changed — verified by the unmodified existing test suite continuing to pass.
