import threading
import time
from pathlib import Path
from urllib.parse import quote

import anki.import_export_pb2 as ie
import pytest
import uvicorn
from anki.collection import Collection

from ankiweb.app import create_app
from ankiweb.core.config import Settings

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright


@pytest.fixture
def live_server_imp(tmp_path: Path):
    col_path = tmp_path / "c.anki2"
    Collection(str(col_path)).close()
    tmp_dir = tmp_path / "import-tmp"
    tmp_dir.mkdir()
    csv = tmp_dir / "notes.csv"
    csv.write_text("front,back\nhello,world\nfoo,bar\n")
    settings = Settings(collection_path=col_path, port=8135, import_tmp_dir=tmp_dir)
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings), host="127.0.0.1", port=8135, log_level="warning"
        )
    )
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("server did not start")
        time.sleep(0.05)
    yield "http://127.0.0.1:8135", str(csv)
    server.should_exit = True
    t.join(timeout=5)


def test_import_csv_page_boots(live_server_imp):
    url, csv_path = live_server_imp
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{url}/import-csv/{quote(csv_path, safe='')}")
        page.wait_for_selector("#import-csv-submit-btn", timeout=10000)
        page.wait_for_selector("#csv-delimiter-select", timeout=10000)
        assert not errors, errors
        assert page.locator("#import-csv-submit-btn").is_visible()
        assert page.locator("#csv-delimiter-select").is_visible()
        browser.close()


@pytest.fixture
def live_server_apkg(live_server_imp):
    url, csv_path = live_server_imp
    import_dir = Path(csv_path).parent
    apkg_path = import_dir / "import-modal.apkg"
    corrupt_path = import_dir / "corrupt-import-modal.apkg"
    note_front = "AnkiWeb import modal unique note"

    source = Collection(str(import_dir / "source.anki2"))
    deck_id = source.decks.id("Modal Regression")
    assert deck_id is not None
    model = source.models.by_name("Basic")
    assert model is not None
    note = source.new_note(model)
    note["Front"] = note_front
    note["Back"] = "AnkiWeb import modal unique answer"
    source.add_note(note, deck_id)
    source.export_anki_package(
        out_path=str(apkg_path),
        options=ie.ExportAnkiPackageOptions(
            with_scheduling=True,
            with_deck_configs=True,
            with_media=False,
            legacy=False,
        ),
        limit=None,
    )
    source.close()
    corrupt_path.write_bytes(b"not an Anki package")
    return url, apkg_path, corrupt_path, note_front


def _open_import_dialog(page, file_path: Path):
    dialog = page.locator("#importPackageModal")
    page.get_by_role("button", name="Add", exact=True).click()
    with page.expect_file_chooser() as fc_info:
        page.get_by_role("button", name="Import", exact=True).click()
    file_chooser = fc_info.value
    file_chooser.set_files(str(file_path))
    dialog.wait_for(state="visible", timeout=10000)
    return dialog


@pytest.mark.parametrize("dismiss_method", ["close_button", "escape", "backdrop"])
def test_import_apkg_modal_completion_and_dismissal(live_server_apkg, dismiss_method: str):
    url, apkg_path, _corrupt_path, note_front = live_server_apkg
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 480})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(f"{url}/deckbrowser")
        page.wait_for_selector("#deckbrowser-page", timeout=10000)

        dialog = _open_import_dialog(page, apkg_path)
        dialog.get_by_role("button", name="Import", exact=True).click()

        # Wait for import completion results containing the unique note
        dialog.locator(".details-table").wait_for(state="visible", timeout=15000)
        assert dialog.get_by_text(note_front).is_visible()
        close_button = dialog.get_by_role("button", name="Close", exact=True)
        expect(close_button).to_be_in_viewport(ratio=1)

        if dismiss_method == "close_button":
            close_button.click()
        elif dismiss_method == "escape":
            page.keyboard.press("Escape")
        elif dismiss_method == "backdrop":
            dialog.locator(":scope > .modal-backdrop button").click(
                position={"x": 5, "y": 5}
            )

        dialog.wait_for(state="hidden", timeout=10000)
        assert not dialog.is_visible()
        assert "/deckbrowser" in page.url
        assert not errors, errors

        # Verify deckbrowser navigation controls remain usable post-dismissal
        browse_link = page.get_by_role("link", name="Browse")
        assert browse_link.is_visible()
        browse_link.click()
        page.wait_for_url("**/browse", timeout=10000)
        assert "/browse" in page.url

        browser.close()


def test_import_apkg_modal_corrupt_file_error_and_dismissal(live_server_apkg):
    url, _apkg_path, corrupt_path, _note_front = live_server_apkg
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(f"{url}/deckbrowser")
        page.wait_for_selector("#deckbrowser-page", timeout=10000)

        dialog = _open_import_dialog(page, corrupt_path)
        dialog.get_by_role("button", name="Import", exact=True).click()

        # Wait for actual visible error box
        error_box = dialog.locator(".error-box")
        error_box.wait_for(state="visible", timeout=15000)
        assert dialog.locator(".error-text").is_visible()

        # Localized header Close must dismiss the dialog while keeping deckbrowser usable
        dialog.get_by_role("button", name="Close", exact=True).click()
        dialog.wait_for(state="hidden", timeout=10000)
        assert not dialog.is_visible()
        assert "/deckbrowser" in page.url
        assert not errors, errors

        browse_link = page.get_by_role("link", name="Browse")
        assert browse_link.is_visible()
        browse_link.click()
        page.wait_for_url("**/browse", timeout=10000)
        assert "/browse" in page.url

        browser.close()
