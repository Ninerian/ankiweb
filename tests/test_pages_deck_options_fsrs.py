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
        cards = []
        for i in range(120):
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
            # Review 4: 7 days later
            t += 7 * 86400 * 1000
            col.db.execute("INSERT INTO revlog VALUES (?, ?, -1, 3, 16, 7, 2500, 6000, 1)", t, cid)
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


def test_optimize_endpoint(client: TestClient):
    payload = {
        "cfg": {
            "desired_retention": 0.9,
            "fsrs_params_6": [],
            "param_search": "deck:TestDeck",
            "relearn_steps": [10],
        },
        "fsrs_health_check": True,
    }
    r = client.post(
        "/deck-options/fsrs/optimize",
        json=payload,
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200
    # Datastar SSE format
    body = r.text
    assert "event: datastar-patch-signals" in body
    assert "fsrsComputing" in body
    assert "fsrs_params_6" in body or "params_optimal" in body or "alert" in body


def test_evaluate_endpoint(client: TestClient):
    # First get default params
    defaults = [0.4, 1.2, 3.1, 15.6, 7.1, 0.5, 1.0, 0.0, 1.5, 0.1, 1.0, 2.0, 0.0, 0.3, 1.5, 0.2, 2.8, 0.2, 0.2]
    payload = {
        "cfg": {
            "desired_retention": 0.9,
            "fsrs_params_6": defaults,
            "param_search": "deck:TestDeck",
        }
    }
    r = client.post(
        "/deck-options/fsrs/evaluate",
        json=payload,
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200
    body = r.text
    assert "event: datastar-patch-signals" in body
    assert "fsrsEvalLogLoss" in body or "Log loss" in body


def test_calculate_retention_endpoint(client: TestClient):
    defaults = [0.4, 1.2, 3.1, 15.6, 7.1, 0.5, 1.0, 0.0, 1.5, 0.1, 1.0, 2.0, 0.0, 0.3, 1.5, 0.2, 2.8, 0.2, 0.2]
    payload = {
        "cfg": {
            "desired_retention": 0.9,
            "fsrs_params_6": defaults,
            "param_search": "deck:TestDeck",
            "learn_steps": [1, 10],
            "relearn_steps": [10],
        },
        "deck_size": 100,
        "days_to_simulate": 365,
    }
    r = client.post(
        "/deck-options/fsrs/calculate-retention",
        json=payload,
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200
    body = r.text
    assert "event: datastar-patch-signals" in body
    assert "fsrsOptimalRetention" in body


def test_workload_endpoint(client: TestClient):
    defaults = [0.4, 1.2, 3.1, 15.6, 7.1, 0.5, 1.0, 0.0, 1.5, 0.1, 1.0, 2.0, 0.0, 0.3, 1.5, 0.2, 2.8, 0.2, 0.2]
    payload = {
        "cfg": {
            "desired_retention": 0.85,
            "fsrs_params_6": defaults,
            "param_search": "deck:TestDeck",
        },
        "previous_dr": 0.90,
    }
    r = client.post(
        "/deck-options/fsrs/workload",
        json=payload,
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200
    body = r.text
    assert "event: datastar-patch-signals" in body
    assert "fsrsWorkloadFactor" in body


def test_abort_endpoint(client: TestClient):
    r = client.post(
        "/deck-options/fsrs/abort",
        json={},
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200
    body = r.text
    assert "event: datastar-patch-signals" in body
    assert '"fsrsComputing": false' in body or '"fsrsComputing":false' in body
