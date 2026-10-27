import math
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from anki.cards import CardId
from anki.collection import Collection
from anki.scheduler.v3 import CardAnswer
from anki.scheduler.v3 import Scheduler as V3Scheduler
from fastapi.testclient import TestClient

from ankiweb.adapters.inbound.http_pages.graph_svg import (
    BandScale,
    LinearScale,
    render_pie_slice,
)
from ankiweb.adapters.inbound.http_pages.graphs import generate_reviews_chart
from ankiweb.app import create_app
from ankiweb.core.config import Settings


@pytest.fixture
def test_col(tmp_path: Path):
    col_path = tmp_path / "graphs_test.anki2"
    col = Collection(str(col_path))
    try:
        nt = col.models.by_name("Basic")
        assert nt is not None
        did = col.decks.id("Default")
        assert did is not None

        # Add 10 cards

        for i in range(10):
            n = col.new_note(nt)
            n["Front"] = f"Question {i}"
            n["Back"] = f"Answer {i}"
            col.add_note(n, did)

        # Answer 5 cards to generate revlog, future due, today stats
        assert isinstance(col.sched, V3Scheduler)
        queued = col.sched.get_queued_cards(fetch_limit=5)
        for qc in queued.cards:
            card = col.get_card(CardId(qc.card.id))
            card.start_timer()
            ans = col.sched.build_answer(
                card=card, states=qc.states, rating=CardAnswer.Rating.GOOD
            )
            col.sched.answer_card(ans)
    finally:
        col.close()
    return col_path


@pytest.fixture
def client(test_col: Path):
    settings = Settings(collection_path=test_col, port=8124)
    with TestClient(create_app(settings)) as c:
        yield c


def test_svg_linear_scale():
    s = LinearScale((0, 100), (0, 500))
    assert s(0) == 0
    assert s(50) == 250
    assert s(100) == 500
    assert s.invert(250) == 50
    ticks = s.ticks(5)
    assert 0 in ticks
    assert 100 in ticks


def test_svg_band_scale():
    bs = BandScale(["a", "b", "c"], (0, 300))
    assert bs.bandwidth > 0
    assert bs("a") < bs("b") < bs("c")


def test_svg_pie_slice():
    d = render_pie_slice(0, math.pi, 100)
    assert d.startswith("M0.00,0.00")
    assert "A100.00,100.00" in d


def test_graphs_page_renders_shell_and_all_graphs(client):
    r = client.get("/graphs")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    text = r.text

    # Controls and shell
    assert "statisticsSearchText" in text
    assert "scope-deck" in text
    assert "scope-col" in text
    assert "days-365" in text
    assert "days-0" in text

    # All graphs sections present
    assert "Today" in text
    assert "Future Due" in text
    assert "Calendar" in text
    assert "Reviews" in text
    assert "Card Counts" in text
    assert "Review Intervals" in text
    assert "Card Ease" in text
    assert "Retention" in text
    assert "Hourly Breakdown" in text
    assert "Answer Buttons" in text
    assert "Added" in text


def test_graphs_update_endpoint_datastar_sse(client):
    r = client.post(
        "/graphs/update",
        headers={"Datastar-Request": "true"},
        json={
            "search": "deck:current",
            "scope": "deck",
            "days": 30,
            "separate_inactive": True,
        },
    )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    body = r.text
    assert "event: datastar-patch-elements" in body
    assert "Today" in body
    assert "Future Due" in body
    assert "Card Counts" in body


def test_graphs_preferences_persistence(client):
    # Toggle separate_inactive to False
    r1 = client.post(
        "/graphs/update",
        headers={"Datastar-Request": "true"},
        json={
            "search": "deck:current",
            "scope": "deck",
            "days": 30,
            "separate_inactive": False,
        },
    )
    assert r1.status_code == 200

    # Read back through GET /graphs
    r2 = client.get("/graphs")
    assert r2.status_code == 200
    # The JSON signals should reflect separate_inactive: false
    assert '"separate_inactive": false' in r2.text


def test_generate_reviews_chart_svg_structure_and_group_balance(test_col: Path):
    col = Collection(str(test_col))
    try:
        g_resp = col._backend.graphs(search="", days=365)
        chart = generate_reviews_chart(g_resp.reviews, days_range=30, show_time=False)
    finally:
        col.close()

    svg_text = chart["svg"]
    root = ET.fromstring(svg_text)
    assert root.tag == "svg"

    # Verify well-formed XML and balanced group tags
    assert svg_text.count("<g") == svg_text.count("</g>")

    # Hover columns group should be parsed cleanly as a direct or descendant child
    hover_groups = [
        elem for elem in root.iter("g") if elem.attrib.get("class") == "hover-columns"
    ]
    assert len(hover_groups) == 1
    # Hover group should not contain nested axis groups from an unclosed or misplaced tag
    assert all(child.tag == "rect" for child in hover_groups[0])
