from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from datastar_py.fastapi import (
    DatastarResponse,
)
from datastar_py.fastapi import (
    ServerSentEventGenerator as SSE,
)
from datastar_py.sse import DatastarEvent
from fastapi import APIRouter

from ankiweb.adapters.inbound.http_datastar.common import signals_response

router = APIRouter(prefix="/dev")


async def _simulate_progress_events() -> AsyncGenerator[DatastarEvent, None]:
    """Simulate a long-running backend task emitting progress events via Datastar SSE.
    
    In a real operation (e.g. FSRS parameter computation or media checking),
    the background worker runs concurrently and periodically updates progress
    (or writes to `latest_progress` in the Rust backend / auxiliary pool).
    The Datastar SSE generator yields patched elements and signals to the client.
    """
    stages = [
        (0.1, "Initializing task..."),
        (0.25, "Analyzing collection cards (1,250 / 5,000)..."),
        (0.50, "Optimizing parameters (iteration 25 / 50)..."),
        (0.75, "Validating retention curves (3,750 / 5,000)..."),
        (0.90, "Finalizing changes..."),
        (1.0, "Complete!"),
    ]
    
    # 1. Reset / set initial state
    yield SSE.patch_signals({"progressRunning": True, "progressDone": False, "progressError": ""})
    
    for fraction, label in stages:
        await asyncio.sleep(0.35)
        pct = int(fraction * 100)
        yield SSE.patch_signals({
            "progressFraction": fraction,
            "progressPercent": pct,
            "progressLabel": label,
        })
    
    await asyncio.sleep(0.2)
    # Signal completion
    yield SSE.patch_signals({"progressRunning": False, "progressDone": True})


@router.post("/progress/simulate")
async def simulate_progress() -> DatastarResponse:
    """Datastar SSE stream simulating backend progress."""
    return DatastarResponse(_simulate_progress_events())


@router.post("/progress/reset")
async def reset_progress() -> DatastarResponse:
    return signals_response({
        "progressRunning": False,
        "progressDone": False,
        "progressFraction": 0.0,
        "progressPercent": 0,
        "progressLabel": "Idle",
        "progressError": "",
    })
