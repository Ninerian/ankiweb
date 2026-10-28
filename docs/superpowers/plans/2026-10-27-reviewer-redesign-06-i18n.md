# Plan 6: Mehrsprachigkeit (i18n) für `/app/*`

Teil von [00-overview](2026-10-27-reviewer-redesign-00-overview.md). Voraussetzung: [Plan 1](2026-10-27-reviewer-redesign-01-independent-client.md) (Paket, Templates). Wirkt auf Pläne 2 bis 5 (Texte, `<html lang/dir>`, Manifest).

> **Reihenfolge (Entscheidung):** Plan 6 läuft **nach Plan 1 und vor 2/3/4**. Davon zuerst 6.0 bis 6.2 und 6.4. Aufgabe 6.3 (Templates umstellen) entfällt für 2 bis 4, weil sie gleich mit `tr`/`s` entstehen; sie bleibt nur für Plan 5 (Offline-Seite) und für die Prüfung durch das Gate `test_no_hardcoded_text`. 6.5 (Manifest, Cache-Hash) wird in Plan 5 umgesetzt.
Bestehende Lösung: `docs/superpowers/plans/2026-06-02-ankiweb-i18n-i1-language-plumbing.md`, `…-i2-screens.md`, `…-i3-preferences.md`.

**Ziel:** Alle sichtbaren Texte von `/app/*` folgen `ANKIWEB_LANG`, wie der Rest der App. Keine zweite Sprachquelle, kein In-App-Umschalter (gleiche Regel wie heute, README "Language").

**Evidenzlegende:** *belegt* = im Repo gelesen oder in diesem Repo ausgeführt (anki 25.9.4, `.venv`); *ungeprüft* = nicht getestet; *[INFERENCE]* = Schluss von mir.

---

## 1. Ist-Stand (belegt)

| Baustein | Fundort | Verhalten |
|---|---|---|
| Sprachwahl | `core/config.py:43,69` | `Settings.lang` aus `ANKIWEB_LANG`, leer = Englisch. **Beim Start fest**, kein Umschalter, Neustart nötig |
| Anwendung | `adapters/outbound/anki_collection_adapter.py:43,59` | `open()`/`reopen()` rufen `anki.lang.set_lang(lang or "en")` vor `Collection(...)` |
| Translator | `core/i18n.py` | `from ankiweb.core.i18n import tr`: Modul ruft beim Import einmalig `set_lang` (sonst `TypeError` ohne Collection). Immer **hierher** importieren, nie aus `anki.lang` |
| Jinja | `http_shared/templating.py:35,36` | Globals `tr` und Filter `tr_clean` (entfernt `&`-Akzeleratoren, `:` am Ende, Unicode-Isolate U+2068/U+2069) |
| Katalog | Anki-Fluent, `anki._fluent` | **1763** Schlüssel, 55 Sprachen (`anki.lang.langs`). Schlüssel werden zur Laufzeit aufgelöst, folgen also der aktiven Sprache |
| Tests | `tests/test_i18n.py`, `test_i18n_screens.py`, `test_tr_clean.py`, `test_config_lang.py` | Frischer Interpreter, Idempotenz, Env, `tr_clean`. Autouse-Fixture setzt Englisch vor jedem Test |
| `<html lang>` | `templates/shell.html.jinja:2`, `login.html.jinja:2` | **fest `lang="en"`**, kein `dir`. Für `/app/*` falsch bei jeder anderen Sprache |

**Was nicht geht (belegt):**
- Der Backend nimmt **keine eigenen Fluent-Bundles**: `RustBackend(langs, server)` und `translate(module_index, message_index, **args)` kennen nur Indizes des eingebauten Katalogs. Eigene Schlüssel wie `app_streak` lassen sich dort nicht eintragen.
- Anki hat **keinen** Schlüssel für einige Mockup-Texte (Suche ergab null Treffer): "Streak", "Hint"/"Hinweis", "Example sentence", "No decks found", "Your study space", "No cards added yet", "Keep adding more cards", u. a.
- Falsche Annahmen aus dem Mockup, die der Code widerlegt: `studying_suspend_card`, `actions_flag`, `actions_done` **existieren nicht**. Richtig: `actions_suspend_card`, `studying_flag_card`, `browsing_flag`/`actions_set_flag`.

## 2. Entscheidung

**Zwei Schichten, eine Aufrufform.**

1. **Anki-Katalog zuerst** (`tr.<key>()`): Für jeden Text mit passendem Schlüssel. Übersetzung in 55 Sprachen gratis, Wortlaut wie in Anki (Policy "faithful-to-Anki" aus I2).
2. **Eigener Katalog nur für Lücken**: kleines Python-Modul `core/app_client/strings.py` mit `dict[lang, dict[key, str]]`, Englisch **vollständig** (Quelle der Wahrheit), weitere Sprachen **optional** und mit Fallback auf Englisch. Aufruf identisch aus Jinja: `{{ s("streak") }}`.

| Alternative | Verworfen weil |
|---|---|
| Eigene `.ftl`-Bundles in den Backend laden | Geht nicht (belegt, §1) |
| Gettext/Babel | Neue Abhängigkeit und Tooling für ~25 Strings; zweiter Mechanismus neben Anki ohne Not |
| Client-JS-i18n (JSON laden, im Browser ersetzen) | Der Client rendert Texte serverseitig (Jinja plus Datastar-Patches); ein zweiter Weg würde Texte doppelt pflegen und Flackern erzeugen |
| Alles Englisch hardcodiert lassen | Widerspricht "bestehende App hat i18n" und der Nutzerbasis (Mockup ist deutsch/englisch gemischt) |
| Sprache pro Request (`Accept-Language`) | Bricht das Einsprachen-Modell (`set_lang` ist **prozessglobal**, belegt `anki_collection_adapter.py:55-58`); würde Race zwischen Requests erzeugen |

**Wichtig, Sprachumfang [INFERENCE]:** Eigene Strings sind nur so gut übersetzt, wie ich sie pflege. Plan liefert **en + de** (Mockup-Sprache des Zielpublikums). Jede andere Sprache fällt pro Schlüssel auf Englisch zurück; das ist sichtbar und gewollt, nicht still falsch. Weitere Sprachen sind reine Daten-Ergänzung, kein Code.

### 2a. Sprachvertrag (verbindlich, 6.0)

1. **Eine Sprache pro Prozess**, gewählt beim Start durch `ANKIWEB_LANG` (`Settings.lang`). Kein `Accept-Language`, kein In-App-Umschalter (wie README "Language"), kein Toggle im Mockup.
2. **Eine Interpretationsstelle:** `resolve_lang(settings)` in `core/app_client/lang.py`. Nichts im Client liest `anki.lang.current_lang`.
3. **Settings werden durchgereicht, nicht global gehalten.** `build_app_router(get_service, settings)` löst einmal `ResolvedLang` auf und übergibt es an `render_app_page(..., lang=resolved)` (Default: Englisch, nur damit Aufrufer ohne Sprache wie Layout-Tests weiter laufen). Seiten-Bodies rendern mit `render("app/x.html.jinja", app_lang=resolved, …)`.
4. **Jinja-`s`:** `s(key, **fmt)` ist ein `pass_context`-Global und liest `app_lang` aus dem Render-Kontext (fehlt es: Fehler, kein stilles Englisch). Die reine Funktion `strings.s(key, *, lang, **fmt)` löst auf: Block `lang` → `en` → `KeyError`.
5. **Schlüsselbereiche:** `app_decks_*` (Plan 2), `app_review_*` und `app_review_complete_*` (Plan 3), `app_add_*` (Plan 4). Jeder Plan ergänzt nur den eigenen Bereich. Das Gate aus 6.2 erlaubt nur die ausdrücklich aufgelisteten, vorab angelegten Schlüssel als noch unbenutzt; der besitzende Plan entfernt seine Ausnahmen, sobald Templates diese verwenden.
6. **Anki-Schlüssel** nie raten: `getattr(tr, key)()` in `en` und `de` (Test 6.2).
7. **Vor der Parallelphase zurückgestellt:** 6.3 (Plan 2 bis 4 schreiben lokalisiert), 6.5 (Plan 5), Browser-Smoke 6.6 und `README`/`DESIGN`/`REFERENCE` in 6.7 (Dateien außerhalb des Besitzes dieses Schritts), `test_no_hardcoded_text` (Plan 1 `ping.html.jinja` ist absichtlich Klartext; Gate kommt mit Plan 5, wenn `ping` entfällt) und der Text-Vergleich in `test_html_lang_matches_rendered_text` (braucht lokalisierte Seiten aus Plan 2 bis 4). Der Prozess-Global-Test (`Accept-Language` ändert nichts) läuft mit 6.4, weil er das `/app`-Layout rendert.

**Status:** Das Klartext-Gate ist inzwischen aktiv (§6.2), mit einer engen Ausnahme für `Ready` auf der temporären Ping-Seite. Der Browser-Smoke von `/app/ping` ist ausgeführt (§6.6); der Smoke der Seiten aus Plänen 2–4 bleibt zurückgestellt.

## 3. Texte klassifizieren (Inventur aus den Mockups, belegt)

Mockups enthalten ~110 sichtbare Textknoten plus JS-Toasts und `confirm()`. Zuordnung (Auszug, Vollständigkeit prüft Test 6.4):

| Mockup-Text | Quelle | Schlüssel (belegt vorhanden, DE-Wert) |
|---|---|---|
| Decks | Anki | `actions_decks` → "Stapelübersicht" |
| Add | Anki | `actions_add` → "Hinzufügen" |
| Learn / Study | Anki | `decks_study` → "Lernen" |
| Search | Anki | `actions_search` → "Suche" |
| Again / Hard / Good / Easy | Anki | `studying_again/hard/good/easy` |
| Show Answer | Anki | `studying_show_answer` |
| Undo | Anki | `undo_undo` |
| Bury Card | Anki | `studying_bury_card` |
| Suspend | Anki | `actions_suspend_card` |
| Mark | Anki | `studying_mark_note` |
| Flag | Anki | `studying_flag_card` oder `browsing_flag` (Wortlaut im Smoke prüfen) |
| Card Info | Anki | `actions_card_info` |
| Delete Note | Anki | `studying_delete_note` |
| Set Due Date | Anki | `actions_set_due_date` |
| New / Due | Anki | `statistics_counts_new_cards`, `statistics_due_count` |
| Front / Back | Anki | `notetypes_front_field`, `notetypes_back_field` |
| Preview | Anki | `actions_preview` |
| Options | Anki | `actions_options` |
| Finish | Anki | `studying_finish` |
| Close / Cancel / Save | Anki | `actions_close`, `actions_cancel`, `actions_save` |
| Streak, Hint, Example sentence, "No decks found", "Your study space", "No cards added yet", "Keep adding more cards", "Cards ready", Toasts | **Eigen** | `strings.py` |
| Erfolgsscreen (Plan 3): Again, Hard, Good, Easy | Anki | `studying_again`, `studying_hard`, `studying_good`, `studying_easy` (belegt per `getattr(col.tr, key)()`) |
| Erfolgsscreen: "Session complete", "Reviewed", "Recall", "Current streak", "Your ratings", Recall-Hinweis, 4 Titel und 4 Untertitel (Flawless!, Great run!, Solid progress., You showed up.), Hard-Zusatzsatz, "Back to decks", "Study again" | **Eigen** | `strings.py`, Schlüssel `app_review_complete_*`. Geprüft: `statistics_reviews` ist ein Plural-Schlüssel mit Pflichtargument (kein Label), `studying_reviewed`/`studying_current_streak` existieren nicht. `scheduling_congratulations_finished` existiert, ist aber ein Satz für ein beendetes **Deck** und passt nicht zu den Tiers |

Regel: **Schlüssel nie raten.** Jeder Anki-Schlüssel wird im Test per `getattr(tr, key)()` aufgelöst (ein Tippfehler = `AttributeError`, siehe I2). Vor Aufnahme in einen Plan/Template per `find`-Skript nach dem englischen Wortlaut suchen; ein Treffer wie `deck_config_…tooltip` (Langtext) ist **kein** Label.

## 4. Plural, Zähler, Platzhalter

- Anki-Texte mit Zahl: `tr.statistics_cards(cards=3)` liefert "3 cards"/"3 карточки" (belegt, Plural pro Sprache korrekt). Die Zahl kommt **in Unicode-Isolaten** (U+2068/U+2069); darum für Anzeige `tr_clean(...)` oder Filter in Jinja (`{{ tr.statistics_cards(cards=n)|tr_clean }}`).
- **Keyword-Namen sind pro Schlüssel verschieden** (`cards=`, nicht `count=`; `studying_card_studied_in` lehnt `count=` ab, belegt). Nie generisch `count=` annehmen; Signatur per Docstring in `anki/_fluent.py` prüfen.
- Eigene Strings: einfache `str.format`-Platzhalter (`{deck}`), **kein** Plural-Mechanismus. Wo Anki-Plural nötig ist ("14 / 20 CARDS"), Anki-Schlüssel nutzen oder Text so formulieren, dass er ohne Plural auskommt ("14 / 20").
- Unicode-Isolate in Datastar-Signalen: nie Anki-Übersetzungen in `data-*`-Ausdrücke einbetten (Quote-/Escape-Risiko). Texte nur in Element-Inhalt oder `title`/`aria-label`, **Jinja-escaped** (`autoescape=True`, belegt `templating.py`).

## 5. Dokument-Sprache, Richtung, PWA

- `<html lang="{{ html_lang }}" dir="{{ html_dir }}">` im `/app/*`-Layout (Plan 1 Basis-Template). **Quelle der Wahrheit ist `Settings.lang`, nicht `anki.lang.current_lang`.** Belegt: `set_lang("xx")` lässt `current_lang == "xx"`, die Texte sind aber Englisch; aus `current_lang` käme `<html lang="xx">` über englischem Inhalt. `set_lang` selbst prüft nichts, und `tr_legacyglobal` hat keinen Getter für die wirksame Sprache.
- Ableitung in `core/app_client/lang.py`: Ein kurzlebiger `RustBackend(langs=[settings.lang or "en"])` nutzt dieselbe Sprachwahl wie `set_lang`. `i18n_resources(modules=["actions"])` meldet die tatsächlich geladenen Bundle-Locale-IDs in Reihenfolge; bei fehlendem oder defektem Bundle bleibt Englisch. Die Modulfilterung vermeidet das Serialisieren aller Übersetzungen.
- Die Locale-ID ist nicht immer der Name des geladenen Bundles: Anki lädt für `zh-HK`/`zh-TW` traditionelles Chinesisch, sonst vereinfachtes Chinesisch (auch für `zh-Hant` ohne Region); für `pt-PT` europäisches Portugiesisch, sonst brasilianisches Portugiesisch; für `en-GB`/`en-AU` britisches Englisch, sonst das englische Template; für `ga` irisches Gälisch (`ga-IE`). `resolve_lang` berücksichtigt diese Upstream-Zuordnung und normalisiert andere geladene Locale-IDs mit `anki.lang.lang_to_disk_lang`. Das bisherige generische `en` für `en-AU` bleibt gültig. So bleibt etwa `zh-HK` als HTML-Sprache erhalten, während `pt-AO` zu `pt-BR` und `de-Foo` zu `en` wird.
- `resolve_lang(settings) -> ResolvedLang(html_lang, html_dir, catalog_lang)` liefert alle drei Werte; `catalog_lang` (Basissprache, z. B. `de`) wählt den Block in `strings.py`. `html_dir = "rtl"` wenn `anki.lang.is_rtl(base)` mit **Basissprache**. Das alte `shell.html.jinja`/`login.html.jinja` (fest `en`) bleibt unberührt.
- **Upstream-Defekt (Anki 26.9.2, 2026-10-28 gemessen):** `set_lang("fa")` meldet `Failed to create bundle` und Anki fällt auf Englisch zurück. Die Bundle-Locale-IDs erkennen den Fallback, ohne den Defekt fest im Resolver zu kodieren. Der Vergleich einzelner Schlüssel ist keine zuverlässige Laufzeit-Erkennung: `tl` übersetzt `actions_add` und `actions_decks`, verwendet aber für `studying_again()` den englischen Fallback „Again“; Fallback pro Schlüssel ist dort korrekt.
- RTL und Layout: Das Mockup nutzt physische Richtungen (`left/right`, `translateX`). Für RTL **logische** Tailwind-Klassen (`ms-*`, `me-*`, `ps-*`, `text-start`, `start-0`) und `rtl:`-Varianten bei Pfeilen ("Next →", "Back ←" spiegeln). *Ungeprüft:* wie `daisyUI 5` `join`, `steps`, `modal-bottom` unter `dir=rtl` aussehen.
- Manifest (Plan 5): `name`/`short_name`/`description` sind bisher fest ("AnkiWeb"). Pro Start-Sprache ableiten, `lang` und `dir` im Manifest setzen. `name` bleibt Markenname und wird **nicht** übersetzt; `description` ja (eigener String).
- Service Worker/Offline-Seite (Plan 5): Die precachte Offline-Seite wird in der Start-Sprache gerendert. Da die Sprache beim Start fest ist, genügt ein Cache-Name ohne Sprachanteil; **ändert sich `ANKIWEB_LANG`, ändert sich die Offline-Seite → Cache-Hash muss `lang` einschließen** (Plan 5, 5.1 ergänzen).
- Seitentitel: `render_page`/`_page_title` lösen den Titel pro Request (nicht beim Import) auf (I2-Muster); `/app/*`-Titel genauso.

## 6. Aufgaben

Jede Aufgabe: Test zuerst, dann Code, dann Commit.

### 6.0 Gate: Sprachvertrag festschreiben (kein Code)
- [x] Prozessglobaler Sprachvertrag: `test_ping_uses_startup_language_not_accept_language` prüft unterschiedliche `Accept-Language`-Header gegen dieselbe Startsprache.
- [x] Entscheidung dokumentiert (§2a): kein In-App-Switcher, kein Toggle im Mockup.

### 6.1 `core/app_client/strings.py` und Jinja-Funktion `s`
- [x] `STRINGS: dict[str, dict[str, str]]` mit `en`/`de`, `snake_case` und den Schlüsselbereichen `app_*`.
- [x] `s(key, *, lang, **fmt)` verwendet die aufgelöste Katalogsprache aus dem Kontext, nicht `anki.lang.current_lang`: Sprachblock → Englisch → `KeyError`.
- [x] Jinja-Global `s` neben `tr`/`tr_clean`; Core importiert keine Adapter.
- [x] Tests für Fallback, `KeyError`, Platzhalter, Jinja-Escaping und unterschiedliche Render-Kontexte. Ein `set_lang`-Wechsel allein beeinflusst eigene Strings absichtlich nicht: Quelle bleibt `Settings.lang`.

### 6.2 Vollständigkeits-Test (Quelle der Wahrheit)
- [x] `test_strings_complete`: referenzierte Schlüssel müssen in `en` stehen, alle nicht-englischen Schlüssel in `en`; nur ausdrücklich benannte Seed-Schlüssel dürfen vor Plänen 2–4 noch ungenutzt sein.
- [x] `test_anki_keys_resolve`: Anki-Inventur und referenzierte Methoden werden in `en` und `de` geprüft; erforderliche Argumente werden anhand der Signatur berücksichtigt.
- [x] `test_no_hardcoded_text` prüft sichtbare Textknoten und Attribute; ausdrücklich ausgenommen sind der Markenname und `Ready` auf der temporären Ping-Seite.

### 6.3 Templates der Pläne 2 bis 5 umstellen
- [ ] Plan 2 (Deck-Liste), Plan 3 (Review, Actions-Sheet, Toasts), Plan 4 (Wizard, Summary, Toasts, `confirm`-Ersatz), Plan 5 (Offline-Seite). Pro Plan: alle Texte aus §3 ersetzen. **Nur Text**: nie IDs, Klassen, `data-*`, Routen, Signalnamen ändern (I2-Regel).
- [ ] **JS-seitige Texte** (Toasts, `confirm`, Label-Wechsel "Next: Back →") dürfen nicht im JS stehen: Server rendert sie in `data-*`-freie Elemente (`<template>`/versteckte `<span>`) oder liefert sie in der Datastar-Patch-Antwort. Kein i18n-JSON im Client.
- [ ] `title`, `aria-label`, `placeholder`, `alt` werden **ebenfalls** übersetzt (häufig vergessen; Test 6.2 deckt Attribute ab).
- [ ] Beispieltexte im Editor-Placeholder ("e.g. die Herausforderung") sind **Beispiele für Deutsch-Vokabeln**, keine UI-Texte: Entscheidung offen (§8), bis dahin eigener String pro Sprache.

### 6.4 `<html lang/dir>` und Layout
- [x] `app/base.html.jinja`: `<html lang>` und `dir` kommen aus `resolve_lang(settings)`; die Ping-Seite nutzt den Render-Kontext. Offline-Seite und Login-Weiterleitung bleiben bei Plan 5.
- [x] Tests `tests/app_client/test_i18n_lang.py`: dokumentieren die Auflösung einschließlich `zh_HK`, `ga`, `pt_AO`, `De`, `nb-123`, `zh-Hant` und `de-Foo` und vergleichen gerendertes HTML mit tatsächlichen Anki-Übersetzungen der passenden Referenz-Bundles.
- [x] `test_all_available_languages` vergleicht Übersetzungen und prüft die aufgelöste Richtung für alle Codes aus `anki.lang.langs`. Der Vergleich aller lokalisierten Seitentitel wartet auf Pläne 2–4.
- [ ] Logische Tailwind-Klassen statt `left/right` (Review-Review beim Template-Umbau in den Plänen 2 bis 4), Pfeilzeichen per `rtl:`-Variante spiegeln.

### 6.5 Manifest, Offline, Cache-Hash
- [ ] Plan 5: `MANIFEST["lang"]`, `dir`, lokalisierte `description`. Test pro Sprache.
- [ ] Cache-Name enthält Hash aus `lang` (Plan 5 Task 5.1). Test: `ANKIWEB_LANG` ändern → anderer Cache-Name.

### 6.6 Sprachsmoke (echter Browser, ungeprüft bis ausgeführt)
- [ ] Server mit `ANKIWEB_LANG=de` und `ANKIWEB_LANG=ar` starten; `/app/`, `/app/review`, `/app/add` bei 375x812 prüfen: keine englischen Reste außer Markenname, kein Textüberlauf (deutsche Wörter sind länger: "Fälligkeitsdatum setzen", "Karte bis morgen aufschieben"), RTL spiegelt korrekt.
  Vorab-Smoke auf `/app/ping` im Chromium bei 375×812: `ANKIWEB_LANG=de` → `<html lang="de" dir="ltr">`, `ANKIWEB_LANG=ar_SA` → `<html lang="ar" dir="rtl">`. `Ready` ist das unveränderte Plan-1-Ping-Label.
- [ ] Überlauf-Test: längste Anki-Übersetzung pro Schlüssel über alle 55 Sprachen messen (`max(len(getattr(tr,k)()))` mit `set_lang` je Sprache) und gegen Button-Breite prüfen; Ease-Kacheln und Actions-Sheet sind die engsten Stellen.
  Messung 2026-10-28 über alle Anki-Sprachcodes für 12 Review-/Aktions-Labels: längste Ease-Labels `Again` 11, `Hard` 9, `Good` 8, `Easy` 10 Zeichen; `studying_flag_card` 29 und `studying_bury_card` 28 Zeichen. Vergleich mit realen Button-Breiten und übrigen Labels erst mit Plan 3 möglich. Zeichenlänge ist kein Ersatz für gemessene Pixelbreite.
- [ ] Screenshots de/ar neben `en` in `design/reviewer-redesign/` nur auf Wunsch (Repo-Größe).

### 6.7 Dokumentation
- [ ] `README.md` "Language": Satz ergänzen, dass `/app/*` dieselbe Variable nutzt; eigene Strings nur en/de, sonst Fallback Englisch.
- [ ] `DESIGN.md`/`REFERENCE.md`: Abschnitt "Sprachen" (Mechanismus, Fallback, RTL-Status).
- [x] Anleitung in diesem Plan: Sprache ergänzen durch neuen Sprachblock in `strings.py`; Schlüssel müssen in `en` existieren und dieselben Format-Platzhalter haben. Fehlende Übersetzungen fallen pro Schlüssel auf Englisch zurück. Anschließend `uv run pytest tests/app_client/test_i18n_complete.py` ausführen.

## 7. Commits

1. Add `core/app_client/strings.py` and Jinja `s` with fallback chain
2. Add completeness tests (strings, anki keys, no hardcoded text)
3. Localize deck list templates (plan 2)
4. Localize review templates and toasts (plan 3)
5. Localize add wizard (plan 4)
6. Set html lang/dir and logical-direction classes
7. Localize manifest and offline page, include lang in cache hash
8. Document i18n (README, DESIGN, REFERENCE)

## 8. Risiken und offene Punkte

| Risiko / offen | Umgang |
|---|---|
| Eigene Strings nur en/de; andere Sprachen sehen Englisch für Lücken (z. B. "Streak") | Gewollt, dokumentiert (6.7). Alternative: Streak über vorhandenen Anki-Begriff lösen, falls einer passt (*ungeprüft*) |
| Anki-Wortlaut weicht vom Mockup ab (z. B. `studying_bury_card` = "Bury Card" vs. DE "Karte bis morgen aufschieben", deutlich länger) | Policy "faithful-to-Anki" (I2); Überlauf-Test 6.6; bei Platzproblem Label kürzen **per eigenem String**, nicht per CSS-Abschneiden |
| Sprache zur Laufzeit nicht wechselbar | Bewusst, wie heute. `set_lang` ist prozessglobal (belegt) |
| Unicode-Isolate in Zahlen-Übersetzungen | `tr_clean`/Filter in Jinja (6.3); Test mit `statistics_cards(cards=3)` |
| RTL bei daisyUI-Komponenten | *Ungeprüft*; 6.6 prüft `ar`. Wenn `join`/`steps` kippen, eigene `rtl:`-Overrides unter `@layer components` |
| Beispieltexte im Editor sind Lerninhalt, nicht UI | Offen: eigene Strings pro Sprache oder neutral lassen. Entscheidung durch Nutzer |
| Mockup-Fehlannahmen bei Schlüsseln | §1 und §3 nennen belegte Namen; Test 6.2 fängt Rest |

**Nicht im Scope:** In-App-Sprachumschalter; Übersetzung von Karteninhalt (ist Nutzerdaten); Offline-Strings im Client; Übersetzung des Markennamens "AnkiWeb"; automatische Browser-Spracherkennung.
