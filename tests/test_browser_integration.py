import threading
import time
from pathlib import Path

import pytest
import uvicorn
from anki.collection import Collection

from ankiweb.app import create_app
from ankiweb.core.config import Settings

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import ViewportSize, sync_playwright


def _observe_browser_refreshes(page):
    page.add_init_script(
        """
        if (window.parent === window) {
          window.__browserRefreshEvents = 0;
          window.addEventListener("ankiweb:browser-refresh", () => {
            window.__browserRefreshEvents += 1;
          });
        }
        """
    )


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
        websocket_urls = []
        page.on("websocket", lambda websocket: websocket_urls.append(websocket.url))
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
        assert websocket_urls == []
        browser.close()


def test_editor_blur_refresh_preserves_iframe_focus_and_saves_fields(
    live_server_browse,
):
    from urllib.parse import urljoin

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        websocket_urls = []
        page.on("websocket", lambda websocket: websocket_urls.append(websocket.url))
        browser_refresh_requests = []

        def record_browser_refresh_request(request):
            if request.method == "POST" and request.url.endswith("/browse/refresh"):
                browser_refresh_requests.append(request)

        page.on("request", record_browser_refresh_request)
        _observe_browser_refreshes(page)
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
        field0 = frame.locator("#editor-field-0 .rich-text-input[data-ankiweb-rich]")
        field1 = frame.locator("#editor-field-1 .rich-text-input[data-ankiweb-rich]")
        field0.wait_for(state="visible", timeout=8000)
        field1.wait_for(state="visible", timeout=8000)

        refresh_events_before_unrelated_messages = page.evaluate(
            "window.__browserRefreshEvents"
        )
        page.evaluate(
            """() => {
              const editor = document.querySelector('#detail iframe#editor-frame');
              const saved = {type: 'ankiweb:editor-saved'};
              window.dispatchEvent(new MessageEvent('message', {
                data: saved, origin: location.origin, source: window
              }));
              window.dispatchEvent(new MessageEvent('message', {
                data: saved, origin: 'https://unrelated.invalid', source: editor.contentWindow
              }));
              window.dispatchEvent(new MessageEvent('message', {
                data: {type: 'unrelated'}, origin: location.origin, source: editor.contentWindow
              }));
            }"""
        )
        assert (
            page.evaluate("window.__browserRefreshEvents")
            == refresh_events_before_unrelated_messages
        )

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
                lambda response: (
                    response.request.method == "POST"
                    and response.url.endswith("/browse/refresh")
                ),
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
        tag_add_button = frame.locator(".tag-add-button")
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and response.url.endswith("/editor/blur-field")
            ),
            timeout=10000,
        ) as tag_button_blur:
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST"
                    and response.url.endswith("/browse/refresh")
                ),
                timeout=10000,
            ) as tag_button_refresh:
                tag_add_button.click()
        assert tag_button_blur.value.status == 200
        assert tag_button_refresh.value.status == 200

        tag_input = frame.locator(".tag-input")
        tag_input.fill("same-tab-editor-tag")
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and response.url.endswith("/editor/save-tags")
            ),
            timeout=10000,
        ) as tag_save_info:
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST"
                    and response.url.endswith("/browse/refresh")
                ),
                timeout=10000,
            ) as tag_refresh_info:
                tag_input.press("Enter")
        assert tag_save_info.value.status == 200
        assert tag_refresh_info.value.status == 200
        page.wait_for_function(
            "(cid) => { const cell = document.querySelector('#browser-row-' + cid + ' .cell-tags'); "
            "return cell && cell.textContent.includes('same-tab-editor-tag'); }",
            arg=cid,
            timeout=10000,
        )
        saved_editor = page.request.get(urljoin(live_server_browse, editor_src))
        assert "same-tab-editor-tag" in saved_editor.text()

        refresh_requests_before_failed_tag = len(browser_refresh_requests)
        page.route(
            "**/editor/save-tags",
            lambda route: route.fulfill(status=500, body="tag save failed"),
        )
        tag_add_button.click()
        failed_tag_input = frame.locator(".tag-input")
        failed_tag_input.fill("failed-editor-tag")
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and response.url.endswith("/editor/save-tags")
            ),
            timeout=10000,
        ) as failed_tag_save:
            failed_tag_input.press("Enter")
        assert failed_tag_save.value.status == 500
        failed_tag_save.value.finished()
        frame.locator(".tag-chip .tag-label", has_text="failed-editor-tag").wait_for(
            state="visible", timeout=6000
        )
        assert selected_row.is_visible()
        assert_editor_identity_is_unchanged()
        tag_cell_text = selected_row.locator(".cell-tags").text_content()
        assert tag_cell_text is not None
        assert "same-tab-editor-tag" in tag_cell_text
        assert "failed-editor-tag" not in tag_cell_text
        assert len(browser_refresh_requests) == refresh_requests_before_failed_tag
        assert websocket_urls == []
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
        page.locator("#btn-actions-learning").click()
        page.locator("#btn-suspend").click()
        page.wait_for_function(
            "document.querySelectorAll('#results-body tr.selected').length===0",
            timeout=6000,
        )
        browser.close()


def test_due_dialog_validation_preserves_selection_and_retries(live_server_browse):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1101, "height": 803})
        page.goto(f"{live_server_browse}/browse")
        page.wait_for_function(
            "document.querySelectorAll('#results-body tr.browser-row').length === 2",
            timeout=6000,
        )

        row = page.locator("#results-body tr[data-cid]").first
        cid = row.get_attribute("data-cid")
        assert cid is not None
        original_due = row.locator(".cell-due").inner_text().strip()
        row.click()
        page.wait_for_function(
            "document.querySelectorAll('#results-body tr[aria-selected=\"true\"]').length === 1",
            timeout=6000,
        )

        page.locator("#btn-actions-learning").click()
        page.locator("#btn-setdue").click()
        dialog = page.locator("#dialog-setdue")
        dialog.wait_for(state="visible", timeout=6000)
        due_input = dialog.locator("#input-setdue")
        due_input.fill("not-a-valid-due")
        dialog.locator('form button[type="submit"]').click()

        alert = dialog.get_by_role("alert")
        alert.wait_for(state="visible", timeout=6000)
        assert alert.is_visible()
        assert alert.inner_text().strip()
        assert dialog.is_visible()
        assert dialog.get_attribute("open") is not None
        assert due_input.input_value() == "not-a-valid-due"
        selected_row = page.locator(f"#browser-row-{cid}")
        assert selected_row.get_attribute("aria-selected") == "true"
        assert selected_row.locator('input[type="checkbox"]').is_checked()
        assert dialog.locator('input[name="selectedCids"]').input_value() == cid

        due_input.fill("3")
        dialog.locator('form button[type="submit"]').click()
        dialog.wait_for(state="hidden", timeout=6000)
        page.wait_for_function(
            "document.querySelectorAll('#results-body tr[aria-selected=\"true\"]').length === 0",
            timeout=6000,
        )
        page.wait_for_function(
            "(args) => { const row = document.getElementById('browser-row-' + args.cid); "
            "return row && row.querySelector('.cell-due')?.textContent.trim() !== args.due; }",
            arg={"cid": cid, "due": original_due},
            timeout=6000,
        )
        changed_due = page.locator(f"#browser-row-{cid} .cell-due").inner_text().strip()
        assert changed_due != original_due
        browser.close()


def test_change_deck_dialog_cancels_without_saving(live_server_browse):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1101, "height": 803})
        page.goto(f"{live_server_browse}/browse")
        page.wait_for_function(
            "document.querySelectorAll('#results-body tr[data-cid]').length === 2",
            timeout=6000,
        )

        rows = page.locator("#results-body tr[data-cid]")
        initial_cids = [
            rows.nth(index).get_attribute("data-cid") for index in range(rows.count())
        ]
        assert all(initial_cids)
        row = rows.first
        cid = row.get_attribute("data-cid")
        assert cid is not None
        row.click()
        page.wait_for_function(
            "document.querySelectorAll('#results-body tr[aria-selected=\"true\"]').length === 1",
            timeout=6000,
        )

        draft_deck = "Unsaved Cancel Deck"
        page.locator("#btn-actions-organize").click()
        page.locator("#btn-changedeck").click()
        dialog = page.locator("#dialog-changedeck")
        dialog.wait_for(state="visible", timeout=6000)
        deck_input = dialog.locator("#input-changedeck")
        deck_input.fill(draft_deck)
        page.keyboard.press("Escape")
        dialog.wait_for(state="hidden", timeout=6000)
        assert row.get_attribute("aria-selected") == "true"
        assert (
            page.locator('#browser-state input[name="selectedCids"]').input_value()
            == cid
        )

        page.locator("#btn-actions-organize").click()
        page.locator("#btn-changedeck").click()
        dialog.wait_for(state="visible", timeout=6000)
        deck_input = dialog.locator("#input-changedeck")
        assert deck_input.input_value() == ""
        dialog.locator('form button[type="button"]').click()
        dialog.wait_for(state="hidden", timeout=6000)
        assert row.get_attribute("aria-selected") == "true"
        assert (
            page.locator('#browser-state input[name="selectedCids"]').input_value()
            == cid
        )

        page.goto(f"{live_server_browse}/browse")
        page.wait_for_function(
            "document.querySelectorAll('#results-body tr[data-cid]').length === 2",
            timeout=6000,
        )
        refreshed_rows = page.locator("#results-body tr[data-cid]")
        refreshed_cids = [
            refreshed_rows.nth(index).get_attribute("data-cid")
            for index in range(refreshed_rows.count())
        ]
        assert refreshed_cids == initial_cids
        assert page.get_by_role("link", name=draft_deck, exact=True).count() == 0
        browser.close()


def test_selection_request_finishes_before_pending_browser_refresh(live_server_browse):
    from urllib.parse import parse_qs

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1101, "height": 803})
        page_errors = []
        page.on("pageerror", lambda err: page_errors.append(str(err)))
        page.goto(f"{live_server_browse}/browse")
        page.wait_for_function(
            "document.querySelectorAll('#results-body tr.browser-row').length === 2",
            timeout=6000,
        )

        row = page.locator("#results-body tr[data-cid]").first
        cid = row.get_attribute("data-cid")
        assert cid is not None
        front = row.locator(".cell-sortfield").inner_text().strip()
        paused_select = []

        def hold_select(route):
            paused_select.append(route)

        page.route("**/browse/select*", hold_select)
        with page.expect_request(
            lambda request: (
                request.method == "POST"
                and request.url.split("?", 1)[0].endswith("/browse/select")
            ),
            timeout=6000,
        ):
            row.click()

        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and response.url.split("?", 1)[0].endswith("/browse/refresh")
            ),
            timeout=6000,
        ) as refresh_info:
            with page.expect_request(
                lambda request: (
                    request.method == "POST"
                    and request.url.split("?", 1)[0].endswith("/browse/refresh")
                ),
                timeout=6000,
            ) as refresh_request_info:
                page.evaluate(
                    "window.dispatchEvent(new Event('ankiweb:browser-refresh'))"
                )
                assert paused_select
                paused_select[0].continue_()

        refresh_fields = parse_qs(refresh_request_info.value.post_data or "")
        assert refresh_fields.get("selectedCids") == [cid]
        assert refresh_fields.get("selectionAnchor") == [cid]
        refresh_response = refresh_info.value
        assert refresh_response.status == 200
        refresh_response.finished()

        page.wait_for_function(
            "(cid) => {"
            " const row = document.getElementById('browser-row-' + cid);"
            " const selected = document.querySelectorAll("
            "'#browser-state input[name=\"selectedCids\"]');"
            " const anchor = document.querySelector("
            "'#browser-state input[name=\"selectionAnchor\"]');"
            " const cardInfo = document.getElementById('btn-cardinfo');"
            " return row?.getAttribute('aria-selected') === 'true' &&"
            " row.querySelector('input[type=\"checkbox\"]')?.checked &&"
            " selected.length === 1 && selected[0].value === cid &&"
            " anchor?.value === cid && "
            "cardInfo?.getAttribute('href') === '/card-info/' + cid;"
            "}",
            arg=cid,
            timeout=6000,
        )
        page.wait_for_function(
            "(front) => { const frame = document.querySelector('#detail iframe.editor-frame'); "
            "const field = frame?.contentDocument?.querySelector('[data-ankiweb-rich]'); "
            "return field?.textContent.includes(front); }",
            arg=front,
            timeout=8000,
        )
        assert not page_errors, f"Unexpected page errors: {page_errors}"
        browser.close()


def test_browser_row_and_checkbox_selection_regression(live_server_browse):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1101, "height": 803})
        page_errors = []
        page.on("pageerror", lambda err: page_errors.append(str(err)))

        page.goto(f"{live_server_browse}/browse")
        page.wait_for_function(
            "document.getElementById('results-body').children.length >= 2",
            timeout=6000,
        )
        assert not page_errors, f"Unexpected page startup errors: {page_errors}"

        rows = page.locator("#results-body tr.browser-row")
        header_chk = page.locator("#select-all-cards")
        second_row = rows.nth(1)
        first_row = rows.nth(0)

        # 1. Plain click on second row: exactly 1 row selected and 1 row checkbox checked
        second_row.click()
        page.wait_for_function(
            "() => document.querySelectorAll('#results-body tr.browser-row.selected').length === 1",
            timeout=6000,
        )
        assert "selected" in (second_row.get_attribute("class") or "")
        assert second_row.locator("input[type='checkbox']").is_checked()
        assert not first_row.locator("input[type='checkbox']").is_checked()
        assert "selected" not in (first_row.get_attribute("class") or "")

        # Action buttons are enabled for single selection
        assert not page.locator("#btn-suspend").is_disabled()
        assert page.locator("#btn-cardinfo").get_attribute("aria-disabled") == "false"

        # Embedded editor mounts and displays the second row note ('catword')
        page.wait_for_selector("#detail iframe.editor-frame", timeout=6000)
        page.wait_for_function(
            "() => { const f = document.querySelector('#detail iframe.editor-frame'); "
            "return f && f.contentDocument && f.contentDocument.querySelector('[data-ankiweb-rich]') "
            "&& f.contentDocument.querySelector('[data-ankiweb-rich]').textContent.includes('catword'); }",
            timeout=8000,
        )

        # 2. Checkbox multi-select: toggle first row checkbox additively
        first_row.locator("input[type='checkbox']").click()
        page.wait_for_function(
            "() => document.querySelectorAll('#results-body tr.browser-row.selected').length === 2",
            timeout=6000,
        )
        assert first_row.locator("input[type='checkbox']").is_checked()
        assert second_row.locator("input[type='checkbox']").is_checked()
        # With 2 rows total, 2 selected means header is checked
        assert header_chk.is_checked()

        # Remove second row via checkbox: 1 remains selected, header becomes indeterminate
        second_row.locator("input[type='checkbox']").click()
        page.wait_for_function(
            "() => document.querySelectorAll('#results-body tr.browser-row.selected').length === 1",
            timeout=6000,
        )
        assert not second_row.locator("input[type='checkbox']").is_checked()
        assert first_row.locator("input[type='checkbox']").is_checked()
        assert header_chk.evaluate("el => el.indeterminate === true")
        assert not header_chk.is_checked()

        # 3. Select-all checks all rendered row checkboxes
        header_chk.click()
        page.wait_for_function(
            "() => document.querySelectorAll('#results-body tr.browser-row.selected').length === 2",
            timeout=6000,
        )
        page.wait_for_function(
            "() => { const boxes = document.querySelectorAll('#results-body tr.browser-row input[type=\"checkbox\"]'); "
            "return boxes.length === 2 && Array.from(boxes).every(b => b.checked); }",
            timeout=6000,
        )
        assert header_chk.is_checked()
        assert not header_chk.evaluate("el => el.indeterminate === true")

        # 4. Selecting none clears all row checkboxes and disables actions
        header_chk.click()
        page.wait_for_function(
            "() => document.querySelectorAll('#results-body tr.browser-row.selected').length === 0",
            timeout=6000,
        )
        page.wait_for_function(
            "() => { const boxes = document.querySelectorAll('#results-body tr.browser-row input[type=\"checkbox\"]'); "
            "return boxes.length === 2 && Array.from(boxes).every(b => !b.checked); }",
            timeout=6000,
        )
        assert not header_chk.is_checked()
        assert not header_chk.evaluate("el => el.indeterminate === true")
        assert page.locator("#btn-suspend").is_disabled()
        cardinfo = page.locator("#btn-cardinfo")
        assert cardinfo.get_attribute("aria-disabled") == "true"
        assert cardinfo.get_attribute("tabindex") == "-1"
        assert cardinfo.get_attribute("href") is None

        assert not page_errors, f"Page errors encountered: {page_errors}"
        browser.close()


def test_categorized_browser_actions_menu_states_and_links(live_server_browse):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1101, "height": 803})
        page_errors = []
        page.on("pageerror", lambda err: page_errors.append(str(err)))

        # Intercept any mutation or action navigation requests
        action_requests = []
        page.on(
            "request",
            lambda req: (
                action_requests.append(req.url)
                if any(
                    x in req.url
                    for x in (
                        "/browse/suspend",
                        "/browse/unsuspend",
                        "/browse/forget",
                        "/browse/setdue",
                        "/browse/changedeck",
                        "/browse/addtag",
                        "/browse/removetag",
                        "/browse/delete",
                        "/card-info",
                        "/change-notetype",
                    )
                )
                else None
            ),
        )

        page.goto(f"{live_server_browse}/browse")
        page.wait_for_function(
            "document.getElementById('results-body').children.length >= 2",
            timeout=6000,
        )
        assert not page_errors, f"Unexpected page startup errors: {page_errors}"

        # 1. Zero selection: All three menus can open; entries are visible and disabled
        learning_menu = page.locator("#browser-actions-learning")
        organize_menu = page.locator("#browser-actions-organize")
        cards_menu = page.locator("#browser-actions-cards")

        # Open Learning menu, assert mutual exclusion (others closed)
        page.locator("#btn-actions-learning").click()
        assert learning_menu.get_attribute("open") is not None
        assert organize_menu.get_attribute("open") is None
        assert cards_menu.get_attribute("open") is None
        for btn_id in ("#btn-suspend", "#btn-unsuspend", "#btn-forget", "#btn-setdue"):
            btn = page.locator(btn_id)
            assert btn.is_visible()
            assert btn.is_disabled()

        # Attempting to click disabled button must not emit network request
        initial_req_count = len(action_requests)
        page.locator("#btn-suspend").click(force=True)
        assert len(action_requests) == initial_req_count

        # Open Organize menu, assert Learning closed
        page.locator("#btn-actions-organize").click()
        assert organize_menu.get_attribute("open") is not None
        assert learning_menu.get_attribute("open") is None
        assert cards_menu.get_attribute("open") is None
        for btn_id in ("#btn-changedeck", "#btn-addtag", "#btn-removetag"):
            btn = page.locator(btn_id)
            assert btn.is_visible()
            assert btn.is_disabled()

        # Open Cards menu, assert Organize closed
        page.locator("#btn-actions-cards").click()
        assert cards_menu.get_attribute("open") is not None
        assert organize_menu.get_attribute("open") is None
        assert learning_menu.get_attribute("open") is None
        btn_delete = page.locator("#btn-delete")
        assert btn_delete.is_visible()
        assert btn_delete.is_disabled()

        link_cardinfo = page.locator("#btn-cardinfo")
        link_changenotetype = page.locator("#btn-changenotetype")

        assert link_cardinfo.is_visible()
        assert link_cardinfo.get_attribute("aria-disabled") == "true"
        assert link_cardinfo.get_attribute("tabindex") == "-1"
        assert link_cardinfo.get_attribute("href") in (None, "#", "")

        assert link_changenotetype.is_visible()
        assert link_changenotetype.get_attribute("aria-disabled") == "true"
        assert link_changenotetype.get_attribute("tabindex") == "-1"
        assert link_changenotetype.get_attribute("href") in (None, "#", "")

        # Attempting click or keyboard navigation on disabled links does not trigger navigation
        initial_url = page.url
        # Evaluate native click to trigger actual onclick guard event
        link_cardinfo.evaluate("(el) => el.click()")
        link_changenotetype.evaluate("(el) => el.click()")
        assert page.url == initial_url
        assert len(action_requests) == initial_req_count

        # Verify keyboard activation fails while menu is open and link is focused
        if cards_menu.get_attribute("open") is None:
            page.locator("#btn-actions-cards").click()
        link_cardinfo.focus()
        page.keyboard.press("Enter")
        assert page.url == initial_url
        assert len(action_requests) == initial_req_count

        # 2. Single selection: row selected, editor mounted, appropriate actions enabled
        rows = page.locator("#results-body tr.browser-row")
        first_row = rows.nth(0)
        first_cid = first_row.get_attribute("data-cid")
        assert first_cid is not None

        first_row.click()
        page.wait_for_function(
            "() => document.querySelectorAll('#results-body tr.browser-row.selected').length === 1",
            timeout=6000,
        )

        # Editor mounts for the selected row
        page.wait_for_selector("#detail iframe.editor-frame", timeout=6000)

        # All actions enabled for single selection
        assert not page.locator("#btn-suspend").is_disabled()
        assert not page.locator("#btn-changedeck").is_disabled()
        assert not page.locator("#btn-delete").is_disabled()

        # Ensure Cards menu is open to inspect enabled links
        page.locator("#btn-actions-cards").click()
        assert cards_menu.get_attribute("open") is not None
        assert link_cardinfo.get_attribute("aria-disabled") == "false"
        assert link_cardinfo.get_attribute("tabindex") == "0"
        assert link_cardinfo.get_attribute("href") == f"/card-info/{first_cid}"

        assert link_changenotetype.get_attribute("aria-disabled") == "false"
        assert link_changenotetype.get_attribute("tabindex") == "0"
        assert (
            link_changenotetype.get_attribute("href")
            == f"/change-notetype?cids={first_cid}"
        )

        # 3. Multi-selection: Card Info disabled & safe from keyboard, Change Note Type enabled
        second_row = rows.nth(1)
        second_cid = second_row.get_attribute("data-cid")
        assert second_cid is not None
        second_row.locator("input[type='checkbox']").click()
        page.wait_for_function(
            "() => document.querySelectorAll('#results-body tr.browser-row.selected').length === 2",
            timeout=6000,
        )

        assert not page.locator("#btn-suspend").is_disabled()
        assert not page.locator("#btn-delete").is_disabled()

        # Card Info disabled for multi-select
        assert link_cardinfo.get_attribute("aria-disabled") == "true"
        assert link_cardinfo.get_attribute("tabindex") == "-1"
        assert link_cardinfo.get_attribute("href") in (None, "#", "")

        # Change Note Type enabled with multiple cids
        assert link_changenotetype.get_attribute("aria-disabled") == "false"
        assert link_changenotetype.get_attribute("tabindex") == "0"
        href_cnt = link_changenotetype.get_attribute("href")
        assert href_cnt is not None
        assert first_cid in href_cnt and second_cid in href_cnt

        # Ensure Cards menu is open to test multi-select disabled link keyboard/click
        page.locator("#btn-actions-cards").click()
        assert cards_menu.get_attribute("open") is not None
        link_cardinfo.focus()
        page.keyboard.press("Enter")
        link_cardinfo.evaluate("(el) => el.click()")
        assert page.url == initial_url
        assert len(action_requests) == initial_req_count

        # 4. Bulk action execution via category menu & genuine pending-request busy state
        # Intercept /browse/suspend so we can freeze it in flight and verify $_busy disables all actions
        paused_route = []

        def handle_suspend_route(route):
            paused_route.append(route)

        page.route("**/browse/suspend", handle_suspend_route)

        page.locator("#btn-actions-learning").click()
        page.wait_for_selector("#btn-suspend", state="visible")
        page.locator("#btn-suspend").click()

        # Wait until the POST request is in flight
        page.wait_for_function("() => true")
        for _ in range(50):
            if paused_route:
                break
            page.wait_for_timeout(50)
        assert len(paused_route) == 1, "Expected pending /browse/suspend route"

        # While request is in flight, all action controls must be disabled due to $_busy
        page.wait_for_function(
            "() => document.querySelector('#btn-suspend')?.disabled === true",
            timeout=6000,
        )
        assert page.locator("#btn-suspend").is_disabled()
        assert page.locator("#btn-changedeck").is_disabled()
        assert page.locator("#btn-delete").is_disabled()
        assert page.locator("#btn-cardinfo").get_attribute("aria-disabled") == "true"
        assert (
            page.locator("#btn-changenotetype").get_attribute("aria-disabled") == "true"
        )

        # Release route and unroute handler
        paused_route[0].continue_()
        page.unroute("**/browse/suspend")

        # After response completes, selection resets to 0 and actions remain disabled
        page.wait_for_function(
            "() => document.querySelectorAll('#results-body tr.browser-row.selected').length === 0",
            timeout=6000,
        )
        assert page.locator("#btn-suspend").is_disabled()
        assert link_cardinfo.get_attribute("aria-disabled") == "true"
        assert link_cardinfo.get_attribute("href") in (None, "#", "")

        assert not page_errors, f"Page errors encountered: {page_errors}"
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


@pytest.fixture
def live_server_sidebar_search(tmp_path: Path):
    col_path = tmp_path / "sidebar_search.anki2"
    col = Collection(str(col_path))
    special_deck = 'Quoted "deck" + & # Ω'
    special_tag = 'quote"+&#Ω*'
    decoy_tag = 'quote"+&#Ω-decoy'
    try:
        did_default = col.decks.id("Default")
        assert did_default is not None
        did_special = col.decks.id(special_deck)
        assert did_special is not None

        nt = col.models.by_name("Basic")
        assert nt is not None

        # Note in special deck
        n1 = col.new_note(nt)
        n1["Front"] = "special deck front"
        n1["Back"] = "special deck back"
        col.add_note(n1, did_special)

        # Note with literal wildcard tag
        n2 = col.new_note(nt)
        n2["Front"] = "special tag front"
        n2["Back"] = "special tag back"
        col.add_note(n2, did_default)
        col.tags.bulk_add([n2.id], special_tag)

        # Decoy note that would match if '*' were a wildcard
        n3 = col.new_note(nt)
        n3["Front"] = "decoy tag front"
        n3["Back"] = "decoy tag back"
        col.add_note(n3, did_default)
        col.tags.bulk_add([n3.id], decoy_tag)
    finally:
        col.close()

    settings = Settings(collection_path=col_path, port=8138)
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings), host="127.0.0.1", port=8138, log_level="warning"
        )
    )
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("server did not start")
        time.sleep(0.05)
    yield "http://127.0.0.1:8138", special_deck, special_tag
    server.should_exit = True
    t.join(timeout=5)


def test_browse_sidebar_native_navigation_history_and_new_tabs(
    live_server_sidebar_search,
):
    from urllib.parse import parse_qs, urlparse

    base, special_deck, special_tag = live_server_sidebar_search
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        page = context.new_page()
        page.goto(f"{base}/browse")

        page.wait_for_function(
            "document.getElementById('results-body').children.length===3", timeout=6000
        )
        page.wait_for_selector("#sidebar .side-item", timeout=6000)

        deck_item = page.get_by_role("link", name=special_deck, exact=True)
        tag_item = page.get_by_role("link", name=special_tag, exact=True)
        deck_href = deck_item.get_attribute("href")
        tag_href = tag_item.get_attribute("href")
        expected_deck_query = parse_qs(urlparse(deck_href or "").query).get("q", [""])[
            0
        ]
        expected_tag_query = parse_qs(urlparse(tag_href or "").query).get("q", [""])[0]
        assert expected_deck_query
        assert expected_tag_query

        # Preserve the original tab's draft, results, and URL during modified/middle clicks.
        page.fill("#search", "original page draft")
        original_url = page.url
        original_results = page.inner_text("#results-body")
        assert page.eval_on_selector("#results-body", "el => el.children.length") == 3
        assert "special deck front" in original_results
        assert "special tag front" in original_results
        assert "decoy tag front" in original_results

        with context.expect_page() as new_page_info:
            tag_item.click(modifiers=["ControlOrMeta"])
        new_page = new_page_info.value
        new_page.wait_for_function(
            "(query) => new URL(location.href).searchParams.get('q') === query",
            arg=expected_tag_query,
            timeout=6000,
        )
        new_page.wait_for_function(
            "document.getElementById('results-body').children.length===1", timeout=6000
        )
        parsed_new_url = urlparse(new_page.url)
        assert parsed_new_url.path == "/browse"
        assert parse_qs(parsed_new_url.query).get("q") == [expected_tag_query]
        assert new_page.input_value("#search") == expected_tag_query
        new_results = new_page.inner_text("#results-body")
        assert (
            new_page.eval_on_selector("#results-body", "el => el.children.length") == 1
        )
        assert "special tag front" in new_results
        assert "special deck front" not in new_results
        assert "decoy tag front" not in new_results

        assert page.input_value("#search") == "original page draft"
        assert page.url == original_url
        assert page.inner_text("#results-body") == original_results
        new_page.close()

        with context.expect_page() as middle_page_info:
            deck_item.click(button="middle")
        middle_page = middle_page_info.value
        middle_page.wait_for_function(
            "(query) => new URL(location.href).searchParams.get('q') === query",
            arg=expected_deck_query,
            timeout=6000,
        )
        middle_page.wait_for_function(
            "document.getElementById('results-body').children.length===1", timeout=6000
        )
        parsed_middle_url = urlparse(middle_page.url)
        assert parsed_middle_url.path == "/browse"
        assert parse_qs(parsed_middle_url.query).get("q") == [expected_deck_query]
        assert middle_page.input_value("#search") == expected_deck_query
        middle_results = middle_page.inner_text("#results-body")
        assert (
            middle_page.eval_on_selector("#results-body", "el => el.children.length")
            == 1
        )
        assert "special deck front" in middle_results
        assert "special tag front" not in middle_results
        assert "decoy tag front" not in middle_results

        assert page.input_value("#search") == "original page draft"
        assert page.url == original_url
        assert page.inner_text("#results-body") == original_results
        middle_page.close()

        # A primary click performs a GET, changing the address bar and loading deck results.
        deck_item.click()
        page.wait_for_function(
            "(query) => new URL(location.href).searchParams.get('q') === query",
            arg=expected_deck_query,
            timeout=6000,
        )
        page.wait_for_function(
            "document.getElementById('results-body')?.textContent.includes('special deck front')",
            timeout=6000,
        )
        parsed_deck_url = urlparse(page.url)
        assert parsed_deck_url.path == "/browse"
        assert parse_qs(parsed_deck_url.query).get("q") == [expected_deck_query]
        assert page.input_value("#search") == expected_deck_query
        deck_results = page.inner_text("#results-body")
        assert page.eval_on_selector("#results-body", "el => el.children.length") == 1
        assert "special deck front" in deck_results
        assert "special tag front" not in deck_results
        assert "decoy tag front" not in deck_results

        # Normal tag navigation keeps the literal '*' semantics and excludes the decoy.
        page.get_by_role("link", name=special_tag, exact=True).click()
        page.wait_for_function(
            "(query) => new URL(location.href).searchParams.get('q') === query",
            arg=expected_tag_query,
            timeout=6000,
        )
        page.wait_for_function(
            "document.getElementById('results-body')?.textContent.includes('special tag front')",
            timeout=6000,
        )
        parsed_tag_url = urlparse(page.url)
        assert parsed_tag_url.path == "/browse"
        assert parse_qs(parsed_tag_url.query).get("q") == [expected_tag_query]
        assert page.input_value("#search") == expected_tag_query
        tag_results = page.inner_text("#results-body")
        assert page.eval_on_selector("#results-body", "el => el.children.length") == 1
        assert "special tag front" in tag_results
        assert "special deck front" not in tag_results
        assert "decoy tag front" not in tag_results

        page.go_back()
        page.wait_for_function(
            "(query) => new URL(location.href).searchParams.get('q') === query",
            arg=expected_deck_query,
            timeout=6000,
        )
        page.wait_for_function(
            "document.getElementById('results-body')?.textContent.includes('special deck front')",
            timeout=6000,
        )
        assert parse_qs(urlparse(page.url).query).get("q") == [expected_deck_query]
        assert page.input_value("#search") == expected_deck_query
        back_results = page.inner_text("#results-body")
        assert page.eval_on_selector("#results-body", "el => el.children.length") == 1
        assert "special deck front" in back_results
        assert "special tag front" not in back_results
        assert "decoy tag front" not in back_results

        page.go_forward()
        page.wait_for_function(
            "(query) => new URL(location.href).searchParams.get('q') === query",
            arg=expected_tag_query,
            timeout=6000,
        )
        page.wait_for_function(
            "document.getElementById('results-body')?.textContent.includes('special tag front')",
            timeout=6000,
        )
        assert parse_qs(urlparse(page.url).query).get("q") == [expected_tag_query]
        assert page.input_value("#search") == expected_tag_query
        forward_results = page.inner_text("#results-body")
        assert page.eval_on_selector("#results-body", "el => el.children.length") == 1
        assert "special tag front" in forward_results
        assert "special deck front" not in forward_results
        assert "decoy tag front" not in forward_results

        browser.close()


def test_browse_sidebar_sections_fold_independently_and_filter(
    live_server_sidebar_search,
):
    from urllib.parse import parse_qs, urlparse

    base, special_deck, special_tag = live_server_sidebar_search
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1101, "height": 803})
        page.goto(f"{base}/browse")
        page.wait_for_function(
            "document.getElementById('results-body').children.length===3", timeout=6000
        )

        decks = page.locator("#sidebar-decks-section")
        tags = page.locator("#sidebar-tags-section")
        deck_link = page.get_by_role("link", name=special_deck, exact=True)
        tag_link = page.get_by_role("link", name=special_tag, exact=True)
        assert decks.get_attribute("open") is not None
        assert tags.get_attribute("open") is not None
        assert deck_link.is_visible() and tag_link.is_visible()

        decks.locator("summary").click()
        assert decks.get_attribute("open") is None
        assert tags.get_attribute("open") is not None
        assert not deck_link.is_visible() and tag_link.is_visible()
        tag_href = tag_link.get_attribute("href")
        assert tag_href is not None
        tag_query = parse_qs(urlparse(tag_href).query)["q"][0]
        tag_link.click()
        page.wait_for_function(
            "(q) => new URL(location.href).searchParams.get('q') === q",
            arg=tag_query,
            timeout=6000,
        )
        page.wait_for_function(
            "(text) => document.getElementById('results-body')?.textContent.includes(text)",
            arg="special tag front",
            timeout=6000,
        )
        assert page.locator("#results-body tr.browser-row").count() == 1

        deck_summary = decks.locator("summary")
        if decks.get_attribute("open") is None:
            deck_summary.press("Enter")
        assert decks.get_attribute("open") is not None
        deck_summary.press("Enter")
        assert decks.get_attribute("open") is None
        if tags.get_attribute("open") is None:
            tags.locator("summary").press("Enter")
        assert tags.get_attribute("open") is not None
        deck_summary.press("Enter")
        assert decks.get_attribute("open") is not None
        tags.locator("summary").click()
        assert decks.get_attribute("open") is not None
        assert tags.get_attribute("open") is None
        assert deck_link.is_visible() and not tag_link.is_visible()
        tags.locator("summary").press("Enter")
        assert tags.get_attribute("open") is not None

        deck_href = deck_link.get_attribute("href")
        assert deck_href is not None
        deck_query = parse_qs(urlparse(deck_href).query)["q"][0]
        deck_link.click()
        page.wait_for_function(
            "(q) => new URL(location.href).searchParams.get('q') === q",
            arg=deck_query,
            timeout=6000,
        )
        page.wait_for_function(
            "(text) => document.getElementById('results-body')?.textContent.includes(text)",
            arg="special deck front",
            timeout=6000,
        )
        assert page.locator("#results-body tr.browser-row").count() == 1

        browser.close()


def test_browse_mobile_sidebar_folding_keeps_dialog_open(live_server_sidebar_search):
    from urllib.parse import parse_qs, urlparse

    base, special_deck, _ = live_server_sidebar_search
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True
        )
        page = context.new_page()
        page.goto(f"{base}/browse")
        page.wait_for_function(
            "document.getElementById('results-body').children.length===3", timeout=6000
        )

        dialog = page.locator("#sidebar-offcanvas")
        label = page.locator("#sidebar-offcanvas-label").text_content()
        assert label
        page.get_by_role("button", name=label.strip(), exact=True).tap()
        page.wait_for_function(
            "document.getElementById('sidebar-offcanvas')?.open === true", timeout=6000
        )

        decks = page.locator("#sidebar-decks-section")
        tags = page.locator("#sidebar-tags-section")
        assert decks.get_attribute("open") is not None
        assert tags.get_attribute("open") is not None
        decks.locator("summary").tap()
        assert decks.get_attribute("open") is None
        assert tags.get_attribute("open") is not None
        assert dialog.get_attribute("open") is not None

        decks.locator("summary").tap()
        deck_link = page.get_by_role("link", name=special_deck, exact=True)
        href = deck_link.get_attribute("href")
        assert href is not None
        query = parse_qs(urlparse(href).query)["q"][0]
        deck_link.tap()
        page.wait_for_function(
            "(q) => new URL(location.href).searchParams.get('q') === q",
            arg=query,
            timeout=6000,
        )
        page.wait_for_function(
            "(text) => document.getElementById('results-body')?.textContent.includes(text)",
            arg="special deck front",
            timeout=6000,
        )
        page.wait_for_function(
            "document.getElementById('sidebar-offcanvas')?.open === false", timeout=6000
        )
        dialog.wait_for(state="hidden", timeout=6000)

        browser.close()


def test_browse_mobile_touch_checkbox_selection_and_remorphed_row(live_server_browse):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True
        )
        page = context.new_page()
        page.goto(f"{live_server_browse}/browse")
        page.wait_for_function(
            "document.getElementById('results-body').children.length===2", timeout=6000
        )

        rows = page.locator("#results-body tr.browser-row")
        first_box = rows.nth(0).locator("input[type='checkbox']")
        second_box = rows.nth(1).locator("input[type='checkbox']")
        header = page.locator("#select-all-cards")
        first_target = rows.nth(0).locator(".browser-checkbox-target")
        second_target = rows.nth(1).locator(".browser-checkbox-target")
        header_target = page.locator(".browser-checkbox-target").filter(has=header)
        status = page.locator("#browser-selected-status-compact")
        suspend = page.locator("#btn-suspend")
        detail_dialog = page.locator("#detail-offcanvas")

        def wait_for_badge_counts(expected):
            page.wait_for_function(
                (
                    "(expected) => {"
                    " const text = document.getElementById("
                    "'browser-selected-status-compact')?.textContent || '';"
                    " const counts = (text.match(/\\d+/g) || []).map(Number);"
                    " return counts.length === expected.length &&"
                    " counts.every((count, index) => count === expected[index]);"
                    " }"
                ),
                arg=expected,
                timeout=6000,
            )

        assert (
            first_box.is_visible() and second_box.is_visible() and header.is_visible()
        )
        assert (
            first_target.is_visible()
            and second_target.is_visible()
            and header_target.is_visible()
        )
        header_label = header.get_attribute("aria-label")
        row_label = first_box.get_attribute("aria-label")
        assert header_label and row_label and header_label != row_label

        first_target.tap()
        page.wait_for_function(
            "document.querySelector('#results-body input[type=checkbox]')?.checked === true",
            timeout=6000,
        )
        page.wait_for_function(
            "document.getElementById('select-all-cards')?.indeterminate === true",
            timeout=6000,
        )
        assert first_box.is_checked() and not second_box.is_checked()
        assert rows.nth(0).get_attribute("aria-selected") == "true"
        assert rows.nth(1).get_attribute("aria-selected") == "false"
        assert status.is_visible()
        wait_for_badge_counts([1, 2])
        assert not suspend.is_disabled()
        assert detail_dialog.get_attribute("open") is None

        second_target.tap()
        page.wait_for_function(
            "document.querySelectorAll('#results-body input[type=checkbox]:checked').length===2",
            timeout=6000,
        )
        assert header.is_checked()
        assert rows.nth(0).get_attribute("aria-selected") == "true"
        assert rows.nth(1).get_attribute("aria-selected") == "true"
        assert status.is_visible()
        wait_for_badge_counts([2, 2])
        assert not suspend.is_disabled()
        assert detail_dialog.get_attribute("open") is None
        header_target.tap()
        page.wait_for_function(
            "document.querySelectorAll('#results-body input[type=checkbox]:checked').length===0",
            timeout=6000,
        )
        assert not header.is_checked()
        assert not header.evaluate("el => el.indeterminate")
        status.wait_for(state="hidden", timeout=6000)
        assert suspend.is_disabled()

        header_target.tap()
        page.wait_for_function(
            "document.querySelectorAll('#results-body input[type=checkbox]:checked').length===2",
            timeout=6000,
        )
        assert header.is_checked() and status.is_visible()
        assert rows.nth(0).get_attribute("aria-selected") == "true"
        assert rows.nth(1).get_attribute("aria-selected") == "true"
        assert not suspend.is_disabled()
        assert detail_dialog.get_attribute("open") is None

        second_target.tap()
        page.wait_for_function(
            "document.querySelectorAll('#results-body input[type=checkbox]:checked').length===1",
            timeout=6000,
        )
        page.wait_for_function(
            "document.getElementById('select-all-cards')?.indeterminate === true",
            timeout=6000,
        )
        assert first_box.is_checked() and not second_box.is_checked()
        assert rows.nth(0).get_attribute("aria-selected") == "true"
        assert rows.nth(1).get_attribute("aria-selected") == "false"
        assert status.is_visible()
        wait_for_badge_counts([1, 2])
        assert not suspend.is_disabled()
        assert detail_dialog.get_attribute("open") is None

        page.locator("#search").fill("dogword")
        page.locator("#search").press("Enter")
        page.wait_for_function(
            "() => { const body = document.getElementById('results-body');"
            "return body?.children.length === 1 && body.textContent.includes('dogword'); }",
            timeout=6000,
        )
        page.wait_for_function(
            "() => { const header = document.getElementById('select-all-cards');"
            "return header && !header.checked && !header.indeterminate; }",
            timeout=6000,
        )
        assert not header.is_checked()
        assert not header.evaluate("el => el.indeterminate")
        status.wait_for(state="hidden", timeout=6000)
        assert suspend.is_disabled()

        remorphed_row = page.locator("#results-body tr.browser-row")
        remorphed_box = remorphed_row.locator("input[type='checkbox']")
        remorphed_target = remorphed_row.locator(".browser-checkbox-target")
        assert remorphed_box.is_visible() and remorphed_target.is_visible()
        assert not remorphed_box.is_checked()
        remorphed_target.tap()
        page.wait_for_function(
            "document.querySelector('#results-body input[type=checkbox]')?.checked === true",
            timeout=6000,
        )
        assert header.is_checked() and status.is_visible()
        assert remorphed_row.get_attribute("aria-selected") == "true"
        wait_for_badge_counts([1, 1])
        assert not suspend.is_disabled()
        assert detail_dialog.get_attribute("open") is None

        remorphed_row.locator(".row-line1 span.truncate").tap(
            position={"x": 8, "y": 12}
        )
        page.wait_for_function(
            "document.getElementById('detail-offcanvas')?.open === true", timeout=6000
        )
        page.wait_for_function(
            "() => { const f = document.querySelector('#detail iframe.editor-frame'); "
            "return f && /[/]edit[?]nid=/.test(f.getAttribute('src') || '') && f.contentDocument "
            "&& f.contentDocument.querySelector('[data-ankiweb-rich]')"
            "?.textContent.includes('dogword'); }",
            timeout=8000,
        )

        browser.close()


def test_browser_selected_status_reserves_layout_across_selection(live_server_browse):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        # Reserved status row is desktop-only; mobile renders compact badge in the table header.
        viewports: tuple[tuple[ViewportSize, bool, bool, str], ...] = (
            ({"width": 1440, "height": 900}, False, False, "desktop"),
        )
        for viewport, is_mobile, has_touch, label in viewports:
            context = browser.new_context(
                viewport=viewport, is_mobile=is_mobile, has_touch=has_touch
            )
            page = context.new_page()
            page.goto(f"{live_server_browse}/browse")
            page.wait_for_function(
                "document.querySelectorAll('#results-body tr.browser-row').length === 2",
                timeout=6000,
            )

            rows = page.locator("#results-body tr.browser-row")
            first_box = rows.nth(0).locator("input[type='checkbox']")
            second_box = rows.nth(1).locator("input[type='checkbox']")
            first_target = rows.nth(0).locator(".browser-checkbox-target")
            second_target = rows.nth(1).locator(".browser-checkbox-target")
            header = page.locator("#select-all-cards")
            header_target = page.locator(".browser-checkbox-target").filter(has=header)
            status = page.locator("#browser-selected-status")
            start_url = page.url

            def selected_count():
                return page.locator(
                    "#results-body input[type='checkbox']:checked"
                ).count()

            def wait_for_count(expected):
                page.wait_for_function(
                    "(expected) => document.querySelectorAll("
                    "'#results-body input[type=checkbox]:checked').length === expected",
                    arg=expected,
                    timeout=6000,
                )
                status.wait_for(state="visible" if expected else "hidden", timeout=6000)

            def geometry():
                return page.evaluate(
                    """() => {
                      const rect = (selector) => {
                        const {top, bottom, left, right, width, height} =
                          document.querySelector(selector).getBoundingClientRect();
                        return {top, bottom, left, right, width, height};
                      };
                      return {
                        actions: rect('#browser-actions'),
                        statusRow: rect('#browser-selection-status-row'),
                        badge: rect('#browser-selected-status'),
                        resultsWrap: rect('#results-wrap'),
                        results: rect('#results'),
                        browserTop: rect('#browser-top'),
                        browserTopClientWidth:
                          document.getElementById('browser-top').clientWidth,
                        viewportWidth: window.innerWidth,
                        scrollY: window.scrollY
                      };
                    }"""
                )

            baseline = None

            def capture(state, expected):
                nonlocal baseline
                assert selected_count() == expected
                current = geometry()
                row = current["statusRow"]
                assert row["height"] >= 24
                assert row["top"] >= current["actions"]["bottom"] - 1
                assert current["resultsWrap"]["top"] >= row["bottom"] - 1
                assert row["width"] >= current["browserTopClientWidth"] - 18
                assert row["left"] >= -1
                assert row["right"] <= current["viewportWidth"] + 1
                assert current["scrollY"] == 0
                assert page.url == start_url
                assert page.locator("#detail-offcanvas").get_attribute("open") is None

                if expected:
                    assert status.is_visible()
                    assert current["badge"]["top"] >= current["actions"]["bottom"] - 1
                    assert current["badge"]["left"] >= -1
                    assert current["badge"]["right"] <= current["viewportWidth"] + 1
                    assert current["badge"]["width"] <= row["width"] + 1
                else:
                    assert not status.is_visible()

                if baseline is None:
                    baseline = current
                else:
                    for key in (
                        "actions",
                        "statusRow",
                        "resultsWrap",
                        "results",
                    ):
                        for edge in ("top", "bottom"):
                            assert abs(current[key][edge] - baseline[key][edge]) <= 2, (
                                f"{label} {state} moved {key}.{edge}: "
                                f"{baseline[key][edge]} -> {current[key][edge]}"
                            )

            def toggle(target):
                if has_touch:
                    target.tap()
                else:
                    target.click()

            wait_for_count(0)
            capture("none", 0)

            toggle(first_target)
            wait_for_count(1)
            assert first_box.is_checked() and not second_box.is_checked()
            capture("one", 1)

            toggle(second_target)
            wait_for_count(2)
            assert first_box.is_checked() and second_box.is_checked()
            capture("two", 2)

            toggle(header_target)
            wait_for_count(0)
            assert not header.is_checked()
            capture("clear", 0)

            context.close()

        browser.close()
