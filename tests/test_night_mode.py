#!/usr/bin/env python3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ankiweb.adapters.inbound.http_shared.page import render_page
from ankiweb.app import create_app
from ankiweb.core.config import Settings


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(collection_path=tmp_path / "c.anki2"))) as c:
        yield c


def test_render_page_injects_night_css():
    html = render_page("deckbrowser", "<div>x</div>")
    assert "night-mode" in html
    assert "/shell/static/app.css" in html


def test_deckbrowser_has_night_toggle(client):
    r = client.get("/deckbrowser")
    assert "ankiwebToggleNight" in r.text


def test_bootstrap_js_has_night_toggle_and_persistence():
    js = (
        Path(__file__).resolve().parent.parent
        / "ankiweb"
        / "shell"
        / "static"
        / "bootstrap.js"
    ).read_text()
    assert "ankiwebToggleNight" in js
    assert "ankiweb-night" in js  # localStorage key (persisted preference)
