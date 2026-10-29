import html
import re

import pytest
from anki.collection import Collection
from anki.decks import DeckId
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    ("stored", "emoji", "name"),
    [
        ("Biologie · 🧬", "🧬", "Biologie"),
        ("Mathematik", "🗂️", "Mathematik"),
        ("<b>x</b> · 🧬", "🧬", "<b>x</b>"),
        ('It\'s "biology" · 🧬', "🧬", 'It\'s "biology"'),
        ("🇩🇪 German", "🗂️", "🇩🇪 German"),
    ],
)
def test_review_and_add_show_the_same_deck_display(
    client: TestClient, stored: str, emoji: str, name: str
) -> None:
    def seed(col: Collection) -> tuple[int, int]:
        deck_id = col.decks.id(stored)
        model = col.models.by_name("Basic")
        assert deck_id is not None and model is not None
        note = col.new_note(model)
        note["Front"] = "Question"
        note["Back"] = "Answer"
        col.add_note(note, deck_id)
        return int(deck_id), int(note.cards()[0].id)

    assert client.portal is not None
    service = client.app.state.service
    deck_id, card_id = client.portal.call(service.run, seed)

    review = client.get("/app/review", params={"deck": deck_id})
    add = client.get("/app/add", params={"deck": deck_id})
    assert review.status_code == add.status_code == 200

    def display(markup: str, element_id: str) -> tuple[str, str]:
        match = re.search(
            rf'id="{element_id}"[^>]*><span[^>]*>(.*?)</span> <span[^>]*>(.*?)</span>',
            markup,
        )
        assert match is not None
        rendered_emoji, rendered_name = match.groups()
        assert "<" not in rendered_name
        return html.unescape(rendered_emoji), html.unescape(rendered_name)

    assert display(review.text, "card-deck") == (emoji, name)
    assert display(add.text, "deck-chip") == (emoji, name)
    if "<" in name:
        assert "&lt;b&gt;x&lt;/b&gt;" in review.text
        assert "&lt;b&gt;x&lt;/b&gt;" in add.text
    if "'" in name:
        assert "&#39;" in review.text and "&#34;" in review.text
        assert "&#39;" in add.text and "&#34;" in add.text

    marked = client.post(
        "/app/review/action/mark",
        json={"cardId": card_id},
        headers={"Datastar-Request": "true"},
    )
    assert marked.status_code == 200
    assert display(marked.text, "card-deck") == (emoji, name)
    assert (
        client.portal.call(service.run, lambda col: col.decks.name(DeckId(deck_id)))
        == stored
    )


def test_review_header_of_subdeck_card_uses_root_emoji(client: TestClient) -> None:
    def seed(col: Collection) -> int:
        root_id = col.decks.id("Biologie · 🧬")
        child_id = col.decks.id("Biologie · 🧬::Zellen")
        model = col.models.by_name("Basic")
        assert root_id is not None and child_id is not None and model is not None
        note = col.new_note(model)
        note["Front"] = "Question"
        note["Back"] = "Answer"
        col.add_note(note, child_id)
        return int(root_id)

    assert client.portal is not None
    service = client.app.state.service
    root_id = client.portal.call(service.run, seed)

    review = client.get("/app/review", params={"deck": root_id})
    assert review.status_code == 200
    match = re.search(
        r'id="card-deck"[^>]*><span>(.*?)</span> <span>(.*?)</span>', review.text
    )
    assert match is not None
    assert (html.unescape(match[1]), html.unescape(match[2])) == (
        "🧬",
        "Biologie::Zellen",
    )
