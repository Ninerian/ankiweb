# AnkiWeb Mobile Client

Eigenstaendiger, mobiler Lern-Client unter `/app/*` neben dem bestehenden Web-Client. Deckt Deck-Liste, Review sowie das Hinzufuegen und Bearbeiten von Vokabeln ab; Verwaltung (Browser, Graphs, Deck-Optionen, Import) bleibt im bestehenden Client.

## Language

**Deck**:
Ein Anki-Stapel, der Karten gruppiert und zum Lernen gewaehlt wird. UI-Name auf Deutsch: "Stapel".
_Avoid_: Stack, Ordner

**Sprachpaar**:
Ein geordnetes Paar aus Ursprungssprache und Zielsprache fuer genau ein Deck. Beide Sprachen muessen verschieden sein und zum Katalog `de`, `en`, `es`, `fr`, `it`, `pt`, `nl`, `pl`, `tr`, `ru`, `ja`, `zh`, `ko`, `ar`, `sv`, `la` gehoeren. Ein Deck ohne gueltigen Sprach-Marker hat kein Sprachpaar; Unterdecks erben kein Sprachpaar.
Die Formularauswahl `LanguageMode` unterscheidet Sprachpaar (`langs`) und keine Sprachen (`none`). Gespeichert wird weiterhin nur das Sprachpaar oder dessen Abwesenheit; ungueltige Eingaben bleiben bis zur Validierung erhalten.

**Ursprungssprache**:
Die Sprache des Sprachpaars, die die lernende Person bereits kann; sie steht vor dem Pfeil und entspricht im Karteneditor der Rueckseite.
_Avoid_: Muttersprache

**Zielsprache**:
Die Sprache des Sprachpaars, die die lernende Person lernt; sie steht nach dem Pfeil und entspricht im Karteneditor der Vorderseite. Dies ist eine UI-Konvention: Gespeicherte Feldinhalte werden nicht auf ihre Sprache geprueft oder umsortiert.
_Avoid_: Lernsprache

**Eingabehilfen**:
Artikel- und Sonderzeichen-Buttons am Vorderseiten-Feld, abgeleitet aus der Zielsprache des Decks. Ohne gueltiges Sprachpaar gelten die bisherigen deutschen Buttons; Unterdecks erben kein Sprachpaar. Fuer `ko` und unbekannte Sprachcodes liefert der Katalog keine Buttons (ein ungueltiger Marker bedeutet jedoch kein Sprachpaar). Fuer andere Schriften werden keine vollstaendigen Tastaturen angeboten.

**Sprach-Marker**:
Der maschinenlesbare HTML-Kommentar in der Deck-Beschreibung, etwa `<!--ankiweb:lang=es>de-->` fuer Ursprungssprache `es` und Zielsprache `de`. Ein fehlender oder ungueltiger Marker bedeutet keine Sprachen.

**Sprachstapel**:
Ein Deck mit einem gueltigen Sprachpaar. Ein Deck ohne Sprachen ist kein Sprachstapel.

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
Die in der laufenden Sitzung neu gespeicherten Notizen im Wizard unter `/app/edit`; sie sind sofort im Deck gespeichert. Der Sitzungszaehler erfasst nur Neuanlagen und bleibt vom deckweiten Stapel-Badge getrennt. „Fertig“ steht auch in der geoeffneten Deck-Kartenliste bereit und oeffnet die Zusammenfassung, die den Sitzungszaehler auch bei null hinzugefuegten Karten anzeigt. Bei ungespeichertem Entwurf erfolgt vorher eine Abfrage. Bearbeiten erhoeht keinen der beiden Zaehler. Anki-Wortlaut: `adding_added` ("Hinzugefuegt").
Die Pfade `/app/edit/<deck>/front`, `/back` und `/preview` bilden die Wizard-Schritte ab; `/app/edit/<deck>/cards` zeigt die Deck-Kartenliste, `/app/edit/<deck>/cards/<nid>/<step>` eine bestehende Notiz.
Fehlermeldungen bleiben bis zur naechsten Eingabe oder Editor-Anfrage sichtbar; eine erneut abgelehnte Anfrage zeigt ihre eigene Meldung.
_Avoid_: Stack, Stapel, Batch, Neue Karten

**Deck-Kartenliste**:
Die vollstaendige Liste der `AnkiWeb Vocab`-Notizen mit mindestens einer Karte im gewaehlten Deck, auch aus frueheren Sitzungen. Andere Notiztypen, geloeschte und deckfremde Notizen fehlen. Der visuelle Stapel zeigt bis zu fuenf der neuesten dieser Notizen; sein Badge zaehlt alle. Tippen oder Hochwischen oeffnet die Liste in der Reihenfolge von alt nach neu. Eine Zeile laedt dieselbe Notiz im Wizard ab Schritt 1; erfolgreiches Speichern aktualisiert ihre bestehende ID, ohne Stapelgroesse oder Reihenfolge zu aendern, und oeffnet die Liste mit der aktualisierten Zeile erneut. Das gilt auch fuer unveraendertes Speichern und erfolgreiche Wiederholung einer vorgemerkten Ruecksetzung. Neuanlagen bleiben im Wizard; Validierungs-, Netzwerk- und Ruecksetzfehler bleiben mit Fehlermeldung im Editor.
_Avoid_: Sitzungsstapel, Deck-Liste

**Gelernt**:
Eine Notiz gilt im gewaehlten Deck als gelernt, wenn mindestens eine ihrer Karten dort den Anki-Kartentyp `type != 0` hat. Die Deck-Kartenliste kennzeichnet sie mit Warnfarbe und Text; beim Bearbeiten warnt ein Banner vor dem Zuruecksetzen des Lernfortschritts.

**Lernfortschritt zuruecksetzen**:
Beim Speichern tatsaechlich geaenderter Felder einer gelernten Notiz werden ihre Karten im gewaehlten Deck mit `reset_counts=True` als neu eingeplant (`reps` und `lapses` werden geloescht). Danach bleibt ein lokalisierter Statushinweis in der erneut geoeffneten Deck-Kartenliste sichtbar und wird angesagt. Ohne vorgemerkte Ruecksetzung setzen unveraendertes Speichern und Aenderungen an ungelernten Notizen nichts zurueck; Karten in anderen Decks bleiben unveraendert. Abbruch loest selbst keine Ruecksetzung aus und entfernt keine vorgemerkte Ruecksetzung. Das Revlog bleibt erhalten und die Neueinplanung wird protokolliert. Eine dauerhaft vorgemerkte, fehlgeschlagene Ruecksetzung kann beim erneuten Speichern auch unveraendert wiederholt werden; Grenzen und Fehlerrisiken stehen in Plan 9.

**Neue Karten**:
Karten, die aktuell als neu eingeplant sind (Anki-Zaehler `statistics_counts_new_cards`, "New"/"Neu"); dazu koennen auch zurueckgesetzte Karten gehoeren. Hat nichts mit der Hinzufuegen-Sitzung zu tun.
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

- "Stapel" meinte in den Plaenen dreierlei (Deck, Deck-Liste, Hinzufuegen-Stapel). Aufgeloest: **Deck** fuer das Anki-Objekt, **Deck-Liste** fuer die Startseite, **Hinzugefuegte Karten** fuer die Neuanlagen der Sitzung und **Deck-Kartenliste** fuer die deckweite Auswahl im Wizard.
- "Neue Karten" ist der Anki-Begriff fuer als neu eingeplante Karten (`scheduling_new_cards`), nicht fuer die sitzungsbezogene Anzeige **Hinzugefuegte Karten**.
