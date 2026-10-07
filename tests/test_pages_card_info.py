from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ankiweb.app import create_app
from ankiweb.core.config import Settings
from ankiweb.core.i18n import tr


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(collection_path=tmp_path / "c.anki2"))) as c:
        yield c


def _add_basic_card(client):
    def fn(col):
        n = col.new_note(col.models.by_name("Basic"))
        n["Front"] = "Question Front"
        n["Back"] = "Answer Back"
        col.add_note(n, col.decks.id("Default"))
        return n.cards()[0].id

    return client.portal.call(client.app.state.service.run, fn)


def _add_fsrs_reviewed_card(client):
    def fn(col):
        did = col.decks.id("Default")
        d = col.decks.get(did)
        conf = col.decks.get_config(d["conf"])
        conf["fsrs"] = True
        col.decks.update_config(conf)

        n = col.new_note(col.models.by_name("Basic"))
        n["Front"] = "FSRS Question"
        n["Back"] = "FSRS Answer"
        col.add_note(n, did)
        card = n.cards()[0]

        from anki.scheduler.v3 import CardAnswer
        queued = col.sched.get_queued_cards(fetch_limit=1)
        top = queued.cards[0]
        c = col.get_card(top.card.id)
        c.start_timer()
        ans = col.sched.build_answer(
            card=c, states=top.states, rating=CardAnswer.Rating.GOOD
        )
        col.sched.answer_card(ans)
        return card.id

    return client.portal.call(client.app.state.service.run, fn)


def test_next_card_info_single_new_card(client):
    cid = _add_basic_card(client)
    r = client.get(f"/card-info/{cid}")
    assert r.status_code == 200
    assert "route-card-info" in r.text
    # Should display rows: Added, Position, Card Type, Note Type, Deck, Preset, Card ID, Note ID
    assert tr.card_stats_added() in r.text
    assert tr.card_stats_new_card_position() in r.text
    assert tr.card_stats_card_template() in r.text
    assert tr.card_stats_note_type() in r.text
    assert tr.card_stats_deck_name() in r.text
    assert tr.card_stats_card_id() in r.text
    assert str(cid) in r.text
    assert "Basic" in r.text
    assert "Default" in r.text


def test_next_card_info_multi_card(client):
    cid1 = _add_basic_card(client)
    cid2 = _add_basic_card(client)
    r = client.get(f"/card-info/{cid1}/{cid2}")
    assert r.status_code == 200
    assert "Current" in r.text
    assert "Previous" in r.text
    assert str(cid1) in r.text
    assert str(cid2) in r.text


def test_next_card_info_empty_or_non_numeric(client):
    r = client.get("/card-info/")
    assert r.status_code == 200
    assert tr.card_stats_no_card() in r.text

    r_abc = client.get("/card-info/abc")
    assert r_abc.status_code == 200
    assert tr.card_stats_no_card() in r_abc.text


def test_next_card_info_missing_card_error(client):
    # Non-existent card returns 200 with database inconsistent error message
    r = client.get("/card-info/9999999999")
    assert r.status_code == 200
    assert "Your database appears to be in an inconsistent state" in r.text
    assert "No such card: '9999999999'" in r.text


def test_next_card_info_huge_id(client):
    # Beyond 64-bit int
    huge = "999999999999999999999999999999999999"
    r = client.get(f"/card-info/{huge}")
    assert r.status_code == 200
    assert f"int64 invalid: {huge}" in r.text


def test_next_card_info_query_params(client):
    cid = _add_basic_card(client)
    # revlog=0 hides revlog
    r = client.get(f"/card-info/{cid}?revlog=0")
    assert r.status_code == 200
    assert "revlog-table" not in r.text

    # curve=0 hides forgetting curve
    r_curve = client.get(f"/card-info/{cid}?curve=0")
    assert r_curve.status_code == 200
    assert "forgetting-curve" not in r_curve.text


def test_next_card_info_fsrs_and_revlog(client):
    cid = _add_fsrs_reviewed_card(client)
    r = client.get(f"/card-info/{cid}")
    assert r.status_code == 200
    assert tr.card_stats_fsrs_stability() in r.text
    assert tr.card_stats_fsrs_difficulty() in r.text
    assert tr.card_stats_review_count() in r.text
    assert "revlog-table" in r.text
    # Check forgetting curve svg is rendered
    assert "forgetting-curve" in r.text
    assert "<svg" in r.text
    assert "forgetting-curve-line" in r.text


def test_next_card_info_curve_time_range_update(client):
    cid = _add_fsrs_reviewed_card(client)
    # Datastar SSE post to change range
    r = client.post(f"/card-info/curve/{cid}?range=0")
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    assert f"selector #curve-{cid}" in r.text
    assert "<svg" in r.text
