import pytest
import time
from pathlib import Path
from fastapi.testclient import TestClient

from ankiweb.core.config import Settings
from ankiweb.app import create_app
import anki.collection


def _populate_test_reviews(col_path: Path):
    """Seed collection with realistic cards and reviews for FSRS operations."""
    col = anki.collection.Collection(str(col_path))
    try:
        m = col.models.by_name("Basic")
        assert m is not None
        assert col.db is not None
        deck_id = col.decks.id("TestDeck")
        assert deck_id is not None
        for i in range(100):
            note = col.new_note(m)
            note["Front"] = f"Front {i}"
            note["Back"] = f"Back {i}"
            col.add_note(note, deck_id)

        cards = col.find_cards("deck:TestDeck")
        base_time = int(time.time() * 1000) - 200 * 86400 * 1000

        for idx, cid in enumerate(cards):
            t = base_time + idx * 60000
            # Review 1: Learn
            col.db.execute("INSERT INTO revlog VALUES (?, ?, -1, 3, 1, 0, 2500, 10000, 0)", t, cid)
            # Review 2: 1 day later
            t += 86400 * 1000
            col.db.execute("INSERT INTO revlog VALUES (?, ?, -1, 3, 3, 1, 2500, 8000, 1)", t, cid)
            # Review 3: 3 days later
            t += 3 * 86400 * 1000
            col.db.execute("INSERT INTO revlog VALUES (?, ?, -1, 3, 7, 3, 2500, 7000, 1)", t, cid)
        col.save()
    finally:
        col.close()


@pytest.fixture
def client(tmp_path: Path):
    col_path = tmp_path / "test_col.anki2"
    _populate_test_reviews(col_path)
    settings = Settings(collection_path=col_path)
    with TestClient(create_app(settings)) as c:
        yield c


def test_run_simulator_endpoint(client: TestClient):
    payload = {
        "cfg": {
            "desired_retention": 0.9,
            "new_per_day": 20,
            "reviews_per_day": 200,
            "maximum_review_interval": 36500,
            "easy_days_percentages": [1.0] * 7,
            "review_order": 0,
        },
        "simDaysToSimulate": 30,
        "simDeckSize": 50,
        "simDesiredRetention": 0.9,
        "simNewLimit": 20,
        "simReviewLimit": 200,
        "simMaxInterval": 36500,
        "simSubgraph": "count",
        "simSmooth": True,
        "simHistory": [],
    }
    r = client.post("/deck-options/sim/run-simulator", json=payload, headers={"Datastar-Request": "true"})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    text = r.text
    assert "datastar-patch-signals" in text
    assert "simHistory" in text
    assert "simChartContainer" in text
    assert "<svg" in text
    assert "sim-lines" in text


def test_run_workload_endpoint(client: TestClient):
    payload = {
        "cfg": {
            "desired_retention": 0.9,
            "new_per_day": 20,
            "reviews_per_day": 200,
            "maximum_review_interval": 36500,
            "easy_days_percentages": [1.0] * 7,
            "review_order": 0,
        },
        "workloadDaysToSimulate": 30,
        "workloadDeckSize": 50,
        "workloadNewLimit": 20,
        "workloadReviewLimit": 9999,
        "workloadMaxInterval": 36500,
        "workloadSubgraph": "ratio",
        "workloadHistory": [],
    }
    r = client.post("/deck-options/sim/run-workload", json=payload, headers={"Datastar-Request": "true"})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    text = r.text
    assert "datastar-patch-signals" in text
    assert "workloadHistory" in text
    assert "workloadChartContainer" in text
    assert "<svg" in text
    assert "workload-lines" in text


def test_clear_simulation_and_workload(client: TestClient):
    # Test clear-simulation
    payload_sim = {
        "simHistory": [
            {"label": 1, "days": 30, "counts": [10] * 30, "time_costs": [100] * 30, "memorized": [5] * 30}
        ],
        "simSubgraph": "count",
        "simSmooth": True,
    }
    r = client.post("/deck-options/sim/clear-simulation", json=payload_sim, headers={"Datastar-Request": "true"})
    assert r.status_code == 200
    assert "simHistory" in r.text
    assert "No simulation data" in r.text

    # Test clear-workload
    payload_w = {
        "workloadHistory": [
            {"label": 1, "days": 30, "cost": {70: 100}, "memorized": {70: 10}, "review_count": {70: 5}}
        ],
        "workloadSubgraph": "ratio",
    }
    r = client.post("/deck-options/sim/clear-workload", json=payload_w, headers={"Datastar-Request": "true"})
    assert r.status_code == 200
    assert "workloadHistory" in r.text
    assert "No workload data" in r.text


def test_switch_subgraph(client: TestClient):
    payload = {
        "simMode": "review",
        "simHistory": [
            {"label": 1, "days": 10, "counts": [5] * 10, "time_costs": [50] * 10, "memorized": [2] * 10}
        ],
        "simSubgraph": "time",
        "simSmooth": False,
    }
    r = client.post("/deck-options/sim/switch-subgraph", json=payload, headers={"Datastar-Request": "true"})
    assert r.status_code == 200
    assert "simChartContainer" in r.text
    assert "<svg" in r.text


def test_save_sim_to_preset(client: TestClient):
    payload = {
        "cfg": {
            "desired_retention": 0.85,
            "new_per_day": 10,
            "reviews_per_day": 100,
        },
        "simMode": "review",
        "simNewLimit": 30,
        "simReviewLimit": 300,
        "simMaxInterval": 180,
        "simDesiredRetention": 0.92,
        "simReviewOrder": 1,
        "simSuspendLeeches": True,
        "simLeechThreshold": 6,
    }
    r = client.post("/deck-options/sim/save-sim-to-preset", json=payload, headers={"Datastar-Request": "true"})
    assert r.status_code == 200
    assert "datastar-patch-signals" in r.text
    assert "dirty" in r.text
