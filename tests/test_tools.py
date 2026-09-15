import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from ankiweb.config import Settings
from ankiweb.app import create_app
from ankiweb.adapters.inbound.http_shared.page import render_page
from ankiweb.adapters.inbound.http_datastar.tools import render_tools_html
from conftest import parse_datastar_events


# ---- render tests -------------------------------------------------------


def test_render_tools_has_three_buttons_and_notetypes_link(temp_collection):
    html = render_tools_html(temp_collection)
    assert "Check Database" in html
    assert "Check Media" in html
    assert "Empty Cards" in html
    assert "Manage Note Types" in html
    assert "href='/notetypes'" in html or 'href="/notetypes"' in html
    assert "id='res-db'" in html or 'id="res-db"' in html
    assert "id='res-media'" in html or 'id="res-media"' in html
    assert "id='res-empty'" in html or 'id="res-empty"' in html


def test_render_tools_translates(temp_collection):
    import anki.lang

    anki.lang.set_lang("zh-CN")
    html = render_tools_html(temp_collection)
    assert "检查数据库" in html


# ---- handler round-trips -----------------------------------------------


def test_checkdb_pushes_report(tmp_path: Path):
    with TestClient(
        create_app(Settings(collection_path=tmp_path / "c.anki2"))
    ) as client:
        r = client.post("/tools/checkdb")
        assert r.status_code == 200
        events = parse_datastar_events(r.text)
        assert any(
            "res-db" in data
            and (
                "checked" in data.lower()
                or "database" in data.lower()
                or "no problems" in data.lower()
            )
            for _, data in events
        )


def test_checkmedia_pushes_report(tmp_path: Path):
    with TestClient(
        create_app(Settings(collection_path=tmp_path / "c.anki2"))
    ) as client:
        r = client.post("/tools/checkmedia")
        assert r.status_code == 200
        events = parse_datastar_events(r.text)
        assert any(
            "res-media" in data
            and (
                "missing" in data.lower()
                or "unused" in data.lower()
                or "files" in data.lower()
            )
            for _, data in events
        )


def test_emptycards_roundtrip_deletes(tmp_path: Path):
    with TestClient(
        create_app(Settings(collection_path=tmp_path / "c.anki2"))
    ) as client:

        def seed(col):
            cloze_model = col.models.by_name("Cloze")
            note = col.new_note(cloze_model)
            note["Text"] = "plain text with no cloze marker"
            col.add_note(note, col.decks.id("Default"))
            return len(col.find_cards(""))

        before = client.portal.call(client.app.state.service.run, seed)
        assert before >= 1

        # 1. Ask for the report.
        r1 = client.post("/tools/emptycards")
        assert r1.status_code == 200
        events1 = parse_datastar_events(r1.text)
        assert any("emptycards_delete" in data for _, data in events1)

        # 2. Click delete -> should delete the empty cards.
        r2 = client.post("/tools/emptycards_delete")
        assert r2.status_code == 200
        events2 = parse_datastar_events(r2.text)
        assert any("Deleted 1 empty cards" in data for _, data in events2)

        after = client.portal.call(
            client.app.state.service.run, lambda col: len(col.find_cards(""))
        )
        assert after == before - 1


def test_deleteunused_no_files_is_noop(tmp_path: Path):
    with TestClient(
        create_app(Settings(collection_path=tmp_path / "c.anki2"))
    ) as client:
        r = client.post("/tools/deleteunused")
        assert r.status_code == 200
        events = parse_datastar_events(r.text)
        assert any("res-media" in data for _, data in events)


# ---- toolbar ------------------------------------------------------------


def test_toolbar_has_tools_link():
    html = render_page("deckbrowser", "x")
    assert "/tools" in html and "Tools" in html


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(collection_path=tmp_path / "c.anki2"))) as c:
        yield c


def test_tools_route_renders(client):
    r = client.get("/tools")
    assert r.status_code == 200
    assert "Check Database" in r.text
    assert "Check Media" in r.text
    assert "Empty Cards" in r.text
    assert "href='/notetypes'" in r.text or 'href="/notetypes"' in r.text
