"""Cross-site writes to /app POST routes must be rejected before they touch the collection."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ankiweb.app import create_app
from ankiweb.core.config import Settings

_JSON = {"Content-Type": "application/json"}
_BODY = {"front": "probe", "back": "b", "hint": "", "example": "", "step": 3, "nid": 0}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(Settings(collection_path=tmp_path / "c.anki2"))) as c:
        yield c


def _deck_and_notes(client: TestClient):
    assert client.portal is not None
    service = cast(FastAPI, client.app).state.service
    deck_id = client.portal.call(service.run, lambda col: col.decks.id("Origin deck"))
    assert deck_id is not None
    assert client.get(f"/app/add?deck={deck_id}").status_code == 200

    def notes() -> int:
        assert client.portal is not None
        return client.portal.call(service.run, lambda col: len(col.find_notes("")))

    return deck_id, notes


def _commit(client: TestClient, deck_id: int, headers: dict[str, str]):
    return client.post(
        f"/app/add/commit?deck={deck_id}", content=json.dumps(_BODY), headers=headers
    )


@pytest.mark.parametrize(
    "headers",
    [
        {**_JSON, "Origin": "https://evil.example"},
        {"Content-Type": "text/plain", "Origin": "https://evil.example"},
        {**_JSON, "Sec-Fetch-Site": "cross-site"},
        {**_JSON, "Sec-Fetch-Site": "same-site"},
        {**_JSON, "Origin": "null"},
    ],
    ids=[
        "foreign-origin",
        "text-plain-form",
        "cross-site",
        "same-site-sibling",
        "null-origin",
    ],
)
def test_cross_site_post_is_rejected_and_writes_nothing(
    client: TestClient, headers: dict[str, str]
) -> None:
    deck_id, notes = _deck_and_notes(client)

    response = _commit(client, deck_id, headers)

    assert response.status_code == 403
    assert notes() == 0


@pytest.mark.parametrize(
    "headers",
    [
        _JSON,
        {**_JSON, "Sec-Fetch-Site": "same-origin"},
        {**_JSON, "Origin": "http://testserver"},
    ],
    ids=["no-fetch-metadata", "same-origin-fetch", "matching-origin"],
)
def test_same_origin_and_non_browser_posts_still_write(
    client: TestClient, headers: dict[str, str]
) -> None:
    deck_id, notes = _deck_and_notes(client)

    response = _commit(client, deck_id, headers)

    assert response.status_code == 200
    assert notes() == 1


def test_get_is_never_blocked_by_the_origin_check(client: TestClient) -> None:
    response = client.get(
        "/app/",
        headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"},
    )

    assert response.status_code == 200
