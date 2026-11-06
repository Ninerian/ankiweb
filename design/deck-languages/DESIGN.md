# Stapel-Sprachen: Design-Entscheidungen

Mocks (standalone HTML, kein Netzwerk, UI-Sprache Deutsch), Sprache der Doku: Deutsch. Speicherort-Empfehlung siehe `RESEARCH.md` (Marker in Stapelbeschreibung `desc`).

| Datei | Inhalt |
|---|---|
| `create-deck-mockup.html` | „Neuer Stapel“ + Sprachen. Demo-Chips: Leer, Ausgefüllt, Gleiche Sprache, Nur eine Sprache, Keine Sprachen |
| `deck-settings-mockup.html` | Neuer Dialog „Stapel-Einstellungen“ über Deck-Menü (⋯). Demo-Chips: Deck-Menü, Unverändert, Geändert, Gleiche Sprache |

Bedienung: obere Demo-Leiste (nur Mock-Chrome, nicht Produkt) wechselt Hell/Dunkel + Zustand. URL-Parameter: `?theme=dark&state=changed` (Mock 2: `menu|unchanged|changed|same`; Mock 1: `empty|filled|same|incomplete|none`; `open=0` lässt den Dialog zu).

## Entscheidungen

- **Designsprache** aus `reviewer-redesign` übernommen: 2.5px-Borders, harte Schatten, Gelb-Akzent `#ffd13b`, Pillen-Chips, `neo-press`-artiger Press-Effekt, System-Fonts (keine Webfonts → `file://` ohne Requests). Tokens wie in `_deck_sheet.html.jinja` / `decks-mockup.html` (modal-box-Rahmen, `fieldset-legend`, Input mit Schatten, Emoji-Tabs/-Grid, Preview-Karte gestrichelt).
- **Sheet-Aufbau** dreiteilig: Kopf fix, Body scrollt, Footer fix (Erstellen / Abbrechen+Speichern immer erreichbar bei 375×667). Ab 640px zentrierter Dialog statt Bottom-Sheet.
- **Begriffe**: Ursprungssprache = „die Sprache, die du schon kannst“, Zielsprache = „die Sprache, die du lernst“ (Hinweis unter den sichtbaren Selects, da sonst mehrdeutig).
- **Sprachwahl**: native `<select>` (OS-Picker mobil, Tastatur/A11y gratis) mit Flaggen-Badge links (Emoji) und Kürzel im Optionstext (`Spanisch · ES`) als Fallback, wo Flaggen-Emoji nicht rendern (Windows). Latein: 🏛️ statt Flagge.
- **Tauschen**: Pillen-Button zwischen den Selects (gestrichelte Verbindungslinie), Icon dreht sich. Disabled, wenn beide leer oder „Keine Sprachen“. In beiden Dialogen steht der Button auf einer Zeile mit dem Label „Zielsprache“ und hat zu beiden Selects denselben Abstand.
- **„Keine Sprachen“**: Segment-Schalter „Sprachstapel | Keine Sprachen“. In beiden Dialogen werden Sprachauswahl und Erklärung ausgeblendet; beim Zurückwechseln bleiben zuvor gewählte Sprachen erhalten. In den Stapel-Einstellungen warnt ein Hinweis vor dem Entfernen bestehender Sprachangaben beim Speichern. Beide Sprachen leer = noch nicht entschieden, Erstellen gesperrt.
- **Validierung** (Meldung direkt unter dem Segment, nicht unter den Selects, damit sie bei 375×667 ohne Scrollen sichtbar ist): gleiche Sprache = Fehler (roter Rand + Schatten an beiden Selects, `role=alert`, `aria-invalid`), nur eine Sprache = Warnung, nichts gewählt = keine Meldung. Erstellen/Speichern gesperrt, solange ungültig.
- **Flaggen-Vorschlag**: Chip „Flagge von Spanisch als Emoji nutzen“, wenn Zielsprache gewählt und Emoji abweicht (Neuer Stapel).
- **Sprach-Chip** `🇩🇪 DE → 🇪🇸 ES` in Preview und Stapelliste; gestrichelt bei „Keine Sprachen“/offen.
- **Einstiegspunkt**: Mobile `/app/decks` (`app/_deck_row.html.jinja`) hat derzeit nur „Lernen“ und „Bearbeiten“, kein Per-Deck-Menü. Der Mock schlägt deshalb ein neues ⋯-Kebab im Kopf der Stapelkachel vor; es öffnet das Menü mit „Stapel-Einstellungen“ und „Stapel löschen“. Das bestehende Desktop-Dropdown (`deckbrowser_list.html.jinja`) enthält dagegen Optionen, Umbenennen und Löschen; das Mock-Menü ist ein Vorschlag, kein Abbild dieses Dropdowns.
- **Stapel-Einstellungen**: Zustand „geändert“: blaue Pille „N ungespeicherte Änderungen“ mit blauem Punkt und blaue „geändert“-Tags an betroffenen Feldern, Speichern erst dann aktiv. Die Markierungen unterscheiden sich farblich von den gelben Buttons. Reihenfolge Name → Sprachen → Emoji (Emoji-Picker ist hoch und ändert sich selten). Eine gesonderte Export-Hinweiskarte wird nicht angezeigt.
- **Dark Mode**: systemgesteuert (`prefers-color-scheme`), Demo-Toggle überschreibt; gleiche Tokens wie Referenz (`#121316`/`#1e2025`, Schatten schwarz, Border hell).
- **A11y**: Dialog `aria-modal` + `inert` im geschlossenen Zustand, Labels/`aria-describedby`, `aria-live` für Meldungen, Fokusring 3px, `prefers-reduced-motion` beachtet.

## Screenshots

Die lokal erzeugten, nicht committeten Screenshots folgen dem Schema `screenshot-<mock>-<zustand>-<light|dark>-<mobile|desktop>.png` (mobil 375×667 @2x, Desktop 1280×800; Einstellungen zusätzlich mit `…-scrolled.png`).
