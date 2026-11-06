# 0002: Sprach-Marker in der Stapelbeschreibung

Status: akzeptiert

## Entscheidung

Das Sprachpaar eines Stapels steht als HTML-Kommentar am Anfang seiner Beschreibung `desc`, z. B. `<!--ankiweb:lang=es>de-->` (Ursprungs- vor Zielsprache). Neu geschriebene Marker tragen unmittelbar danach `<!--ankiweb:lang-separator-->\n\n`: Die eigene Kennung unterscheidet den eingefuegten Markdown-Abstand von echten Zeilenumbruechen des Beschreibungstexts. Aeltere Marker ohne Kennung bleiben lesbar und werden ohne anschliessende Textbytes entfernt. Ohne gueltigen Marker gilt „Keine Sprachen“; Unterstapel erben kein Paar. Beim Aendern des Paars entfernt die App vorhandene Marker und setzt hoechstens einen neuen vor den uebrigen Beschreibungstext. Ohne Aenderung bleiben die Stapel-Einstellungen bytegleich; bei einer Namens- oder Emoji-Aenderung wird ein gueltiger alter Marker in Markdown-Beschreibungen migriert.

## Kontext

Das Paar muss pro Stapel gelten und mit Anki-Exporten transportiert werden. Der Spike mit `anki==26.9.2` verglich sechs Speicherorte durch Export und Import in eine frische Collection: siehe [RESEARCH.md](../../design/deck-languages/RESEARCH.md). Die Beschreibung mit Textmarker ueberstand die untersuchten `.apkg`-Varianten mit und ohne Deck-Configs sowie `legacy` und auch den `.colpkg`-Roundtrip. Der HTML-Kommentar-Marker blieb im untersuchten `.apkg` bytegenau erhalten; fuer seine Sichtbarkeit in Anki Desktop wurde kein Rendering getestet. [Plan 11](../superpowers/plans/2026-11-06-reviewer-redesign-11-deck-languages.md) dokumentiert weitere Messungen und die Umsetzung.

## Folgen

- Ein leerer Stapel fehlte nach dem untersuchten `.apkg`-Export und -Import ganz. Ein Sprach-Marker kann ihn nicht erhalten.
- Beim Import in einen bestehenden gleichnamigen Stapel wurde dessen Beschreibung ueberschrieben. Dabei kann auch dessen bisheriger Marker verloren gehen.
- Ersetzt jemand die Beschreibung in Anki Desktop, kann der Marker verloren gehen. Die App kann dann kein Sprachpaar mehr lesen. Ueber die Darstellung des Kommentars in Anki Desktop wurde keine Aussage gemessen.
- Die Beschreibungsbearbeitung in der bestehenden App-Overview blendet Marker im Eingabefeld aus. Bei unveraendertem Nicht-Markdown-Text bleibt die gespeicherte Beschreibung bytegleich. Beim Bearbeiten oder Migrieren bleiben ungueltige Marker auch nach einem gueltigen ersten Marker erhalten; gueltige Duplikate werden entfernt. Diese Erhaltung schuetzt nicht vor Aenderungen in Anki Desktop oder beim Import.
- Die App entfernt Marker vor der Markdown-Verarbeitung und sanitisiert die gerenderte Beschreibung. Neu geschriebene Marker stehen durch den gekennzeichneten Abstand in einem eigenen HTML-Block, sodass auch Ankis Markdown-Renderer den Beschreibungstext danach verarbeiten kann. Beim Speichern einer Markdown-Beschreibung wird ein gueltiger alter Marker auch ohne Textaenderung migriert; bis zum Speichern kann die Darstellung in Anki fehlerhaft bleiben. Bei markierter Beschreibung verwendet die Congrats-Ansicht dafuer den rohen Decktext statt der bereits gerenderten Scheduler-Ausgabe.

## Verworfen

- (b) Unbekannter Deck-Key (`common.other`): ging in allen untersuchten `.apkg`-Varianten verloren; `.colpkg` allein reicht nicht.
- (c) DeckConfig/Preset-Key: ohne Deck-Configs verloren; Presets werden von Stapeln geteilt und beim Import gleichnamig dupliziert.
- (d) Notiz-Tags: reisen zwar mit, gelten aber pro Notiz statt pro Stapel und fehlen bei leeren Stapeln oder Eltern ohne eigene Notizen.
- (e) Notetype-Key: ging im `.apkg` verloren und Notiztypen werden stapeluebergreifend geteilt.
- (f) Marker im Deck-Namen: bleibt beim Export im Namen, geht aber beim Umbenennen verloren und belastet Anzeige, Eindeutigkeit und Hierarchie.
