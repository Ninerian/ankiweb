# Reference: Reviewer Redesign Prototype and PWA Install Surface

Technical reference for the files in `design/reviewer-redesign/` and for the PWA install
surface added to the ankiweb server. It lists facts and where to find them. For the reasoning
behind the visual design see [DESIGN.md](DESIGN.md); for the research behind the PWA choice see
[RESEARCH-pwa.md](RESEARCH-pwa.md) and [RESEARCH-fastpwa.md](RESEARCH-fastpwa.md).

**Audience:** developers porting the prototype into ankiweb or operating the PWA.

**Legend:** *Verified* = observed by the author in a run. *QA-verified* = reported by a browser
subagent; its transcript is the only evidence, the author did not re-run it. *Read* = taken from
source, not executed. *Not verified* = no evidence.

---

## 1. Files

### Prototype folder `design/reviewer-redesign/`

| File | Kind | Purpose |
|---|---|---|
| `decks-mockup.html` | Static HTML | Deck list with search, empty state, per-deck Learn / Edit / Add links and a New deck sheet (name and emoji picker) |
| `mockup.html` | Static HTML | Reviewer (card stage, ease tiles, streak, actions sheet, completion feedback) |
| `editor-mockup.html` | Static HTML | Quick-add wizard (Front, Back, Preview), card stack, edit-last-card |
| `card-render.js` | Script | Shared card model and renderer used by the reviewer and the editor preview |
| `study-api-spike.py` | Archived Python | Study JSON API spike. **Not imported anywhere.** Per RESEARCH-independent-client.md the router was removed from the server code after its test |
| `DESIGN.md` | Doc | Design rationale and porting blueprint |
| `REFERENCE.md` | Doc | This file |
| `RESEARCH-enrichment.md`, `RESEARCH-independent-client.md`, `RESEARCH-pwa.md`, `RESEARCH-fastpwa.md` | Docs | Research notes |
| `screenshot-*.webp`, `screenshot-editor-*.png` | Images | 9 historical screenshots from before the deck list and the former mode switch were added; they also predate the current editor header. **Not regenerated** |

All three mockups are standalone: no build step, no external assets, no network access.

### Server files for the PWA

| File | Change |
|---|---|
| `ankiweb/adapters/inbound/http_shared/pwa.py` | New. Manifest and service worker routes |
| `ankiweb/app.py` | Mounts the PWA router; exempts both PWA paths from the password gate |
| `ankiweb/adapters/inbound/http_shared/templates/shell.html.jinja` | Manifest link, meta tags, touch icon, worker registration |
| `ankiweb/shell/static/icons/` | `icon.svg`, `icon-192.png`, `icon-512.png` |
| `.gitignore` | Adds `!ankiweb/shell/static/icons/` (the parent `ankiweb/shell/static/*` is ignored) |

---

## 2. Prototype pages

### 2.1 Deck ids

The same five ids are hard-coded in all three pages.

| `deck` id | Label | Due | New |
|---|---|---|---|
| `german-b1` | German B1 Vocab | 20 | 8 |
| `spanish-a2` | Spanish A2 | 12 | 6 |
| `biology` | Biology Cells | 9 | 4 |
| `history` | History 1900s | 15 | 5 |
| `chemistry` | Chemistry Basics | 7 | 10 |

Due and new counts exist only in `decks-mockup.html`. *Read.*

**Fallback:** a missing, empty or unknown `?deck=` resolves to `german-b1` in `mockup.html` and
`editor-mockup.html`. *QA-verified* for missing, empty, unknown and `__proto__` values on all three pages in both themes.
`decks-mockup.html` does not read `?deck=`.

### 2.2 `decks-mockup.html`

| Element | Behaviour |
|---|---|
| Search box `#deck-search` | Case-insensitive substring match on each card's `data-name`. Non-matching cards get `hidden` |
| Empty state `#empty-state` | Shown with "No decks found" when zero cards match |
| **Learn** | Links to `mockup.html?deck=<id>` |
| **Edit / Add** | Links to `editor-mockup.html?deck=<id>` |
| Progress bar | `role="progressbar"` with `aria-valuenow`. German B1 shows 70 % |

No chip, no mode switch and no persisted state (`localStorage` and `sessionStorage` are unused
in all three pages). *Read.*

### 2.3 `mockup.html` (reviewer)

| Element | Behaviour |
|---|---|
| Back button `#btn-back` | Links to `decks-mockup.html` (no `?deck=`) |
| More button `#btn-actions-sheet` | Opens the actions bottom sheet |
| Deck label `#card-deck` | Shows the resolved deck's emoji and name |

There is no deck chip or mode switch in the reviewer; reach the editor through the deck list. *Read.*

#### Session completion

After the twentieth rating, `#session-complete` replaces the card stage and review controls; the progress HUD remains. The panel shows reviewed count, current streak, all four rating counts and **Recall** = `(Hard + Good + Easy) / all ratings`, not measured accuracy. The displayed percentage is rounded; tier selection uses unrounded ratios in this order:

| Tier | Condition | Title |
|---|---|---|
| Perfect | No Again and Easy ≥ 40% | Flawless! |
| Great | Otherwise, Recall ≥ 85% | Great run! |
| Good | Otherwise, Recall ≥ 60% | Solid progress. |
| Tough | Otherwise | You showed up. |

The initial `14/20` is mockup-only demo history: 2 Again, 3 Hard, 7 Good and 2 Easy. `?complete=perfect` (or `great`, `good`, `tough` as the value) selects a completed demo history for preview. **Study again** clears the tally and streak and starts at `0/20`; **Back to decks** opens `decks-mockup.html`. The title receives focus, decorative graphics are hidden from assistive technology, and the counts are text. The screen follows the system theme and reduced-motion preference. *Read.*

### 2.4 `editor-mockup.html` (editor)

| Element | Behaviour |
|---|---|
| Header | Back button, deck-name chip and Done on the first row; added-card count on the second row |
| Deck chip `#deck-chip` | Shows emoji and name; guarded link to `decks-mockup.html?deck=<id>` |
| Active card | Note-type pill, without a repeated deck badge |
| Navigation | No editor mode switch; use the deck list to choose Learn or Edit / Add |
| Feedback | The added-card count updates without a duplicate success toast; warnings and other action feedback remain |
| Navigation guard | The chip, Back, and finish/leave actions guard uncommitted text |

**Guard rule** (`confirmDiscard`): if any of the front, back, hint or example text is non-empty,
the page shows `confirm("You have unsaved text in your current card. <action>")` and cancels the
navigation on "Cancel". Navigation and edit/finish actions are blocked while a card is committing.
The guard also applies when editing a stacked card and finishing.

### 2.5 Link matrix

| From | To | Link | Carries `?deck=` |
|---|---|---|---|
| Deck list | Reviewer | Learn | yes |
| Deck list | Editor | Edit / Add | yes |
| Reviewer | Deck list | Back button / completion: Back to decks | **no** |
| Editor | Deck list | Back button | no |
| Editor | Deck list | Chip | yes |
| Editor | Reviewer | Done → summary → Start studying (after the discard guard) | yes |

*Historical QA report*, not observed by the author: before the reviewer sheet, completion and current editor header changes, a browser subagent opened all three pages at 375 x 812 in light and dark, ran 110 navigation clicks over the five deck ids, and reported no console errors, no uncaught exceptions and a scroll width of 375 px on every page. Its transcript is the only evidence; no screenshots from that run are kept in this folder. It does not verify the current sheet, completion screen or editor header.

---

## 3. Theming

| Rule | Detail |
|---|---|
| No toggle | `#btn-theme`, `#theme-icon` and `toggleTheme()` are removed from every page. Searching the three mockups for these names returns nothing. *Verified* |
| Source of truth | Each page reads `matchMedia('(prefers-color-scheme: dark)')` at load and sets `data-theme` on the document |
| Dark palette | `[data-theme="dark"]` CSS variables |
| Contrast target | WCAG AA, 4.5:1 for text. First QA pass found Again/Easy shortcut numbers and intervals below 4.5:1 (light 2.75 to 3.75, dark down to 3.70); they were fixed and a second QA pass re-measured at 4.5:1 or above. *QA-verified* |

---

## 4. PWA routes

Both routes are served by `build_pwa_router()` in `pwa.py` and need **no login**.

| Route | Content type | Notes |
|---|---|---|
| `GET /manifest.webmanifest` | `application/manifest+json` | Fixed JSON, see 5 |
| `GET /service-worker.js` | `application/javascript` | Headers `Cache-Control: no-cache`, `Service-Worker-Allowed: /` |

### Why they are public

`_auth_guard` in `app.py` redirects every other path to `/login` when `ANKIWEB_PASSWORD` is set.
`PWA_PUBLIC_PATHS = (MANIFEST_PATH, SERVICE_WORKER_PATH)` is exempt, as is `/shell/static/`
(already exempt before). Browsers fetch the manifest without credentials. *Verified* with the
password set: both return 200 without a cookie, while `/` returns 303 to `/login`.

### Why the worker is a route

A worker's maximum scope is its own path. A file under `/shell/static/` could not control `/`.
Serving it from `/service-worker.js` gives scope `/`.

---

## 5. Manifest fields

| Field | Value |
|---|---|
| `name` | `AnkiWeb` |
| `short_name` | `Anki` |
| `id` | `/` |
| `start_url` | `/` |
| `scope` | `/` |
| `display` | `standalone` |
| `theme_color` | `#ffd43b` |
| `background_color` | `#f4f3ed` |
| `icons[0]` | `/shell/static/icons/icon-192.png`, `192x192`, `image/png`, purpose `any maskable` |
| `icons[1]` | `/shell/static/icons/icon-512.png`, `512x512`, `image/png`, purpose `any maskable` |

Chromium reported **no installability errors and no manifest errors** for this manifest
(`Page.getInstallabilityErrors` and `Page.getAppManifest`, headless Chromium, `127.0.0.1`).
*Verified.*

Chrome's published install criteria (web.dev, last updated 2024-09-19): HTTPS, `name` or
`short_name`, a 192 px and a 512 px icon, `start_url`, `display` of `standalone`, `fullscreen`,
`minimal-ui` or `window-controls-overlay`, and `prefer_related_applications` absent or false.
A service worker is not in that list.

---

## 6. Service worker

Source: `SERVICE_WORKER_JS` in `pwa.py`.

| Property | Value |
|---|---|
| Cache name | `ankiweb-shell-v1` |
| Handled requests | `GET`, same origin, path starts with `/shell/static/` |
| Strategy | Cache first; on a miss, fetch and store the response if `res.ok` |
| Not handled | Every other request. The browser's normal network path applies |
| `install` | `skipWaiting()` |
| `activate` | Deletes every cache whose name differs from `CACHE`, then `clients.claim()` |
| Eviction | Change the `CACHE` constant. There is no other invalidation |

### Cache contents

*Verified* in headless Chromium with a logged-in session and the worker controlling the page.
After requesting each of the following, the cache held only `/shell/static/…` entries:

| Requested | Cached |
|---|---|
| `/` (authenticated page) | no |
| `/add` | no |
| `/healthz` | no |
| `/_anki/css/deckbrowser.css`, `/_anki/js/deckbrowser.js` | no |
| `POST /_anki/<method>` | no (non-GET) |
| `/shell/static/*.css`, `*.js`, `icons/icon-192.png` | yes |

### Behaviour without network

*Verified*, same session, browser offline:

| Request | Result |
|---|---|
| `/shell/static/app.css` | 200, from cache |
| `/` | network error |
| `/manifest.webmanifest` | network error |

The app **does not open offline**. Only static assets are cached. An offline reviewer is a
separate design (RESEARCH-pwa.md, scenario 3).

After the session cookie is removed, `/` redirects to `/login` again, so no authenticated page
is served from the cache. *Verified.*

---

## 7. Page tags and icons

### Tags in `shell.html.jinja` `<head>`

| Tag | Value |
|---|---|
| `link rel="manifest"` | `/manifest.webmanifest` |
| `meta name="theme-color"` | `#ffd43b` |
| `meta name="mobile-web-app-capable"` | `yes` |
| `meta name="apple-mobile-web-app-capable"` | `yes` |
| `link rel="apple-touch-icon"` | `/shell/static/icons/icon-192.png` |
| Inline script | Registers `/service-worker.js` with scope `/`; errors are swallowed |

*Verified* present on the logged-in page; the worker reaches `activated` with scope
`http://127.0.0.1:8765/` and controls the page.

The tags are in the shared shell template, so they apply to every page it renders.

### Icons

| File | Size | Notes |
|---|---|---|
| `icon.svg` | viewBox 512 | Source. Cream background, yellow card with a dark offset shadow, letter "A" |
| `icon-192.png` | 192 x 192 | Rendered from the SVG with `rsvg-convert` |
| `icon-512.png` | 512 x 512 | Same |

The background fills the whole square and the glyph sits inside the centre area, so the icons
are declared `any maskable`. Whether launcher masks crop the glyph acceptably was **not
verified** on a device. The icon is a **placeholder** and has no approved design.

---

## 8. Verification status

| Area | Status |
|---|---|
| Prototype pages: layout, links, `?deck=` fallback, theme, contrast | Historical *QA-verified* report (see 2.5), predating the reviewer sheet, completion and current editor header changes; not re-run by the author of this document |
| PWA routes, auth exemption, tags, worker activation, cache contents, offline behaviour | *Verified* in headless Chromium on `127.0.0.1` |
| Chromium installability errors | None reported |
| Existing test suite | 736 passed after the PWA change |
| Install on an Android or iOS device | *Not verified* |
| HTTPS deployment | *Not verified* (tested on localhost only) |
| Maskable icon cropping on a launcher | *Not verified* |
| Permanent tests for the manifest, worker or auth exemption | None written |
| Screenshots in this folder | Pre-date the deck list, former mode switch and current editor header |
| Unsaved-text guard under a real typed-in state | Reported by the editor agent, **not reproduced** by the QA agent or by me |
