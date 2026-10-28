"""Exercise the independent reviewer in a real browser against an Anki collection."""

import re
import socket
import threading
import time
from collections.abc import Iterator
from html import escape
from pathlib import Path
from typing import Literal

import pytest
import uvicorn
from anki.collection import Collection

from ankiweb.app import create_app
from ankiweb.core.config import Settings

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page, expect, sync_playwright


@pytest.fixture
def review_server(
    tmp_path: Path, request: pytest.FixtureRequest
) -> Iterator[tuple[str, int]]:
    """Start the normal application with an isolated, pre-populated collection."""
    parameter = getattr(request, "param", 3)
    vocab = parameter == "vocab"
    count = 2 if vocab else parameter
    collection_path = tmp_path / "review.anki2"
    col = Collection(str(collection_path))
    try:
        deck_id = col.decks.id("Browser review")
        model = col.models.by_name("Basic")
        assert deck_id is not None and model is not None
        if vocab:
            model["name"] = "AnkiWeb Vocab"
            model["tmpls"][0]["qfmt"] = '<div class="av-front-text">{{Front}}</div>'
            model["tmpls"][0]["afmt"] = (
                '{{FrontSide}}<div class="av-example">{{Back}}</div>'
            )
            col.models.update_dict(model)
        for index in range(count):
            note = col.new_note(model)
            note["Front"] = f"Question {index}"
            if vocab:
                note["Back"] = escape(
                    f"Answer {index}: <b>*word*</b> "
                    "<script>window.__unsafeExecuted=1</script> "
                    "<img src=x onerror=window.__unsafeExecuted=2>"
                )
            else:
                note["Back"] = f"Answer {index}"
            col.add_note(note, deck_id)
    finally:
        col.close()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                create_app(Settings(collection_path=collection_path)),
                log_level="warning",
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
                    raise RuntimeError("review server did not start")
                time.sleep(0.05)
            yield f"http://127.0.0.1:{port}", deck_id
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError("review server did not stop")


@pytest.fixture
def page() -> Iterator[Page]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": 375, "height": 812}, locale="en-US"
        )
        try:
            yield context.new_page()
        finally:
            context.close()
            browser.close()


def _open(page: Page, server: tuple[str, int]) -> None:
    url, deck_id = server
    page.goto(f"{url}/app/review?deck={deck_id}")
    expect(page.locator("#btn-show-ans")).to_be_visible()
    expect(page.locator("#answer-box")).to_be_hidden()


def _reveal(page: Page) -> None:
    page.evaluate("document.activeElement?.blur()")
    page.keyboard.press("Space")
    expect(page.locator("#answer-box")).to_be_visible()
    expect(page.locator("#ease-4")).to_be_visible()


def _rate(page: Page, ease: int) -> None:
    _reveal(page)
    with page.expect_response(
        lambda response: (
            response.url.endswith("/app/review/answer")
            and response.request.method == "POST"
        )
    ) as response:
        page.keyboard.press(str(ease))
    assert response.value.status == 200
    payload = response.value.request.post_data_json
    assert isinstance(payload, dict)
    assert payload["ease"] == ease
    expect(page.locator("#answer-box")).to_be_hidden()


def _open_sheet(page: Page) -> None:
    page.locator("#btn-actions-sheet").click()
    expect(page.locator("#sheet")).to_have_class(re.compile(r"\bmodal-open\b"))


def _no_horizontal_overflow(page: Page) -> None:
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def test_local_reveal_keyboard_and_no_legacy_network(
    page: Page, review_server: tuple[str, int]
) -> None:
    requests: list[str] = []
    sockets: list[str] = []
    errors: list[str] = []
    page.on("websocket", lambda ws: sockets.append(ws.url))
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: (
            errors.append(message.text) if message.type == "error" else None
        ),
    )
    page.on("request", lambda request: requests.append(request.url))
    _open(page, review_server)
    # Exclude initial assets and the browser's favicon request from the reveal window.
    page.wait_for_load_state("networkidle")
    assert not any("/_anki/" in url or "reviewer.js" in url for url in requests)
    requests.clear()

    _reveal(page)
    assert requests == [], (
        "revealing an already-rendered answer must not use the network"
    )
    assert "Answer 0" in page.locator("#answer-box").inner_text()
    _no_horizontal_overflow(page)
    with page.expect_response(
        lambda response: response.url.endswith("/app/review/answer")
    ):
        page.keyboard.press("4")
    expect(page.locator("#answer-box")).to_be_hidden()
    expect(page.locator("#streak-count")).to_have_text("1")
    assert not sockets
    assert not any("/_anki/" in url or "reviewer.js" in url for url in requests)
    assert not errors, errors


@pytest.mark.parametrize("review_server", ["vocab"], indirect=True)
def test_vocab_highlight_preserves_escaped_hostile_text_after_card_patch(
    page: Page, review_server: tuple[str, int]
) -> None:
    page.add_init_script("window.__unsafeExecuted = 0")
    _open(page, review_server)
    for index in range(2):
        expect(page.locator("#card-q")).to_contain_text(f"Question {index}")
        _reveal(page)
        example = page.locator("#answer-box .av-example")
        expect(example.locator("mark")).to_have_text("word")
        expect(example).to_contain_text("<b>word</b>")
        expect(example).to_contain_text("<script>window.__unsafeExecuted=1</script>")
        expect(example).to_contain_text("<img src=x onerror=window.__unsafeExecuted=2>")
        expect(example.locator("b, script, img")).to_have_count(0)
        assert page.evaluate("window.__unsafeExecuted") == 0
        if index == 0:
            with page.expect_response(
                lambda response: response.url.endswith("/app/review/answer")
            ):
                page.keyboard.press("4")
            expect(page.locator("#answer-box")).to_be_hidden()


def test_keyboard_guard_while_button_has_focus(
    page: Page, review_server: tuple[str, int]
) -> None:
    _open(page, review_server)
    requests: list[str] = []
    page.on("request", lambda request: requests.append(request.url))
    more = page.locator("#btn-actions-sheet")
    more.focus()
    page.keyboard.down("Space")
    expect(page.locator("#answer-box")).to_be_hidden()
    page.keyboard.up("Space")
    # Space activates the focused button, but must never reveal the card.
    expect(page.locator("#sheet")).to_have_class(re.compile(r"\bmodal-open\b"))
    page.keyboard.press("Escape")
    expect(page.locator("#sheet")).not_to_have_class(re.compile(r"\bmodal-open\b"))
    _reveal(page)
    more.focus()
    for key in "1234":
        page.keyboard.press(key)
    expect(page.locator("#answer-box")).to_be_visible()
    assert not any(url.endswith("/app/review/answer") for url in requests)


@pytest.mark.parametrize("ease", [1, 2, 3, 4])
def test_each_digit_rates_the_card(
    page: Page, review_server: tuple[str, int], ease: int
) -> None:
    _open(page, review_server)
    _rate(page, ease)
    expect(page.locator("#stage")).to_contain_text("Question 1")
    expect(page.locator("#streak-count")).to_have_text("0" if ease == 1 else "1")


def test_sheet_dialog_traps_focus_and_dismisses(
    page: Page, review_server: tuple[str, int]
) -> None:
    _open(page, review_server)
    sheet = page.locator("#sheet")
    _open_sheet(page)
    expect(sheet).to_have_attribute("role", "dialog")
    expect(sheet).to_have_attribute("aria-modal", "true")
    for _ in range(12):
        page.keyboard.press("Tab")
        assert page.evaluate(
            "document.querySelector('#sheet').contains(document.activeElement)"
        )
    page.keyboard.press("Shift+Tab")
    assert page.evaluate(
        "document.querySelector('#sheet').contains(document.activeElement)"
    )
    page.keyboard.press("Escape")
    expect(sheet).not_to_have_class(re.compile(r"\bmodal-open\b"))
    expect(page.locator("#btn-actions-sheet")).to_be_focused()

    _open_sheet(page)
    page.locator("#sheet-backdrop").click(position={"x": 5, "y": 5})
    expect(sheet).not_to_have_class(re.compile(r"\bmodal-open\b"))
    _open_sheet(page)
    page.locator("#sheet-dismiss").click()
    expect(sheet).not_to_have_class(re.compile(r"\bmodal-open\b"))


@pytest.mark.parametrize(
    ("action", "icon", "updated_label"),
    [
        ("mark", "mark-icon", "Unmark Card"),
        ("flag", "flag-icon", "Remove Flag"),
    ],
)
def test_sheet_toggles_mark_and_flag(
    page: Page,
    review_server: tuple[str, int],
    action: str,
    icon: str,
    updated_label: str,
) -> None:
    _open(page, review_server)
    _open_sheet(page)
    expect(page.locator("#action-info")).to_have_attribute(
        "href", re.compile(r"^/app/review/info/\d+$")
    )
    with page.expect_response(
        lambda response: response.url.endswith(f"/app/review/action/{action}")
    ) as response:
        page.locator(f"#action-{action}").click()
    assert response.value.status == 200
    expect(page.locator(f"#{icon}")).to_be_visible()
    expect(page.locator("#sheet")).not_to_have_class(re.compile(r"\bmodal-open\b"))
    _open_sheet(page)
    expect(page.locator(f"#action-{action}")).to_contain_text(updated_label)
    with page.expect_response(
        lambda response: response.url.endswith(f"/app/review/action/{action}")
    ) as response:
        page.locator(f"#action-{action}").click()
    assert response.value.status == 200
    expect(page.locator(f"#{icon}")).to_have_count(0)


@pytest.mark.parametrize("action", ["bury", "suspend"])
def test_sheet_action_advances_real_queue(
    page: Page, review_server: tuple[str, int], action: str
) -> None:
    _open(page, review_server)
    expect(page.locator("#stage")).to_contain_text("Question 0")
    _open_sheet(page)
    with page.expect_response(
        lambda response: response.url.endswith(f"/app/review/action/{action}")
    ) as response:
        page.locator(f"#action-{action}").click()
    assert response.value.status == 200
    expect(page.locator("#stage")).to_contain_text("Question 1")
    expect(page.locator("#stage")).not_to_contain_text("Question 0")


def test_due_date_error_then_success(
    page: Page, review_server: tuple[str, int]
) -> None:
    _open(page, review_server)
    _open_sheet(page)
    page.locator("#action-due").click()
    due = page.locator("#due-spec")
    due.fill("not-a-date")
    with page.expect_response(
        lambda response: response.url.endswith("/app/review/due")
    ):
        page.locator("#due-submit").click()
    expect(page.locator("#app-error")).to_be_visible()
    expect(page.locator("#stage")).to_contain_text("Question 0")
    due.fill("3")
    with page.expect_response(
        lambda response: response.url.endswith("/app/review/due")
    ) as response:
        page.locator("#due-submit").click()
    assert response.value.status == 200
    expect(page.locator("#stage")).to_contain_text("Question 1")
    expect(page.locator("#app-error")).to_be_hidden()


@pytest.mark.parametrize("review_server", [0], indirect=True)
def test_empty_deck_has_no_completion_summary(
    page: Page, review_server: tuple[str, int]
) -> None:
    url, deck_id = review_server
    page.goto(f"{url}/app/review?deck={deck_id}")
    expect(page.get_by_text("No cards due")).to_be_visible()
    expect(page.locator("#session-complete")).to_be_hidden()
    expect(page.locator("#sc-reviewed")).to_have_count(0)
    expect(page.locator("#streak-count")).to_have_text("0")


def test_streak_reload_undo_and_again_reset(
    page: Page, review_server: tuple[str, int]
) -> None:
    _open(page, review_server)
    _rate(page, 4)
    expect(page.locator("#streak-count")).to_have_text("1")
    page.reload()
    expect(page.locator("#streak-count")).to_have_text("1")
    _rate(page, 4)
    expect(page.locator("#streak-count")).to_have_text("2")
    _open_sheet(page)
    with page.expect_response(
        lambda response: response.url.endswith("/app/review/action/undo")
    ) as response:
        page.locator("#action-undo").click()
    assert response.value.status == 200
    expect(page.locator("#streak-count")).to_have_text("1")
    expect(page.locator("#stage")).to_contain_text("Question 1")
    _rate(page, 1)
    expect(page.locator("#streak-count")).to_have_text("0")
    expect(page.get_by_text(re.compile("Streak Reset", re.IGNORECASE))).to_be_visible()


@pytest.mark.parametrize("review_server", [1], indirect=True)
def test_reload_after_completion_does_not_invent_a_session(
    page: Page, review_server: tuple[str, int]
) -> None:
    _open(page, review_server)
    _rate(page, 4)
    expect(page.locator("#session-complete")).to_be_visible()
    expect(page.locator("#streak-count")).to_have_text("1")
    page.reload()
    expect(page.get_by_text("No cards due")).to_be_visible()
    expect(page.locator("#session-complete")).to_be_hidden()
    expect(page.locator("#sc-reviewed")).to_have_count(0)
    expect(page.locator("#streak-count")).to_have_text("1")


def test_reduced_motion_disables_reveal_and_streak_animations(
    page: Page, review_server: tuple[str, int]
) -> None:
    page.emulate_media(reduced_motion="reduce")
    _open(page, review_server)
    _reveal(page)
    assert page.evaluate(
        "document.getAnimations().every(animation => animation.playState !== 'running')"
    )
    with page.expect_response(
        lambda response: response.url.endswith("/app/review/answer")
    ):
        page.keyboard.press("4")
    expect(page.locator("#streak-count")).to_have_text("1")
    assert page.evaluate(
        "document.getAnimations().every(animation => animation.playState !== 'running')"
    )


@pytest.mark.parametrize("color_scheme", ["light", "dark"])
@pytest.mark.parametrize(
    ("review_server", "ratings", "title", "counts", "recall"),
    [
        (1, (4,), "Flawless!", (0, 0, 0, 1), "100"),
        (1, (2, 2, 2, 4), "Great run!", (0, 3, 0, 1), "100"),
        (2, (1, 4, 4), "Solid progress.", (1, 0, 0, 2), "67"),
        (1, (1, 1, 1, 4), "You showed up.", (3, 0, 0, 1), "25"),
    ],
    indirect=["review_server"],
    ids=["perfect", "great", "good", "tough"],
)
def test_completion_tiers_mobile_theme_and_reduced_motion(
    page: Page,
    review_server: tuple[str, int],
    ratings: tuple[int, ...],
    title: str,
    counts: tuple[int, int, int, int],
    recall: str,
    color_scheme: Literal["light", "dark"],
    tmp_path: Path,
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: (
            errors.append(message.text) if message.type == "error" else None
        ),
    )
    page.emulate_media(color_scheme=color_scheme, reduced_motion="reduce")
    _open(page, review_server)
    _no_horizontal_overflow(page)
    page.screenshot(path=tmp_path / f"review-{color_scheme}.png", full_page=True)
    for rating in ratings:
        _rate(page, rating)

    completion = page.locator("#session-complete")
    expect(completion).to_be_visible()
    expect(completion).to_have_attribute("aria-labelledby", "sc-title")
    expect(page.locator("#sc-title")).to_have_text(title)
    expect(page.locator("#sc-title")).to_be_focused()
    expect(page.locator("#sc-reviewed")).to_contain_text(str(len(ratings)))
    expect(page.locator("#sc-recall")).to_contain_text(recall)
    streak = 0
    for rating in reversed(ratings):
        if rating == 1:
            break
        streak += 1
    expect(page.locator("#sc-streak")).to_have_text(str(streak))
    expect(page.locator("#meter-fill")).to_have_attribute(
        "style", re.compile(r"width:\s*100%")
    )
    expect(page.locator("#sc-bar-again").locator("..")).to_have_attribute(
        "aria-hidden", "true"
    )
    for name, count in zip(("again", "hard", "good", "easy"), counts, strict=True):
        expect(page.locator(f"#sc-count-{name}")).to_contain_text(str(count))
    expect(page.locator("#btn-actions-sheet")).to_be_hidden()
    if ratings == (4,):
        expect(page.locator("#sc-restart")).to_have_count(0)
    _no_horizontal_overflow(page)
    assert page.evaluate(
        """() => document.getAnimations().filter(animation =>
            animation.playState === 'running').length === 0"""
    )
    page.screenshot(path=tmp_path / f"completion-{color_scheme}.png", full_page=True)
    assert not errors, errors
    back = completion.get_by_role(
        "link", name=re.compile("back to decks", re.IGNORECASE)
    )
    for locator in (page.locator("#sc-title"), back):
        locator.scroll_into_view_if_needed()
        assert locator.evaluate(
            """el => {
                const r = el.getBoundingClientRect();
                return r.left >= 0 && r.right <= innerWidth &&
                    r.top >= 0 && r.bottom <= innerHeight;
            }"""
        )
    expect(back).to_have_attribute("href", "/app/")
