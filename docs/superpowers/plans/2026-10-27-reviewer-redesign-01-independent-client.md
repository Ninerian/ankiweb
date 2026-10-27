# Plan 1: Unabhängiger Client (`/app/*`)

> Teil von [00-overview](2026-10-27-reviewer-redesign-00-overview.md). Voraussetzung für Pläne 2 bis 5.

**Ziel:** Ein eigenes Inbound-Paket, das unter `/app/*` Seiten im Neo-Pop-Design ausliefert, ohne Code, Templates oder JS des bestehenden Clients (`/`, `/reviewer`, `/add`, `reviewer.js`, `editor.js`, `/ws`) zu nutzen. Dazu: Design-Tokens, Basis-Layout, ein Study-Service-Kern (Queue/Answer), Auth-Verhalten, Test-Fixtures.

**Warum zuerst:** Alle Folgeschritte hängen an Layout, Tokens, Router-Aggregation und dem Study-Kern. Nach diesem Schritt sind 2, 3, 4 parallel machbar.

## Grundlage (belegt)

| Fakt | Quelle |
|---|---|
| Queue-Lücke: `get_queued_cards` fehlt in AnkiConnect; Spike löst sie mit `load_question`, `render_answer`, `answer_current` | RESEARCH-independent-client §3, §11; `study-api-spike.py` |
| Spike-Fehler: `next` als GET, obwohl Zustand und Timer verändert werden. Muss POST sein | RESEARCH §11 |
| `counts(card)` ignoriert Argument, holt Queue erneut. Zähler aus derselben Antwort lesen | RESEARCH §11 Limits |
| Ein In-flight-Karte pro Prozess (zwei Tabs überschreiben sich) | RESEARCH §11 Limits |
| Router vor Media-Catch-All `/{path}` mounten | `app.py` Kommentar |
| `core` darf `adapters` nicht importieren | `tests/test_architecture_boundaries.py` |
| `reviewer.py` Hilfen (`load_question`, `render_av_buttons`) liegen in `http_screens` (Adapter), importieren `templating` | `reviewer.py:14-121` |

**Konsequenz:** `load_question`/`render_answer`/`answer_current` nicht aus dem Adapter `http_screens.reviewer` importieren (würde den alten Client koppeln und `core` dürfte sie nie nutzen). Stattdessen **eigener Kern** `core/app_client/study.py` direkt auf `col.sched` (3 kurze Funktionen). Kein Import aus `http_screens/*`.

## Entscheidungen

| Thema | Wahl |
|---|---|
| Auth | `/app/*` bleibt hinter `_auth_guard` (Session-Cookie). Keine Änderung am Guard. Manifest/SW-Ausnahmen existieren bereits |
| State der In-flight-Karte | Serverseitig, **eine `StudySession` je Browser-Session**, Schlüssel = zufälliges Cookie `app_sid` (httponly, samesite=lax), im Speicher (`dict`, LRU ≤ 8). Zwei Tabs im selben Browser teilen sie, Stale-Answer wird per `cardId`-Check mit 409 abgelehnt |
| Fehlerform | Datastar-Signal `error` via vorhandenes `error_response` (`http_datastar/common.py`) |
| CSS | Eigene Dateien `ankiweb/shell/static/app/*.css`, **nicht** `app.css`/`theme.css` (daisyUI) laden |
| Bundles | Kein Build-Schritt: statisches CSS/JS (Mockups sind schon so), Datastar aus `/shell/static/datastar.js` |
| i18n | UI-Texte Englisch wie Mockups; `tr.*` nur für Ease-Labels (kommen fertig von `describe_next_states`). Lokalisierung = ungeprüft, nicht im Scope |
| Sanitizing | Karten-HTML kommt aus dedizierten Typen. Vor Einfügen `sanitize_html` (`core/html_sanitize.py`) anwenden (RESEARCH §3a: Felder können aus Importen stammen) |

## Dateien

| Datei | Zweck |
|---|---|
| `ankiweb/core/app_client/__init__.py` | leer |
| `ankiweb/core/app_client/study.py` | `StudySession`, `QueueSnapshot`, `fetch_next`, `answer`, `StaleCard` |
| `ankiweb/adapters/inbound/http_app/__init__.py` | `build_app_router(get_service)` aggregiert Sub-Router |
| `ankiweb/adapters/inbound/http_app/layout.py` | `render_app_page(title, body, *, active, scripts=())` |
| `ankiweb/adapters/inbound/http_app/session.py` | Cookie `app_sid` + `SessionStore` |
| `ankiweb/adapters/inbound/http_shared/templates/app/base.html.jinja` | Dokument-Gerüst (eigenes, **nicht** `shell.html.jinja`) |
| `ankiweb/shell/static/app/tokens.css` | `:root` + dunkle Variante, aus `mockup.html` extrahiert |
| `ankiweb/shell/static/app/app.css` | Basis-Komponenten (HUD, Button, Sheet) |
| `ankiweb/app.py` | **eine** Zeile: `app.include_router(build_app_router(...))` vor Media-Router |
| `tests/app_client/conftest.py` | Fixtures `col_with_vocab`, `client`, `live_app` |
| `tests/app_client/test_study_core.py` | Kernlogik |
| `tests/app_client/test_app_shell.py` | Layout, Auth, Isolation |

## Aufgaben

### 1.0 Design-Tokens extrahieren (kein Code-Risiko)
- [ ] `:root` und `[data-theme="dark"]` Variablen aus `mockup.html` (Zeilen `<style>`) kopieren nach `static/app/tokens.css`. Dunkel **per `@media (prefers-color-scheme: dark)`** statt JS-`data-theme` (DESIGN §6: "dark palette applied via prefers-color-scheme"; spart Inline-JS, vermeidet FOUC).
- [ ] Gemeinsame Basisklassen (`.btn`, `.hud`, `.sheet`, Fokus-Ring) nach `app.css`. Kontrast ≥ 4.5:1 beibehalten (REFERENCE §3, bereits gefixt in Mockups: Werte 1:1 übernehmen, nicht neu wählen).
- [ ] Verifikation: Seite mit nur diesen CSS-Dateien lädt ohne `/shell/static/app.css`.

### 1.1 Study-Kern (TDD)
`core/app_client/study.py`, reines Python auf `Collection`:

```python
@dataclass(frozen=True)
class QueueCounts: new: int; learning: int; review: int

@dataclass(frozen=True)
class CardView:
    card_id: int; deck: str
    question_html: str; answer_html: str     # sanitized
    labels: tuple[str, str, str, str]        # Again/Hard/Good/Easy
    counts: QueueCounts

class StudySession:  # in-flight: card, states, context
    ...

def fetch_next(col, session, deck_id: int | None) -> CardView | None
def answer(col, session, card_id: int, ease: int) -> None   # raises StaleCard, ValueError
```

Regeln (alle aus RESEARCH §11 belegt):
- **Feldnamen-Zuordnung (eine Stelle, mit Test):** Queue-Antwort `get_queued_cards` nutzt `new_count`, `learning_count`, `review_count`; `deck_due_tree`-Knoten nutzen `new_count`, `learn_count`, `review_count` (beide belegt per Probe). Das Mapping steht ausschließlich in `QueueCounts.from_queue(...)` (Plan 1) und `DeckRow` (Plan 2). Ein Test legt je eine Karte in New und Learning an und prüft beide Wege auf konkrete Werte ungleich 0, weil ein falscher Feldname sonst still 0 liefert.
- `fetch_next`: `col.decks.set_current(deck_id)`, `queued = col.sched.get_queued_cards(fetch_limit=1)`; Zähler **aus `queued.new_count/learning_count/review_count`** (gleiche Antwort, kein zweiter Call). `card.start_timer()` **vor** Render. Labels via `col.sched.describe_next_states(top.states)`.
- Unicode-Isolate (U+2068/U+2069) aus Labels entfernen, NBSP durch Leerzeichen (RESEARCH §11 letzter Punkt). `tr_clean`-Logik aus `templating.tr_clean` **nicht** importieren (Adapter); kleine eigene Funktion im Kern.
- `answer`: `StaleCard` wenn `session.card is None or session.card.id != card_id`; `ValueError` bei `ease` ∉ 1..4. Mapping auf `CardAnswer.Rating` wie `answer_current`.
- `<style></style>`-Präfix im Render entfernen (RESEARCH §10: leer, harmlos; vor `sanitize_html` strippen, damit Tests deterministisch sind).
- AV-Tags: dedizierter Typ hat kein Audio. Falls `[anki:play:...]` im Render vorkommt: entfernen (nicht abspielbar im neuen Client), Log auf debug.
- Type-in-Answer: **nicht unterstützt** (dedizierter Typ hat keinen `{{type:}}`).

Tests (`test_study_core.py`, `temp_collection` aus `tests/conftest.py`):
- [ ] 5 neue Karten, Reihenfolge = Erstellungsreihenfolge, Zähler fallen 5→0 (Spike-Tabelle nachstellen).
- [ ] Again/Hard: Karte kehrt zurück; `learning` steigt.
- [ ] `StaleCard` bei falscher ID; `ValueError` bei ease 0 und 5; Karte in flight bleibt unverändert.
- [ ] **Zeitmessung:** `time.sleep(0.05)` zwischen `fetch_next` und `answer`, Review-Log `time` ≥ 40 ms (Regressionstest gegen `answerCards`-Problem, RESEARCH §3 Timing-Caveat).
- [ ] Zweiter `fetch_next` für dieselbe Karte startet Timer neu (dokumentiert, kein Fehler).
- [ ] Leere Queue → `None`.
- [ ] Labels enthalten keine U+2068/2069.
- [ ] `core` importiert nichts aus `adapters` (bestehender Architekturtest läuft mit).

### 1.2 Router, Layout, Session
- [ ] `http_app/__init__.py`: `build_app_router(get_service) -> APIRouter(prefix="/app")`; inkludiert Sub-Router der Pläne 2 bis 4 (jetzt leer, nur Healthprobe `GET /app/ping` → 200, für Smoke).
- [ ] `layout.py::render_app_page` rendert `app/base.html.jinja`: `<meta viewport-fit=cover>`, Tokens/App-CSS, `datastar.js` (module), Manifest/Theme-Color-Tags **noch nicht** (Plan 5, hält Schritte unabhängig).
- [ ] `session.py`: `SessionStore` (LRU 8), `get_session(request) -> StudySession` setzt Cookie `app_sid` bei Bedarf. Kein `localStorage`, Server ist Quelle der Wahrheit (Tao).
- [ ] `app.py`: `app.include_router(build_app_router(lambda: app.state.service))` **vor** `build_media_router`. Test sichert Reihenfolge (`GET /app/ping` nicht 404 durch Catch-All).
- [ ] Datastar-Basis: `<body data-signals="{error: ''}">`. Fehler-Toast-Element `#app-error` mit `data-show="$error"` + `style="display:none"` (Gotcha #4), `data-text="$error"`.

Tests (`test_app_shell.py`):
- [ ] `GET /app/ping` 200 ohne Passwort; mit Passwort 303 → `/login`; mit Cookie 200.
- [ ] Seite enthält **keine** Referenz auf `/_anki/`, `reviewer.js`, `editor.js`, `/ws`, `bootstrap.js`, `/shell/static/app.css` (Isolations-Test, Substring-Check über `render_app_page`).
- [ ] Router-Reihenfolge vor Media-Catch-All.
- [ ] `app_sid` Cookie: httponly, samesite=lax, gesetzt nur wenn nötig.

### 1.3 Fixtures
- [ ] `col_with_vocab(tmp_path)`: Collection + Deck `German B1 Vocab` + 3 bis 5 Noten. Note-Type `AnkiWeb Vocab` erst in Plan 4 per `ensure_vocab_model`; bis dahin nutzt die Fixture `Basic`. Fixture so bauen, dass Plan 4 sie erweitert statt ersetzt.
- [ ] `live_app` (uvicorn in Thread, freier Port per `socket.bind(0)`; **nicht** feste 8124 wie `test_study_loop_home.py`, vermeidet Port-Kollision bei parallelem Lauf).

## Akzeptanz
- `GET /app/ping` liefert eine Seite im Design (Tokens geladen, dunkel per OS-Einstellung), ohne Anki-Vendor-Assets.
- Study-Kern besteht alle Tests; Zeitmessungstest grün.
- Gesamte bestehende Suite unverändert grün (nur eine Zeile in `app.py` geändert).
- Smoke: Wegwerf-Server, `curl -i /app/ping` + Headless-Screenshot 375x812 hell/dunkel.

## Risiken
| Risiko | Gegenmaßnahme |
|---|---|
| Zwei Tabs teilen In-flight-Karte | 409 per `cardId`; UI lädt bei 409 neu (Plan 3). Dokumentiert, nicht gelöst (RESEARCH Limit) |
| `get_queued_cards`-Felder heißen anders in `anki` 26.9.2 | Task 1.1 beginnt mit 5-Zeilen-Check per `uv run python` gegen Wegwerf-Collection, Namen in Docstring festhalten |
| Cookie-Store unbegrenzt | LRU 8, Test |

## Commits
1. `Add app client design tokens and base css`
2. `Add study core: queue head, answer, stale-card guard` (Tests in demselben Commit)
3. `Add /app router, layout and session store`
4. `Wire /app router before media catch-all`
5. `Add app client test fixtures and shell isolation tests`
