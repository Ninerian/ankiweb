from typing import cast

from anki.collection import Collection
from anki.scheduler.v3 import Scheduler

from ankiweb.core.app_client.study import VOCAB_NOTETYPE


def test_mixed_note_types_follow_anki_daily_limit(client):
    def seed(col: Collection):
        deck = col.decks.id("Mixed daily limit")
        basic = col.models.by_name("Basic")
        assert deck is not None and basic is not None
        basic_ids = []
        for number in range(200):
            note = col.new_note(basic)
            note["Front"], note["Back"] = f"Basic {number}", "Basic answer"
            col.add_note(note, deck)
            basic_ids.append(note.cards()[0].id)
        vocab_type = col.models.copy(basic, add=False)
        vocab_type["name"] = VOCAB_NOTETYPE
        col.models.add_dict(vocab_type)
        vocab_type = col.models.by_name(VOCAB_NOTETYPE)
        assert vocab_type is not None
        note = col.new_note(vocab_type)
        note["Front"], note["Back"] = "Vocabulary", "Vocabulary answer"
        col.add_note(note, deck)
        vocab_id = note.cards()[0].id
        col.decks.set_current(deck)
        queued = cast(Scheduler, col.sched).get_queued_cards(fetch_limit=100)
        return int(deck), set(basic_ids), vocab_id, queued

    assert client.portal is not None
    deck, basic_ids, vocab_id, queue = client.portal.call(
        client.app.state.service.run, seed
    )
    queued_ids = {card.card.id for card in queue.cards}
    assert queue.new_count == len(queued_ids) == 20
    assert queued_ids <= basic_ids and vocab_id not in queued_ids

    response = client.get("/app/review", params={"deck": deck})
    assert response.status_code == 200
    assert "Other note type" in response.text
    assert 'id="progress-text">0 / 20<' in response.text
    assert "Basic " in response.text
    assert "Vocabulary answer" not in response.text
