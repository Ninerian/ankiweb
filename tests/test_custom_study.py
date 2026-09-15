import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from ankiweb.core.config import Settings
from ankiweb.app import create_app


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


def test_overview_studymore_navigates_to_custom_study(client):
    from conftest import parse_datastar_events

    _seed(client)
    r = client.post("/overview/studymore")
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location = '/custom-study'" in data for _, data in events)


def test_overview_opts_navigates_to_deck_options(client):
    from conftest import parse_datastar_events

    did = _seed(client)
    r = client.post("/overview/opts")
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any(f"window.location = '/deck-options/{did}'" in data for _, data in events)
