from pathlib import Path

import pytest
from conftest import parse_datastar_events
from fastapi.testclient import TestClient

from ankiweb.app import create_app
from ankiweb.core.config import Settings


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(collection_path=tmp_path / "c.anki2"))) as c:
        yield c


def test_next_deck_options_serves_html(client):
    did = client.portal.call(
        client.app.state.service.run, lambda col: col.decks.id("Default")
    )
    r = client.get(f"/deck-options/{did}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "route-deck-options" in r.text
    assert "Daily Limits" in r.text
    assert "New Cards" in r.text
    assert "Lapses" in r.text
    assert "FSRS" in r.text
    assert "data-signals" in r.text


def test_next_deck_options_filtered_deck(client):
    def make_dyn(col):
        import anki.decks_pb2 as dp
        # Add a note so filtered deck has matching cards
        note = col.new_note(col.models.by_name("Basic"))
        note["Front"] = "test front"
        note["Back"] = "test back"
        col.add_note(note, col.decks.id("Default"))

        g = col.sched.get_or_create_filtered_deck(0)
        g.name = "MyFilteredDeck"
        del g.config.search_terms[:]
        g.config.search_terms.append(
            dp.Deck.Filtered.SearchTerm(
                search="deck:Default",
                limit=10,
                order=dp.Deck.Filtered.SearchTerm.Order.ADDED,
            )
        )
        return col.sched.add_or_update_filtered_deck(g).id

    fid = client.portal.call(client.app.state.service.run, make_dyn)
    r = client.get(f"/deck-options/{fid}")
    assert r.status_code == 200
    assert "deck not normal" in r.text

def test_next_deck_options_change_preset(client):
    did = client.portal.call(
        client.app.state.service.run, lambda col: col.decks.id("Default")
    )
    # Add a custom preset first
    def add_cfg(col):
        return col.decks.add_config_returning_id("Test Preset")
    new_pid = client.portal.call(client.app.state.service.run, add_cfg)

    r = client.post(
        "/deck-options/change-preset",
        headers={"Datastar-Request": "true"},
        json={
            "deckId": did,
            "presetId": new_pid,
        },
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("presetId" in data for _, data in events)
    assert any("dirty" in data for _, data in events)


def test_next_deck_options_add_preset(client):
    did = client.portal.call(
        client.app.state.service.run, lambda col: col.decks.id("Default")
    )
    r = client.post(
        "/deck-options/add-preset",
        headers={"Datastar-Request": "true"},
        json={
            "deckId": did,
            "newPresetName": "Brand New Preset",
        },
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("Brand New Preset" in data for _, data in events)

    # Verify preset exists in collection
    configs = client.portal.call(
        client.app.state.service.run,
        lambda col: [c["name"] for c in col.decks.all_config()]
    )
    assert "Brand New Preset" in configs


def test_next_deck_options_clone_preset(client):
    did = client.portal.call(
        client.app.state.service.run, lambda col: col.decks.id("Default")
    )
    r = client.post(
        "/deck-options/clone-preset",
        headers={"Datastar-Request": "true"},
        json={
            "deckId": did,
            "presetId": 1,
            "clonePresetName": "Cloned From Default",
            "cfg": {"new_per_day": 45},
        },
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("Cloned From Default" in data for _, data in events)


def test_next_deck_options_rename_preset(client):
    did = client.portal.call(
        client.app.state.service.run, lambda col: col.decks.id("Default")
    )
    # Add preset to rename
    pid = client.portal.call(
        client.app.state.service.run,
        lambda col: col.decks.add_config_returning_id("To Rename")
    )
    r = client.post(
        "/deck-options/rename-preset",
        headers={"Datastar-Request": "true"},
        json={
            "deckId": did,
            "presetId": pid,
            "renamePresetName": "Renamed Preset",
        },
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("Renamed Preset" in data for _, data in events)


def test_next_deck_options_delete_preset(client):
    def setup_decks_and_presets(col):
        pid = col.decks.add_config_returning_id("To Delete")
        _ = col.decks.add_config_returning_id("Other Preset")
        did_parent = col.decks.id("Parent")
        did_child = col.decks.id("Parent::Child")

        d_parent = col.decks.get(did_parent)
        d_parent["conf"] = pid
        col.decks.save(d_parent)

        d_child = col.decks.get(did_child)
        d_child["conf"] = pid
        col.decks.save(d_child)
        return did_parent, did_child, pid

    did_parent, did_child, pid = client.portal.call(
        client.app.state.service.run, setup_decks_and_presets
    )
    r = client.post(
        "/deck-options/delete-preset",
        headers={"Datastar-Request": "true"},
        json={
            "deckId": did_parent,
            "presetId": pid,
        },
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("Preset deleted" in data for _, data in events)

    # Verify all decks that were using the deleted preset were reassigned to Default (conf=1)
    def check_confs(col):
        return col.decks.get(did_parent)["conf"], col.decks.get(did_child)["conf"]

    parent_conf, child_conf = client.portal.call(client.app.state.service.run, check_confs)
    assert parent_conf == 1
    assert child_conf == 1

def test_next_deck_options_save_and_roundtrip(client):
    did = client.portal.call(
        client.app.state.service.run, lambda col: col.decks.id("Default")
    )
    # Save modified new_per_day, reviews_per_day, learn_steps
    r = client.post(
        "/deck-options/save",
        headers={"Datastar-Request": "true"},
        json={
            "deckId": did,
            "presetId": 1,
            "cfg": {
                "new_per_day": 33,
                "reviews_per_day": 333,
                "graduating_interval_good": 2,
                "graduating_interval_easy": 5,
                "minimum_lapse_interval": 2,
            },
            "learnStepsStr": "2 15",
            "relearnStepsStr": "15",
            "limitMode": "preset",
        },
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("Saved successfully" in data for _, data in events)

    # Verify persisted in collection
    state = client.portal.call(
        client.app.state.service.run,
        lambda col: col.decks.get_deck_configs_for_update(did),
    )
    cfg = next(c.config.config for c in state.all_config if c.config.id == 1)
    assert cfg.new_per_day == 33
    assert cfg.reviews_per_day == 333
    assert list(cfg.learn_steps) == [2.0, 15.0]
    assert list(cfg.relearn_steps) == [15.0]


def test_next_deck_options_save_to_all_subdecks(client):
    parent_id = client.portal.call(
        client.app.state.service.run, lambda col: col.decks.id("ParentDeck")
    )
    child_id = client.portal.call(
        client.app.state.service.run, lambda col: col.decks.id("ParentDeck::ChildDeck")
    )
    # Add new preset
    pid = client.portal.call(
        client.app.state.service.run,
        lambda col: col.decks.add_config_returning_id("Subdeck Preset")
    )
    r = client.post(
        "/deck-options/save",
        headers={"Datastar-Request": "true"},
        json={
            "deckId": parent_id,
            "presetId": pid,
            "applyToSubdecks": True,
            "cfg": {
                "new_per_day": 50,
            },
        },
    )
    assert r.status_code == 200
    # Verify child deck has conf set to pid
    child_conf = client.portal.call(
        client.app.state.service.run,
        lambda col: col.decks.get(child_id)["conf"]
    )
    assert child_conf == pid


def test_next_deck_options_validation_warnings(client):
    did = client.portal.call(
        client.app.state.service.run, lambda col: col.decks.id("Default")
    )
    # graduating_interval_good >= graduating_interval_easy triggers warning
    r = client.post(
        "/deck-options/save",
        headers={"Datastar-Request": "true"},
        json={
            "deckId": did,
            "presetId": 1,
            "cfg": {
                "graduating_interval_good": 10,
                "graduating_interval_easy": 4,
            },
        },
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("warnings" in data for _, data in events)
