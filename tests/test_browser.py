import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from ankiweb.config import Settings
from ankiweb.app import create_app


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(collection_path=tmp_path / "c.anki2"))) as c:
        c.portal.call(c.app.state.service.run, _seed)
        yield c


def _seed(col):
    for q in ("dog", "cat"):
        n = col.new_note(col.models.by_name("Basic"))
        n["Front"] = q
        n["Back"] = q.upper()
        col.add_note(n, col.decks.id("Default"))
    col.tags.bulk_add(col.find_notes(""), "animals")
    col.decks.id("Spanish")


def test_browse_route_renders(client):
    r = client.get("/browse")
    assert r.status_code == 200
    assert 'window.__ankiwebContext = "browser"' in r.text
    assert "id='results'" in r.text or 'id="results"' in r.text
    assert "id='search'" in r.text or 'id="search"' in r.text
    assert "Default" in r.text
    assert "animals" in r.text


def test_browse_search_pushes_rows_and_mirrors_ui_state(client):
    from conftest import parse_datastar_events

    hub = client.app.state.hub
    r = client.post(
        "/browse/search", json={"query": "dog"}, headers={"Datastar-Request": "true"}
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("dog" in data and "cat" not in data for _, data in events)
    assert any("1 cards" in data for _, data in events)
    assert hub.ui_state.browser_open is True
    assert hub.ui_state.last_browse_query == "dog"
    assert len(hub.ui_state.matched_card_ids) == 1


def test_browse_searchdeck_and_searchtag(client):
    from conftest import parse_datastar_events

    did = client.portal.call(
        client.app.state.service.run, lambda col: col.decks.id("Default")
    )
    r1 = client.post(f"/browse/searchdeck/{did}")
    assert r1.status_code == 200
    events1 = parse_datastar_events(r1.text)
    assert any("dog" in data and "cat" in data for _, data in events1)

    r2 = client.post(
        "/browse/searchtag",
        json={"tag": "animals"},
        headers={"Datastar-Request": "true"},
    )
    assert r2.status_code == 200
    events2 = parse_datastar_events(r2.text)
    assert any("dog" in data and "cat" in data for _, data in events2)


def test_browse_open_pushes_detail_and_selection(client):
    from conftest import parse_datastar_events

    cid = client.portal.call(
        client.app.state.service.run, lambda col: list(col.find_cards("dog"))[0]
    )
    hub = client.app.state.hub
    r = client.post(f"/browse/open/{cid}")
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("ankiwebLoadNid" in data for _, data in events)
    assert hub.ui_state.selected_card_ids == [cid]
    assert len(hub.ui_state.selected_note_ids) == 1


def test_browse_invalid_search_does_not_crash(client):
    from conftest import parse_datastar_events

    r = client.post(
        "/browse/search",
        json={"query": "deck:((("},
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("invalid search" in data for _, data in events)
    assert any("0 cards" in data for _, data in events)


def test_search_and_refresh_reset_client_selection(client):
    # rows-repatch responses (search/refresh/mutation reload) must instruct the
    # client to clear its stale _sel/_anchor state, since the freshly-rendered
    # rows carry no "selected" markup of their own — old ankiwebSetRows did this
    # on every row push; __ankiwebResetSel must be invoked the same way now.
    for path, kwargs in [
        (
            "/browse/search",
            dict(json={"query": "dog"}, headers={"Datastar-Request": "true"}),
        ),
        ("/browse/refresh", {}),
    ]:
        r = client.post(path, **kwargs)
        assert r.status_code == 200
        assert "__ankiwebResetSel" in r.text, (
            f"{path} must reset client selection state"
        )


def _run(client, fn):
    return client.portal.call(client.app.state.service.run, fn)


def test_select_then_suspend(client):
    from conftest import parse_datastar_events

    hub = client.app.state.hub
    cids = _run(client, lambda col: list(col.find_cards("")))
    r1 = client.post(
        "/browse/select", json={"cids": cids}, headers={"Datastar-Request": "true"}
    )
    assert r1.status_code == 200
    assert hub.ui_state.selected_card_ids == cids
    assert len(hub.ui_state.selected_note_ids) == 2

    r2 = client.post("/browse/suspend")
    assert r2.status_code == 200
    events2 = parse_datastar_events(r2.text)
    assert any("results-body" in data for _, data in events2)
    assert all(_run(client, lambda col, c=c: col.get_card(c).queue) == -1 for c in cids)


def test_mutation_routes_are_silent_noop_with_empty_selection(client):
    # guard-failure branches (nothing selected) must reproduce the old handler's
    # silent `return None` no-op — a 204 with zero SSE events — not unconditionally
    # re-search and wipe the open #detail pane.
    hub = client.app.state.hub
    hub.ui_state.selected_card_ids = []
    hub.ui_state.selected_note_ids = []
    for path, kwargs in [
        ("/browse/suspend", {}),
        ("/browse/unsuspend", {}),
        ("/browse/forget", {}),
        ("/browse/delete", {}),
        (
            "/browse/setdue",
            dict(json={"value": "0"}, headers={"Datastar-Request": "true"}),
        ),
        (
            "/browse/changedeck",
            dict(json={"deck": "Spanish"}, headers={"Datastar-Request": "true"}),
        ),
        (
            "/browse/addtag",
            dict(json={"tag": "marked"}, headers={"Datastar-Request": "true"}),
        ),
        (
            "/browse/removetag",
            dict(json={"tag": "marked"}, headers={"Datastar-Request": "true"}),
        ),
    ]:
        r = client.post(path, **kwargs)
        assert r.status_code == 204, f"{path} should no-op (204) with empty selection"
        assert r.text == ""


def test_select_one_pushes_editor(client):
    from conftest import parse_datastar_events

    cid = _run(client, lambda col: list(col.find_cards("dog"))[0])
    nid = _run(client, lambda col: col.get_card(cid).nid)
    r = client.post(
        "/browse/select", json={"cids": [cid]}, headers={"Datastar-Request": "true"}
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any(f"nid: {nid}" in data for _, data in events)


def test_delete_removes_notes(client):
    from conftest import parse_datastar_events

    cid = _run(client, lambda col: list(col.find_cards("dog"))[0])
    before = _run(client, lambda col: len(col.find_notes("")))
    client.post(
        "/browse/select", json={"cids": [cid]}, headers={"Datastar-Request": "true"}
    )
    r = client.post("/browse/delete")
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("results-body" in data for _, data in events)
    assert _run(client, lambda col: len(col.find_notes(""))) == before - 1


def test_changedeck_moves_card(client):
    from conftest import parse_datastar_events

    cid = _run(client, lambda col: list(col.find_cards("dog"))[0])
    client.post(
        "/browse/select", json={"cids": [cid]}, headers={"Datastar-Request": "true"}
    )
    r = client.post(
        "/browse/changedeck",
        json={"deck": "Spanish"},
        headers={"Datastar-Request": "true"},
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("results-body" in data for _, data in events)
    did = _run(client, lambda col: col.get_card(cid).did)
    assert did == _run(client, lambda col: col.decks.id("Spanish"))


def test_add_and_remove_tag(client):
    cid = _run(client, lambda col: list(col.find_cards("dog"))[0])
    nid = _run(client, lambda col: col.get_card(cid).nid)
    client.post(
        "/browse/select", json={"cids": [cid]}, headers={"Datastar-Request": "true"}
    )
    r1 = client.post(
        "/browse/addtag", json={"tag": "marked"}, headers={"Datastar-Request": "true"}
    )
    assert r1.status_code == 200
    assert "marked" in _run(client, lambda col: col.get_note(nid).tags)

    client.post(
        "/browse/select", json={"cids": [cid]}, headers={"Datastar-Request": "true"}
    )
    r2 = client.post(
        "/browse/removetag",
        json={"tag": "marked"},
        headers={"Datastar-Request": "true"},
    )
    assert r2.status_code == 200
    assert "marked" not in _run(client, lambda col: col.get_note(nid).tags)


def test_setdue_runs(client):
    from conftest import parse_datastar_events

    cid = _run(client, lambda col: list(col.find_cards("dog"))[0])
    client.post(
        "/browse/select", json={"cids": [cid]}, headers={"Datastar-Request": "true"}
    )
    r = client.post(
        "/browse/setdue", json={"value": "0"}, headers={"Datastar-Request": "true"}
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("results-body" in data for _, data in events)


def test_browse_refresh_repushes_rows(client):
    from conftest import parse_datastar_events

    client.post(
        "/browse/search", json={"query": "dog"}, headers={"Datastar-Request": "true"}
    )
    r = client.post("/browse/refresh")
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("dog" in data for _, data in events)


def test_browser_select_emits_reusable_editor_script(client):
    # the reuse wiring: each single-note select response must postMessage an
    # already-mounted iframe, falling back to creating one only if none exists —
    # not rebuild a fresh iframe unconditionally on every selection.
    from conftest import parse_datastar_events

    cid1 = _run(client, lambda col: list(col.find_cards("dog"))[0])
    nid1 = _run(client, lambda col: col.get_card(cid1).nid)
    cid2 = _run(client, lambda col: list(col.find_cards("cat"))[0])
    nid2 = _run(client, lambda col: col.get_card(cid2).nid)

    for cid, nid in ((cid1, nid1), (cid2, nid2)):
        r = client.post(
            "/browse/select", json={"cids": [cid]}, headers={"Datastar-Request": "true"}
        )
        assert r.status_code == 200
        _, script = parse_datastar_events(r.text)[0]
        assert "contentWindow" in script and "postMessage" in script
        assert f"nid: {nid}" in script
        assert "editor-frame" in script


def test_editor_listens_for_in_place_note_switch(client):
    nid = _run(client, lambda col: list(col.find_notes("dog"))[0])
    html = client.get(f"/edit?nid={nid}").text
    # editor reloads a note in-place on a parent postMessage (no full editor.js reload)
    assert "addEventListener('message'" in html
    assert "ankiwebLoadNid" in html
