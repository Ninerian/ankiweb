import pytest
from anki.collection import Collection
from anki.decks import DeckId

from ankiweb.core.app_client.vocab import (
    NOTETYPE_NAME,
    DuplicateNote,
    add_vocab_note,
    ensure_vocab_model,
    escape_field,
    highlight_example,
    read_vocab_note,
    unescape_field,
    update_vocab_note,
)

# Literal copies of DESIGN.md section 5.F: drift in the module fails here.
DESIGN_FRONT = """<div class="av-card av-front">
  <div class="av-front-text">{{Front}}</div>
  {{#Hint}}<div class="av-hint">{{Hint}}</div>{{/Hint}}
</div>"""
DESIGN_BACK = """<div class="av-card av-back">
  <div class="av-front-text">{{Front}}</div>
  {{#Hint}}<div class="av-hint">{{Hint}}</div>{{/Hint}}
  <hr id="answer">
  <div class="av-back-text">{{Back}}</div>
  {{#Example}}<div class="av-example">{{Example}}</div>{{/Example}}
</div>"""


@pytest.fixture
def deck_id(temp_collection: Collection) -> DeckId:
    did = temp_collection.decks.id("Vocab")
    assert did is not None
    ensure_vocab_model(temp_collection)
    return did


def test_model_matches_design_contract(temp_collection: Collection) -> None:
    model = ensure_vocab_model(temp_collection)
    assert model["name"] == NOTETYPE_NAME == "AnkiWeb Vocab"
    assert [f["name"] for f in model["flds"]] == [
        "Front",
        "Back",
        "Hint",
        "Example",
    ]
    assert model["css"] == ""
    assert len(model["tmpls"]) == 1
    template = model["tmpls"][0]
    assert template["name"] == "Card 1"
    assert template["qfmt"] == DESIGN_FRONT
    assert template["afmt"] == DESIGN_BACK
    for text in (template["qfmt"], template["afmt"]):
        assert "<style" not in text
        assert "<script" not in text
        assert "onclick" not in text


def test_ensure_is_idempotent(temp_collection: Collection) -> None:
    first = ensure_vocab_model(temp_collection)
    second = ensure_vocab_model(temp_collection)
    assert first["id"] == second["id"]
    names = [m.name for m in temp_collection.models.all_names_and_ids()]
    assert names.count(NOTETYPE_NAME) == 1


def test_ensure_rejects_foreign_type_with_same_name(
    temp_collection: Collection,
) -> None:
    model = temp_collection.models.new(NOTETYPE_NAME)
    temp_collection.models.add_field(model, temp_collection.models.new_field("Only"))
    template = temp_collection.models.new_template("Card 1")
    template["qfmt"] = "{{Only}}"
    temp_collection.models.add_template(model, template)
    temp_collection.models.add_dict(model)
    with pytest.raises(ValueError, match=NOTETYPE_NAME):
        ensure_vocab_model(temp_collection)


@pytest.mark.parametrize("side", ["qfmt", "afmt"])
def test_ensure_rejects_changed_template(
    temp_collection: Collection, side: str
) -> None:
    model = ensure_vocab_model(temp_collection)
    model["tmpls"][0][side] += "<b>x</b>"
    temp_collection.models.update_dict(model)
    with pytest.raises(ValueError, match="template"):
        ensure_vocab_model(temp_collection)


def test_ensure_rejects_changed_styling(temp_collection: Collection) -> None:
    model = ensure_vocab_model(temp_collection)
    model["css"] = ".av-card { color: red; }"
    temp_collection.models.update_dict(model)
    with pytest.raises(ValueError, match="styling"):
        ensure_vocab_model(temp_collection)


def test_ensure_rejects_reordered_fields(temp_collection: Collection) -> None:
    model = ensure_vocab_model(temp_collection)
    model["flds"][0]["name"], model["flds"][1]["name"] = "Back", "Front"
    temp_collection.models.update_dict(model)
    with pytest.raises(ValueError, match="fields"):
        ensure_vocab_model(temp_collection)


def test_empty_hint_and_example_render_no_elements(
    temp_collection: Collection, deck_id: DeckId
) -> None:
    nid = add_vocab_note(temp_collection, deck_id, "Hund", "dog")
    card = temp_collection.get_note(nid).cards()[0]
    assert "av-hint" not in card.question()
    assert "av-hint" not in card.answer()
    assert "av-example" not in card.answer()
    assert "av-front-text" in card.question()
    assert "av-back-text" in card.answer()


def test_filled_hint_and_example_render_elements(
    temp_collection: Collection, deck_id: DeckId
) -> None:
    nid = add_vocab_note(
        temp_collection, deck_id, "Hund", "dog", "noun", "Der *Hund* bellt."
    )
    card = temp_collection.get_note(nid).cards()[0]
    assert 'class="av-hint">noun<' in card.question()
    assert 'class="av-hint">noun<' in card.answer()
    assert 'class="av-example">Der *Hund* bellt.<' in card.answer()


def test_note_lands_in_deck_with_vocab_type(
    temp_collection: Collection, deck_id: DeckId
) -> None:
    nid = add_vocab_note(temp_collection, deck_id, "Hund", "dog")
    note = temp_collection.get_note(nid)
    model = note.note_type()
    assert model is not None
    assert model["name"] == NOTETYPE_NAME
    assert {card.did for card in note.cards()} == {deck_id}


ROUND_TRIP = "a < b & c\n*x* 😀 <b>&amp;</b>"


def test_escape_round_trip_through_storage(
    temp_collection: Collection, deck_id: DeckId
) -> None:
    nid = add_vocab_note(
        temp_collection, deck_id, ROUND_TRIP, ROUND_TRIP, "h", ROUND_TRIP
    )
    note = temp_collection.get_note(nid)
    assert note["Front"] == "a &lt; b &amp; c<br>*x* 😀 &lt;b&gt;&amp;amp;&lt;/b&gt;"
    assert "*x*" in note["Example"]
    values = read_vocab_note(temp_collection, nid)
    assert values == {
        "front": ROUND_TRIP,
        "back": ROUND_TRIP,
        "hint": "h",
        "example": ROUND_TRIP,
    }


@pytest.mark.parametrize(
    "text",
    [
        "",
        "plain",
        ROUND_TRIP,
        "&lt;",
        "<br>",
        "&lt;br&gt;",
        "line1\r\nline2",
        "a\n\nb\n",
        '"quotes" & <img src=x onerror=alert(1)>',
    ],
)
def test_escape_and_unescape_are_inverse(text: str) -> None:
    assert unescape_field(escape_field(text)) == text.replace("\r\n", "\n")


def test_unescape_does_not_convert_literal_br_to_newline() -> None:
    assert escape_field("<br>\n&") == "&lt;br&gt;<br>&amp;"
    assert unescape_field("&lt;br&gt;<br>&amp;") == "<br>\n&"
    assert escape_field('"quoted"') == '"quoted"'


def test_highlight_wraps_asterisk_word_after_escaping() -> None:
    assert (
        highlight_example(escape_field("Das ist *<b>*"))
        == "Das ist <mark>&lt;b&gt;</mark>"
    )
    assert highlight_example("no marks") == "no marks"
    assert highlight_example("a *b*<br>c *d*") == "a <mark>b</mark><br>c <mark>d</mark>"
    assert highlight_example("**") == "**"
    assert highlight_example(escape_field("*first\nsecond*")) == "*first<br>second*"
    assert highlight_example(escape_field("*<br>*")) == "<mark>&lt;br&gt;</mark>"
    assert highlight_example(escape_field("*<img src=x onerror=alert(1)>*")) == (
        "<mark>&lt;img src=x onerror=alert(1)&gt;</mark>"
    )


@pytest.mark.parametrize(("front", "back"), [(" \n", "x"), ("x", "  "), ("", "")])
def test_blank_front_or_back_is_rejected(
    temp_collection: Collection, deck_id: DeckId, front: str, back: str
) -> None:
    with pytest.raises(ValueError, match="required"):
        add_vocab_note(temp_collection, deck_id, front, back)
    assert temp_collection.find_notes("") == []


def test_duplicate_is_rejected(temp_collection: Collection, deck_id: DeckId) -> None:
    add_vocab_note(temp_collection, deck_id, "Hund", "dog")
    with pytest.raises(DuplicateNote):
        add_vocab_note(temp_collection, deck_id, "Hund", "other")
    assert len(temp_collection.find_notes("")) == 1


def test_duplicate_is_rejected_across_decks(
    temp_collection: Collection, deck_id: DeckId
) -> None:
    add_vocab_note(temp_collection, deck_id, "Hund", "dog")
    other_deck = temp_collection.decks.id("Other")
    assert other_deck is not None
    with pytest.raises(DuplicateNote):
        add_vocab_note(temp_collection, other_deck, "Hund", "hound")
    assert len(temp_collection.find_notes("")) == 1


def test_update_changes_note_without_duplicate_error(
    temp_collection: Collection, deck_id: DeckId
) -> None:
    nid = add_vocab_note(temp_collection, deck_id, "Hund", "dog")
    update_vocab_note(temp_collection, nid, "Hund", "dog")
    update_vocab_note(temp_collection, nid, "Hund", "hound", "noun", "Der *Hund*")
    assert read_vocab_note(temp_collection, nid) == {
        "front": "Hund",
        "back": "hound",
        "hint": "noun",
        "example": "Der *Hund*",
    }
    assert len(temp_collection.find_notes("")) == 1


def test_update_can_change_first_field(
    temp_collection: Collection, deck_id: DeckId
) -> None:
    nid = add_vocab_note(temp_collection, deck_id, "Hund", "dog")
    update_vocab_note(temp_collection, nid, "Katze", "cat")
    assert read_vocab_note(temp_collection, nid)["front"] == "Katze"
    assert len(temp_collection.find_notes("")) == 1


def test_update_round_trip_does_not_double_escape(
    temp_collection: Collection, deck_id: DeckId
) -> None:
    nid = add_vocab_note(temp_collection, deck_id, ROUND_TRIP, ROUND_TRIP)
    update_vocab_note(
        temp_collection, nid, ROUND_TRIP, ROUND_TRIP, ROUND_TRIP, ROUND_TRIP
    )
    note = temp_collection.get_note(nid)
    assert all(
        note[field] == escape_field(ROUND_TRIP)
        for field in ("Front", "Back", "Hint", "Example")
    )
    assert read_vocab_note(temp_collection, nid) == dict.fromkeys(
        ("front", "back", "hint", "example"), ROUND_TRIP
    )


def test_update_rejects_duplicate_of_other_note(
    temp_collection: Collection, deck_id: DeckId
) -> None:
    add_vocab_note(temp_collection, deck_id, "Hund", "dog")
    nid = add_vocab_note(temp_collection, deck_id, "Katze", "cat")
    with pytest.raises(DuplicateNote):
        update_vocab_note(temp_collection, nid, "Hund", "cat")
    assert read_vocab_note(temp_collection, nid)["front"] == "Katze"


def test_update_rejects_existing_duplicate_even_if_front_is_unchanged(
    temp_collection: Collection, deck_id: DeckId
) -> None:
    nid = add_vocab_note(temp_collection, deck_id, "Hund", "dog")
    duplicate = temp_collection.new_note(ensure_vocab_model(temp_collection))
    duplicate["Front"], duplicate["Back"] = "Hund", "other"
    temp_collection.add_note(duplicate, deck_id)
    with pytest.raises(DuplicateNote):
        update_vocab_note(temp_collection, nid, "Hund", "hound")
    assert read_vocab_note(temp_collection, nid)["back"] == "dog"


@pytest.mark.parametrize(("front", "back"), [("  ", "dog"), ("Hund", "\n ")])
def test_update_rejects_blank_required_fields(
    temp_collection: Collection, deck_id: DeckId, front: str, back: str
) -> None:
    nid = add_vocab_note(temp_collection, deck_id, "Hund", "dog")
    with pytest.raises(ValueError, match="required"):
        update_vocab_note(temp_collection, nid, front, back)
    assert read_vocab_note(temp_collection, nid)["front"] == "Hund"
    assert read_vocab_note(temp_collection, nid)["back"] == "dog"


def test_update_and_read_reject_other_note_types(
    temp_collection: Collection, deck_id: DeckId
) -> None:
    basic = temp_collection.models.by_name("Basic")
    assert basic is not None
    note = temp_collection.new_note(basic)
    note["Front"], note["Back"] = "x", "y"
    temp_collection.add_note(note, deck_id)
    with pytest.raises(ValueError, match=NOTETYPE_NAME):
        update_vocab_note(temp_collection, note.id, "a", "b")
    with pytest.raises(ValueError, match=NOTETYPE_NAME):
        read_vocab_note(temp_collection, note.id)
    assert temp_collection.get_note(note.id)["Front"] == "x"


def test_added_card_counts_as_new_in_target_deck(
    temp_collection: Collection, deck_id: DeckId
) -> None:
    add_vocab_note(temp_collection, deck_id, "Hund", "dog")
    add_vocab_note(temp_collection, deck_id, "Katze", "cat")
    tree = temp_collection.sched.deck_due_tree()
    node = next(child for child in tree.children if child.deck_id == deck_id)
    assert node.new_count == 2
