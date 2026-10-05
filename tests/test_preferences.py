from pathlib import Path
from typing import Any, cast

import anki.lang
from conftest import parse_datastar_events
from fastapi.testclient import TestClient

from ankiweb.adapters.inbound.http_datastar.preferences import render_preferences_html
from ankiweb.app import create_app
from ankiweb.core.config import Settings


def test_render_default_english(temp_collection):
    html = render_preferences_html(temp_collection)
    assert "Next day starts at" in html  # preferences_next_day_starts_at
    assert "Learn ahead limit" in html
    assert "New/review order" in html  # deck_config_new_review_priority
    assert "Enable load balancer" in html  # english fallback
    assert "id='rollover'" in html or 'id="rollover"' in html
    assert "id='default_search_text'" in html or 'id="default_search_text"' in html


def test_render_zh(temp_collection):
    anki.lang.set_lang("zh-CN")
    html = render_preferences_html(temp_collection)
    assert "设置" in html  # preferences_preferences heading


def test_saveprefs_roundtrip(tmp_path: Path):
    with TestClient(
        create_app(Settings(collection_path=tmp_path / "c.anki2"))
    ) as client:
        assert client.portal is not None
        app = cast(Any, client.app)
        base = client.portal.call(
            app.state.service.run, lambda col: col.get_preferences()
        )
        payload = {
            "rollover": 6,
            "learn_ahead_mins": 20,
            "new_review_mix": 2,
            "new_timezone": base.scheduling.new_timezone,
            "day_learn_first": True,
            "hide_audio_play_buttons": False,
            "interrupt_audio_when_answering": True,
            "show_remaining_due_counts": True,
            "show_intervals_on_buttons": True,
            "time_limit_mins": 3,
            "load_balancer_enabled": True,
            "fsrs_short_term_with_steps_enabled": False,
            "adding_defaults_to_current_deck": True,
            "paste_images_as_png": False,
            "paste_strips_formatting": False,
            "default_search_text": "deck:current",
            "ignore_accents_in_search": False,
            "render_latex": False,
            "daily": 7,
            "weekly": 4,
            "monthly": 3,
            "minimum_interval_mins": 45,
        }
        r = client.post(
            "/preferences/savePrefs", json=payload, headers={"Datastar-Request": "true"}
        )
        assert r.status_code == 200
        events = parse_datastar_events(r.text)
        assert any("window.location = '/deckbrowser'" in data for _, data in events)
        p = client.portal.call(
            app.state.service.run, lambda col: col.get_preferences()
        )
        assert p.scheduling.rollover == 6
        assert p.scheduling.learn_ahead_secs == 20 * 60  # form minutes -> proto seconds
        assert p.reviewing.time_limit_secs == 3 * 60
        assert p.scheduling.new_review_mix == 2
        assert p.scheduling.day_learn_first is True
        assert p.editing.default_search_text == "deck:current"
        assert p.backups.minimum_interval_mins == 45


def test_saveprefs_svelte_editor_roundtrip(tmp_path: Path):
    with TestClient(
        create_app(Settings(collection_path=tmp_path / "c.anki2"))
    ) as client:
        assert client.portal is not None
        app = cast(Any, client.app)
        client.portal.call(
            app.state.service.run, lambda col: col.get_preferences()
        )
        payload = {
            "rollover": 4,
            "learn_ahead_mins": 20,
            "new_review_mix": 0,
            "new_timezone": True,
            "day_learn_first": False,
            "hide_audio_play_buttons": False,
            "interrupt_audio_when_answering": True,
            "show_remaining_due_counts": True,
            "show_intervals_on_buttons": True,
            "time_limit_mins": 0,
            "load_balancer_enabled": True,
            "fsrs_short_term_with_steps_enabled": False,
            "adding_defaults_to_current_deck": True,
            "paste_images_as_png": False,
            "paste_strips_formatting": False,
            "default_search_text": "",
            "ignore_accents_in_search": False,
            "render_latex": False,
            "daily": 12,
            "weekly": 10,
            "monthly": 9,
            "minimum_interval_mins": 30,
            "svelte_editor": True,
        }
        r = client.post(
            "/preferences/savePrefs", json=payload, headers={"Datastar-Request": "true"}
        )
        assert r.status_code == 200
        exp = client.portal.call(
            app.state.service.run, lambda col: col.get_config("experimentalFeatures")
        )
        assert exp == {"1": True}

        # Now toggle back to False
        payload["svelte_editor"] = False
        r = client.post(
            "/preferences/savePrefs", json=payload, headers={"Datastar-Request": "true"}
        )
        assert r.status_code == 200
        exp = client.portal.call(
            app.state.service.run, lambda col: col.get_config("experimentalFeatures")
        )
        assert exp == {"1": False}

def test_saveprefs_inverse_checkboxes(tmp_path: Path):
    """legacy_timezone checked => new_timezone False; show_play_buttons unchecked => hide True."""
    with TestClient(
        create_app(Settings(collection_path=tmp_path / "c.anki2"))
    ) as client:
        assert client.portal is not None
        app = cast(Any, client.app)
        base = client.portal.call(
            app.state.service.run, lambda col: col.get_preferences()
        )
        payload = {
            f.name: getattr(base.scheduling, f.name)
            for f in base.scheduling.DESCRIPTOR.fields
        }
        payload.update(
            {
                f.name: getattr(base.reviewing, f.name)
                for f in base.reviewing.DESCRIPTOR.fields
            }
        )
        payload.update(
            {
                f.name: getattr(base.editing, f.name)
                for f in base.editing.DESCRIPTOR.fields
            }
        )
        payload.update(
            {
                f.name: getattr(base.backups, f.name)
                for f in base.backups.DESCRIPTOR.fields
            }
        )
        # the form sends minute-valued keys for these two (not the raw proto seconds):
        payload["learn_ahead_mins"] = base.scheduling.learn_ahead_secs // 60
        payload["time_limit_mins"] = base.reviewing.time_limit_secs // 60
        # the JS would send these (inverted) proto values:
        payload["new_timezone"] = False
        payload["hide_audio_play_buttons"] = True
        r = client.post(
            "/preferences/savePrefs", json=payload, headers={"Datastar-Request": "true"}
        )
        assert r.status_code == 200
        p = client.portal.call(
            app.state.service.run, lambda col: col.get_preferences()
        )
        assert p.scheduling.new_timezone is False
        assert p.reviewing.hide_audio_play_buttons is True


def test_saveprefs_direct_signals(tmp_path: Path):
    """Verify savePrefs succeeds when sending direct frontend signals (including legacy_timezone/show_play_buttons)."""
    with TestClient(
        create_app(Settings(collection_path=tmp_path / "c.anki2"))
    ) as client:
        assert client.portal is not None
        app = cast(Any, client.app)
        signals = {
            "rollover": 5,
            "learn_ahead_mins": 15,
            "new_review_mix": 1,
            "legacy_timezone": True,
            "new_timezone": False,
            "day_learn_first": False,
            "show_play_buttons": False,
            "hide_audio_play_buttons": True,
            "interrupt_audio_when_answering": False,
            "show_remaining_due_counts": False,
            "show_intervals_on_buttons": False,
            "time_limit_mins": 5,
            "load_balancer_enabled": False,
            "fsrs_short_term_with_steps_enabled": True,
            "adding_defaults_to_current_deck": False,
            "paste_images_as_png": True,
            "paste_strips_formatting": True,
            "default_search_text": "tag:test",
            "ignore_accents_in_search": True,
            "render_latex": True,
            "daily": 3,
            "weekly": 2,
            "monthly": 1,
            "minimum_interval_mins": 60,
            "svelte_editor": True,
            "dirty": True,
            "initial": {},
        }
        r = client.post(
            "/preferences/savePrefs", json=signals, headers={"Datastar-Request": "true"}
        )
        assert r.status_code == 200
        p = client.portal.call(
            app.state.service.run, lambda col: col.get_preferences()
        )
        assert p.scheduling.rollover == 5
        assert p.scheduling.new_timezone is False
        assert p.reviewing.hide_audio_play_buttons is True
        assert p.reviewing.fsrs_short_term_with_steps_enabled is True
        assert p.editing.default_search_text == "tag:test"
        assert p.editing.render_latex is True


def test_cancel_navigates(tmp_path: Path):
    with TestClient(
        create_app(Settings(collection_path=tmp_path / "c.anki2"))
    ) as client:
        r = client.post("/preferences/cancel")
        assert r.status_code == 200
        events = parse_datastar_events(r.text)
        assert any("window.location = '/deckbrowser'" in data for _, data in events)
