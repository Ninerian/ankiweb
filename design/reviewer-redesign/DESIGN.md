# AnkiWeb Reviewer Mobile-First Playful Redesign
**Target Audience**: High-school students & active learners  
**Format**: Standalone prototype & architectural implementation blueprint  
**Directory**: `design/reviewer-redesign/`  

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
- **Session Scope**: Lives purely in memory (`let streakCount = 7`). When the student leaves or closes the tab, it resets cleanly without dirtying backend user stats.

### B. Session Progress Meter
- **Concept**: Visualizes study pacing (`14 / 20 CARDS` or dynamic deck due count) inside a candy-bar striped meter.
- **Micro-Interaction**: Dynamic fill bar (`transition: width 0.35s cubic-bezier(0.34, 1.56, 0.64, 1)`) with angled diagonal stripes that smoothly stretches as cards are rated.

---

## 3. Interaction Architecture

1. **Top HUD**:
   - Left: Back to Decks button (chunky rounded square icon).
   - Center: Animated Streak pill badge.
   - Right: Quick Dark/Light theme toggle (`🌙` / `☀️`) and More Actions button (`⋮`).
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
