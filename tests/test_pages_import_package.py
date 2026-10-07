import os
import tempfile
import urllib.parse
from pathlib import Path

import anki.import_export_pb2 as ie
import pytest
from anki.collection import Collection
from conftest import parse_datastar_events
from fastapi.testclient import TestClient

from ankiweb import import_tmp
from ankiweb.app import create_app
from ankiweb.core.config import Settings


@pytest.fixture
def client_and_settings(tmp_path: Path):
    settings = Settings(
        collection_path=tmp_path / "c.anki2",
        import_tmp_dir=tmp_path / "import-tmp",
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c, settings


def _create_test_apkg(out_path: str, front: str = "Test Front", back: str = "Test Back"):
    with tempfile.TemporaryDirectory() as tmp:
        src_col_path = os.path.join(tmp, "src.anki2")
        col = Collection(src_col_path)
        did = col.decks.id("TestDeck")
        assert did is not None
        model = col.models.by_name("Basic")
        assert model is not None
        note = col.new_note(model)
        note["Front"] = front
        note["Back"] = back
        col.add_note(note, did)
        col.export_anki_package(
            out_path=out_path,
            options=ie.ExportAnkiPackageOptions(
                with_scheduling=True,
                with_deck_configs=True,
                with_media=False,
                legacy=False,
            ),
            limit=None,
        )
        col.close()


def test_next_import_anki_package_get_page(client_and_settings):
    client, settings = client_and_settings
    pkg_file = import_tmp.allocate(settings, ".apkg")
    _create_test_apkg(str(pkg_file))

    quoted = urllib.parse.quote(str(pkg_file), safe="")
    resp = client.get(f"/import-anki-package/{quoted}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "route-import-package" in resp.text
    assert "import-package-container" in resp.text
    # Verify controls and labels
    assert "Import any learning progress" in resp.text
    assert "Import any deck presets" in resp.text
    assert "Merge note types" in resp.text
    assert "Update notes" in resp.text
    assert "Update note types" in resp.text
    assert "If newer" in resp.text
    assert "Always" in resp.text
    assert "Never" in resp.text
    assert os.path.basename(str(pkg_file)) in resp.text


def test_next_import_anki_package_do_import_success(client_and_settings):
    client, settings = client_and_settings
    pkg_file = import_tmp.allocate(settings, ".apkg")
    _create_test_apkg(str(pkg_file), front="Hello New Note", back="World Content")

    resp = client.post(
        "/import-anki-package/do-import",
        headers={"Datastar-Request": "true"},
        json={
            "package_path": str(pkg_file),
            "with_scheduling": True,
            "with_deck_configs": True,
            "merge_notetypes": False,
            "update_notes": 0,
            "update_notetypes": 0,
        },
    )
    assert resp.status_code == 200
    events = parse_datastar_events(resp.text)
    assert len(events) >= 1
    # Check rendered log
    html_content = "".join(data for _, data in events)
    assert "Overview" in html_content
    assert "Details" in html_content
    assert "new note imported" in html_content
    assert "Hello New Note" in html_content


def test_next_import_anki_package_rejects_path_outside_tmp(client_and_settings):
    client, _settings = client_and_settings
    resp = client.post(
        "/import-anki-package/do-import",
        headers={"Datastar-Request": "true"},
        json={
            "package_path": "/etc/passwd",
            "with_scheduling": False,
            "with_deck_configs": False,
            "merge_notetypes": False,
            "update_notes": 0,
            "update_notetypes": 0,
        },
    )
    assert resp.status_code == 200
    events = parse_datastar_events(resp.text)
    html_content = "".join(data for _, data in events)
    assert "Import path not allowed" in html_content
    assert "error-box" in html_content

def test_next_import_anki_package_corrupt_file_displays_error(client_and_settings):
    client, settings = client_and_settings
    pkg_file = import_tmp.allocate(settings, ".apkg")
    pkg_file.write_bytes(b"corrupt content not zip")

    resp = client.post(
        "/import-anki-package/do-import",
        headers={"Datastar-Request": "true"},
        json={
            "package_path": str(pkg_file),
            "with_scheduling": False,
            "with_deck_configs": False,
            "merge_notetypes": False,
            "update_notes": 0,
            "update_notetypes": 0,
        },
    )
    assert resp.status_code == 200
    events = parse_datastar_events(resp.text)
    html_content = "".join(data for _, data in events)
    assert "invalid Zip archive: Could not find EOCD" in html_content
    assert "error-box" in html_content


def test_next_import_anki_package_empty_file_displays_error(client_and_settings):
    client, settings = client_and_settings
    pkg_file = import_tmp.allocate(settings, ".apkg")
    pkg_file.write_bytes(b"")

    resp = client.post(
        "/import-anki-package/do-import",
        headers={"Datastar-Request": "true"},
        json={
            "package_path": str(pkg_file),
            "with_scheduling": False,
            "with_deck_configs": False,
            "merge_notetypes": False,
            "update_notes": 0,
            "update_notetypes": 0,
        },
    )
    assert resp.status_code == 200
    events = parse_datastar_events(resp.text)
    html_content = "".join(data for _, data in events)
    assert "invalid Zip archive: Could not find EOCD" in html_content
    assert "error-box" in html_content


def test_next_import_anki_package_missing_file_displays_error(client_and_settings):
    client, settings = client_and_settings
    missing_file = import_tmp.dir(settings) / "nonexistent.apkg"

    resp = client.post(
        "/import-anki-package/do-import",
        headers={"Datastar-Request": "true"},
        json={
            "package_path": str(missing_file),
            "with_scheduling": False,
            "with_deck_configs": False,
            "merge_notetypes": False,
            "update_notes": 0,
            "update_notetypes": 0,
        },
    )
    assert resp.status_code == 200
    events = parse_datastar_events(resp.text)
    html_content = "".join(data for _, data in events)
    assert "No such file or directory" in html_content
    assert "error-box" in html_content


def test_next_import_page_direct_route(client_and_settings):
    client, settings = client_and_settings
    pkg_file = import_tmp.allocate(settings, ".apkg")
    _create_test_apkg(str(pkg_file), front="Direct Note", back="Direct Back")

    quoted = urllib.parse.quote(str(pkg_file), safe="")
    resp = client.get(f"/import-page/{quoted}")
    assert resp.status_code == 200
    assert "Overview" in resp.text
    assert "Details" in resp.text
    assert "Direct Note" in resp.text


def test_next_import_page_duplicate_log_flow(client_and_settings):
    client, settings = client_and_settings
    pkg_file = import_tmp.allocate(settings, ".apkg")
    _create_test_apkg(str(pkg_file), front="Dup Note", back="Dup Back")

    # Import once
    resp1 = client.post(
        "/import-anki-package/do-import",
        headers={"Datastar-Request": "true"},
        json={
            "package_path": str(pkg_file),
            "with_scheduling": False,
            "with_deck_configs": False,
            "merge_notetypes": False,
            "update_notes": 0,
            "update_notetypes": 0,
        },
    )
    assert resp1.status_code == 200

    # Import twice: should report skipped/duplicate
    resp2 = client.post(
        "/import-anki-package/do-import",
        headers={"Datastar-Request": "true"},
        json={
            "package_path": str(pkg_file),
            "with_scheduling": False,
            "with_deck_configs": False,
            "merge_notetypes": False,
            "update_notes": 0,
            "update_notetypes": 0,
        },
    )
    assert resp2.status_code == 200
    events = parse_datastar_events(resp2.text)
    html_content = "".join(data for _, data in events)
    assert "already present in your collection" in html_content
    assert "Dup Note" in html_content


def test_next_import_page_browse_search_query_generation(client_and_settings):
    import anki.import_export_pb2 as ie

    from ankiweb.adapters.inbound.http_pages.import_package import (
        _build_log_summary_and_rows,
    )
    resp_pb = ie.ImportResponse()
    log = resp_pb.log
    log.found_notes = 3
    n1 = log.new.add()
    n1.id.nid = 111111
    n1.fields.append("F1")
    n2 = log.new.add()
    n2.id.nid = 222222
    n2.fields.append("F2")
    n3 = log.duplicate.add()
    n3.id.nid = 333333
    n3.fields.append("F3")

    summaries, rows = _build_log_summary_and_rows(log)
    # New summary should have browse_query nid:111111,222222
    assert summaries[0]["browse_query"] == "nid:111111,222222"
    # Duplicate summary should have browse_query nid:333333
    assert summaries[1]["browse_query"] == "nid:333333"
    # Each row has nid
    assert rows[0]["nid"] == 111111
    assert rows[1]["nid"] == 222222
    assert rows[2]["nid"] == 333333


def test_next_import_page_renders_browse_links(client_and_settings):
    client, settings = client_and_settings
    pkg_file = import_tmp.allocate(settings, ".apkg")
    _create_test_apkg(str(pkg_file), front="SearchMe", back="BackContent")

    quoted = urllib.parse.quote(str(pkg_file), safe="")
    resp = client.get(f"/import-page/{quoted}")
    assert resp.status_code == 200
    # Check that href contains /browse?q=nid:
    assert "/browse?q=nid%3A" in resp.text or "/browse?q=nid:" in resp.text
