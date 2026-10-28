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
  - **Failure ('Again')**: When a student fails a card and presses **Again**, the streak does not punish with shame; it resets with a gentle sideways wobble `@keyframes streakReset` (`💔 0 STREAK`) accompanied by encouraging micro-copy (*"Streak Reset! Don’t give up 💪"*).
- **Scope (implementation decision, differs from the prototype)**: The prototype keeps the streak in memory (`let streakCount = 7`). The implementation **derives it from the review log**: the run of most recent reviews with ease 2, 3 or 4 since the collection's day start, across all decks; ease 1 ends the run. It is read-only (no backend stats are written) and survives reload.

### B. Session Progress Meter
- **Concept**: Visualizes study pacing (`14 / 20 CARDS` or dynamic deck due count) inside a candy-bar striped meter.
- **Micro-Interaction**: Dynamic fill bar (`transition: width 0.35s cubic-bezier(0.34, 1.56, 0.64, 1)`) with angled diagonal stripes that smoothly stretches as cards are rated.

---

## 3. Interaction Architecture

1. **Top HUD**:
   - Left: Back to Decks button (chunky rounded square icon) → `decks-mockup.html`.
   - Center: Animated Streak pill badge.
   - Right: More Actions button (`⋮`), which opens the actions sheet holding the `Study | Add` segmented mode switch. The day/night icon is intentionally not shown; dark mode follows `prefers-color-scheme` automatically.
   - Bottom: Session progress meter bar.
2. **Card Stage**:
   - Contained inside an elevated white card with rounded corners (`border-radius: 24px`) and hard shadows.
   - Distinct tags for deck origin (`🇩🇪 German B1 Vocab`) and dynamic star/flag indicator badges.
   - Question presented prominently with phonetic/grammatical hints.
   - Reveal transition unfolds smoothly (`@keyframes revealAnswer`) into definition and contextual sample sentence with highlighted keyword `<mark>`.
3. **Bottom Controls**:
   - **Front State**: Giant, full-width thumb-friendly **Show Answer** button with keyboard indicator (`SPACE`).
   - **Back State**: 4 large ease rating tiles (**Again**, **Hard**, **Good**, **Easy**), each displaying the keyboard shortcut (`1-4`), ease label, and scheduled interval (`< 10m`, `2 d`, `5 d`, `9 d`).
4. **Mobile Bottom Sheet (Card Actions)**:
   - Replaces the desktop-style dropdown menu with a slide-up bottom drawer.
   - Provides clean 2-column quick-action tiles: **Mark Card**, **Flag (Red)**, **Bury Card**, **Suspend**, **Undo Review**, **Set Due Date**, **Card Info**, and **Delete Note**.
   - Tap outside or tap **Dismiss** to close.

---

## 4. Implementation Porting Blueprint for AnkiWeb

When transitioning this design into the live production templates in `ankiweb/`, the changes map directly to four Jinja templates:

### 1. `reviewer_page_body.html.jinja`
- **Location**: `ankiweb/adapters/inbound/http_shared/templates/reviewer_page_body.html.jinja`
- **Changes**:
  - Replace the existing standard Bootstrap top header (`<header class="d-flex justify-content-between...">`) with the new `.top-hud` containing the streak container, theme switcher, and progress meter.
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
  - Restyle `<button id="ansbut">` with `.btn-show-answer` Neo-Pop styling (bold yellow background `#ffd13b`, hard black border, tactile drop-shadow, and `SPACE` badge).
  - Retain the existing `onclick="ankiwebShowAnswer()"` bridge hook.

### 3. `reviewer_ease_buttons_bar.html.jinja`
- **Location**: `ankiweb/adapters/inbound/http_shared/templates/reviewer_ease_buttons_bar.html.jinja`
- **Changes**:
  - Replace the flex row of default Bootstrap outline buttons with the `.ease-grid` 4-column layout.
  - Apply the color classes `.btn-ease-again`, `.btn-ease-hard`, `.btn-ease-good`, `.btn-ease-easy` according to `c.i` index.
  - Display the shortcut key badge in the top-right corner of each tile.
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
   - Primary CTA: **Next: Back →** (`Enter` shortcut).
2. **Step 2: Back (Answer / Definition)**:
   - Focus transitions directly to the definition/answer field.
   - Two optional, collapsed-by-default fields below it: **Hint** (part of speech, plural; the quick chips `Noun`, `Verb`, `Adj`, `(Plural:)` insert here) and **Example sentence** (wrap the key word in `*asterisks*` to highlight it).
   - Leaving both empty keeps the fast two-field path unchanged.
   - Primary CTA: **Preview Card →**.
3. **Step 3: Quick Preview & Commit**:
   - Renders the finished card exactly as the reviewer shows it: Prompt, Answer, plus Hint and Example (with highlighted key word) when present.
   - Primary CTA: **Add to Stack 📥** (vibrant emerald green `#40c057`).
   - Once tapped, the card is **saved immediately as a note** in the target deck (not held in the browser) and the editor resets to Step 1 with clean fields, enabling friction-free continuous entry without leaving the view. Reloading the page loses nothing.

### C. Card-Stack Physical Metaphor & Animation

> Naming (see `CONTEXT.md`): the visual pile is the **added cards** of this session. "Stack" stays only as the animation metaphor and in the mockup's identifiers; the Anki object is a **deck**.

The core psychological hook of the creator is the **physical growing card pile**:
- **Slide-to-Stack Keyframe Animation (`@keyframes slideToStack`)**:
  - Upon tapping **Add to Stack**, the active card physically slides down and rotates (`transform: translate(x, y) rotate(deg)`), visibly joining the stack beneath the editing stage.
  - A fresh blank card simultaneously drops into place from above (`@keyframes popInFreshCard`).
- **Dealt Physical Stack Layers**:
  - Completed cards accumulate beneath the editor at natural cascading offsets (`+32px`, `+64px`, `+96px`) and slight organic rotations (`-3.2°`, `+2.8°`, `-2.0°`), resembling an authentic pile of physical cards dealt onto a table.
  - The top card displays a glowing cue badge: `TOP CARD ↩`.
- **Top HUD Stack Counter (`🗂️ N CARDS ADDED`)**:
  - Counter updates in real-time with an energetic pop-and-wobble animation (`@keyframes stackPillPop`) mirroring the reviewer streak counter.

### D. Edit-Last-Card Affordance (Quick Mistake Correction)
When rapidly typing cards on mobile, students inevitably make typos or notice mistakes right after submitting:
- **One-Tap Reversal**: Tapping either the topmost card in the physical stack, the bottom **Top of stack** peek banner, or the top HUD stack pill loads that card back into the editor (`@keyframes popCardUp`). The card **stays saved**; saving again **updates** the same note instead of adding a second one.
- **State Reconstitution**: The Front and Back text are restored into the editor inputs, the wizard opens directly to Step 1, and the card count is **unchanged** (the card was never removed).
- **Safety Guard**: If the student has already started typing new unsaved text in the current card, a confirmation guards against accidental text loss before loading the saved card.

### E. Porting & Architecture Blueprint
This flow is designed as a **new dedicated mobile route**, completely separate from Anki's existing complex `/add` route:
- **New Route**: `/add/basic` or `/add/quick` (e.g. `quick_add_body.html.jinja`).
- **Scope Separation**:
  - The existing full-featured `/add` editor remains intact for desktop power-users, cloze deletion cards, media uploads, math formulas, and multi-field custom note types.
  - The new quick-add view provides high-school students and mobile users with a distraction-free, zero-config card builder strictly for notes of the dedicated note type **`AnkiWeb Vocab`** (§5.F). Other note types are not shown in the design.
- **Design Token Continuity**:
  - Uses identical `:root` and `[data-theme="dark"]` CSS variables, border widths (`2.5px`), drop shadows (`var(--shadow-card)`), and system font stack as `mockup.html`.
  - Seamless visual transition from building cards in `editor-mockup.html` to reviewing them in `mockup.html`.

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

**Escaping and highlight (change from the prototype):** Anki fields are HTML. The prototype stored plain text and escaped at render time (`CardRender.renderCard`). With server-rendered HTML the contract is: the **writer escapes on save** (the quick-add view must HTML-escape `<`, `>`, `&` before `addNote`, otherwise typed `<` is interpreted as markup), and the `*word*` → `<mark>` conversion for `.av-example` happens in the **client** after render, because Anki has no template filter for it. The converted text is already escaped, so only `<mark>` is added.

**Verified against a throwaway server (not the user's profile; separate `ANKIWEB_COLLECTION`, removed afterwards):**
- `createModel` accepts the type as specified: four fields in order, `css` stays `""`, both templates are stored unchanged (`modelFieldNames`, `modelStyling`, `modelTemplates`).
- Rendering (`cardsInfo`): with empty Hint/Example **no element is emitted** (only whitespace remains); with values the `av-hint` / `av-example` elements appear. `*word*` arrives unchanged, so the `<mark>` conversion stays in the client.
- **Escaping is required, and this test does not show the view passes it:** `a < b` and `x & y` were stored as typed and came back raw in `av-front-text` / `av-back-text`. This only demonstrates that the server does not escape; the quick-add view that must escape on save does not exist yet, so there is no passing check for it.
- **An empty `<style></style>` is still prepended** to both `question` and `answer` even though `css` is empty. The templates and the type carry no styling, but the render output is not free of the tag. It is empty and harmless; the client can ignore or strip it. A rule that the card HTML contains no `<style>` element would be wrong for the raw server output.
- `addNote` rejects an all-empty note ("cannot create note because it is empty") and a duplicate ("... it is a duplicate").
- Deleting the type works only after its notes are gone (`/extra_actions/deleteModel`: "3 note(s) still use it" before, `true` after).

**Scope of the type:** Basic (front/back) with two further fields that may be left empty (hint, example). Not covered: cloze, reversed cards, type-in-answer, audio, images, math. Each would be a separate dedicated type with its own contract.

**Existing cards of other note types** are outside the design (not shown in the new reviewer). Handling them (hidden, old reviewer, `changeNotetype` conversion) is not decided; see `RESEARCH-independent-client.md` §3a.

---

## 6. Deck List & Mode Switching (`decks-mockup.html`)

- **Deck list**: chunky card rows (emoji, name, due/new counts, mini candy-stripe progress bar) with live search and an empty state.
- **Per-deck actions**: **Learn** → `mockup.html?deck=<id>`, **Edit / Add** → `editor-mockup.html?deck=<id>`.
- **Mode switch**: the reviewer's More Actions sheet holds a `Study | Add` segmented control; the back button in the HUD returns to the deck list. The deck list itself has no chip or switch. Deck ids: `german-b1`, `spanish-a2`, `biology`, `history`, `chemistry`; invalid/missing falls back to `german-b1`.
- **Editor**: shows "Adding to <deck>"; switching deck/mode with uncommitted text reuses the unsaved-text confirm guard.
- **Theme**: no toggle in any page; dark palette applied via `prefers-color-scheme`.
