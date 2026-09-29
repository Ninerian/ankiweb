"""I2: hand-written screens follow the active UI language.

The autouse `_default_english_lang` fixture (conftest) resets to English before each test,
so the default-English tests need no setup; the zh-CN tests call set_lang in-body. Screens
use the process-global `tr` (ankiweb.core.i18n), so set_lang controls their language regardless
of how the test collection was opened.
"""

from __future__ import annotations
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import anki.lang
from ankiweb.core.config import Settings
from ankiweb.app import create_app
from ankiweb.adapters.inbound.http_shared.page import render_page
from ankiweb.adapters.inbound.http_datastar.deckbrowser import render_deckbrowser_html
from ankiweb.adapters.inbound.http_datastar.custom_study import render_custom_study_html


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(collection_path=tmp_path / "c.anki2"))) as c:
        yield c

def test_toolbar_default_english():
    html = render_page("deckbrowser", "<div>x</div>")
    assert ">Decks</a>" in html and ">Add</a>" in html
    assert ">Browse</a>" in html and ">Stats</a>" in html
    assert ">Source</a>" in html  # keyless, stays English


def test_toolbar_zh():
    anki.lang.set_lang("zh-CN")
    html = render_page("deckbrowser", "<div>x</div>")
    assert "牌组" in html and "浏览" in html and "统计" in html
    assert ">Source</a>" in html  # keyless stays English even in zh


def test_spa_toolbar_default_english(client):
    r = client.get("/graphs")
    assert r.status_code == 200
    assert ">Decks</a>" in r.text and ">Add</a>" in r.text
    assert ">Browse</a>" in r.text and ">Stats</a>" in r.text
    assert "‹ Decks" in r.text
def test_spa_toolbar_zh(client):
    anki.lang.set_lang("zh-CN")
    r = client.get("/graphs")
    assert r.status_code == 200
    assert "牌组" in r.text and "浏览" in r.text and "统计" in r.text
    assert "‹ 牌组" in r.text


def test_spa_toolbar_de(client):
    anki.lang.set_lang("de")
    r = client.get("/graphs")
    assert r.status_code == 200
    assert "Stapel" in r.text and "Kartenverwaltung" in r.text and "Statistiken" in r.text
    assert "‹ Stapel" in r.text
def test_deckbrowser_default_english(temp_collection):
    html = render_deckbrowser_html(temp_collection)
    assert "Create Deck" in html and "Import" in html


def test_deckbrowser_zh(temp_collection):
    anki.lang.set_lang("zh-CN")
    html = render_deckbrowser_html(temp_collection)
    assert "创建牌组" in html and "导入" in html


def test_custom_study_default_english(temp_collection):
    html = render_custom_study_html(temp_collection)
    assert "Custom Study" in html
    assert "Increase today's new card limit" in html


def test_custom_study_zh(temp_collection):
    anki.lang.set_lang("zh-CN")
    html = render_custom_study_html(temp_collection)
    assert "自定义学习" in html
    assert "提升今日新卡片上限" in html
