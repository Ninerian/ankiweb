"""Application-specific translations not available in Anki's catalog."""

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # Deck list (plan 2)
        "app_decks_study_space": "Your study space",
        "app_decks_my_decks": "My Decks",
        "app_decks_search": "Search decks",
        "app_decks_your_decks": "Your decks",
        "app_decks_progress": "Study progress",
        "app_decks_progress_for": "{deck} study progress",
        "app_decks_no_results": "No decks found",
        "app_decks_try_search": "Try a different search.",
        "app_decks_add_first": "Add your first deck",
        "app_decks_edit_add": "Edit / Add",
        "app_decks_learn_deck": "Learn {deck}",
        # Review (plan 3)
        "app_review_streak": "Streak",
        "app_review_streak_title": "Study streak (cards mastered in a row)",
        "app_review_streak_reset": "Streak Reset! Don't give up 💪",
        "app_review_streak_increase": "Streak +1! ({count} in a row 🎯)",
        "app_review_progress": "Session Progress",
        "app_review_more_actions": "More actions",
        "app_review_card_actions": "Card Actions",
        "app_review_other_note_type": "Other note type",
        "app_review_no_cards_due": "No cards due",
        "app_review_unmark_card": "Unmark Card",
        "app_review_remove_flag": "Remove Flag",
        "app_review_marked": "Card Marked ⭐",
        "app_review_unmarked": "Card Unmarked",
        "app_review_flagged": "Flagged Card 🚩",
        "app_review_flag_removed": "Flag Removed",
        "app_review_buried": "Card Buried for Today 📦",
        "app_review_suspended": "Card Suspended ⏸️",
        "app_review_note_deleted": "Note Deleted 🗑️",
        # Session completion (plan 3)
        "app_review_complete_session": "Session complete",
        "app_review_complete_statistics": "Session statistics",
        "app_review_complete_reviewed": "Reviewed",
        "app_review_complete_recall": "Recall",
        "app_review_complete_streak": "Current streak",
        "app_review_complete_ratings": "Your ratings",
        "app_review_complete_recall_note": (
            "Recall = Hard, Good, or Easy ratings; not measured accuracy."
        ),
        "app_review_complete_perfect_title": "Flawless!",
        "app_review_complete_perfect_subtitle": (
            "What a run! You made those cards look easy."
        ),
        "app_review_complete_great_title": "Great run!",
        "app_review_complete_great_subtitle": "Look at that momentum. Keep it rolling!",
        "app_review_complete_good_title": "Solid progress.",
        "app_review_complete_good_subtitle": "Every review helps those ideas take root.",
        "app_review_complete_tough_title": "You showed up.",
        "app_review_complete_tough_subtitle": (
            "You gave your memory a workout today. That counts."
        ),
        "app_review_complete_hard_extra": "Plenty of those cards took extra effort.",
        "app_review_complete_back_to_decks": "Back to decks",
        "app_review_complete_study_again": "Study again",
        # Add cards (plan 4)
        "app_add_cards_added": "Cards added",
        "app_add_exit": "Exit Creator",
        "app_add_edit_last": "Edit last added card",
        "app_add_front_prompt": "Front (Question / Prompt)",
        "app_add_front_help": "What will you test?",
        "app_add_back_prompt": "Back (Answer / Meaning)",
        "app_add_back_help": "The correct answer",
        "app_add_hint": "Hint",
        "app_add_example": "Example sentence",
        "app_add_characters": "characters",
        "app_add_optional": "Optional",
        "app_add_example_help": "Wrap the key word in *asterisks* to highlight it.",
        "app_add_front_placeholder": "e.g. die Herausforderung",
        "app_add_back_placeholder": "e.g. the challenge",
        "app_add_hint_placeholder": "e.g. noun, feminine",
        "app_add_example_placeholder": "e.g. Das ist eine *Herausforderung*.",
        "app_add_card_preview": "Card Preview",
        "app_add_ready_to_add": "Ready to add?",
        "app_add_front_preview": "Front Prompt",
        "app_add_back_preview": "Back Answer",
        "app_add_edit_preview": "Edit text before adding",
        "app_add_no_cards": "No cards added yet",
        "app_add_first_card": "Add your first card above!",
        "app_add_top_card": "Top card",
        "app_add_next_back": "Next: Back →",
        "app_add_next_preview": "Next: Preview →",
        "app_add_previous_step": "Previous Step",
        "app_add_front_required": "Front cannot be empty!",
        "app_add_back_required": "Back cannot be empty!",
        "app_add_both_required": "Front and back are required",
        "app_add_editing": "Editing…",
        "app_add_card_first": "Add a card first.",
        "app_add_cards_ready": "Cards Ready!",
        "app_add_keep_adding": "Keep adding more cards",
        "app_add_start_studying": "Start studying",
        "app_add_discard_leave": (
            "You have unsaved text in your current card. Discard it and leave?"
        ),
        "app_add_discard_finish": (
            "You have unsaved text in your current card. Discard it and finish?"
        ),
        "app_add_discard_edit": (
            "You have unsaved text in your current card. Discard it and edit the card?"
        ),
    },
    "de": {
        "app_decks_study_space": "Dein Lernbereich",
        "app_decks_my_decks": "Meine Stapel",
        "app_decks_search": "Stapel suchen",
        "app_decks_your_decks": "Deine Stapel",
        "app_decks_progress": "Lernfortschritt",
        "app_decks_progress_for": "Lernfortschritt für {deck}",
        "app_decks_no_results": "Keine Stapel gefunden",
        "app_decks_try_search": "Versuche einen anderen Suchbegriff.",
        "app_decks_add_first": "Füge deinen ersten Stapel hinzu",
        "app_decks_edit_add": "Bearbeiten / Hinzufügen",
        "app_decks_learn_deck": "{deck} lernen",
        "app_review_streak": "Serie",
        "app_review_streak_title": "Lernserie (Karten in Folge gemeistert)",
        "app_review_streak_reset": "Serie zurückgesetzt! Gib nicht auf 💪",
        "app_review_streak_increase": "Serie +1! ({count} in Folge 🎯)",
        "app_review_progress": "Sitzungsfortschritt",
        "app_review_more_actions": "Weitere Aktionen",
        "app_review_card_actions": "Kartenaktionen",
        "app_review_other_note_type": "Anderer Notiztyp",
        "app_review_no_cards_due": "Keine Karten fällig",
        "app_review_unmark_card": "Markierung der Karte entfernen",
        "app_review_remove_flag": "Flagge entfernen",
        "app_review_marked": "Karte markiert ⭐",
        "app_review_unmarked": "Markierung entfernt",
        "app_review_flagged": "Karte mit Flagge versehen 🚩",
        "app_review_flag_removed": "Flagge entfernt",
        "app_review_buried": "Karte für heute zurückgestellt 📦",
        "app_review_suspended": "Karte dauerhaft ausgeschlossen ⏸️",
        "app_review_note_deleted": "Notiz gelöscht 🗑️",
        "app_review_complete_session": "Sitzung abgeschlossen",
        "app_review_complete_statistics": "Sitzungsstatistik",
        "app_review_complete_reviewed": "Wiederholt",
        "app_review_complete_recall": "Abrufrate",
        "app_review_complete_streak": "Aktuelle Serie",
        "app_review_complete_ratings": "Deine Bewertungen",
        "app_review_complete_recall_note": (
            "Abrufrate = Bewertungen Schwer, Gut oder Einfach; keine gemessene Genauigkeit."
        ),
        "app_review_complete_perfect_title": "Makellos!",
        "app_review_complete_perfect_subtitle": (
            "Was für eine Serie! Diese Karten waren für dich ein Kinderspiel."
        ),
        "app_review_complete_great_title": "Starke Leistung!",
        "app_review_complete_great_subtitle": "Du bist in Schwung. Mach weiter so!",
        "app_review_complete_good_title": "Guter Fortschritt.",
        "app_review_complete_good_subtitle": "Jede Wiederholung festigt dein Wissen.",
        "app_review_complete_tough_title": "Du hast durchgehalten.",
        "app_review_complete_tough_subtitle": (
            "Du hast dein Gedächtnis heute trainiert. Das zählt."
        ),
        "app_review_complete_hard_extra": "Viele dieser Karten waren besonders schwer.",
        "app_review_complete_back_to_decks": "Zurück zu den Stapeln",
        "app_review_complete_study_again": "Erneut lernen",
        "app_add_cards_added": "Hinzugefügte Karten",
        "app_add_exit": "Kartenerstellung verlassen",
        "app_add_edit_last": "Zuletzt hinzugefügte Karte bearbeiten",
        "app_add_front_prompt": "Vorderseite (Frage / Stichwort)",
        "app_add_front_help": "Was möchtest du abfragen?",
        "app_add_back_prompt": "Rückseite (Antwort / Bedeutung)",
        "app_add_back_help": "Die richtige Antwort",
        "app_add_hint": "Hinweis",
        "app_add_example": "Beispielsatz",
        "app_add_characters": "Zeichen",
        "app_add_optional": "Optional",
        "app_add_example_help": (
            "Setze das Schlüsselwort zur Hervorhebung zwischen *Sternchen*."
        ),
        "app_add_front_placeholder": "z. B. die Herausforderung",
        "app_add_back_placeholder": "z. B. the challenge",
        "app_add_hint_placeholder": "z. B. Substantiv, feminin",
        "app_add_example_placeholder": "z. B. Das ist eine *Herausforderung*.",
        "app_add_card_preview": "Kartenvorschau",
        "app_add_ready_to_add": "Bereit zum Hinzufügen?",
        "app_add_front_preview": "Vorderseite: Frage",
        "app_add_back_preview": "Rückseite: Antwort",
        "app_add_edit_preview": "Text vor dem Hinzufügen bearbeiten",
        "app_add_no_cards": "Noch keine Karten hinzugefügt",
        "app_add_first_card": "Füge oben deine erste Karte hinzu!",
        "app_add_top_card": "Oberste Karte",
        "app_add_next_back": "Weiter: Rückseite →",
        "app_add_next_preview": "Weiter: Vorschau →",
        "app_add_previous_step": "Vorheriger Schritt",
        "app_add_front_required": "Die Vorderseite darf nicht leer sein!",
        "app_add_back_required": "Die Rückseite darf nicht leer sein!",
        "app_add_both_required": "Vorder- und Rückseite sind erforderlich",
        "app_add_editing": "Wird bearbeitet…",
        "app_add_card_first": "Füge zuerst eine Karte hinzu.",
        "app_add_cards_ready": "Karten bereit!",
        "app_add_keep_adding": "Weitere Karten hinzufügen",
        "app_add_discard_leave": (
            "Die aktuelle Karte enthält ungespeicherten Text. Verwerfen und verlassen?"
        ),
        "app_add_discard_finish": (
            "Die aktuelle Karte enthält ungespeicherten Text. Verwerfen und abschließen?"
        ),
        "app_add_discard_edit": (
            "Die aktuelle Karte enthält ungespeicherten Text. "
            "Verwerfen und die Karte bearbeiten?"
        ),
        "app_add_start_studying": "Lernen beginnen",
    },
}


def s(key: str, *, lang: str, **fmt: object) -> str:
    """Look up a string in the selected catalog, falling back to English."""
    text = STRINGS.get(lang, {}).get(key)
    if text is None:
        text = STRINGS["en"][key]
    return text.format(**fmt)
