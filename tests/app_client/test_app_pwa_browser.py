"""Exercise the app journey and PWA in Chromium against a live server."""

import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from anki.collection import Collection

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page, expect, sync_playwright


@pytest.fixture
def journey_deck(tmp_path: Path) -> int:
    # The shared live_app fixture opens this path after this fixture finishes.
    col = Collection(str(tmp_path / "live.anki2"))
    try:
        deck_id = col.decks.id("Journey deck")
        model = col.models.by_name("Basic")
        assert deck_id is not None and model is not None
        for index in range(3):
            note = col.new_note(model)
            note["Front"] = f"Journey question {index}"
            note["Back"] = f"Journey answer {index}"
            col.add_note(note, deck_id)
        return deck_id
    finally:
        col.close()


@pytest.fixture
def journey_app(journey_deck: int, request: pytest.FixtureRequest) -> tuple[str, int]:
    # Start the server only after the seeded collection has been closed.
    return request.getfixturevalue("live_app"), journey_deck


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


def _wait_for_app_worker(page: Page) -> None:
    page.wait_for_function(
        """async () => {
          const registration = await navigator.serviceWorker.getRegistration('/app/');
          const worker = navigator.serviceWorker.controller;
          return registration?.active && worker &&
            registration.scope === new URL('/app/', location.origin).href &&
            worker.scriptURL === new URL('/app/service-worker.js', location.origin).href;
        }"""
    )


def test_study_add_and_study_new_card(page: Page, journey_app: tuple[str, int]) -> None:
    base, deck_id = journey_app
    page.goto(f"{base}/app/")
    deck = page.locator(f"#deck-{deck_id}")
    new_count = deck.get_by_text(re.compile(r"^\d+ new$", re.IGNORECASE))
    expect(new_count).to_have_text(re.compile(r"^3 new$", re.IGNORECASE))

    deck.get_by_role("link", name="Learn Journey deck").click()
    expect(page).to_have_url(f"{base}/app/review?deck={deck_id}")
    seen: set[str] = set()
    for index in range(3):
        question = page.locator("#card-q")
        expect(question).to_contain_text("Journey question")
        question_text = question.inner_text()
        seen.add(question_text)
        page.locator("#btn-show-ans").click()
        page.locator("#ease-4").click()
        expect(page.locator("#streak-count")).to_have_text(str(index + 1))
        if index < 2:
            expect(question).not_to_have_text(question_text)
    assert len(seen) == 3
    expect(page.locator("#session-complete")).to_be_visible()

    page.locator("#hud-progress").get_by_role("link", name="Back to decks").click()
    expect(page).to_have_url(f"{base}/app/")
    expect(new_count).to_have_text(re.compile(r"^0 new$", re.IGNORECASE))
    deck.get_by_role("link", name="Edit / Add").click()
    expect(page).to_have_url(f"{base}/app/add?deck={deck_id}")

    front = page.get_by_label("Front (Question / Prompt)", exact=True)
    front.fill("New journey card")
    front.press("Enter")
    back = page.get_by_label("Back (Answer / Meaning)", exact=True)
    expect(back).to_be_visible()
    back.fill("New journey answer")
    back.press("Enter")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(page.locator("#added-cards")).to_contain_text("New journey card")
    page.get_by_role("button", name="Done", exact=True).click()
    summary = page.get_by_role("dialog")
    expect(summary).to_be_visible()
    summary.get_by_role("link", name="Start studying", exact=True).click()
    expect(page).to_have_url(f"{base}/app/review?deck={deck_id}")
    expect(page.locator("#card-q")).to_contain_text("New journey card")


def test_worker_controls_app_and_offline_retry(page: Page, live_app: str) -> None:
    page.goto(f"{live_app}/app/")
    expect(page.get_by_role("heading", name="My Decks")).to_be_visible()
    _wait_for_app_worker(page)

    page.context.set_offline(True)
    try:
        response = page.goto(f"{live_app}/app/")
        assert response is not None and response.status == 200
        expect(page.get_by_role("heading", name="You're offline")).to_be_visible()
        expect(page.get_by_role("heading", name="My Decks")).to_have_count(0)
        retry = page.get_by_role("link", name="Try again")
        expect(retry).to_have_attribute("href", "/app/")
        page.context.set_offline(False)
        retry.click()
        expect(page).to_have_url(f"{live_app}/app/")
        expect(page.get_by_role("heading", name="My Decks")).to_be_visible()
    finally:
        page.context.set_offline(False)


def test_chromium_reports_app_installable(page: Page, live_app: str) -> None:
    page.goto(f"{live_app}/app/")
    _wait_for_app_worker(page)
    session = page.context.new_cdp_session(page)
    try:
        installability = session.send("Page.getInstallabilityErrors")
        manifest = session.send("Page.getAppManifest")
        assert installability["installabilityErrors"] == []
        assert manifest["errors"] == []
        assert manifest["url"] == f"{live_app}/app/manifest.webmanifest"
        data = json.loads(manifest["data"])
        assert data["id"] == data["scope"] == data["start_url"] == "/app/"
    finally:
        session.detach()
