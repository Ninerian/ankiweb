"""Browser coverage for native deck settings and deletion dialogs."""

import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn
from anki.collection import Collection
from anki.decks import DeckId

from ankiweb.app import create_app
from ankiweb.core.config import Settings

playwright = pytest.importorskip("playwright.sync_api")
Page = playwright.Page
expect = playwright.expect
sync_playwright = playwright.sync_playwright


# Hold a real projection response after the server has rendered it, then mark
# delivery only after Datastar has processed every preceding event.
_HOLD_PREVIEW = r"""
(() => {
  const originalFetch = window.fetch.bind(window);
  const gate = window.__settingsGate = {
    armed: false, holdName: null, captured: false, delivered: false, body: '', release: null
  };
  window.fetch = async (input, init = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    if (!gate.armed || !/^\/app\/decks\/\d+\/settings\/preview$/.test(url.pathname)) {
      return originalFetch(input, init);
    }
    const fields = Object.fromEntries(await new Request(input, init).formData());
    if (gate.holdName && fields.name !== gate.holdName) return originalFetch(input, init);
    gate.armed = false;
    gate.fields = fields;
    // Exercise token scoping even if Datastar cancels the original request.
    const response = await originalFetch(input, {...init, signal: undefined});
    const body = await response.text();
    gate.body = body;
    gate.status = response.status;
    gate.captured = true;
    await new Promise(resolve => { gate.release = resolve; });
    const marker = '\nevent: datastar-patch-elements\n'
      + 'data: mode append\ndata: selector body\n'
      + 'data: elements <script data-effect="window.__settingsGate.delivered = true; el.remove()"></script>\n\n';
    return new Response(body + marker, {
      status: response.status, statusText: response.statusText, headers: response.headers
    });
  };
})();
"""


@pytest.fixture
def settings_server(tmp_path: Path) -> Iterator[tuple[str, dict[str, int]]]:
    path = tmp_path / "settings-browser.anki2"
    col = Collection(str(path))
    try:
        model = col.models.by_name("Basic")
        assert model is not None
        ids: dict[str, int] = {"Default": 1}
        for name in ("Original", "Deck A", "Deck B", "Deletable"):
            ids[name] = col.decks.add_normal_deck_with_name(f"{name} · 📚").id
        ids["Child"] = col.decks.add_normal_deck_with_name("Deletable · 📚::Child").id
        for name in ("Original", "Deck B"):
            deck = col.decks.get(DeckId(ids[name]), default=False)
            assert deck is not None
            deck["desc"] = "<!--ankiweb:lang=de>fr-->"
            col.decks.update_dict(deck)
        for name, deck_id in ids.items():
            note = col.new_note(model)
            note["Front"] = name
            col.add_note(note, DeckId(deck_id))
    finally:
        col.close()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                create_app(Settings(collection_path=path)), log_level="warning"
            )
        )
        thread = threading.Thread(
            target=server.run, kwargs={"sockets": [listener]}, daemon=True
        )
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("server did not start")
                time.sleep(0.05)
            yield f"http://127.0.0.1:{port}", ids
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError("server did not stop")


@pytest.fixture
def page() -> Iterator[Page]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": 375, "height": 812}, locale="en-US"
        )
        context.add_init_script(_HOLD_PREVIEW)
        try:
            yield context.new_page()
        finally:
            context.close()
            browser.close()


def _open_action(page: Page, name: str, action: str) -> None:
    page.get_by_role("button", name=f"Open menu for {name}", exact=True).click()
    page.get_by_role("menu", name=f"Open menu for {name}").get_by_role(
        "menuitem", name=action, exact=True
    ).click()


def _open_settings(page: Page, name: str) -> None:
    _open_action(page, name, "Deck settings")
    expect(page.locator("#deck-dialog")).to_be_visible()
    expect(page.locator("#set-name")).to_have_value(name)


def test_settings_dirty_projection_validation_and_saved_state(
    page: Page, settings_server: tuple[str, dict[str, int]]
) -> None:
    base, _ = settings_server
    page.goto(f"{base}/app/")
    _open_settings(page, "Original")
    name = page.locator("#set-name")
    dirty = page.locator("#deck-settings-dirty")
    save = page.locator("#deck-settings-save")
    expect(dirty).to_be_hidden()
    expect(save).to_be_disabled()

    name.press("ControlOrMeta+A")
    name.press_sequentially("Renamed")
    expect(name).to_have_value("Renamed")
    expect(page.locator("#set-name-changed")).to_be_visible()
    expect(dirty).to_contain_text("1 unsaved change")
    expect(save).to_be_enabled()
    page.get_by_role("radio", name="🧬").locator("..").click()
    expect(page.locator("#set-emoji-changed")).to_be_visible()
    expect(dirty).to_contain_text("2 unsaved changes")
    page.locator("#set-swap").click()
    expect(page.locator("#set-lang-changed")).to_be_visible()
    expect(dirty).to_contain_text("3 unsaved changes")

    page.locator("#set-src").select_option("de")
    expect(page.locator("#set-lang-msg")).to_contain_text("both German")
    expect(save).to_be_disabled()
    page.locator("#set-src").select_option("fr")
    expect(save).to_be_enabled()
    page.locator("#set-swap").click()
    page.get_by_role("radio", name="📚").locator("..").click()
    name.fill("Original")
    expect(dirty).to_be_hidden()
    expect(save).to_be_disabled()

    name.press("ControlOrMeta+A")
    name.press_sequentially("Saved name")
    expect(name).to_have_value("Saved name")
    expect(save).to_be_enabled()
    save.click()
    expect(page.locator("#deck-dialog")).to_be_hidden()
    expect(page.get_by_role("heading", name="Saved name", level=3)).to_be_visible()
    _open_settings(page, "Saved name")
    expect(page.locator("#set-src")).to_have_value("de")
    expect(page.locator("#set-dst")).to_have_value("fr")
    expect(dirty).to_be_hidden()
    expect(save).to_be_disabled()
    # A previous request's saving indicator must not disable the new instance.
    name.press("ControlOrMeta+A")
    name.press_sequentially("Saved again")
    expect(save).to_be_enabled()
    save.click()
    expect(page.locator("#deck-dialog")).to_be_hidden()
    expect(page.get_by_role("heading", name="Saved again", level=3)).to_be_visible()


def test_late_settings_a_response_cannot_replace_settings_b(
    page: Page, settings_server: tuple[str, dict[str, int]]
) -> None:
    base, _ = settings_server
    page.goto(f"{base}/app/")
    _open_settings(page, "Deck A")
    token_a = page.locator("#deck-dialog").get_attribute("data-token")
    assert token_a
    page.evaluate("window.__settingsGate.armed = true")
    page.locator("#set-name").fill("Modified A")
    page.wait_for_function("window.__settingsGate.captured")
    assert page.evaluate("window.__settingsGate.status") == 200
    assert f'data-token="{token_a}"' in page.evaluate("window.__settingsGate.body")
    fields = page.evaluate("window.__settingsGate.fields")
    assert fields["token"] == token_a
    assert fields["name"] == "Modified A"
    assert fields["emoji"] == "📚"
    assert fields["mode"] == "none"
    page.keyboard.press("Escape")
    expect(page.locator("#deck-dialog")).to_be_hidden()

    _open_settings(page, "Deck B")
    token_b = page.locator("#deck-dialog").get_attribute("data-token")
    assert token_b and token_b != token_a
    page.evaluate("window.__settingsGate.release()")
    page.wait_for_function("window.__settingsGate.delivered")
    expect(page.locator("#deck-dialog")).to_be_visible()
    expect(page.locator("#deck-dialog")).to_have_attribute("data-token", token_b)
    expect(page.locator("#set-name")).to_have_value("Deck B")
    expect(page.locator("#settings-preview-name")).to_have_text("Deck B")
    expect(page.locator("#set-src")).to_have_value("de")
    expect(page.locator("#set-dst")).to_have_value("fr")
    expect(page.locator("#deck-settings-dirty")).to_be_hidden()
    expect(page.locator("#deck-settings-save")).to_be_disabled()


def test_settings_language_swap_preserves_hidden_values(
    page: Page, settings_server: tuple[str, dict[str, int]]
) -> None:
    base, _ = settings_server
    page.goto(f"{base}/app/")
    _open_settings(page, "Original")
    src = page.locator("#set-src")
    dst = page.locator("#set-dst")
    details = page.locator("#set-language-details")
    preview = page.locator("#settings-preview-languages")
    expect(src).to_have_value("de")
    expect(dst).to_have_value("fr")
    expect(preview).to_contain_text("DE → 🇫🇷 FR")

    page.locator("#set-swap").click()
    expect(src).to_have_value("fr")
    expect(dst).to_have_value("de")
    expect(preview).to_contain_text("FR → 🇩🇪 DE")
    page.locator("#set-mode-none").check()
    expect(details).to_be_hidden()
    expect(preview).to_be_hidden()
    page.locator("#set-mode-langs").check()
    expect(details).to_be_visible()
    expect(src).to_have_value("fr")
    expect(dst).to_have_value("de")
    expect(preview).to_contain_text("FR → 🇩🇪 DE")
    expect(page.locator("#deck-settings-dirty")).to_contain_text("1 unsaved change")
    page.locator("#set-swap").click()
    expect(page.locator("#deck-settings-dirty")).to_be_hidden()
    expect(page.locator("#deck-settings-save")).to_be_disabled()


def test_settings_keyboard_edit_and_enter_submits_while_preview_is_pending(
    page: Page, settings_server: tuple[str, dict[str, int]]
) -> None:
    base, ids = settings_server
    page.goto(f"{base}/app/")
    _open_settings(page, "Original")
    name = page.locator("#set-name")
    name.press("ControlOrMeta+A")
    name.press("Backspace")
    page.evaluate("""() => {
      window.__settingsGate.holdName = 'Keyboard deck';
      window.__settingsGate.armed = true;
    }""")
    name.press_sequentially("Keyboard decx")
    name.press("Backspace")
    name.press("ArrowLeft")
    assert name.evaluate("el => [el.selectionStart, el.selectionEnd]") == [11, 11]
    name.press("Backspace")
    expect(name).to_have_value("Keyboard dc")
    name.press_sequentially("e")
    name.press("ArrowRight")
    name.press_sequentially("k")
    expect(name).to_have_value("Keyboard deck")
    page.wait_for_function("window.__settingsGate.captured")
    assert page.evaluate("window.__settingsGate.fields.name") == "Keyboard deck"
    with page.expect_request(
        lambda request: (
            request.method == "POST"
            and request.url.split("?", 1)[0].endswith(
                f"/app/decks/{ids['Original']}/settings"
            )
        )
    ):
        name.press("Enter")
    expect(page.locator("#deck-dialog")).to_be_hidden()
    expect(page.get_by_role("heading", name="Keyboard deck", level=3)).to_be_visible()
    page.evaluate("window.__settingsGate.release()")
    page.wait_for_function("window.__settingsGate.delivered")
    _open_settings(page, "Keyboard deck")
    expect(page.locator("#set-name")).to_have_value("Keyboard deck")
    expect(page.locator("#deck-settings-save")).to_be_disabled()


def test_delete_confirms_descendants_and_preserves_other_decks(
    page: Page, settings_server: tuple[str, dict[str, int]]
) -> None:
    base, _ = settings_server
    page.goto(f"{base}/app/")
    _open_action(page, "Deletable", "Delete deck")
    dialog = page.locator("#deck-dialog")
    expect(dialog).to_be_visible()
    expect(page.locator("#deck-delete-description")).to_contain_text("Deletable")
    expect(page.locator("#deck-delete-description")).to_contain_text("(2)")
    page.locator("#deck-delete-confirm").click()
    expect(dialog).to_be_hidden()
    expect(page.get_by_role("heading", name="Deletable", level=3)).to_have_count(0)
    expect(page.get_by_role("heading", name="Original", level=3)).to_be_visible()
    expect(page.locator("#toast")).to_contain_text("Deck deleted")
    page.reload()
    expect(page.get_by_role("heading", name="Deletable", level=3)).to_have_count(0)
    expect(page.get_by_role("heading", name="Original", level=3)).to_be_visible()


def test_default_deck_delete_is_protected(
    page: Page, settings_server: tuple[str, dict[str, int]]
) -> None:
    base, _ = settings_server
    page.goto(f"{base}/app/")
    page.get_by_role("button", name="Open menu for Default", exact=True).click()
    menu = page.get_by_role("menu", name="Open menu for Default")
    delete = menu.get_by_role("menuitem", name="Delete deck", exact=True)
    expect(delete).to_be_disabled()
    expect(delete).to_have_attribute("title", "The default deck cannot be deleted.")
    expect(page.get_by_role("heading", name="Default", level=3)).to_be_visible()


@pytest.mark.parametrize("action", ["Deck settings", "Delete deck"])
@pytest.mark.parametrize("dismissal", ["Escape", "Cancel"])
def test_dialog_dismissal_returns_focus_to_deck_menu(
    page: Page, settings_server: tuple[str, dict[str, int]], action: str, dismissal: str
) -> None:
    base, _ = settings_server
    page.goto(f"{base}/app/")
    opener = page.get_by_role("button", name="Open menu for Original", exact=True)
    _open_action(page, "Original", action)
    dialog = page.locator("#deck-dialog")
    expect(dialog).to_be_visible()
    if dismissal == "Escape":
        page.keyboard.press("Escape")
    elif action == "Deck settings":
        page.locator("#deck-settings-cancel").click()
    else:
        page.locator("#deck-delete-cancel").click()
    expect(dialog).to_be_hidden()
    expect(opener).to_be_focused()
    expect(page.get_by_role("heading", name="Original", level=3)).to_be_visible()
