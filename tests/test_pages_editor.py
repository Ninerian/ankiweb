import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from ankiweb.core.config import Settings
from ankiweb.app import create_app


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(collection_path=tmp_path / "editor_test.anki2"))) as c:
        assert c.portal is not None
        c.portal.call(c.app.state.service.run, _seed)
        yield c


def _seed(col):
    m = col.models.by_name("Basic")
    n = col.new_note(m)
    n["Front"] = "FranceCapital"
    n["Back"] = "Paris"
    n.tags = ["geography", "europe"]
    col.add_note(n, col.decks.id("Default"))

    # Also add a Cloze note to test cloze field badge
    m_cloze = col.models.by_name("Cloze")
    n_cloze = col.new_note(m_cloze)
    n_cloze["Text"] = "Canberra is the capital of {{c1::Australia}}."
    col.add_note(n_cloze, col.decks.id("Default"))


def _first_nid(client):
    assert client.portal is not None
    return client.portal.call(
        client.app.state.service.run, lambda col: list(col.find_notes("FranceCapital"))[0]
    )


def test_next_edit_route_renders(client):
    nid = _first_nid(client)
    r = client.get(f"/edit?nid={nid}")
    assert r.status_code == 200
    assert "route-editor" in r.text
    assert "FranceCapital" in r.text
    assert "Paris" in r.text
    assert "geography" in r.text and "europe" in r.text
    assert "ankiweb-tag-editor" in r.text
    assert "ankiweb-editor-toolbar" in r.text
    assert 'data-field-index="0"' in r.text
    assert 'data-ankiweb-rich' in r.text
    assert 'data-ankiweb-plain' in r.text


def test_next_add_route_renders(client):
    r = client.get("/add")
    assert r.status_code == 200
    assert "route-editor" in r.text
    assert "editor-notetype-select" in r.text
    assert "editor-deck-select" in r.text
    assert "editor-add-btn" in r.text
    assert 'data-field-index="0"' in r.text


def test_save_and_blur_field(client):
    nid = _first_nid(client)
    r = client.post(
        "/editor/save-field",
        json={"index": 0, "html": "UpdatedFront", "nid": nid},
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200

    # Blur saves with run_op
    r2 = client.post(
        "/editor/blur-field",
        json={"index": 1, "html": "UpdatedBack", "nid": nid},
        headers={"Datastar-Request": "true"},
    )
    assert r2.status_code == 200

    def check(col):
        note = col.get_note(nid)
        return note["Front"], note["Back"]

    front, back = client.portal.call(client.app.state.service.run, check)
    assert front == "UpdatedFront"
    assert back == "UpdatedBack"


def test_save_tags(client):
    nid = _first_nid(client)
    r = client.post(
        "/editor/save-tags",
        json={"nid": nid, "tags_str": "newtag1 newtag2"},
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200

    def check(col):
        note = col.get_note(nid)
        return list(note.tags)

    tags = client.portal.call(client.app.state.service.run, check)
    assert "newtag1" in tags
    assert "newtag2" in tags


def test_toggle_collapse_and_sticky(client):
    ntid = client.portal.call(
        client.app.state.service.run, lambda col: col.models.by_name("Basic")["id"]
    )
    r = client.post(
        "/editor/toggle-collapse?idx=0",
        json={"notetype_id": ntid},
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200

    r2 = client.post(
        "/editor/toggle-sticky?idx=0",
        json={"notetype_id": ntid},
        headers={"Datastar-Request": "true"},
    )
    assert r2.status_code == 200

    def check(col):
        m = col.models.get(ntid)
        return m["flds"][0].get("collapsed"), m["flds"][0].get("sticky")

    collapsed, sticky = client.portal.call(client.app.state.service.run, check)
    assert collapsed is True
    assert sticky is True


def test_add_note_via_next_add(client):
    ntid = client.portal.call(
        client.app.state.service.run, lambda col: col.models.by_name("Basic")["id"]
    )
    did = client.portal.call(
        client.app.state.service.run, lambda col: col.decks.get_current_id()
    )

    r = client.post(
        "/editor/add-note",
        json={
            "notetype_id": ntid,
            "deck_id": did,
            "field_val_0": "BrandNewQuestion",
            "field_val_1": "BrandNewAnswer",
            "tags_str": "brand-new",
        },
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200
    assert "Added" in r.text or "toast_msg" in r.text

    def check(col):
        notes = col.find_notes("BrandNewQuestion")
        assert len(notes) == 1
        n = col.get_note(notes[0])
        return n["Back"], list(n.tags)

    back, tags = client.portal.call(client.app.state.service.run, check)
    assert back == "BrandNewAnswer"
    assert "brand-new" in tags


def test_add_duplicate_warning(client):
    ntid = client.portal.call(
        client.app.state.service.run, lambda col: col.models.by_name("Basic")["id"]
    )
    did = client.portal.call(
        client.app.state.service.run, lambda col: col.decks.get_current_id()
    )

    r = client.post(
        "/editor/add-note",
        json={
            "notetype_id": ntid,
            "deck_id": did,
            "field_val_0": "FranceCapital",  # already exists from _seed!
            "field_val_1": "ParisDuplicate",
            "tags_str": "",
        },
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200
    assert "duplicate" in r.text.lower()
