import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from ankiweb.core.config import Settings
from ankiweb.app import create_app


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(collection_path=tmp_path / "c.anki2"))) as c:
        assert c.portal is not None
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
    assert any("dog" in data and ">cat<" not in data for _, data in events)
    from ankiweb.adapters.inbound.http_datastar.browser import _card_count_str

    # the status line is updated to the localized "<n> cards" label for the match count
    assert any("browser-status" in data and _card_count_str(1) in data for _, data in events)
    assert hub.ui_state.browser_open is True
    assert hub.ui_state.last_browse_query == "dog"
    assert len(hub.ui_state.matched_card_ids) == 1


def test_browse_searchdeck_and_searchtag(client):
    from conftest import parse_datastar_events

    assert client.portal is not None
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

    assert client.portal is not None
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
    assert client.portal is not None
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


def test_row_data_rich_fields_and_formatted_due(client):
    import datetime, time
    from ankiweb.adapters.inbound.http_datastar.browser import _row_data, _format_due

    def seed_various_cards(col):
        m_rev = col.models.by_name("Basic (and reversed card)")
        d = col.decks.id("Default")
        note = col.new_note(m_rev)
        note["Front"] = "alpha"
        note["Back"] = "beta"
        note.tags = ["tag1", "tag2"]
        col.add_note(note, d)

        cards = note.cards()
        c1, c2 = cards[0], cards[1]

        # c1 is new
        c1.queue = 0
        c1.due = 7
        col.update_card(c1)

        # c2 is review
        c2.queue = 2
        c2.type = 2
        c2.due = col.sched.today + 4
        col.update_card(c2)

        # single basic note for suspended & learn
        m_basic = col.models.by_name("Basic")
        note2 = col.new_note(m_basic)
        note2["Front"] = "gamma"
        note2["Back"] = "delta"
        col.add_note(note2, d)
        c3 = note2.cards()[0]
        c3.queue = -1
        col.update_card(c3)

        note3 = col.new_note(m_basic)
        note3["Front"] = "learn_card"
        note3["Back"] = "epsilon"
        col.add_note(note3, d)
        c4 = note3.cards()[0]
        c4.queue = 1
        c4.due = int(time.time()) + 300
        col.update_card(c4)

        # c5 is review past due
        note4 = col.new_note(m_basic)
        note4["Front"] = "past_due_card"
        note4["Back"] = "zeta"
        col.add_note(note4, d)
        c5 = note4.cards()[0]
        c5.queue = 2
        c5.type = 2
        c5.due = col.sched.today - 3
        col.update_card(c5)

        return c1.id, c2.id, c3.id, c4.id, c5.id

    c1_id, c2_id, c3_id, c4_id, c5_id = _run(client, seed_various_cards)

    def check_rows(col):
        rows = _row_data(col, [c1_id, c2_id, c3_id, c4_id, c5_id])
        return rows

    rows = _run(client, check_rows)
    assert len(rows) == 5


    r1 = next(r for r in rows if r["cid"] == c1_id)
    assert r1["sort_text"] == "alpha"
    assert r1["template_name"] == "Card 1"
    assert r1["note_type_name"] == "Basic (and reversed card)"
    assert r1["deck"] == "Default"
    assert r1["tags"] == "tag1 tag2"
    assert "#7" in r1["due"]
    assert r1["is_suspended"] is False

    r2 = next(r for r in rows if r["cid"] == c2_id)
    assert r2["sort_text"] == "alpha"
    assert r2["template_name"] == "Card 2"
    assert r2["note_type_name"] == "Basic (and reversed card)"
    assert r2["due"] == (datetime.date.today() + datetime.timedelta(days=4)).isoformat()
    assert r2["is_suspended"] is False

    r3 = next(r for r in rows if r["cid"] == c3_id)
    assert r3["sort_text"] == "gamma"
    assert r3["is_suspended"] is True
    assert len(r3["due"]) > 0  # e.g. 'Suspended' or 'Ausgeschlossen'

    r4 = next(r for r in rows if r["cid"] == c4_id)
    assert r4["sort_text"] == "learn_card"
    assert ":" in r4["due"]  # HH:MM timestamp

    r5 = next(r for r in rows if r["cid"] == c5_id)
    assert r5["sort_text"] == "past_due_card"
    assert r5["due"] == (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
    # verify rendering of these rows includes template names and tags
    html = client.get("/browse?q=alpha").text
    assert "Card 1" in html
    assert "Card 2" in html
    assert "tag1 tag2" in html


def test_browse_q_param_prefills_input(client):
    r = client.get("/browse?q=deck:Default")
    assert r.status_code == 200
    assert 'value="deck:Default"' in r.text


def test_browse_q_param_html_escaped(client):
    r = client.get('/browse?q=front:"a<b>"')
    assert r.status_code == 200
    assert "&lt;b&gt;" in r.text
    assert "<b&gt;" not in r.text
