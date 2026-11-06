# AnkiWeb Reviewer Mobile-First Playful Redesign
**Target Audience**: High-school students & active learners  
**Format**: Standalone prototype and implemented mobile client design
**Directory**: `design/reviewer-redesign/`  
**Technical reference**: [REFERENCE.md](REFERENCE.md) (files, routes, link matrix, PWA manifest and service worker, verification status)  

---

## 1. Aesthetic Direction: "Playful Neo-Pop / Neo-Brutalist Arcade"

### Why this aesthetic?
High-school pupils find traditional flashcard apps sterile, punishing, and clinical. When an interface looks like an administrative spreadsheet or generic Bootstrap form, study sessions feel like homework drudgery. 

We adopted a **Playful Neo-Pop** direction characterized by:
- **Tactile Chunky Affordances**: Hard drop shadows (`3px 3px 0px #18191f`), crisp 2.5px borders, and physical "button press" active states (`transform: translate(2px, 2px)` with shadow zeroing) that feel responsive, physical, and delightful to tap with thumbs on mobile screens.
- **Bold, Non-Generic Color System**:
  - Warm cream canvas background (`#f4f3ed`) that reduces eye strain while feeling like premium stationery.
  - Saturated ease tiles: **Again** (coral red `#ffe3e3` / border `#fa5252`), **Hard** (warm amber `#fff3bf` / border `#fab005`), **Good** (mint emerald `#d3f9d8` / border `#40c057`), **Easy** (sky blue `#d0ebff` / border `#228be6`).
  - Dark mode inverted to an arcade cyber aesthetic (`#121316` deep charcoal background, dark surface panels, neon borders, and glowing amber meter fill).
- **Zero-Network System Typography**:
  - Instead of downloading webfont binaries (which add network overhead and latency), we forged a punchy typographic identity strictly through CSS styling on system font stacks:
  - `-apple-system, BlinkMacSystemFont, "Trebuchet MS", "Impact", "Segoe UI", system-ui, sans-serif` paired with high font weights (`font-weight: 900`), tight letter-spacing (`-0.03em`), and monospaced interval numbers.
  - High-impact contrast between uppercase microscopic badge metadata (`0.75rem`, letter-spaced) and oversized flashcard display text (`2rem`).

---

## 2. Gamification Mechanics (Client-Only Session Gamification)

The prototype delivers instant dopamine and flow state without requiring backend schema changes or database migrations:

### A. The Streak Counter (`🔥 N STREAK`)
- **Concept**: Counts consecutive cards successfully recalled in the active session (i.e. rated **Hard**, **Good**, or **Easy**).
- **Visual Feedback**:
  - **Success / Increment**: Triggers `@keyframes streakPop` (a bouncy `1.35x` scale pop with subtle rotation and orange halo) giving a rewarding physical chime-like sensation.
  - **Failure ('Again')**: When a student fails a card and presses **Again**, the streak resets with a gentle sideways wobble `@keyframes streakReset` (`💔 0 STREAK`). **Product decision (user, 2026-10-28):** the implementation shows no streak-change toast. The prototype's micro-copy (*"Streak Reset! Don’t give up 💪"*, *"Streak +1!"*) is not ported; the pill animation and the counter carry the feedback.
- **Scope (implementation decision, differs from the prototype)**: The prototype keeps the streak in memory (`let streakCount = 7`). The implementation **derives it from the review log**: the run of most recent reviews with ease 2, 3 or 4 since the collection's day start, across all decks; ease 1 ends the run. It is read-only (no backend stats are written) and survives reload.

### B. Session Progress Meter
- **Concept**: Visualizes study pacing (`14 / 20 CARDS` or dynamic deck due count) inside a candy-bar striped meter.
- **Micro-Interaction**: Dynamic fill bar (`transition: width 0.35s cubic-bezier(0.34, 1.56, 0.64, 1)`) with angled diagonal stripes that smoothly stretches as cards are rated.

---

## 3. Interaction Architecture

1. **Top HUD**:
   - Left: Back to Decks button (chunky rounded square icon) → `decks-mockup.html`.
   - Center: Animated Streak pill badge.
   - Right: More Actions button (`⋮`) opens the card actions sheet, without a mode switch. Use Back to Decks, then the deck's **Edit** action to reach the mobile editor. The day/night icon is intentionally not shown; dark mode follows `prefers-color-scheme` automatically.
   - Bottom: Session progress meter bar.
2. **Card Stage**:
   - Contained inside an elevated white card with rounded corners (`border-radius: 24px`) and hard shadows.
   - Distinct tags for deck origin (`🇩🇪 German B1 Vocab`) and dynamic star/flag indicator badges.
   - Question presented prominently with phonetic/grammatical hints.
   - Reveal transition unfolds smoothly (`@keyframes revealAnswer`) into definition and contextual sample sentence with highlighted keyword `<mark>`.
3. **Bottom Controls**:
   - **Front State**: Giant, full-width thumb-friendly **Show Answer** button, without a keyboard indicator.
   - **Back State**: 4 large ease rating tiles (**Again**, **Hard**, **Good**, **Easy**), each displaying its ease label and scheduled interval (`< 10m`, `2 d`, `5 d`, `9 d`), without shortcut key badges.
4. **Mobile Bottom Sheet (Card Actions)**:
   - Replaces the desktop-style dropdown menu with a slide-up bottom drawer.
   - Provides clean 2-column quick-action tiles: **Mark Card**, **Flag (Red)**, **Bury Card**, **Suspend**, **Undo Review**, **Set Due Date**, **Card Info**, and **Delete Note**.
   - In the real reviewer, tiles use inline SVG icons and theme-aware base, border, shadow, and danger colors; translated labels and mark/flag state remain unchanged.
   - Tap outside or tap **Dismiss** to close.

---

## 4. Implementation in AnkiWeb

The mobile design is implemented as a separate HTTP client under `/app/`, not by
replacing the existing reviewer's Jinja templates. `/app/` lists decks;
`/app/review?deck=<id>` studies a deck; `/app/edit?deck=<id>` opens the mobile editor.
The existing client and `/add` remain available. The app uses Jinja, Datastar and
its own app assets; it does not depend on the legacy `/ws` reviewer bridge.

When password protection is enabled, the app uses `/app/login`; the existing client
uses `/login`. Both share the same authentication cookie. App login always opens
`/app/`, not the previously requested URL. If authentication expires during a
Datastar request, full navigation to login can discard unsaved drafts; a rejected
POST is neither executed nor retried after login.

The app reviewer uses the Anki scheduler directly and saves each answer as it is
rated. The queue is **not filtered by note type**: foreign note types remain
reachable and are labelled, rather than consuming daily queue slots invisibly.
Completion is shown after a rating when no card is immediately available and at
least one card was rated. Learning counts may still be positive, in which case
**Study again** is offered; an initially empty queue shows the no-cards state.
The completion tally is server-side session state, not permanent review history.
See [REFERENCE.md](REFERENCE.md) for routes and verification status.

---

## 5. Card Creation Flow ("Quick Add Stack")

### A. Overview & High-School Persona
Adding flashcards is traditionally the highest friction point in spaced repetition systems. Desktop Anki's standard Add Note modal confronts users with complex options: note-type select dropdowns, cloze syntax brackets, image occlusion editors, deck selectors, and multi-field grids. For high-school students, this cognitive load causes abandonment before they create their first deck.

The **Card Creation Flow** (`editor-mockup.html`) provides a streamlined, tactile mobile wizard engineered for rapid-fire creation of **Basic (Front / Back)** cards. Two fields are required (Front, Back); two are optional (**Hint**, **Example sentence**) so the card shown in the reviewer can carry the same extra info it displays. It mimics building a physical stack of flashcards on a desk, giving students tangible visual momentum as they study and summarize their notes.

**Prototype card model** (`card-render.js`): `{ front, hint?, back, example? }`.
The prototype stores plain text and escapes at render time. In the implemented
client, Anki fields are HTML: quick-add escapes input when saving, and the client
highlights `*word*` in the rendered example. See the note-type contract below.

### B. 3-Step Guided Wizard Mechanics
The editor presents a focused single-purpose card interface divided into three distinct steps:
1. **Step 1: Front (Prompt / Question)**:
   - Oversized, high-contrast `<textarea>` styled with chunky 2.5px borders and tactile focus depression.
   - Real-time character count and front-field helper chips based on the deck's target language (articles and special characters). Without a valid language pair, the original German chips `der`, `die`, `das`, `ä`, `ö`, `ü`, `ß` remain. Subdecks do not inherit a pair; Korean has no chips, and the catalog returns none for unknown codes. These are not full keyboards for other scripts.
   - With a valid pair, the front label shows the target language's flag and localized name; the textarea uses its language code.
   - Primary CTA: **Next: Back →**. The `Enter` shortcut works without an on-screen keyboard hint.
2. **Step 2: Back (Answer / Definition)**:
   - Focus transitions directly to the definition/answer field.
   - With a valid pair, the back label shows the source language's flag and localized name; the textarea uses its language code. This field mapping is a UI convention, not a check or reordering of stored content.
   - Two optional, collapsed-by-default fields below it: **Hint** (part of speech, plural; the quick chips `Noun`, `Verb`, `Adj`, `(Plural:)` insert here) and **Example sentence** (wrap the key word in `*asterisks*` to highlight it).
   - Leaving both empty keeps the fast two-field path unchanged.
   - Primary CTA: **Preview Card →**.
3. **Step 3: Quick Preview & Commit**:
   - Renders the finished card exactly as the reviewer shows it: Prompt, Answer, plus Hint and Example (with highlighted key word) when present.
   - Primary CTA: **Add to Stack 📥** (vibrant emerald green `#40c057`).
   - Once tapped, the card is **saved immediately as a note** in the target deck (not held in the browser) and the editor resets to Step 1. Saved notes survive reload; uncommitted text is a draft and is not saved by Done.

### C. Deck Pile & Animation

> Naming (see `CONTEXT.md`): the visual pile represents supported notes in the selected **deck**, including earlier sessions. The separate session additions counter remains the source for Done and the summary.

The mobile editor shows a compact pile 12px below the editor: up to five opaque, 104px-high layers step upward by 16px, with rotation, perspective and shadow; the newest note is in front. The upper-right badge counts all supported deck notes, not just the visible layers, without overlapping the editor. Only a new note grows and animates the pile; editing updates the same note without changing its size or order.

### D. Added cards and editing
Tap the pile or badge, or swipe upward, to open the deck-card list. On a tap, the editor slides away and the pile rises before the list cards fan upward from its captured screen position. During a swipe, the actual rows unfold continuously with the finger as the editor and pile fade; the preview remains inert until release. A short swipe reverses to the editor; a committed swipe completes without restarting. Neither path jumps. The three step badges and footer fade out during opening, remain hidden while the list is open or closing, and fade back in on return. The steps and footer keep their layout space during opening and return and are inert while browsing. Done remains visible and available in the open list, subject to the same saving and transition guards as in the editor. Closing or selecting a row folds the list back and restores the editor. Staggering is capped for large decks, and reduced-motion preferences are respected. An empty deck shows the empty state instead of an actionable pile.

### D. Browse and Edit Deck Cards

- **Scope**: `#deck-cards` lists all `AnkiWeb Vocab` notes with at least one card in the selected deck, including notes from earlier sessions, oldest first. Other note types, deleted notes and notes without a card in that deck are excluded. The pile shows at most the five newest notes, but the list has no such limit.
- **Open and choose**: activating the pile or badge, or swiping upward, opens the list and focuses its labelled `#deck-cards` region once open. There is no visible list header or separate **Back to new card** control; the list title remains available to screen readers. Each row is a labelled button carrying its note ID. Selecting it folds the list and loads that note in the same three-step wizard at Step 1 and focuses the first field. There is no editing label, separate edit/cancel banner or note-type badge. If loading fails, the list stays open.
- **Save and Back**: a successful existing-note save, including an unchanged save or a successful retry of a pending reset, updates the same note ID without a duplicate and automatically reopens the deck-wide list with the updated row. It uses the same fan animation and list focus as opening from the pile; the pile is the logical opener for focus return. Creating a note stays in the wizard at Step 1. Validation, network and reset failures stay in the editor with their existing errors; a reset failure can follow a persisted note update. Back or Escape in an existing-note wizard returns to the list through the guarded opening flow, discarding only the unsaved draft, not an already persisted change. Back or Escape from the list returns to the new-card editor and focuses the pile. Back can interrupt opening, but is disabled during closing and return. Back from the new-card wizard navigates to the deck overview (`/app/`) with the unsaved-draft guard.
- **Draft safety**: opening the list or navigating away asks before discarding unsaved text. An unchanged loaded note is not an unsaved draft and never triggers that prompt. Saving and animation handling remain in effect for Back.
- **Learned cards**: a note is learned when at least one of its cards in the selected deck has Anki `type != 0`. Its row shows a theme warning color and the text **Learned** / **Gelernt**; there is no separate list legend. Editing a learned note shows a warning that changes reset progress, associated with the Front field in addition to its existing help text.
- **Progress reset**: an actual field change to a learned note reschedules that note's cards in the selected deck as new with `reset_counts=True`, clearing `reps` and `lapses`, and shows a localized `role="status"` notice in the reopened list. Without a pending reset, unchanged saves and edits to unlearned notes do not reset progress; cards in other decks are not rescheduled. Cancellation itself neither triggers a reset nor clears a pending marker. Existing review history is not deleted; rescheduling is logged. A durably pending failed reset can be retried on an unchanged save; see [Plan 9](../../docs/superpowers/plans/2026-10-30-reviewer-redesign-09-edit-deck-cards.md) for its failure caveats.
- **Accessibility**: the pile button has `aria-expanded`, `aria-controls="deck-cards"`, a visible focus ring and a localized spoken count and action. Enter and Space open the list; its screen-reader-only title labels the focusable list region. Back or Escape from the list returns focus to the pile; selecting a row focuses the first field. The top-left Back control is labelled **Back to card editor** / **Zurück zum Karteneditor** in the list, **Back to cards** / **Zurück zu den Karten** in the existing-note wizard, and uses `app_add_exit` in the new-card wizard. It is a native link to `/app/` only for a clean, idle new-card exit; with a draft, while editing, browsing, saving or transitioning it has button semantics without an href, supports Enter and Space, and applies the same phase and discard guards. It is temporarily disabled during closing and return. Rows are labelled buttons, and motion respects `prefers-reduced-motion`. Labels, warnings and feedback are available in German and English.

### E. Mobile Editor Routes & Scope

The deck list's **Edit** / **Bearbeiten** action and its empty state lead to `/app/edit?deck=<id>`. The mobile editor uses:

| Route | Purpose |
|---|---|
| `GET /app/edit?deck=<id>` | Open the new-card wizard |
| `GET /app/edit?deck=<id>&view=cards` | Open the deck-card list directly |
| `GET /app/edit?deck=<id>&card=<nid>` | Open a supported note directly for editing |
| `POST /app/edit/preview` | Preview `front`, `back`, `hint` and `example` without saving |
| `POST /app/edit/card/{nid}?deck=<id>` | Load an editable note in the selected deck at Step 1 |
| `POST /app/edit/commit?deck=<id>` | Create for `nid: 0`; otherwise update the selected deck's existing note |

Missing, deck-foreign and unsupported notes cannot be loaded or updated. App navigation, templates and client calls use these routes and `shell_src/app/edit.js`, without legacy app-route aliases. The separate full-featured desktop `/add` editor remains unchanged.

The URL tracks the deck and editor view. Browser Back and Forward restore views with a discard guard; the in-app Back control moves from card to list, list to editor, then editor to deck overview. For a direct card or list link, in-app Back replaces that entry with its parent view. After saving a card opened from the list, the existing list history entry is restored: the first browser Back reaches the prior editor, or the earlier page if the list was a direct link. Forward returns to the saved list and can then reopen the saved card. A direct-card save replaces its entry with the list; browser Back reaches the earlier page, while in-app Back opens the editor. Invalid or unavailable card links normalize to the editor URL.

#### Unimplemented alternative: light-DOM pile element

A native custom element could wrap the existing pile button, preserving its native keyboard and accessibility behavior while encapsulating pointer lifecycle and local gesture state. Datastar could pass page state into observed attributes with `data-attr:*`; the element could emit bubbling custom events for gesture progress and open requests, which the page handles. The page would still own draft guards, list/editor choreography, focus, server updates and URL/history state.

This is not implemented. Morphs may replace or reconnect the element, requiring listener and state cleanup and careful handling of pointer capture; animation still spans the pile, list and editor. Encapsulation does not remove browser history or deep-link state. [Rocket](https://data-star.dev/reference/rocket) is an optional beta web-component API in a separate `datastar-rocket.js` bundle loaded instead of `datastar.js`, not an installed dependency. Datastar's [web-component example](https://data-star.dev/examples/web_component) illustrates signal-to-attribute and event communication without Rocket.

Done is available in both the editor and the open deck-card list. It confirms before discarding unsaved text and is guarded while saving or transitioning. It opens a summary using the session count, including when no cards were added. The summary offers **Start studying** for `/app/review?deck=<id>` and **Back to decks** for `/app/`, with no separate close button. Focus stays within the dialog; Escape or the backdrop dismisses it and returns focus to Done. Browser Back dismisses it and also restores the previous editor history view.

### F. Dedicated Note Type Contract (`AnkiWeb Vocab`)
Quick-add creates the dedicated `AnkiWeb Vocab` note type. Its templates carry **no CSS and no JavaScript**: presentation lives in the app stylesheet, and card HTML is rendered by Anki. The implementation creates and validates the model directly in the collection.

**Fields (in this order; the first field is the sort field).** In an Anki note type **all four fields always exist**; none is optional as a type property. A field can only hold an empty value. What the quick-add view requires is a rule of the view, not of the note type:

| # | Field | Quick-add requires a value | Content | Mockup name |
|---|---|---|---|---|
| 1 | `Front` | yes (view rule) | Prompt / question, plain text | `front` |
| 2 | `Back` | yes (view rule) | Answer / definition, plain text | `back` |
| 3 | `Hint` | no, empty value allowed | Part of speech, plural, short note | `hint` |
| 4 | `Example` | no, empty value allowed | Example sentence; key word wrapped in `*asterisks*` | `example` |

What the server enforces on `addNote` (belegt, `actions/_helpers.py:43`): it rejects a note whose fields check reports it as **empty** and, unless `options.allowDuplicate` is set, a **duplicate**. It does not know the view rules above, so the view must check Front and Back itself.

**One card template, `Card 1` (Front → Back).** The **templates** contain no `<style>`, no `<script>`, no inline handlers, and the note type's `css` is the empty string. Note that Anki's render still prepends an empty `<style></style>` wrapper to the output (see the verification list below); that tag is harmless but present. Stable class names are the only styling hook:

```html
<!-- Front template (qfmt) -->
<div class="av-card av-front">
  <div class="av-front-text">{{Front}}</div>
  {{#Hint}}<div class="av-hint">{{Hint}}</div>{{/Hint}}
</div>

<!-- Back template (afmt) -->
<div class="av-card av-back">
  <div class="av-front-text">{{Front}}</div>
  {{#Hint}}<div class="av-hint">{{Hint}}</div>{{/Hint}}
  <hr id="answer">
  <div class="av-back-text">{{Back}}</div>
  {{#Example}}<div class="av-example">{{Example}}</div>{{/Example}}
</div>
```

`{{#Field}}...{{/Field}}` is Anki's built-in conditional, so empty Hint/Example render no element and the fast two-field path is unchanged. The back template repeats the front markup instead of using `{{FrontSide}}`, so the design can address each part by class.

The reviewer adds a localized front label outside the Anki template for `AnkiWeb Vocab` cards. The card content is centered for this note type; other note types keep their own presentation. The question and hint remain visible on reveal. For the dedicated vocabulary template, the client removes the repeated front-text element from the answer face after matching it against the question; the answer's hint and example are retained. The stored note template remains unchanged, so existing collections need no migration. A back-only answer is left intact. Foreign note-type answers, including type-in cards, are left unchanged because their HTML has no reliable shared front/back structure; the mobile reviewer does not implement type-in answer input or grading.

**Escaping and highlight (change from the prototype):** Anki fields are HTML. The prototype stored plain text and escaped at render time (`CardRender.renderCard`). With server-rendered HTML the contract is: the **writer escapes on save** (the quick-add view must HTML-escape `<`, `>`, `&` before `addNote`, otherwise typed `<` is interpreted as markup), and the `*word*` → `<mark>` conversion for `.av-example` happens in the **client** after render, because Anki has no template filter for it. The converted text is already escaped, so only `<mark>` is added.

**Verified against a throwaway server (not the user's profile; separate `ANKIWEB_COLLECTION`, removed afterwards):**
- `createModel` accepts the type as specified: four fields in order, `css` stays `""`, both templates are stored unchanged (`modelFieldNames`, `modelStyling`, `modelTemplates`).
- Rendering (`cardsInfo`): with empty Hint/Example **no element is emitted** (only whitespace remains); with values the `av-hint` / `av-example` elements appear. `*word*` arrives unchanged, so the `<mark>` conversion stays in the client.
- **Escaping was required:** `a < b` and `x & y` were stored as typed and came back raw in `av-front-text` / `av-back-text`. This historical test demonstrated that the server does not escape; it did not test the subsequently implemented quick-add view.
- **An empty `<style></style>` is still prepended** to both `question` and `answer` even though `css` is empty. The templates and the type carry no styling, but the render output is not free of the tag. It is empty and harmless; the client can ignore or strip it. A rule that the card HTML contains no `<style>` element would be wrong for the raw server output.
- `addNote` rejects an all-empty note ("cannot create note because it is empty") and a duplicate ("... it is a duplicate").
- Deleting the type works only after its notes are gone (`/extra_actions/deleteModel`: "3 note(s) still use it" before, `true` after).

**Scope of the type:** Basic (front/back) with two further fields that may be left empty (hint, example). Not covered: cloze, reversed cards, type-in-answer, audio, images, math. Each would be a separate dedicated type with its own contract.

**Existing cards of other note types** are shown **as they are** (server-rendered HTML without the design classes) with an "Other note type" badge. They are **not** skipped: measured, the daily new-card limit (20) fills the queue with the other type and a dedicated-type card becomes unreachable while the counter still shows 20 (`get_queued_cards` and `deck_due_tree` have no note-type filter). Layout of foreign HTML (images, cloze, math) is not guaranteed.

---

## 6. Deck List & Navigation

The static `decks-mockup.html` demonstrates the deck-list visuals, search, empty
state and New deck sheet. Its fixed ids and `mockup.html` / `editor-mockup.html`
links are prototype data, not production routes.

In the implemented client, **Learn** links to `/app/review?deck=<id>` and
**Edit / Add** links to `/app/edit?deck=<id>`. Review Back, Edit Back and the
Edit deck chip return to `/app/`; Done opens the summary as described in §5.E.
There is no mode switch. The app has no theme toggle: it follows
`prefers-color-scheme`, independently of the old client's night toggle.

---

## 7. Session Completion (`mockup.html`)

After the twentieth rating, `#session-complete` replaces the card and review controls while the progress HUD remains. The panel shows reviewed count, current streak, rating distribution, and **Recall**: `(Hard + Good + Easy) / all ratings`, not measured accuracy. Emoji and copy follow these ordered tiers, using unrounded ratios:

| Tier | Condition |
|---|---|
| Perfect | No Again ratings and Easy ≥ 40% |
| Great | Otherwise, Recall ≥ 85% |
| Good | Otherwise, Recall ≥ 60% |
| Tough | Otherwise |

The initial `14/20` is mockup-only demo history: 2 Again, 3 Hard, 7 Good, 2 Easy. **Study again** resets the mockup to `0/20` with an empty tally; **Back to decks** opens the deck list. Use `?complete=perfect` (or `great`, `good`, `tough` as the value) to preview each design. These demo histories are not production session data.

In `/app/` this fixed 20-card demo is replaced by the scheduler-driven completion
behavior in §4. The summary appears only after a rating exhausts the currently
available queue; learning cards may remain scheduled. The tally is per session.

The completion title receives focus, decorative graphics are hidden from assistive technology, and rating counts remain available as text. The screen follows the system theme and honors `prefers-reduced-motion` for its animations and transitions.
