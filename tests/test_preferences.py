import anki.lang
from pathlib import Path
from fastapi.testclient import TestClient
from ankiweb.core.config import Settings
from ankiweb.app import create_app
from ankiweb.adapters.inbound.http_datastar.preferences import render_preferences_html
from conftest import parse_datastar_events


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
        base = client.portal.call(
            client.app.state.service.run, lambda col: col.get_preferences()
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
            client.app.state.service.run, lambda col: col.get_preferences()
        )
        assert p.scheduling.rollover == 6
        assert p.scheduling.learn_ahead_secs == 20 * 60  # form minutes -> proto seconds
        assert p.reviewing.time_limit_secs == 3 * 60
        assert p.scheduling.new_review_mix == 2
        assert p.scheduling.day_learn_first is True
        assert p.editing.default_search_text == "deck:current"
        assert p.backups.minimum_interval_mins == 45


def test_saveprefs_inverse_checkboxes(tmp_path: Path):
    """legacy_timezone checked => new_timezone False; show_play_buttons unchecked => hide True."""
    with TestClient(
        create_app(Settings(collection_path=tmp_path / "c.anki2"))
    ) as client:
        base = client.portal.call(
            client.app.state.service.run, lambda col: col.get_preferences()
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
            client.app.state.service.run, lambda col: col.get_preferences()
        )
        assert p.scheduling.new_timezone is False
        assert p.reviewing.hide_audio_play_buttons is True


def test_cancel_navigates(tmp_path: Path):
    with TestClient(
        create_app(Settings(collection_path=tmp_path / "c.anki2"))
    ) as client:
        r = client.post("/preferences/cancel")
        assert r.status_code == 200
        events = parse_datastar_events(r.text)
        assert any("window.location = '/deckbrowser'" in data for _, data in events)
