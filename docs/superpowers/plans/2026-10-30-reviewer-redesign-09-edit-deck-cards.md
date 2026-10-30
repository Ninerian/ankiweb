# Plan 9: Deck-Karten bearbeiten (`/app/edit`)

> Teil von [00-overview](2026-10-27-reviewer-redesign-00-overview.md). Baut auf [Plan 4](2026-10-27-reviewer-redesign-04-add-cards.md) und [Plan 8](2026-10-30-reviewer-redesign-08-added-cards-list.md) auf. Dieser Plan ersetzt deren sitzungsgebundene Bearbeitung und Editor-Routen; die historischen Pläne bleiben unverändert. Von Plan 8 wird **nur** die Listen- und Bearbeitungslogik (Öffnen, Zeile wählen, Abbruch, Entwurfsschutz, Fokus) übernommen. Dessen **Umgestaltung des Stapels** (Boden, Hinweisschild, Wischgeste, Staffelung 26 px) wird **nicht** umgesetzt, weil das heutige Stapeldesign beibehalten wird.

**Ziel:** Im mobilen Wizard Vokabeln eines gewählten Decks hinzufügen und vorhandene Vokabeln desselben Decks bearbeiten – auch aus früheren Sitzungen. Änderungen gelernter Karten setzen deren Lernfortschritt bewusst zurück.

> **Stand: noch nicht umgesetzt.** Dieser Plan hält die Änderungen nur fest. Ein erster Umsetzungsversuch wurde auf Wunsch des Nutzers zurückgenommen; es gibt keinen Code zu diesem Plan.

## Entscheidungen

| Frage | Entscheidung |
|---|---|
| Welche Notizen? | Alle `AnkiWeb Vocab`-Notizen mit mindestens einer Karte im gewählten Deck; keine anderen Notiztypen. Die Auswahl ist nicht an die aktuelle Sitzung gebunden. |
| Stapel und Liste | Der sichtbare Stapel bleibt sitzungsbezogen: höchstens die letzten vier in dieser Sitzung und diesem Deck hinzugefügten Karten, Badge mit Anzahl aller dieser Sitzung. Der Stapel **öffnet** die separate deckweite Liste `#deck-cards`; diese enthält alle Karten des Decks, nicht nur die des Stapels. |
| Stapeldesign | **Das aktuelle Design des Kartenstapels bleibt unverändert.** Der Plan ergänzt nur den Auslöser zum Öffnen der Liste und übernimmt **nicht** die Umgestaltung aus Plan 8 (Boden, Hinweisschild, Wischgeste). Markup und Klassen von `#added-cards` bleiben unangetastet: Container `mt-1`, Fläche `relative mx-3 h-72`, Karten `.added-0..3` (`h-40`, `border-3`, `shadow-neo`), Sternen-Badge `.add-stack-badge`, Animation `animate-slide-to-added`, Leerzustand `.add-empty`. Der Auslöser ist ein **umschließender** `<button>` um diesen Block (kein Umbau darin). Das Badge ist heute `pointer-events-none`; Klicks fallen dadurch auf den umschließenden Button durch, das bleibt so. Siehe Abschnitt „Stapel als Einstieg“. |
| Bearbeiten | Jede Listenzeile ist ein Button mit `data-note-id`. Dieselbe Notiz wird im Wizard ab Schritt 1 geladen und unter derselben ID gespeichert; kein Duplikat. |
| Gelernt | Mindestens eine Karte der Notiz **im gewählten Deck** hat Anki-Kartentyp `type != 0`. In der Liste **farblich** (Warnton aus dem Theme) **und** mit Text `Gelernt` / `learned` kennzeichnen, nie nur über Farbe. Eine Legende erklärt, dass Änderungen den Lernfortschritt löschen. |
| Stapelliste | Der Button der Deckzeile heißt `Bearbeiten` / `Edit` (Schlüssel `app_decks_edit` statt `app_decks_edit_add`) und verlinkt auf `/app/edit?deck=<id>`; ebenso der Leerzustand der Stapelliste. |
| Lernfortschritt | Beim Bearbeiten einer gelernten Notiz warnt ein Banner vor dem Zurücksetzen. Nur wenn die gespeicherten Felder tatsächlich geändert wurden, setzt `col.sched.schedule_cards_as_new(card_ids, reset_counts=True)` die Karten dieser Notiz im gewählten Deck zurück (`reset_counts=True` soll `reps` und `lapses` löschen; vor der Umsetzung per Test belegen). Das Revlog wird dabei nicht gelöscht; Pylib ruft mit `log=True` auf, die Neueinplanung wird also zusätzlich protokolliert. Auch das ist vor der Umsetzung gegen die installierte Anki-Version zu prüfen. Danach erscheint ein Hinweis. Unverändertes Speichern und Abbruch setzen nichts zurück. |

## Stapel als Einstieg

| Element | Verhalten |
|---|---|
| Auslöser | Der vorhandene Stapel (einschließlich Sternen-Badge) wird zu **einer** bedienbaren Fläche: ein `<button type="button" id="pile">` umschließt den Stapel, ohne dessen Optik zu ändern. Tippen, Enter und Leertaste öffnen die Deckliste `#deck-cards`. Eine Wischgeste gibt es nicht. |
| Hinweis | Ein kleines Textlabel am Stapel (vorhandene Tokens, z. B. `text-muted-fg`, gleiche Schrift wie der Leerzustand) nennt die Aktion: „Tippen zum Bearbeiten“ / „Tap to edit“. Es verändert Stapel, Staffelung und Badge nicht. |
| Leerer Sitzungsstapel | Hat das Deck Karten, die Sitzung aber keine neuen, zeigt der Leerzustand zusätzlich einen Button „Karten im Stapel bearbeiten (n)“, der dieselbe Liste öffnet. Hat das Deck gar keine Karten, bleibt der Leerzustand wie heute ohne Button. |
| Zugänglichkeit | Der Button trägt `aria-expanded`, `aria-controls="deck-cards"` und den Sprechtext „n Karten hinzugefügt. Tippen zum Bearbeiten.“ (de und en); sichtbarer Fokusring; Fokus geht nach dem Schließen zurück auf den Button. `prefers-reduced-motion` bleibt unverändert wirksam. |
| Liste öffnen | Die Liste erscheint anstelle der Eingabekarte. Hat die **neue** Karte ungespeicherten Text, fragt das vorhandene `avConfirmDiscard` vorher nach; eine unverändert geladene Karte fragt nie. |
| Liste schließen | `Zurück zur neuen Karte` oder Escape schließen ohne Änderung. Eine Zeile wählen lädt die Karte in den Wizard (Schritt 1), schließt die Liste und zeigt das Bearbeiten-Banner. |
| Speichern | Nach dem Speichern einer bearbeiteten Karte bleibt der Stapel unverändert (gleiche Karten, gleicher Zähler); nur eine Neuanlage lässt ihn wachsen und animiert wie heute. |

## Routenvertrag

| Methode und Route | Verhalten |
|---|---|
| `GET /app/edit?deck=<id>` | Wizard für das gewählte Deck mit Sitzungsstapel und Deck-Kartenliste öffnen. |
| `POST /app/edit/preview` | Vorschau für `front`, `back`, `hint`, `example` erzeugen; kein Speichern. |
| `POST /app/edit/card/{nid}?deck=<id>` | Deck-eigene `AnkiWeb Vocab`-Notiz laden und den Wizard auf Schritt 1 setzen. Fehlende, deckfremde oder nicht unterstützte Notizen nicht laden. |
| `POST /app/edit/commit?deck=<id>` | Felder speichern: `nid: 0` legt an, eine vorhandene `nid` aktualisiert die deck-eigene Notiz. |

Der App-Client verwendet `shell_src/app/edit.js`. Navigation, Templates, Client-Aufrufe und Tests verwenden ausschließlich die neuen Editor-Routen; der separate bestehende Desktop-Editor `/add` bleibt unverändert.

## Aufgaben

- [ ] Deck-Kartenliste unabhängig von Sitzungs-IDs laden; gelöschte, deckfremde und andere Notiztypen ausschließen. Sitzungsstapel und Zähler nicht durch die Deckliste ersetzen.
- [ ] **Baseline zuerst:** Vor jeder Änderung die berechneten Stile von `#added-cards`, `.added-0..3`, `.add-stack-badge` und `.add-empty` je Element (Schlüssel Tag, Id, Klasse) als JSON sichern, in Hell und Dunkel, bei 375×812 und 509×904, mit 1, 4 und 5 Sitzungskarten sowie leerem Stapel. Nach der Umsetzung gegen diese Baseline vergleichen; nur der neue umschließende Button und das Hinweislabel dürfen hinzukommen.
- [ ] Stapel als Einstieg: Stapelfläche mit einem umschließenden `<button id="pile">` versehen (Markup und Klassen innerhalb unverändert), Hinweislabel, Leerzustands-Button, `aria-expanded`/`aria-controls`, Fokusrückgabe, Öffnen/Schließen der Liste per Datastar-Signal (nicht per DOM-Klasse, damit der Commit-Morph den Zustand nicht überschreibt). Stapeloptik, `.added-0..3`-CSS und Animation **nicht** anfassen. Der Test `test_added_stack_is_noninteractive_and_preserves_draft` wird durch einen Klicktest ersetzt (Klick öffnet die Liste, Entwurf bleibt erhalten).
- [ ] Strings (de, en) für Hinweislabel, Leerzustands-Button, Sprechtext und „Zurück zur neuen Karte“.
- [ ] Auswahl lädt die Notiz über die Kartenroute; Speichern aktualisiert ihre Felder ohne neue Notiz. Ungültige Decks und nicht bearbeitbare Notizen weiterhin ablehnen.
- [ ] Lernstatus aus den Kartentypen im gewählten Deck ermitteln. Änderungen mit den gespeicherten Werten vergleichen; nur beim geänderten, gelernten Eintrag die zugehörigen Deck-Karten mit zurückgesetzten Zählern als neu einplanen.
- [ ] Liste, Lernstatus, Warnbanner und Hinweis auf zurückgesetzten Fortschritt in Deutsch und Englisch zugänglich anzeigen. Abbruch verwirft den Entwurf; unverändert geladene Notizen gelten nicht als ungespeicherte Änderung.
- [ ] App-Routen, Skript- und Asset-Referenzen sowie alle zugehörigen Aufrufer auf `/app/edit` und `edit.js` umstellen; keine alten App-Routen als Alias behalten.
- [ ] `DESIGN.md`, `REFERENCE.md` und `CONTEXT.md` auf Deckliste, Sitzungsstapel und Rücksetzregel abstimmen.

## Akzeptanz und Prüfungen

- [ ] Eine Vokabel aus einer früheren Sitzung erscheint und lässt sich bearbeiten; andere Decks und Notiztypen erscheinen nicht und sind über die Kartenroute nicht bearbeitbar. Dieselbe Notiz-ID bleibt erhalten.
- [ ] Eine Liste mit mehr als vier Vokabeln ist vollständig; der Sitzungsstapel zeigt höchstens vier und sein Badge zählt nur eigene Sitzungs-Neuanlagen im aktuellen Deck.
- [ ] Stapeldesign unverändert: berechnete Stile (Größe, Lage, Rahmen, Schatten, Badge) von `#added-cards` und `.added-0..3` sind vor und nach der Änderung gleich (JSON-Vergleich je Element, hell und dunkel); der Stapel ist jetzt ein Button, Tastatur (Enter, Leertaste, Escape) und Screenreader funktionieren.
- [ ] Tippen auf den Stapel und auf das Badge öffnet die Liste; bei leerem Sitzungsstapel öffnet der Leerzustands-Button sie. Ungespeicherter Text in der neuen Karte fragt vorher nach, unverändert geladene Karten nie. Escape und „Zurück zur neuen Karte“ ändern nichts. Der Test `test_added_stack_is_noninteractive_and_preserves_draft` verlangt heute das Gegenteil und wird bewusst ersetzt.
- [ ] `type != 0` einer beliebigen Karte der Notiz im Deck ergibt den Textmarker und die Warnung; nur neue Karten ergeben keinen Marker. Karten derselben Notiz in anderen Decks bestimmen diesen Status nicht.
- [ ] Geänderte gelernte Notiz: Karten im gewählten Deck werden mit `reset_counts=True` als neu eingeplant und der Hinweis erscheint. Unverändert speichern, abbrechen und geänderte ungelernte Notizen setzen keinen Lernfortschritt zurück; Karten in anderen Decks bleiben unverändert.
- [ ] Vorschau, Neuanlage, Editieren, Navigation und Abbruch funktionieren auf den neuen Routen; alte App-Routen sind nicht erreichbar. Tests für Routen und Browser in Deutsch und Englisch prüfen Liste, Marker und Warnung.
- [ ] Der Test für die Rücksetzung prüft nach einer Änderung `type == 0`, `reps == 0` **und** `lapses == 0` (Lern- und Wiederholungskarte); ohne Änderung bleiben `type, queue, due, ivl, factor, reps, lapses` gleich.
- [ ] Nach der Umsetzung `tests/app_client` vollständig, Ruff und ty ausführen und die Seite gegen eine isolierte Test-Collection im Browser (509×904) prüfen; ein bereits laufender Server mit altem Code ist neu zu starten.
