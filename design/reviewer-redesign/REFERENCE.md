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
| `login-mockup.html` | Static HTML | App login with idle, error, success and dark states |
| `card-render.js` | Script | Shared card model and renderer used by the reviewer and the editor preview |
| `study-api-spike.py` | Archived Python | Study JSON API spike. **Not imported anywhere.** Per RESEARCH-independent-client.md the router was removed from the server code after its test |
| `DESIGN.md` | Doc | Design rationale and porting blueprint |
| `REFERENCE.md` | Doc | This file |
| `RESEARCH-enrichment.md`, `RESEARCH-independent-client.md`, `RESEARCH-pwa.md`, `RESEARCH-fastpwa.md` | Docs | Research notes |
| `screenshot-*.webp`, `screenshot-editor-*.png` | Images | 9 historical screenshots from before the deck list and the former mode switch were added; they also predate the current editor header. **Not regenerated** |
| `screenshot-app-decks.png`, `screenshot-app-review.png`, `screenshot-app-add.png` | Images | Current app views captured on localhost at 390 × 844 |
| `screenshot-login-1-idle.png`, `screenshot-login-2-error.png`, `screenshot-login-3-dark.png`, `screenshot-login-4-success.png` | Images | Login mockup states |

All four mockups are standalone: no build step, no external assets, no network access.

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

This section describes the standalone historical mockup, not the mobile `/app/edit` data model. The mobile editor retains its open/close motion but uses a compact pile below the editor and lists supported notes from the whole selected deck rather than only session additions; see §2.5.

| Element | Behaviour |
|---|---|
| Header | Back button, deck-name chip and Done on the first row; step bar on the second row. No count pill in the header. Done stays visible and usable in the open list; it is disabled during list transitions |
| Deck chip `#deck-chip` | Shows emoji and name; guarded link to `decks-mockup.html?deck=<id>` |
| Active card | Note-type pill, without a repeated deck badge |
| Pile `#stack-pile-layer` and cue `#pile-cue` | Cards stand at the bottom of the stage; the cue ("Tap or swipe up to edit") stands on the floor under them. Both hidden at 0 cards. A tap on either, or an upward drag of more than 28 px on either, opens the list |
| Count badge `#stack-badge` | Starburst on the pile, hidden at 0 cards. Tapping it opens or closes the list (`aria-expanded`) |
| Step badges `.step-indicator-row` | Fade out, collapse and become inert while the list is open (`body.is-browsing`), fade back in on close or when a card is picked |
| Browse list `#browse-list` | One `.browse-card` button per added card, oldest first, vertically scrollable. Opens after the input card slides away; folds back onto the pile on pick or close |
| Edit mode | Picking a row loads the card into the same wizard at Step 1. Banner `#edit-banner` with `×`; saving replaces the card in place (same id, same position, same count) |
| Leave edit / list | `×` or `Escape` in edit mode keeps the card as saved. `Escape` or **Back to new card** closes the list |
| Navigation | No editor mode switch; use the deck list to choose Learn or Edit / Add |
| Feedback | The count updates without a duplicate success toast; a saved edit shows `Card n updated ✓`; warnings remain |
| Navigation guard | The chip, Back, finish/leave and opening the list guard uncommitted text |
| Done and summary | After the discard guard, Done opens the session summary even when no cards were added. The summary offers Study Deck and Back to decks, with no separate close button. Focus is trapped; Escape or clicking the backdrop dismisses the summary and returns focus to Done. Browser Back dismisses it while navigating browser history |

**Guard rule** (`confirmDiscard`): the page shows `confirm("You have unsaved text in your current card. <action>")` and cancels on "Cancel" when the editor holds text that is not already saved. For a new card that is any non-empty front, back, hint or example. For a card loaded for editing it is only a **difference from the saved card**, so an unchanged loaded card never prompts. Navigation and edit/finish actions are blocked while a card is committing.

### 2.5 Mobile deck editor (`/app/edit`)

The mobile editor combines creation with editing `AnkiWeb Vocab` notes that have at least one card in the selected deck, including notes from earlier sessions. Deleted notes, other note types and notes without a card in that deck are excluded. The deck list's **Edit** / **Bearbeiten** action and its empty state lead to `GET /app/edit?deck=<id>`; the separate desktop `/add` remains unchanged.

| Element | Behaviour |
|---|---|
| Field languages and helpers | A valid pair on the selected deck maps target to Front and source to Back; each label adds its flag and localized name, and each textarea gets its language code as `lang`. This is a UI convention: stored content is not language-checked or reordered. Front, Back and Example use language-neutral placeholders. The front helper row contains target-language articles and special characters; ordinary articles insert a trailing space, while elided forms, prefixes and characters insert exactly themselves. The Hint chips remain unchanged. Without a valid pair, the original labels, placeholders and German front chips (`der`, `die`, `das`, `ä`, `ö`, `ü`, `ß`) remain. Subdecks do not inherit pairs; Korean has no front chips, and the catalog returns none for unknown codes. Helpers are not full keyboards for other scripts |
| Deck pile `#added-cards` | Up to five newest supported notes, 104px high and stepping upward by 16px, with rotation, perspective and shadow. The compact pile follows the editor with a 12px gap; the upper-right badge counts all supported deck notes without overlapping the editor. The newest note is in front. Editing preserves pile size and order; only creating a note grows and animates it |
| Opener `#pile` | Tap the pile or badge, or swipe upward, to open `#deck-cards`. During a swipe, the editor and pile fade as the actual list rows unfold with the finger; the preview remains inert until release. Releasing below the threshold reverses the transition and returns to the editor. A cue below the pile identifies the action. An empty deck shows the empty state rather than an actionable pile |
| Session counter and Done | Counts only additions in the current session and deck, separately from the deck-wide badge. Done remains visible and usable in the editor and the open list. After the unsaved-draft guard, it opens the session-count summary even if no cards were added. Saving and transition guards still apply |
| Deck-card list `#deck-cards` | All supported deck notes, oldest first, in a scrollable list. On a tap, the editor slides away while the pile rises, then cards fan upward from its captured screen position with capped staggering. On a swipe, the rows unfold continuously with the gesture and complete without restarting. Neither path causes a layout jump. The three step badges and footer fade out during opening, remain hidden while the list is open or closing, and fade back in on return; steps and footer retain their layout space during opening and return and are inert while browsing. Done remains visible and available in the open list. There is no visible list header or separate Back to new card control; the screen-reader-only `#deck-cards-title` labels the focusable list region. Each row is a labelled button with its note ID; selecting it folds the list and loads the same note in the wizard at Step 1, focusing the first field. A failed load keeps the list open |
| List and draft controls | Opening the list asks before discarding unsaved text; an unchanged loaded note does not prompt. Escape or the top-left Back control folds the list and returns to the editor, focusing the pile. Back can interrupt opening, but is disabled during closing and return. In an existing-note wizard, Back or Escape discards the unsaved draft and returns to the list; in a new-card wizard, Back navigates to the deck overview (`/app/`) with the unsaved-draft guard. Saving and animation handling remain in effect. Leaving an edit does not undo a change already persisted before a reset failure |
| Accessibility | The pile button has `aria-expanded`, `aria-controls="deck-cards"`, a visible focus ring and localized spoken deck count and action; Enter and Space activate it. Once open, the labelled `#deck-cards` region receives focus; Back or Escape from the list returns focus to the pile, while selection focuses the first field. The top-left Back control is labelled **Back to card editor** / **Zurück zum Karteneditor** in the list, **Back to cards** / **Zurück zu den Karten** in the existing-note wizard, and uses `app_add_exit` in the new-card wizard. Only a clean, idle new-card exit is a native link to `/app/`; with a draft, while editing, browsing, saving or transitioning it has button semantics without an href, supports Enter and Space, and retains phase and discard guards. It is temporarily disabled during closing and return. Rows are labelled buttons, and motion respects `prefers-reduced-motion` |
| Summary | Offers Back to decks (`/app/`) and Start studying (`/app/review?deck=<id>`), with no separate close button. Focus is trapped in the dialog; Escape or the backdrop dismisses it and returns focus to Done. Browser Back dismisses it and also processes the previous editor history view |
| Editing indication | No editing label or note-type badge is shown in either editor mode. Back cancels editing and returns to the list |
| Learned status | A note is learned when any of its cards in the selected deck has `type != 0`. Its row has both a theme warning color and **Learned** / **Gelernt** text; there is no separate list legend. Editing a learned note shows the `role="note"` warning `#edit-warning`. The Front textarea retains `input-front-help` in `aria-describedby` and adds `edit-warning` only while editing a learned note |
| Save and progress | A successful existing-note save updates the same note ID without a duplicate and reopens the deck-wide list with the updated row, using the existing fan animation and list focus; the pile is the logical opener for focus return. This includes unchanged saves and successful retries of pending resets. New-card creation stays in the wizard at Step 1; validation, network and reset failures stay in the editor with their existing errors. A reset failure can occur after the note fields were persisted. Changed fields on a learned note trigger rescheduling of that note's cards in the selected deck as new with `reset_counts=True`, clearing `reps` and `lapses`; a localized `role="status"` notice remains visible in the reopened list. Without a pending reset, unchanged saves and edits to unlearned notes do not reset progress. Cancellation itself neither triggers a reset nor clears a pending marker. Cards in other decks are not rescheduled. Revlog history remains and the rescheduling is logged. A durably pending failed reset can be retried on an unchanged save; see [Plan 9](../../docs/superpowers/plans/2026-10-30-reviewer-redesign-09-edit-deck-cards.md) for failure caveats |

The final success signal sets `_editSaved: true` only for successful existing-note edits (including unchanged edits). The template starts it as false; after the SSE element and signal patches, the client consumes and clears it once when `$saving` becomes false, then starts the existing list-opening transition. Creation and failures do not set it; Datastar `finished` alone is not a success signal.

| Method and route | Purpose |
|---|---|
| `GET /app/edit?deck=<id>` | Open the new-card wizard |
| `GET /app/edit?deck=<id>&view=cards` | Open the deck-card list directly |
| `GET /app/edit?deck=<id>&card=<nid>` | Open a supported note directly for editing |
| `POST /app/edit/preview` | Preview fields without saving |
| `POST /app/edit/card/{nid}?deck=<id>` | Load a supported note belonging to the selected deck at Step 1 |
| `POST /app/edit/commit?deck=<id>` | Create with `nid: 0`, otherwise update the selected deck's existing note |

Missing, deck-foreign and unsupported notes cannot be loaded or updated. App navigation, templates and client calls use these routes and `shell_src/app/edit.js`; there are no old app-route aliases. User-facing list, warning and notice strings are available in German and English.

The URL tracks the selected deck and editor view. Browser Back and Forward restore in-page views, asking before discarding unsaved changes. The editor's Back control returns from a card to the list, from the list to the editor, and from the editor to the deck overview; for direct card or list links it replaces the URL with the parent view. Saving a card opened from the list returns to the existing list history entry, so the first browser Back reaches the prior editor or, for a direct list, the earlier page. Forward returns to the saved list and can then reopen the saved card. A direct-card save replaces its entry with the list; browser Back reaches the earlier page, while in-app Back opens the editor. Reload preserves valid editor-history and legacy skip metadata. An invalid, foreign or unsupported card link returns to the editor and normalizes its URL. If a history card load fails with an HTTP error, an error signal or exhausted network retries, the editor shows an unavailable notice and replaces the card URL with the editor URL; later card selections continue to update the URL normally.

### 2.6 Mockup link matrix

The following links describe only the standalone mockups, not the mobile editor routes.

| From | To | Link | Carries `?deck=` |
|---|---|---|---|
| Deck list | Reviewer | Learn | yes |
| Deck list | Editor | Edit / Add | yes |
| Reviewer | Deck list | Back button / completion: Back to decks | **no** |
| Editor | Deck list | Back button | no |
| Editor | Deck list | Chip | yes |
| Editor | Deck list | Done → summary → Back to decks | no |
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
| `GET`, `POST /app/login` | App login; successful authentication opens `/app/`, without returning to the original URL |
| `GET /app/` | Deck list; Learn links to `/app/review?deck=<id>`, Edit to `/app/edit?deck=<id>`. The empty-list action opens the deck-creation dialog |
| `GET /app/review?deck=<id>` | Review for a deck; Back and completion return to `/app/` |
| `POST /app/review/answer`, `/app/review/action/*`, `/app/review/due` | Answer and card actions |
| `GET /app/review/info/<card_id>` | Card information |
| `GET /app/edit?deck=<id>` | Mobile editor; Back and deck chip return to `/app/` (see §2.5) |
| `POST /app/edit/preview`, `/app/edit/commit`, `/app/edit/card/<nid>` | Preview, persist, and load a deck note for editing |
| `GET /app/manifest.webmanifest`, `/app/service-worker.js`, `/app/offline` | Public app install assets and static offline fallback |

The editor commits each new card to the collection immediately as an `AnkiWeb Vocab`
note and can browse and edit every such note in the deck (§2.5). Done does not perform
a batch save. It guards unsaved text and opens the summary with links to the deck list
and to the same deck's review, including when no cards were added in the session.
Session-added IDs and the review tally are kept in server memory, not persisted as a
separate browser draft; the collection notes survive a session or server restart. *Read.*

The reviewer uses the scheduler's queue without filtering by note type, so other
types are shown with an “Other note type” badge rather than silently occupying the
daily limit. When an answer leaves no immediately available card and at least one
card has been rated, the completion summary is shown. Learning counts can remain
positive; in that case “Study again” is offered. Entering a review with no available
card shows the no-cards state instead. Review answers are persisted by Anki's
scheduler; the summary's tally is session state. *Read.*

## 5. Manifest fields and auth

The existing manifest and the new manifest are distinct installs. Both manifests,
both workers, `/app/offline`, `/shell/static/*` and both login pages are public even
when a password is configured; `/app/` and its study routes remain protected. *Read.*

The app and existing client use `/app/login` and `/login` respectively and share the
`ankiweb_auth` cookie. It is HTTP-only, SameSite=Lax and Secure for HTTPS; `app_sid`
is separate session state, not authentication. `/logout` clears the shared cookie
and redirects to `/login`. App login always opens `/app/`, without a return URL.
On an unauthenticated Datastar app request, an SSE redirect causes full navigation
to `/app/login`. A rejected POST does not reach its handler and is not retried after
login; unsaved drafts can be lost. Normal protected app requests receive a 303.

`GET /app/login` displays the form only when a password is configured and the
cookie is absent or invalid; otherwise it redirects to `/app/`. A successful form
POST sets the shared cookie and returns a 303; an incorrect password returns 401
with a visible localized error. Datastar POSTs return an SSE redirect on success
or an error signal on failure. The app router's origin guard also applies to login
POSTs. Legacy `/login` retains its existing contracts and success destination `/`.

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
| Cache | `ankiweb-shell-v1` | `ankiweb-app-` plus hash of deployed app CSS, JS and rendered offline page |
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
| Localhost browser | Fresh temporary collection: `/app/` worker registered and controlled the page; two theme-color metas present. Simulated install prompt showed the button and `appinstalled` hid it. Deck → review → deck → add form reached; after reordering page scripts the `avDeckFocus` error no longer appeared. One earlier Orca `click` reported success without navigation, while a DOM click worked; a final 390 × 844 Orca `click` on the deck's add link navigated to the correct `/app/add?deck=` form with a clean console, so the earlier intermittent click remains unexplained. Stopping the server showed the offline fallback; after restart, retry opened the deck list |
| Android / iOS installation | *Not verified* on devices |
| HTTPS deployment | *Not verified* in practice |
| Maskable icon cropping | *Not verified* on a launcher |
| Screenshots | `screenshot-app-decks.png`, `screenshot-app-review.png`, `screenshot-app-add.png` captured on localhost at 390 × 844; older prototype images remain historical |
| Unsaved-text guard under a real typed-in prototype state | Reported by the editor agent, not reproduced by the QA agent or the author |
