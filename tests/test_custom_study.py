from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ankiweb.app import create_app
from ankiweb.core.config import Settings


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(collection_path=tmp_path / "c.anki2"))) as c:
        yield c


def _seed(client, n=3):
    def seed(col):
        did = col.decks.id("Default")
        col.decks.set_current(did)
        for i in range(n):
            note = col.new_note(col.models.by_name("Basic"))
            note["Front"] = f"f{i}"
            note["Back"] = f"b{i}"
            col.add_note(note, did)
        return did

    return client.portal.call(client.app.state.service.run, seed)


def test_custom_study_route_renders_form(client):
    _seed(client)
    r = client.get("/custom-study")
    assert r.status_code == 200
    body = r.text
    assert "Increase today's new card limit" in body
    assert "Study by card state or tag" in body
    assert 'name="r"' in body
    assert 'id="spin"' in body


def test_custom_study_new_limit_navigates_and_broadcasts(client):
    from conftest import parse_datastar_events

    _seed(client)
    r = client.post(
        "/custom-study/submit",
        json={"radio": 1, "value": 5},
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location = '/overview'" in data for _, data in events)


def test_custom_study_cram_creates_filtered_deck(client):
    from conftest import parse_datastar_events

    _seed(client)
    r = client.post(
        "/custom-study/submit",
        json={"radio": 6, "value": 50, "cram_kind": 1, "include": [], "exclude": []},
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location = '/overview'" in data for _, data in events)
    cur = client.portal.call(
        client.app.state.service.run,
        lambda col: (
            col.decks.get(col.decks.get_current_id())["name"],
            bool(col.decks.get(col.decks.get_current_id()).get("dyn")),
        ),
    )
    assert cur[1] is True
    assert cur[0] == "Custom Study Session"


def test_custom_study_direct_signals_cram(client):
    """Verify submit handles signals directly with value, spin, cram_kind, and tags filtering."""
    from conftest import parse_datastar_events

    def seed_tagged(col):
        did = col.decks.id("Default")
        col.decks.set_current(did)
        # Card 1 with tag_inc
        n1 = col.new_note(col.models.by_name("Basic"))
        n1["Front"] = "front_inc"
        n1["Back"] = "b1"
        n1.tags.append("tag_inc")
        col.add_note(n1, did)
        # Card 2 with tag_inc and tag_exc
        n2 = col.new_note(col.models.by_name("Basic"))
        n2["Front"] = "front_both"
        n2["Back"] = "b2"
        n2.tags.extend(["tag_inc", "tag_exc"])
        col.add_note(n2, did)
        # Card 3 with neither
        n3 = col.new_note(col.models.by_name("Basic"))
        n3["Front"] = "front_other"
        n3["Back"] = "b3"
        col.add_note(n3, did)
        return did

    client.portal.call(client.app.state.service.run, seed_tagged)

    # Send native browser signal shape: value (from data-computed), spin, cram_kind, include, exclude
    r = client.post(
        "/custom-study/submit",
        json={
            "radio": 6,
            "spin": 25,
            "value": 25,
            "cram_kind": 1,
            "include": ["tag_inc"],
            "exclude": ["tag_exc"],
            "error": "",
        },
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location = '/overview'" in data for _, data in events)

    def check_cards(col):
        cram_id = col.decks.get_current_id()
        deck = col.decks.get(cram_id)
        assert deck["name"] == "Custom Study Session"
        assert bool(deck.get("dyn")) is True
        cids = col.decks.cids(cram_id)
        cards = [col.get_card(cid) for cid in cids]
        notes = [c.note() for c in cards]
        fronts = [n["Front"] for n in notes]
        return fronts

    fronts = client.portal.call(client.app.state.service.run, check_cards)
    assert fronts == ["front_inc"]

def test_custom_study_error_when_no_cards_match(client):
    from conftest import parse_datastar_events

    _seed(client)
    r = client.post(
        "/custom-study/submit",
        json={"radio": 3, "value": 1},
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any(
        "matched" in data.lower() or "card" in data.lower() for _, data in events
    )
    assert not any("window.location = '/overview'" in data for _, data in events)


