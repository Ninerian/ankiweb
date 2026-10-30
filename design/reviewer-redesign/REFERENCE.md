# Reference: Reviewer Redesign Prototype and PWA Install Surface

Technical reference for the files in `design/reviewer-redesign/` and for the PWA install
surface added to the ankiweb server. It lists facts and where to find them. For the reasoning
behind the visual design see [DESIGN.md](DESIGN.md); for the research behind the PWA choice see
[RESEARCH-pwa.md](RESEARCH-pwa.md) and [RESEARCH-fastpwa.md](RESEARCH-fastpwa.md).

**Audience:** developers maintaining the prototype or `/app/` client, and PWA operators.

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
| `editor-mockup.html` | Static HTML | Quick-add wizard (Front, Back, Preview), card pile with count starburst, browse-and-edit list |
| `card-render.js` | Script | Shared card model and renderer used by the reviewer and the editor preview |
| `study-api-spike.py` | Archived Python | Study JSON API spike. **Not imported anywhere.** Per RESEARCH-independent-client.md the router was removed from the server code after its test |
| `DESIGN.md` | Doc | Design rationale and porting blueprint |
| `REFERENCE.md` | Doc | This file |
| `RESEARCH-enrichment.md`, `RESEARCH-independent-client.md`, `RESEARCH-pwa.md`, `RESEARCH-fastpwa.md` | Docs | Research notes |
| `screenshot-*.webp`, `screenshot-editor-*.png` | Images | 9 historical screenshots from before the deck list and the former mode switch were added; they also predate the current editor header. **Not regenerated** |
| `screenshot-app-decks.png`, `screenshot-app-review.png`, `screenshot-app-add.png` | Images | Current app views captured on localhost at 390 × 844 |

All three mockups are standalone: no build step, no external assets, no network access.

### Server files for the PWA

| File | Purpose |
|---|---|
| `ankiweb/adapters/inbound/http_shared/pwa.py` | Existing `/` manifest and worker |
| `ankiweb/adapters/inbound/http_app/pwa.py` | Separate `/app/` manifest, worker and offline page |
| `ankiweb/app.py` | Mounts both routers and exempts public PWA paths from the password gate |
| `ankiweb/adapters/inbound/http_shared/templates/shell.html.jinja` | Existing client's PWA tags and registration |
| `ankiweb/adapters/inbound/http_shared/templates/app/base.html.jinja` | `/app/` PWA tags and registration |
| `ankiweb/shell/static/icons/` | Shared placeholder icons |
| `docs/pwa-deployment.md` | HTTPS, proxy and device installation guidance |

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
| Header | Back button, deck-name chip and Done on the first row; step bar on the second row. No count pill in the header |
| Deck chip `#deck-chip` | Shows emoji and name; guarded link to `decks-mockup.html?deck=<id>` |
| Active card | Note-type pill, without a repeated deck badge |
| Pile `#stack-pile-layer` and cue `#pile-cue` | Cards stand at the bottom of the stage; the cue ("Tap or swipe up to edit") stands on the floor under them. Both hidden at 0 cards. A tap on either, or an upward drag of at least 28 px on either, opens the list; a shorter drag does not |
| Count badge `#stack-badge` | Starburst on the pile, hidden at 0 cards. Tapping it opens or closes the list (`aria-expanded`) |
| Step badges `.step-indicator-row` | Fade out and collapse while the list is open (`body.is-browsing`), fade back in on close or when a card is picked |
| Browse list `#browse-list` | One `.browse-card` button per added card, oldest first, vertically scrollable. Opens after the input card slides away; folds back onto the pile on pick or close |
| Edit mode | Picking a row loads the card into the same wizard at Step 1. Banner `#edit-banner` with `×`; saving replaces the card in place (same id, same position, same count) |
| Leave edit / list | `×` or `Escape` in edit mode keeps the card as saved. `Escape` or **Back to new card** closes the list |
| Navigation | No editor mode switch; use the deck list to choose Learn or Edit / Add |
| Feedback | The count updates without a duplicate success toast; a saved edit shows `Card n updated ✓`; warnings remain |
| Navigation guard | The chip, Back, finish/leave and opening the list guard uncommitted text |

**Guard rule** (`confirmDiscard`): the page shows `confirm("You have unsaved text in your current card. <action>")` and cancels on "Cancel" when the editor holds text that is not already saved. For a new card that is any non-empty front, back, hint or example. For a card loaded for editing it is only a **difference from the saved card**, so an unchanged loaded card never prompts. Navigation and edit/finish actions are blocked while a card is committing.

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

## 4. App routes and persistence

The prototype links in §2 describe static mockups. The implemented mobile client is
separate from the existing client and uses the following routes. *Read.*

| Route | Purpose |
|---|---|
| `GET /app/` | Deck list; Learn links to `/app/review?deck=<id>`, Edit / Add to `/app/add?deck=<id>` |
| `GET /app/review?deck=<id>` | Review for a deck; Back and completion return to `/app/` |
| `POST /app/review/answer`, `/app/review/action/*`, `/app/review/due` | Answer and card actions |
| `GET /app/review/info/<card_id>` | Card information |
| `GET /app/add?deck=<id>` | Quick-add; Back and deck chip return to `/app/` |
| `POST /app/add/preview`, `/app/add/commit`, `/app/add/edit/<nid>` | Preview, persist, and load a session-added note for editing |
| `GET /app/manifest.webmanifest`, `/app/service-worker.js`, `/app/offline` | Public app install assets and static offline fallback |

Quick-add commits each new card to the collection immediately as an `AnkiWeb Vocab`
note. The server supports loading and updating session-added notes, but the current
pile has no browse/edit control. Done does not perform a batch save. It requires at
least one session-added card, guards unsaved text, and opens a summary with links to
the deck list and to the same deck's review. Session-added IDs and the review tally
are kept in server memory, not persisted as a separate browser draft; the collection
notes survive a session or server restart. The pile shows at most the four most recent
session additions for the current deck. *Read.*

The reviewer uses the scheduler's queue without filtering by note type, so other
types are shown with an “Other note type” badge rather than silently occupying the
daily limit. When an answer leaves no immediately available card and at least one
card has been rated, the completion summary is shown. Learning counts can remain
positive; in that case “Study again” is offered. Entering a review with no available
card shows the no-cards state instead. Review answers are persisted by Anki's
scheduler; the summary's tally is session state. *Read.*

## 5. Manifest fields and auth

The existing manifest and the new manifest are distinct installs. Both manifests,
both workers, `/app/offline`, and `/shell/static/` assets are public even when a
password is configured; `/app/` and its study routes remain protected. *Read.*

| Field | Existing `/manifest.webmanifest` | New `/app/manifest.webmanifest` |
|---|---|---|
| `name` / `short_name` | `AnkiWeb` / `Anki` | `AnkiWeb` / `Anki` |
| `id`, `start_url`, `scope` | `/` | `/app/` |
| `display` | `standalone` | `standalone` |
| `theme_color` | `#ffd43b` | `#f4f3ed` |
| `background_color` | `#f4f3ed` | `#f4f3ed` |
| Icons | `/shell/static/icons/icon-192.png`, `icon-512.png`; `any maskable` | Same shared placeholder icons |

The legacy manifest was previously checked with Chromium CDP on localhost. That
historical result is not evidence of installability for the new manifest.

## 6. Service workers

`/service-worker.js` has maximum scope `/` and is the legacy worker.
`/app/service-worker.js` has `Service-Worker-Allowed: /app/` and
`Cache-Control: no-cache`, and is registered for `/app/`. A worker served under `/shell/static/`
could not control `/app/`. *Read.*

| Property | Legacy worker | `/app/` worker |
|---|---|---|
| Cache | `ankiweb-shell-v1` | `ankiweb-app-` plus hash of deployed app CSS and JS |
| Cache-first | Same-origin `GET /shell/static/*` | Same-origin `GET /shell/static/app-client.css` and `/shell/static/app/*` |
| Navigation | Normal network path | `/app/` navigations use network; a network failure returns the precached public `/app/offline` page |
| Install | `skipWaiting()` | Precache offline page and its CSS, then `skipWaiting()` |
| Activation cleanup | Deletes old `ankiweb-shell-` caches only | Deletes old `ankiweb-app-` caches only |

Neither worker deliberately caches authenticated HTML; neither provides offline
study or editing. Each worker's activation cleanup is restricted to its own cache
namespace, preserving the other worker's caches and unrelated caches. Restricting
legacy cleanup is a targeted deviation from the original unchanged-worker plan;
its other behavior remains unchanged. *Read.*

The earlier localhost cache, activation, offline, and auth checks in this reference
concerned the legacy worker only: the existing client served static assets offline,
but `/` failed offline and redirected to login after the session cookie was removed.
Those historical observations do not verify the new worker.

## 7. Page tags, installation and icons

The existing shell keeps its manifest, yellow theme color, touch icon and root worker
registration. The app layout links the app manifest, supplies light (`#f4f3ed`) and
dark (`#121316`) theme-color media variants, Apple web-app tags and a touch icon,
and registers the `/app/` worker; registration failures are logged. The app themes
follow the OS, independently of the old client's night toggle. *Read.*

The deck list can show an install button when Chromium supplies
`beforeinstallprompt`; iOS Safari has a dismissible Share → Add to Home Screen
hint outside standalone mode. See [deployment guidance](../../docs/pwa-deployment.md).
These flows have not been verified on Android or iOS devices.

The shared 192 px and 512 px PNG icons derive from `icon.svg`. They are placeholders
declared `any maskable`; launcher cropping has **not** been verified on a device.

## 8. Verification status

| Area | Status |
|---|---|
| Prototype layout, links, fallback, theme, contrast | Historical *QA-verified* report (§2.5), predating later prototype changes |
| Legacy PWA routes, auth, worker and localhost offline behavior | Previously *Verified* in headless Chromium; applies to `/`, not the new app |
| New `/app/` automated tests and Chromium installability | `uv run pytest tests/app_client -q -rs`: 550 passed, 2 deprecation warnings, no skips reported; includes Bun worker harness and Playwright/CDP tests. A separate run of `tests/app_client/test_app_pwa.py` and `tests/app_client/test_app_pwa_browser.py` passed 9 tests with no skips. These are not full-suite results |
| Full test suite | `uv run pytest -q -rs`: 1324 passed, 2 deprecation warnings, no skips reported |
| Localhost browser | Fresh temporary collection: `/app/` worker registered and controlled the page; two theme-color metas present. Simulated install prompt showed the button and `appinstalled` hid it. Deck → review → deck → add form reached; after changing page-script order to prevent an `avDeckFocus` Datastar initialization race, the console was clean. One earlier Orca `click` reported success without navigation, while a DOM click worked; a final 390 × 844 Orca `click` on the deck's add link navigated to the correct `/app/add?deck=` form with a clean console, so the earlier intermittent click remains unexplained. Stopping the server showed the offline fallback; after restart, retry opened the deck list |
| Android / iOS installation | *Not verified* on devices |
| HTTPS deployment | *Not verified* in practice |
| Maskable icon cropping | *Not verified* on a launcher |
| Screenshots | `screenshot-app-decks.png`, `screenshot-app-review.png`, `screenshot-app-add.png` captured on localhost at 390 × 844; older prototype images remain historical |
| Unsaved-text guard under a real typed-in prototype state | Reported by the editor agent, not reproduced by the QA agent or the author |
