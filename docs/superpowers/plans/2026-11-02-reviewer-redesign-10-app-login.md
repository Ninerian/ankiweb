# Plan 10: App-Anmeldung (`/app/login`)

> Teil von [00-overview](2026-10-27-reviewer-redesign-00-overview.md). Plan 10 ersetzt die Aussagen in [Plan 1](2026-10-27-reviewer-redesign-01-independent-client.md) und [Plan 5](2026-10-27-reviewer-redesign-05-pwa-bootstrap.md), nach denen unangemeldete App-Anfragen zu `/login` führen. Die historischen Pläne bleiben unverändert. Plan 5 ist noch nicht umgesetzt; bei seiner späteren Umsetzung sind seine PWA-Ausnahmen und das Login-Ziel mit diesem Plan abzustimmen.

**Ziel:** Die passwortgeschützte App zeigt eine Anmeldung im bestehenden Neo-Pop-Design. Alter und neuer Client erkennen dieselbe Anmeldung; nach erfolgreicher App-Anmeldung öffnet sich immer `/app/`.

> **Stand: noch nicht umgesetzt.** Dieser Plan beschreibt zukünftiges Verhalten; er ist keine Aussage über bereits implementierte oder visuell geprüfte Änderungen.

## Entscheidungen

| Frage | Entscheidung |
|---|---|
| Anmeldung | `GET` und `POST /app/login` im bestehenden App-Router. Standardformular und das vorhandene Datastar-Protokoll unterstützen. Ohne konfiguriertes Passwort oder mit gültigem Auth-Cookie geht es direkt nach `/app/`. |
| Gemeinsame Auth | `password_ok`, `cookie_ok`, Passwortauslesen, lokalisierter Fehler und `_set_login_cookie` werden wiederverwendet, nicht dupliziert. Nötige HTTP-Helfer aus `ankiweb/app.py` in ein gemeinsames Inbound-Modul auslagern: der App-Router darf nicht aus `app.py` zurückimportieren. |
| Cookie | Beide Anmeldungen setzen dasselbe `ankiweb_auth` mit dem bestehenden `auth_token` und **unveränderten** Attributen von `_set_login_cookie` (`httponly`, `samesite=lax`, `max_age=30 * 86400` und bisherige Defaults). `app_sid` ist davon unabhängig und kein Auth-Cookie. |
| Guard | Der globale `_auth_guard` bleibt zuständig. Nur exakt `/app` und Pfade unter `/app/` erhalten das App-Ziel; `/app/login` ist explizit freigegeben. Übrige Pfade und bisherige Ausnahmen bleiben unverändert. Die bestehende Freigabeliste konsistent halten, keine zweite abweichende Wahrheit einführen; `core/auth.py::OPEN_PATHS` wird vom Guard derzeit nicht verwendet. |
| Datastar | Nicht authentifizierte App-Anfragen mit `Datastar-Request` erhalten `redirect_response('/app/login')` als SSE für eine vollständige Dokumentnavigation; normale Anfragen erhalten `303 /app/login`. Der Guard beendet die Anfrage vor dem Handler: ein abgewiesener POST ändert nichts und wird nach der Anmeldung nicht erneut ausgeführt. Ungespeicherte Eingaben können bei der Navigation verloren gehen. |
| Alter Client | `/login` behält seine bestehenden GET-, Formular- und Datastar-Verträge einschließlich Erfolgsziel `/`; `/logout` löscht das Auth-Cookie und leitet weiter auf `/login`. Keine neue Abmeldefunktion. |
| Design | App-Layout `render_app_page` und vorhandene `app-client.css`/Datastar verwenden. Neo-Pop mit vorhandenen Theme-Tokens und harten Schatten; `.neo-press` nur auf bedienbaren Elementen, nicht auf statischen Karten. Hell/Dunkel folgt `prefers-color-scheme`; kein Umschalter. Keine unnötigen neuen Styles. |
| Fehler und Sprache | Feldnaher, zugänglicher Fehler einmal anzeigen: Für die Anmeldeseite den globalen `$error`-Toast im App-Layout gezielt ausblenden, damit das bestehende Fehlersignal nicht doppelt erscheint; andere Seiten bleiben unverändert. Auch ohne JavaScript muss die `401`-Seite den Fehler sichtbar rendern. Anki-Labels `tr.sync_password_label()`, `tr.sync_log_in_button()` und `tr.sync_wrong_pass()` mit `tr_clean` wiederverwenden; neue eigene Texte in `core/app_client/strings.py` auf Englisch und Deutsch anlegen. |

## Routenvertrag

| Methode und Route | Verhalten |
|---|---|
| `GET /app/login` | Passwort gesetzt und kein gültiges Cookie: `200` mit App-Anmeldeseite. Ohne Passwort oder bereits angemeldet: `303 /app/`. |
| `POST /app/login`, Formular | Korrektes Passwort: bestehendes Auth-Cookie setzen, `303 /app/`. Falsches Passwort: `401` mit sichtbarem lokalisiertem Fehler, kein Auth-Cookie. Ohne Passwort oder bereits angemeldet: `303 /app/`. |
| `POST /app/login`, Datastar | Korrektes Passwort: bestehendes Auth-Cookie setzen, SSE-Redirect nach `/app/`. Falsches Passwort: SSE-Fehlersignal `error`, kein Auth-Cookie. Ohne Passwort oder bereits angemeldet: SSE-Redirect nach `/app/`. |
| Geschütztes `/app` oder `/app/*` ohne gültiges Cookie | Normale Anfrage: `303 /app/login`. Anfrage mit `Datastar-Request`: SSE-Redirect auf `/app/login`, kein HTML-Redirect im Fetch. |
| Andere geschützte Pfade ohne gültiges Cookie | Unverändert `303 /login`; bestehende öffentliche Pfade einschließlich `/login`, `/logout`, `/healthz`, `/manifest.webmanifest`, `/service-worker.js` und `/shell/static/*` bleiben erreichbar. |

Der bestehende Origin-Guard des App-Routers gilt auch für `POST /app/login`; er wird nicht gelockert. Die bisherigen Root-PWA-Routen sind keine Umsetzung von Plan 5.

## Aufgaben

- [ ] **Baseline vor Änderungen:** `uv run pytest tests/test_auth.py tests/app_client -q` ausführen und bestehende Fehler festhalten. Ganze Module ausführen, nicht nur einzelne Testfunktionen.
- [ ] Gemeinsame HTTP-Login-Helfer ohne Importzyklus bereitstellen; alte `/login`- und `/logout`-Verträge erhalten. Cookie-Attribute und Prüfung unverändert lassen.
- [ ] Globalen Guard für `/app` und `/app/…` ändern, `/app/login` ausnehmen und Datastar-Anfragen anhand ihres Headers mit SSE beantworten. Normale App-Anfragen und alle anderen Pfade nach obigem Vertrag behandeln.
- [ ] App-Routen registrieren und das Formular im bestehenden Layout umsetzen: Passwortfeld mit Label und `autocomplete="current-password"`, Submit-Button, zugänglicher Fehler und funktionierender No-JS-POST. Fehler im Formular und globaler Toast dürfen sich nicht doppeln.
- [ ] Eigene Texte bei Bedarf in beiden Sprachkatalogen ergänzen und Anki-Labels nutzen. `test_i18n_complete.py` prüft englische Referenzen und keine vollständige deutsche Abdeckung; Deutsch daher ausdrücklich testen. Falls Anki-Labels im Template verwendet werden, das bestehende Test-Inventar passend ergänzen.
- [ ] Alle betroffenen Aufrufer und Tests an den neuen Guard-Vertrag anpassen: insbesondere `tests/app_client/test_app_shell.py`, `test_add_routes.py`, `test_decks.py`, `test_decks_create_routes.py` und `test_review_routes.py`. Der Deck-Erstellungstest sendet bereits `Datastar-Request` und muss SSE statt `303` erwarten. Weitere betroffene App-Routen und deren Testmodule vollständig erfassen; bestehende Tests nicht abschwächen.
- [ ] Nach der Implementierung `README.md`, `DOCKER.md`, `design/reviewer-redesign/DESIGN.md` und `design/reviewer-redesign/REFERENCE.md` an den tatsächlichen Anmeldevertrag anpassen; Plan 1 und 5 bleiben historisch. Die Übersicht kennzeichnet Plan 10 und dessen Vorrang.

## Akzeptanz und Prüfungen

- [ ] Ohne Cookie und mit ungültigem Cookie gehen `/app`, `/app/` und geschützte App-Unterpfade auf `/app/login`; `/appx` gehört nicht zum App-Bereich und folgt dem alten Guard. Der Login selbst erzeugt keine Schleife. Öffentliche Pfade und der alte Client bleiben wie bisher erreichbar beziehungsweise geschützt.
- [ ] Formular und Datastar-Anmeldung testen: richtiges Passwort, falsches Passwort, kein Passwort und bereits gültiges Cookie; jeweils Status, Ziel, Fehlersignal beziehungsweise sichtbares `401`-HTML und Cookie prüfen. `Set-Cookie`-Attribute der beiden Logins vergleichen; `app_sid` ist nicht das Auth-Cookie.
- [ ] Cookie aus `/app/login` öffnet `/deckbrowser`; Cookie aus `/login` öffnet `/app/`. `/logout` macht das gemeinsame Cookie ungültig. `tests/test_auth.py` vollständig weiterhin ausführen.
- [ ] Ein abgelaufenes oder ungültiges Cookie bei einem schreibenden Datastar-POST liefert SSE statt `303`; der Handler verändert keine Collection-Daten und setzt kein `app_sid`. Im Browser Dokumentnavigation zur App-Anmeldung prüfen; nach erfolgreicher Anmeldung `/app/`, keine nachträgliche Mutation. Den möglichen Verlust des ungespeicherten Entwurfs ausdrücklich berücksichtigen.
- [ ] Cross-Origin-Formular- und Datastar-POSTs auf `/app/login` bleiben vom Origin-Guard abgewiesen; gleichartige Same-Origin-Anfragen funktionieren. Bestehende Origin-Guard-Tests für App-Schreibzugriffe bleiben erhalten.
- [ ] Englisch und Deutsch explizit prüfen: Labels, Button, Fehlermeldung im Datastar-Fall und sichtbare Fehlermeldung ohne JavaScript. Der Fehler erscheint nur einmal; `test_i18n_complete.py` und die Inventarprüfung bleiben bestehen.
- [ ] App-Anmeldeseite im Browser bei 375×812 und 509×904 in hellem und dunklem Systemtheme prüfen: vorhandene Neo-Pop-Tokens, kein Theme-Schalter, keine Press-Optik auf statischen Flächen, Label, Tastaturbedienung und sichtbarer Fehler. Keine solche Prüfung als bereits erfolgt ausgeben.
- [ ] Nach Umsetzung zuerst `npm run build`, danach `uv run pytest tests/test_auth.py tests/app_client -q` und `uv run pytest -q` ausführen; damit ganze betroffene Testmodule und die vollständige Suite prüfen. Zusätzlich `uv run ruff check .`, `uv run ruff format --check .` und `uv run ty check` ausführen. Browserprüfung gegen einen isolierten Server mit aktuellem Code durchführen.
