# Plan 2: Startseite mit Deck-Liste (`GET /app/`)

> Teil von [00-overview](2026-10-27-reviewer-redesign-00-overview.md). Voraussetzung: [Plan 1](2026-10-27-reviewer-redesign-01-independent-client.md).

**Ziel:** Deck-Liste im Neo-Pop-Design nach `design/reviewer-redesign/decks-mockup.html`: Kartenzeilen (Emoji, Name, Due/New, Candy-Stripe-Fortschritt), Live-Suche, Leerzustand, je Deck **Learn** und **Edit / Add**.

## Vorgabe aus Design (DESIGN §6, REFERENCE §2)

| Element | Verhalten |
|---|---|
| Suche `#deck-search` | Case-insensitive Teilstring auf Deck-Namen; Nicht-Treffer `hidden`; Leerzustand "No decks found" |
| Learn | → Review-Seite für dieses Deck |
| Edit / Add | → Add-Seite für dieses Deck |
| Fortschritt | `role="progressbar"` + `aria-valuenow` |
| Kein Mode-Switch, kein Chip, kein State in `localStorage` | |
| Dark | nur `prefers-color-scheme`, kein Toggle |

## Abweichungen von Mockup (bewusst, begründet)

| Mockup | Umsetzung | Grund |
|---|---|---|
| Fünf feste `deck`-IDs (`german-b1` …), Fallback auf `german-b1` | Echte Anki-Deck-IDs (int). Unbekannte/fehlende ID → Redirect `/app/` | Mockup-IDs waren Prototyp-Stub (REFERENCE §2.1) |
| Emoji je Deck hart codiert | Aus Deck-Namen abgeleitet: führendes Emoji-Graphem im Namen, sonst Standard `🗂️` | Anki kennt kein Emoji-Feld; Namen wie `🇩🇪 German B1 Vocab` sind im Mockup-Stil |
| Due/New aus Mockup-Konstanten | `deck_due_tree()`; Due = `review_count + learn_count`, New = `new_count` | Verifiziert: `DeckTreeNode` hat diese Felder (Plan 1 Probe) |
| Fortschritt 70 % (Konstante) | **Tagesfortschritt pro Deck** (Entscheidung): `studied / (studied + due + new)`, 0 wenn Nenner 0. `studied` = Reviews seit Tagesbeginn je Deck | **Belegt:** `DeckTreeNode` hat kein `studied_today`; `col.studied_today()` ist ein **Text** für die ganze Sammlung. Deshalb eigene Abfrage: **eine** gruppierte SQL über alle Decks, `select c.did, count(*) from revlog r join cards c on c.id=r.cid where r.id > ? group by c.did`, Parameter `(col.sched.day_cutoff - 86400) * 1000` (Tagesgrenze der Sammlung, **nicht** Mitternacht). Probe: 100 Läufe = 0,3 ms, kein Query pro Zeile. Kinder-Decks fließen über `cards.did` nicht in den Elternwert ein: Summe über die Teilbaum-IDs bilden |
| Reviews zählen | Jeder `revlog`-Eintrag zählt, auch wiederholte Karten (Again) | Produktannahme: Fortschritt kann dadurch über den Anfangsbestand hinaus wachsen, Anzeige auf 100 geklemmt |
| Wo die SQL liegt | `core/app_client/deck_progress.py` auf `col.db` (Collection-Zugriff nur in `service.run`), reine Funktion `(rows, tree) -> dict[deck_id, pct]` getrennt testbar | Adapter bleibt ohne SQL (Architekturregel) |
| Suche mit Client-JS | `data-bind` + `data-show`-Filter per **Server-Fragment** (siehe unten) | Datastar-Prinzip: Backend rendert; aber Live-Suche pro Taste ist Round Trip |

**Suche:** zwei Optionen, Standard **Option A**:
- **A (empfohlen):** Reiner Client-Filter über Datastar-Signal `q` und `data-show` je Zeile, z. B. `data-show="$q === '' || $name.includes($q.toLowerCase())"`. Kein Round Trip. Name steckt als `data-signals`-freies Attribut; Ausdruck liest `el.dataset.name` nicht (Sandbox, Gotcha #2). Praktikabel: pro Zeile `data-show="'<lowername>'.includes($q.toLowerCase())"` serverseitig eingesetzt (Name Jinja-escaped via `tojson`). Kein Block-Syntax (Gotcha #24).
- B: `data-on:input__debounce.200ms="@get('/app/decks/list')"` rendert gefilterte Liste. Mehr Latenz, nicht nötig bei wenigen Decks.

## Dateien

| Datei | Zweck |
|---|---|
| `ankiweb/core/app_client/decks.py` | `DeckRow`, `deck_rows(col) -> list[DeckRow]` |
| `ankiweb/adapters/inbound/http_app/decks.py` | `GET /app/` (+ `GET /app` Redirect), Router-Factory |
| `.../templates/app/decks.html.jinja` | Seite |
| `.../templates/app/_deck_row.html.jinja` | Zeile (eigene Datei, wiederverwendbar für Fragment-Updates) |
| `shell_src/app-client.css` | nur `.neo-press` und Meter-Stripes, falls nicht schon aus Plan 1 vorhanden |
| `tests/app_client/test_decks.py` | Kern + HTTP |
| `tests/app_client/test_decks_browser.py` | Playwright-Smoke (optional per `importorskip`, wie `test_study_loop_home.py`) |

## Aufgaben

### 2.1 Kern `deck_rows`
```python
@dataclass(frozen=True)
class DeckRow:
    deck_id: int
    name: str
    emoji: str
    due: int
    new: int
    progress_pct: int
```
- [ ] Wurzel-Decks aus `col.sched.deck_due_tree().children`. Unterdecks: **nur oberste Ebene** (Mockup zeigt flache Liste); `due/new` verwenden `*_uncapped`? Nein: die gedeckelten Werte (`review_count`, `new_count`) entsprechen dem Anki-Deckbrowser. Unterdeck-Summen sind in den Knotenwerten enthalten (zu prüfen, siehe Test).
- [ ] Filtered Decks (`filtered=True`) ausblenden (nicht Teil des Designs).
- [ ] Default-Deck ausblenden wenn leer (`total_in_deck == 0` und Name `Default`), wie Anki Desktop.
- [ ] Nur Decks mit mindestens einer Karte des Typs `AnkiWeb Vocab`? **Offene Produktfrage** (Overview). Default: alle Decks zeigen; Filter wird erst in Plan 3 Task 0 entschieden und hier per eine Konstante nachgezogen.
- [ ] Emoji-Ableitung: erstes Zeichen mit `unicodedata.category` ∈ `So`/Regional-Indicator-Paar; Rest des Namens als Anzeigename ohne Emoji. Reine Funktion, parametrisiert testbar.
- [ ] `progress_pct`: ganzzahlig 0..100, geklemmt.

Tests (TDD, `temp_collection`):
- [ ] Zähler stimmen mit `deck_due_tree` überein; Kind-Decks fließen in Eltern ein (Anki-Verhalten) oder werden dokumentiert abweichend.
- [ ] Filtered Deck fehlt. Leeres `Default` fehlt.
- [ ] Emoji-Ableitung: `🇩🇪 German` → (`🇩🇪`, `German`); `Biology` → (`🗂️`, `Biology`); Name nur Emoji.
- [ ] Progress 0 bei Nenner 0, 100 bei nichts offen und etwas gelernt.
- [ ] Sortierung wie Anki (`deck_due_tree` Reihenfolge), stabil.

### 2.2 Route und Template
- [ ] `GET /app/` → `render_app_page("Decks", body, active="decks")`. Body: Suchfeld, Liste `#deck-list`, Leerzustand `#empty-state` (immer gerendert, `style="display:none"` + `data-show`, Gotcha #17/#4).
- [ ] Zeile: `<a>` **Learn** → `/app/review?deck=<id>`; **Edit / Add** → `/app/add?deck=<id>` (echte Links, keine JS-Navigation: Tao "kein Client-Routing").
- [ ] Alle gemorphten Elemente mit `id` (`deck-<id>`), Gotcha #3.
- [ ] `data-signals="{q: ''}"` auf dem Container, der die Suche und alle Zeilen enthält (Gotcha #23: Scope).
- [ ] Aktualisierung bei Rückkehr aus Review/Add: Seite wird per Navigation neu gerendert (kein Polling). Optional Bonus: `pageshow`-Reload bei bfcache. **Nicht** im Scope, falls nicht nötig; im Smoke prüfen (Zähler nach Rating aktuell?).
- [ ] Barrierefreiheit: Suchfeld `type="search"` mit Label, Fortschritt `role="progressbar"` + `aria-valuemin/max/now`, Link-Texte eindeutig (`aria-label="Learn German B1 Vocab"`).
- [ ] Leere Collection: eigener Hinweis "Add your first deck" mit Link auf `/app/add` (nicht im Mockup; minimal, sonst leere Seite).

Tests (`TestClient`, ohne Browser):
- [ ] Antwort enthält je Deck genau einen Learn- und einen Add-Link mit korrekter ID.
- [ ] Deck-Namen sind HTML-escaped (Deck `<b>x</b>` → kein Markup).
- [ ] Alle Zeilen haben `id`.
- [ ] Mit Passwort: 303 ohne Cookie.
- [ ] Kein Verweis auf alte Assets (Isolations-Test aus Plan 1 deckt ab; hier Wiederverwendung der Hilfsfunktion).

### 2.3 Styling mit daisyUI und Tailwind (Vorlage `decks-mockup.html`)
- [ ] Zeile = daisyUI `card card-border` mit `neo-press`; Inhalt per Tailwind-Flex. Emoji als `text-3xl`, Name `font-black tracking-tight`, Zähler als `badge badge-info` (New) und `badge badge-error` bzw. `badge-success` (Due), Learn = `btn btn-primary`, Edit/Add = `btn btn-ghost`.
- [ ] Fortschritt = daisyUI `progress progress-accent` mit Stripes aus `app-client.css`; `role="progressbar"` und `aria-valuenow` bleiben (daisyUI `progress` ist `<progress>`: dann reicht `value`/`max` und der native Role, **prüfen**, welche Variante im Test stabiler ist).
- [ ] Suche = daisyUI `input input-bordered` in `label` (mit sichtbarem oder `sr-only` Text). Leerzustand = daisyUI `alert` oder zentrierter Block.
- [ ] Touch-Ziele `min-h-11`; Fokus-Ring über daisyUI-Default; `motion-reduce:` für Press/Stripes; Safe-Area per `pt-[env(safe-area-inset-top)]` und `pb-[env(safe-area-inset-bottom)]`.
- [ ] Klassen **vollständig** im Template ausschreiben (kein `badge-{{ x }}`); Due/New-Farbe über feste Zuordnung im Template.

### 2.4 Browser-Smoke
- [ ] Wegwerf-Server mit 5 Decks (Namen/Zähler wie REFERENCE §2.1), Headless-Chromium 375x812 hell/dunkel.
- [ ] Suche "bio" zeigt 1 Zeile, "zzz" zeigt Leerzustand, Leeren zeigt alle.
- [ ] Learn-Klick landet auf `/app/review?deck=<id>` (404/Platzhalter bis Plan 3 ist ok; Link-Ziel prüfen, nicht Seite).
- [ ] `scrollWidth == 375`, keine Konsolenfehler (Muster aus REFERENCE §2.5).
- [ ] Screenshot neben `decks-mockup.html` vergleichen.

## Akzeptanz
- `/app/` zeigt echte Decks mit korrekten Zählern; Suche und Leerzustand funktionieren ohne Netzwerkrequest (Option A).
- Learn/Add-Links tragen die echte Deck-ID.
- Alle Tests grün, Ruff/Complexipy sauber, keine Änderung am alten Client.

## Risiken
| Risiko | Gegenmaßnahme |
|---|---|
| Tailwind-Klasse fehlt im Build (z. B. neue Utility nur im Template) | Klassen-Test aus Plan 1; `npm run build` vor Smoke |
| Datastar-Ausdruck mit Deck-Namen enthält Quotes/Backslashes | Name über `tojson`-Filter in den Ausdruck; Test mit `'`, `"`, `\` im Namen |
| Zähler weichen von Anki Desktop ab (Limits, Kinder) | Test gegen `deck_due_tree`; Abweichung dokumentieren statt neu berechnen |
| Emoji-Erkennung zerlegt Graphem-Cluster | Test mit Flaggen und ZWJ-Sequenzen; Fallback Standard-Emoji |
| Sehr viele Decks (100+) | Server rendert alles; Datastar-Filter günstig. Virtualisierung nicht im Scope |

## Commits
1. `Add deck_rows core: counts, emoji split, progress`
2. `Add /app/ deck list route and templates`
3. `Style deck list with daisyUI and tailwind`
4. `Add deck list tests incl. escaping and auth`
5. `Add deck list browser smoke test`
