"""Filesystem-JSON implementation of ankiweb.core.ports.ConfigStorePort, for NotifyConfig.
Module-level `load`/`save` functions structurally satisfy ConfigStorePort (a module is a valid
Protocol instance) — no wrapper class needed."""

from __future__ import annotations

import json
from pathlib import Path

from ankiweb.core.notify.engine import NotifyConfig


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
