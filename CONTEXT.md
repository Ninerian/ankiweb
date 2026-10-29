# AnkiWeb Mobile Client

Eigenstaendiger, mobiler Lern-Client unter `/app/*` neben dem bestehenden Web-Client. Deckt Stapelliste, Review und Karten hinzufuegen ab; Verwaltung (Browser, Graphs, Deck-Optionen, Import) bleibt im bestehenden Client.

## Language

**Deck**:
Ein Anki-Stapel, der Karten gruppiert und zum Lernen gewaehlt wird. UI-Name auf Deutsch: "Stapel".
_Avoid_: Stack, Ordner

**Deck-Liste**:
Die Startseite des mobilen Clients mit allen Decks, Suche und Zaehlern.
_Avoid_: Stapelansicht, Home

**Deck-Emoji**:
Das eine Emoji eines Decks, gespeichert als Suffix im Anki-Namen: `Biologie · 🧬` (Name, Leerzeichen, Mittelpunkt, Leerzeichen, genau ein Emoji). Der Mittelpunkt ist der Trenner, nicht `::` (das waere ein Unterdeck). Die App zeigt Emoji und Name getrennt; ohne passendes Suffix gilt `🗂️` und der volle Name. Das Suffix haelt die Sortierung wie in Anki Desktop. Anki Desktop zeigt das Suffix im Klartext, und ein dort umbenanntes Deck verliert sein Emoji (kein Datenfehler). Es gibt kein Praefix-Format und keine Umbenennung aelterer Decks, weil es in Produktion keine Decks mit Emoji gibt.
_Avoid_: Icon, Praefix-Emoji

**Karte**:
Eine einzelne Lerneinheit, die im Review beantwortet wird.
_Avoid_: Flashcard, Item

**Notiz**:
Der gespeicherte Inhalt (Felder), aus dem eine oder mehrere Karten entstehen. Eine Notiz hat genau einen Notiztyp.
_Avoid_: Eintrag, Record

**Notiztyp**:
Die Vorlage einer Notiz mit Feldern und Kartenvorlagen. Der mobile Client nutzt nur dedizierte Notiztypen (zuerst `AnkiWeb Vocab`).
_Avoid_: Note-Type, Modell, Template

**Hinzugefuegte Karten**:
Die in der laufenden Hinzufuegen-Sitzung gespeicherten Notizen, sichtbar im Wizard. Sie sind sofort im Deck gespeichert. Anki-Wortlaut: `adding_added` ("Hinzugefuegt").
_Avoid_: Stack, Stapel, Batch, Neue Karten

**Neue Karten**:
Karten, die noch nie gelernt wurden (Anki-Zaehler `statistics_counts_new_cards`, "New"/"Neu"). Hat nichts mit der Hinzufuegen-Sitzung zu tun.
_Avoid_: Frische Karten

**Review**:
Das Beantworten der faelligen Karten eines Decks mit Ease-Bewertung.
_Avoid_: Lernmodus, Quiz

**Tagesfortschritt**:
Anteil der heute erledigten Reviews eines Decks an erledigten plus noch offenen (faellige plus neue). Tagesgrenze ist die der Sammlung (folgt dem Rollover, Standard 04:00), nicht Mitternacht.
_Avoid_: Lernstand, Fortschritt

**Streak**:
Anzahl der zuletzt direkt nacheinander mit Ease 2, 3 oder 4 bewerteten Reviews seit Tagesbeginn, ueber alle Decks. Wird aus dem Revlog gelesen, nicht gespeichert.
_Avoid_: Serie, Combo, Sitzungs-Streak

## Flagged ambiguities

- "Stapel" meinte in den Plaenen dreierlei (Deck, Deck-Liste, Hinzufuegen-Stapel). Aufgeloest: **Deck** fuer das Anki-Objekt, **Deck-Liste** fuer die Startseite, **Hinzugefuegte Karten** fuer die Wizard-Liste.
- "Neue Karten" war zuerst fuer die Wizard-Liste vorgesehen, ist aber Anki-Begriff fuer nie gelernte Karten (`scheduling_new_cards`). Aufgeloest: gehoert exklusiv dem Zaehler; die Wizard-Liste heisst **Hinzugefuegte Karten**.
