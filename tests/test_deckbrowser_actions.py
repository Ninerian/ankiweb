import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from ankiweb.core.config import Settings
from ankiweb.app import create_app
from conftest import parse_datastar_events


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(collection_path=tmp_path / "c.anki2"))) as c:
        yield c


def _make_deck(client, name="Custom"):
    return client.portal.call(client.app.state.service.run, lambda col: col.decks.id(name))


def test_deckbrowser_row_has_options_dropdown(client):
    did = _make_deck(client)
    r = client.get("/deckbrowser")
    assert r.status_code == 200
    assert 'data-testid="deck-options-dropdown"' in r.text
    assert f"/deckbrowser/rename/{did}" in r.text
    assert f"/deckbrowser/delete/{did}" in r.text


def test_deckbrowser_rename_deck(client):
    did = _make_deck(client)
    r = client.post(
        f"/deckbrowser/rename/{did}",
        json={"name": "Renamed"},
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location.reload()" in data for _, data in events)
    name = client.portal.call(
        client.app.state.service.run, lambda col: col.decks.get(did)["name"]
    )
    assert name == "Renamed"


def test_deckbrowser_rename_deck_blank_name_noop(client):
    did = _make_deck(client)
    r = client.post(
        f"/deckbrowser/rename/{did}",
        json={"name": "  "},
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 204
    name = client.portal.call(
        client.app.state.service.run, lambda col: col.decks.get(did)["name"]
    )
    assert name == "Custom"


def test_deckbrowser_rename_deck_conflict_suffixes_name(client):
    # Anki's decks.rename() resolves a same-name collision by appending "+"
    # rather than raising, so the row still ends up renamed (uniquely) and the
    # SSE response still triggers a reload rather than patching #err.
    _make_deck(client, "First")
    did = _make_deck(client, "Second")
    r = client.post(
        f"/deckbrowser/rename/{did}",
        json={"name": "First"},
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location.reload()" in data for _, data in events)
    name = client.portal.call(
        client.app.state.service.run, lambda col: col.decks.get(did)["name"]
    )
    assert name == "First+"


def test_deckbrowser_delete_deck(client):
    did = _make_deck(client)
    r = client.post(
        f"/deckbrowser/delete/{did}", headers={"Datastar-Request": "true"}
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location.reload()" in data for _, data in events)
    remaining_ids = client.portal.call(
        client.app.state.service.run,
        lambda col: {d.id for d in col.decks.all_names_and_ids()},
    )
    assert did not in remaining_ids
