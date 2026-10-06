import threading
import time
from pathlib import Path

import pytest
import uvicorn
from anki.collection import Collection

from ankiweb.app import create_app
from ankiweb.core.config import Settings

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright


@pytest.fixture
def live_server_browse(tmp_path: Path):
    col_path = tmp_path / "browse.anki2"
    col = Collection(str(col_path))
    try:
        did = col.decks.id("Default")
        assert did is not None
        for q in ("dogword", "catword"):
            nt = col.models.by_name("Basic")
            assert nt is not None
            n = col.new_note(nt)
            n["Front"] = q
            n["Back"] = q.upper()
            col.add_note(n, did)
    finally:
        col.close()
    settings = Settings(collection_path=col_path, port=8127)
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings), host="127.0.0.1", port=8127, log_level="warning"
        )
    )
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("server did not start")
        time.sleep(0.05)
    yield "http://127.0.0.1:8127"
    server.should_exit = True
    t.join(timeout=5)


def test_browse_search_and_open(live_server_browse):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"{live_server_browse}/browse")
        # initial empty search loads all rows
        page.wait_for_function(
            "document.getElementById('results-body').children.length>=2", timeout=6000
        )
        # narrow the search
        page.fill("#search", "dogword")
        page.keyboard.press("Enter")
        page.wait_for_function(
            "document.getElementById('results-body').children.length===1", timeout=6000
        )
        assert "dogword" in page.inner_text("#results-body")
        # click the row -> D4 embeds the live editor iframe (/edit?nid=) in the detail pane,
        # and the editor mounts + loads the clicked note inside the iframe
        page.click(".browser-row")
        page.wait_for_selector("#detail iframe.editor-frame", timeout=6000)
        page.wait_for_function(
            "() => { const f=document.querySelector('#detail iframe.editor-frame'); "
            "return f && /[/]edit[?]nid=/.test(f.getAttribute('src') || '') && f.contentDocument "
            "&& f.contentDocument.querySelector('#editor-fields-container')!==null; }",
            timeout=8000,
        )
        browser.close()


def test_editor_blur_refresh_preserves_iframe_focus_and_saves_fields(
    live_server_browse,
):
    from urllib.parse import urljoin

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"{live_server_browse}/browse")
        page.wait_for_function(
            "document.getElementById('results-body').children.length>=2", timeout=6000
        )

        row = page.locator(".browser-row").first
        cid = row.get_attribute("data-cid")
        assert cid is not None
        row.click()
        selected_row = page.locator(f'.browser-row[data-cid="{cid}"].selected')
        selected_row.wait_for(state="visible", timeout=6000)

        iframe_selector = "#detail iframe#editor-frame.editor-frame"
        page.locator(iframe_selector).wait_for(state="visible", timeout=6000)
        frame = page.frame_locator(iframe_selector)
        field0 = frame.locator(
            '#editor-field-0 .rich-text-input[data-ankiweb-rich]'
        )
        field1 = frame.locator(
            '#editor-field-1 .rich-text-input[data-ankiweb-rich]'
        )
        field0.wait_for(state="visible", timeout=8000)
        field1.wait_for(state="visible", timeout=8000)

        original_iframe = page.locator(iframe_selector).element_handle()
        assert original_iframe is not None
        original_document = page.evaluate_handle(
            "(iframe) => iframe.contentDocument", original_iframe
        )

        def assert_editor_identity_is_unchanged():
            assert page.evaluate(
                "(original) => original === document.querySelector("
                "'#detail iframe#editor-frame.editor-frame')",
                original_iframe,
            )
            assert page.evaluate(
                "(original) => { const iframe = document.querySelector("
                "'#detail iframe#editor-frame.editor-frame'); "
                "return iframe && iframe.contentDocument === original; }",
                original_document,
            )

        def expect_refresh_on_click(locator):
            with page.expect_response(
                lambda response: response.request.method == "POST"
                and response.url.endswith("/browse/refresh"),
                timeout=10000,
            ) as refresh_info:
                locator.click()
            response = refresh_info.value
            assert response.status == 200
            _ = response.text()

        # An untouched field blur still causes the real browser refresh. The next
        # field must stay focused in the same editor document after that response.
        field0.click()
        expect_refresh_on_click(field1)
        assert_editor_identity_is_unchanged()
        assert selected_row.is_visible()
        assert field1.evaluate("(el) => el.ownerDocument.activeElement === el")

        first_value = "dogword first field saved"
        field0.fill(first_value)
        expect_refresh_on_click(field1)
        page.locator(f'.browser-row[data-cid="{cid}"]').filter(
            has_text=first_value
        ).wait_for(state="visible", timeout=10000)
        assert_editor_identity_is_unchanged()
        assert selected_row.is_visible()
        assert field1.evaluate("(el) => el.ownerDocument.activeElement === el")

        second_value = "second field remains editable"
        field1.fill(second_value)
        expect_refresh_on_click(field0)
        page.locator(f'.browser-row[data-cid="{cid}"]').filter(
            has_text=first_value
        ).wait_for(state="visible", timeout=10000)
        assert_editor_identity_is_unchanged()
        assert selected_row.is_visible()

        editor_src = page.locator(iframe_selector).get_attribute("src")
        assert editor_src is not None
        saved_editor = page.request.get(urljoin(live_server_browse, editor_src))
        assert saved_editor.status == 200
        assert second_value in saved_editor.text()
        browser.close()


def test_select_all_and_suspend(live_server_browse):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"{live_server_browse}/browse")
        page.wait_for_function(
            "document.getElementById('results-body').children.length>=2", timeout=6000
        )
        rows = page.locator(".browser-row")
        rows.nth(0).click()
        rows.nth(1).click(modifiers=["Control"])
        page.wait_for_function(
            "document.querySelectorAll('#results-body tr.selected').length===2",
            timeout=6000,
        )
        page.click("#browser-actions >> text=Suspend")
        page.wait_for_function(
            "document.querySelectorAll('#results-body tr.selected').length===0",
            timeout=6000,
        )
        browser.close()


@pytest.fixture
def live_server_longdeck(tmp_path: Path):
    col_path = tmp_path / "longdeck.anki2"
    col = Collection(str(col_path))
    # A deep, unbreakable path far wider than the 200px sidebar — the case that used to overflow.
    long_name = "prefix_" + "a" * 40 + "::middle_" + "b" * 40 + "::leaf_zzz"
    try:
        did = col.decks.id(long_name)
        assert did is not None
        nt = col.models.by_name("Basic")
        assert nt is not None
        n = col.new_note(nt)
        n["Front"] = "q"
        n["Back"] = "a"
        col.add_note(n, did)
    finally:
        col.close()
    settings = Settings(collection_path=col_path, port=8129)
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings), host="127.0.0.1", port=8129, log_level="warning"
        )
    )
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("server did not start")
        time.sleep(0.05)
    yield "http://127.0.0.1:8129", long_name
    server.should_exit = True
    t.join(timeout=5)


def test_browse_sidebar_long_name_truncated(live_server_longdeck):
    base, long_name = live_server_longdeck
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"{base}/browse")
        page.wait_for_selector("#sidebar .side-item", timeout=6000)
        item = page.locator("#sidebar").get_by_title(long_name, exact=True)
        # the full name is preserved on the hover tooltip even though the visible text is clipped
        assert item.get_attribute("title") == long_name
        geo = item.evaluate(
            "el => { const cs = getComputedStyle(el);"
            " return {scrollW: el.scrollWidth, clientW: el.clientWidth,"
            "  overflowX: cs.overflowX, textOverflow: cs.textOverflow,"
            "  whiteSpace: cs.whiteSpace}; }"
        )
        # genuinely clipped (content far wider than its box) instead of spilling over the results
        assert geo["scrollW"] > geo["clientW"]
        assert geo["overflowX"] == "hidden"
        assert geo["textOverflow"] == "ellipsis"
        assert geo["whiteSpace"] == "nowrap"
        browser.close()
