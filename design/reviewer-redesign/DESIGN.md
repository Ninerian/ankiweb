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
   - Right: More Actions button (`⋮`) opens the card actions sheet, without a mode switch. Use Back to Decks, then the deck's **Edit / Add** action to reach the editor. The day/night icon is intentionally not shown; dark mode follows `prefers-color-scheme` automatically.
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
`/app/review?deck=<id>` studies a deck; `/app/add?deck=<id>` opens quick-add.
The existing client and `/add` remain available. The app uses Jinja, Datastar and
its own app assets; it does not depend on the legacy `/ws` reviewer bridge.

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
   - Real-time character count and high-school helper chips (e.g. German articles `der`, `die`, `das` and umlauts `ä`, `ö`, `ü`, `ß`).
   - Primary CTA: **Next: Back →**. The `Enter` shortcut works without an on-screen keyboard hint.
2. **Step 2: Back (Answer / Definition)**:
   - Focus transitions directly to the definition/answer field.
   - Two optional, collapsed-by-default fields below it: **Hint** (part of speech, plural; the quick chips `Noun`, `Verb`, `Adj`, `(Plural:)` insert here) and **Example sentence** (wrap the key word in `*asterisks*` to highlight it).
   - Leaving both empty keeps the fast two-field path unchanged.
   - Primary CTA: **Preview Card →**.
3. **Step 3: Quick Preview & Commit**:
   - Renders the finished card exactly as the reviewer shows it: Prompt, Answer, plus Hint and Example (with highlighted key word) when present.
   - Primary CTA: **Add to Stack 📥** (vibrant emerald green `#40c057`).
   - Once tapped, the card is **saved immediately as a note** in the target deck (not held in the browser) and the editor resets to Step 1. Saved notes survive reload; uncommitted text is a draft and is not saved by Done.

### C. Card-Stack Physical Metaphor & Animation

> Naming (see `CONTEXT.md`): the visual pile is the **added cards** of this session. "Stack" stays only as the animation metaphor and in the mockup's identifiers; the Anki object is a **deck**.

The core psychological hook of the creator is the **physical growing card pile**:
- **Slide-to-Stack Keyframe Animation (`@keyframes slideToStack`)**:
  - Upon tapping **Add to Stack**, the active card physically slides down and rotates (`transform: translate(x, y) rotate(deg)`), visibly joining the stack beneath the editing stage.
  - A fresh blank card simultaneously drops into place from above (`@keyframes popInFreshCard`).
- **Dealt Physical Stack Layers**:
  - Completed cards stand on the floor at the **bottom of the stage**, below the input card: the newest sits in front, older ones step back and rise behind it (`26px` per layer, slight rotations `-3.2°`, `+2.8°`, `-2.0°`, opaque and slightly darker with depth), so each top edge stays visible. At most five layers are drawn.
- **Cue standing on the floor**:
  - A small label under the pile reads **Tap or swipe up to edit**, with a chevron that nudges upward. It has a hard foot and a soft contact shadow so it reads as standing on the same surface as the cards. It is hidden at 0 cards and while the list is open.
- **Count starburst on the pile**:
  - The count sits in a spinning starburst badge at the lower right edge of the pile (as on `/app/add`), with the unit ("CARD" / "CARDS") set on an arc. It bumps when the count changes (`@keyframes stackPillPop`); no separate add-success toast repeats it.

### D. Added cards and editing

The prototype explores a browse-and-edit list of all cards added in the session.
The implemented `/app/add` currently renders the four most recent session-added
cards in the pile, with a count of all session-added cards still in that deck.
The server has routes to load and update a session-added note, but the current
pile has no browse/edit control. Session IDs are kept in server memory, so the
pile is session-scoped; the notes themselves are persisted in the collection.

### E. Implemented route and scope

The dedicated mobile route is `/app/add?deck=<id>`; preview and persistence use
`/app/add/preview`, `/app/add/commit` and `/app/add/edit/<nid>`. Quick-add
creates `AnkiWeb Vocab` notes (§5.F); the existing full-featured `/add` remains
separate. Done requires at least one session-added card, confirms before
discarding unsaved text, and opens a summary. It is not a batch-save action.
From the summary, **Start studying** opens `/app/review?deck=<id>` and the
deck-list action returns to `/app/`.

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

The reviewer adds a localized front label outside the Anki template for `AnkiWeb Vocab` cards. The card content is centered for this note type; other note types keep their own presentation.

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
**Edit / Add** links to `/app/add?deck=<id>`. Review Back, Add Back and the
Add deck chip return to `/app/`; Done opens the summary described in §5.E.
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
