# ankiweb/core/ports.py
"""Ports (Cockburn hexagonal architecture): the Protocols ankiweb's application core depends
on (outbound) and is called through (inbound). See
docs/superpowers/specs/2026-09-12-ankiweb-hexagonal-architecture-design.md.

No FastAPI/Starlette/httpx/anki imports here — that is the entire point of this module."""

from __future__ import annotations
from typing import Any, Callable, Protocol, TypeVar

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

    async def __call__(self, rt: Any, req: dict, actions: dict = ...) -> Any: ...


class BackendRpcPort(Protocol):
    """What the SvelteKit passthrough adapter calls into on the core. Raises LookupError
    for an unknown method — the adapter maps that to HTTP 404."""

    async def __call__(
        self, method: str, body: bytes, hub: Any, service: CollectionPort
    ) -> bytes: ...
