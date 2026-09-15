"""Deck push notifier — an ankiweb-original feature (not part of the Anki/AnkiConnect port).

Watches deck *learnability* (does a deck have cards to study right now) via the efficient
`deck_due_tree()` and POSTs a notification whenever a deck flips learnable<->not. Configured
live from the web UI (Extras menu), persisted to a `notify.json` sidecar. See
docs/superpowers/specs/2026-06-04-deck-push-notifier-design.md.
"""

from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional


# ---------------------------------------------------------------------------- config + status
@dataclass
class NotifyConfig:
    enabled: bool = False
    url: str = ""
    token: str = ""  # bearer token; omitted from the request when empty
    poll_sec: float = 60.0  # deck_due_tree() refresh cadence
    retry_sec: float = 30.0  # resend cadence after a failed POST
    scope: str = "leaf"  # "leaf" = only decks with no subdecks; "all" = every level

    def active(self) -> bool:
        """The notifier acts only when fully configured."""
        return bool(
            self.enabled and self.url and self.poll_sec > 0 and self.retry_sec > 0
        )


@dataclass
class NotifyStatus:
    last_attempt_ts: Optional[float] = None
    last_success_ts: Optional[float] = None
    last_error: str = ""
    watching: int = 0  # decks currently tracked
    learnable: int = 0  # of those, how many are learnable now
    pending: int = 0  # decks whose change is not yet acknowledged


class NotifierState:
    """Shared between the web form (edits config, reads status) and the background runner
    (reads config, writes status). Single process / single event loop, so no locking."""

    def __init__(
        self,
        config_path: Path,
        config: Optional[NotifyConfig] = None,
        store: Any | None = None,
    ):
        self.config_path = Path(config_path)
        self._store = store
        if config is not None:
            self.config = config
        elif store is not None:
            self.config = store.load(self.config_path)
        else:
            self.config = NotifyConfig()
        self.status = NotifyStatus()
        self.changed = asyncio.Event()  # set by update() to wake the runner immediately
        self.resync_pending = (
            False  # set by request_resync() -> runner drops its baseline
        )

    def update(self, config: NotifyConfig) -> None:
        self.config = config
        if self._store is not None:
            self._store.save(config, self.config_path)
        self.changed.set()

    def request_resync(self) -> None:
        """Ask the runner to re-push every currently-learnable deck (drop its baseline)."""
        self.resync_pending = True
        self.changed.set()


# ---------------------------------------------------------------------------- pure logic
def learnable(counts: dict) -> bool:
    return (
        counts.get("new_count", 0)
        + counts.get("learn_count", 0)
        + counts.get("review_count", 0)
    ) > 0


def header_safe(token: str) -> bool:
    """A Bearer token must be encodable into an HTTP header (latin-1), or httpx raises on
    every send — a forever-failing config. Used to reject such tokens at config-set time."""
    try:
        ("Bearer " + (token or "")).encode("latin-1")
        return True
    except UnicodeEncodeError:
        return False


def counts_sig(counts: dict) -> tuple:
    """The (new, learn, review) tuple — the value a deck's notification state is keyed on.
    A change in ANY of the three (incl. bucket shifts that keep the total) triggers a notify."""
    return (
        counts.get("new_count", 0),
        counts.get("learn_count", 0),
        counts.get("review_count", 0),
    )


def snapshot(col) -> dict:
    """{full_deck_name: {deck_id, new_count, learn_count, review_count}} from deck_due_tree().
    One backend call for the whole tree — scales to thousands of decks. The synthetic root
    (deck_id 0) is skipped; full names disambiguate same-named subdecks."""
    out: dict[str, dict] = {}

    def walk(node):
        did = node.deck_id
        if did:
            out[col.decks.name(did)] = {
                "deck_id": did,
                "new_count": node.new_count,
                "learn_count": node.learn_count,
                "review_count": node.review_count,
                "is_leaf": not node.children,  # a deck with no subdecks
            }
        for child in node.children:
            walk(child)

    walk(col.sched.deck_due_tree())
    return out


def diff_changes(current: dict, last_notified: dict) -> list:
    """Decks whose (new, learn, review) counts differ from what the receiver last acknowledged.
    `last_notified` maps full name -> the acknowledged counts tuple; an absent deck is treated
    as (0, 0, 0), so an empty baseline makes every deck with any nonzero count a change (the
    startup push) while always-empty decks stay silent."""
    changes = []
    for name, counts in current.items():
        sig = counts_sig(counts)
        if sig != last_notified.get(name, (0, 0, 0)):
            changes.append(
                {
                    "deck": name,
                    "deckId": counts["deck_id"],
                    "learnable": sum(sig) > 0,
                    "new_count": counts["new_count"],
                    "learn_count": counts["learn_count"],
                    "review_count": counts["review_count"],
                }
            )
    return changes


def build_payload(changes: list, ts: float) -> dict:
    return {"source": "ankiweb", "ts": int(ts), "changes": changes}


def eval_response(status_code: int, body: Any) -> tuple:
    """Success == HTTP 200 AND a JSON body with `ok` exactly true. Returns (ok, error)."""
    if status_code != 200:
        return False, f"HTTP {status_code}"
    if not isinstance(body, dict) or body.get("ok") is not True:
        return False, 'response was not {"ok": true}'
    return True, ""


def adapt_transport(
    transport: Callable[..., Awaitable[tuple]],
) -> Callable[..., Awaitable[tuple]]:
    """Adapt a `NotificationTransportPort`-shaped callable (`async (url, headers, json) ->
    (status_code, body)`) into the `async (cfg, payload) -> (ok, error)` shape `DeckNotifier.post`
    expects: builds the `Authorization: Bearer <token>` header from `cfg.token`, then interprets
    the raw HTTP response via `eval_response`. This is the adapting logic the old, deleted
    `DeckNotifier._http_post` used to inline alongside its own httpx call — now the raw transport
    lives in `ankiweb.adapters.outbound.httpx_notification_adapter.post`, and this function is
    the seam that reconnects it to `DeckNotifier`."""

    async def _post(cfg: NotifyConfig, payload: dict) -> tuple:
        headers = {"Authorization": "Bearer " + cfg.token} if cfg.token else {}
        status_code, body = await transport(cfg.url, headers, payload)
        return eval_response(status_code, body)

    return _post


# ---------------------------------------------------------------------------- async runner
class DeckNotifier:
    def __init__(
        self,
        state: NotifierState,
        fetch: Callable[[], Awaitable[dict]],
        post: Callable[..., Awaitable[tuple]],
        now: Callable[[], float] = time.time,
    ):
        self.state = state
        self._fetch = fetch  # async () -> snapshot dict
        self._post = post  # async (cfg, payload) -> (ok, error)
        self._now = now
        self.last_notified: dict[
            str, tuple
        ] = {}  # deck name -> acknowledged (new, learn, review)
        self._last_sig = (
            None  # (url, scope): a change re-syncs the receiver from scratch
        )

    async def run(self) -> None:
        try:
            while True:
                cfg = self.state.config
                if not cfg.active():
                    self.last_notified = {}
                    self._last_sig = None
                    st = self.state.status
                    st.watching = st.learnable = st.pending = (
                        0  # don't show stale counts
                    )
                    await self._wait(None)  # idle until the config changes
                    continue
                sig = (cfg.url, cfg.scope)
                if sig != self._last_sig or self.state.resync_pending:
                    self.last_notified = {}  # (re)pointed, scope changed, or manual resync
                    self._last_sig = sig
                    self.state.resync_pending = False
                try:
                    delay = await self._tick(cfg)
                except Exception as exc:  # a fetch/backend error must NOT kill the task
                    self.state.status.last_error = str(exc)
                    delay = cfg.retry_sec
                await self._wait(delay)
        except asyncio.CancelledError:
            pass

    async def _tick(self, cfg: NotifyConfig) -> float:
        """One observe-diff-send cycle. Returns how long to wait before the next cycle."""
        current = await self._fetch()
        if cfg.scope == "leaf":
            # only the last-level decks (no subdecks); switching scope makes filtered-out
            # decks vanish from `current`, so the prune step drops them silently.
            current = {n: c for n, c in current.items() if c.get("is_leaf", True)}
        st = self.state.status
        st.watching = len(current)
        st.learnable = sum(1 for c in current.values() if learnable(c))
        # Decks that vanished from deck_due_tree() since the last notify. deck_due_tree() prunes
        # EMPTIED decks (0 cards) the same as deleted/renamed ones, so "gone" means "0 learnable
        # cards now" in every case. If we last told the receiver a nonzero count, push (0,0,0) to
        # zero its cached count — otherwise an emptied deck leaves the receiver waking on a
        # phantom due forever (its new-card interrupter fires on a count fetch can never satisfy).
        # Decks already acknowledged at (0,0,0) just drop silently.
        gone = set(self.last_notified) - set(current)
        gone_changes = [
            {
                "deck": name,
                "deckId": 0,
                "learnable": False,
                "new_count": 0,
                "learn_count": 0,
                "review_count": 0,
            }
            for name in gone
            if self.last_notified[name] != (0, 0, 0)
        ]
        for name in gone:
            if self.last_notified[name] == (0, 0, 0):
                del self.last_notified[name]  # already zero + gone -> nothing to send
        changes = diff_changes(current, self.last_notified) + gone_changes
        st.pending = len(changes)
        if not changes:
            return cfg.poll_sec
        if self.state.config is not cfg:
            # config was edited (url/token/disable/intervals) during the fetch await — don't
            # POST to a stale target; run()'s next iteration re-reads config and re-baselines.
            return cfg.poll_sec
        st.last_attempt_ts = self._now()
        ok, err = await self._safe_post(cfg, build_payload(changes, self._now()))
        if ok:
            for ch in changes:
                if ch["deck"] in gone:
                    self.last_notified.pop(ch["deck"], None)  # zero-out acked -> forget
                else:
                    self.last_notified[ch["deck"]] = counts_sig(ch)
            st.last_success_ts = self._now()
            st.last_error = ""
            st.pending = 0
            return cfg.poll_sec
        # failure: leave last_notified untouched so the next cycle re-sends the LATEST state
        st.last_error = err
        return cfg.retry_sec

    async def _safe_post(self, cfg: NotifyConfig, payload: dict) -> tuple:
        try:
            return await self._post(cfg, payload)
        except Exception as exc:  # connection error, timeout, etc. -> retry
            return False, str(exc)

    async def _wait(self, timeout: Optional[float]) -> None:
        try:
            await asyncio.wait_for(self.state.changed.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        self.state.changed.clear()
