from typing import Any, cast
import pytest
from pathlib import Path
from urllib.parse import quote
from fastapi.testclient import TestClient

from ankiweb.core.config import Settings
from ankiweb.app import create_app
from ankiweb import import_tmp
from conftest import parse_datastar_events

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c434"
    "0000000a49444154789c6360000002000154a24f1f0000000049454e44ae426082"
)
OCCL_HIDE_ALL = "{{c1::image-occlusion:rect:left=.1:top=.1:width=.2:height=.2:oi=1}}"
OCCL_HIDE_ONE = "{{c1::image-occlusion:rect:left=.1:top=.1:width=.2:height=.2}}"


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(collection_path=tmp_path / "c.anki2"))) as c:
        yield c


def _img_in_tmp(client: TestClient, name: str = "test.png") -> str:
    settings = cast(Any, client.app).state.service.settings
    d = import_tmp.io_dir(settings)
    p = d / name
    p.write_bytes(PNG)
    return str(p)


def test_next_image_occlusion_add_page_serves_html(client):
    img_path = _img_in_tmp(client, "add.png")
    r = client.get(f"/image-occlusion/{quote(img_path, safe='')}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "route-image-occlusion" in r.text
    assert "ankiweb-io-editor" in r.text
    assert "tab-btn-mask" in r.text
    assert "tab-btn-fields" in r.text
    assert "io-field-header" in r.text
    assert "io-field-back-extra" in r.text
    assert "io-field-tags" in r.text
    assert "mode-btn-hide-all" in r.text
    assert "mode-btn-hide-one" in r.text
    assert "io-save-btn" in r.text


def test_next_image_occlusion_add_note_save(client):
    svc = cast(Any, client.app).state.service
    img_path = _img_in_tmp(client, "save_add.png")
    before_notes = client.portal.call(svc.run, lambda col: col.note_count())

    # Get notetype ID for Image Occlusion
    io_nt_id = client.portal.call(
        svc.run,
        lambda col: (col.add_image_occlusion_notetype(), col.models.by_name("Image Occlusion")["id"])[1],
    )

    r = client.post(
        "/image-occlusion/save",
        headers={"Datastar-Request": "true"},
        json={
            "mode": "add",
            "image_path": img_path,
            "header": "My Header",
            "back_extra": "My Back Extra",
            "comments": "My Comment",
            "tags_str": "anatomy test_tag",
            "occlusions": OCCL_HIDE_ALL,
            "hide_all": True,
            "selected_notetype_id": io_nt_id,
            "selected_deck_id": 1,
        },
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    assert any("/deckbrowser" in data for _, data in events)

    after_notes = client.portal.call(svc.run, lambda col: col.note_count())
    assert after_notes == before_notes + 1

    # Verify created note
    nids = client.portal.call(svc.run, lambda col: col.find_notes('note:"Image Occlusion"'))
    assert len(nids) >= 1
    nid = nids[-1]

    def verify_note(col):
        note = col.get_note(nid)
        resp = col.get_image_occlusion_note(note_id=nid).note
        return {
            "header": note["Header"],
            "back_extra": note["Back Extra"],
            "comments": note["Comments"],
            "tags": list(note.tags),
            "cards_count": len(note.cards()),
            "occlude_inactive": resp.occlude_inactive,
            "image_filename": resp.image_file_name,
        }

    note_data = client.portal.call(svc.run, verify_note)
    assert note_data["header"] == "My Header"
    assert note_data["back_extra"] == "My Back Extra"
    assert note_data["comments"] == "My Comment"
    assert "anatomy" in note_data["tags"]
    assert "test_tag" in note_data["tags"]
    assert note_data["cards_count"] == 1
    assert note_data["occlude_inactive"] is True


def test_next_image_occlusion_hide_one_mode(client):
    svc = client.app.state.service
    img_path = _img_in_tmp(client, "hide_one.png")

    io_nt_id = client.portal.call(
        svc.run,
        lambda col: (col.add_image_occlusion_notetype(), col.models.by_name("Image Occlusion")["id"])[1],
    )

    r = client.post(
        "/image-occlusion/save",
        headers={"Datastar-Request": "true"},
        json={
            "mode": "add",
            "image_path": img_path,
            "header": "Hide One Header",
            "back_extra": "Hide One Extra",
            "comments": "",
            "tags_str": "",
            "occlusions": OCCL_HIDE_ALL,  # passed with oi=1 but hide_all is False
            "hide_all": False,
            "selected_notetype_id": io_nt_id,
            "selected_deck_id": 1,
        },
    )
    assert r.status_code == 200

    nids = client.portal.call(svc.run, lambda col: col.find_notes('note:"Image Occlusion"'))
    nid = nids[-1]

    resp = client.portal.call(svc.run, lambda col: col.get_image_occlusion_note(note_id=nid).note)
    assert resp.occlude_inactive is False


def test_next_image_occlusion_edit_page_and_update(client):
    svc = client.app.state.service
    img_path = _img_in_tmp(client, "edit_test.png")

    # Create initial note
    def create_note(col):
        col.add_image_occlusion_notetype()
        nt = col.models.by_name("Image Occlusion")
        col.add_image_occlusion_note(
            notetype_id=nt["id"],
            image_path=img_path,
            occlusions=OCCL_HIDE_ALL,
            header="Initial Header",
            back_extra="Initial Extra",
            tags=["tag1"],
        )
        return col.find_notes('note:"Image Occlusion"')[-1]

    nid = client.portal.call(svc.run, create_note)

    # 1. GET /image-occlusion/{nid}
    r = client.get(f"/image-occlusion/{nid}")
    assert r.status_code == 200
    assert "route-image-occlusion" in r.text
    assert "Initial Header" in r.text
    assert "Initial Extra" in r.text
    assert "tag1" in r.text

    # 2. POST /image-occlusion/save in edit mode
    upd_occl = "{{c1::image-occlusion:rect:left=.1:top=.1:width=.2:height=.2:oi=1}} {{c2::image-occlusion:rect:left=.3:top=.3:width=.2:height=.2:oi=1}}"
    r_upd = client.post(
        "/image-occlusion/save",
        headers={"Datastar-Request": "true"},
        json={
            "mode": "edit",
            "note_id": nid,
            "header": "Updated Header",
            "back_extra": "Updated Extra",
            "comments": "Updated Comment",
            "tags_str": "tag1 tag2",
            "occlusions": upd_occl,
            "hide_all": True,
        },
    )
    assert r_upd.status_code == 200

    def verify_updated(col):
        note = col.get_note(nid)
        resp = col.get_image_occlusion_note(note_id=nid).note
        return {
            "header": note["Header"],
            "back_extra": note["Back Extra"],
            "comments": note["Comments"],
            "tags": list(note.tags),
            "cards_count": len(note.cards()),
            "occlude_inactive": resp.occlude_inactive,
        }

    updated_data = client.portal.call(svc.run, verify_updated)
    assert updated_data["header"] == "Updated Header"
    assert updated_data["back_extra"] == "Updated Extra"
    assert updated_data["comments"] == "Updated Comment"
    assert set(updated_data["tags"]) == {"tag1", "tag2"}
    assert updated_data["cards_count"] == 2
    assert updated_data["occlude_inactive"] is True


def test_next_image_occlusion_path_confinement_error(client):
    r = client.get("/image-occlusion/%2Fetc%2Fpasswd")
    assert r.status_code == 403


def test_next_image_occlusion_nonexistent_note_404(client):
    r = client.get("/image-occlusion/999999999")
    assert r.status_code == 404


def test_next_image_occlusion_zero_shapes_rejected(client):
    svc = client.app.state.service
    img_path = _img_in_tmp(client, "empty_save.png")
    before_notes = client.portal.call(svc.run, lambda col: col.note_count())

    r = client.post(
        "/image-occlusion/save",
        headers={"Datastar-Request": "true"},
        json={
            "mode": "add",
            "image_path": img_path,
            "header": "Empty Header",
            "back_extra": "",
            "comments": "",
            "tags_str": "",
            "occlusions": "",
            "shapes_count": 0,
            "hide_all": True,
        },
    )
    assert r.status_code == 200
    events = parse_datastar_events(r.text)
    # Assert no redirect to /deckbrowser was sent
    assert not any("/deckbrowser" in data for _, data in events)
    # Assert notes count remained unchanged
    after_notes = client.portal.call(svc.run, lambda col: col.note_count())
    assert after_notes == before_notes
    # Assert danger status_msg was returned
    assert any("Cannot save" in data for _, data in events)
