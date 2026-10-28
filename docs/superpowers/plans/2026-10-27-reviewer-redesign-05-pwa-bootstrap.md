# Plan 5: PWA-Bootstrap und Einbindung der Ansichten

> Teil von [00-overview](2026-10-27-reviewer-redesign-00-overview.md). Voraussetzung: Pläne 1 bis 4 gemerged.

**Ziel:** `/app/` erfüllt die Installierbarkeitskriterien von Chromium (Manifest, Worker, Icons; geprüft per CDP auf localhost). **Nicht im Umfang (Entscheidung): HTTPS-Betrieb.** Der Plan liefert nur Dokumentation (`docs/pwa-deployment.md`); ohne TLS lässt sich die App auf einem Smartphone außerhalb von `localhost` nicht installieren, und das ist im Repo nicht testbar. Alle drei Ansichten (Deck-Liste, Review, Add) sind konsistent verbunden, der alte Client bleibt unter `/` funktionsfähig.

## Ausgangslage (belegt, `pwa.py`, `REFERENCE.md` §4 bis §8)

| Ist | Folge |
|---|---|
| Manifest `/manifest.webmanifest`: `id`/`start_url`/`scope` = `/` | Installiert den **alten** Client. Muss für `/app/` getrennt werden |
| SW `/service-worker.js`, Scope `/`, cached nur `GET /shell/static/*`, cache-first, `CACHE = ankiweb-shell-v1` | Funktioniert; Der **alte** Worker cached dank `/shell/static/*` auch `app-client.css` (gleicher Origin); der neue Worker braucht eine eigene Regel (siehe Cache-Strategie). Versionierung nur per Konstante |
| Manifest/SW öffentlich (`PWA_PUBLIC_PATHS`) | Neue Pfade müssen ebenfalls dort eingetragen werden |
| Icons 192/512 Platzhalter, `any maskable` | Maskable-Beschnitt auf Gerät **ungeprüft** |
| Kein Test für Manifest/SW/Auth-Ausnahme | Wird hier nachgeholt (permanente Tests mit Verhaltenswert) |
| HTTPS nicht umgesetzt, Cookie ohne `secure` | Betriebsfrage, siehe unten |

## Entscheidungen

| Thema | Wahl | Begründung |
|---|---|---|
| Manifest-`id` | Das Manifest `/` behält `id: "/"` unverändert (sonst zweite installierte App für Bestandsnutzer). Das neue Manifest `/app/` erhält `id: "/app/"` und ist bewusst eine **eigene** App | Stabile Identität des bestehenden PWA-Installs |
| Manifest-Trennung | **Zweites Manifest** `/app/manifest.webmanifest` mit `id`/`scope`/`start_url` = `/app/`; Manifest `/` bleibt für den alten Client | Zwei Apps, zwei Identitäten; Scope-Trennung verhindert, dass beide sich überlagern |
| Service Worker | **Eigener Worker** `/app/service-worker.js` mit `Service-Worker-Allowed: /app/`, Scope `/app/` | Eigener Cache-Namespace und eigene Eviction; alter Worker bleibt unberührt. Max-Scope = Pfad (REFERENCE §4) |
| Cache-Strategie | Wie gehabt: nur `GET /shell/static/app-client.css` und `GET /shell/static/app/*` cache-first. **Plus** Offline-Fallback-Seite für Navigationen (`/app/offline`): bei Netzfehler statt Browserfehler (RESEARCH-pwa Szenario 2) | Kleine Verbesserung ohne Offline-Lernen. Authentifiziertes HTML wird **nie** gecacht |
| Offline-Seite | Statisches HTML, beim Install precached, ohne Nutzerdaten, ohne Auth | Darf deshalb öffentlich sein |
| Theme-Color | `<meta name="theme-color">` mit `media`-Varianten hell/dunkel; Werte = `--color-base-100` bzw. Primärfarbe der Themes `aw-light`/`aw-dark` (eine Quelle: Konstanten in Python, aus denselben Hexwerten wie `app-client.css`; Test gleicht beide ab) | Dunkel folgt `prefers-color-scheme` (DESIGN §6); verhindert Drift Theme und Manifest |
| Icons | Platzhalter beibehalten; **nicht neu erfinden**. Maskable-Safe-Zone prüfen (Glyph innerhalb 80 % Kreis) | Kein genehmigtes Design (REFERENCE §7) |
| Installations-UI | `beforeinstallprompt` → kleiner Button "Install app" in der Deck-Liste (nur wenn Ereignis feuerte); iOS: statischer Hinweis "Share → Add to Home Screen" nur in Standalone-Erkennung `!navigator.standalone` auf iOS | Chrome-Prompt braucht Nutzerinteraktion (RESEARCH-pwa §3); iOS installiert manuell |
| Update-Strategie | `CACHE`-Konstante enthält Build-Hash der App-Assets (aus Dateimtime oder Paketversion), nicht manuelles `v1` | Verhindert vergessenes Bumping (REFERENCE §6 "Eviction nur per Konstante") |
| Alter Client | Unverändert; `shell.html.jinja` behält Registrierung für `/service-worker.js` | Kein Eingriff in bestehende Seiten |
| Navigation | Gemeinsame Leiste/Links in Layout (Plan 1) ergänzt: Deck-Liste ↔ Review ↔ Add über die bereits in 2 bis 4 gebauten Links; Review-Sheet und Add-Header tragen Mode-Switch | Matrix siehe unten |

## Link-Matrix (Soll, aus REFERENCE §2.5 auf Echt-URLs übertragen)

| Von | Nach | Link | `?deck=` |
|---|---|---|---|
| Deck-Liste | Review | Learn → `/app/review?deck=<id>` | ja |
| Deck-Liste | Add | Edit/Add → `/app/add?deck=<id>` | ja |
| Review | Deck-Liste | Back → `/app/` | nein |
| Review | Add | Sheet-Switch → `/app/add?deck=<id>` | ja |
| Add | Deck-Liste | Chip → `/app/` | nein (Mockup trug `?deck`, hier unnötig: Liste ist deck-unabhängig) |
| Add | Review | Study / Finish → `/app/review?deck=<id>` | ja |
| Offline | Deck-Liste | "Try again" → `/app/` | nein |

Test: automatisierte Link-Matrix (alle Links je Seite crawlen, Ziel liefert 200/303-auf-200, kein 404).

## Dateien

| Datei | Zweck |
|---|---|
| `http_shared/pwa.py` oder neu `http_app/pwa.py` | `build_app_pwa_router()`: `/app/manifest.webmanifest`, `/app/service-worker.js`, `/app/offline` |
| `ankiweb/app.py` | Router einhängen; `PWA_PUBLIC_PATHS` um drei Pfade erweitern (Auth-Guard) |
| `templates/app/base.html.jinja` | Manifest-Link, Theme-Color (2x), Apple-Tags, Apple-Touch-Icon, SW-Registrierung Scope `/app/` |
| `static/app/install.js` | `beforeinstallprompt`, iOS-Hinweis |
| `templates/app/offline.html.jinja` | Offline-Seite. Styling: precachte `/shell/static/app-client.css` (Install-Schritt, Regel siehe Cache-Strategie) |
| `tests/app_client/test_app_pwa.py` | Manifest, SW, Auth, Cache-Regeln |
| `tests/app_client/test_app_links.py` | Link-Matrix |
| `docs/pwa-deployment.md` | HTTPS, Host-Whitelist, Cookie, Installation Android/iOS |
| `design/reviewer-redesign/REFERENCE.md`, `DESIGN.md` | Aktualisieren (neue Routen, Persistenzentscheidung, Verifikationsstatus) |

## Aufgaben

### 5.1 Manifest und Worker für `/app/`
- [ ] Manifest: `name` "AnkiWeb", `short_name` "Anki", `id`/`start_url`/`scope` `/app/`, `display: standalone`, Farben, Icons (bestehende Dateien), `application/manifest+json`.
- [ ] Worker-Quelle als Python-Konstante wie `SERVICE_WORKER_JS`; Header `Cache-Control: no-cache`, `Service-Worker-Allowed: /app/`.
- [ ] Fetch-Handler: (a) `GET` auf `/shell/static/app-client.css` und unter `/shell/static/app/` cache-first; (b) Navigationen (`req.mode === "navigate"`, Pfad unter `/app/`): `fetch` network-only, bei Fehler `caches.match("/app/offline")`; (c) **alles andere nicht abfangen**.
- [ ] `install`: precache `/app/offline` und `/shell/static/app-client.css` (Offline-Seite braucht Stil), danach `skipWaiting`. Fetch-Handler (a) deckt `GET /shell/static/app-client.css` und `/shell/static/app/*` ab (Pfadpräfix-Liste, nicht nur `/shell/static/app/`).
- [ ] `activate`: alte Caches mit Präfix `ankiweb-app-` löschen, `clients.claim()`.
- [ ] Cache-Name mit Build-Hash. Der Hash umfasst `app-client.css` und `shell_src/app/*.js`, damit eine CSS-Änderung den cache-first-Eintrag nicht veraltet stehen lässt (sonst bleibt altes Styling auf Geräten).
- [ ] `PWA_PUBLIC_PATHS` erweitern; **`/app/offline` öffentlich** (enthält keine Daten), `/app/` und Rest bleiben geschützt.

Tests (`test_app_pwa.py`), nur Verhalten:
- [ ] Mit Passwort: Manifest, Worker, Offline-Seite → 200 ohne Cookie; `/app/` → 303 `/login`; `/app/review` → 303.
- [ ] Manifest: `scope == start_url == id == "/app/"`; Icons existieren und liefern 200 (Datei-Existenz-Test, fängt die `.gitignore`-Falle aus Commit `b097545`).
- [ ] Worker-Header: `Service-Worker-Allowed: /app/`, `no-cache`.
- [ ] Alter Client unverändert: `/manifest.webmanifest` `scope == "/"`.
- [ ] **Worker-Logik unter bun mit Fake-`caches`/`fetch`** (Methode aus RESEARCH-fastpwa §4, bewährt): `/shell/static/app-client.css` und `/shell/static/app/*.js` werden gecacht; `/app/` (HTML), `/app/review`, `POST` werden **nie** gecacht; Navigation bei Netzfehler liefert Offline-Seite; nach Cookie-Entzug wird kein Auth-HTML aus Cache geliefert. Falls `bun` in CI fehlt: Test per `pytest.mark.skipif(shutil.which("bun") is None)`.

### 5.2 Layout-Einbindung
- [ ] `base.html.jinja`: `link rel=manifest href=/app/manifest.webmanifest`, zwei `theme-color` mit `media="(prefers-color-scheme: ...)"`, `apple-mobile-web-app-capable`, `apple-mobile-web-app-title`, `apple-touch-icon`, Registrierung `register("/app/service-worker.js", {scope: "/app/"})`; Fehler nicht schlucken, sondern `console.warn` (REFERENCE-Stand schluckt still; schlechter zu debuggen).
- [ ] `viewport-fit=cover` (Plan 1) und Safe-Area-Padding in allen drei Seiten verifizieren.
- [ ] Standalone-Display: Zurück-Navigation per UI vorhanden (kein Browser-Chrome): jede Seite hat Back/Exit (HUD-Back, Add-Exit, Deck-Liste = Wurzel).

### 5.3 Installations-UX
- [ ] `install.js`: `beforeinstallprompt` abfangen (`preventDefault`, merken), Button in Deck-Liste einblenden, `prompt()` bei Klick; `appinstalled` blendet aus.
- [ ] iOS-Hinweis nur auf iOS-Safari außerhalb Standalone, schließbar; Zustand **nicht** in `localStorage` (Server-Wahrheit-Regel gilt für App-Daten; hier nur UI-Komfort: `sessionStorage` reicht, kein Persistenzzwang).
- [ ] Beides ist **nicht automatisiert prüfbar** auf echten Geräten → im Verifikationsstatus offen führen.

### 5.4 Link-Matrix und End-to-End
- [ ] `test_app_links.py`: pro Seite alle `<a href>` einsammeln, intern folgen, Statuscodes prüfen, Matrix oben abgleichen.
- [ ] Playwright-Gesamtfluss: Deck-Liste → Learn → 3 Karten bewerten → Back → Zähler gesunken → Edit/Add → Karte hinzufügen → Study → neue Karte erscheint im Review.
- [ ] Playwright: Offline simulieren (`context.set_offline(True)`), Navigation zu `/app/` zeigt Offline-Seite statt Browserfehler; Online → Retry funktioniert.
- [ ] Chromium-Installierbarkeit: `Page.getInstallabilityErrors` und `Page.getAppManifest` per CDP für `/app/` (Methode aus REFERENCE §5, "keine Fehler" erwartet).
- [ ] Lighthouse-/Konsolencheck optional.

### 5.5 Dokumentation und Betrieb
- [ ] `docs/pwa-deployment.md`: HTTPS ist **Voraussetzung** für Installation auf Geräten außerhalb `localhost` (RESEARCH-pwa §1); Reverse-Proxy-Beispiel (Caddy), `ANKIWEB_ALLOWED_HOSTS`, WebSocket nicht nötig für den neuen Client (kein `/ws`), Cookie-`secure`-Flag unter HTTPS (aktuell nicht gesetzt: **eigene kleine Änderung** `secure=request.url.scheme == "https"` im Login-Cookie, mit Test; sonst als bekannte Lücke dokumentieren).
- [ ] `REFERENCE.md`: neue Routen, Persistenz pro Karte, Verifikationsstatus ehrlich aktualisieren (was wirklich gelaufen ist, was nicht: Gerätetest, HTTPS, Maskable).
- [ ] `DESIGN.md` §4/§5/§6: Porting-Abschnitt ersetzen (Mockups sind jetzt umgesetzt unter `/app/*`, nicht mehr "Jinja-Templates des alten Reviewers anpassen"), Finish-Semantik, Queue-Filter-Ergebnis aus Plan 3.
- [ ] Screenshots neu erzeugen (aktuell veraltet, REFERENCE §8).
- [ ] `README.md`: Abschnitt "Mobile PWA (`/app/`)"; die Zeile "theming comes only from daisyUI's built-in light/dark themes" auf den Altclient einschränken und `/app/*` (eigene Themes `aw-light`/`aw-dark`, Dunkel nur per Betriebssystem) ergänzen. Vermerk: Nacht-Toggle des alten Clients wirkt nicht auf `/app/`.

## Akzeptanz
- Chromium meldet für `/app/` keine Installierbarkeits- und Manifestfehler.
- Alter Client und alter Worker unverändert funktionsfähig (bestehende Suite grün).
- Offline zeigt Offline-Seite; kein authentifiziertes HTML im Cache (Worker-Test).
- Link-Matrix vollständig, Gesamtfluss grün.
- Dokumentation benennt offen: Gerätetest Android/iOS, HTTPS-Praxis, Maskable-Beschnitt.

## Synchronität Worker-Pfad und Registrierung

Worker-Pfad und Scope stehen an drei Stellen: Route in `pwa.py`/`http_app/pwa.py`, `register(...)` in `base.html.jinja` (neu) und `shell.html.jinja` (alt, bleibt `/service-worker.js`, Scope `/`). Ein Test liest die Registrierung aus dem gerenderten HTML und prüft, dass Pfad und Scope zur Route und zum `Service-Worker-Allowed`-Header passen.

## Risiken
| Risiko | Gegenmaßnahme |
|---|---|
| Zwei Manifeste/Worker verwirren Installation (Chrome bietet beide an) | Klare Scopes; Test dass Manifest `/` den Scope `/` behält; manuelle Prüfung der Install-Auswahl |
| Worker-Scope `/app/` vs. Registrierung | Test: `navigator.serviceWorker.getRegistration("/app/")` aktiv und kontrolliert die Seite (Playwright) |
| cache-first liefert veraltetes `app-client.css` nach Redeploy | Build-Hash im Cache-Namen (5.1); Test: Hash ändert sich bei geänderter CSS-Datei |
| `/app/offline` öffentlich = Fingerprint der App | Statisch, ohne Daten; akzeptiert |
| Cookie ohne `secure` unter HTTPS | 5.5, mit Test |
| iOS-Verhalten (Eviction, Add-to-Home) | **ungeprüft**, offen dokumentiert |
| Maskable-Icons beschnitten | Safe-Zone-Prüfung, Hinweis in Doku |

## Commits
1. `Add /app manifest, worker and offline page`
2. `Exempt app PWA paths from auth gate`
3. `Wire manifest, theme-color and worker registration into app layout`
4. `Add install prompt and iOS hint`
5. `Add PWA tests: auth, manifest, worker cache rules`
6. `Add link matrix and end-to-end flow tests`
7. `Set secure login cookie under https`
8. `Add PWA deployment doc; update DESIGN and REFERENCE`
