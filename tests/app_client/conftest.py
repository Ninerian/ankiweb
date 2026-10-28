import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn
from anki.collection import Collection
from fastapi.testclient import TestClient

from ankiweb.app import create_app
from ankiweb.core.config import Settings


@pytest.fixture
def col_with_vocab(tmp_path: Path) -> Iterator[Collection]:
    col = Collection(str(tmp_path / "vocab.anki2"))
    try:
        deck_id = col.decks.id("German B1 Vocab")
        model = col.models.by_name("Basic")
        assert deck_id is not None
        assert model is not None
        for front, back in (
            ("Hund", "dog"),
            ("Katze", "cat"),
            ("Haus", "house"),
            ("Buch", "book"),
        ):
            note = col.new_note(model)
            note["Front"] = front
            note["Back"] = back
            col.add_note(note, deck_id)
        yield col
    finally:
        col.close()


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(collection_path=tmp_path / "client.anki2")
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def live_app(tmp_path: Path) -> Iterator[str]:
    settings = Settings(collection_path=tmp_path / "live.anki2")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(create_app(settings), log_level="warning")
        )
        thread = threading.Thread(
            target=server.run, kwargs={"sockets": [listener]}, daemon=True
        )
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("server did not start")
                time.sleep(0.05)
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError("server did not stop")
