# Plan 9: Deck-Karten bearbeiten (`/app/edit`)

> Teil von [00-overview](2026-10-27-reviewer-redesign-00-overview.md). Baut auf [Plan 4](2026-10-27-reviewer-redesign-04-add-cards.md) und [Plan 8](2026-10-30-reviewer-redesign-08-added-cards-list.md) auf. Dieser Plan ersetzte deren sitzungsgebundene Bearbeitung und Editor-Routen. Seine Entscheidung, das sitzungsbezogene Stapeldesign unverändert zu lassen und die Umgestaltung aus Plan 8 nicht zu übernehmen, ist durch den direkten Nutzerwunsch vom 30.10.2026 überholt; siehe „Aktuelle Vorgabe“. Die historischen Pläne bleiben unverändert.

**Ziel:** Im mobilen Wizard Vokabeln eines gewählten Decks hinzufügen und vorhandene Vokabeln desselben Decks bearbeiten – auch aus früheren Sitzungen. Änderungen gelernter Karten setzen deren Lernfortschritt bewusst zurück.

> **Historischer Stand von Plan 9: umgesetzt.** Prüfstand, Entscheidungen, Aufgaben und Akzeptanz unten dokumentieren den damaligen Stand, nicht die Prüfung der aktuellen Vorgabe.

**Prüfstand:** `tests/app_client`: 581 Tests bestanden; Ruff und ty bestanden. Der Browser-Smoke lief auf Deutsch bei 509×904 mit temporärer Collection und Server auf freiem Port; Liste, Stapel-Badge und Rücksetzung gelernter Karten einschließlich Revlog wurden geprüft. Bei Lern-, Wiederholungs- und Wiederlernkarten setzte `reset_counts=True` `type`, `reps` und `lapses` auf 0, erhielt bestehende Revlog-Einträge und ergänzte einen Typ-4-Eintrag. Ein Test prüfte nach einmaligem Rücksetzfehler, neuem Cookie und erneutem Öffnen der Collection die Rücksetzung beim unveränderten erneuten Speichern. Als Negativkontrolle scheiterte derselbe Test auf Deutsch und Englisch erwartungsgemäß am Rücksetzungshinweis, wenn die dauerhafte Vormerkung unmittelbar vor dem Wiederholungsversuch entfernt wurde. Der JSON-Vergleich berechneter Stile war für alle 16 Kombinationen aus echtem Hell-/Dunkelmodus, zwei Viewports und 0, 1, 4 bzw. 5 Sitzungskarten bytegleich. Die echte Hell-/Dunkel-Baseline wurde nach den Stapeländerungen aus dem archivierten Original-Commit `ccfb9f6` (`/app/add`) erneut erfasst; sie stimmt bytegleich mit dem Endstand und dem archivierten Snapshot nach Routenumbenennung und vor Stapeländerungen überein. Die erste Erfassung im Arbeitsbaum vor den Änderungen war für den Dunkelmodus falsch beschriftet.

**Risiko:** Notizaktualisierung und Neueinplanung sind nicht atomar; `run_op` allein ist keine Transaktion. Schlägt die Rücksetzung nach dem Speichern fehl, meldet die App den gespeicherten Text und den nicht zurückgesetzten Lernfortschritt; die Bearbeitung und das Signal für eine gelernte Karte bleiben erhalten, der Fehler wird protokolliert. Vor dem Schreiben merkt der Server die Rücksetzung dauerhaft in der Collection-Konfiguration vor, mit Deck- und Notiz-ID sowie einem 128-Bit-Fingerabdruck der normalisierten ursprünglichen Felder. Kann die Vormerkung nicht gespeichert werden, bricht die App vor der Notizänderung mit einer Fehlermeldung ab; die Konfiguration begrenzt sie auf 50 Einträge und 4096 serialisierte JSON-Bytes. Die Vormerkung übersteht Abbruch, erneutes Laden, andere Sitzungen und Cookies sowie Serverneustarts. Bei einer vorgemerkten Änderung versucht erneutes Speichern die Rücksetzung auch mit unveränderten Eingaben und wenn keine Karte mehr als gelernt gilt. Entsprechen die aktuellen Felder noch dem ursprünglichen Fingerabdruck und werden sie unverändert gespeichert, wird keine Rücksetzung versucht: Eine extern exakt auf die ursprünglichen Werte zurückgesetzte Änderung ist nicht von einem unterbrochenen Schreiben zu unterscheiden; die ausstehende Rücksetzung ist in diesem Fall nicht garantiert. Nach erfolgreicher Rücksetzung wird die Vormerkung entfernt; bei bekannter Validierungsablehnung und unveränderten gespeicherten Feldern wird eine neu erstellte Vormerkung bestmöglich entfernt. Scheitert das Entfernen nach erfolgreicher Rücksetzung, meldet die App dies gesondert. Abbruch setzt nichts zurück; unverändertes Speichern ohne Vormerkung ebenso wenig. Teiländerungen der fehlgeschlagenen Neueinplanung sind nicht durch eine gemeinsame Transaktion zurückgerollt. Eine naive Datenbanktransaktion wird vermieden, weil beobachtete Rollback-/Undo-Probleme Ankis Undo-Verlauf inkonsistent machen oder löschen können.

## Aktuelle Vorgabe (30.10.2026)

Der direkte Nutzerwunsch ersetzt die frühere Entscheidung für einen unveränderten Sitzungsstapel: Der sichtbare Stapel und die Liste beziehen alle `AnkiWeb Vocab`-Notizen mit mindestens einer Karte im gewählten Deck ein, auch aus früheren Sitzungen. Andere Notiztypen und deckfremde Notizen bleiben ausgeschlossen. Der bodenstehende Stapel folgt `editor-mockup.html`: bis zu fünf undurchsichtige, 104 px hohe Karten, um 26 px nach oben gestaffelt, mit Drehung, Perspektive und Schatten; die neueste liegt vorn. Das Badge unten rechts zählt alle unterstützten Deck-Notizen. Der Sitzungszähler bleibt davon getrennt und zählt Neuanlagen für „Fertig“ und die Zusammenfassung.

Tippen auf Stapel oder Badge oder Hochwischen öffnet die vollständige Liste von alt nach neu: Der Editor gleitet weg, die Karten fächern gestaffelt auf; Zurück, Escape oder eine Zeilenauswahl falten sie wieder zusammen. Die Staffelung ist für große Decks begrenzt, reduzierte Bewegung wird respektiert. Zeilen sind zugängliche Buttons; bei fehlgeschlagenem Laden bleibt die Liste offen. Entwurfsschutz, Tastaturbedienung und Fokusrückgabe bleiben erhalten. Bearbeiten aktualisiert dieselbe Notiz-ID ohne Duplikat und ändert weder Stapelgröße noch Reihenfolge; nur Neuanlagen vergrößern und animieren den Stapel. Die Regeln und Fehlerrisiken für gelernte Karten und dauerhafte Rücksetzversuche bleiben unverändert.

Die nachfolgenden historischen Prüfungen belegen diese neue Vorgabe nicht.

## Historische Entscheidungen

| Frage | Entscheidung |
|---|---|
| Welche Notizen? | Alle `AnkiWeb Vocab`-Notizen mit mindestens einer Karte im gewählten Deck; keine anderen Notiztypen. Die Auswahl ist nicht an die aktuelle Sitzung gebunden. |
| Stapel und Liste | Der sichtbare Stapel bleibt sitzungsbezogen: höchstens die letzten vier in dieser Sitzung und diesem Deck hinzugefügten Karten, Badge mit Anzahl aller dieser Sitzung. Der Stapel **öffnet** die separate deckweite Liste `#deck-cards`; diese enthält alle Karten des Decks, nicht nur die des Stapels. |
| Stapeldesign | **Das aktuelle Design des Kartenstapels bleibt unverändert.** Der Plan ergänzt nur den Auslöser zum Öffnen der Liste und übernimmt **nicht** die Umgestaltung aus Plan 8 (Boden, Hinweisschild, Wischgeste). Markup und Klassen von `#added-cards` bleiben unangetastet: Container `mt-1`, Fläche `relative mx-3 h-72`, Karten `.added-0..3` (`h-40`, `border-3`, `shadow-neo`), Sternen-Badge `.add-stack-badge`, Animation `animate-slide-to-added`, Leerzustand `.add-empty`. Der Auslöser ist ein **umschließender** `<button>` um diesen Block (kein Umbau darin). Das Badge ist heute `pointer-events-none`; Klicks fallen dadurch auf den umschließenden Button durch, das bleibt so. Siehe Abschnitt „Stapel als Einstieg“. |
| Bearbeiten | Jede Listenzeile ist ein Button mit `data-note-id`. Dieselbe Notiz wird im Wizard ab Schritt 1 geladen und unter derselben ID gespeichert; kein Duplikat. |
| Gelernt | Mindestens eine Karte der Notiz **im gewählten Deck** hat Anki-Kartentyp `type != 0`. In der Liste **farblich** (Warnton aus dem Theme) **und** mit Text `Gelernt` / `learned` kennzeichnen, nie nur über Farbe. Eine Legende erklärt, dass Änderungen den Lernfortschritt löschen. |
| Stapelliste | Der Button der Deckzeile heißt `Bearbeiten` / `Edit` und verlinkt auf `/app/edit/<deck>/front`. |
| Lernfortschritt | Beim Bearbeiten einer gelernten Notiz warnt ein Banner vor dem Zurücksetzen. Nur wenn die gespeicherten Felder tatsächlich geändert wurden, setzt `col.sched.schedule_cards_as_new(card_ids, reset_counts=True)` die Karten dieser Notiz im gewählten Deck zurück (`reset_counts=True` soll `reps` und `lapses` löschen; vor der Umsetzung per Test belegen). Das Revlog wird dabei nicht gelöscht; Pylib ruft mit `log=True` auf, die Neueinplanung wird also zusätzlich protokolliert. Auch das ist vor der Umsetzung gegen die installierte Anki-Version zu prüfen. Danach erscheint ein Hinweis. Unverändertes Speichern und Abbruch setzen nichts zurück. |

## Historischer Stapel als Einstieg

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
| `GET /app/edit/<deck>/<step>` | Wizard; Schritt `front`, `back` oder `preview`. Direkte Aufrufe ohne Entwurf starten bei `front`. |
| `GET /app/edit/<deck>/cards` und `GET /app/edit/<deck>/cards/<nid>/<step>` | Deckliste bzw. vorhandene Notiz öffnen. |
| `POST /app/edit/<deck>/<instance>/<revision>/step/<step>/<via>` | Pflichtfelder prüfen und Schritt sowie Vorschau als SSE-Fragmente rendern. |
| `POST /app/edit/<deck>/<instance>/<revision>/card/<nid>` | Deck-eigene Notiz laden und Formular ersetzen. |
| `POST /app/edit/<deck>/<instance>/<revision>/commit` | Formular speichern. |
| `POST /app/edit/<deck>/<instance>/<revision>/reset` | Formular nach bestätigtem Verwerfen zurücksetzen. |

Der App-Client verwendet `shell_src/app/edit.js`. Navigation, Templates, Client-Aufrufe und Tests verwenden ausschließlich die neuen Editor-Routen; der separate bestehende Desktop-Editor `/add` bleibt unverändert.

## Historische Aufgaben

- [x] Deck-Kartenliste unabhängig von Sitzungs-IDs laden; gelöschte, deckfremde und andere Notiztypen ausschließen. Sitzungsstapel und Zähler nicht durch die Deckliste ersetzen.
- [ ] **Baseline zuerst:** Vor jeder Änderung die berechneten Stile von `#added-cards`, `.added-0..3`, `.add-stack-badge` und `.add-empty` je Element (Schlüssel Tag, Id, Klasse) als JSON sichern, in Hell und Dunkel, bei 375×812 und 509×904, mit 1, 4 und 5 Sitzungskarten sowie leerem Stapel. Nach der Umsetzung gegen diese Baseline vergleichen; nur der neue umschließende Button und das Hinweislabel dürfen hinzukommen.
  - Der Vergleich liegt vor; die korrekte Hell-/Dunkel-Baseline wurde erst nach den Stapeländerungen aus dem archivierten Original erneut erfasst.
- [x] Stapel als Einstieg: Stapelfläche mit einem umschließenden `<button id="pile">` versehen (Markup und Klassen innerhalb unverändert), Hinweislabel, Leerzustands-Button, `aria-expanded`/`aria-controls`, Fokusrückgabe, Öffnen/Schließen der Liste per Datastar-Signal (nicht per DOM-Klasse, damit der Commit-Morph den Zustand nicht überschreibt). Stapeloptik, `.added-0..3`-CSS und Animation **nicht** anfassen. Der Test `test_added_stack_is_noninteractive_and_preserves_draft` wird durch einen Klicktest ersetzt (Klick öffnet die Liste, Entwurf bleibt erhalten).
- [x] Strings (de, en) für Hinweislabel, Leerzustands-Button, Sprechtext und „Zurück zur neuen Karte“.
- [x] Auswahl lädt die Notiz über die Kartenroute; Speichern aktualisiert ihre Felder ohne neue Notiz. Ungültige Decks und nicht bearbeitbare Notizen weiterhin ablehnen.
- [x] Lernstatus aus den Kartentypen im gewählten Deck ermitteln. Änderungen mit den gespeicherten Werten vergleichen; nur beim geänderten, gelernten Eintrag die zugehörigen Deck-Karten mit zurückgesetzten Zählern als neu einplanen.
- [x] Liste, Lernstatus, Warnbanner und Hinweis auf zurückgesetzten Fortschritt in Deutsch und Englisch zugänglich anzeigen. Abbruch verwirft den Entwurf; unverändert geladene Notizen gelten nicht als ungespeicherte Änderung.
- [x] App-Routen, Skript- und Asset-Referenzen sowie alle zugehörigen Aufrufer auf `/app/edit` und `edit.js` umstellen; keine alten App-Routen als Alias behalten.
- [x] `DESIGN.md`, `REFERENCE.md` und `CONTEXT.md` auf Deckliste, Sitzungsstapel und Rücksetzregel abstimmen.

## Historische Akzeptanz und Prüfungen

- [x] Eine Vokabel aus einer früheren Sitzung erscheint und lässt sich bearbeiten; andere Decks und Notiztypen erscheinen nicht und sind über die Kartenroute nicht bearbeitbar. Dieselbe Notiz-ID bleibt erhalten.
- [x] Eine Liste mit mehr als vier Vokabeln ist vollständig; der Sitzungsstapel zeigt höchstens vier und sein Badge zählt nur eigene Sitzungs-Neuanlagen im aktuellen Deck.
- [ ] Stapeldesign unverändert: berechnete Stile (Größe, Lage, Rahmen, Schatten, Badge) von `#added-cards` und `.added-0..3` sind vor und nach der Änderung gleich (JSON-Vergleich je Element, hell und dunkel); der Stapel ist jetzt ein Button, Tastatur (Enter, Leertaste, Escape) und Screenreader funktionieren.
  - Stilgleichheit und Tastaturtests liegen vor; die Bedienung mit einem Screenreader wurde nicht gesondert geprüft.
- [x] Tippen auf den Stapel und auf das Badge öffnet die Liste; bei leerem Sitzungsstapel öffnet der Leerzustands-Button sie. Ungespeicherter Text in der neuen Karte fragt vorher nach, unverändert geladene Karten nie. Escape und „Zurück zur neuen Karte“ ändern nichts. Der Test `test_added_stack_is_noninteractive_and_preserves_draft` verlangt heute das Gegenteil und wird bewusst ersetzt.
- [x] `type != 0` einer beliebigen Karte der Notiz im Deck ergibt den Textmarker und die Warnung; nur neue Karten ergeben keinen Marker. Karten derselben Notiz in anderen Decks bestimmen diesen Status nicht.
- [x] Geänderte gelernte Notiz: Karten im gewählten Deck werden mit `reset_counts=True` als neu eingeplant und der Hinweis erscheint. Unverändert speichern, abbrechen und geänderte ungelernte Notizen setzen keinen Lernfortschritt zurück; Karten in anderen Decks bleiben unverändert.
- [x] Vorschau, Neuanlage, Editieren, Navigation und Abbruch funktionieren auf den neuen Routen; alte App-Routen sind nicht erreichbar. Tests für Routen und Browser in Deutsch und Englisch prüfen Liste, Marker und Warnung.
- [x] Der Test für die Rücksetzung prüft nach einer Änderung `type == 0`, `reps == 0` **und** `lapses == 0` (Lern- und Wiederholungskarte); ohne Änderung bleiben `type, queue, due, ivl, factor, reps, lapses` gleich.
- [x] Nach der Umsetzung `tests/app_client` vollständig, Ruff und ty ausführen und die Seite gegen eine isolierte Test-Collection im Browser (509×904) prüfen; ein bereits laufender Server mit altem Code ist neu zu starten.
