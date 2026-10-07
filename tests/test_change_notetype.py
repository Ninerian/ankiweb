import html
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ankiweb.app import create_app
from ankiweb.core.config import Settings


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(collection_path=tmp_path / "c.anki2"))) as c:
        yield c


def _basic_cloze(client):
    def ids(col):
        return col.models.by_name("Basic")["id"], col.models.by_name("Cloze")["id"]

    return client.portal.call(client.app.state.service.run, ids)


def _signals(content):
    match = re.search(r'data-signals="([^"]+)"', content)
    assert match is not None
    return json.loads(html.unescape(match.group(1)))


def test_get_change_notetype_info_passthrough(client):
    r = client.post(
        "/_anki/get_change_notetype_info",
        content=b"",
        headers={"content-type": "application/binary"},
    )
    assert r.status_code != 404


def test_change_notetype_converts_selected_notes_and_broadcasts(client):
    old, new = _basic_cloze(client)
    svc = client.app.state.service

    def seed(col):
        n1 = col.new_note(col.models.get(old))
        n1["Front"] = "a"
        n1["Back"] = "b"
        col.add_note(n1, col.decks.id("Default"))
        n2 = col.new_note(col.models.get(old))
        n2["Front"] = "c"
        n2["Back"] = "d"
        col.add_note(n2, col.decks.id("Default"))
        return n1.id, n2.id

    nid1, nid2 = client.portal.call(svc.run, seed)
    client.app.state.hub.ui_state.selected_note_ids = [nid1]

    info = client.portal.call(
        svc.run,
        lambda col: col.models.change_notetype_info(
            old_notetype_id=old, new_notetype_id=new
        ),
    )
    req = info.input
    assert list(req.note_ids) == []
    r = client.post(
        "/_anki/changeNotetype",
        content=req.SerializeToString(),
        headers={"content-type": "application/binary"},
    )
    assert r.status_code == 200
    mids = client.portal.call(
        svc.run, lambda col: (col.get_note(nid1).mid, col.get_note(nid2).mid)
    )
    assert mids[0] == new
    assert mids[1] == old


def test_change_notetype_falls_back_to_all_notes_when_no_selection(client):
    old, new = _basic_cloze(client)
    svc = client.app.state.service

    def seed(col):
        n = col.new_note(col.models.get(old))
        n["Front"] = "x"
        n["Back"] = "y"
        col.add_note(n, col.decks.id("Default"))
        return n.id

    nid = client.portal.call(svc.run, seed)
    client.app.state.hub.ui_state.selected_note_ids = []

    info = client.portal.call(
        svc.run,
        lambda col: col.models.change_notetype_info(
            old_notetype_id=old, new_notetype_id=new
        ),
    )
    r = client.post(
        "/_anki/changeNotetype",
        content=info.input.SerializeToString(),
        headers={"content-type": "application/binary"},
    )
    assert r.status_code == 200
    assert client.portal.call(svc.run, lambda col: col.get_note(nid).mid) == new


def test_change_notetype_get_uses_requested_cards_not_shared_selection(client):
    old, _new = _basic_cloze(client)
    svc = client.app.state.service

    def seed(col):
        def add_note(front):
            note = col.new_note(col.models.get(old))
            note["Front"] = front
            note["Back"] = "answer"
            col.add_note(note, col.decks.id("Default"))
            cid = next(
                cid
                for cid in col.find_cards("")
                if col.get_card(cid).nid == note.id
            )
            return note.id, cid

        return add_note("selected"), add_note("unselected")

    (selected_nid, selected_cid), (unselected_nid, unselected_cid) = (
        client.portal.call(svc.run, seed)
    )
    client.app.state.hub.ui_state.selected_card_ids = [unselected_cid]
    client.app.state.hub.ui_state.selected_note_ids = [unselected_nid]

    response = client.get(f"/change-notetype?cids={selected_cid}")

    assert response.status_code == 200
    assert _signals(response.text)["note_ids"] == [selected_nid]
