# Plan 11: Stapel-Sprachen und Stapel-Einstellungen (`/app/decks`)

> Teil von [00-overview](2026-10-27-reviewer-redesign-00-overview.md). Voraussetzung: [Plan 7](2026-10-29-reviewer-redesign-07-new-deck.md) (Stapel anlegen, `split_emoji`/`join_emoji`, `_deck_sheet`), [Plan 6](2026-10-27-reviewer-redesign-06-i18n.md) (`s()`-Strings).
> Quelle: `design/deck-languages/` (`DESIGN.md`, `RESEARCH.md`, `create-deck-mockup.html`, `deck-settings-mockup.html`). Mocks sind vom Nutzer abgenommen.

**Ziel:** Pro Stapel ein **Sprachpaar** (Ursprungssprache → Zielsprache) speichern, das Export (`.apkg`, `.colpkg`) und Import überlebt. Das Paar wird (1) beim Anlegen gewählt, (2) in neuen **Stapel-Einstellungen** (Name, Sprachen, Emoji) geändert und (3) als Chip `🇩🇪 DE → 🇪🇸 ES` in der Deck-Liste gezeigt. Zusätzlich ein Per-Deck-Menü (`⋯`) mit "Stapel-Einstellungen" und "Stapel löschen". UI mit **daisyUI**-Klassen und Datastar, Server ist die Quelle der Wahrheit.

## Ist-Stand (aus dem Code, nicht aus Plänen)

| Punkt | Befund |
|---|---|
| Plan 7 | Umgesetzt: `POST /app/decks` (`http_app/decks.py`), `create_deck`, `split_emoji`/`join_emoji`, `_deck_sheet.html.jinja` |
| Deck-Menü | **Fehlt.** `_deck_row.html.jinja` hat nur "Lernen" und "Bearbeiten" |
| Sprachen | **Nichts vorhanden.** Kein Modell, Parser, Marker, Route |
| Beschreibung schreiben | Nur Desktop-`POST /overview/setdesc` (`http_datastar/overview.py:76-92`) und **ersetzt `desc` komplett**; Textarea zeigt `raw_desc` (`:116`) samt Marker |
| `create_deck` | Erlaubt nur Emoji aus `ALL_EMOJI` (`decks.py:106`); `world` enthält nur `🇩🇪 🇫🇷 🇯🇵` |
| Strings | `test_strings_complete` verlangt: **jeder** englische Schlüssel kommt als Literal in einem Template vor (`test_i18n_complete.py:311-326`); dynamische Schlüssel werden abgelehnt (`:255-258`) |
| daisyUI 5.7.47 | `join`/`join-item` **sind vorhanden**, aber unter `node_modules/daisyui/utilities/join.css` (nicht unter `components/`). Die Aussage in Plan 7 ("nicht vorhanden") war falsch, weil nur `components/` durchsucht wurde. Außerdem vorhanden: `select`, `alert`, `badge`, `divider`, `dropdown` (Popover-API), `menu`, `fieldset`, `modal`, `tab` |

## Entscheidungen

| Frage | Entscheidung | Beleg |
|---|---|---|
| Speicherort | **Marker in der Stapelbeschreibung `desc`**: `<!--ankiweb:lang=es>de-->` (`src>dst`, ISO-639-1-Kürzel klein) | `RESEARCH.md`: einziger Kandidat, der pro Stapel gilt und `.apkg` (mit/ohne Configs, `legacy`) und `.colpkg` byte-genau übersteht (E11) |
| Position | Marker **am Anfang** von `desc`, Rest unverändert dahinter | so gemessen (`<!--…-->Mein Text`) |
| Lesen | Erster passender Marker im ganzen `desc` gewinnt; Kürzel außerhalb des Katalogs = **kein Sprachpaar** (nicht kaputt, nicht angezeigt) | tolerant gegenüber Fremdwerkzeugen |
| Schreiben | Alle Marker entfernen, genau einen voranstellen (oder keinen). **Nur wenn sich das Paar ändert**; sonst bleibt `desc` byte-identisch | kein Datenverlust beim Umbenennen oder Emoji-Wechsel |
| "Keine Sprachen" | = kein Marker. Zurückwechseln zum Paar im selben Dialog stellt die zuvor gewählten Sprachen wieder her (nur Client-Zustand) | `DESIGN.md` |
| Beide Selects leer, Modus Sprachstapel | "noch nicht entschieden": Erstellen/Speichern gesperrt; Server lehnt mit `incomplete` ab | `DESIGN.md` |
| Gleiche Sprache | Fehler (Server `same`, Client roter Rand an beiden Selects) | `DESIGN.md` |
| Sprachkatalog | 16 Sprachen aus dem Mock (de en es fr it pt nl pl tr ru ja zh ko ar sv la), Flagge je Sprache, `la` = 🏛️. Namen lokalisiert über `s()`, Kürzel im Optionstext (`Spanisch · ES`) | `DESIGN.md` Sprachwahl |
| Flaggen als Deck-Emoji | Erlaubte Menge = `ALL_EMOJI` ∪ Katalog-Flaggen. Das Raster bleibt unverändert; eine Flagge außerhalb des Rasters zeigt Vorschau, aber keine gewählte Kachel; Tab `world` | Flaggen-Vorschlag aus dem Mock braucht das, ohne die 18er-Gruppen umzubauen |
| Marker bei Desktop-Bearbeitung | `overview.py` blendet den Marker im Textarea aus und setzt ihn beim Speichern wieder ein | sonst löscht jedes Speichern der Beschreibung im Desktop-Client das Sprachpaar (E6) |
| Stapel löschen | Im Menü, mit **Bestätigungsdialog** (daisyUI `modal`) mit Kartenanzahl. Nur Wurzelstapel; Standardstapel (ID 1) nicht löschbar. Mock zeigt nur den Menüpunkt; der Dialog ist neu und zu bestätigen | destruktive Aktion |
| Menü-Technik | daisyUI `dropdown` per **Popover-API** (`popovertarget`, `anchor-name`), `menu` als Inhalt | Escape, Außenklick, Fokus ohne eigenes JS |
| Untergeordnete Stapel | Einstellungen gelten nur für **Wurzelstapel** (Liste zeigt nur Wurzeln). Umbenennen eines Wurzelstapels benennt Unterstapel mit (Anki) | `deck_rows` |
| Gemeinsame Sprachfelder | **Ein** Jinja-Makro `_deck_languages.html.jinja` für Neu-Dialog (`new…`) und Einstellungen (`set…`) | ein Quelltext, kein Drift |

## Abweichungen vom Mockup (bewusst)

| Mockup | Umsetzung | Grund |
|---|---|---|
| Gestrichelte Verbindungslinie, Eigenbau | daisyUI `divider` mit Button als Inhalt, Label "Zielsprache" davor auf derselben Zeile; Abstand zu beiden Selects per Messung gleich | daisyUI zuerst; `divider` ist solid, Eigenbau nur wenn die Messung es verlangt |
| Segment als eigene Komponente | daisyUI `join` mit `join-item btn` als Radio-Inputs (`aria-label` als Beschriftung), Auswahl über `checked:`-Stil (`btn-accent`) | daisyUI zuerst |
| Flagge im `<select>` als Badge | `select` mit Flagge als `badge` links davor (`pointer-events-none`), nativer Picker bleibt | Mock-Verhalten, daisyUI-Komponenten |
| Alles clientseitig im Mock | Server prüft **alles** erneut; Client nur für Sofort-Feedback (`data-show`, `data-attr:disabled`) | Datastar: Server ist Wahrheit |

## DDD-Schnitt (Ubiquitous Language: `CONTEXT.md`)

Bounded Context **App-Client / Stapelverwaltung** (`ankiweb/core/app_client/`). Das Anki-**Deck** bleibt das Aggregat; die App hält kein eigenes.

| Baustein | Typ | Ort | Inhalt |
|---|---|---|---|
| `Language` | Value Object | `deck_languages.py` | `code`, `flag`; Katalog `LANGUAGES` (geschlossene Menge) |
| `LanguagePair` | Value Object | `deck_languages.py` | `src`, `dst`; Invariante `src != dst`, beide im Katalog. Verletzung: `DeckLanguageError("same" \| "unknown")` |
| Sprach-Marker | Domain-Service (rein) | `deck_languages.py` | `read_marker(desc)`, `apply_marker(desc, pair)`, `strip_marker(desc)`, `choose(mode, src, dst)` (UI-Eingabe → `LanguagePair \| None`, `incomplete` bei nur einer Sprache) |
| `DeckSettings` | Read-Modell | `decks.py` | `deck_id`, `name`, `emoji`, `languages`; für den Dialog |
| Anwendungsfälle | Use Cases | `decks.py` | `create_deck(col, name, emoji, languages)` (erweitert), `deck_settings(col, deck_id)`, `update_deck_settings(col, deck_id, name, emoji, languages)`, `delete_deck(col, deck_id)` |
| Fehler | Domain-Fehler | `decks.py` | `DeckNameError` (erweitert um `"not_found"`, `"protected"`), `DeckLanguageError` |

**Hexagon:**
- **Port** (bestehend): `CollectionPort.run/run_op` (`core/ports.py`). Kein neuer Port: Use Cases bekommen wie bisher `col` und werden vom Adapter über `service.run`/`service.run_op(…, initiator="app")` ausgeführt.
- **Rein:** `deck_languages.py` importiert weder `anki`, `fastapi`, `starlette` noch `ankiweb.adapters`. Neuer Architekturtest erzwingt das (Erweiterung von `tests/test_architecture_boundaries.py`).
- **Inbound-Adapter:** `http_app/deck_settings.py` (neu) und Erweiterung `http_app/decks.py`. Übersetzt Signale → Kernaufruf, Kernfehler → `s()`-Text, Ergebnis → SSE.
- **Zweiter Inbound-Adapter:** `http_datastar/overview.py` nutzt `strip_marker`/`apply_marker` aus dem Kern (Adapter → Kern, erlaubt).
- Kein Import `http_app` → `http_datastar` außer dem bestehenden `common.error_response`.

## Aufgabe 11.0: Messungen (vor jeder Zeile Produktcode)

Wegwerfskript gegen `temp_collection`, Ergebnisse **in diese Tabelle eintragen**, danach Entscheidungen prüfen.

| # | Frage | Beeinflusst |
|---|---|---|
| M1 | `col.decks.new_deck()` + `normal.description` setzen + `col.decks.add_deck(deck)`: ein Schritt, Beschreibung gespeichert, `OpChangesWithId`? | Gemessen: ein `add_deck` speichert Beschreibung und liefert `OpChangesWithId`; ein Undo entfernt den Stapel. Fehlgeschlagene Anlage unter gefiltertem Elternstapel verändert nichts. |
| M2 | Wurzelstapel mit Unterstapeln umbenennen und `desc` ändern: `col.decks.get` + `update_dict` in **einem** Aufruf, oder `col.decks.rename` + `update_dict`? Werden Unterstapel mitgezogen? Ein Undo-Schritt? | Gemessen: ein `update_dict` ändert Name und Beschreibung, benennt Kind und Enkel um und ist mit einem Undo vollständig rückgängig. Fehlerhafte Eingabe ändert nichts. Separates `rename` + `update_dict` ist bei Fehler im zweiten Schritt nicht atomar. |
| M3 | `col.decks.remove([did])`: Rückgabe, Unterstapel/Karten, Verhalten für ID 1; `col.decks.card_count(dids, include_subdecks=True)` für den Bestätigungstext | Gemessen: 3 Stapel und 5 Karten; `card_count` ohne Kinder 2, mit Kindern 5. `remove([root])` liefert `OpChangesWithCount.count=5` und entfernt alle 3 Stapel und Karten. Löschen von ID 1 entfernt Karten und Kinder, setzt Namen zurück und behält die Beschreibung: explizit schützen. |
| M4 | `col.decks.all()` (ein Aufruf) gegen N-mal `col.decks.get`: reicht für `deck_rows`, Zeitmessung bei 500 Stapeln | Gemessen: gleiche IDs, Namen und Beschreibungen; Median aus neun warmen Messungen bei 500 Stapeln: `all()` 0,854 ms, 500× `get()` 1,943 ms. Für die Liste einmal `all()` und ID-Lookup verwenden. |
| M5 | `sanitize_html` und `col.render_markdown` mit führendem `<!--ankiweb:lang=…-->`: Ausgabe in Overview und Congrats | Gemessen: `render_markdown('<!--ankiweb:lang=es>de-->Hello **world**')` liefert unformatiertes `Hello **world**`, nach Entfernen des Markers dagegen `<p>Hello <strong>world</strong></p>`. Der Congrats-Scheduler liefert bei leerem Stapel bereits unformatierten Text. Daher Marker **vor** Markdown entfernen; Congrats muss bei markierter Beschreibung den rohen Decktext statt der bereits gerenderten Scheduler-Ausgabe nutzen. |
| M6 | Datastar: private Signale, Tausch, berechneter Änderungszähler, `@get` und Popover sowie Namens-Map in `data-text` | Gemessen in Chromium 150 mit Datastar 1.0.4: Tausch `de/en` → `en/de`; `_dirty` 0 → 2 → 0; private Signale einschließlich verschachtelter privater Werte fehlen in GET und POST. `@get` schließt das Popover; lokalisierter Name aktualisiert sich. Keine Browserfehler. |
| M7 | daisyUI-Divider, Join-Radios, Tastatur/Fokus sowie Jinja-Sentinel | Gemessen mit vollständigem installiertem daisyUI 5.7.47: gleiche Abstände 9/9 px bei 800 px und 3/3 px bei 375 px; Tab und Pfeiltasten bedienen die Radiogruppe, Fokus-Outline 2 px. Aktuell gebautes CSS enthält diese bisher ungenutzten Klassen nicht; `checked:btn-accent` wurde im Messaufbau nachgebildet und muss nach dem Build geprüft werden. Jinja 3.1.6 übersetzt `\x1f` in Codepoint 31 und trennt repräsentative deutsche und englische Texte in zwei Teile; endgültige Katalogtexte müssen noch geprüft werden. |

## Format und Regeln des Markers

```
<!--ankiweb:lang=es>de-->Mein Text      -> LanguagePair(src="es", dst="de"), Rest "Mein Text"
Mein Text<!--ankiweb:lang=es>de-->      -> gelesen (Marker irgendwo), beim Schreiben nach vorn
<!--ankiweb:lang=xx>yy-->Text           -> kein Paar (Kürzel unbekannt); unverändert, solange Paar unverändert
<!--ankiweb:lang=es>es-->               -> kein Paar (gleich)
```

Regex: `<!--ankiweb:lang=([a-z]{2,3})>([a-z]{2,3})-->`. `apply_marker(desc, None)` liefert `""`, wenn nach dem Entfernen nichts bleibt. Das Markdown-Flag (`md`) wird nie angefasst.

## Dateien

| Datei | Zweck |
|---|---|
| `ankiweb/core/app_client/deck_languages.py` | **Neu, rein.** Katalog, `LanguagePair`, Marker-Funktionen, `choose`, `DeckLanguageError` |
| `ankiweb/core/app_client/decks.py` | `DeckRow.languages`, `deck_rows` liest `desc`; Namensprüfung herausziehen (`exclude_id`); `create_deck` mit Sprachen; `DeckSettings`, `deck_settings`, `update_deck_settings`, `delete_deck`; erlaubte Emoji = `ALL_EMOJI` ∪ Flaggen |
| `ankiweb/adapters/inbound/http_app/deck_settings.py` | **Neu.** Menü-/Einstellungs-/Lösch-Routen |
| `ankiweb/adapters/inbound/http_app/decks.py` | `POST /app/decks` liest `newMode/newSrc/newDst`; Sprachliste und Namen ins Template |
| `ankiweb/adapters/inbound/http_app/__init__.py` | Router einhängen |
| `ankiweb/adapters/inbound/http_datastar/overview.py` | Marker ausblenden/erhalten (`render_overview_html`, `setdesc`) |
| `…/templates/app/_deck_languages.html.jinja` | **Neu.** Makro: Segment, Meldung, zwei Selects, Tausch-Zeile, Chip |
| `…/templates/app/_deck_settings_sheet.html.jinja` | **Neu.** Einstellungsdialog (Kopf fix, Body scrollt, Footer fix) |
| `…/templates/app/_deck_delete_sheet.html.jinja` | **Neu.** Bestätigung |
| `…/templates/app/_deck_sheet.html.jinja`, `_deck_row.html.jinja`, `decks.html.jinja` | Sprachfelder, Chip, Kebab, Signale |
| `ankiweb/core/app_client/strings.py` | Neue Schlüssel de und en (Tabelle unten) |
| `shell_src/app/decks.js` | Fokus/Tab-Falle für mehrere Dialoge verallgemeinern |
| `shell_src/app-client.css` | Nur falls nötig (keine Arbitrary Values) |
| `tests/app_client/test_deck_languages.py`, `test_deck_settings.py`, `test_deck_settings_routes.py`, `test_deck_settings_browser.py` | Neu |
| `tests/test_architecture_boundaries.py`, `tests/test_overview.py`, `tests/app_client/test_decks*.py` | Erweitern |
| `CONTEXT.md`, `design/deck-languages/DESIGN.md`, `00-overview.md`, `docs/adr/0002-…` | Doku |

## Datastar-Konzept

Geprüft in `references/attributes.md`, `references/sse-events.md`, `modules/gotchas.md`.

- **Scope:** `decks.html.jinja` (`#decks-page`) bekommt zusätzlich `newMode: 'langs', newSrc: '', newDst: ''` und für den Einstellungsdialog `setOpen: false, setId: 0, setName: '', setEmoji: '', setMode: 'langs', setSrc: '', setDst: '', baseName: '', baseEmoji: '', baseMode: 'langs', baseSrc: '', baseDst: '', saving: false, setError: ''`, dazu `delOpen: false`. `_`-Signale (`$_swap`) bleiben lokal und gehen nicht an den Server.
- **Dialog-Inhalt vom Server:** Menüpunkt "Stapel-Einstellungen" → `@get('/app/decks/<id>/settings')`. Antwort: `patch_elements` für `#deck-settings-body` (Titel, Formularziel `@post('/app/decks/<id>/settings')`, Emoji-Raster mit aktuellem Wert) und `patch_signals` (`setId`, `set*` und `base*` mit den Ausgangswerten, `setError: ''`, `setOpen: true`). Alle gemorphten Elemente haben `id` (Gotcha #3).
- **Änderungszähler** (blaue Pille "N ungespeicherte Änderungen", "geändert"-Tag je Feld): clientseitig aus dem Vergleich `set*` gegen `base*`, nur Anzeige. Ein berechnetes lokales Signal (`data-computed:_dirty`, Anzahl geänderter Felder; M6 prüft Syntax) speist Pille und Tags. Speichern: `data-attr:disabled="$_dirty === 0 || !!$setError || $saving"`.
- **Validierung (Client):** gleiche Sprache → `data-show` Fehlertext + `aria-invalid` + Randklasse über `data-class`; eine Sprache → Warnung; beide leer → keine Meldung; Modus `none` blendet Selects aus. Jede Variante nutzt **vollständige** Klassennamen (keine Konkatenation).
- **Tauschen:** `data-on:click="$_swap = $newSrc; $newSrc = $newDst; $newDst = $_swap"` (`;`-Kette, kein Block, Gotcha #24). Icon-Drehung über `data-class`.
- **Flaggen-Vorschlag (nur Neu-Dialog):** Chip "Flagge von {language} als Emoji nutzen" wie im Mock. Sichtbar bei Zielsprache gewählt, kein Fehler und `$newEmoji` ≠ Flagge der Zielsprache. Klick setzt `$newEmoji`. Flaggen und Namen liegen als vollständige Maps (`js_literal`) im Template, Zugriff `flags[$newDst]`/`names[$newDst]`; kein Block in Ausdrücken. Satzbau siehe "Sprachname im Satz".
- **Sprachname im Satz (Fehlertext "beide Deutsch", Flaggen-Chip):** Der i18n-Test verlangt, dass der Schlüssel als Literal im Template steht und die Platzhalter zum englischen Text passen. Beides bleibt erfüllt, wenn die Übersetzung **am Platzhalter zerlegt** und der Name als `data-text`-Element dazwischen gesetzt wird. So bleibt die Wortstellung je Sprache im Katalog:
  ```jinja
  {% macro with_language(text, signal) %}
    {% set p = text.split('\x1f') %}
    <span>{{ p[0] }}<strong data-text="{{ js_literal(names) }}[{{ signal }}]"></strong>{{ p[1] }}</span>
  {% endmacro %}
  {{ with_language(s('app_decks_lang_same', language='\x1f'), '$' ~ prefix ~ 'Src') }}
  ```
  Das Makro bekommt den **bereits übersetzten** Text; der `s()`-Aufruf mit Literal-Schlüssel steht an der Aufrufstelle (ein Makro mit `s(key)` würde der Test als dynamisch ablehnen). Die Funktion `s()` bleibt unverändert, `{language}` ist ein normales Formatfeld, das `test_translated_format_fields_match_english` prüft. Das Sentinel `\x1f` und die Jinja-Escapes misst M6; de und en enthalten je genau **einen** Platzhalter (Test in `test_deck_settings_routes.py`: gerendertes HTML enthält Satzteile und Namen in der richtigen Reihenfolge, auch für `en`).
- **Speichern/Anlegen (SSE):** Erfolg: Zeile `#deck-<id>` morphen (Update) bzw. `#decks-content` neu rendern (Anlegen, Löschen, wegen veraltetem `no_match` wie Plan 7.3), Toast, Signale zurücksetzen, Dialog zu. Fehler: **nur** `newError`/`setError` patchen, Dialog bleibt offen.
- **FOUC (Gotcha #4):** `style="display:none"` an jedem `data-show`-Element.
- **Kein optimistisches UI (Tao):** Chip und Name erscheinen erst nach der Serverantwort; Ladezustand über `data-indicator:saving`.

## daisyUI-Klassen (gegen installiertes 5.7.47 zu prüfen, Aufgabe 11.4)

| Baustein | Klassen |
|---|---|
| Menü | `dropdown dropdown-end` (Popover-API: `popovertarget`, `anchor-name`/`position-anchor` inline), Inhalt `menu rounded-box border-2 border-neo-edge bg-base-200 shadow-neo`, Eintrag `<button>` in `<li>`; Löschen mit `text-error` |
| Kebab-Knopf | `btn btn-ghost btn-square btn-sm`, `aria-haspopup="menu"`, `aria-label` mit Stapelname |
| Dialoge | `modal modal-bottom sm:modal-middle`, `modal-box`, `modal-backdrop`; Öffnen per `data-class:modal-open`, `data-attr:inert`, `data-attr:aria-hidden` (exakt das Muster von `_deck_sheet`) |
| Segment | `join` mit `input.join-item.btn[type=radio][aria-label]` (je Option), gewählt: `checked:btn-accent`; eine `name`-Gruppe je Dialog (`new-mode`/`set-mode`) |
| Felder | `fieldset`, `fieldset-legend`, `select w-full border-neo-edge bg-base-200 shadow-neo`; Fehler `select-error` |
| Flagge | `badge badge-ghost` absolut links im `relative`-Wrapper |
| Tausch-Zeile | `flex items-center gap-2.5` mit `label.fieldset-legend` + `divider grow my-0` + `btn btn-sm rounded-full` |
| Meldungen | `alert alert-error` / `alert alert-warning` mit `role="alert"`, `aria-live="polite"` im umgebenden Container |
| Chip | `badge badge-outline`; offen/"Keine Sprachen": `badge-dash` |
| Änderungs-Pille / Tag | `badge badge-info` (blau, unterscheidet sich von den gelben Buttons laut `DESIGN.md`) |
| Speichern/Anlegen | `btn btn-accent neo-press` (Repo-Muster); Abbrechen `btn` |
| Löschen-Bestätigung | `btn btn-error neo-press` |
| Schriftzüge Katalog | Namen als **Literale** in einem Jinja-Dict im Makro (Muster `group_labels` in `_deck_sheet.html.jinja:1`) |

Keine Arbitrary Values (`[…]`), keine zusammengesetzten Klassennamen, keine Hex-Farben. Dunkelmodus nur über die Themes.

## Strings (de und en, Schlüssel `app_decks_…` / `app_lang_…`)

`app_decks_languages`, `app_decks_lang_mode_pair`, `app_decks_lang_mode_none`, `app_decks_lang_src`, `app_decks_lang_dst`, `app_decks_lang_src_hint`, `app_decks_lang_dst_hint`, `app_decks_lang_pick`, `app_decks_lang_swap`, `app_decks_lang_same`, `app_decks_lang_missing_dst`, `app_decks_lang_missing_src`, `app_decks_lang_unset`, `app_decks_lang_none_chip`, `app_decks_lang_none_removes`, `app_decks_lang_flag_suggest`, `app_decks_lang_chip_label` (`{src}`/`{dst}` für `sr-only`), `app_decks_menu_open`, `app_decks_settings`, `app_decks_settings_title`, `app_decks_changes_one`/`_many`, `app_decks_changed_tag`, `app_decks_save`, `app_decks_cancel`, `app_decks_saved`, `app_decks_delete`, `app_decks_delete_title`, `app_decks_delete_body` (`{deck}`, `{cards}`), `app_decks_delete_confirm`, `app_decks_deleted`, `app_decks_not_found`, `app_decks_protected`, sowie `app_lang_de` … `app_lang_la` (16). Alle als Literale im Template (Test `test_strings_complete`); de-Katalog darf Teilmenge sein, wird hier aber vollständig geliefert.

## Aufgaben

Reihenfolge: 11.0 → 11.1 → 11.2; danach **parallel** 11.3 (Strings), 11.4–11.6 (UI und Routen, setzen 11.2 voraus), 11.7 (Overview, setzt nur 11.1 voraus); zuletzt 11.8, 11.9. Jede Aufgabe: Test zuerst, dann Code.

### 11.0 Messungen
- [x] M1–M7 laufen lassen, Ergebnisse in der Tabelle oben ergänzen, abweichende Entscheidungen hier dokumentieren. Wegwerfskripte nicht committen.

### 11.1 Domain: `deck_languages.py`
- [x] `Language`, `LANGUAGES` (16, Reihenfolge wie Mock), `LanguagePair` mit Invariante, `DeckLanguageError(kind)`, `read_marker`, `apply_marker`, `strip_marker`, `choose(mode, src, dst)`.
- [x] Tests (`test_deck_languages.py`, tabellengetrieben): Rundreise byte-genau mit Fremdtext (`<div>…</div>`, Markdown, Zeilenumbrüche, führende Leerzeichen); Marker in der Mitte wird gelesen und nach vorn geschrieben; mehrere Marker → einer; unbekannte Kürzel → `None`; `es>es` → Fehler `same`; `choose("langs", "es", "")` → `incomplete`; `choose("none", …)` → `None`; `apply_marker(marker_only, None) == ""`; Idempotenz `apply(apply(d, p), p) == apply(d, p)`.
- [x] Architekturtest: `deck_languages.py` importiert nichts aus `anki`, `fastapi`, `starlette`, `ankiweb.adapters`.

### 11.2 Kern: Use Cases in `decks.py`
- [x] `DeckRow.languages: LanguagePair | None`; `deck_rows` liest `desc` über die in M4 gewählte Methode, ohne zusätzlichen Aufruf je Zeile, wenn M4 das stützt.
- [x] Namensprüfung aus `create_deck` in eine Funktion mit `exclude_id` ziehen; **Umbenennen auf den eigenen Namen in anderer Schreibweise ist erlaubt**, `taken` nur bei fremdem Stapel.
- [x] Erlaubte Emoji = `ALL_EMOJI` ∪ Katalog-Flaggen.
- [x] `create_deck(col, name, emoji, languages)`: Marker in `desc` im **selben** Schritt (M1). Bei Fehler wird nichts angelegt.
- [x] `deck_settings`, `update_deck_settings` (Name, Emoji, Sprachen in einer Operation nach M2; `desc` nur anfassen, wenn `languages != read_marker(desc)`), `delete_deck` (Wurzel, nicht ID 1, nicht gefiltert).
- [x] Alle Rückgaben tragen `changes` für `run_op` (Muster `DeckRow.changes`).
- [x] Tests (`temp_collection`): Anlegen mit Paar schreibt Marker, ohne Paar keine; Fremdtext in `desc` überlebt Umbenennen, Emoji-Wechsel und Paarwechsel; unveränderte Sprachen lassen `desc` byte-identisch (auch bei Fremdmarker `xx>yy`); `taken` gegen anderen Stapel, nicht gegen sich selbst; Unterstapel folgen dem Umbenennen; Flagge als Emoji akzeptiert, beliebiger String abgelehnt; Löschen entfernt Wurzel samt Unterstapeln, ID 1 → `protected`; unbekannte ID → `not_found`; `deck_rows` liefert `languages`.

### 11.3 Strings
- [x] Schlüssel oben in `strings.py` (de, en). `test_i18n_complete`, `test_i18n_strings` grün.

### 11.4 Templates (daisyUI)
- [x] `_deck_languages.html.jinja` als Makro `languages(prefix)`: Signalnamen aus `prefix` (`new`/`set`) in `data-bind:`-Attributen und Ausdrücken (Attributnamen dürfen zusammengesetzt werden, Tailwind-Klassen nicht). Katalog-Namen als Literale im Dict.
- [x] Meldung direkt unter dem Segment (nicht unter den Selects), `role="alert"`, `aria-live="polite"`. Fehlertext und Flaggen-Chip nennen die Sprache (Makro `with_language`, siehe Datastar-Konzept).
- [x] Tausch-Zeile: Label "Zielsprache" und Button auf **einer** Zeile; Abstand Button → oberer Select gleich Button → unterer Select (Playwright-Messung, ±1 px, 375 und 800 px Breite).
- [x] `_deck_sheet.html.jinja`: Segment, Selects, Flaggen-Vorschlag, Sprach-Chip in der Vorschau; Anlegen gesperrt, solange ungültig.
- [x] `_deck_settings_sheet.html.jinja`: Reihenfolge Name → Sprachen → Emoji; Hinweis "Beim Speichern wird der Sprach-Marker aus der Beschreibung entfernt" nur bei Wechsel Paar → "Keine Sprachen"; **keine** Export-Hinweiskarte (`DESIGN.md`).
- [x] `_deck_delete_sheet.html.jinja`: Name, Kartenanzahl, `btn-error`.
- [x] `_deck_row.html.jinja`: Kebab im Kopf der Kachel (Popover-Menü), Sprach-Chip unter dem Namen (`🇩🇪 DE → 🇪🇸 ES`, `sr-only` Klartext; ohne Paar `badge-dash` "Keine Sprachen"; `view.row.languages is none` ist der Normalfall für Bestandsdecks).
- [x] Fokus: `decks.js` auf mehrere Dialoge verallgemeinern (Zielfeld und Rückkehr zum Auslöser je Dialog), Tab-Falle wiederverwenden; **keine** Block-Statements in Ausdrücken.

### 11.5 Routen `http_app/deck_settings.py`
- [x] `GET /app/decks/{deck_id}/settings` (SSE wie oben), `POST /app/decks/{deck_id}/settings`, `POST /app/decks/{deck_id}/delete`; `POST /app/decks` um die Sprachsignale erweitern. Alle über `service.run`/`run_op(…, initiator="app")`.
- [x] Signale defensiv lesen (`ReadSignals`, Typprüfung, kein 500): falsche Typen → Fehlerpfad; unbekannte Deck-ID → `not_found` als Toast/Fehler.
- [x] Kernfehler → `s()`: `DeckNameError` (alt + neu) und `DeckLanguageError` (`same`, `incomplete`, `unknown`) → `newError`/`setError`.
- [x] Origin-Guard und Passwort-Gate greifen über `build_app_router` automatisch; keine Sonderfälle.
- [x] Namen und Beschreibung nie roh in JS-Literale: `js_literal`; Escaping-Tests mit `'`, `"`, `\`, `<b>x</b>`, `$`.
- [x] Tests (`test_deck_settings_routes.py`, Muster `test_decks_create_routes.py`): Erfolg je Route (Collection prüfen, SSE-Signale), jede Fehlerart, Cross-Site 403, ohne Login Redirect, Löschen der letzten Zeile rendert den Leerzustand.

### 11.6 Styling
- [x] Nur das Nötige in `shell_src/app-client.css`, mit Theme-Token; `npm run build:css:app`; Klassen-Test (`test_app_css.py`) grün.

### 11.7 Desktop-Overview erhält den Marker
- [x] `render_overview_html`: `raw_desc=strip_marker(raw)`. `setdesc`: `d["desc"] = apply_marker(p.get("desc", ""), read_marker(d.get("desc", "")))`.
- [x] Entscheidung M5: Falls `sanitize_html`/Markdown den Marker sichtbar machen, im Render ebenfalls `strip_marker`.
- [x] Tests in `tests/test_overview.py`: Beschreibung speichern lässt das Paar bestehen; Textarea enthält den Marker nicht; Stapel ohne Marker unverändert; vom Nutzer eingefügter Marker im Textfeld wird zu genau einem Marker.

### 11.8 Browser-Smoke (Playwright, eigener Chromium-Start)
- [x] 375x667 und 800x800, hell und dunkel, `scrollWidth` = Viewport, keine Konsolenfehler.
- [x] Anlegen: Segment, zwei Sprachen, Tauschen, gleiche Sprache (Fehler, Button gesperrt), nur eine (Warnung), Flaggen-Vorschlag, Anlegen → Zeile mit Chip, in Anki `desc` prüfen.
- [x] Einstellungen: Menü öffnen (Escape, Außenklick, Fokus zurück), Pille zählt, Speichern erst bei Änderung, Umbenennen, "Keine Sprachen" (Hinweis, Marker weg), Emoji-Wechsel lässt `desc` byte-gleich, Dialog zu.
- [x] Löschen: Bestätigung mit Kartenanzahl, Abbrechen, Löschen, Zeile weg, Leerzustand.
- [x] **Export-Rundreise:** Stapel mit Paar und Fremdtext → `.apkg`-Export → Import in frische Collection → Paar wird gelesen (Bestätigung von RESEARCH E11 mit der echten App-Funktion).
- [x] Screenshots neben den Mocks, Abweichungen berichten.

### 11.9 Doku und Aufräumen
- [x] `CONTEXT.md`: Sprachpaar, Ursprungssprache, Zielsprache, Sprach-Marker, Sprachstapel; Alias vermeiden: "Lernsprache"/"Muttersprache".
- [x] `docs/adr/0002-deck-language-marker-in-description.md`: Entscheidung, Alternativen (a)–(f) aus `RESEARCH.md`, Folgen (Anki Desktop kann Marker überschreiben; Import überschreibt `desc`; leere Stapel exportiert Anki nicht).
- [x] `design/deck-languages/DESIGN.md`: Verweis auf Plan 11; `00-overview.md`: Zeile 11 in die Tabelle.
- [x] Wegwerfskripte und Screenshots nicht committen.

## Akzeptanz
- Ein Stapel lässt sich mit Sprachpaar oder ohne Sprachen anlegen; in der Collection steht höchstens **ein** Marker am Anfang von `desc`, Fremdtext unangetastet.
- Einstellungen ändern Name, Sprachen und Emoji atomar; Speichern erst bei Änderung aktiv; unveränderte Sprachen berühren `desc` nicht.
- Der Server lehnt gleiche, unvollständige und unbekannte Sprachen sowie fremde Emoji ab; der Dialog bleibt mit Text offen.
- Chip in der Deck-Liste; "Keine Sprachen" gestrichelt.
- Löschen nur mit Bestätigung; ID 1 geschützt.
- Desktop-"Beschreibung bearbeiten" verliert das Sprachpaar nicht.
- Paar übersteht `.apkg`-Export/Import (App-Funktion liest es danach).
- Nur daisyUI/Tailwind aus dem Build, keine Arbitrary Values; hell/dunkel; i18n-Tests, Ruff, Complexipy, `ty` grün; alter Client unverändert (außer `overview.py` wie oben).

## Risiken
| Risiko | Gegenmaßnahme |
|---|---|
| Nutzer ersetzt Beschreibung in Anki Desktop → Marker weg (E6) | Fehlender Marker = "Keine Sprachen"; ADR dokumentiert; kein Datenfehler |
| Import in gleichnamigen Stapel überschreibt `desc` (E2) | Anki-Standard; ADR |
| Leere Stapel fehlen im `.apkg` (E1) | unabhängig vom Speicherort; ADR |
| `markdown_description` aktiv | Kommentar bleibt im Quelltext; M5 misst Rendering |
| `update_dict` mit neuem Namen benennt Unterstapel nicht mit | M2 entscheidet; sonst `rename` + `update_dict` in einer `run_op`-Funktion, Teilfehler per Test abgedeckt |
| Veraltetes `no_match`-Literal nach Anlegen/Umbenennen/Löschen | `#decks-content` neu rendern (Plan 7.3) |
| `select` mit Flaggen-Badge: Emoji rendert nicht überall | Kürzel im Optionstext (`Spanisch · ES`) |
| Popover-API in älteren Browsern | M6/11.8 in Chromium; Fallback nicht geplant, auf echtem Gerät testen (iOS Safari) |
| Zwei Tabs speichern gegensätzlich | Letzter Schreiber gewinnt; Serialisierung über `service.run_op` |

## Commits
1. `Add deck language domain (marker, catalog, pair)`
2. `Add language support to deck create and settings use cases`
3. `Add deck settings and delete routes`
4. `Add language fields, chip and deck menu with daisyUI`
5. `Add deck language strings for de and en`
6. `Keep language marker when editing description in overview`
7. `Add deck settings route and browser tests`
8. `Document deck languages (CONTEXT, ADR 0002, plan index)`
