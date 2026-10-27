import asyncio
import threading
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlsplit

import pytest
import uvicorn
from anki.cards import CardId
from anki.collection import Collection
from anki.dbproxy import Row
from anki.models import NotetypeId
from anki.notes import NoteId
from fastapi import FastAPI

from ankiweb.app import create_app
from ankiweb.core.config import Settings

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright

_SOURCE_NOTETYPE_NAME = "CurrentNoteType" + "x" * 64
_TARGET_NOTETYPE_NAME = "NewNoteType" + "x" * 64
_SOURCE_FIELDS = ("CurrentFirstField" + "x" * 64, "CurrentSecondField" + "x" * 64)
_TARGET_FIELDS = ("NewFirstField" + "x" * 64, "NewSecondField" + "x" * 64)
_SOURCE_TEMPLATES = (
    "CurrentCardTemplate" + "x" * 64,
    "CurrentSecondTemplate" + "x" * 64,
)
_TARGET_TEMPLATES = (
    "NewCardTemplate" + "x" * 64,
    "NewSecondTemplate" + "x" * 64,
)


class _NotetypeSnapshot(TypedDict):
    name: str
    config: bytes
    fields: list[tuple[int, str, bytes]]
    templates: list[tuple[int, str, bytes]]


type _NotetypeState = tuple[
    str,
    tuple[str, ...],
    tuple[tuple[str, bytes], ...],
    bytes,
    tuple[bytes, ...],
]
type _CollectionSnapshot = tuple[
    tuple[int, int, str],
    tuple[Row, ...],
    dict[int, _NotetypeState],
]


class _ChangeNotetypeFixture(TypedDict):
    url: str
    app: FastAPI
    basic_cid: CardId
    source_note_id: NoteId
    source_card_ids: list[CardId]
    source_model_id: NotetypeId
    target_model_id: NotetypeId


def _read_collection_snapshot(
    app: FastAPI,
    note_id: NoteId,
    source_model_id: NotetypeId,
    target_model_id: NotetypeId,
) -> _CollectionSnapshot:
    model_ids = (source_model_id, target_model_id)

    def read(col: Collection) -> _CollectionSnapshot:
        db = col.db
        assert db is not None
        note = db.first("SELECT id, mid, flds FROM notes WHERE id = ?", note_id)
        cards = db.all(
            "SELECT id, nid, ord FROM cards WHERE nid = ? ORDER BY id", note_id
        )
        notetype_rows = db.all(
            "SELECT id, name, config FROM notetypes NOT INDEXED "
            "WHERE id IN (?, ?) ORDER BY id",
            *model_ids,
        )
        field_rows = db.all(
            "SELECT ntid, ord, name, config FROM fields NOT INDEXED "
            "WHERE ntid IN (?, ?) ORDER BY ntid, ord",
            *model_ids,
        )
        template_rows = db.all(
            "SELECT ntid, ord, name, config FROM templates NOT INDEXED "
            "WHERE ntid IN (?, ?) ORDER BY ntid, ord",
            *model_ids,
        )
        assert note is not None
        models_by_id: dict[int, _NotetypeSnapshot] = {
            model_id: {
                "name": name,
                "config": bytes(config),
                "fields": [],
                "templates": [],
            }
            for model_id, name, config in notetype_rows
        }
        assert set(models_by_id) == set(model_ids)
        for notetype_id, ordinal, name, config in field_rows:
            models_by_id[notetype_id]["fields"].append((ordinal, name, bytes(config)))
        for notetype_id, ordinal, name, config in template_rows:
            models_by_id[notetype_id]["templates"].append(
                (ordinal, name, bytes(config))
            )

        model_state: dict[int, _NotetypeState] = {}
        for model_id, model in models_by_id.items():
            model_state[model_id] = (
                model["name"],
                tuple(name for _ordinal, name, _config in model["fields"]),
                tuple((name, config) for _ordinal, name, config in model["templates"]),
                model["config"],
                tuple(config for _ordinal, _name, config in model["fields"]),
            )
        return tuple(note), tuple(cards), model_state

    return asyncio.run_coroutine_threadsafe(
        app.state.service.run(read), app.state.test_loop
    ).result(timeout=10)


def _assert_controls_fit(page, selectors: list[str]) -> None:
    viewport = page.viewport_size
    assert viewport is not None
    document_width, layout_width = page.locator("html").evaluate(
        "element => [element.scrollWidth, element.clientWidth]"
    )
    assert document_width <= layout_width

    for selector in selectors:
        locator = page.locator(selector)
        assert locator.is_visible(), selector
        locator.scroll_into_view_if_needed()
        bounds = locator.bounding_box()
        assert bounds is not None, selector
        assert bounds["x"] >= 0, selector
        assert bounds["x"] + bounds["width"] <= viewport["width"], selector


@pytest.fixture
def live_server_cnt(tmp_path: Path) -> Iterator[_ChangeNotetypeFixture]:
    col_path = tmp_path / "c.anki2"
    col = Collection(str(col_path))
    try:
        basic_nt = col.models.by_name("Basic")
        assert basic_nt is not None
        basic_note = col.new_note(basic_nt)
        basic_note["Front"] = "x"
        basic_note["Back"] = "y"
        did = col.decks.id("Default")
        assert did is not None
        col.add_note(basic_note, did)
        basic_cid = CardId(col.find_cards("")[0])

        source = col.models.new(_SOURCE_NOTETYPE_NAME)
        for field_name in _SOURCE_FIELDS:
            col.models.add_field(source, col.models.new_field(field_name))
        for index, template_name in enumerate(_SOURCE_TEMPLATES):
            template = col.models.new_template(template_name)
            template["qfmt"] = "{{" + _SOURCE_FIELDS[index] + "}}"
            template["afmt"] = (
                "{{FrontSide}}<hr id=answer>{{" + _SOURCE_FIELDS[1 - index] + "}}"
            )
            col.models.add_template(source, template)
        col.models.add_dict(source)

        target = col.models.new(_TARGET_NOTETYPE_NAME)
        for field_name in _TARGET_FIELDS:
            col.models.add_field(target, col.models.new_field(field_name))
        for index, template_name in enumerate(_TARGET_TEMPLATES):
            template = col.models.new_template(template_name)
            template["qfmt"] = "{{" + _TARGET_FIELDS[index] + "}}"
            template["afmt"] = (
                "{{FrontSide}}<hr id=answer>{{" + _TARGET_FIELDS[1 - index] + "}}"
            )
            col.models.add_template(target, template)
        col.models.add_dict(target)

        source = col.models.by_name(_SOURCE_NOTETYPE_NAME)
        target = col.models.by_name(_TARGET_NOTETYPE_NAME)
        assert source is not None
        assert target is not None
        source_note = col.new_note(source)
        source_note[_SOURCE_FIELDS[0]] = "first-value"
        source_note[_SOURCE_FIELDS[1]] = "second-value"
        col.add_note(source_note, did)
        source_note_id = source_note.id
        source_card_ids = sorted(
            cid for cid in col.find_cards("") if col.get_card(cid).nid == source_note_id
        )
        assert len(source_card_ids) == 2
        source_model_id = NotetypeId(int(source["id"]))
        target_model_id = NotetypeId(int(target["id"]))
    finally:
        col.close()

    settings = Settings(collection_path=col_path, port=8132)
    app = create_app(settings)
    app_lifespan_context = app.router.lifespan_context

    @asynccontextmanager
    async def record_test_loop(application):
        application.state.test_loop = asyncio.get_running_loop()
        async with app_lifespan_context(application):
            yield

    app.router.lifespan_context = record_test_loop
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=8132, log_level="warning")
    )
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("server did not start")
        time.sleep(0.05)
    try:
        yield {
            "url": "http://127.0.0.1:8132",
            "app": app,
            "basic_cid": basic_cid,
            "source_note_id": source_note_id,
            "source_card_ids": source_card_ids,
            "source_model_id": source_model_id,
            "target_model_id": target_model_id,
        }
    finally:
        server.should_exit = True
        t.join(timeout=5)


def test_change_notetype_page_boots(live_server_cnt):
    url = live_server_cnt["url"]
    cid = live_server_cnt["basic_cid"]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{url}/change-notetype?cids={cid}")
        page.wait_for_selector("#target-notetype-select", timeout=10000)
        page.wait_for_selector("#change-notetype-save-btn", timeout=10000)
        assert not errors, errors
        assert page.locator("#target-notetype-select").is_visible()
        assert page.locator("#change-notetype-save-btn").is_visible()
        browser.close()


def test_mobile_cancel_after_remapping_preserves_collection(live_server_cnt):
    fixture = live_server_cnt
    url = fixture["url"]
    source_note_id = fixture["source_note_id"]
    source_model_id = fixture["source_model_id"]
    target_model_id = fixture["target_model_id"]
    before = _read_collection_snapshot(
        fixture["app"], source_note_id, source_model_id, target_model_id
    )
    cids = ",".join(str(cid) for cid in fixture["source_card_ids"])
    controls = [
        "#source-notetype-select",
        "#target-notetype-select",
        "#change-notetype-cancel-btn",
        "#change-notetype-save-btn",
        'select[data-bind="field_map_0"]',
        'select[data-bind="field_map_1"]',
        'select[data-bind="template_map_0"]',
        'select[data-bind="template_map_1"]',
    ]
    requests = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": 375, "height": 900},
            is_mobile=True,
            has_touch=True,
        )
        page = context.new_page()
        page.on(
            "request",
            lambda request: requests.append(
                (request.method, urlsplit(request.url).path)
            ),
        )
        page.goto(f"{url}/change-notetype?cids={cids}")
        page.wait_for_selector("#target-notetype-select", timeout=10000)
        assert page.locator('label[for="source-notetype-select"]').is_visible()
        assert page.locator('label[for="target-notetype-select"]').is_visible()
        _assert_controls_fit(page, controls)

        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and urlsplit(response.url).path == "/change-notetype/select-target"
            )
        ) as target_response:
            page.locator("#target-notetype-select").select_option(str(target_model_id))
        assert target_response.value.status == 200
        assert page.locator("#target-notetype-select").input_value() == str(
            target_model_id
        )
        assert page.get_by_text(_TARGET_FIELDS[0], exact=True).is_visible()
        assert page.get_by_text(_TARGET_FIELDS[1], exact=True).is_visible()
        assert page.get_by_text(_TARGET_TEMPLATES[0], exact=True).is_visible()
        assert page.get_by_text(_TARGET_TEMPLATES[1], exact=True).is_visible()
        _assert_controls_fit(page, controls)

        field_map = page.locator('select[data-bind="field_map_0"]')
        field_value = "1" if field_map.input_value() != "1" else "0"
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and urlsplit(response.url).path == "/change-notetype/remap-field"
            )
        ) as field_response:
            field_map.select_option(field_value)
        assert field_response.value.status == 200
        assert field_map.input_value() == field_value
        _assert_controls_fit(page, controls)

        template_map = page.locator('select[data-bind="template_map_0"]')
        template_value = "1" if template_map.input_value() != "1" else "0"
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and urlsplit(response.url).path == "/change-notetype/remap-template"
            )
        ) as template_response:
            template_map.select_option(template_value)
        assert template_response.value.status == 200
        assert template_map.input_value() == template_value
        _assert_controls_fit(page, controls)

        target_select = page.locator("#target-notetype-select")
        target_select.focus()
        expect(target_select).to_be_focused()
        page.keyboard.press("Tab")
        expect(page.locator("#change-notetype-cancel-btn")).to_be_focused()
        page.keyboard.press("Tab")
        expect(page.locator("#change-notetype-save-btn")).to_be_focused()
        page.keyboard.press("Tab")
        expect(page.locator('select[data-bind="field_map_0"]')).to_be_focused()

        assert (
            page.locator("#change-notetype-cancel-btn").get_attribute("href")
            == "/browse"
        )
        page.locator("#change-notetype-cancel-btn").tap()
        page.wait_for_url(f"{url}/browse")
        assert ("GET", "/browse") in requests
        assert ("POST", "/change-notetype/save") not in requests
        assert ("POST", "/editor/change-notetype") not in requests
        context.close()
        browser.close()

    after = _read_collection_snapshot(
        fixture["app"], source_note_id, source_model_id, target_model_id
    )
    assert after == before


def test_change_notetype_save_persists_ui_mapping_and_redirects(live_server_cnt):
    fixture = live_server_cnt
    url = fixture["url"]
    source_note_id = fixture["source_note_id"]
    target_model_id = fixture["target_model_id"]
    cids = ",".join(str(cid) for cid in fixture["source_card_ids"])
    requests = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on(
            "request",
            lambda request: requests.append(
                (request.method, urlsplit(request.url).path)
            ),
        )
        page.goto(f"{url}/change-notetype?cids={cids}")
        page.wait_for_selector("#target-notetype-select", timeout=10000)

        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and urlsplit(response.url).path == "/change-notetype/select-target"
            )
        ) as target_response:
            page.locator("#target-notetype-select").select_option(str(target_model_id))
        assert target_response.value.status == 200

        field_map_0 = page.locator('select[data-bind="field_map_0"]')
        if field_map_0.input_value() != "1":
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST"
                    and urlsplit(response.url).path == "/change-notetype/remap-field"
                )
            ) as field_response:
                field_map_0.select_option("1")
            assert field_response.value.status == 200

        field_map_1 = page.locator('select[data-bind="field_map_1"]')
        if field_map_1.input_value() != "0":
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST"
                    and urlsplit(response.url).path == "/change-notetype/remap-field"
                )
            ) as field_response:
                field_map_1.select_option("0")
            assert field_response.value.status == 200
        assert field_map_0.input_value() == "1"
        assert field_map_1.input_value() == "0"

        template_map_0 = page.locator('select[data-bind="template_map_0"]')
        if template_map_0.input_value() != "0":
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST"
                    and urlsplit(response.url).path == "/change-notetype/remap-template"
                )
            ) as template_response:
                template_map_0.select_option("0")
            assert template_response.value.status == 200

        template_map_1 = page.locator('select[data-bind="template_map_1"]')
        if template_map_1.input_value() != "1":
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST"
                    and urlsplit(response.url).path == "/change-notetype/remap-template"
                )
            ) as template_response:
                template_map_1.select_option("1")
            assert template_response.value.status == 200
        assert template_map_0.input_value() == "0"
        assert template_map_1.input_value() == "1"

        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and urlsplit(response.url).path == "/change-notetype/save"
            )
        ) as save_response:
            page.locator("#change-notetype-save-btn").click()
        assert save_response.value.status == 200
        page.wait_for_url(f"{url}/deckbrowser")
        browser.close()

    saved_note, saved_cards, saved_models = _read_collection_snapshot(
        fixture["app"],
        source_note_id,
        fixture["source_model_id"],
        target_model_id,
    )
    assert saved_note[:2] == (source_note_id, target_model_id)
    assert saved_note[2].split("\x1f") == ["second-value", "first-value"]
    assert len(saved_cards) == 2
    assert all(card[1] == source_note_id for card in saved_cards)
    assert {card[2] for card in saved_cards} == {0, 1}
    assert saved_models[target_model_id][1] == _TARGET_FIELDS
    assert (
        tuple(template[0] for template in saved_models[target_model_id][2])
        == _TARGET_TEMPLATES
    )
    assert requests.count(("POST", "/change-notetype/save")) == 1


def test_empty_change_notetype_error_page_can_cancel_to_browse(live_server_cnt):
    url = live_server_cnt["url"]
    requests = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on(
            "request",
            lambda request: requests.append(
                (request.method, urlsplit(request.url).path)
            ),
        )
        response = page.goto(f"{url}/change-notetype")
        assert response is not None and response.status == 400
        cancel = page.locator("#change-notetype-cancel-btn")
        assert cancel.is_visible()
        assert cancel.get_attribute("href") == "/browse"
        cancel.click()
        page.wait_for_url(f"{url}/browse")
        assert ("GET", "/browse") in requests
        assert ("POST", "/change-notetype/save") not in requests
        browser.close()
