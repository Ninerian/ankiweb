import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from ankiweb.config import Settings
from ankiweb.app import create_app
from conftest import parse_datastar_events


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(collection_path=tmp_path / "c.anki2"))) as c:
        yield c


def _basic_id(col):
    return col.models.by_name("Basic")["id"]


def _cloze_id(col):
    return col.models.by_name("Cloze")["id"]


# (a) /notetypes renders Basic + Cloze rows with /fields/ and /card-layout/ links + Add form
def test_notetypes_route_renders(client):
    r = client.get("/notetypes")
    assert r.status_code == 200
    assert "Manage Note Types" in r.text or "Note Types" in r.text
    assert "Basic" in r.text
    assert "Cloze" in r.text
    assert "/fields/" in r.text
    assert "/card-layout/" in r.text
    assert "Rename" in r.text
    assert "Delete" in r.text
    assert "Add" in r.text
    assert "@post('/notetypes/add/" in r.text


# (b) RENAME: rename/{basicId} -> name persists, returns reload script
def test_rename_persists(client):
    basicId = client.portal.call(client.app.state.service.run, _basic_id)
    r = client.post(f"/notetypes/rename/{basicId}", json={"name": "MyBasic"}, headers={"Datastar-Request": "true"})
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location.reload()" in data for _, data in events)
    name = client.portal.call(client.app.state.service.run, lambda col: col.models.get(basicId)["name"])
    assert name == "MyBasic"


# (c) ADD: add/{basicId} -> new notetype exists AND adding a note generates a card
def test_add_clones_usable_notetype(client):
    basicId = client.portal.call(client.app.state.service.run, _basic_id)
    r = client.post(f"/notetypes/add/{basicId}", json={"name": "Cloned"}, headers={"Datastar-Request": "true"})
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location.reload()" in data for _, data in events)

    def check(col):
        m = col.models.by_name("Cloned")
        assert m is not None
        n = col.new_note(m)
        n["Front"] = "cf"
        n["Back"] = "cb"
        col.add_note(n, col.decks.id("Default"))
        cids = col.models.nids(m["id"])
        assert len(cids) == 1

    client.portal.call(client.app.state.service.run, check)


# (d) DELETE: clone an extra type, delete/{thatId} removes it
def test_delete_removes_notetype(client):
    basicId = client.portal.call(client.app.state.service.run, _basic_id)
    client.post(f"/notetypes/add/{basicId}", json={"name": "Temp"}, headers={"Datastar-Request": "true"})
    tempId = client.portal.call(client.app.state.service.run, lambda col: col.models.by_name("Temp")["id"])
    r = client.post(f"/notetypes/delete/{tempId}")
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("window.location.reload()" in data for _, data in events)
    assert client.portal.call(client.app.state.service.run, lambda col: col.models.by_name("Temp")) is None


# (e) delete REFUSED when only one notetype remains -> error fragment, no removal
def test_delete_refused_when_only_one(client):
    def setup_single(col):
        all_ids = [nt.id for nt in col.models.all_names_and_ids()]
        for ntid in all_ids[1:]:
            col.models.remove(ntid)
        return all_ids[0]

    onlyId = client.portal.call(client.app.state.service.run, setup_single)
    count = client.portal.call(client.app.state.service.run, lambda col: len(col.models.all_names_and_ids()))
    assert count == 1

    r = client.post(f"/notetypes/delete/{onlyId}")
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("Cannot delete the only note type" in data for _, data in events)
    assert not any("window.location.reload()" in data for _, data in events)
    assert client.portal.call(client.app.state.service.run, lambda col: len(col.models.all_names_and_ids())) == 1


# (f) the page lists the note counts
def test_page_lists_note_counts(client):
    def seed_notes(col):
        m = col.models.by_name("Basic")
        for i in range(3):
            n = col.new_note(m)
            n["Front"] = f"f{i}"
            col.add_note(n, col.decks.id("Default"))

    client.portal.call(client.app.state.service.run, seed_notes)
    r = client.get("/notetypes")
    assert r.status_code == 200
    assert "3 notes" in r.text
