# AnkiWeb Reviewer Mobile-First Playful Redesign
**Target Audience**: High-school students & active learners  
**Format**: Standalone prototype & architectural implementation blueprint  
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

## 4. Implementation Porting Blueprint for AnkiWeb

When transitioning this design into the live production templates in `ankiweb/`, the changes map directly to four Jinja templates:

### 1. `reviewer_page_body.html.jinja`
- **Location**: `ankiweb/adapters/inbound/http_shared/templates/reviewer_page_body.html.jinja`
- **Changes**:
  - Replace the existing standard Bootstrap top header (`<header class="d-flex justify-content-between...">`) with the new `.top-hud` containing the streak container, More Actions button, and progress meter.
  - Inject the client-only JS session state manager:
    ```javascript
    let _sessionStreak = 0;
    let _sessionTotal = 0;
    // Hook into pycmd('ease{N}') calls:
    // If ease == '1': _sessionStreak = 0; trigger streakReset
    // If ease in ['2','3','4']: _sessionStreak++; trigger streakPop
    ```
  - Bind keyboard shortcuts (`Space` for show answer, `1-4` for ease selection).
  - Wrap `#qa` inside the styled `.reviewer-stage` and `.flashcard` containers.

### 2. `reviewer_show_answer_bar.html.jinja`
- **Location**: `ankiweb/adapters/inbound/http_shared/templates/reviewer_show_answer_bar.html.jinja`
- **Changes**:
  - Restyle `<button id="ansbut">` with `.btn-show-answer` Neo-Pop styling (bold yellow background `#ffd13b`, hard black border, tactile drop-shadow), without a `SPACE` badge.
  - Retain the existing `onclick="ankiwebShowAnswer()"` bridge hook.

### 3. `reviewer_ease_buttons_bar.html.jinja`
- **Location**: `ankiweb/adapters/inbound/http_shared/templates/reviewer_ease_buttons_bar.html.jinja`
- **Changes**:
  - Replace the flex row of default Bootstrap outline buttons with the `.ease-grid` 4-column layout.
  - Apply the color classes `.btn-ease-again`, `.btn-ease-hard`, `.btn-ease-good`, `.btn-ease-easy` according to `c.i` index.
  - Do not display shortcut key badges on the tiles.
  - Keep `onclick="pycmd('ease{{ c.i }}')"` intact, while wrapping it with local streak animation triggers.

### 4. `reviewer_actions_bar.html.jinja`
- **Location**: `ankiweb/adapters/inbound/http_shared/templates/reviewer_actions_bar.html.jinja`
- **Changes**:
  - Replace the desktop Bootstrap dropdown (`<div class="dropdown">...<ul class="dropdown-menu">`) with the mobile `.bottom-sheet` component and backdrop overlay.
  - Map each action in `buttons` (`Mark`, `Bury`, `Suspend`, `Delete`, etc.) into `.btn-action-tile` grid buttons with clear SVG icons.

---

## 5. Card Creation Flow ("Quick Add Stack")

### A. Overview & High-School Persona
Adding flashcards is traditionally the highest friction point in spaced repetition systems. Desktop Anki's standard Add Note modal confronts users with complex options: note-type select dropdowns, cloze syntax brackets, image occlusion editors, deck selectors, and multi-field grids. For high-school students, this cognitive load causes abandonment before they create their first deck.

The **Card Creation Flow** (`editor-mockup.html`) provides a streamlined, tactile mobile wizard engineered for rapid-fire creation of **Basic (Front / Back)** cards. Two fields are required (Front, Back); two are optional (**Hint**, **Example sentence**) so the card shown in the reviewer can carry the same extra info it displays. It mimics building a physical stack of flashcards on a desk, giving students tangible visual momentum as they study and summarize their notes.

**Card model** (shared by editor and reviewer via `card-render.js`): `{ front, hint?, back, example? }`. `hint` and `example` are optional; when empty the reviewer hides them. In `example`, the key word is wrapped in `*asterisks*` and rendered as `<mark>`. Text is HTML-escaped before the highlight is applied, so user input never injects markup. Editor preview, stack cards and the reviewer all render through `CardRender.renderCard`, so they cannot drift apart.

**Persistence note**: stored values are plain text (e.g. `example` keeps `*word*` and any typed `<` characters literally). Escaping happens only at render time inside `CardRender`; never interpret a stored field as HTML when saving, exporting or rendering elsewhere.

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
   - Once tapped, the card is **saved immediately as a note** in the target deck (not held in the browser) and the editor resets to Step 1 with clean fields, enabling friction-free continuous entry without leaving the view. Reloading the page loses nothing.

### C. Session Pile & Animation

> Naming (see `CONTEXT.md`): the visual pile is the **added cards** of this session; the Anki object is a **deck**. The separate deck-card list includes cards from earlier sessions.

The mobile editor retains its current pile design, including `.added-0..3`, the starburst badge, empty state and add animation. At most the four most recently added cards of this session and deck are visible; the badge counts all session additions in that deck. Only creating a note grows and animates the pile. Saving an edit leaves its cards and count unchanged.

The pile is wrapped by one button, including the badge, with a small **Tap to edit** label. Activating it opens the deck-card list; there is no swipe gesture. If the session pile is empty but the deck has cards, the empty state provides a button to open the list with the deck-card count. A deck without cards keeps the existing empty state without that button.

The floor-standing five-layer pile, 26px staggering, chevron cue and swipe gesture belong to the historical `editor-mockup.html` design (see [REFERENCE.md §2.4](REFERENCE.md)); they are not the mobile implementation.

### D. Browse and Edit Deck Cards

- **Scope**: `#deck-cards` lists all `AnkiWeb Vocab` notes with at least one card in the selected deck, including notes from earlier sessions. Other note types, deleted notes and notes without a card in that deck are excluded. The list is separate from the session pile and is not limited to four rows.
- **Open and choose**: activating the pile or its badge opens the list in place of the input card and moves focus into the list. Each row is a button carrying its note ID. Selecting it loads that note in the same three-step wizard at Step 1, closes the list, shows an editing banner and focuses the first field.
- **Save and cancel**: saving updates the same note ID without a duplicate. Cancel or Escape while editing discards the edit. Escape or **Back to new card** closes the list without changing a note.
- **Draft safety**: opening the list asks before discarding unsaved text in a new card. An unchanged loaded note is not an unsaved draft and never triggers that prompt.
- **Learned cards**: a note is learned when at least one of its cards in the selected deck has Anki `type != 0`. Its row shows a theme warning color and the text **Learned** / **Gelernt**; a legend explains that changes reset progress. Editing a learned note shows a warning banner.
- **Progress reset**: only an actual field change to a learned note reschedules that note's cards in the selected deck as new with `reset_counts=True`, clearing `reps` and `lapses`, and shows a notice. Unchanged saves, cancellation and edits to unlearned notes do not reset progress; cards in other decks are not rescheduled. Existing review history is not deleted; rescheduling is logged.
- **Accessibility**: the pile button has `aria-expanded`, `aria-controls="deck-cards"`, a visible focus ring and a localized spoken count and action. Enter and Space open the list; focus returns to its opener on close. Rows are labelled buttons, and motion respects `prefers-reduced-motion`. Labels, warnings and feedback are available in German and English.

### E. Mobile Editor Routes & Scope

The deck list's **Edit** / **Bearbeiten** action and its empty state lead to `/app/edit?deck=<id>`. The mobile editor uses:

| Route | Purpose |
|---|---|
| `GET /app/edit?deck=<id>` | Open the wizard, session pile and deck-card list |
| `POST /app/edit/preview` | Preview `front`, `back`, `hint` and `example` without saving |
| `POST /app/edit/card/{nid}?deck=<id>` | Load an editable note in the selected deck at Step 1 |
| `POST /app/edit/commit?deck=<id>` | Create for `nid: 0`; otherwise update the selected deck's existing note |

Missing, deck-foreign and unsupported notes cannot be loaded or updated. App navigation, templates and client calls use these routes and `shell_src/app/edit.js`, without legacy app-route aliases. The separate full-featured desktop `/add` editor remains unchanged.

### F. Dedicated Note Type Contract (`AnkiWeb Vocab`)
The design shows only cards of dedicated note types. They carry **no CSS and no JavaScript**: all presentation lives in the design's own stylesheet, and the card HTML is inert markup from Anki's server-side render. Created via AnkiConnect `createModel` (`modelName`, `inOrderFields`, `cardTemplates`, `css`, `isCloze`).

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
- **Escaping is required, and this test does not show the view passes it:** `a < b` and `x & y` were stored as typed and came back raw in `av-front-text` / `av-back-text`. This only demonstrates that the server does not escape; the quick-add view that must escape on save does not exist yet, so there is no passing check for it.
- **An empty `<style></style>` is still prepended** to both `question` and `answer` even though `css` is empty. The templates and the type carry no styling, but the render output is not free of the tag. It is empty and harmless; the client can ignore or strip it. A rule that the card HTML contains no `<style>` element would be wrong for the raw server output.
- `addNote` rejects an all-empty note ("cannot create note because it is empty") and a duplicate ("... it is a duplicate").
- Deleting the type works only after its notes are gone (`/extra_actions/deleteModel`: "3 note(s) still use it" before, `true` after).

**Scope of the type:** Basic (front/back) with two further fields that may be left empty (hint, example). Not covered: cloze, reversed cards, type-in-answer, audio, images, math. Each would be a separate dedicated type with its own contract.

**Existing cards of other note types** are shown **as they are** (server-rendered HTML without the design classes) with an "Other note type" badge. They are **not** skipped: measured, the daily new-card limit (20) fills the queue with the other type and a dedicated-type card becomes unreachable while the counter still shows 20 (`get_queued_cards` and `deck_due_tree` have no note-type filter). Layout of foreign HTML (images, cloze, math) is not guaranteed.

---

## 6. Deck List & Mode Switching (`decks-mockup.html`)

The following links and deck IDs describe the standalone mockups. For the mobile editor's **Edit** action and `/app/edit` route, see §5.E.

- **Deck list**: chunky card rows (emoji, name, due/new counts, mini candy-stripe progress bar) with live search and an empty state.
- **Per-deck actions**: **Learn** → `mockup.html?deck=<id>`, **Edit / Add** → `editor-mockup.html?deck=<id>`.
- **New deck**: a floating yellow **New deck** button (`.btn-new-deck`, fixed above a fade of the canvas colour) and the empty state's **+ New deck** button open a bottom sheet, the same pattern as the reviewer's actions sheet (handle, backdrop, `inert` while closed, Escape and backdrop tap close, focus returns to the opener). The sheet holds a live preview tile (emoji and name), a name field (max 40 characters, counter turns red at the limit, whitespace-only and case-insensitive duplicate names block **Create deck** with an inline error) and a curated emoji picker (four categories, 18 emoji each, `radiogroup`, no system emoji keyboard needed). The new deck is added at the top with 0 due / 0 new / 0 %, a drop-in animation and a toast; its id is a slug of the name, made unique with a `-2`, `-3` suffix. From the empty state the search text pre-fills the name. Reduced motion disables the animations. The sheet reopens reset (empty name, 📚).
- **Navigation**: the reviewer HUD returns to the deck list, whose **Edit / Add** action opens the editor. The reviewer, deck list and editor have no mode switch. Deck ids: `german-b1`, `spanish-a2`, `biology`, `history`, `chemistry`; invalid/missing falls back to `german-b1`.
- **Editor**: the header's first row contains Back, a deck-name chip and Done; the added-card counter is on the second row. The card retains its note-type pill without a repeated deck badge. The chip links back to the deck list and guards uncommitted text, as do leaving and finishing. Done opens the summary; **Start studying** returns to the reviewer for the same deck.
- **Theme**: no toggle in any page; dark palette applied via `prefers-color-scheme`.

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

The completion title receives focus, decorative graphics are hidden from assistive technology, and rating counts remain available as text. The screen follows the system theme and honors `prefers-reduced-motion` for its animations and transitions.
