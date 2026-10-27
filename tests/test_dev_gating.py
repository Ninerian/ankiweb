from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ankiweb.app import create_app
from ankiweb.core.config import Settings


@pytest.fixture
def shell_dir(tmp_path: Path) -> Path:
    shell = tmp_path / "shell"
    (shell / "static").mkdir(parents=True)
    (shell / "dev-static").mkdir()
    (shell / "static" / "app.css").write_text("/* public css */", encoding="utf-8")
    (shell / "dev-static" / "gallery.css").write_text(
        "/* dev gallery css */", encoding="utf-8"
    )
    return shell


def test_dev_routes_404_by_default(tmp_path):
    # Default settings has dev=False
    settings = Settings(collection_path=tmp_path / "c.anki2")
    assert not settings.dev
    with TestClient(create_app(settings)) as client:
        r1 = client.get("/dev/components")
        assert r1.status_code == 404
        r2 = client.get("/dev/progress/sample")
        assert r2.status_code == 404


def test_dev_routes_work_when_enabled(tmp_path):
    settings = Settings(collection_path=tmp_path / "c.anki2", dev=True)
    assert settings.dev
    with TestClient(create_app(settings)) as client:
        r1 = client.get("/dev/components")
        assert r1.status_code == 200
        assert "component-gallery" in r1.text


def test_stale_dev_css_is_not_public_in_production(tmp_path: Path, shell_dir: Path):
    settings = Settings(collection_path=tmp_path / "c.anki2", shell_dir=shell_dir)
    with TestClient(create_app(settings)) as client:
        public = client.get("/shell/static/app.css")
        assert public.status_code == 200
        assert public.text == "/* public css */"

        for path in ("/dev/static/gallery.css", "/shell/static/dev-static/gallery.css"):
            response = client.get(path)
            assert response.status_code == 404
            assert "/* dev gallery css */" not in response.text

        normal = client.get("/notify")
        assert normal.status_code == 200
        assert "/dev/static/gallery.css" not in normal.text


def test_dev_css_is_only_served_from_dev_mount_and_linked_in_gallery(
    tmp_path: Path, shell_dir: Path
):
    settings = Settings(
        collection_path=tmp_path / "c.anki2", shell_dir=shell_dir, dev=True
    )
    with TestClient(create_app(settings)) as client:
        public = client.get("/shell/static/app.css")
        assert public.status_code == 200
        assert public.text == "/* public css */"

        dev_css = client.get("/dev/static/gallery.css")
        assert dev_css.status_code == 200
        assert dev_css.text == "/* dev gallery css */"
        nested = client.get("/shell/static/dev-static/gallery.css")
        assert nested.status_code == 404
        assert "/* dev gallery css */" not in nested.text

        gallery = client.get("/dev/components")
        assert gallery.status_code == 200
        assert '<link rel="stylesheet" href="/dev/static/gallery.css">' in gallery.text

        normal = client.get("/notify")
        assert normal.status_code == 200
        assert "/dev/static/gallery.css" not in normal.text


def test_dev_app_starts_without_built_dev_css(tmp_path: Path):
    shell = tmp_path / "shell"
    settings = Settings(collection_path=tmp_path / "c.anki2", shell_dir=shell, dev=True)
    with TestClient(create_app(settings)) as client:
        assert not (shell / "dev-static").exists()
        assert client.get("/dev/components").status_code == 200
