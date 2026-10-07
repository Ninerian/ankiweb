# Anki Frontend Component & Subsystem Migration Tracker (`ts/`)

This document tracks the strangler-fig migration of frontend components from [ankitects/anki `ts/`](https://github.com/ankitects/anki/tree/main/ts) into this Datastar + Jinja + Tailwind/daisyUI stack.

**Verification Approach:** In-Repo Component Gallery & Harness (`/dev/components`) using the Orca browser CLI (`agent-browser`) to inspect rendered DOM, verify interactive events, and ensure feature equality with upstream behavior.

---

## Migration Progress Overview

| Tier | Complexity | Total | Ported & verified | Satisfied without port | Remaining |
|---|---|---|---|---|---|
| **Tier 1** | Easy | 33 | 33 | 0 | 0 |
| **Tier 2** | Medium | 26 | 20 | 6 | 0 |
| **Tier 3** | Hard | 13 | 10 | 3 | 0 |
| **Tier 4** | Very Hard | 7 | 7 | 0 | 0 |
| **Total** | | **79** | **70** | **9** | **0** |


## Overview: what was converted and where to look

**See the components.** Start the app with `ANKIWEB_DEV=1` (the gallery is a dev tool and is off by default) and open `/dev/components`: every ported macro from `ankiweb/adapters/inbound/http_shared/templates/components/` is rendered with its variants and is interactive (`_demo_<name>.html.jinja` next to each macro). Build first with `npm run build` (bundles and CSS).

**Pages that replaced the SvelteKit routes** (all served at the original URL; Jinja + Datastar + small hand-written JS bundles, no compiled Svelte):

| Upstream route | Served at | Python | Templates | JS bundle |
|---|---|---|---|---|
| card-info | `/card-info/<cids>` | `http_pages/card_info.py` | `pages/card_info*.html.jinja` | (server-rendered SVG) |
| change-notetype | `/change-notetype/<old>/<new>` | `http_pages/change_notetype.py` | `pages/change_notetype.html.jinja` | |
| congrats | shown by `/overview` | `http_shared/congrats.py` | `congrats.html.jinja` | |
| deck-options | `/deck-options/<deck id>` | `http_pages/deck_options*.py` (+ FSRS, simulator, help texts) | `pages/deck_options*.html.jinja`, `pages/deck_options/_fsrs`, `_simulator` | |
| editor | `/edit?nid=`, `/add` | `http_pages/editor.py`, `editor_tags.py` | `pages/editor*.html.jinja`, `pages/editor/_toolbar`, `_tags` | `editor-engine`, `tag-editor`, `editor-plain` (CodeMirror 6), `editor-overlays` (MathJax, image, paste, html-filter) |
| graphs | `/graphs` | `http_pages/graphs.py`, `graph_svg.py` | `pages/graphs*.html.jinja` | `graphs` (tooltips) |
| image-occlusion | `/image-occlusion/<path>` | `http_pages/image_occlusion.py` | `pages/image_occlusion.html.jinja` | `io-editor` (SVG mask editor replacing Fabric.js) |
| import-anki-package, import-page | `/import-anki-package/<path>`, `/import-page/<path>` | `http_pages/import_package.py` | `pages/import_anki_package.html.jinja`, `pages/import_page.html.jinja` | |
| import-csv | `/import-csv/<path>` | `http_pages/import_csv.py` | `pages/import_csv*.html.jinja` | |
| preferences | `/preferences` | `http_datastar/preferences.py` | `preferences.html.jinja` | |

Reviewer runtime (`ts/reviewer/*`), MathJax setup, `sveltelib` and `tslib` are **not ported**: they are already provided by the vendored `reviewer.js`/`mathjax.js` and by `shell_src/*` plus Datastar (marked `Satisfied` below with the evidence).

**What "verified" means in this document.** `verified by lead` = I ran real input in the orca browser myself. `independent QA` = a separate agent compared the page with the legacy page (or upstream source) using real input and reported defects, then the author fixed them (rounds are counted). `agent-verified` = only the porting agent's own report, not independently re-checked. Items fixed after the last QA round are flagged "not re-QA'd".

---

## 1. Tier 1: Easy Components (Pure DOM / Presentational / Basic Wrappers)

| Component / Subsystem | Upstream Path | Primary DOM Tags & Key Classes | Target In This Stack | Status | Verification Notes |
|---|---|---|---|---|---|
| **Absolute** | `lib/components/Absolute.svelte` | `<div class="absolute ...">` | `templates/components/absolute.html.jinja` | Ported, agent-verified; gallery render confirmed | Pure CSS positioning container |
| **Badge** | `lib/components/Badge.svelte` | `<span class="badge ...">` | `templates/components/badge.html.jinja` | Ported, agent-verified; gallery render confirmed | daisyUI badge wrapper |
| **ButtonGroup** | `lib/components/ButtonGroup.svelte` | `<div class="btn-group ...">` | `templates/components/button_group.html.jinja` | Ported, agent-verified; gallery render confirmed | Flex button group |
| **ButtonToolbar** | `lib/components/ButtonToolbar.svelte` | `<div class="btn-toolbar" role="toolbar">` | `templates/components/button_toolbar.html.jinja` | Ported, agent-verified; gallery render confirmed | Toolbar wrapper |
| **CheckBox** | `lib/components/CheckBox.svelte` | `<input type="checkbox" class="form-check-input">` | `templates/components/checkbox.html.jinja` | Ported, verified by lead in orca browser | Standard checkbox |
| **Col** | `lib/components/Col.svelte` | `<div class="col-...">` | `templates/components/col.html.jinja` | Ported, agent-verified; gallery render confirmed | Tailwind flex column |
| **Container** | `lib/components/Container.svelte` | `<div class="container...">` | `templates/components/container.html.jinja` | Ported, agent-verified; gallery render confirmed | Tailwind container |
| **DropdownDivider** | `lib/components/DropdownDivider.svelte` | `<hr class="dropdown-divider">` | `templates/components/dropdown_divider.html.jinja` | Ported, agent-verified; gallery render confirmed | Divider line |
| **DropdownItem** | `lib/components/DropdownItem.svelte` | `<button/a class="dropdown-item">` | `templates/components/dropdown_item.html.jinja` | Ported, agent-verified; gallery render confirmed | Dropdown menu item |
| **EnumSelector** | `lib/components/EnumSelector.svelte` | `<select class="form-select">` | `templates/components/enum_selector.html.jinja` | Ported, verified by lead in orca browser | Single select control |
| **EnumSelectorRow** | `lib/components/EnumSelectorRow.svelte` | `<div class="row align-items-center">` | `templates/components/enum_selector_row.html.jinja` | Ported, verified by lead in orca browser | Form label + select row |
| **ErrorPage** | `lib/components/ErrorPage.svelte` | `<div class="error-page alert alert-danger">` | `templates/components/error_page.html.jinja` | Ported, agent-verified; gallery render confirmed | Error display card |
| **FloatingArrow** | `lib/components/FloatingArrow.svelte` | `<div class="floating-arrow">` | `templates/components/floating_arrow.html.jinja` | Ported, agent-verified; gallery render confirmed | Floating popper arrow |
| **HelpSection** | `lib/components/HelpSection.svelte` | `<div class="help-section">` | `templates/components/help_section.html.jinja` | Ported, agent-verified; gallery render confirmed | Help text / link snippet |
| **Icon** | `lib/components/Icon.svelte` | `<svg class="anki-icon">` | `templates/components/icon.html.jinja` | Ported, agent-verified; gallery render confirmed | Inline SVG presenter |
| **IconButton** | `lib/components/IconButton.svelte` | `<button class="btn btn-square">` | `templates/components/icon_button.html.jinja` | Ported to the daisyUI icon button (`btn-square btn-xs`; `btn-primary` / `btn-active` modifiers), no custom CSS | Icon-only button |
| **IconConstrain** | `lib/components/IconConstrain.svelte` | `<span class="icon-constrain">` | `templates/components/icon_constrain.html.jinja` | Ported, agent-verified; gallery render confirmed | Aspect ratio wrapper |
| **Item** | `lib/components/Item.svelte` | `<div class="item ...">` | `templates/components/item.html.jinja` | Ported, agent-verified; gallery render confirmed | Generic item container |
| **Label** | `lib/components/Label.svelte` | `<label class="form-label">` | `templates/components/label.html.jinja` | Ported, verified by lead in orca browser | Form label |
| **LabelButton** | `lib/components/LabelButton.svelte` | `<button class="btn btn-xs">` | `templates/components/label_button.html.jinja` | Ported to the daisyUI button (`btn-xs`; `btn-primary` / `btn-active` modifiers), no custom CSS | Styled label trigger |
| **RenderChildren** | `lib/components/RenderChildren.svelte` | Fragment / slot | `templates/components/render_children.html.jinja` | Ported, agent-verified | Slot pass-through |
| **RevertButton** | `lib/components/RevertButton.svelte` | `<button class="btn btn-sm btn-outline-secondary revert-btn">` | `templates/components/revert_button.html.jinja` | Ported, agent-verified; gallery render confirmed | Reset-to-default button |
| **Row** | `lib/components/Row.svelte` | `<div class="row ...">` | `templates/components/row.html.jinja` | Ported, agent-verified; gallery render confirmed | Tailwind flex row |
| **SelectOption** | `lib/components/SelectOption.svelte` | `<option value="...">` | `templates/components/select_option.html.jinja` | Ported, agent-verified; gallery render confirmed | Option element |
| **SettingTitle** | `lib/components/SettingTitle.svelte` | `<h6 class="setting-title">` | `templates/components/setting_title.html.jinja` | Ported, agent-verified; gallery render confirmed | Section title heading |
| **Spacer** | `lib/components/Spacer.svelte` | `<div class="flex-grow-1">` | `templates/components/spacer.html.jinja` | Ported, agent-verified; gallery render confirmed | Flexbox space filler |
| **StickyContainer** | `lib/components/StickyContainer.svelte` | `<div class="sticky-top">` | `templates/components/sticky_container.html.jinja` | Ported, agent-verified; gallery render confirmed | Sticky positioned box |
| **Switch** | `lib/components/Switch.svelte` | `<div class="form-check form-switch">` | `templates/components/switch.html.jinja` | Ported, verified by lead in orca browser | Toggle switch input |
| **SwitchRow** | `lib/components/SwitchRow.svelte` | `<div class="row align-items-center">` | `templates/components/switch_row.html.jinja` | Ported, agent-verified; gallery render confirmed | Label + toggle row |
| **WithState** | `lib/components/WithState.svelte` | Scoped variables | `templates/components/with_state.html.jinja` | Ported, verified by lead in orca browser | Scoped template values |
| **congrats** (Route) | `ts/routes/congrats/` | `congrats.html.jinja` | `http_shared/congrats.py` + `templates/congrats.html.jinja` | Ported, verified by lead; limits/buried/description/custom-study covered by tests | Study finish screen |
| **browser_selector** | `ts/reviewer/browser_selector.ts` | CSS classes on `<body>` | `shell_src/browser_selector.ts` (called from `shell_src/bootstrap.ts`) | Ported, verified by lead in orca browser | Platform/theme classes |
| **icons** | `ts/icons/` | SVG definitions | `templates/components/icons.html.jinja` (generated by `tools/generate_icons.py`) | Ported, agent-verified (97 icons inline; SVG sprite decision open) | Upstream icon set |

---

## 2. Tier 2: Medium Components (Form Controls / Simple Modals / Basic State)

| Component / Subsystem | Upstream Path | Primary DOM Tags & Key Classes | Target In This Stack | Status | Verification Notes |
|---|---|---|---|---|---|
| **BackendProgressIndicator** | `lib/components/BackendProgressIndicator.svelte` | `<div class="progress">` | `templates/components/backend_progress.html.jinja` | Ported, agent-verified; gallery render confirmed (demo SSE route: dev_progress.py) | Progress bar with SSE |
| **ButtonGroupItem** | `lib/components/ButtonGroupItem.svelte` | `.button-group-item` | `templates/components/button_group_item.html.jinja` | Ported, agent-verified; gallery render confirmed | Contextual border-radius |
| **Collapsible** | `lib/components/Collapsible.svelte` | `<details class="collapsible">` | `templates/components/collapsible.html.jinja` | Ported, verified by lead in orca browser | Collapsible disclosure |
| **ConfigInput** | `lib/components/ConfigInput.svelte` | `<input class="form-control">` | `templates/components/config_input.html.jinja` | Ported, agent-verified; gallery render confirmed | Auto-syncing text input |
| **HelpModal** | `lib/components/HelpModal.svelte` | `<div class="modal">` | `templates/components/help_modal.html.jinja` | Ported, agent-verified; gallery render confirmed | Modal fetching docs |
| **Modal** | `lib/components/Modal.svelte` | `<dialog class="modal">` | `templates/components/modal.html.jinja` | Ported, verified by lead in orca browser | native dialog + daisyUI modal |
| **NotetypeChooser** | `lib/components/NotetypeChooser.svelte` | `<button class="btn">` + modal | `templates/components/notetype_chooser.html.jinja` | Ported, agent-verified; gallery render confirmed; quoting hardened | Note type selector |
| **Popover** | `lib/components/Popover.svelte` | `<div class="popover">` | `templates/components/popover.html.jinja` | Ported, agent-verified; gallery render confirmed | Floating popup menu |
| **Portal** | `lib/components/Portal.svelte` | Dynamic DOM teleport | `templates/components/portal.html.jinja` (Datastar `data-init` teleport) | Ported, agent-verified | Teleports to body |
| **Shortcut** | `lib/components/Shortcut.svelte` | Window keydown listener | `templates/components/shortcut.html.jinja` | Ported, verified by lead (real key presses) | Key shortcut binder |
| **TitledContainer** | `lib/components/TitledContainer.svelte` | `<div class="card">` | `templates/components/titled_container.html.jinja` | Ported, agent-verified; gallery render confirmed | Card with header title |
| **WithContext** | `lib/components/WithContext.svelte` | Context provider | `templates/components/with_context.html.jinja` | Ported, agent-verified | Dependency injection |
| **WithOverlay** | `lib/components/WithOverlay.svelte` | `<div class="modal-backdrop">` | `templates/components/with_overlay.html.jinja` | Ported, agent-verified; gallery render confirmed | Backdrop overlay |
| **WithTooltip** | `lib/components/WithTooltip.svelte` | daisyUI `tooltip` + `data-tip` | `templates/components/with_tooltip.html.jinja` (daisyUI tooltip) | Ported, agent-verified | Tooltip trigger |
| **change-notetype** (Route)| `ts/routes/change-notetype/` | Field mapping form | `http_pages/change_notetype.py` + `templates/pages/change_notetype.html.jinja` | Served at /change-notetype; verified by lead (mapping + Save); independent QA round 3; malformed ids now handled like legacy (author-verified) | Remap note type fields |
| **import-anki-package** (Route)| `ts/routes/import-anki-package/` | File upload & deck choice | `http_pages/import_package.py` + `templates/pages/import_anki_package.html.jinja` | Served at /import-anki-package; independent QA round 3; final sweep confirmed payload, results log counts vs backend and error views | Package import wizard |
| **import-page** (Route)| `ts/routes/import-page/` | Import logs & conflicts | `http_pages/import_package.py` + `templates/pages/import_page.html.jinja` | Served at /import-page (legacy had no route); agent-verified; search links open /browse | Log results viewer |
| **preferences** (Route)| `ts/routes/preferences/` | Settings tabs & inputs | `http_datastar/preferences.py` + `templates/preferences.html.jinja` | Already Jinja at /preferences; author audit; independent QA round 3 (round trip incl. Svelte-editor lab flag) | Global preferences |
| **answering** | `ts/reviewer/answering.ts` | Ease button generator | `reviewer_ease_buttons_bar.html.jinja` | Satisfied, no port: vendored reviewer.js already provides it (agent observed window.anki.mutateNextCardStates + live ease-button flow) | Ease intervals & keys |
| **images** | `ts/reviewer/images.ts` | Preload `<img>` tags | `shell_src/reviewer_images.js` | Satisfied, no port: vendored reviewer.js preloads answer images (agent observed answer-only image fetched before reveal) | Image load observer |
| **preload** | `ts/reviewer/preload.ts` | `<link rel="preload">` | Shell asset preloader | Satisfied, no port: vendored reviewer.js preloadResources runs in _updateQA | Font/style prefetching |
| **reviewer.scss** | `ts/reviewer/reviewer.scss` | CSS card layout rules | `shell_src/reviewer.css` | Satisfied, no port: vendored css/reviewer.css is the compiled upstream file (agent measured computed styles) | Card review styling |
| **context-menu** | `ts/lib/context-menu/` | Custom context menu | `templates/components/context_menu.html.jinja` | Ported, agent-verified; gallery render confirmed (macro components/context_menu.html.jinja) | Right-click action menu |
| **html-filter** | `ts/lib/html-filter/` | HTML cleaning | `shell_src/bundles/editor-overlays/html-filter.ts` (client) + `ankiweb/core/html_sanitize.py` (server, unchanged) | Ported (basic/extended/internal modes) in the overlays bundle; independent QA checked paste handling | Strip unsafe tags |
| **tslib** | `ts/lib/tslib/` | RPC, nightmode, shortcuts | `shell_src/` | Satisfied, no port: covered by shell_src pycmd_shim/bootstrap/browser_selector + Python i18n; no page needs an unshimmed function (agent audit) | Core webview bridge |
| **mathjax** | `ts/mathjax/` | MathJax 3 configuration | MathJax script in shell | Satisfied, no port: web_assets/js/mathjax.js matches ts/mathjax/index.ts; agent observed \(x^2\) and \[\frac{a}{b}\] typeset in reviewer | TeX equation rendering |

---

## 3. Tier 3: Hard Components (Complex State Machines / Async Search / Floating UI)

| Component / Subsystem | Upstream Path | Primary DOM Tags & Key Classes | Target In This Stack | Status | Verification Notes |
|---|---|---|---|---|---|
| **DeckChooser** | `lib/components/DeckChooser.svelte` | Tree modal with live search | `templates/components/deck_chooser.html.jinja` | Ported, agent-verified; gallery render confirmed; quoting hardened | Deck tree selection modal |
| **DynamicallySlottable** | `lib/components/DynamicallySlottable.svelte` | Dynamic slot injector | `templates/components/dynamically_slottable.html.jinja` | Ported, agent-verified | Dynamic sub-layouts |
| **ItemChooser** | `lib/components/ItemChooser.svelte` | Modal + keyboard filter | `templates/components/item_chooser.html.jinja` | Ported, verified by lead in orca browser (open/search/Enter/Escape); attribute quoting hardened for special characters | Searchable item picker |
| **Select** | `lib/components/Select.svelte` | Custom combobox list | `templates/components/select.html.jinja` | Ported, verified by lead (real click, ArrowDown+Enter, mouse option, outside click, Escape) | Accessible dropdown listbox |
| **SpinBox** | `lib/components/SpinBox.svelte` | Number input with steppers | `templates/components/spin_box.html.jinja` | Ported, verified by lead in orca browser (click/ArrowUp/clamp/percentage; wheel and long-press not exercisable via CLI) | Accelerated stepper input |
| **WithFloating** | `lib/components/WithFloating.svelte` | Popper/Floating-UI layout | `templates/components/with_floating.html.jinja` | Ported, verified by lead (real click open/close, keyboard, outside click); flip/shift/scroll edge cases agent-verified | Dropdown positioning |
| **card-info** (Route) | `ts/routes/card-info/` | Card statistics & revlog | `http_pages/card_info.py` + `templates/pages/card_info*.html.jinja` | Served at /card-info; verified by lead; independent QA round 3; missing-card/invalid ids and time-range selector confirmed by the final sweep | Card metrics & history |
| **import-csv** (Route) | `ts/routes/import-csv/` | Column-to-field mapper | `http_pages/import_csv.py` + `templates/pages/import_csv*.html.jinja` | Served at /import-csv; verified by lead on a real CSV; independent QA round 3 (TSV, semicolon, BOM, directives, ragged rows) | CSV preview and mapping |
| **reviewer index** | `ts/reviewer/index.ts` | QA review controller | `reviewer_page_body.html.jinja` | Satisfied, no port: vendored reviewer.js provides _showQuestion/_showAnswer/_updateQA/type-in (agent observed in live reviewer) | Card review cycle logic |
| **reviewer_extras** | `ts/reviewer/reviewer_extras.ts` | Action drawer & whiteboard | `reviewer_actions_bar.html.jinja` | Satisfied, no port: obsolete upstream shim; mutateNextCardStates and imageOcclusion API already in vendored reviewer.js | Gesture & whiteboard tools |
| **tag-editor** | `ts/lib/tag-editor/` | Tag chips + autocomplete | `shell_src/bundles/tag-editor.ts`, `templates/pages/editor/_tags.html.jinja`, `http_pages/editor_tags.py` | Ported; independent QA (editor round 1 and 3): chips, autocomplete, save | Chips input with dropdown |
| **domlib** | `ts/lib/domlib/` | Range & selection utils | `shell_src/bundles/editor/{selection,dom,surround,commands}.ts` | Ported inside the editor engine; independent QA (editor round 3) | Caret & node operations |
| **sveltelib** | `ts/lib/sveltelib/` | Action stores & directives | Datastar signal expressions | Satisfied, no port: replaced by Datastar modifiers, native dialogs and daisyUI components, shortcut and modal macros | Client reactivity glue |

---

## 4. Tier 4: Very Hard Components (WYSIWYG / Canvas / Data Tables / FSRS Simulator)

| Component / Subsystem | Upstream Path | Primary DOM Tags & Key Classes | Target In This Stack | Status | Verification Notes |
|---|---|---|---|---|---|
| **VirtualTable** | `lib/components/VirtualTable.svelte` | Sliced table rows | `templates/components/virtual_table.html.jinja` + `shell_src/bundles/tables.ts` | Ported, verified by lead (15 rows rendered for 100,000; wheel 3000px -> row #93; end -> #99999) | Large data infinite list |
| **ScrollArea** | `lib/components/ScrollArea.svelte` | Custom scrollbar tracks | `templates/components/scroll_area.html.jinja` + `shell_src/bundles/tables.ts` | Ported, agent-verified (thumb ratio, drag, keyboard); not independently re-checked | Custom virtual scroll track |
| **editor** (Route) | `ts/routes/editor/` | ContentEditable note editor | `http_pages/editor.py`, `templates/pages/editor*.html.jinja`, bundles `editor-engine`, `tag-editor`, `editor-plain`, `editor-overlays` | Served at /edit and /add; independent QA 3 rounds. Open: audio recording implemented but not exercised with a microphone | Rich text field editing |
| **deck-options** (Route) | `ts/routes/deck-options/` | FSRS optimizer & deck tabs | `http_pages/deck_options*.py`, `templates/pages/deck_options*.html.jinja` (+ FSRS and simulator partials) | Served at /deck-options/<id>; independent QA 3 rounds; final sweep confirmed FSRS URLs, Close prompt, filtered deck, Default preset; preset-delete reassignment and modal cleanup fixed afterwards by the author (tests, not re-QA'd) | Complex deck parameters |
| **graphs** (Route) | `ts/routes/graphs/` | D3 statistical charts | `http_pages/graphs.py` + `graph_svg.py`, `templates/pages/graphs*.html.jinja`, `shell_src/bundles/graphs.ts` | Served at /graphs; independent QA 3 rounds; round-3 fixes confirmed by the final independent sweep (values checked against pylib) | Analytics charts & curves |
| **image-occlusion** (Route)| `ts/routes/image-occlusion/` | Fabric.js mask editor | `http_pages/image_occlusion.py`, `templates/pages/image_occlusion.html.jinja`, `shell_src/bundles/io-editor.ts` | Served at /image-occlusion; independent QA 3 rounds (cloze strings vs upstream source); late fixes (8 handles, duplicate, toolbar, serialization) confirmed by the final independent sweep | Vector image occlusion |
| **editable** | `ts/lib/editable/` | ContentEditable engine | `shell_src/bundles/editor-engine.ts` (`window.AnkiwebEditor`) | Ported; independent QA (3 rounds): typing, formatting, nested toggles, cloze incl. nested/overlap, Tab navigation, toolbar states | Core field rich text engine |

---
*Updated after each verification in Orca browser.*

---

## Verification protocol and lessons (read before adding rows)

- Gallery: `GET /dev/components` auto-discovers `templates/components/_demo_*.html.jinja`. Run `npm run build` after touching `shell_src/**`.
- **Datastar needs settle time.** The full gallery takes seconds to be processed after `networkidle`; clicking earlier gives false failures. Wait ~3 s before interacting.
- **Use real input**, not scripted `el.value = ...`: Datastar 1.0.3 patches element property setters (`datastar-prop-change`), so synthetic assignments can mask or fake results. Use `agent-browser select/click/fill`.
- Datastar 1.0.3 syntax used here: `data-bind="signalName"` (bare name, never `$name`; the leaf macros strip a leading `$`), modifiers as `__prevent` / `__duration.60s`, non-empty expressions for `data-on:*`.

## Adaptations and known deviations from upstream

| Component | Deviation | Reason |
|---|---|---|
| Switch | `rtl` is a macro argument, not read from `getComputedStyle`; extra `anki-switch` scoping class; no `nightMode` class on the input | server-rendered, theme via daisyUI `data-theme` |
| Label | `preventDefault` via `data-on:click__prevent="void 0"` | Datastar requires a non-empty expression |
| ButtonGroupItem | position passed explicitly instead of Svelte context | no context in Jinja |
| Icon | data generated by `tools/generate_icons.py` into `icons.html.jinja` (97 icons) | `icons.ts` is TypeScript |
| congrats | Kept a `Back to Decks` button outside `.congrats` (upstream relies on the desktop toolbar); 60 s refresh is a page reload, not a `@post`, so it never mutates the collection (a filtered deck's `/overview/refresh` rebuilds the deck) | web navigation / no side effects |
| browser_selector | Ported to `shell_src/browser_selector.ts`, applied from `bootstrap.ts` | parity with `ts/reviewer/browser_selector.ts` |

## Known open items

- Audio recording in the editor (F5) is implemented (MediaRecorder + upload) but was not exercised with a real microphone (headless browser); media attach (F3) was verified with a PNG and an MP3.
- Deck-options preset deletion now reassigns decks via `col.decks.remove_config` and the modal cleanup was hardened after the last independent sweep; both are covered by tests and author-verified only.
- The shared revert-button macro now accepts bare signal names (a `$`-less name broke Datastar's `data-show` on the import page); verified by the lead on the import page and the gallery.
- Icons are inlined per use; an SVG sprite would reduce page weight (design decision open).
- Long-press and mouse-wheel behaviour of SpinBox could not be exercised through the CLI.

## Decision log

- 2026-09-30: user chose **full rewrite in Jinja/Datastar** for the four routes whose upstream JS is compiled Svelte that owns its DOM (deck-options, editor, graphs, image-occlusion). Replacement pages were staged under `/next/*` and independently verified.
- 2026-09-30: **Cutover completed**: all replacement pages are now served at original URLs (`/graphs`, `/deck-options/{deck_id}`, `/card-info/{ids}`, `/change-notetype/{ids}`, `/image-occlusion/{path}`, `/import-csv/{path}`, `/import-anki-package/{path}`, `/import-page/{path}`, `/edit`, `/add`). The vendored SvelteKit SPA router, `_app` asset serving, SPA night-mode hash rewrites, and legacy editor/add handlers were fully removed.
- 2026-09-30 (later): **cutover done.** All rewritten pages are served at their original URLs (package `http_pages`, no `/next` prefix); the vendored SvelteKit page plumbing (`build_sveltekit_router`, `/_app`, `SVELTEKIT_PAGES`, the `#night` SPA link hack) and the legacy `/edit`/`/add` WebSocket editor pages were removed; `/dev/components` and `/dev/progress/*` are dev tools behind `ANKIWEB_DEV=1`. Page titles use the upstream Fluent strings. The cutover also produced 14 failing browser tests (written for the removed pages) and a broken toolbar selector; both were fixed, and the editor gained Fields / Cards / Preview links that the legacy glue provided. Dark mode was found broken on the new pages (white cards with pale text) and fixed with an objective contrast scan per page (graphs dark: 190 offenders -> 1; deck-options: 13 -> 0; theme aliases `--canvas`, `--fg`, `--border` added to `shell_src/theme.css`); light mode unchanged.
