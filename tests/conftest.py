from __future__ import annotations
import pytest
from pathlib import Path
from anki.collection import Collection


@pytest.fixture(autouse=True)
def _default_english_lang():
    """Reset the process-global UI language to English before each test so default-English
    assertions are order-independent (set_lang is process-global and sticky, and it keeps
    anki.lang.current_i18n in sync with tr_legacyglobal's backend). Tests that need another
    locale call anki.lang.set_lang(...) in their own body."""
    import anki.lang

    anki.lang.set_lang("en")
    yield


@pytest.fixture
def temp_collection(tmp_path: Path):
    col = Collection(str(tmp_path / "collection.anki2"))
    yield col
    col.close()


def parse_datastar_events(text: str) -> list[tuple[str | None, str]]:
    """Parse a DatastarResponse SSE body into (event-type, joined-data-lines) pairs."""
    events = []
    for block in text.replace("\r\n", "\n").strip("\n").split("\n\n"):
        if not block.strip():
            continue
        etype, data = None, []
        for line in block.splitlines():
            if line.startswith("event: "):
                etype = line[len("event: ") :]
            elif line.startswith("data: "):
                data.append(line[len("data: ") :])
        events.append((etype, "\n".join(data)))
    return events


def wait_for_body_text_length(page, min_len: int, timeout: float = 10.0) -> None:
    """Poll page.inner_text('body') (native CDP text extraction, no page-side eval) until it
    exceeds min_len chars. Avoids page.wait_for_function's string predicate, which compiles via
    eval() in the page's JS realm and violates the CSP the vendored SvelteKit bundle now ships
    (script-src 'self' '<hash>', no 'unsafe-eval')."""
    import time

    deadline = time.monotonic() + timeout
    while True:
        if len(page.inner_text("body")) > min_len:
            return
        if time.monotonic() > deadline:
            raise TimeoutError(f"body text did not exceed {min_len} chars within {timeout}s")
        time.sleep(0.1)
