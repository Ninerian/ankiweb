from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ankiweb.adapters.inbound.http_pages.editor_tags import make_router


@pytest.fixture
def test_app():
    mock_service = MagicMock()
    mock_col = MagicMock()

    # Mock complete_tag
    mock_col._backend.complete_tag.return_value = ["tag1", "tag2::child", "test"]
    mock_col.tags.all.return_value = ["tag1", "tag2::child", "test", "another"]

    async def run(fn):
        return fn(mock_col)

    mock_service.run = run
    mock_service.tr = MagicMock()

    app = FastAPI()
    router = make_router(lambda: mock_service)
    app.include_router(router)
    return TestClient(app)


def test_complete_tag_endpoint(test_app):
    resp = test_app.get("/api/tags/complete?input=tag&matchLimit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert "tags" in data
    assert data["tags"] == ["tag1", "tag2::child", "test"]


def test_complete_tag_strips_colons(test_app):
    resp = test_app.get("/api/tags/complete?input=::tag::")
    assert resp.status_code == 200
    data = resp.json()
    assert "tags" in data


def test_all_tags_endpoint(test_app):
    resp = test_app.get("/api/tags/all")
    assert resp.status_code == 200
    data = resp.json()
    assert "tags" in data
    assert len(data["tags"]) == 4


