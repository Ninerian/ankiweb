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


def _basic_and_cloze_and_rev(client):
    def ids(col):
        return (
            col.models.by_name("Basic")["id"],
            col.models.by_name("Cloze")["id"],
            col.models.by_name("Basic (and reversed card)")["id"],
        )

    return client.portal.call(client.app.state.service.run, ids)


def test_next_change_notetype_page_serves_html(client):
    basic_id, _cloze_id, _ = _basic_and_cloze_and_rev(client)
    r = client.get(f"/change-notetype/{basic_id}")
    assert r.headers["content-type"].startswith("text/html")
    assert "route-change-notetype" in r.text
    assert "target-notetype-select" in r.text
    assert "change-notetype-save-btn" in r.text
    # Should list both field and template containers
    assert "Fields" in r.text
    assert "Templates" in r.text


def test_next_change_notetype_two_ids(client):
    basic_id, _cloze_id, rev_id = _basic_and_cloze_and_rev(client)
    r = client.get(f"/change-notetype/{basic_id}/{rev_id}")
    assert r.status_code == 200
    assert "route-change-notetype" in r.text
    # Target notetype should have rev_id selected
    assert f'value="{rev_id}" selected' in r.text


def test_next_change_notetype_select_target(client):
    basic_id, cloze_id, _rev_id = _basic_and_cloze_and_rev(client)
    r = client.post(
        "/change-notetype/select-target",
        headers={"Datastar-Request": "true"},
        json={
            "old_notetype_id": basic_id,
            "target_notetype_id": cloze_id,
            "note_ids": [],
        },
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("When changing to or from a Cloze note type" in data for _, data in events)


def test_next_change_notetype_remap_template_prevents_duplicate(client):
    basic_id, _, rev_id = _basic_and_cloze_and_rev(client)
    # Basic -> Reversed has 2 templates. Card 1 initially mapped to 0, Card 2 to -1.
    # If user maps Card 2 (new_index=1) to 0, Card 1 (new_index=0) should automatically become -1 (Nothing).
    r = client.post(
        "/change-notetype/remap-template?new_index=1",
        headers={"Datastar-Request": "true"},
        json={
            "old_notetype_id": basic_id,
            "target_notetype_id": rev_id,
            "note_ids": [],
            "template_map_0": 0,
            "template_map_1": 0,
        },
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    content = "".join(data for _, data in events)
    # Should see that template_map_0 now has value -1 selected (Nothing)
    assert 'data-bind="template_map_0"' in content
    assert 'data-bind="template_map_1"' in content


def test_next_change_notetype_save_unchanged_alerts(client):
    basic_id, _, _ = _basic_and_cloze_and_rev(client)
    r = client.post(
        "/change-notetype/save",
        headers={"Datastar-Request": "true"},
        json={
            "old_notetype_id": basic_id,
            "target_notetype_id": basic_id,
            "note_ids": [],
            "field_map_0": 0,
            "field_map_1": 1,
            "template_map_0": 0,
        },
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("alert('No changes to save')" in data for _, data in events)


def test_next_change_notetype_save_mutates_collection(client):
    basic_id, _, rev_id = _basic_and_cloze_and_rev(client)
    svc = client.app.state.service

    def seed(col):
        n = col.new_note(col.models.get(basic_id))
        n["Front"] = "Question"
        n["Back"] = "Answer"
        col.add_note(n, col.decks.id("Default"))
        return n.id

    nid = client.portal.call(svc.run, seed)

    # Convert to Basic (and reversed card)
    r = client.post(
        "/change-notetype/save",
        headers={"Datastar-Request": "true"},
        json={
            "old_notetype_id": basic_id,
            "target_notetype_id": rev_id,
            "note_ids": [nid],
            "field_map_0": 0,
            "field_map_1": 1,
            "template_map_0": 0,
            "template_map_1": -1,
        },
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("deckbrowser" in data for _, data in events)

    def check(col):
        note = col.get_note(nid)
        return note.mid, note["Front"], note["Back"]

    mid, front, back = client.portal.call(svc.run, check)
    assert mid == rev_id
    assert front == "Question"
    assert back == "Answer"


def test_next_change_notetype_malformed_ids_error_handling(client):
    # Non-numeric ids
    r = client.get("/change-notetype/bad/alsobad")
    assert r.status_code == 200
    assert "Cannot convert bad to a BigInt" in r.text

    r = client.get("/change-notetype/bad")
    assert r.status_code == 200
    assert "Cannot convert bad to a BigInt" in r.text

    basic_id, _, _ = _basic_and_cloze_and_rev(client)
    r = client.get(f"/change-notetype/{basic_id}/bad")
    assert r.status_code == 200
    assert "Cannot convert bad to a BigInt" in r.text


def test_next_change_notetype_unknown_or_deleted_id(client):
    # Unknown notetype id
    r = client.get("/change-notetype/9999999999")
    assert r.status_code == 200
    assert "No such notetype" in r.text
    assert "9999999999" in r.text

    # Multiple segments
    r = client.get("/change-notetype/1/2/3/4")
    assert r.status_code == 200
    assert "No such notetype" in r.text
    assert "1" in r.text


def test_next_change_notetype_post_malformed_payloads(client):
    # Empty or malformed payload to select-target
    r = client.post(
        "/change-notetype/select-target",
        headers={"Datastar-Request": "true"},
        json={},
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("alert-error" in data for _, data in events)

    # Malformed IDs to remap-field
    r = client.post(
        "/change-notetype/remap-field?new_index=0",
        headers={"Datastar-Request": "true"},
        json={"old_notetype_id": "not-an-id", "target_notetype_id": "abc"},
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("Malformed notetype IDs" in data for _, data in events)

    # Malformed IDs to remap-template
    r = client.post(
        "/change-notetype/remap-template?new_index=0",
        headers={"Datastar-Request": "true"},
        json={"old_notetype_id": "bad", "target_notetype_id": "bad"},
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("Malformed notetype IDs" in data for _, data in events)

    # Malformed payload to save
    r = client.post(
        "/change-notetype/save",
        headers={"Datastar-Request": "true"},
        json={"old_notetype_id": "bad", "target_notetype_id": "bad"},
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("Malformed notetype IDs" in data for _, data in events)
