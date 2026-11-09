"""Browser coverage for native create forms and delayed server projections."""

from collections.abc import Iterator

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page, expect, sync_playwright

# Hold real server responses, but honor the fetch AbortSignal when releasing them.
# The marker confirms that Datastar processed all preceding SSE fragments.
_HOLD_RESPONSES = r"""
(() => {
  const originalFetch = window.fetch.bind(window);
  const state = window.__deckFormRequests = {
    holdNames: [], holdMutationNames: [], requests: [], mutations: [], held: [], done: [],
    discarded: [], releases: {}, heldMutations: [], doneMutations: [], mutationReleases: {}
  };
  window.fetch = async (input, init = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    const method = (init.method || 'GET').toUpperCase();
    const preview = url.pathname === '/app/decks/new/preview' && method === 'POST';
    const create = url.pathname === '/app/decks' && method === 'POST';
    if (!preview && !create) return originalFetch(input, init);
    const fields = Object.fromEntries(new URLSearchParams(init.body));
    const contentType = new Headers(init.headers).get('content-type');
    if (create) {
      const id = state.mutations.length;
      state.mutations.push({fields, contentType});
      if (!state.holdMutationNames.includes(fields.name)) return originalFetch(input, init);
      const response = await originalFetch(input, {...init, signal: undefined});
      const body = await response.text();
      state.mutations[id].status = response.status;
      state.heldMutations.push(id);
      await new Promise(resolve => { state.mutationReleases[id] = resolve; });
      if (init.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      const marker = '\nevent: datastar-patch-elements\n'
        + 'data: mode append\ndata: selector body\n'
        + 'data: elements <script data-effect="el.remove()">'
        + 'window.__deckFormRequests.doneMutations.push(' + id + ')</script>\n\n';
      return new Response(body + marker, {
        status: response.status, statusText: response.statusText, headers: response.headers
      });
    }
    const id = state.requests.length;
    state.requests.push({id, fields, contentType});
    // Let the server finish even if Datastar cancels the browser request later.
    const response = await originalFetch(input, {...init, signal: undefined});
    const body = await response.text();
    state.requests[id].status = response.status;
    if (state.holdNames.includes(fields.name)) {
      state.held.push(id);
      await new Promise(resolve => { state.releases[id] = resolve; });
    }
    if (init.signal?.aborted) {
      state.discarded.push(id);
      throw new DOMException('Aborted', 'AbortError');
    }
    const marker = '\nevent: datastar-patch-elements\n'
      + 'data: mode append\ndata: selector body\n'
      + 'data: elements <script data-effect="el.remove()">'
      + 'window.__deckFormRequests.done.push(' + id + ')</script>\n\n';
    return new Response(body + marker, {
      status: response.status, statusText: response.statusText, headers: response.headers
    });
  };
})();
"""


@pytest.fixture
def page() -> Iterator[Page]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": 375, "height": 812}, locale="en-US"
        )
        context.add_init_script(_HOLD_RESPONSES)
        try:
            yield context.new_page()
        finally:
            context.close()
            browser.close()


def test_create_preview_ignores_out_of_order_response_and_preserves_cursor(
    page: Page, live_app: str
) -> None:
    page.goto(f"{live_app}/app/")
    page.locator("#btn-new-deck").click()
    name = page.locator("#deck-name")
    page.evaluate("window.__deckFormRequests.holdNames = ['Older name', 'Newer name']")
    name.press_sequentially("Older name")
    page.wait_for_function("window.__deckFormRequests.held.length === 1")
    name.press("ControlOrMeta+A")
    name.press_sequentially("Newer name")
    page.wait_for_function("window.__deckFormRequests.held.length === 2")
    name.evaluate("el => el.setSelectionRange(2, 5)")
    expect(name).to_be_focused()

    requests = page.evaluate("window.__deckFormRequests.requests")
    older = next(r for r in requests if r["fields"]["name"] == "Older name")
    newer = next(r for r in requests if r["fields"]["name"] == "Newer name")
    assert older["status"] == newer["status"] == 200
    assert older["contentType"].startswith("application/x-www-form-urlencoded")
    assert newer["contentType"].startswith("application/x-www-form-urlencoded")
    assert older["fields"]["token"] == newer["fields"]["token"]
    page.evaluate("id => window.__deckFormRequests.releases[id]()", newer["id"])
    page.wait_for_function(
        "id => window.__deckFormRequests.done.includes(id)", arg=newer["id"]
    )
    expect(page.locator("#preview-name")).to_have_text("Newer name")
    expect(name).to_be_focused()
    assert name.evaluate("el => [el.selectionStart, el.selectionEnd]") == [2, 5]
    page.evaluate("id => window.__deckFormRequests.releases[id]()", older["id"])
    page.wait_for_function(
        "id => window.__deckFormRequests.discarded.includes(id)", arg=older["id"]
    )
    expect(page.locator("#preview-name")).to_have_text("Newer name")
    expect(name).to_have_value("Newer name")
    expect(name).to_be_focused()
    assert name.evaluate("el => [el.selectionStart, el.selectionEnd]") == [2, 5]


def test_language_swap_and_hidden_values_are_preserved(
    page: Page, live_app: str
) -> None:
    page.goto(f"{live_app}/app/")
    page.locator("#btn-new-deck").click()
    src = page.locator("#new-src")
    dst = page.locator("#new-dst")
    details = page.locator("#new-language-details")
    preview = page.locator("#preview-languages")
    src.select_option("de")
    dst.select_option("fr")
    expect(preview).to_contain_text("DE → 🇫🇷 FR")
    page.locator("#new-swap").click()
    expect(src).to_have_value("fr")
    expect(dst).to_have_value("de")
    expect(preview).to_contain_text("FR → 🇩🇪 DE")
    page.locator("#new-mode-none").check()
    expect(details).to_be_hidden()
    expect(preview).to_have_count(0)
    page.locator("#new-mode-langs").check()
    expect(details).to_be_visible()
    expect(src).to_have_value("fr")
    expect(dst).to_have_value("de")
    expect(preview).to_contain_text("FR → 🇩🇪 DE")
    page.locator("#new-mode-none").check()
    page.locator("#deck-name").press_sequentially("Hidden languages")
    submit = page.locator("#btn-create-deck")
    expect(submit).to_be_enabled()
    submit.click()
    expect(
        page.get_by_role("heading", name="Hidden languages", level=3)
    ).to_be_visible()
    fields = page.evaluate("window.__deckFormRequests.mutations[0].fields")
    assert fields["mode"] == "none"
    assert fields["src"] == "fr"
    assert fields["dst"] == "de"


def test_enter_submits_current_draft_while_preview_is_pending(
    page: Page, live_app: str
) -> None:
    page.goto(f"{live_app}/app/")
    page.locator("#btn-new-deck").click()
    dialog = page.locator("#deck-dialog")
    name = page.locator("#deck-name")
    dialog.get_by_role("radio", name="No languages").check()
    page.evaluate("window.__deckFormRequests.holdNames = ['Keyboard deck']")
    name.press_sequentially("Keyboard decx")
    name.press("Backspace")
    name.press("ArrowLeft")
    assert name.evaluate("el => [el.selectionStart, el.selectionEnd]") == [11, 11]
    name.press("Backspace")
    name.press_sequentially("e")
    name.press("ArrowRight")
    name.press_sequentially("k")
    expect(name).to_have_value("Keyboard deck")
    page.wait_for_function("window.__deckFormRequests.held.length === 1")
    held = page.evaluate("window.__deckFormRequests.held[0]")
    token = dialog.get_attribute("data-token")
    name.press("Enter")
    expect(dialog).to_have_count(0)
    expect(page.get_by_role("heading", name="Keyboard deck", level=3)).to_be_visible()
    mutations = page.evaluate("window.__deckFormRequests.mutations")
    assert len(mutations) == 1
    assert mutations[0]["contentType"].startswith("application/x-www-form-urlencoded")
    assert mutations[0]["fields"] == {
        "token": token,
        "name": "Keyboard deck",
        "emoji": "📚",
        "mode": "none",
        "src": "",
        "dst": "",
    }

    # A response from the closed dialog must not patch a newly opened instance.
    page.locator("#btn-new-deck").click()
    expect(dialog).to_have_attribute("open", "")
    assert dialog.get_attribute("data-token") != token
    expect(name).to_have_value("")
    page.evaluate("id => window.__deckFormRequests.releases[id]()", held)
    page.wait_for_function(
        "id => window.__deckFormRequests.done.includes(id) || "
        "window.__deckFormRequests.discarded.includes(id)",
        arg=held,
    )
    expect(dialog).to_have_attribute("open", "")
    expect(name).to_have_value("")
    expect(page.locator("#preview-name")).not_to_have_text("Keyboard deck")


def test_preview_after_escape_cannot_patch_reopened_dialog(
    page: Page, live_app: str
) -> None:
    page.goto(f"{live_app}/app/")
    opener = page.locator("#btn-new-deck")
    dialog = page.locator("#deck-dialog")
    name = page.locator("#deck-name")
    opener.click()
    old_token = dialog.get_attribute("data-token")
    page.evaluate("window.__deckFormRequests.holdNames = ['Abandoned draft']")
    name.press_sequentially("Abandoned draft")
    page.wait_for_function("window.__deckFormRequests.held.length === 1")
    held = page.evaluate("window.__deckFormRequests.held[0]")
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    opener.click()
    assert dialog.get_attribute("data-token") != old_token
    expect(name).to_have_value("")
    page.evaluate("id => window.__deckFormRequests.releases[id]()", held)
    page.wait_for_function(
        "id => window.__deckFormRequests.done.includes(id)", arg=held
    )
    expect(dialog).to_have_attribute("open", "")
    expect(name).to_have_value("")
    expect(page.locator("#preview-name")).not_to_have_text("Abandoned draft")


def test_enter_validates_current_languages_even_when_preview_is_pending(
    page: Page, live_app: str
) -> None:
    page.goto(f"{live_app}/app/")
    page.locator("#btn-new-deck").click()
    dialog = page.locator("#deck-dialog")
    page.locator("#new-src").select_option("de")
    page.locator("#new-dst").select_option("de")
    page.evaluate("window.__deckFormRequests.holdNames = ['Invalid pair']")
    name = page.locator("#deck-name")
    name.press_sequentially("Invalid pair")
    page.wait_for_function("window.__deckFormRequests.held.length === 1")
    held = page.evaluate("window.__deckFormRequests.held[0]")
    name.press("Enter")
    expect(dialog).to_have_attribute("open", "")
    expect(page.locator("#deck-name-error")).to_contain_text("both German")
    expect(name).to_have_value("Invalid pair")
    expect(page.locator("#new-src")).to_have_value("de")
    expect(page.locator("#new-dst")).to_have_value("de")
    expect(page.get_by_role("heading", name="Invalid pair", level=3)).to_have_count(0)
    mutations = page.evaluate("window.__deckFormRequests.mutations")
    assert len(mutations) == 1
    assert mutations[0]["fields"]["src"] == mutations[0]["fields"]["dst"] == "de"
    page.evaluate("id => window.__deckFormRequests.releases[id]()", held)
    page.wait_for_function(
        "id => window.__deckFormRequests.done.includes(id) || "
        "window.__deckFormRequests.discarded.includes(id)",
        arg=held,
    )
    expect(page.locator("#deck-name-error")).to_contain_text("both German")
    expect(dialog).to_have_attribute("open", "")
    expect(name).to_have_value("Invalid pair")


def test_late_duplicate_error_cannot_touch_reopened_dialog(
    page: Page, live_app: str
) -> None:
    page.goto(f"{live_app}/app/")
    opener = page.locator("#btn-new-deck")
    dialog = page.locator("#deck-dialog")
    name = page.locator("#deck-name")
    submit = page.locator("#btn-create-deck")
    opener.click()
    name.press_sequentially("Existing")
    dialog.get_by_role("radio", name="No languages").check()
    expect(submit).to_be_enabled()
    submit.click()
    expect(dialog).to_have_count(0)
    expect(page.get_by_role("heading", name="Existing", level=3)).to_be_visible()

    opener.click()
    name.press_sequentially("Existing")
    dialog.get_by_role("radio", name="No languages").check()
    expect(submit).to_be_enabled()
    page.evaluate("window.__deckFormRequests.holdMutationNames = ['Existing']")
    old_token = dialog.get_attribute("data-token")
    submit.click()
    page.wait_for_function("window.__deckFormRequests.heldMutations.length === 1")
    held = page.evaluate("window.__deckFormRequests.heldMutations[0]")
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)

    opener.click()
    assert dialog.get_attribute("data-token") != old_token
    name.press_sequentially("New draft")
    dialog.get_by_role("radio", name="No languages").check()
    expect(page.locator("#preview-name")).to_have_text("New draft")
    expect(submit).to_be_enabled()
    page.evaluate("id => window.__deckFormRequests.mutationReleases[id]()", held)
    page.wait_for_function(
        "id => window.__deckFormRequests.doneMutations.includes(id)", arg=held
    )
    expect(dialog).to_have_attribute("open", "")
    expect(name).to_have_value("New draft")
    expect(page.locator("#deck-name-error")).to_be_hidden()
    expect(submit).to_be_enabled()
    submit.click()
    expect(dialog).to_have_count(0)
    expect(page.get_by_role("heading", name="New draft", level=3)).to_be_visible()
