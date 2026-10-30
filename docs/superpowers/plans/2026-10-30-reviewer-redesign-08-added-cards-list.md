# Plan 8: Hinzugefügte Karten ansehen und bearbeiten (Stapel unten, Wischen, Liste)

> Teil von [00-overview](2026-10-27-reviewer-redesign-00-overview.md). Voraussetzung: [Plan 4](2026-10-27-reviewer-redesign-04-add-cards.md) (`/app/add`, `POST /app/add/edit/{nid}`, `commit` mit `nid`), [Plan 6](2026-10-27-reviewer-redesign-06-i18n.md) (`s()`-Strings).
>
> **Ersetzt von Plan 4:** alle Vorgaben zu **Edit-last** (Klick auf oberste Karte, Peek-Banner, HUD-Pille, `TOP CARD`-Hinweis, `popCardUp`; Plan 4 Z. 16, 39, 86, 105, 114, 120 und Commit 4 `Add edit-last route with unescape round trip`). Wer Plan 4 umsetzt, darf diese Teile **nicht** bauen. Die **Serverroute** `POST /app/add/edit/{nid}` und der `commit` mit `nid` aus Plan 4 bleiben bestehen und sind gebaut; Plan 8 ändert nur, **wer sie aufruft** (Listenzeile statt oberster Karte).

**Ziel:** `/app/add` bekommt das Verhalten aus `design/reviewer-redesign/editor-mockup.html` (Stand `0581817`, `DESIGN.md` §5.C/D, `REFERENCE.md` §2.4): Die hinzugefügten Karten stehen **unten** auf der Bühne, ein Hinweis auf dem Boden zeigt "Tippen oder nach oben wischen zum Bearbeiten", ein Tipp oder Wisch öffnet eine **scrollbare Liste aller Karten der Sitzung**, die gewählte Karte wird im selben Eingabewizard bearbeitet und ersetzt die gespeicherte Notiz.

> **Stand heute (gelesen, nicht angenommen):** Die Seite zeigt höchstens **4** Karten (`added_cards` in `add.py:140-173`), oben unter der Eingabekarte (`.added-0..3`, `top-0`, `h-72`), mit einem **nicht klickbaren** Badge (`pointer-events-none`). Der Server kann Karten **schon bearbeiten**: `POST /app/add/edit/{nid}` lädt eine Karte in die Signale, `commit` mit `nid != 0` ruft `update_vocab_note`. **Es gibt keinen Aufrufer in der UI.** Plan 8 ist also fast nur Client und eine erweiterte Leseabfrage.

## Entscheidungen

| Frage | Entscheidung | Beleg |
|---|---|---|
| Mock oder Seite führend? | Der Mock ist die Vorgabe; er ist am `0581817` abgenommen | Nutzerfeedback zu `/app/add` (Stapel unten, Hinweis auf dem Boden, Badges sanft aus) |
| "Edit last" | **Entfällt** (schon im Mock entfernt). Kein Peek-Banner, keine HUD-Pille, kein `TOP CARD`-Hinweis. **Plan 4 nennt Edit-last noch** (Z. 16, 39, 86, 114, 120, Commit 4); dieser Plan ersetzt diese Teile, Plan 4 bleibt als Protokoll des damaligen Stands unverändert | `DESIGN.md` §5.D |
| Bearbeiten | Jede Karte der Sitzung, im **selben** Wizard (Schritt 1), Speichern ersetzt in place (gleiche Notiz-ID, gleiche Position, gleicher Zähler) | Mock-Test: Mittelkarte und letzte Karte bei 10 Karten |
| Server-Edit-Pfad | **Unverändert wiederverwenden** (`/add/edit/{nid}`, `commit` mit `nid`) | Schon getestet in `test_add_routes.py`: `test_edit_round_trip_updates_in_place_and_keeps_stack_order`, `test_edit_and_update_reject_cross_session_and_preserve_new_cookie`, `test_edit_and_update_follow_actual_deck_and_reject_deleted_notes`, `test_edit_and_update_reject_changed_note_type`, `test_edit_rejects_invalid_deck` |
| Welche Karten? | Alle `session.added_note_ids`, die noch existieren und im Deck liegen (bisher: letzte 4) | Liste im Mock zeigt alle |
| Gesten | Tippen auf Stapel/Hinweis/Badge oder Wischen ≥ 28 px nach oben öffnet; kürzerer Zug nichts | Mock-Test: 12 px öffnet nicht, 60 px öffnet |

## Abweichungen vom Mock (bewusst, begründet)

| Mock | Umsetzung | Grund |
|---|---|---|
| Zustand `state.cardStack` im Browser | Server liefert die Liste (`_add_added_cards`), Datastar patcht | Server ist Quelle der Wahrheit (Tao); Seite lädt nach Reload dieselben Karten |
| Liste aus JS gerendert (`renderBrowseList`) | Server rendert die Liste einmalig mit dem Stapel | ein Renderer, kein Client-Template |
| `confirmDiscard` per `window.confirm` | vorhandenes `window.avConfirmDiscard` (`add.js:35`) | schon in der Seite, schon getestet |
| Animationen per `await wait(ms)`-Ketten | CSS-Übergänge über Klassen (`data-class:`), JS nur für Fokus | kein Zeit-State im Client; `prefers-reduced-motion` greift zentral |

## Vorgabe aus Design

| Element | Verhalten |
|---|---|
| Stapel | steht am **Boden der Bühne** unter der Eingabekarte; neueste vorn, ältere gestaffelt dahinter (26 px je Ebene, deckend, mit Tiefe abgedunkelt); höchstens 5 Ebenen gezeichnet |
| Hinweis | Schild "Tippen oder nach oben wischen zum Bearbeiten" **unter** dem Stapel, mit Fußkante und Kontaktschatten; Pfeil wippt; bei 0 Karten und bei offener Liste weg |
| Öffnen | Tippen auf Stapel, Hinweis oder Badge; Wischen nach oben ≥ 28 px auf dem Stapel. Die **drei Schritt-Badges blenden sanft aus** (~350 ms, Höhe klappt zu), die Eingabekarte fährt nach oben weg, die Karten entfalten sich zur Liste |
| Liste | scrollbar, älteste zuerst, je Zeile Nummer, Vorder-/Rückseite, `Gespeichert`, `Hinweis`/`Beispiel`-Marken, `Bearbeiten →`; Kopf "Karte zum Bearbeiten wählen" und **Zurück zur neuen Karte** |
| Bearbeiten | Zeilenklick faltet die Liste zurück, Eingabekarte kommt mit der Karte zurück, Banner `Karte n wird bearbeitet` mit `×`, oranger Rand; Schritt-Badges kommen zurück |
| Verlassen | `×` oder Escape im Bearbeiten ändert nichts; Escape oder Zurück in der Liste schließt |
| Schutz | Öffnen mit ungespeichertem Text in der neuen Karte fragt nach; eine **unveränderte** geladene Karte fragt nie |
| A11y | Badge `aria-expanded`/`aria-controls`, Sprechtext "n Karten hinzugefügt. Tippen zum Ansehen und Bearbeiten."; Zeilen sind Buttons `Karte n bearbeiten: <Vorderseite>`; Fokus zurück aufs Badge; `prefers-reduced-motion` schaltet Bewegung ab |

## Konzept (nach den gelesenen Datastar-Referenzen)

Quellen: `references/attributes.md` (`data-on`-Modifikatoren, `data-class`, `data-show`), `modules/gotchas.md` (#3 IDs, #4 FOUC, Block-Statements), `references/sse-events.md` (Morph), `modules/tao.md`. **Vor 8.4 gegen https://data-star.dev prüfen**, weil die Referenzen Pointer-Ereignisse nicht nennen.

- **Zustand nur als Signal:** `data-signals` am `#add-wizard` ergänzen um `browsing: false`, `editing: false` (Signale ohne Präfix `_` werden mitgesendet; UI-Zustand, der den Server nichts angeht, bekommt `_`-Präfix, siehe `guide-core.md`: `_browsing`, `_editing`). **Offen zu prüfen:** ob `_`-Signale nach `patch_signals` im Commit stehen bleiben.
- **Sichtbarkeit:** Schritt-Badges und Hinweis über `data-class:` (`is-browsing`), **nicht** über `data-show`, damit der Übergang animiert (Opacity/Max-Height). Nur wo kein Übergang nötig ist, `data-show` mit `style="display:none"` (Gotcha #4).
- **Eingabe:** Stapelkarten als **ein** Button/Fläche (`<button type="button" id="pile">`) mit `data-on:click` und `data-on:pointerdown`/`pointerup`. Die Wischlogik (28 px, `setPointerCapture`) ist **kein** Datastar-Ausdruck, sondern eine kleine getestete Funktion in `add.js` (`window.avPileGesture`), aufgerufen aus `data-on:pointerup`. Grund: Block-Statements in Ausdrücken brechen den Parser (Skill-Hinweis); Mock-Befund: ohne Pointer-Capture endet der Zug auf der Eingabekarte und löst nichts aus.
- **Bearbeiten:** Zeilenklick = `@post('/app/add/edit/<nid>?deck=<id>')`. Die Antwort setzt die Signale (`front`, `back`, `hint`, `example`, `nid`, `step: 1`). Nach der Antwort schließt ein `datastar-fetch`-Handler die Liste (Muster wie `avAnimateCommit` in `add.html.jinja:47`).
- **Speichern:** unverändert `@post('/app/add/commit?deck=…')`; Antwort patcht Stapel **und** Liste und setzt `nid: 0`. Kein optimistisches UI.
- **IDs (Gotcha #3):** `#added-cards` (Stapel und Hinweis), `#added-list` (Liste), `#pile`, `#pile-cue`, jede Zeile `#added-<nid>`.
- **Fat morph:** Der Server rendert Stapel **und** Liste in **einem** Fragment (`_add_added_cards.html.jinja`); die Liste ist nur sichtbar, wenn `$_browsing`.

## Dateien

| Datei | Zweck |
|---|---|
| `ankiweb/adapters/inbound/http_app/add.py` | `added_cards` liefert **alle** Karten der Sitzung (Stapel nimmt die letzten 5); `add_card` kappt nicht mehr auf 4 |
| `.../templates/app/_add_added_cards.html.jinja` | Stapel unten, Hinweis, Badge als Button, Liste (`#added-list`) |
| `.../templates/app/add.html.jinja` | Signale `_browsing`/`_editing`, Schritt-Badges mit Übergangsklasse, Escape-Handler, Banner mit `×` |
| `shell_src/app-client.css` | Boden-Stapel, Hinweis mit Fußkante und Schatten, Listenzeile, Übergang der Schritt-Leiste, Reduced-Motion; **alte `.added-0..3`-Regeln ersetzen** |
| `shell_src/app/add.js` | `avPileGesture`, `avOpenList`, `avCloseList`, Fokus zurück aufs Badge; vorhandenes `avConfirmDiscard` wiederverwenden |
| `ankiweb/core/app_client/strings.py` | neue Strings, **de und en** (siehe 8.5) |
| `tests/app_client/test_add_routes.py` | Liste vollständig, Reihenfolge, Escaping, Sitzungsbindung |
| `tests/app_client/test_add_browser.py` | `test_added_stack_is_noninteractive_and_preserves_draft` **ersetzen** (verlangt heute das Gegenteil), neue Browser-Tests |
| `tests/app_client/test_i18n_complete.py` | `BACKEND_ONLY_STRINGS` prüfen (der 404-Text bleibt) |
| `design/reviewer-redesign/REFERENCE.md`, `CONTEXT.md` | Seite statt "nur Mock" kennzeichnen |

## Aufgaben

### 8.1 Server: alle Karten der Sitzung
- [ ] `added_cards` gibt **alle** vorhandenen Karten der Sitzung zurück (Reihenfolge wie `session.added_note_ids`, nur im Deck, nur Vokabel-Notiztyp, wie heute), nicht mehr die letzten 4. Der Stapel zeichnet im Template die letzten 5, die Liste alle.
- [ ] `add_card` (Neuanlage): `del cards[0]` bei > 4 entfällt; Zähler bleibt `count + 1`.
- [ ] Obergrenze bedenken: Sitzung mit sehr vielen Karten. **Entscheidung nötig** (Frage 1 unten); Vorschlag: Liste zeigt alle, Abfrage bleibt in 32er-Blöcken wie heute.
- [ ] **Tests, die das 4-Karten-Limit festschreiben, werden bewusst geändert** (gelesen in `test_add_routes.py`): `test_added_stack_shows_latest_four_and_counts_all` (ab Z. 482, erwartet `Front 0` **nicht** in der Seite und `count: 4` nach Löschen), `test_added_cards_span_query_batches` (ab Z. 516) und `test_changed_note_types_are_excluded_from_session_stack` (ab Z. 571: `Front 0/1` fehlen dort nur wegen des Limits, nicht wegen des Notiztyps). Neu: Stapel zeichnet die letzten 5, die **Liste** enthält alle; die Notiztyp-Prüfung bleibt, die Limit-Annahme entfällt.
- [ ] **Edit erzeugt keine zweite Notiz (Server, schon belegt):** `test_edit_round_trip_updates_in_place_and_keeps_stack_order` (ab Z. 688) prüft, dass `commit` mit `nid` die Felder ändert, `set(_notes(client))` gleich bleibt und die Reihenfolge im Stapel erhalten bleibt. Neu für die **Liste**: dieselbe Aussage für die Zeile in `#added-list` (Edit der **Mittelkarte** bei 7 Karten: Position, Zähler und Notizmenge unverändert) und dass die Zeile die **Notiz-ID** (`data-note-id`) trägt, mit der `edit/{nid}` aufgerufen wird.
- [ ] Neu: 7 Karten → Liste enthält 7 in Reihenfolge; fremder Stapel/andere Sitzung sieht sie nicht (`test_added_cards_are_scoped_to_session_and_deck` bleibt); gelöschte oder verschobene Notiz verschwindet (`test_deleted_notes_are_removed_without_losing_other_decks`, `test_added_note_follows_card_moved_between_decks` bleiben); Escaping (`<b>x</b>`, `"`, `&`, `$`).

### 8.2 Template: Stapel unten, Hinweis, Liste
- [ ] `_add_added_cards.html.jinja`: Stapel als eine Fläche am Boden (`bottom`-verankert), letzte 5 Karten, Hinweis darunter, Badge als `<button>` mit `aria-expanded`/`aria-controls`. Bei 0 Karten: Leerzustand wie heute, **kein** Hinweis.
- [ ] Liste `#added-list` mit einer `<button>`-Zeile je Karte (`aria-label` mit Vorderseite), serverseitig gerendert.
- [ ] Zeilen sind **echte Buttons**; der Test, der "keine interaktiven Elemente" verlangt, wird in 8.6 ersetzt.
- [ ] Nur daisyUI/Tailwind-Klassen aus dem Build, vollständig ausgeschrieben (keine zusammengesetzten Namen).

### 8.3 CSS
- [ ] Alte `.added-0..3`-Regeln (`top-0`, `origin-top`, Ziel-Variablen) **ersetzen**, nicht ergänzen. `--add-target-*` und `slideToAdded` auf die neue Lage umstellen (Ziel: Boden statt unterhalb der Karte).
- [ ] Hinweis: Fußkante (`box-shadow: 0 4px 0`), Kontaktschatten, wippender Pfeil. Farben aus den daisyUI-Variablen (Mock nutzt `--border-color`/`--bg-surface`; Seite: `border-neo-edge`, `bg-base-200`).
- [ ] Schritt-Leiste: Übergang über `max-height`, `opacity`, `transform` (~350 ms), Klasse `is-browsing`.
- [ ] `@media (prefers-reduced-motion: reduce)` schaltet die neuen Animationen ab.
- [ ] `npm run build:css:app`; Klassen-Test (jede im Template benutzte Klasse existiert im Build) läuft grün.

### 8.4 Client: Gesten, Öffnen, Bearbeiten
- [ ] **Vorab** die offizielle Datastar-Doku zu `data-on:pointerdown`/`pointerup`, `__passive`, und zum Verhalten von `_`-Signalen nach `patch_signals` lesen (die gebündelten Referenzen schweigen dazu). Ergebnis im Plan nachtragen.
- [ ] `window.avPileGesture`: Pointer-Capture, Schwelle 28 px, Tippen (< 6 px), ruft `avOpenList`. Kein Block-Statement in Datastar-Ausdrücken.
- [ ] `avOpenList`: fragt über `avConfirmDiscard` nach, wenn die **neue** Karte Text hat; setzt `$_browsing = true`, verschiebt Fokus in die Liste.
- [ ] Zeilenklick → `@post('/app/add/edit/<nid>?deck=…')`; danach Liste zu, Fokus ins Feld, Schritt-Leiste zurück. **Unveränderte** geladene Karte darf nie nachfragen (Vergleich gegen die geladenen Werte).
- [ ] Escape: im Bearbeiten Abbruch ohne Änderung; in der Liste schließen; Fokus aufs Badge.
- [ ] Sperre während `$saving` (wie heute bei Navigation).

### 8.5 Strings (de und en, `s()`)
- [ ] `app_add_pile_cue` ("Tap or swipe up to edit" / "Tippen oder nach oben wischen zum Bearbeiten"), `app_add_browse_title`, `app_add_browse_back`, `app_add_stack_label` (Sprechtext mit Anzahl), `app_add_row_label` (`Karte {n} bearbeiten: {front}`), `app_add_row_edit`, `app_add_saved`, `app_add_editing_banner`, `app_add_editing_cancel`, `app_add_discard_browse`.
- [ ] Plural/Anzahl wie `app_add_stack_cards_one/other`. `test_i18n_complete` bleibt grün (keine ungenutzten, keine fehlenden Schlüssel).

### 8.6 Tests
- [ ] **Ersetzen:** `test_added_stack_is_noninteractive_and_preserves_draft` (verlangt `to_have_count(0)` für interaktive Elemente und einen wirkungslosen Klick). Neu: Klick auf den Stapel öffnet die Liste; **Entwurf bleibt** und fragt nach.
- [ ] Browser (Playwright, `importorskip`, wie `test_add_browser.py`): öffnen per Tipp, per Hinweis, per Wischen (Maus und **Touch-Emulation** `has_touch`), 12-px-Zug öffnet nicht; Liste scrollt bei 10 Karten; Mittelkarte bearbeiten → Zähler, Reihenfolge, Notizzahl unverändert; Abbruch per `×` und Escape ändert nichts; unveränderte Karte fragt nicht; Schritt-Leiste: Opacity 0 in der Liste, 1 danach; Reload zeigt dieselben Karten.
- [ ] Reduced Motion: Ablauf funktioniert, Animationsdauer ~0.
- [ ] Zwei Sitzungen: Karten der anderen Sitzung erscheinen nicht und sind nicht bearbeitbar (404).
- [ ] Deutsch und Englisch (`live_app` parametrisiert wie `test_added_stack_badge_counts_session_cards`).
- [ ] Bestehende Tests grün: Doppelklick-Add (`test_double_click_add_saves_only_one_note`), Duplikat, Guards, `test_added_cards_overlap_without_horizontal_overflow` (**anpassen**: Lage unten, kein Überlauf bei 375 px).

### 8.7 Browser-Smoke (echter Server)
- [ ] Wegwerf-Server, eigener Chromium-Start mit separatem Profil (Muster Plan 7 §7.6), 375×812 und 509×904, hell und dunkel.
- [ ] Ablauf: 5 Karten anlegen, Stapel unten, Hinweis steht auf dem Boden, wischen, Liste, Karte 2 ändern, speichern, Reload, `scrollWidth == Viewport`, keine Konsolenfehler.
- [ ] Screenshots neben `design/reviewer-redesign/editor-mockup.html` vergleichen (Lage des Stapels, Hinweis, Schritt-Leiste).
- [ ] **Touch** auf einem echten Gerät: nicht prüfbar im Headless; als **nicht verifiziert** ausweisen.

### 8.8 Doku
- [ ] `REFERENCE.md` §2.4: Abschnitt "Seite" ergänzen; `DESIGN.md` §5.E (Porting) auf "umgesetzt" setzen; `CONTEXT.md`: Begriffe Stapel/Liste/Hinweis.
- [ ] Plan 4: den Widerspruch "Edit-last" (falls dort noch genannt) auf diesen Plan verweisen, **keinen** Text still ändern.

## Offene Fragen an den Nutzer
1. **Wie viele Karten maximal in der Liste?** Alle der Sitzung (Vorschlag) oder gedeckelt (z. B. 50) mit Hinweis?
2. **Bearbeiten einer Karte, die schon gelernt wurde?** Heute sind nur Karten der **laufenden Sitzung** editierbar (Server-Sitzungsbindung). Soll das so bleiben (Vorschlag), oder sollen auch ältere Karten des Stapels erscheinen? Letzteres wäre ein größerer Eingriff (Suche, Paging, Rechte).
3. **Zähler nach Löschen in Anki Desktop?** Heute zählt `count` nur noch vorhandene Notizen; unverändert lassen (Vorschlag).

## Akzeptanz
- `/app/add` zeigt die Karten unten gestapelt, mit Hinweis auf dem Boden; Tippen oder Wischen nach oben öffnet die scrollbare Liste **aller** Karten der Sitzung; Schritt-Badges blenden sanft aus und kommen zurück.
- Eine gewählte Karte wird im selben Wizard bearbeitet; Speichern **ersetzt** die Notiz (gleiche ID, gleiche Position, gleicher Zähler, **keine** zweite Notiz in der Collection, gegengeprüft über `live_app.notes()`).
- Abbruch (`×`, Escape, Zurück) verändert nichts; eine unveränderte Karte fragt nie nach; ungespeicherter Text in der neuen Karte fragt vor dem Öffnen nach.
- Nur Karten der eigenen Sitzung und des eigenen Stapels sind sichtbar und bearbeitbar (andere → 404, vorhandene Tests grün).
- Alle Texte über `s()` (de, en); Tastatur und Screenreader bedienbar; `prefers-reduced-motion` respektiert.
- Alte `.added-0..3`-Regeln und der Test für "nicht interaktiv" sind **ersetzt**, nicht daneben stehen gelassen.
- Alle Tests grün, Ruff/ty/Complexipy sauber, kein Eingriff in den alten Client.

## Risiken
| Risiko | Gegenmaßnahme |
|---|---|
| Wischen im Mock nur mit **Maus** getestet | Touch-Emulation im Playwright-Test (`has_touch`); echtes Gerät als **nicht verifiziert** ausweisen. `touch-action: none` auf dem Stapel, sonst scrollt die Seite statt zu wischen |
| Zeiger verlässt den Stapel beim Ziehen (Mock-Befund: `pointerup` ging verloren) | `setPointerCapture` in `avPileGesture`; Test mit 60-px-Zug |
| Datastar-Morph überschreibt Client-Zustand (`$_browsing`, Klassen) beim Commit-Patch | Zustand als Signal, nicht als DOM-Klasse; Test: Commit bei offener Liste ist nicht möglich, Commit danach lässt die Liste zu |
| Lange Sitzungen (hunderte Karten) machen das Fragment groß | Frage 1; Abfrage in 32er-Blöcken bleibt; Liste serverseitig gedeckelt, falls nötig |
| `slideToAdded` zielt auf die alte Lage (oben) | 8.3: Ziel-Variablen auf Boden umstellen; Test bei `reduced_motion` und normal |
| Bestehender Test verlangt "nicht interaktiv" | 8.6: bewusst **ersetzen**, Begründung im Commit |
| Mock und Seite driften (Mock nutzt eigene Variablen) | 8.7: Screenshot-Vergleich; Abweichungen in der Tabelle oben festhalten |
| Fokusring auf dem Badge nach Escape sieht wie ein Fehler aus | Gewollt (Tastatur); im Mock gemessen, kein Layoutfehler |

## Commits
1. `Return all session cards from added_cards`
2. `Render pile on the floor with cue, button badge and list`
3. `Style floor pile, grounded cue and soft step-bar fade`
4. `Add pile gesture, list open and edit flow`
5. `Add added-cards list strings for de and en`
6. `Replace noninteractive stack test with list and edit tests`
7. `Add added-cards list browser smoke`
8. `Document added-cards list in REFERENCE and CONTEXT`
