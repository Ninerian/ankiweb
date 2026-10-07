import threading
import time
from pathlib import Path

import pytest
import uvicorn
from anki.cards import CardId
from anki.collection import Collection
from anki.scheduler.v3 import Scheduler as V3Scheduler

from ankiweb.app import create_app
from ankiweb.core.config import Settings

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright


@pytest.fixture
def live_server_graphs(tmp_path: Path):
    col_path = tmp_path / "g.anki2"
    col = Collection(str(col_path))
    try:
        nt = col.models.by_name("Basic")
        assert nt is not None
        did = col.decks.id("Default")
        assert did is not None
        for q in ("a", "b", "c"):
            n = col.new_note(nt)
            n["Front"] = q
            n["Back"] = q
            col.add_note(n, did)
        from anki.scheduler.v3 import CardAnswer

        assert isinstance(col.sched, V3Scheduler)
        queued = col.sched.get_queued_cards(fetch_limit=1)
        if queued.cards:
            top = queued.cards[0]
            c = col.get_card(CardId(top.card.id))
            c.start_timer()
            ans = col.sched.build_answer(
                card=c, states=top.states, rating=CardAnswer.Rating.GOOD
            )
            col.sched.answer_card(ans)
    finally:
        col.close()
    settings = Settings(collection_path=col_path, port=8130)
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings), host="127.0.0.1", port=8130, log_level="warning"
        )
    )
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("server did not start")
        time.sleep(0.05)
    yield "http://127.0.0.1:8130"
    server.should_exit = True
    t.join(timeout=5)


def test_graphs_spa_boots(live_server_graphs):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on(
            "requestfailed",
            lambda r: (
                errors.append("REQFAIL " + r.url)
                if ("/_app/" in r.url or "/_anki/" in r.url)
                else None
            ),
        )
        page.goto(f"{live_server_graphs}/graphs")
        page.wait_for_selector(".graphs-container", timeout=10000)
        page.wait_for_function(
            "document.querySelectorAll('.graphs-container svg').length>=1",
            timeout=10000,
        )
        assert not errors, errors
        browser.close()
