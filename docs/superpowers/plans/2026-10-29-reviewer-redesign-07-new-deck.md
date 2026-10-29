# Plan 7: Stapel anlegen mit Name und Emoji (`POST /app/decks`)

> Teil von [00-overview](2026-10-27-reviewer-redesign-00-overview.md). Voraussetzung: [Plan 2](2026-10-27-reviewer-redesign-02-deck-list.md) (Deck-Liste), [Plan 6](2026-10-27-reviewer-redesign-06-i18n.md) (`s()`-Strings).

**Ziel:** Auf der Startseite einen neuen Stapel anlegen: Name eingeben, Emoji wählen. Design nach `design/reviewer-redesign/decks-mockup.html` (Abschnitt "New deck", `DESIGN.md` §6). UI mit **daisyUI**-Klassen und Datastar, Server ist die Quelle der Wahrheit.

## Entscheidungen (vom Nutzer bestätigt)

| Frage | Entscheidung | Beleg |
|---|---|---|
| Wo steht das Emoji? | Im **Deck-Namen als Suffix** mit Trenner ` · ` (Leerzeichen, U+00B7, Leerzeichen), z. B. `Biologie · 🧬` | Nutzer: "Emoji als Suffix mit lesbarem aber eindeutigem Trenner" |
| Warum Suffix? | Die Sortierung bleibt wie in Anki: Präfix-Emoji sortieren nach Codepoint **hinter `Zebra`** (Messung unten) | Nutzer: "um die Sortierung beizubehalten" |
| Sortierung der App-Liste | Reihenfolge aus `deck_due_tree()` unverändert, identisch mit Anki Desktop | folgt aus Suffix |

## Messung: Was Anki mit Emoji im Namen macht

Gemessen mit der gebündelten `anki`-Bibliothek (`col.decks.add_normal_deck_with_name`), nicht angenommen.

| Fall | Ergebnis |
|---|---|
| Emoji-Präfix, Flagge (2 Regional Indicators), ZWJ-Familie, Hautton, Variation Selector, Keycap, Subdivision-Flagge, nur Emoji, Emoji mittendrin | Name wird **byte-identisch** gespeichert |
| Name mit `"`, `'`, `\` | unverändert |
| Führende/folgende Leerzeichen | werden **entfernt** (`"  🧬 Trim  "` → `"🧬 Trim"`) |
| NFD-Umlaut (`U` + U+0308) | wird zu **NFC** normalisiert (Ankis eigene Regel, betrifft Emoji nicht) |
| 100+ Zeichen | wird gespeichert (keine Längengrenze durch Anki) |
| `Name::🧬` | **legt ein Unterdeck `🧬` an**, kein Suffix. `::` ist Ankis Unterdeck-Trenner und scheidet aus |
| Emoji-Präfix, Sortierung | `['Apfel','Bio','Zebra','🇩🇪 Berlin','🧬 Mitte']`: Emoji-Decks stehen **am Ende** |
| Suffix-Trenner ` · `, ` \| `, ` — `, ` ~ `, ` @ `, `[..]`, `(..)`, `{..}`, ` #`, ` : ` | alle unverändert gespeichert; `deck:"…"`-Suche parst sie |
| Umbenennen in Anki Desktop ohne Emoji | Emoji ist weg (`Biologie 3`). Kein Datenfehler, die App zeigt dann das Standard-Emoji |
| `decks`-Tabelle | Spalten `id, name, mtime_secs, usn, common, kind`; kein Emoji-Feld, kein Trenner `\x1f` im Namen |

**Folgerung:** Emoji im Namen ist für Anki ungefährlich. Es gibt nichts zu "reparieren"; nur ein Format, das die App eindeutig lesen und schreiben muss.

## Format: `<Name> · <Emoji>`

```
Biologie · 🧬            -> ("Biologie", "🧬")
German B1 Vocab · 🇩🇪    -> ("German B1 Vocab", "🇩🇪")
A · B · 🧬               -> ("A · B", "🧬")          letzter Trenner gewinnt
Biologie · 🧬::Zellen    -> Wurzel "Biologie · 🧬"    nur der Wurzelname trägt das Emoji
```

**Parser-Regel** (`split_emoji_suffix`): `name.rpartition(" · ")`; gültig **nur**, wenn
1. der Kopf nach `strip()` nicht leer ist und
2. der Rest **genau ein** Emoji-Graphem ist (`_emoji_end(rest) == len(rest)` und `> 0`).

Sonst bleibt der Name unverändert und das Standard-Emoji `🗂️` greift. Geprüft gegen bestehende Namen: `Mathe · Klasse 5`, `Chemie · 🧪 Labor`, `Vokabeln · Spanisch`, `Algebra ·`, `· 🧬`, `Bio · 🧬🧪` (zwei Emoji), `Bio · x`, `Bio·🧬` (ohne Leerzeichen) und `Bio · 🧬 ` werden **nicht** zerlegt.

**Restrisiko:** Ein Nutzer, der selbst einen Stapel `Reise · ✈️` nennt, bekommt dort das Emoji als Symbol gezeigt. Das ist gewollt und eindeutig; ein eigener Marker (z. B. Zero-Width-Zeichen) würde in Anki Desktop unsichtbar mitkopiert und beim Suchen stören.

## Abweichungen von Plan 2 (bewusst, begründet)

| Plan 2 | Jetzt | Grund |
|---|---|---|
| Emoji als **Präfix** (`🧬 Biologie`) | **Suffix** (`Biologie · 🧬`) | Sortierung wie Anki; Nutzerentscheidung |
| `split_emoji(name)` zerlegt Präfix | `split_emoji(name)` zerlegt **Suffix** | gleiche Signatur `(emoji, anzeige_name)`, Aufrufer unverändert |
| Bestehende Präfix-Namen werden zerlegt | Präfix-Namen bleiben **ungeteilt** mit Standard-Emoji | Clean Cutover; kein zweites Format, keine Doppelzerlegung, keine Migration (keine Bestandsdaten) |
| Tests mit Präfix-Fällen | Tests werden **ersetzt**, nicht ergänzt | keine toten Fälle |

**Keine Migration (Nutzerentscheidung):** Es gibt in Produktion keine Stapel mit Emoji. Deshalb entfällt eine Umbenennung alter Präfix-Namen samt Banner, Vorschau und Route. Wer dennoch einen Präfix-Stapel hat, sieht ihn mit `🗂️` und vollem Namen. Der Review-Kopf (`view.deck`, `study.py:179`) und der Add-Badge (`add.py:_deck_name`) zeigten den **rohen** Namen; siehe Aufgabe 7.4a.

## Vorgabe aus Design (`DESIGN.md` §6, `decks-mockup.html`)

| Element | Verhalten |
|---|---|
| Einstieg | schwebender gelber Button **New deck** und Button im Leerzustand der Suche (Name aus Suchfeld vorbelegt) |
| Dialog | Bottom-Sheet: Handle, Backdrop, Escape und Hintergrund schließen, Fokus zurück zum Auslöser, `inert` im geschlossenen Zustand |
| Vorschau | Kachel mit Emoji und Namen, live |
| Name | max. 40 Zeichen, Zähler wird bei 40 rot, leer/nur Leerzeichen/Duplikat sperrt **Create deck** mit Fehlertext |
| Emoji | kuratierte Auswahl, vier Kategorien (Study, Words, Science, Fun) je 18, `radiogroup`, keine System-Tastatur nötig |
| Neuer Stapel | oben in der Liste, 0 fällig / 0 neu / 0 %, Einblend-Animation, Toast |
| Bewegung | `prefers-reduced-motion` schaltet Animationen ab |

## Abweichungen vom Mockup (bewusst)

| Mockup | Umsetzung | Grund |
|---|---|---|
| ID = Slug des Namens (`deck`, `deck-2`) | Echte Anki-Deck-ID aus `add_normal_deck_with_name` | Server vergibt IDs; Slug-Kollisionen (Emoji-only-Namen) entfallen |
| Duplikat-Prüfung im Browser über `data-name` | **Server** prüft (Anki-Regel), Client zeigt nur Hinweis | Quelle der Wahrheit; Anki vergleicht normalisiert und ohne Beachtung von `::` |
| Neuer Stapel per `createElement` | Server rendert die Zeile (`_deck_row.html.jinja`) und patcht sie ein | Datastar "fat morph", kein zweiter Renderer |
| Emoji-Raster per JS | Server rendert das Raster einmalig, Datastar-Signal `emoji` | kein Client-Template, ein Quelltext für Emoji-Liste |
| Toast mit JS-Timer | Server patcht ein `#toast`-Element, CSS blendet es aus | kein Timer-State im Client |

## Datastar-Konzept (nach den gelesenen Referenzen)

Geprüft in `references/attributes.md`, `modules/core.md`, `modules/gotchas.md`, `references/patterns.md`.

- **Scope (Gotcha #23):** `data-signals` auf einem Vorfahren von Suche, Liste und Dialog. Plan 2 hat `q` dort schon. Ergänzen: `{q: '', newName: '', newEmoji: '📚', newOpen: false, creating: false, newError: ''}`.
- **Bindung:** `<input data-bind:new-name>` (hyphen → `$newName`, camelCase-Standard, Gotcha Signalnamen). Emoji-Radios mit `data-bind:new-emoji` auf `<input type="radio" value="…">` (Muster aus `guide-ui-patterns-1.md`).
- **Sperren:** `data-attr:disabled="!$newName.trim() || $creating"` am Create-Button (Muster `patterns.md`).
- **Zähler und Vorschau:** `data-text="$newName.length + ' / 40'"`, Vorschau-Name `data-text="$newName.trim() || …"`. Nur Anzeige, kein Zustand.
- **Absenden:** `data-on:click="@post('/app/decks')"` mit `data-indicator:creating` (Muster `patterns.md`: "POST with loading indicator"). Enter im Feld: `data-on:keydown__enter` (belegt in `modules/core.md`). Kein `if (…) { … }` in Ausdrücken (Gotcha #24); Verzweigung per Ternär oder `;`-Kette.
- **Antwort (SSE):** `datastar-patch-elements` für die neue Zeile (`<article id="deck-<id>">`, Einfügen vor der ersten Zeile per `selector`/`mode`), den Toast und `datastar-patch-signals` für `{newOpen: false, newName: '', newEmoji: '📚', newError: ''}`. Bei Fehler **nur** `newError` patchen, Dialog bleibt offen.
- **IDs (Gotcha #3):** Dialog `id="deck-sheet"`, Liste `id="deck-list"`, Toast `id="toast"`, jede Zeile `id="deck-<id>"`.
- **FOUC (Gotcha #4):** `style="display:none"` an `data-show`-Elementen.
- **Kein optimistisches UI (Tao):** Die Zeile erscheint erst nach der Serverantwort. Ladeanzeige über `creating`.
- **Suche:** Die vorhandenen `data-show`-Ausdrücke in `decks.py` (`_views`, `_no_match`) enthalten nach dem Patch die **neue Zeile nicht**, weil `no_match` die Namen als Literal einbettet. Siehe Aufgabe 7.3.

## Dateien

| Datei | Zweck |
|---|---|
| `ankiweb/core/app_client/decks.py` | `split_emoji` auf Suffix umstellen; `join_emoji(name, emoji)`; `create_deck(col, name, emoji) -> DeckRow`; `DeckNameError` |
| `ankiweb/core/app_client/emoji_picker.py` | Konstante `EMOJI_GROUPS` (vier Gruppen à 18), reine Daten |
| `ankiweb/adapters/inbound/http_app/decks.py` | `POST /app/decks` (SSE), Router erweitern |
| `.../templates/app/decks.html.jinja` | schwebender Button, Dialog-Einbindung |
| `.../templates/app/_deck_sheet.html.jinja` | **neu:** Bottom-Sheet mit Vorschau, Name, Emoji-Raster, Create |
| `.../templates/app/_deck_row.html.jinja` | unverändert; wird für die neue Zeile wiederverwendet |
| `ankiweb/core/app_client/strings.py` | Strings `app_decks_new`, `app_decks_new_title`, `app_decks_name`, `app_decks_pick_emoji`, `app_decks_create`, `app_decks_created`, `app_decks_name_taken`, `app_decks_name_invalid`, Emoji-Gruppennamen, **de und en** |
| `shell_src/app-client.css` | nur was daisyUI nicht liefert: Dock-Verlauf, `emoji-pop`, `deck-drop`, Reduced-Motion |
| `tests/app_client/test_decks.py` | Suffix-Parser ersetzt Präfix-Fälle; `create_deck` |
| `tests/app_client/test_decks_create_routes.py` | **neu:** POST-Route |
| `tests/app_client/test_decks_create_browser.py` | **neu:** Playwright-Smoke (`importorskip`) |
| `CONTEXT.md` | Glossar: Emoji-Suffix-Format |

## daisyUI-Klassen (gegen 5.7.47 geprüft)

Alle Klassen unten wurden in `node_modules/daisyui/components` gefunden. **Nicht** verwenden (existieren nicht oder sind in v5 überflüssig): `input-bordered` (`input` ist in v5 schon umrandet), `join`/`join-item` (nicht vorhanden).

| Baustein | Klassen |
|---|---|
| Dialog | `modal modal-bottom`, `modal-box`, `modal-action`, `modal-backdrop`; Öffnen per `data-class:modal-open="$newOpen"`, `data-attr:inert`, `data-attr:aria-hidden` (**exakt das Muster von `_review_sheet.html.jinja`**) |
| Schließen-Knopf | `btn btn-sm btn-circle btn-ghost` mit `aria-label` |
| Name-Feld | `fieldset` + `fieldset-legend` + `input w-full` (eine `label`/`for`-Verknüpfung) |
| Fehlertext | `alert alert-error` mit `role="alert"` oder `label text-error` |
| Kategorien | `tabs tabs-box` + `tab` + `tab-active` (`role="tablist"`/`tab`) |
| Emoji-Kacheln | `btn btn-square` je Emoji (`aria-checked`); Auswahl `btn-accent` über `data-class` |
| Create | `btn btn-accent btn-block` (wie `#btn-show-ans`), `neo-press` aus dem Projekt |
| Einstieg | `btn btn-accent btn-block neo-press` im festen Dock |
| Toast | `toast toast-top toast-center` + `alert` |
| Klassen **vollständig ausschreiben** | keine zusammengesetzten Namen (`btn-{{ x }}`), sonst fehlt die Klasse im Build |

## Aufgaben

### 7.1 Kern: Suffix-Format
- [ ] `split_emoji` auf `rpartition(" · ")` umstellen (Parser-Regel oben). `DEFAULT_EMOJI` bleibt.
- [ ] `join_emoji(name, emoji) -> str`: `f"{name.strip()} · {emoji}"`, wenn `emoji` ein einzelnes Emoji-Graphem ist, sonst `ValueError`.
- [ ] **Tests ersetzen:** Die ~17 Präfix-Fälle in `test_split_emoji` werden durch Suffix-Fälle ersetzt: Flagge, ZWJ, Hautton, Keycap, Variation Selector, Subdivision-Flagge, mehrere Trenner, Nicht-Treffer (`Mathe · Klasse 5`, `Algebra ·`, `· 🧬`, `Bio · 🧬🧪`, `Bio · x`, `Bio·🧬`, `Bio · 🧬 `), Präfix-Namen bleiben ungeteilt.
- [ ] Rundreise-Test: `split_emoji(join_emoji(n, e)) == (e, n)` für jede Emoji der Auswahl und für Namen mit `·`, `::`-freien Sonderzeichen, `'`, `"`, `\`.

### 7.2 Kern: `create_deck`
- [ ] `create_deck(col, name, emoji) -> DeckRow` über `col.decks.add_normal_deck_with_name(join_emoji(name, emoji))`.
- [ ] **Vorab prüfen**, nicht den Fehler fangen: Name nach `strip()` nicht leer, höchstens 40 Zeichen **ohne** Emoji, kein `::` im Namen (würde ein Unterdeck anlegen), Emoji ∈ `EMOJI_GROUPS` (nur die kuratierte Auswahl, kein beliebiger String vom Client), kein vorhandener Wurzelname (case-insensitiv, **NFC-normalisiert** wie Anki).
- [ ] `DeckNameError(kind)` mit `kind ∈ {"empty", "too_long", "invalid", "taken"}`; Route übersetzt in Strings, Kern kennt keine Texte.
- [ ] Die Zeile zurückgeben: neue ID, `due=0`, `new=0`, `progress_pct=0`, `emoji`, Anzeigename.
- [ ] Änderung über `service.run_op(lambda col: ..., initiator="app")` (Undo und Änderungsbenachrichtigung wie überall). Das Muster steht in `http_datastar/deckbrowser.py` (`create_deck`); es wird **nachgebaut, nicht importiert**: `http_app` importiert aus `http_datastar` bisher nur `common.error_response` (`add.py:21`, `review.py:20`), und diese Grenze wird nicht erweitert.
- [ ] Tests (`temp_collection`): Anlegen liefert Zeile; Anki speichert exakt `join_emoji(...)`; `taken` auch bei `german b1 vocab`; NFD-Eingabe kollidiert mit NFC-Bestand; `::` abgelehnt; 41 Zeichen abgelehnt, 40 ok; Emoji außerhalb der Auswahl abgelehnt; Sortierung: neuer Name `Zebra · 🧬` steht in `deck_rows` **nach Anki-Reihenfolge**, nicht am Ende.

### 7.3 Route `POST /app/decks`
- [ ] Signale lesen wie `review.py`: `payload: ReadSignals = None` aus `datastar_py.fastapi` (nicht aus `http_datastar`); Felder `newName`, `newEmoji`. Fehlende oder falsch typisierte Felder → Fehlerpfad `invalid`, kein 500.
- [ ] Erfolg: SSE mit (1) Zeile als `<article id="deck-<id>">` vor die Liste, (2) Toast-Fragment, (3) Signale zurücksetzen und `newOpen: false`. Fehler: SSE mit **nur** `newError` (Text aus `s()`), Status 200 (SSE), Dialog bleibt offen.
- [ ] **Suche nach dem Patch:** `decks.py` bettet `no_match` mit allen Namen ein. Nach dem Einfügen ist das veraltet. Lösung: bei Erfolg den Container `#deck-list`-Rahmen samt `no_match` neu rendern (fat morph) statt nur die Zeile. Test: neue Zeile ist per Suche findbar, Leerzustand erscheint nicht fälschlich.
- [ ] Passwort-Gate: ohne gültiges Cookie 303 (wie die anderen `/app`-Routen, `test_add_routes.py::test_add_routes_follow_password_gate`). Test.
- [x] **Cross-Site-Schutz (gemessen, behoben vor diesem Plan):** Vorher legte `POST /app/add/commit` bei fremdem `Origin`, `text/plain` und `Sec-Fetch-Site: cross-site` jeweils eine Notiz an (5 von 5 Schreibvorgängen, in der Collection gezählt). Es gab keine Origin- oder Fetch-Metadata-Prüfung; allein `SameSite=lax` auf `app_sid` und dem Auth-Cookie schützte. Jetzt lehnt die Router-Abhängigkeit `http_app/origin_guard.py` (an `build_app_router`) jeden Nicht-GET mit `Sec-Fetch-Site` außer `same-origin`/`none` oder mit einem `Origin` ungleich `Host` mit 403 ab; das gilt automatisch auch für `POST /app/decks`. **Für diese Route:** kein eigener Header-Check, kein Sonderfall. Der Test `test_decks_create_routes.py` enthält einen Cross-Site-Fall (fremder `Origin` → 403, **kein** neuer Stapel in `col.decks`), der zuerst fehlschlägt, wenn die Abhängigkeit fehlt.
- [ ] Anführungszeichen, `<`, `&` im Namen werden im HTML **escaped** und in JS-Literalen per `_js_literal` kodiert. Tests mit `'`, `"`, `\`, `<b>x</b>`, `$`.

### 7.4 Dialog und Einstieg (Templates, daisyUI)
- [ ] `_deck_sheet.html.jinja` mit den Klassen oben; Öffnen/Schließen **identisch** zum Review-Sheet (`inert`, `aria-hidden`, `data-class:modal-open`). Escape: `data-on:keydown__escape` am Dialog; Backdrop-Klick schließt.
- [ ] Fokus: beim Öffnen ins Namensfeld, beim Schließen zurück zum Auslöser (kleine, getestete Funktion in `shell_src/app/decks.js`, **kein** Block-Statement in Datastar-Ausdrücken).
- [ ] Emoji-Raster serverseitig aus `EMOJI_GROUPS` rendern; Kategorien als `tab`-Buttons (`data-show` je Gruppe, alle Gruppen im DOM, Zustand bleibt erhalten).
- [ ] Vorschau-Kachel zeigt gewähltes Emoji und `$newName`; Platzhalter, wenn leer.
- [ ] Schwebender Button im Dock mit Safe-Area (`pb-[env(safe-area-inset-bottom)]`), Liste bekommt unten Abstand (`pb-30`), damit die letzte Karte frei bleibt (Mockup-Messung: 692 px gegen 738 px).
- [ ] Leerzustand der Suche: Button **+ New deck** öffnet den Dialog und setzt `$newName` auf `$q` (gekürzt auf 40). `data-on:click` mit `;`-Kette.
- [ ] i18n: alle Texte über `s()`; Strings de und en; der Test `test_i18n_complete` muss grün bleiben.

### 7.4a Review-Kopf und Add-Badge
- [ ] `view.deck` (`study.py:179`) und `_deck_name` (`add.py`) liefern heute den rohen Namen. Beide zeigen künftig den **Anzeigenamen** aus `split_emoji(name)[1]` und das Emoji aus `[0]` davor (Mockup `#card-deck` und `#deck-chip` zeigen "Emoji und Name", `REFERENCE.md` §2.4/§2.5). Sonst stünde `Biologie · 🧬` im Klartext neben dem Emoji der Startseite.
- [ ] Nur **Anzeige**: die Collection wird nicht verändert, `session.deck_id` und alle Abfragen laufen weiter über die ID.
- [ ] Tests: Deck `Biologie · 🧬` zeigt im Review-Kopf `🧬` und `Biologie`; Deck ohne Suffix zeigt `🗂️` und den vollen Namen; HTML-Escaping bleibt (`<b>x</b> · 🧬`).

### 7.5 Styling
- [ ] Nur das nötige CSS: Dock-Verlauf, `emoji-pop`, `deck-drop`, `@media (prefers-reduced-motion: reduce)`. Farben aus den daisyUI-Theme-Variablen, kein hartes Gelb (`btn-accent`).
- [ ] `npm run build:css:app`; Klassen-Test aus Plan 1/2 (jede im Template benutzte Klasse existiert im Build) läuft grün.
- [ ] Dunkelmodus nur über `prefers-color-scheme`, kein Schalter.

### 7.6 Browser-Smoke
- [ ] Wegwerf-Server, Headless-Chromium 375x812, hell und dunkel, **eigener Chromium-Start** mit separatem Profil (der geteilte Browser hat bei der Mockup-Prüfung sein Rendering eingestellt; Muster: `app.path` + `--user-data-dir`).
- [ ] Ablauf: öffnen, Emoji wählen, Namen tippen, Duplikat (Fehlertext, Dialog bleibt), leer (Button gesperrt), anlegen per Enter und per Button, Zeile oben, Toast, Dialog zu, Fokus zurück.
- [ ] Nach dem Anlegen in **Anki** gegenprüfen: `col.decks.name(id) == "Name · 🧬"`; Suche `deck:"Name · 🧬"` findet 0 Karten ohne Fehler.
- [ ] Zwei Stapel mit gleichem Emoji, verschiedenen Namen; Emoji-only-Name wird abgelehnt (leerer Anzeigename), **nicht** als `deck` gespeichert.
- [ ] Suche findet den neuen Stapel; `scrollWidth == 375`; keine Konsolenfehler.
- [ ] Screenshot neben `decks-mockup.html`.

## Akzeptanz
- Ein Stapel lässt sich mit Name und Emoji anlegen; Anki speichert `"<Name> · <Emoji>"`. Für NFC-Eingaben byte-identisch; NFD-Eingaben normalisiert Anki zu NFC (gemessen: `e` + U+0301 wird U+00E9), die Zeile zeigt den gespeicherten Namen.
- Die Liste zeigt Name und Emoji getrennt; **Sortierung entspricht Anki Desktop**.
- Duplikate, leere Namen, `::`, zu lange Namen und fremde Emoji werden vom **Server** abgelehnt; der Dialog bleibt mit Fehlertext offen.
- Keine IDs aus Slugs; Zeile trägt die echte Deck-ID, Learn und Edit/Add führen dorthin.
- Alle Klassen sind daisyUI/Tailwind aus dem Build; keine eigenen Komponenten-Stile außer den genannten.
- Alle Tests grün, Ruff/Complexipy sauber, kein Eingriff in den alten Client.

## Risiken
| Risiko | Gegenmaßnahme |
|---|---|
| Nutzer benennt in Anki Desktop um und verliert das Emoji | Kein Datenfehler; Standard-Emoji greift. In `CONTEXT.md` dokumentieren |
| Eigener Name enthält ` · <Emoji>` und wird ungewollt zerlegt | Eindeutig und gewollt (Parser verlangt genau ein Emoji); Test dokumentiert das |
| Unterdeck `Name::Kind` und Emoji | Nur der **Wurzelname** trägt das Emoji; `::` im Eingabenamen wird abgelehnt |
| Veraltetes Such-Literal nach dem Patch | Aufgabe 7.3: Listenrahmen samt `no_match` neu rendern; Test |
| Zwei gleichzeitige Anlegevorgänge | Anki vergleicht nur **volle** Namen: `Bio · 🧬` und `Bio · 🌱` kollidieren dort nicht. Die Anzeigenamen-Prüfung in `create_deck` und die Serialisierung über `service.run_op` verhindern das; der Fehlerpfad `taken` greift |
| Emoji-Darstellung unterscheidet sich je System | Nur in macOS-Chromium geprüft; Kacheln nutzen System-Emoji-Schrift, kein Bildsatz |
| Systemtastatur verdeckt das Sheet auf Geräten | **Nicht geprüft** (nur Headless). Auf echtem Gerät testen, `max-h` mit `dvh` |
| Geteilter Headless-Browser friert ein | Eigener Chromium-Start im Smoke (Aufgabe 7.6) |

## Commits
1. `Switch emoji convention from prefix to suffix in deck names`
2. `Add create_deck core with server-side name validation`
3. `Add POST /app/decks with SSE patch`
4. `Add new-deck sheet and floating button with daisyUI`
5. `Add new-deck strings for de and en`
6. `Add create-deck route tests`
7. `Add create-deck browser smoke test`
8. `Document emoji suffix format in CONTEXT.md`
