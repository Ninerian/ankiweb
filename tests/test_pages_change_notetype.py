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


def _basic_and_cloze_and_rev(client):
    def ids(col):
        return (
            col.models.by_name("Basic")["id"],
            col.models.by_name("Cloze")["id"],
            col.models.by_name("Basic (and reversed card)")["id"],
        )

    return client.portal.call(client.app.state.service.run, ids)


def _seed_note(client, notetype_id, prefix="note"):
    def seed(col):
        note = col.new_note(col.models.get(notetype_id))
        for index, field_name in enumerate(note.keys()):
            note[field_name] = f"{prefix}-{index}"
        col.add_note(note, col.decks.id("Default"))
        card_ids = [
            cid
            for cid in col.find_cards("")
            if col.get_card(cid).nid == note.id
        ]
        return note.id, card_ids

    return client.portal.call(client.app.state.service.run, seed)


def _signals(content):
    match = re.search(r'data-signals="([^"]+)"', content)
    assert match is not None
    return json.loads(html.unescape(match.group(1)))


def _assert_invalid_selection_response(response):
    assert response.status_code == 200
    assert "alert-error" in response.text


def test_change_notetype_get_resolves_selected_cards_and_deduplicates_notes(
    client,
):
    _basic_id, _cloze_id, reverse_id = _basic_and_cloze_and_rev(client)
    selected_nid, selected_cids = _seed_note(client, reverse_id, "selected")
    assert len(selected_cids) == 2

    response = client.get(
        "/change-notetype?cids=" + ",".join(map(str, selected_cids))
    )

    assert response.status_code == 200
    signals = _signals(response.text)
    assert signals["old_notetype_id"] == reverse_id
    assert signals["target_notetype_id"] == reverse_id
    assert signals["note_ids"] == [selected_nid]


@pytest.mark.parametrize(
    "selection",
    [
        "missing",
        "empty",
        "malformed",
        "malformed-list",
        "zero",
        "negative",
        "nonexistent",
    ],
)
def test_change_notetype_get_rejects_invalid_card_selections(client, selection):
    basic_id, _cloze_id, _reverse_id = _basic_and_cloze_and_rev(client)
    _nid, cids = _seed_note(client, basic_id)
    valid_cid = cids[0]
    if selection == "missing":
        url = "/change-notetype"
    else:
        raw = {
            "empty": "",
            "malformed": "not-a-card",
            "malformed-list": f"{valid_cid},not-a-card",
            "zero": "0",
            "negative": "-1",
            "nonexistent": "999999999999",
        }[selection]
        url = f"/change-notetype?cids={raw}"

    response = client.get(url)

    assert response.status_code == 400
    assert "Invalid card selection" in response.text


def test_change_notetype_get_rejects_cards_from_multiple_note_types(client):
    basic_id, _cloze_id, reverse_id = _basic_and_cloze_and_rev(client)
    _basic_nid, basic_cids = _seed_note(client, basic_id, "basic")
    _reverse_nid, reverse_cids = _seed_note(client, reverse_id, "reverse")

    response = client.get(
        f"/change-notetype?cids={basic_cids[0]},{reverse_cids[0]}"
    )

    assert response.status_code == 400
    assert "Invalid card selection" in response.text


def test_change_notetype_selection_survives_mapping_and_only_selected_note_converts(
    client,
):
    basic_id, _cloze_id, reverse_id = _basic_and_cloze_and_rev(client)
    selected_nid, selected_cids = _seed_note(client, reverse_id, "selected")
    unselected_nid, _unselected_cids = _seed_note(client, reverse_id, "unselected")
    headers = {"Datastar-Request": "true"}

    page = client.get(
        "/change-notetype?cids=" + ",".join(map(str, selected_cids))
    )
    assert page.status_code == 200
    assert _signals(page.text)["note_ids"] == [selected_nid]

    base_payload = {
        "old_notetype_id": reverse_id,
        "target_notetype_id": basic_id,
        "note_ids": [selected_nid],
        "field_map_0": 0,
        "field_map_1": 1,
        "template_map_0": 0,
    }
    selected = client.post(
        "/change-notetype/select-target", headers=headers, json=base_payload
    )
    assert selected.status_code == 200
    assert _signals(selected.text)["note_ids"] == [selected_nid]

    remapped_fields = client.post(
        "/change-notetype/remap-field?new_index=0",
        headers=headers,
        json=base_payload,
    )
    assert remapped_fields.status_code == 200
    assert _signals(remapped_fields.text)["note_ids"] == [selected_nid]

    remapped_templates = client.post(
        "/change-notetype/remap-template?new_index=0",
        headers=headers,
        json=base_payload,
    )
    assert remapped_templates.status_code == 200
    assert _signals(remapped_templates.text)["note_ids"] == [selected_nid]

    save_payload = {**base_payload, "note_ids": [str(selected_nid)]}
    saved = client.post(
        "/change-notetype/save", headers=headers, json=save_payload
    )
    assert saved.status_code == 200

    def read_result(col):
        selected = col.get_note(selected_nid)
        unselected = col.get_note(unselected_nid)
        return (
            selected.mid,
            selected["Front"],
            selected["Back"],
            unselected.mid,
        )

    selected_mid, front, back, unselected_mid = client.portal.call(
        client.app.state.service.run, read_result
    )
    assert selected_mid == basic_id
    assert (front, back) == ("selected-0", "selected-1")
    assert unselected_mid == reverse_id


def test_change_notetype_remap_template_prevents_duplicate_mapping_and_keeps_scope(
    client,
):
    basic_id, _cloze_id, reverse_id = _basic_and_cloze_and_rev(client)
    nid, _cids = _seed_note(client, basic_id)

    response = client.post(
        "/change-notetype/remap-template?new_index=1",
        headers={"Datastar-Request": "true"},
        json={
            "old_notetype_id": basic_id,
            "target_notetype_id": reverse_id,
            "note_ids": [nid],
            "template_map_0": 0,
            "template_map_1": 0,
        },
    )

    assert response.status_code == 200
    signals = _signals(response.text)
    assert signals["note_ids"] == [nid]
    assert signals["template_map_0"] == -1
    assert signals["template_map_1"] == 0


@pytest.mark.parametrize(
    "endpoint", ["select-target", "remap-field", "remap-template"]
)
@pytest.mark.parametrize(
    "invalid_case",
    [
        "missing",
        "empty",
        "malformed",
        "nonpositive",
        "boolean",
        "fractional",
        "deleted",
        "wrong-type",
    ],
)
def test_change_notetype_mapping_posts_reject_invalid_note_ids(
    client, endpoint, invalid_case
):
    basic_id, _cloze_id, reverse_id = _basic_and_cloze_and_rev(client)
    valid_nid, _ = _seed_note(client, basic_id, "valid")
    deleted_nid, _ = _seed_note(client, basic_id, "deleted")
    wrong_type_nid, _ = _seed_note(client, reverse_id, "wrong-type")
    client.portal.call(
        client.app.state.service.run, lambda col: col.remove_notes([deleted_nid])
    )

    payload = {
        "old_notetype_id": basic_id,
        "target_notetype_id": reverse_id,
        "field_map_0": 0,
        "field_map_1": 1,
        "template_map_0": 0,
        "template_map_1": -1,
    }
    invalid_values = {
        "empty": [],
        "malformed": [valid_nid, "not-an-integer"],
        "nonpositive": [valid_nid, 0],
        "boolean": [valid_nid, True],
        "fractional": [valid_nid, 1.5],
        "deleted": [valid_nid, deleted_nid],
        "wrong-type": [valid_nid, wrong_type_nid],
    }
    if invalid_case != "missing":
        payload["note_ids"] = invalid_values[invalid_case]

    path = f"/change-notetype/{endpoint}"
    if endpoint == "remap-field":
        path += "?new_index=0"
    elif endpoint == "remap-template":
        path += "?new_index=0"
    response = client.post(
        path, headers={"Datastar-Request": "true"}, json=payload
    )

    _assert_invalid_selection_response(response)

    def read_types(col):
        return col.get_note(valid_nid).mid, col.get_note(wrong_type_nid).mid

    assert client.portal.call(client.app.state.service.run, read_types) == (
        basic_id,
        reverse_id,
    )


@pytest.mark.parametrize(
    "invalid_case",
    [
        "missing",
        "empty",
        "malformed",
        "nonpositive",
        "boolean",
        "fractional",
        "deleted",
        "wrong-type",
    ],
)
def test_change_notetype_save_rejects_invalid_note_ids_without_mutation(
    client, invalid_case
):
    basic_id, _cloze_id, reverse_id = _basic_and_cloze_and_rev(client)
    valid_nid, _ = _seed_note(client, basic_id, "valid")
    unselected_nid, _ = _seed_note(client, basic_id, "unselected")
    deleted_nid, _ = _seed_note(client, basic_id, "deleted")
    wrong_type_nid, _ = _seed_note(client, reverse_id, "wrong-type")
    client.portal.call(
        client.app.state.service.run, lambda col: col.remove_notes([deleted_nid])
    )

    payload = {
        "old_notetype_id": basic_id,
        "target_notetype_id": reverse_id,
        "field_map_0": 0,
        "field_map_1": 1,
        "template_map_0": 0,
        "template_map_1": -1,
    }
    invalid_values = {
        "empty": [],
        "malformed": [valid_nid, "not-an-integer"],
        "nonpositive": [valid_nid, 0],
        "boolean": [valid_nid, True],
        "fractional": [valid_nid, 1.5],
        "deleted": [valid_nid, deleted_nid],
        "wrong-type": [valid_nid, wrong_type_nid],
    }
    if invalid_case != "missing":
        payload["note_ids"] = invalid_values[invalid_case]

    response = client.post(
        "/change-notetype/save",
        headers={"Datastar-Request": "true"},
        json=payload,
    )

    _assert_invalid_selection_response(response)

    def read_types(col):
        return (
            col.get_note(valid_nid).mid,
            col.get_note(unselected_nid).mid,
            col.get_note(wrong_type_nid).mid,
        )

    assert client.portal.call(client.app.state.service.run, read_types) == (
        basic_id,
        basic_id,
        reverse_id,
    )


def test_change_notetype_save_rejects_empty_selection_before_noop_branch(client):
    basic_id, _cloze_id, _reverse_id = _basic_and_cloze_and_rev(client)
    nid, _cids = _seed_note(client, basic_id)

    response = client.post(
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

    _assert_invalid_selection_response(response)
    assert client.portal.call(
        client.app.state.service.run, lambda col: col.get_note(nid).mid
    ) == basic_id


@pytest.mark.parametrize(
    "endpoint", ["select-target", "remap-field", "remap-template", "save"]
)
def test_change_notetype_posts_reject_malformed_notetype_ids(client, endpoint):
    basic_id, _cloze_id, reverse_id = _basic_and_cloze_and_rev(client)
    nid, _cids = _seed_note(client, basic_id)
    path = f"/change-notetype/{endpoint}"
    if endpoint in {"remap-field", "remap-template"}:
        path += "?new_index=0"
    response = client.post(
        path,
        headers={"Datastar-Request": "true"},
        json={
            "old_notetype_id": "not-an-id",
            "target_notetype_id": reverse_id,
            "note_ids": [nid],
            "field_map_0": 0,
            "field_map_1": 1,
            "template_map_0": 0,
            "template_map_1": -1,
        },
    )

    _assert_invalid_selection_response(response)
    assert client.portal.call(
        client.app.state.service.run, lambda col: col.get_note(nid).mid
    ) == basic_id


def _change_note_type_for_test(client, note_id, old_id, new_id):
    def change(col):
        info = col.models.change_notetype_info(
            old_notetype_id=old_id, new_notetype_id=new_id
        )
        request = info.input
        col._backend.change_notetype(
            note_ids=[note_id],
            new_fields=list(request.new_fields),
            new_templates=list(request.new_templates),
            old_notetype_id=old_id,
            new_notetype_id=new_id,
            current_schema=request.current_schema,
            old_notetype_name=request.old_notetype_name,
            is_cloze=request.is_cloze,
        )

    client.portal.call(client.app.state.service.run, change)


def test_change_notetype_save_revalidates_stale_note_type(client):
    basic_id, cloze_id, reverse_id = _basic_and_cloze_and_rev(client)
    stale_nid, stale_cids = _seed_note(client, basic_id, "stale")
    unselected_nid, _ = _seed_note(client, basic_id, "unselected")
    page = client.get(f"/change-notetype?cids={stale_cids[0]}")
    assert page.status_code == 200
    assert _signals(page.text)["note_ids"] == [stale_nid]

    _change_note_type_for_test(client, stale_nid, basic_id, cloze_id)
    response = client.post(
        "/change-notetype/save",
        headers={"Datastar-Request": "true"},
        json={
            "old_notetype_id": basic_id,
            "target_notetype_id": reverse_id,
            "note_ids": [stale_nid],
            "field_map_0": 0,
            "field_map_1": 1,
            "template_map_0": 0,
            "template_map_1": -1,
        },
    )

    _assert_invalid_selection_response(response)

    def read_types(col):
        return col.get_note(stale_nid).mid, col.get_note(unselected_nid).mid

    assert client.portal.call(client.app.state.service.run, read_types) == (
        cloze_id,
        basic_id,
    )
