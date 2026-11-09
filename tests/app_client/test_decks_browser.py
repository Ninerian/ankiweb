import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import pytest
import uvicorn
from anki.collection import Collection

from ankiweb.app import create_app
from ankiweb.core.app_client.strings import s
from ankiweb.core.config import Settings

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import (
    APIResponse,
    ConsoleMessage,
    Error,
    Page,
    Route,
    expect,
    sync_playwright,
)


class _ResponseGate:
    """Capture one real response and fulfill its intercepted request later."""

    def __init__(self) -> None:
        self.route: Route | None = None
        self.response: APIResponse | None = None

    def arm(self, page: Page, method: str, path: str) -> None:
        self.route = None
        self.response = None
        page.evaluate("() => { window.__deckGateCaptured = false; }")

        def capture(route: Route) -> None:
            if (
                self.route is not None
                or route.request.method != method
                or urlsplit(route.request.url).path != path
            ):
                route.continue_()
                return
            # Playwright's API fetch decompresses responses before fulfillment.
            # Negotiate identity so the returned body and headers still agree.
            headers = {**route.request.all_headers(), "accept-encoding": "identity"}
            response = route.fetch(headers=headers)
            assert response.status == 200
            assert "content-encoding" not in response.headers
            assert "text/event-stream" in response.headers["content-type"]
            self.route = route
            self.response = response
            page.evaluate("() => { window.__deckGateCaptured = true; }")

        page.route(f"**{path}*", capture)

    def wait(self, page: Page) -> None:
        page.wait_for_function("() => window.__deckGateCaptured === true")

    def release(self, *, canceled: bool = False) -> None:
        assert self.route is not None and self.response is not None
        try:
            self.route.fulfill(response=self.response)
        except Error:
            if not canceled:
                raise


DECKS = (
    "German B1 Vocab · 🇩🇪",
    "Spanish A2 · 🇪🇸",
    "Biology Cells · 🧬",
    "History 1900s · 🏛️",
    "Chemistry Basics · ⚗️",
)


@pytest.fixture
def decks_server(tmp_path: Path) -> Iterator[tuple[str, dict[str, int], _ResponseGate]]:
    path = tmp_path / "browser.anki2"
    col = Collection(str(path))
    try:
        model = col.models.by_name("Basic")
        assert model is not None
        for name in DECKS:
            deck_id = col.decks.id(name)
            assert deck_id is not None
            note = col.new_note(model)
            note["Front"] = name
            col.add_note(note, deck_id)
        ids = {node.name: node.deck_id for node in col.sched.deck_due_tree().children}
    finally:
        col.close()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        gate = _ResponseGate()
        app = create_app(Settings(collection_path=path))
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        thread = threading.Thread(
            target=server.run, kwargs={"sockets": [listener]}, daemon=True
        )
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if time.monotonic() > deadline:
                    raise RuntimeError("server did not start")
                time.sleep(0.05)
            yield f"http://127.0.0.1:{port}", ids, gate
        finally:
            server.should_exit = True
            thread.join(timeout=10)


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_deck_list_search_and_links(
    decks_server: tuple[str, dict[str, int], _ResponseGate],
    scheme: Literal["light", "dark"],
) -> None:
    base, ids, _ = decks_server
    problems: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(
            viewport={"width": 375, "height": 812}, color_scheme=scheme
        )

        def on_console(message: ConsoleMessage) -> None:
            if message.type == "error":
                problems.append(message.text)

        page.on("console", on_console)
        page.on("pageerror", lambda e: problems.append(str(e)))
        page.goto(f"{base}/app/")
        page.wait_for_selector("#deck-search")
        page.wait_for_load_state("networkidle")
        assert page.locator("article:visible").count() == 5

        requests: list[str] = []
        page.on("request", lambda r: requests.append(r.url))
        page.locator("#deck-search").press_sequentially("bio")
        expect(page.locator("article:visible h3")).to_have_text(["Biology Cells"])
        assert page.locator("article:visible h3").all_inner_texts() == ["Biology Cells"]
        assert not page.locator("#empty-state").is_visible()

        page.fill("#deck-search", "zzz")
        page.wait_for_selector("#empty-state", state="visible")
        assert page.locator("article:visible").count() == 0

        page.fill("#deck-search", "")
        page.wait_for_selector("#empty-state", state="hidden")
        assert page.locator("article:visible").count() == 5
        assert any("/app/decks/search" in url for url in requests)

        page.fill("#deck-search", "🧬" * 45)
        empty_button = page.locator("#empty-new-deck")
        expect(empty_button).to_be_visible()
        empty_button.click()
        expect(page.locator("#deck-name")).to_have_value("🧬" * 40)
        page.keyboard.press("Escape")
        page.fill("#deck-search", "")
        expect(page.locator("article:visible")).to_have_count(5)

        deck_id = ids["German B1 Vocab · 🇩🇪"]
        learn = page.locator(f"#deck-{deck_id} a").first
        assert learn.get_attribute("href") == f"/app/review?deck={deck_id}"
        edit = page.locator(f"#deck-{deck_id}").get_by_role(
            "link", name="Edit", exact=True
        )
        assert edit.get_attribute("href") == f"/app/edit?deck={deck_id}"
        assert page.evaluate("document.documentElement.scrollWidth") == 375
        browser.close()
    assert problems == []


def test_deck_overview_initializes_before_and_after_editor_navigation(
    decks_server: tuple[str, dict[str, int], _ResponseGate],
) -> None:
    base, ids, _ = decks_server
    problems: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 375, "height": 812})

        def on_console(message: ConsoleMessage) -> None:
            if message.type == "error":
                problems.append(f"console: {message.text}")

        def check_deck_sheet() -> None:
            page.wait_for_load_state("networkidle")
            opener = page.locator("#btn-new-deck")
            expect(page.locator("#deck-dialog")).to_have_count(0)
            opener.click()
            expect(page.locator("#deck-dialog")).to_be_visible()
            expect(page.locator("#deck-name")).to_be_focused()
            page.keyboard.press("Escape")
            expect(page.locator("#deck-dialog")).to_have_count(0)
            expect(opener).to_be_focused()

        page.on("console", on_console)
        page.on("pageerror", lambda error: problems.append(f"pageerror: {error}"))
        page.goto(f"{base}/app/")
        check_deck_sheet()
        assert problems == []

        deck_id = ids["German B1 Vocab · 🇩🇪"]
        page.locator(f"#deck-{deck_id}").get_by_role(
            "link", name="Edit", exact=True
        ).click()
        expect(page).to_have_url(f"{base}/app/edit?deck={deck_id}")
        expect(page.locator("#input-front")).to_be_visible()
        page.wait_for_load_state("networkidle")
        assert problems == []

        page.locator("#edit-back").click()
        expect(page).to_have_url(f"{base}/app/")
        check_deck_sheet()
        assert problems == []

        page.goto(f"{base}/app/edit?deck={deck_id}&view=cards")
        cards = page.locator("#deck-cards")
        expect(cards).to_be_visible()
        expect(cards).to_be_focused()
        page.wait_for_load_state("networkidle")
        expect(cards).to_be_focused()
        assert problems == []
        browser.close()


def _open_deck_action(page, name: str, action: str) -> None:
    page.get_by_role(
        "button", name=s("app_decks_menu_open", lang="en", deck=name)
    ).click()
    page.get_by_role("menuitem", name=s(action, lang="en"), exact=True).click()


def test_search_ignores_delayed_response_and_preserves_input_focus_and_cursor(
    decks_server: tuple[str, dict[str, int], _ResponseGate],
) -> None:
    base, _, gate = decks_server
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_viewport_size({"width": 375, "height": 500})
        page.goto(f"{base}/app/")
        page.wait_for_load_state("networkidle")
        search = page.locator("#deck-search")
        gate.arm(page, "GET", "/app/decks/search")
        search.press_sequentially("history")
        gate.wait(page)
        search.fill("biogy")
        search.evaluate("(el) => el.setSelectionRange(3, 3)")
        search.press_sequentially("lo")
        expect(search).to_have_value("biology")
        expect(page.locator("article:visible h3")).to_have_text(["Biology Cells"])
        expect(search).to_be_focused()
        assert search.evaluate("(el) => [el.selectionStart, el.selectionEnd]") == [5, 5]
        gate.release(canceled=True)
        expect(page.locator("article:visible h3")).to_have_text(["Biology Cells"])
        expect(search).to_be_focused()
        assert search.evaluate("(el) => [el.selectionStart, el.selectionEnd]") == [5, 5]
        browser.close()


def test_refresh_is_canceled_by_typing_and_preserves_scroll(
    decks_server: tuple[str, dict[str, int], _ResponseGate],
) -> None:
    base, ids, gate = decks_server
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 375, "height": 500})
        page.goto(f"{base}/app/")
        page.wait_for_load_state("networkidle")
        search = page.locator("#deck-search")
        gate.arm(page, "GET", "/app/decks/search")
        page.evaluate(
            """created => window.dispatchEvent(
                new CustomEvent('ankiweb:decks-refresh', {detail: {created}})
            )""",
            ids["Biology Cells · 🧬"],
        )
        gate.wait(page)
        assert gate.route is not None
        assert gate.route.request.headers["x-deck-created"] == str(
            ids["Biology Cells · 🧬"]
        )
        page.evaluate("""() => {
            window.__searchPatched = false;
            document.addEventListener('datastar-fetch', event => {
                if (event.detail.type === 'datastar-patch-elements' &&
                    event.detail.argsRaw.selector === '#deck-results') {
                    window.__searchPatched = true;
                }
            });
        }""")
        with page.expect_response(
            lambda response: (
                "/app/decks/search" in response.url
                and response.request.headers.get("x-deck-created") is None
            )
        ):
            search.press_sequentially(" ")
            page.evaluate("window.scrollTo(0, 300)")
            before = page.evaluate("window.scrollY")
        page.wait_for_function("() => window.__searchPatched === true")
        expect(page.locator("article:visible")).to_have_count(5)
        assert page.evaluate("window.scrollY") == before
        expect(search).to_be_focused()
        gate.release(canceled=True)
        expect(page.locator("article:visible")).to_have_count(5)
        browser.close()


def test_create_save_and_delete_reproject_active_search(
    decks_server: tuple[str, dict[str, int], _ResponseGate],
) -> None:
    base, _, _ = decks_server
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(f"{base}/app/")
        page.wait_for_load_state("networkidle")
        search = page.locator("#deck-search")
        search.press_sequentially("biology")
        expect(page.locator("article:visible h3")).to_have_text(["Biology Cells"])

        page.locator("#btn-new-deck").click()
        create = page.locator("#deck-dialog")
        page.locator("#deck-name").press_sequentially("Marine Biology")
        create.get_by_role("radio", name="No languages").check()
        expect(page.locator("#btn-create-deck")).to_be_enabled()
        page.locator("#btn-create-deck").click()
        expect(create).to_have_count(0)
        expect(search).to_have_value("")
        expect(
            page.get_by_role("heading", name="Marine Biology", level=3)
        ).to_be_visible()
        expect(page.locator("article:visible")).to_have_count(6)

        search.fill("biology")
        expect(page.locator("article:visible h3")).to_have_text(
            ["Biology Cells", "Marine Biology"]
        )
        _open_deck_action(page, "Biology Cells", "app_decks_settings")
        settings = page.locator("#deck-dialog")
        expect(settings).to_be_visible()
        page.locator("#set-name").fill("")
        page.locator("#set-name").press_sequentially("Botany Cells")
        expect(page.locator("#deck-settings-save")).to_be_enabled()
        page.locator("#deck-settings-save").click()
        expect(settings).to_have_count(0)
        expect(search).to_have_value("biology")
        expect(page.locator("article:visible h3")).to_have_text(["Marine Biology"])

        _open_deck_action(page, "Marine Biology", "app_decks_delete")
        delete = page.locator("#deck-dialog")
        expect(delete).to_be_visible()
        page.locator("#deck-delete-confirm").click()
        expect(delete).to_have_count(0)
        expect(search).to_have_value("biology")
        expect(page.locator("#empty-state")).to_be_visible()
        expect(page.locator("article:visible")).to_have_count(0)
        search.fill("")
        expect(
            page.get_by_role("heading", name="Botany Cells", level=3)
        ).to_be_visible()
        expect(page.locator("article:visible")).to_have_count(5)
        browser.close()


@pytest.mark.parametrize("operation", ["save", "delete"])
def test_typing_while_mutation_response_is_pending_uses_latest_search(
    decks_server: tuple[str, dict[str, int], _ResponseGate],
    operation: str,
) -> None:
    base, ids, gate = decks_server
    deck_id = ids["Biology Cells · 🧬"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(f"{base}/app/")
        page.wait_for_load_state("networkidle")
        search = page.locator("#deck-search")
        search.fill("biology")
        expect(page.locator("article:visible h3")).to_have_text(["Biology Cells"])
        if operation == "save":
            _open_deck_action(page, "Biology Cells", "app_decks_settings")
            expect(page.locator("#deck-dialog")).to_be_visible()
            page.locator("#set-name").fill("Botany Cells")
            expect(page.locator("#deck-settings-save")).to_be_enabled()
            gate.arm(page, "POST", f"/app/decks/{deck_id}/settings")
            page.locator("#deck-settings-save").click()
        else:
            _open_deck_action(page, "Biology Cells", "app_decks_delete")
            expect(page.locator("#deck-dialog")).to_be_visible()
            gate.arm(page, "POST", f"/app/decks/{deck_id}/delete")
            page.locator("#deck-delete-confirm").click()
        gate.wait(page)
        page.keyboard.press("Escape")
        search.fill("")
        search.press_sequentially("history")
        expect(page.locator("article:visible h3")).to_have_text(["History 1900s"])
        gate.release()
        expect(search).to_have_value("history")
        expect(page.locator("article:visible h3")).to_have_text(["History 1900s"])
        search.fill("")
        if operation == "save":
            expect(
                page.get_by_role("heading", name="Botany Cells", level=3)
            ).to_be_visible()
        else:
            expect(
                page.get_by_role("heading", name="Biology Cells", level=3)
            ).to_have_count(0)
        browser.close()


def test_search_started_before_delete_cannot_restore_deleted_row(
    decks_server: tuple[str, dict[str, int], _ResponseGate],
) -> None:
    base, _, gate = decks_server
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(f"{base}/app/")
        page.wait_for_load_state("networkidle")
        search = page.locator("#deck-search")
        search.fill("biology")
        expect(page.locator("article:visible h3")).to_have_text(["Biology Cells"])
        gate.arm(page, "GET", "/app/decks/search")
        search.fill("bio")
        gate.wait(page)
        _open_deck_action(page, "Biology Cells", "app_decks_delete")
        expect(page.locator("#deck-dialog")).to_be_visible()
        page.locator("#deck-delete-confirm").click()
        expect(page.locator("#deck-dialog")).to_have_count(0)
        expect(page.locator("#empty-state")).to_be_visible()
        gate.release(canceled=True)
        expect(search).to_have_value("bio")
        expect(page.locator("#empty-state")).to_be_visible()
        expect(
            page.get_by_role("heading", name="Biology Cells", level=3)
        ).to_have_count(0)
        browser.close()


def test_typing_while_create_is_pending_resets_search_on_success(
    decks_server: tuple[str, dict[str, int], _ResponseGate],
) -> None:
    base, _, gate = decks_server
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(f"{base}/app/")
        page.wait_for_load_state("networkidle")
        search = page.locator("#deck-search")
        search.fill("biology")
        expect(page.locator("article:visible h3")).to_have_text(["Biology Cells"])
        page.locator("#btn-new-deck").click()
        sheet = page.locator("#deck-dialog")
        page.locator("#deck-name").fill("Marine Biology")
        sheet.get_by_role("radio", name="No languages").check()
        expect(page.locator("#btn-create-deck")).to_be_enabled()
        gate.arm(page, "POST", "/app/decks")
        page.locator("#btn-create-deck").click()
        gate.wait(page)
        page.keyboard.press("Escape")
        search.fill("")
        search.press_sequentially("history")
        expect(page.locator("article:visible h3")).to_have_text(["History 1900s"])
        gate.release()
        expect(page.locator("#deck-search")).to_have_value("")
        expect(page.locator("article:visible")).to_have_count(6)
        search.fill("")
        expect(
            page.get_by_role("heading", name="Marine Biology", level=3)
        ).to_be_visible()
        browser.close()


def test_search_visibility_tracks_empty_collection(
    decks_server: tuple[str, dict[str, int], _ResponseGate],
) -> None:
    base, _, _ = decks_server
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(f"{base}/app/")
        page.wait_for_load_state("networkidle")
        for name in (
            "German B1 Vocab",
            "Spanish A2",
            "Biology Cells",
            "History 1900s",
            "Chemistry Basics",
        ):
            _open_deck_action(page, name, "app_decks_delete")
            expect(page.locator("#deck-dialog")).to_be_visible()
            page.locator("#deck-delete-confirm").click()
            expect(page.locator("#deck-dialog")).to_have_count(0)
            expect(page.get_by_role("heading", name=name, level=3)).to_have_count(0)
        expect(page.locator("#no-decks")).to_be_visible()
        expect(page.locator("#deck-search")).to_be_hidden()
        page.locator("#no-decks button").click()
        sheet = page.locator("#deck-dialog")
        page.locator("#deck-name").fill("First again")
        sheet.get_by_role("radio", name="No languages").check()
        expect(page.locator("#btn-create-deck")).to_be_enabled()
        page.locator("#btn-create-deck").click()
        expect(page.get_by_role("heading", name="First again", level=3)).to_be_visible()
        expect(page.locator("#deck-search")).to_be_visible()
        expect(page.locator("#no-decks")).to_have_count(0)
        browser.close()
