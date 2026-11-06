# Stapel-Sprachen: Speicherorte im Export/Import (Spike)

Ziel: Ursprungs-/Zielsprache pro Stapel speichern, so dass sie `.apkg`/`.colpkg`-Export + Import in frische Collection überleben.
Alles unten stammt aus echtem Lauf mit `anki==26.9.2` (Repo-Pin): Wegwerf-Skripte `/tmp/dlspike/spike*.py` (nicht committet).
Methode: Collection A bauen → `export_anki_package` (je `with_deck_configs` an/aus, `legacy` an/aus) bzw. `export_collection_package` → `import_anki_package` / `import_collection_package` in frische Collection B → Werte neu lesen.

## Ergebnis-Tabelle

`✔` = nach Roundtrip unverändert gelesen, `✘` = `LOST`.

| Kandidat | .apkg (Stapel) | .apkg ohne Deck-Configs | .colpkg | Sichtbar für Nutzer | Kollisionsrisiko (beobachtet) |
|---|---|---|---|---|---|
| (a) Marker in `desc` | ✔ (`'Mein Stapel [lang:es>de]'`, auch als `<!--ankiweb:lang=es>de-->Mein Text` byte-genau) | ✔ | ✔ | Ja, als Text; als HTML-Kommentar nicht gerendert [INFERENCE: Render nicht getestet] | Nutzer ersetzt Beschreibung → Marker weg (E6). Import in bestehenden gleichnamigen Stapel **überschreibt** dessen `desc` (E2) |
| (b) Unbekannter Key im Deck-Dict (`common.other`) | ✘ `LOST` (alle Varianten, auch `legacy=True`) | ✘ | ✔ (`{'dst':'de','src':'es'}`) | Nein | Nur Vollbackup; apkg verliert ihn → als Hauptspeicher ungeeignet |
| (c) Key im DeckConfig/Preset | ✔ (`'es>de'`) | ✘ (Preset → `Default`) | ✔ | Nein | Preset wird von mehreren Stapeln geteilt: 4 Stapel nutzen Preset `Sprachen DE-EN`, Deck-Keys differieren (`es>de`/`fr>de`/`xx>yy`), Preset-Key nur einer (E9). Import dedupliziert nicht: gleichnamige Presets werden doppelt angelegt (E4/E5) |
| (d) Notiz-Tags `lang::src::es` | ✔ | ✔ | ✔ | Ja (Tag-Liste) | Pro Notiz, nicht pro Stapel; Tags wandern mit Notizen in andere Stapel; leerer Stapel hat keine Tags; Elternstapel ohne eigene Notizen → `LOST` |
| (e) Notetype/Feld-Marker | ✘ `LOST` (Key am Notetype) | ✘ | ✔ | Nein | Notetype wird über Stapel hinweg geteilt → nicht pro Stapel |
| (f) Deck-Namenskonvention `Spanisch [es>de]` | ✔ (Name bleibt) | ✔ | ✔ | Ja, im Namen | Rename löscht Marker (E8); Namen müssen eindeutig bleiben; verschmutzt `::`-Hierarchie/Anzeige |

## Randfälle

| # | Fall | Beobachtung |
|---|---|---|
| E1 | Leerer Stapel (0 Karten, `desc`-Marker) als apkg exportiert | Stapel **fehlt** nach Import komplett (nur `Default`). Betrifft jeden Kandidaten außer `.colpkg` |
| E2 | Import in bestehenden gleichnamigen Stapel mit eigener `desc` (`'Eigene Beschreibung B'`) | `desc` danach `'Mein Stapel [lang:es>de]'` – bestehende Beschreibung wird überschrieben |
| E3 | Bestehender gleichnamiger Stapel, `desc` leer | Marker übernommen |
| E4 | Bestehendes Preset `Sprachen DE-EN` (perDay=5) + Import (mit Configs) | Kein Merge: Presets `[Default, Sprachen DE-EN(20, key es>de), Sprachen DE-EN(5, kein Key)]`; Stapel zeigt auf importiertes |
| E5 | Bestehendes gleichnamiges, inhaltsgleiches Preset ohne Key | Ebenfalls Duplikat (`['Default','Sprachen DE-EN'(es>de),'Sprachen DE-EN'(LOST)]`) |
| E6 | Nutzer ersetzt Beschreibung (`<div>Mein neuer Text</div>`) | Wird verbatim exportiert/importiert; Marker weg, App kann Sprache nicht mehr lesen |
| E7 | Dasselbe apkg 2× importieren | Kein Duplikat-Stapel, `desc` bleibt gleich |
| E8 | Stapel mit Namensmarker umbenannt → Export | Marker weg, `desc`/Preset leer |
| E11 | `desc` mit HTML-Kommentar-Marker | Byte-genau erhalten (`verbatim: True`) |
| E12 | Verschachtelt: nur Kind-Stapel `Sprachen::Franzoesisch::Vokabeln` exportiert | Eltern `Sprachen`, `Sprachen::Franzoesisch` werden angelegt; Eltern-`desc` (`[lang:fr>de]`) wird mitgenommen, Kind-`desc` ebenfalls. Eltern ohne `desc` bleiben leer (keine Vererbung) |
| E13 | Repo-Stil `ie.ExportLimit(deck_id=…)` an `col.export_anki_package` (wie `routes.py::_make_export_limit`, AnkiConnect `import_export.py`) | Es wird die **ganze Collection** exportiert (5 Stapel statt 1). Die Library mappt nur `DeckIdLimit` auf `deck_id` (`pb_export_limit`); Protobuf-Limit fällt in den `else`-Zweig → `whole_collection`. Nebenbefund, nicht Teil dieser Aufgabe, nicht angefasst |

Rohdaten Kandidaten × Export (Auszug, Collection A → Spanisch, `with_deck_configs=True`):
`'Spanisch': b_deck_key=LOST a_desc='Mein Stapel [lang:es>de]' c_conf_key='es>de' d_tags=['lang::dst::de','lang::src::es'] e_nt_key=LOST`.
`.colpkg` (`legacy` True und False): alle Kandidaten (a)–(e) identisch zu Quelle erhalten.

### Proto-Roundtrip: `Deck.Common.other` und `Deck.Normal.description` direkt getestet

Per `col._backend.get_deck` / `update_deck` (Protobuf `Deck`), nicht über das Legacy-Dict (`/tmp/dlspike/spike4.py`). Felder real vorhanden: `common.other` (bytes), `normal.description`, `normal.markdown_description`. Gesetzt: `common.other = b'{"ankiweb_pb": {"src": "de", "dst": "es"}}'`, `normal.description = 'PB-desc [lang:de>es]'`, `markdown_description = True`.

| Pfad (Export → fresh B) | `common.other` | `normal.description` | `markdown_description` |
|---|---|---|---|
| .apkg (mit Configs) | `b''` ✘ | erhalten | `True` erhalten |
| .apkg ohne Configs | `b''` ✘ | erhalten | erhalten |
| .apkg `legacy=True` | `b''` ✘ | erhalten | erhalten |
| .apkg in bestehenden gleichnamigen Stapel (`other={"mine":1}`, `desc='B desc'`) | bleibt `b'{"mine":1}'` (Import mergt/überschreibt nicht) | überschrieben mit `'PB-desc [lang:de>es]'` | überschrieben |
| .colpkg | `b'{"ankiweb_pb": {"src": "de", "dst": "es"}}'` ✔ | erhalten | erhalten |

Befunde: (1) Legacy-Dict-Key aus (b) **ist** `Deck.Common.other` (nach Proto-Update liest das Legacy-Dict `ankiweb_pb` wieder). (2) `Common.other` fällt aus jedem `.apkg`, auch mit gleichem Roundtrip wie beim Legacy-Dict → bestätigt die Ablehnung von (b). (3) `Normal.description` ist der Träger von (a) und übersteht alle Pfade; das Markdown-Flag reist mit. Wichtig für die UI: ist `markdown_description` aktiv, bleibt der HTML-Kommentar-Marker im Quelltext stehen [INFERENCE: Markdown-Rendering in Anki nicht getestet].


## Empfehlung

**(a) Marker in der Stapelbeschreibung `desc`**, als HTML-Kommentar, z. B. `<!--ankiweb:lang=es>de-->`. Die App liest/schreibt den Marker und lässt den übrigen Beschreibungstext unangetastet.

Begründung (nur beobachtet):
- Einziger Kandidat, der **pro Stapel** gilt **und** apkg (mit/ohne Configs, auch `legacy`) **und** colpkg überlebt (Tabelle).
- Byte-genau erhalten (E11), Eltern-Stapel-Beschreibungen reisen im apkg mit (E12), erneuter Import erzeugt keine Dubletten (E7).
- (b) fällt durch apkg; (c) ist Preset- statt Stapel-Ebene und dupliziert sich; (e) fällt durch apkg; (d) ist notizbasiert; (f) bricht beim Umbenennen und beeinflusst Namen.

Bekannte Grenzen, die UI/Doku abdecken muss:
1. Ersetzt der Nutzer die Beschreibung in Anki komplett, ist der Marker weg (E6) → App-Hinweis im Einstellungsdialog; fehlender Marker = „Keine Sprachen".
2. Import überschreibt `desc` eines bestehenden gleichnamigen Stapels (E2) – Standardverhalten von Anki, mit Marker mitgenommen.
3. Leere Stapel exportiert Anki per apkg gar nicht (E1) – unabhängig vom Speicherort.
4. Optional (nicht nötig): Spiegel in (b) für `.colpkg`; bringt nichts, da (a) bereits colpkg überlebt.
