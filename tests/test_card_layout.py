import json
from html.parser import HTMLParser
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


def _basic_id(col):
    return col.models.by_name("Basic")["id"]


def _tmpls(col, ntid):
    return col.models.get(ntid)["tmpls"]


def _tmpl_names(col, ntid):
    return [t["name"] for t in _tmpls(col, ntid)]


def _add_note(col, ntid):
    """Add a Basic note so previews / card generation have something to work with."""
    m = col.models.get(ntid)
    note = col.new_note(m)
    note["Front"] = "Hello"
    note["Back"] = "World"
    col.add_note(note, col.decks.id("Default"))
    return note.id


def _make_layout_draft_payload(ntid: int, templates: list[dict], css: str = "") -> dict:
    rows = {}
    order = []
    for idx, tmpl in enumerate(templates):
        key = tmpl.get("key", f"t{idx}")
        order.append(key)
        row = {
            "name": tmpl.get("name", ""),
            "qfmt": tmpl.get("qfmt", ""),
            "afmt": tmpl.get("afmt", ""),
        }
        if tmpl.get("orig") is not None:
            row["orig"] = tmpl["orig"]
        rows[key] = row
    return {
        "notetypeId": ntid,
        "layoutDraft": {
            "rows": rows,
            "order": order,
            "nextId": len(order),
            "css": css,
        },
    }


class _CardLayoutNavigationParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.return_url: str | None = None
        self.cancel_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form" and attributes.get("id") == "clf":
            signals = attributes.get("data-signals")
            assert signals is not None
            self.return_url = json.loads(signals)["returnUrl"]
        elif tag == "a" and attributes.get("id") == "layout-cancel-btn":
            self.cancel_href = attributes.get("href")


def _layout_navigation(content: str) -> tuple[str, str]:
    parser = _CardLayoutNavigationParser()
    parser.feed(content)
    assert parser.return_url is not None
    assert parser.cancel_href is not None
    return parser.return_url, parser.cancel_href


# Card-layout navigation returns to the explicit source context or the safe default.
def test_card_layout_route_defaults_return_context_to_notetypes(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    response = client.get(f"/card-layout/{ntid}")

    assert response.status_code == 200
    assert _layout_navigation(response.text) == ("/notetypes", "/notetypes")


def test_explicit_return_to_preserves_query_hash_and_precedes_referer(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    destination = "/browse?q=dog&sort=desc#row-2"
    response = client.get(
        f"/card-layout/{ntid}",
        params={"return_to": destination},
        headers={"referer": "http://testserver/edit?nid=123"},
    )

    assert response.status_code == 200
    assert _layout_navigation(response.text) == (destination, destination)


def test_same_origin_referer_preserves_query_hash(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    destination = "/edit?nid=123&tab=front#question"
    response = client.get(
        f"/card-layout/{ntid}",
        headers={"referer": f"http://testserver{destination}"},
    )

    assert response.status_code == 200
    assert _layout_navigation(response.text) == (destination, destination)


def test_cross_origin_referer_defaults_to_notetypes(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    response = client.get(
        f"/card-layout/{ntid}",
        headers={"referer": "https://outside.example/browse?q=dog"},
    )

    assert response.status_code == 200
    assert _layout_navigation(response.text) == ("/notetypes", "/notetypes")


@pytest.mark.parametrize(
    "destination",
    [
        "https://outside.example/browse",
        "//outside.example/browse",
        r"/\\outside.example/browse",
        "/browse?q=dog\r\nLocation: https://outside.example",
    ],
)
def test_unsafe_return_to_defaults_to_notetypes(client, destination):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    response = client.get(f"/card-layout/{ntid}", params={"return_to": destination})

    assert response.status_code == 200
    assert _layout_navigation(response.text) == ("/notetypes", "/notetypes")


def test_cancel_returns_to_context_without_persisting_changes(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    destination = "/browse?q=dog&sort=desc#row-2"
    before = client.portal.call(
        client.app.state.service.run,
        lambda col: [(t["name"], t["qfmt"], t["afmt"]) for t in _tmpls(col, ntid)],
    )
    response = client.get(f"/card-layout/{ntid}", params={"return_to": destination})

    assert response.status_code == 200
    assert _layout_navigation(response.text) == (destination, destination)
    after = client.portal.call(
        client.app.state.service.run,
        lambda col: [(t["name"], t["qfmt"], t["afmt"]) for t in _tmpls(col, ntid)],
    )
    assert after == before


# (b) edit qfmt/afmt persists
def test_edit_qfmt_afmt_persists_and_redirects_to_return_context(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    payload = _make_layout_draft_payload(
        ntid,
        [
            {
                "orig": 0,
                "name": "Card 1",
                "qfmt": "{{Front}}<hr>custom",
                "afmt": "{{FrontSide}}<hr id=answer>{{Back}}<br>extra",
            },
        ],
        css="",
    )
    destination = "/browse?q=dog&sort=desc#row-2"
    payload["returnUrl"] = destination

    r = client.post(
        "/card-layout/savelayout", json=payload, headers={"Datastar-Request": "true"}
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any(destination in data for _, data in events)
    t0 = client.portal.call(
        client.app.state.service.run, lambda col: _tmpls(col, ntid)[0]
    )
    assert t0["qfmt"] == "{{Front}}<hr>custom"
    assert t0["afmt"] == "{{FrontSide}}<hr id=answer>{{Back}}<br>extra"


@pytest.mark.parametrize(
    "destination",
    [
        "https://outside.example/browse",
        "//outside.example/browse",
        r"/\\outside.example/browse",
        "/browse?q=dog\r\nLocation: https://outside.example",
    ],
)
def test_unsafe_save_return_url_falls_back_while_persisting(client, destination):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    payload = _make_layout_draft_payload(
        ntid,
        [
            {
                "orig": 0,
                "name": "Card 1",
                "qfmt": "{{Front}}<hr>saved safely",
                "afmt": "{{FrontSide}}<hr id=answer>{{Back}}",
            }
        ],
    )
    payload["returnUrl"] = destination
    response = client.post(
        "/card-layout/savelayout",
        json=payload,
        headers={"Datastar-Request": "true"},
    )

    assert response.status_code == 200
    events = parse_datastar_events(response.text)
    assert any("/notetypes" in data for _, data in events)
    assert not any(destination in data for _, data in events)
    saved = client.portal.call(
        client.app.state.service.run, lambda col: _tmpls(col, ntid)[0]
    )
    assert saved["qfmt"] == "{{Front}}<hr>saved safely"


# (c) edit css persists
def test_edit_css_persists(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    payload = _make_layout_draft_payload(
        ntid,
        [
            {
                "orig": 0,
                "name": "Card 1",
                "qfmt": "{{Front}}",
                "afmt": "{{FrontSide}}\n\n<hr id=answer>\n\n{{Back}}",
            },
        ],
        css=".card { font-family: monospace; font-size: 24px; }",
    )
    r = client.post(
        "/card-layout/savelayout", json=payload, headers={"Datastar-Request": "true"}
    )
    assert r.status_code == 200
    m = client.portal.call(
        client.app.state.service.run, lambda col: col.models.get(ntid)
    )
    assert ".card { font-family: monospace;" in m["css"]


# (d) rename a template persists
def test_rename_template_persists_and_uses_safe_default(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    payload = _make_layout_draft_payload(
        ntid,
        [
            {"orig": 0, "name": "Recognition", "qfmt": "{{Front}}", "afmt": "{{Back}}"},
        ],
    )
    r = client.post(
        "/card-layout/savelayout", json=payload, headers={"Datastar-Request": "true"}
    )
    events = parse_datastar_events(r.text)
    assert any("/notetypes" in data for _, data in events)
    names = client.portal.call(
        client.app.state.service.run, lambda col: _tmpl_names(col, ntid)
    )
    assert names == ["Recognition"]


# (e) add a template persists (count up)
def test_add_template_persists(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    before = client.portal.call(
        client.app.state.service.run, lambda col: len(_tmpls(col, ntid))
    )
    payload = _make_layout_draft_payload(
        ntid,
        [
            {"orig": 0, "name": "Card 1", "qfmt": "{{Front}}", "afmt": "{{Back}}"},
            {"orig": None, "name": "Card 2", "qfmt": "{{Back}}", "afmt": "{{Front}}"},
        ],
    )
    r = client.post(
        "/card-layout/savelayout", json=payload, headers={"Datastar-Request": "true"}
    )
    assert r.status_code == 200
    after = client.portal.call(
        client.app.state.service.run, lambda col: len(_tmpls(col, ntid))
    )
    assert after == before + 1


# (f) reposition swap persists
def test_reposition_persists(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    # first add a second template so there is something to swap
    p1 = _make_layout_draft_payload(
        ntid,
        [
            {
                "key": "t0",
                "orig": 0,
                "name": "First",
                "qfmt": "{{Front}}",
                "afmt": "{{Back}}",
            },
            {
                "key": "t1",
                "orig": None,
                "name": "Second",
                "qfmt": "{{Back}}",
                "afmt": "{{Front}}",
            },
        ],
    )
    client.post(
        "/card-layout/savelayout", json=p1, headers={"Datastar-Request": "true"}
    )
    # swap positions using draft order
    p2 = {
        "notetypeId": ntid,
        "layoutDraft": {
            "rows": {
                "t0": {
                    "orig": 0,
                    "name": "First",
                    "qfmt": "{{Front}}",
                    "afmt": "{{Back}}",
                },
                "t1": {
                    "orig": 1,
                    "name": "Second",
                    "qfmt": "{{Back}}",
                    "afmt": "{{Front}}",
                },
            },
            "order": ["t1", "t0"],
            "nextId": 2,
            "css": "",
        },
    }
    client.post(
        "/card-layout/savelayout", json=p2, headers={"Datastar-Request": "true"}
    )
    names = client.portal.call(
        client.app.state.service.run, lambda col: _tmpl_names(col, ntid)
    )
    assert names == ["Second", "First"]


# (g) delete a template persists (count down)
def test_delete_template_persists(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    # add a second template first
    p1 = _make_layout_draft_payload(
        ntid,
        [
            {
                "key": "t0",
                "orig": 0,
                "name": "T1",
                "qfmt": "{{Front}}",
                "afmt": "{{Back}}",
            },
            {
                "key": "t1",
                "orig": None,
                "name": "T2",
                "qfmt": "{{Back}}",
                "afmt": "{{Front}}",
            },
        ],
    )
    client.post(
        "/card-layout/savelayout", json=p1, headers={"Datastar-Request": "true"}
    )
    before = client.portal.call(
        client.app.state.service.run, lambda col: len(_tmpls(col, ntid))
    )
    # drop T2 by removing from order and deleting row
    p2 = {
        "notetypeId": ntid,
        "layoutDraft": {
            "rows": {
                "t0": {
                    "orig": 0,
                    "name": "T1",
                    "qfmt": "{{Front}}",
                    "afmt": "{{Back}}",
                },
                "t1": None,
            },
            "order": ["t0"],
            "nextId": 2,
            "css": "",
        },
    }
    client.post(
        "/card-layout/savelayout", json=p2, headers={"Datastar-Request": "true"}
    )
    after = client.portal.call(
        client.app.state.service.run, lambda col: len(_tmpls(col, ntid))
    )
    assert after == before - 1


# (h) deleting all templates -> err fragment + no navigate
def test_delete_all_templates_errors(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    before = client.portal.call(
        client.app.state.service.run, lambda col: _tmpl_names(col, ntid)
    )
    payload = {
        "notetypeId": ntid,
        "layoutDraft": {
            "rows": {},
            "order": [],
            "nextId": 0,
            "css": "",
        },
    }
    r = client.post(
        "/card-layout/savelayout", json=payload, headers={"Datastar-Request": "true"}
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any('"error"' in data for _, data in events)
    assert not any("window.location" in data for _, data in events)
    after = client.portal.call(
        client.app.state.service.run, lambda col: _tmpl_names(col, ntid)
    )
    assert after == before


def test_preview_link_targets_note_of_requested_notetype(client):
    def add_notes(col):
        cloze = col.models.by_name("Cloze")
        cloze_note = col.new_note(cloze)
        cloze_note["Text"] = "Canberra is the capital of {{c1::Australia}}."
        col.add_note(cloze_note, col.decks.id("Default"))

        ntid = _basic_id(col)
        basic_nid = _add_note(col, ntid)
        return ntid, cloze_note.id, basic_nid

    ntid, cloze_nid, basic_nid = client.portal.call(
        client.app.state.service.run, add_notes
    )
    r = client.get(f"/card-layout/{ntid}")

    assert r.status_code == 200
    assert 'id="preview"' in r.text
    assert f'href="/preview/{basic_nid}"' in r.text
    assert f'href="/preview/{cloze_nid}"' not in r.text


def test_preview_is_unavailable_without_notes(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)

    response = client.get(f"/card-layout/{ntid}")

    assert response.status_code == 200
    assert 'id="preview" aria-disabled="true"' in response.text
    assert 'href="/preview/' not in response.text
    assert 'role="status"' in response.text


def test_preview_get_renders_saved_layout_from_native_link(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    nid = client.portal.call(
        client.app.state.service.run, lambda col: _add_note(col, ntid)
    )
    saved_layout = _make_layout_draft_payload(
        ntid,
        [
            {
                "orig": 0,
                "name": "Card 1",
                "qfmt": "{{Front}}<div>SAVED_LAYOUT_MARKER</div>",
                "afmt": "{{FrontSide}}<hr id=answer>{{Back}}",
            }
        ],
    )
    save = client.post(
        "/card-layout/savelayout",
        json=saved_layout,
        headers={"Datastar-Request": "true"},
    )
    assert save.status_code == 200

    editor = client.get(f"/card-layout/{ntid}")
    assert f'href="/preview/{nid}"' in editor.text
    preview = client.get(f"/preview/{nid}")

    assert preview.status_code == 200
    assert "SAVED_LAYOUT_MARKER" in preview.text


def test_multi_new_block_independent_input_and_css(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    payload = {
        "notetypeId": ntid,
        "layoutDraft": {
            "rows": {
                "t0": {
                    "orig": 0,
                    "name": "Edited Existing",
                    "qfmt": "{{Front}}<p>existing</p>",
                    "afmt": "{{FrontSide}}<hr>{{Back}}",
                },
                "t1": {
                    "orig": None,
                    "name": "New Block A",
                    "qfmt": "{{Front}} (A)",
                    "afmt": "{{Back}} (A)",
                },
                "t2": {
                    "orig": None,
                    "name": "New Block B",
                    "qfmt": "{{Front}} (B)",
                    "afmt": "{{Back}} (B)",
                },
            },
            "order": ["t0", "t1", "t2"],
            "nextId": 3,
            "css": ".card { color: navy; }",
        },
    }
    r = client.post(
        "/card-layout/savelayout", json=payload, headers={"Datastar-Request": "true"}
    )
    assert r.status_code == 200
    tmpls = client.portal.call(
        client.app.state.service.run, lambda col: _tmpls(col, ntid)
    )
    assert len(tmpls) == 3
    assert [t["name"] for t in tmpls] == [
        "Edited Existing",
        "New Block A",
        "New Block B",
    ]
    assert tmpls[1]["qfmt"] == "{{Front}} (A)"
    assert tmpls[2]["qfmt"] == "{{Front}} (B)"
    m = client.portal.call(
        client.app.state.service.run, lambda col: col.models.get(ntid)
    )
    assert m["css"] == ".card { color: navy; }"


def test_deleted_records_null_in_map_excluded_on_save(client):
    ntid = client.portal.call(client.app.state.service.run, _basic_id)
    # Add a second template first so we have 2 templates
    p1 = _make_layout_draft_payload(
        ntid,
        [
            {
                "key": "t0",
                "orig": 0,
                "name": "Stay",
                "qfmt": "{{Front}}",
                "afmt": "{{Back}}",
            },
            {
                "key": "t1",
                "orig": None,
                "name": "DeleteMe",
                "qfmt": "{{Back}}",
                "afmt": "{{Front}}",
            },
        ],
    )
    client.post(
        "/card-layout/savelayout", json=p1, headers={"Datastar-Request": "true"}
    )
    # Now simulate Datastar setting row to null and removing from order
    p2 = {
        "notetypeId": ntid,
        "layoutDraft": {
            "rows": {
                "t0": {
                    "orig": 0,
                    "name": "Stay",
                    "qfmt": "{{Front}}",
                    "afmt": "{{Back}}",
                },
                "t1": None,
            },
            "order": ["t0"],
            "nextId": 2,
            "css": "",
        },
    }
    r = client.post(
        "/card-layout/savelayout", json=p2, headers={"Datastar-Request": "true"}
    )
    assert r.status_code == 200
    tmpls = client.portal.call(
        client.app.state.service.run, lambda col: _tmpls(col, ntid)
    )
    assert len(tmpls) == 1
    assert tmpls[0]["name"] == "Stay"
