"""Static-typing proof that today's classes already satisfy ankiweb.core.ports Protocols,
with ZERO shape changes. `ty check` is the real verifier here; pytest only guards against the
module being deleted or the imports rotting."""

from __future__ import annotations

from ankiweb.adapters.outbound.anki_collection_adapter import CollectionService
from ankiweb.ankiconnect.dispatch import dispatch_one
from ankiweb.core.bridge.hub import BridgeHub
from ankiweb.core.ports import (
    AnkiConnectDispatchPort,
    BridgeCommandPort,
    CollectionPort,
)


def _proves_collection_port(svc: CollectionService) -> CollectionPort:
    return svc  # ty FAILS here if CollectionService stops satisfying CollectionPort


def _proves_bridge_command_port(hub: BridgeHub) -> BridgeCommandPort:
    return hub


def _proves_ankiconnect_dispatch_port() -> AnkiConnectDispatchPort:
    return dispatch_one


def test_ports_module_importable():
    assert CollectionPort is not None and BridgeCommandPort is not None
