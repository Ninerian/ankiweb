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
