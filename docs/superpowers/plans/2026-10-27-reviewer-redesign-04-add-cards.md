# Plan 4: Karten hinzufügen mit manueller Eingabe (`/app/add`)

> Teil von [00-overview](2026-10-27-reviewer-redesign-00-overview.md). Voraussetzung: [Plan 1](2026-10-27-reviewer-redesign-01-independent-client.md). Unabhängig von Plan 2 und 3 (Review nutzt später die erzeugten Karten).

**Ziel:** Wizard nach `editor-mockup.html`: Front → Back (+ optional Hint, Example) → Preview → "Add to Stack", Karten-Stapel, Edit-last-card, Finish. Karten werden als Noten des dedizierten Typs `AnkiWeb Vocab` gespeichert.

## Befund: das Mockup speichert nichts (belegt)

`editor-mockup.html`: `state.cardStack` ist ein JS-Array (`commitCardToStack`, `cardStack.push`); kein `fetch`, kein Storage. `finishSession` setzt nur zurück und öffnet das Summary-Modal. "Finish and Save All" ist im Design ein No-op.

**Entscheidung: pro Commit persistieren.**

| Aspekt | Pro Commit (gewählt) | Erst bei Finish |
|---|---|---|
| Datenverlust bei Reload/Tab-Close | keiner | Stapel weg |
| Edit-last | `updateNote` auf gespeicherter Note | braucht Pending-Store (Server-Session oder Browser-Storage; letzteres verletzt "Server ist Quelle der Wahrheit") |
| Finish | reine Navigation + Zusammenfassung | Batch-`addNotes`, Teilfehler-Handling |
| Passt zu Anki-Modell | ja (Note existiert sofort) | nein |
| Preis | Edit-last erzeugt Undo-/Mod-Time-Eintrag; Duplikatprüfung sofort | |

Folgen fürs Design (ins `DESIGN.md` §5.D/§6 nachtragen): "Pop to editor" = Karte bleibt gespeichert und wird beim Speichern **aktualisiert**; "Discard"-Guard gilt nur für ungespeicherten Text im aktuellen Formular. Button "Finish and Save All" → **"Finish"** (nichts mehr zu speichern).

## Vorgaben aus Design (DESIGN §5, REFERENCE §2.4)

- Pflicht (View-Regel): Front, Back. Optional: Hint, Example. Server prüft nur leer/Duplikat (`check_addable`, belegt `_helpers.py:43`), also prüft die View Front/Back selbst.
- **Escaping beim Speichern** (DESIGN §5.F, Test-Befund §10): Server escaped nicht → View escaped `& < >` vor `addNote`. `*word*` bleibt unverändert gespeichert, Umwandlung zu `<mark>` clientseitig nach Render (Plan 3).
- Eingabe ist Klartext; Anzeige im Editor-Preview ebenfalls über Escape-first-Logik (`CardRender`-Prinzip), **nicht** über rohes Server-HTML.
- Note-Type `AnkiWeb Vocab`: 4 Felder `Front, Back, Hint, Example` (Reihenfolge fix), Template `Card 1` wie DESIGN §5.F, `css == ""`. Kein `<style>`/`<script>` in Templates.
- Unsaved-Text-Guard (`confirmDiscard`): wenn Front/Back/Hint/Example nicht leer, `confirm()` vor Verlassen/Edit-last/Deck-Wechsel. Kein Guard während Commit.
- Deck: `/app/add?deck=<id>`; unbekannt/fehlend → 303 `/app/`. Chip → `/app/` , Switch Study → `/app/review?deck=<id>`.

## Entscheidungen

| Thema | Wahl | Begründung |
|---|---|---|
| Wizard-Zustand | Datastar-Signale (`step`, `front`, `back`, `hint`, `example`) + `data-bind`; Schritte per `data-show` | Reine UI-Zustände sind erlaubte Signale (Tao: sparse, nur UI + Formular) |
| Speichern | `POST /app/add/commit` (Signale als JSON) | Server validiert, escaped, fügt hinzu |
| Stapel | Server rendert `#stack` aus den **in dieser Sitzung** hinzugefügten Noten-IDs (Session-Liste, wie `StudySession` in Plan 1), nicht aus Suche | "Stapel" = diese Sitzung, nicht alle Karten des Decks |
| Edit-last | `POST /app/add/edit/{nid}` lädt Felder in Signale (Unescape!), nächster `commit` mit `nid` → `update_note` | Note existiert bereits |
| Animation | Keyframes aus Mockup in `app-client.css` (`slideToStack`, `popInFreshCard`, `stackPillPop`), ausgelöst per vollständiger Klasse nach SSE-Patch (Neustart via `data-ts`, Gotcha #19); `motion-reduce:animate-none` | Gotcha #15/#19 |
| Note-Type-Anlage | `ensure_vocab_model(col)` beim ersten `GET /app/add` (idempotent) | Kein manueller Setup-Schritt; wiederverwendet `createModel`-Logik |
| Wiederverwendung | `_create_model`-Logik **nicht** aus `core.ankiconnect_actions.actions.models` importieren (privat); eigene 12 Zeilen in `core/app_client/vocab.py` | Kein Zugriff auf Underscore-Funktion eines anderen Moduls; Kern bleibt klein |

## Escaping: Round-Trip ist die Falle

Speichern: `html.escape(value, quote=False)` (nur `& < >`; Anführungszeichen unnötig im Textknoten). **Beim Edit-last:** gespeicherten Feldwert **unescapen** (`html.unescape`) bevor er ins Formular geht, sonst doppeltes Escaping (`&amp;lt;`). Zeilenumbrüche: Eingabe-Textarea kann `\n` enthalten → als `<br>` speichern? **Entscheidung:** `\n` → `<br>` beim Speichern, `<br>` → `\n` beim Laden (sonst kollabiert Anki-HTML Umbrüche). Round-Trip-Test mit `a < b & c`, `*x*`, Umbruch, Emoji.

## Dateien

| Datei | Zweck |
|---|---|
| `core/app_client/vocab.py` | `NOTETYPE_NAME`, `ensure_vocab_model`, `escape_field`, `unescape_field`, `add_vocab_note`, `update_vocab_note`, `read_vocab_note` |
| `http_app/add.py` | Routen |
| `templates/app/add.html.jinja`, `_add_stack.html.jinja`, `_add_summary.html.jinja` | Seite, Stapel, Zusammenfassung |
| `static/app/add.js` | nur Zeichenzähler-freie Helfer: Guard-Funktion, Chip-Insert (Umlaute/Artikel), Focus-Management |
| `shell_src/app-client.css` | nur Eigenes: Keyframes (`slideToStack`, `popInFreshCard`, `popCardUp`, `stackPillPop`), Stapel-Offsets/Rotationen als Utility-Klassen `.stack-0 … .stack-3` |
| `tests/app_client/test_vocab.py`, `test_add_routes.py`, `test_add_browser.py` | |

## Aufgaben

### 4.1 Kern `vocab.py` (TDD)
- [ ] `ensure_vocab_model`: legt Typ an, falls Name fehlt; sonst gibt vorhandenen zurück. Vergleicht Feldnamen **und** Template-Text; weicht ab → `ValueError` mit klarer Meldung (kein stilles Überschreiben fremder Typen mit gleichem Namen).
- [ ] `add_vocab_note(col, deck_id, front, back, hint="", example="") -> note_id`: View-Regel (`front.strip()` und `back.strip()` nicht leer, sonst `ValueError`), escape, `check_addable` aus `core.ankiconnect_actions.actions._helpers` (Core importiert Core, erlaubt), Duplikat → `DuplicateNote`.
- [ ] `update_vocab_note(col, nid, ...)`: nur Typ `AnkiWeb Vocab`, sonst `ValueError`; gleiche Validierung; Duplikatprüfung gegen **andere** Noten (eigene Note darf unverändert bleiben).
- [ ] `read_vocab_note(col, nid) -> dict` mit `unescape_field`.
- Tests:
  - [ ] Typ: 4 Felder in Reihenfolge, `css == ""`, Template-Strings exakt wie DESIGN §5.F (Regression gegen Drift), Idempotenz, Konflikt-Fehler.
  - [ ] Leeres Hint/Example → gerenderte Karte ohne `av-hint`/`av-example` (`card.question()` / `answer()`), mit Werten vorhanden (DESIGN §5.F Befund).
  - [ ] Escape-Round-Trip (siehe oben), `*word*` bleibt wörtlich.
  - [ ] Front nur Whitespace → `ValueError`; Duplikat → `DuplicateNote`; Edit ohne Änderung kein Duplikatfehler.
  - [ ] Update auf Note fremden Typs → `ValueError`.
  - [ ] Karte erscheint in `deck_due_tree`-Zählern des Ziel-Decks (`new_count`).

### 4.2 Seite und Wizard
- [ ] `data-signals="{step: 1, front: '', back: '', hint: '', example: '', nid: 0, count: 0, error: ''}"` am Wurzelelement (Gotcha #23).
- [ ] Drei `<section>` mit `data-show="$step === N"` und `style="display:none"` (Gotcha #4). Step-Pills als Buttons mit `data-on:click="$step = N"`; Sprung nach 3 nur wenn Front und Back nicht leer (Ausdruck: `$front.trim() && $back.trim() ? ($step = 3) : ($error = 'Front and back are required')`, Ternär statt `if`).
- [ ] Textareas `data-bind:front` usw.; Zeichenzähler `data-text="$front.length"`.
- [ ] Enter-Shortcut: `data-on:keydown__window="window.avAddKey(evt)"` (Delegation, Gotcha #24); Funktion beachtet `isComposing`, Shift+Enter in Textarea = Umbruch.
- [ ] Optionale Felder als `<details>`; Chips (`der/die/das`, `ä ö ü ß`, `Noun/Verb/Adj/(Plural:)`) schreiben per `data-on:click` in das jeweilige Signal (Cursorposition-Einfügen = Funktion in `add.js`).
- [ ] Preview (Step 3): rendert aus Signalen mit Escape-first (`data-text` escaped automatisch) und Highlight für Example: Datastar `data-html` existiert nicht in den belegten Referenzen → **Preview vom Server rendern lassen** (`POST /app/add/preview` → patcht `#preview`), nutzt denselben `escape_field` + Highlight-Funktion wie Speichern. Verhindert Drift Preview/Gespeichert.
- [ ] Commit-Button: `data-on:click="@post('/app/add/commit')"`, `data-indicator:saving`, `data-attr:disabled="$saving"` (verhindert Doppelklick = Doppelnote; Server prüft zusätzlich Duplikat).
- [ ] Antwort SSE: patcht `#stack`, `#hud-count`, setzt Signale zurück (`front: ''`, … `step: 1`, `nid: 0`, `count`), Toast "Card #N added to stack! 🗂️".
- [ ] Fehler: Duplikat/leer → `error_response`, Formular bleibt unverändert.
- [ ] Stapel-Ansicht: letzte Karten mit Offsets/Rotationen aus `STACK_PRESETS` (Mockup), oberste markiert `TOP CARD ↩`; Peek-Bar.
- [ ] Edit-last: Klick auf oberste Karte/Peek/HUD-Pill → Guard (Funktion `window.avConfirmDiscard`) → `@post('/app/add/edit/{nid}')` → patcht Signale (`front`, `back`, …, `nid`, `step: 1`) und blendet `<details>` je nach Inhalt auf; Toast "Editing…". Commit mit `nid != 0` aktualisiert und lässt Stapelposition.
- [ ] Finish: zeigt Summary-Modal mit Anzahl (`role="dialog"`, `aria-modal`, Fokus-Falle, Escape); Buttons "Keep adding" / "Start studying" → `/app/review?deck=<id>`. Guard bei ungespeichertem Text. Leerer Stapel → Toast "Add a card to your stack first."
- [ ] Exit/Chip/Study-Link: `onclick`-frei; Guard über `data-on:click="window.avGuardNav(evt)"` das bei Abbruch `evt.preventDefault()` aufruft. `beforeunload`-Warnung bei Tab-Schließen mit ungespeichertem Text ergänzen (Mockup hat nur den Klick-Guard; **Erweiterung**, klein, optional).

### 4.2b Styling mit daisyUI und Tailwind (Vorlage `editor-mockup.html`)
- [ ] Schritte: daisyUI `steps steps-horizontal` (Pills `step step-primary` per `data-class`), aktive Karte = `card` mit `neo-press`. Textareas = `textarea textarea-bordered textarea-lg w-full`; Zähler `text-xs opacity-70`.
- [ ] Optionale Felder: daisyUI `collapse collapse-arrow` mit `<details>`-Verhalten (`<details class="collapse">`); Chips = `btn btn-xs btn-outline`.
- [ ] Preview: `card` mit Abschnitts-`badge`; Hint/Example-Abschnitte nur gerendert, wenn gefüllt (Server-Fragment).
- [ ] Primär-Button `btn btn-success btn-block btn-lg` (Add to Stack), Zurück `btn btn-ghost`. Stack-Pill im HUD = `badge badge-lg` mit Pop-Klasse.
- [ ] Stapel: absolut positionierte `card`-Layer mit `.stack-0 … .stack-3` (Offsets +32/+64/+96 px, Rotationen -3.2/+2.8/-2.0°), oberste mit `badge badge-accent` "TOP CARD". Peek-Bar = `btn btn-block`.
- [ ] Summary = daisyUI `modal` mit `modal-box`, `role="dialog"`, `aria-modal`, Fokus-Falle über `window.avModalKey`; Öffnen per Signal `summaryOpen` und `data-class:modal-open`.
- [ ] Toast wie Plan 3. Safe-Area unten für die Aktionsleiste.

### 4.3 Tests
Routen (`TestClient`):
- [ ] Commit legt Note im Ziel-Deck an, Typ `AnkiWeb Vocab`, Felder escaped; Stack-Fragment enthält neue Karte; Zähler +1.
- [ ] Commit ohne Front/Back → Fehler-Signal, keine Note.
- [ ] Doppelter Commit (gleicher Inhalt) → Duplikatfehler, genau eine Note.
- [ ] Edit-last: `edit/{nid}` liefert unescapte Werte; Commit mit `nid` ändert Note, legt keine neue an.
- [ ] `edit/{nid}` einer Note aus anderer Sitzung/anderen Typs → 404/409 (Stapel-Liste ist Autorisierungsgrenze).
- [ ] Unbekanntes Deck → 303 `/app/`. Passwort-Gate.
- [ ] XSS: Front `<img src=x onerror=alert(1)>` erscheint im Stack-Fragment und Preview escaped.
- [ ] Preview und gespeicherte Karte erzeugen identisches Example-HTML (`<mark>`).

Browser (Playwright):
- [ ] Voller Pfad: Front tippen, Enter, Back, Enter, Preview, Add → Stapel 1, Formular leer, Schritt 1.
- [ ] Reload nach Add: Karte noch vorhanden (Server-Wahrheit), Stack-Sitzungsliste ggf. leer (dokumentiert).
- [ ] Edit-last ändert Text; Guard erscheint bei ungespeichertem Text.
- [ ] Doppelklick auf Add erzeugt eine Note.
- [ ] 375 px ohne Horizontal-Scroll; hell/dunkel Screenshot; keine Konsolenfehler.
- [ ] End-to-End mit Plan 3 (nach Merge): hinzugefügte Karte erscheint im Review mit Hint/Example.

## Akzeptanz
- Karten werden persistiert, escaped, im richtigen Deck und Typ; Edit-last ändert statt zu duplizieren.
- Kein Datenverlust bei Reload; "Finish" ist reine Navigation + Summary.
- Typ-Templates entsprechen DESIGN §5.F exakt, `css == ""`.
- Alter `/add` und `editor.js` unberührt.

## Risiken
| Risiko | Gegenmaßnahme |
|---|---|
| Doppelte Escape/Unescape | Round-Trip-Tests (4.1) |
| Typname existiert mit anderem Aufbau | `ensure_vocab_model` bricht mit Meldung ab |
| daisyUI `collapse` und natives `<details>` kollidieren im Zustand | Variante mit `<details class="collapse">` im Browser-Test prüfen; Fallback: eigenes `data-show` |
| Datastar-`data-bind` auf `<details>`/Textarea-Cursor-Insert | Chip-Insert in `add.js`; Smoke zuerst |
| Stack-Sitzungsliste verloren bei Server-Neustart | akzeptiert; Karten selbst bleiben |
| Mehrere Tabs teilen Stack-Liste | akzeptiert, gleiche Begründung wie Plan 1 |
| Enrichment (Hint/Example-Vorschläge) | **Out of Scope** (RESEARCH-enrichment: Lizenz Attribution ungeklärt) |

## Commits

> `DESIGN.md` §5.D/§6 beschreibt bis Commit 8 noch "Finish and Save All" und Pop-aus-Speicher. Bis dahin gilt dieser Plan. Commit 8 darf nicht entfallen.

1. `Add vocab note type, escaping and note add/update core`
2. `Add /app/add page with wizard steps`
3. `Add add-commit route and stack fragment`
4. `Add edit-last route with unescape round trip`
5. `Add finish summary modal and navigation guard`
6. `Style add wizard with daisyUI and tailwind`
7. `Add add-flow route and browser tests`
8. `Update DESIGN.md: persist per card, Finish semantics`
