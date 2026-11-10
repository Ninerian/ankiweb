"""Exercise the links rendered by the app's deck, review, add and offline pages."""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit

import pytest
from anki.collection import Collection
from conftest import parse_datastar_events
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response


@dataclass
class _Anchor:
    href: str
    attributes: dict[str, str | None]
    ancestors: tuple[str, ...]
    parts: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join("".join(self.parts).split())


class _Anchors(HTMLParser):
    _void = frozenset(
        {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }
    )

    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[_Anchor] = []
        self.stack: list[tuple[str, str | None]] = []
        self.active: _Anchor | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        href = attributes.get("href")
        if tag == "a" and href is not None:
            self.active = _Anchor(
                href=href,
                attributes=attributes,
                ancestors=tuple(
                    element_id for _, element_id in self.stack if element_id
                ),
            )
            self.anchors.append(self.active)
        if tag not in self._void:
            self.stack.append((tag, attributes.get("id")))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self._void:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.active = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if self.active is not None:
            self.active.parts.append(data)


def _anchors(html: str) -> list[_Anchor]:
    parser = _Anchors()
    parser.feed(html)
    parser.close()
    return parser.anchors


def _link(
    anchors: list[_Anchor],
    *,
    text: str | None = None,
    element_id: str | None = None,
    ancestor: str | None = None,
    aria_label: str | None = None,
) -> _Anchor:
    matches = [
        anchor
        for anchor in anchors
        if (text is None or anchor.text == text)
        and (element_id is None or anchor.attributes.get("id") == element_id)
        and (ancestor is None or ancestor in anchor.ancestors)
        and (aria_label is None or anchor.attributes.get("aria-label") == aria_label)
    ]
    assert len(matches) == 1, (text, element_id, ancestor, aria_label, matches)
    return matches[0]


def _follow(client: TestClient, source: str, href: str) -> Response:
    origin = urlsplit(str(client.base_url))
    target = urldefrag(urljoin(urljoin(str(client.base_url), source), href)).url
    for _ in range(10):
        parts = urlsplit(target)
        assert (parts.scheme, parts.netloc) == (origin.scheme, origin.netloc), target
        response = client.get(target, follow_redirects=False)
        if response.status_code == 200:
            return response
        assert response.status_code in (301, 302, 303, 307, 308), (
            target,
            response.status_code,
        )
        assert "location" in response.headers, target
        target = urldefrag(urljoin(target, response.headers["location"])).url
    raise AssertionError(f"Too many redirects following {href!r} from {source!r}")


def _crawl(client: TestClient, source: str, anchors: list[_Anchor]) -> None:
    origin = urlsplit(str(client.base_url))
    base = urljoin(str(client.base_url), source)
    for anchor in anchors:
        target = urlsplit(urljoin(base, anchor.href))
        if (target.scheme, target.netloc) == (origin.scheme, origin.netloc):
            _follow(client, source, anchor.href)


def _assert_target(
    client: TestClient, source: str, anchor: _Anchor, target: str
) -> None:
    response = _follow(client, source, anchor.href)
    assert str(response.url) == urljoin(str(client.base_url), target)


def _summary_links(client: TestClient, deck_id: int, editor: Response) -> list[_Anchor]:
    token = re.search(r'data-instance="([0-9a-f]{16})"', editor.text)
    assert token is not None
    done = client.post(
        f"/app/edit/{deck_id}/{token.group(1)}/0/done",
        data={"front": "", "back": "", "hint": "", "example": "", "nid": "0"},
    )
    assert done.status_code == 200
    fragments = [
        "\n".join(
            line.removeprefix("elements ")
            for line in data.splitlines()
            if line.startswith("elements ")
        )
        for event_type, data in parse_datastar_events(done.text)
        if event_type == "datastar-patch-elements"
    ]
    dialogs = [fragment for fragment in fragments if 'id="add-summary"' in fragment]
    assert len(dialogs) == 1
    return _anchors(dialogs[0])


@pytest.fixture
def link_decks(client: TestClient) -> list[tuple[int, int]]:
    def seed(col: Collection) -> list[tuple[int, int]]:
        model = col.models.by_name("Basic")
        assert model is not None
        decks = []
        for name in ("Link matrix A", "Link matrix B"):
            deck_id = col.decks.id(name)
            assert deck_id is not None
            note = col.new_note(model)
            note["Front"] = f"Question in {name}"
            note["Back"] = f"Answer in {name}"
            col.add_note(note, deck_id)
            decks.append((int(deck_id), int(note.cards()[0].id)))
        return decks

    assert client.portal is not None
    assert isinstance(client.app, FastAPI)
    return client.portal.call(client.app.state.service.run, seed)


def test_rendered_app_link_matrix(
    client: TestClient, link_decks: list[tuple[int, int]]
) -> None:
    decks_page = client.get("/app/")
    assert decks_page.status_code == 200
    decks_links = _anchors(decks_page.text)
    _crawl(client, "/app/", decks_links)

    for deck_id, _ in link_decks:
        row = f"deck-{deck_id}"
        learn = _link(decks_links, text="Learn", ancestor=row)
        add = _link(decks_links, text="Edit", ancestor=row)
        review_url = f"/app/review?deck={deck_id}"
        add_url = f"/app/edit/{deck_id}/front"
        _assert_target(client, "/app/", learn, review_url)
        _assert_target(client, "/app/", add, add_url)

        review = _follow(client, "/app/", learn.href)
        review_links = _anchors(review.text)
        _assert_target(
            client, review_url, _link(review_links, element_id="btn-back"), "/app/"
        )
        _crawl(client, review_url, review_links)

        add_page = _follow(client, "/app/", add.href)
        add_links = _anchors(add_page.text)
        _assert_target(
            client, add_url, _link(add_links, aria_label="Exit Creator"), "/app/"
        )
        _assert_target(
            client, add_url, _link(add_links, element_id="deck-chip"), "/app/"
        )
        summary_links = _summary_links(client, deck_id, add_page)
        _assert_target(
            client,
            add_url,
            _link(summary_links, text="Back to decks", ancestor="add-summary"),
            "/app/",
        )
        _assert_target(
            client,
            add_url,
            _link(summary_links, text="Start studying", ancestor="add-summary"),
            review_url,
        )
        _crawl(client, add_url, add_links)
        _crawl(client, add_url, summary_links)

    offline = client.get("/app/offline")
    assert offline.status_code == 200
    offline_links = _anchors(offline.text)
    _assert_target(
        client, "/app/offline", _link(offline_links, text="Try again"), "/app/"
    )
    _crawl(client, "/app/offline", offline_links)


def test_review_completion_back_link(
    client: TestClient, link_decks: list[tuple[int, int]]
) -> None:
    deck_id, card_id = link_decks[0]
    review_url = f"/app/review?deck={deck_id}"
    assert client.get(review_url).status_code == 200
    completed = client.post(
        "/app/review/answer",
        json={"cardId": card_id, "ease": 4},
        headers={"Datastar-Request": "true"},
    )
    assert completed.status_code == 200
    fragments = []
    for event_type, data in parse_datastar_events(completed.text):
        if event_type == "datastar-patch-elements":
            fragments.append(
                "\n".join(
                    line.removeprefix("elements ")
                    for line in data.splitlines()
                    if line.startswith("elements ")
                )
            )
    links = _anchors("\n".join(fragments))
    back = _link(links, text="Back to decks", ancestor="session-complete")
    _assert_target(client, review_url, back, "/app/")
    _crawl(client, review_url, links)

    empty = client.get(review_url)
    assert empty.status_code == 200
    empty_links = _anchors(empty.text)
    _assert_target(
        client, review_url, _link(empty_links, text="Back to decks"), "/app/"
    )
    _crawl(client, review_url, empty_links)


def test_add_summary_study_link_after_commit(
    client: TestClient, link_decks: list[tuple[int, int]]
) -> None:
    deck_id, _ = link_decks[0]
    add_url = f"/app/edit/{deck_id}/front"
    editor = client.get(add_url)
    assert editor.status_code == 200
    token = re.search(r'data-instance="([0-9a-f]{16})"', editor.text)
    assert token is not None
    added = client.post(
        f"/app/edit/{deck_id}/{token.group(1)}/0/commit",
        data={
            "front": "A new word",
            "back": "A new meaning",
            "hint": "",
            "example": "",
            "nid": "0",
        },
    )
    assert added.status_code == 200
    assert re.search(r'id="summary-count"[^>]*>1</span>', added.text)
    page = client.get(add_url)
    assert page.status_code == 200
    links = _summary_links(client, deck_id, page)
    study = _link(links, text="Start studying", ancestor="add-summary")
    _assert_target(client, add_url, study, f"/app/review?deck={deck_id}")
    _crawl(client, add_url, links)
