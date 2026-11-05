# 0001: Mobiler Lern-Client dauerhaft getrennt vom bestehenden Client

Status: akzeptiert

## Entscheidung

`/app/*` ist ein eigenstaendiger, schlanker Lern-Client (Deck-Liste, Review, Karten hinzufuegen) neben dem bestehenden Client unter `/`. Er ersetzt ihn nicht. Verwaltung (Browser, Graphs, Deck-Optionen, Import) bleibt im bestehenden Client.

## Kontext

`DESIGN.md` und `RESEARCH-independent-client.md` sprachen zunaechst davon, die Jinja-Seiten zu "ersetzen". Die Plaene 1 bis 6 bilden aber nur drei Ansichten ab.

## Folgen

- Eigener Build-Entry `app-client.css` mit eigenen daisyUI-Themes `aw-light`/`aw-dark`; kein `app.css`, `theme.css`, `bootstrap.js` unter `/app/*`.
- Dunkelmodus nur per Betriebssystem; der Nacht-Toggle des alten Clients wirkt dort nicht.
- Zwei Manifeste (`id: "/"` alt, eigenes unter `/app/`) und zwei Service-Worker-Scopes.
- Doppelte Pflege von Stil und Texten ist dauerhaft, nicht nur Uebergang.

## Verworfen

- Schrittweiser Ersatz des alten Clients: es fehlen Plaene fuer Browser, Einstellungen, Import.
- Mobil-Redirect von `/`: braucht Geraeteerkennung und Rueckweg-Regel, loest die Doppelpflege nicht.
