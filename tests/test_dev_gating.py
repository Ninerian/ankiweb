from fastapi.testclient import TestClient
from ankiweb.core.config import Settings
from ankiweb.app import create_app


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
