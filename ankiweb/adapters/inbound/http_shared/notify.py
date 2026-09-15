"""Web form + status panel for the deck push notifier (Extras menu).

ankiweb-original feature — labels are intentionally English/keyless (like "Source"), not Anki
translation keys."""

from __future__ import annotations
import time

from ankiweb.notifier import NotifyConfig
from ankiweb.adapters.inbound.http_shared import templating


def config_from_form(
    enabled: bool,
    url: str,
    token: str,
    poll_sec: float,
    retry_sec: float,
    scope: str = "leaf",
) -> NotifyConfig:
    return NotifyConfig(
        enabled=bool(enabled),
        url=(url or "").strip(),
        token=(token or "").strip(),
        poll_sec=float(poll_sec or 0),
        retry_sec=float(retry_sec or 0),
        scope=scope if scope in ("leaf", "all") else "leaf",
    )


def _fmt_ts(ts) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else "—"


def _num(v) -> str:
    try:
        return f"{float(v):g}"
    except (ValueError, TypeError):
        return str(v)


_SCHEMA_DOC = (
    "POST &lt;url&gt;\n"
    "Authorization: Bearer &lt;token&gt;        # omitted when token is empty\n"
    "Content-Type: application/json\n\n"
    '{ "source": "ankiweb", "ts": 1780500000,\n'
    '  "changes": [\n'
    '    { "deck": "A::B", "deckId": 17800, "learnable": true,\n'
    '      "new_count": 12, "learn_count": 3, "review_count": 40 } ] }\n\n'
    "Success = HTTP 200 AND a JSON body with `ok` exactly true; anything else is retried."
)


def render_notify_html(state, error: str = "", form=None) -> str:
    cfg: NotifyConfig = state.config
    st = state.status
    # On a rejected save, prefill from the submitted values (so input isn't lost); else config.
    src = (
        form
        if form is not None
        else {
            "enabled": cfg.enabled,
            "url": cfg.url,
            "token": cfg.token,
            "poll_sec": cfg.poll_sec,
            "retry_sec": cfg.retry_sec,
            "scope": cfg.scope,
        }
    )
    scope = src.get("scope", "leaf")
    return templating.render(
        "notify.html.jinja",
        error=error,
        url=str(src.get("url", "")),
        token=str(src.get("token", "")),
        poll_sec=_num(src.get("poll_sec", 60)),
        retry_sec=_num(src.get("retry_sec", 30)),
        enabled_checked=bool(src.get("enabled")),
        leaf_selected=(scope != "all"),
        all_selected=(scope == "all"),
        active=cfg.active(),
        watching=st.watching,
        learnable=st.learnable,
        pending=st.pending,
        last_attempt=_fmt_ts(st.last_attempt_ts),
        last_success=_fmt_ts(st.last_success_ts),
        last_error=st.last_error or "—",
        schema_doc=_SCHEMA_DOC,
    )
