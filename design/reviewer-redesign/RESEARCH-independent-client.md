# Research: A Client Independent of the Current Frontend

**Questions**
1. What is needed to build a client independent of the current ankiweb frontend?
2. Is the AnkiConnect interface sufficient for communication?
3. What is strictly required from the Anki library to study cards and to implement the design?
4. Which frameworks fit best?

**Scope**: research only. No project code changed. Nothing was built or run against the API.
**Evidence legend**: **belegt** = read in project code or stated by a source; **ungeprüft** = not tested here; **[INFERENCE]** = my conclusion, not directly observed.
**Reading notes**: code references are to the repo at `/Users/danielgrosse/orca/workspaces/ankiweb/design-update`; the `anki` library was read at version 26.9.2 from `.venv`.

---

## 1. Short answer

1. **AnkiConnect covers rating, searching, counting, card data and the four interval labels, but not the queue.** `answerCards` rates cards through the real v3 scheduler without a GUI, and `findCards`/`cardsInfo`/`getDeckStats` give search and data. `cardsInfo` also returns `nextReviews`, the four interval labels per card, **measured without a browser reviewer** (§10). What is missing is the **next card in Anki's learning order, together with the new/learning/review counts for that queue**: no action returns the queue head. The `gui*` actions drive the open browser reviewer and need it. **[INFERENCE]** that the gap is only the queue head, based on the code and the test below.
2. A client can be built by **adding a small server-side study API** (next card, render, answer) on top of the existing core, or by combining AnkiConnect queries with client-side queue logic. The first is cleaner.
3. **The scheduler must stay on the server.** Anki's v3 scheduler and card rendering live in the Rust backend through the `anki` Python package. A browser client cannot run them.
4. For frameworks, this research found **candidates and criteria, not a proven best choice**: Svelte, SolidJS and Preact are reported as small, but those figures come from blog comparisons of sample apps, not from a measurement on this project. See §6.
5. The client talks to this server over the AnkiConnect-style API (or a new study API). It needs **no Anki sync protocol**; sync is out of scope in `README.md`.
6. **Offline is not a goal**, so the client does not have to be a standalone SPA. **Jinja + Datastar is a viable option and the lowest-change one** (§6). The server-side study endpoints in point 2 are needed either way; only the transport differs (HTML fragments over SSE instead of JSON).

## 2. What the current stack exposes (belegt)

| Interface | Where | What it gives a client |
|---|---|---|
| AnkiConnect `POST /` (JSON-RPC) and typed REST `POST /actions/{name}`, port 8765, Swagger at `/docs`, schema at `/openapi.json`, optional `X-API-Key` | `README.md`, `http_ankiconnect/rest.py` | 122 actions (counted via `@action(` decorators) |
| Web pages (Jinja + Datastar) on port 8000, session cookie if `ANKIWEB_PASSWORD` is set | `app.py` | HTML UI, not a data API |
| `/_anki/<method>` RPC passthrough to Rust backend, fixed allow-list `PASSTHROUGH` | `core/rpc/passthrough.py` | A set of backend methods used by the vendored Svelte pages: `get_note`, `card_stats`, `graphs`, `congrats_info`, `get_deck_names`, `get_review_logs`, ... Not the scheduler queue |
| `/ws` WebSocket bridge, enabled only by the native reviewer | `http_shared/page.py`, `ws_bridge/ws.py` | `pycmd`-style commands for the browser reviewer |

## 3. Is AnkiConnect enough? Action-level findings (belegt)

**Available and usable without a GUI session:**
- `deckNamesAndIds`, `getDeckStats`, `findCards`, `cardsInfo`, `notesInfo`, `areDue`, `getIntervals`, `getEaseFactors`, `getNumCardsReviewedToday`, `getReviewsOfCards`, `cardsToNotes`, `retrieveMediaFile`, `extendCardLimits` (ankiweb extra action).
- `answerCards`: answers cards by `cardId` and `ease` (1 to 4) through the real v3 scheduler (`get_scheduling_states` + `build_answer` + `answer_card`). Works without a GUI. It starts the card timer itself right before answering.
- Mutations: suspend/unsuspend, `forgetCards`, `relearnCards`, `setDueDate`, `changeDeck`, note/field edits.

**Not usable for an independent client:**
- `guiCurrentCard`, `guiShowQuestion`, `guiShowAnswer`, `guiAnswerCard`, `guiStartCardTimer`: these read `ui.review_active` / `ui.current_card_id` and dispatch to the browser reviewer through `hub.dispatch_cmd("reviewer", ...)`. They return `false` or raise when no reviewer is open. They mirror the browser UI; they are not a session API for another client.

**What is missing (gap):**
- No action returns "the next card the scheduler would show" (the queue head) in Anki's learning order, with the **learn/review/new counts of that queue**. In the code this data comes from `col.sched.get_queued_cards(...)` and `col.sched.counts()`, used by the native reviewer (`http_screens/reviewer.py`), `guiCurrentCard` and the overview page. The four interval labels are **not** part of the gap: `cardsInfo.nextReviews` returns them per card without a GUI (tested, §10). Whether those labels equal the ones the queue head would show is **ungeprüft**.
- `findCards` with a search like `deck:X is:due` returns ids, but it does not apply Anki's queue rules (learning steps, day-learning, daily limits, burying, new-card order, siblings). **[INFERENCE]** that a client reimplementing this would drift from the real scheduler.
- Card **rendering** is available through `cardsInfo`: tested, it returns `question`, `answer`, `css`, `fields` and `nextReviews` (§10). Whether it includes AV tags is **ungeprüft**, because the dedicated type has no audio.
- No endpoint for "undo last answer" outside the GUI path (`guiUndo`; belegt in `gui.py`). **[INFERENCE]** that it may depend on GUI state as well. **ungeprüft.**

**Auth and transport (belegt):**
- AnkiConnect has its own key (`ANKIWEB_AC_KEY`, header `X-API-Key`), separate from the web password (`ANKIWEB_PASSWORD`, session cookie).
- Default bind is `127.0.0.1`; LAN use needs config. PWA/HTTPS aspects are in `RESEARCH-pwa.md`.
- CORS (read in `http_ankiconnect/cors.py`, `ankiconnect/config.py`, `ankiconnect/app.py`): the origin list comes from `webCorsOriginList` and **defaults to `["http://localhost"]`**. Any other origin is rejected; `"*"` allows all. Requests with no `Origin` header (curl, server-to-server) are allowed. `Access-Control-Allow-Headers` is `*`, and `Access-Control-Allow-Private-Network: true` is sent (`app.py:132`).
- The API key is checked in `ankiconnect/dispatch.py` for every request when set, independently of CORS. A browser client must send it (`key` in the body or `X-API-Key` on the REST routes).
- **[INFERENCE]** A PWA served from an HTTPS origin cannot call a plain `http://` API on a LAN IP (mixed content), so the API also needs HTTPS or the same origin. Not tested.
- **Timing caveat** (read in `cards.py:324`): `answerCards` calls `card.start_timer()` itself immediately before answering, so the recorded answer time is **not** the user's real reading time. A client using only `answerCards` loses accurate time-taken in the review log. The native reviewer starts the timer when the question is shown (`reviewer.py:77`).

**Verdict**: AnkiConnect covers decks, search, card data, mutations and answering. It does not cover **queue-driven studying**. Options:

| Option | Idea | Risk |
|---|---|---|
| A. Add a study API on the server | New endpoints (e.g. `GET /api/study/next?deck=...` returning the queue head, rendered sides, counts, AV tags; `POST /api/study/answer`) built on the same functions the native reviewer uses (`load_question`, `render_answer`, `answer_current`). The four labels can come from `describe_next_states` or from `cardsInfo.nextReviews` | Small server change, no scheduler drift. Needs a session or a stateless token for scheduling states (states come with the queued card). |
| B. Client queue over AnkiConnect | Client calls `findCards`, `cardsInfo` and `answerCards` itself | Reimplements queue rules and counts (the labels are available per card); order would drift from the real scheduler. Not recommended. **[INFERENCE]** |
| C. Reuse the `/ws` bridge | Drive the reviewer by commands | Couples the client to the old reviewer JS and to one session. Not independent. |


## 3a. Card content under the "dedicated note types" rule

**Constraint (from the product owner):** only dedicated note types may be used to show cards in the design. They are created to match the requirements and contain **no styling of their own and no JavaScript**. The design owns all presentation.

**What this removes (belegt for the mechanism, [INFERENCE] for the conclusion):**
- Note-type CSS is part of what Anki's render returns (`render_output().css`, `question_and_style()` in `anki/template.py`) and is stored per note type (`model["css"]`, read by `modelStyling`, written by `updateModelStyling`/`createModel(css=...)`, `actions/models.py`). A dedicated note type is created with **empty `css`**, so there is nothing to collide with the Neo-Pop tokens. The earlier iframe/shadow-root isolation question disappears for these cards.
- No card JavaScript: nothing in the card HTML has to be executed, so the client can insert it as inert markup. **[INFERENCE]** it must still be sanitized if field content can come from imports; the dedicated type does not control what users type into fields.

**What the design must now provide itself:**
- Layout and typography of front, hint, back, example: the client styles them with its own CSS classes. This only works if the templates emit **stable, minimal markup** the client can target (for example one wrapper element per field with a fixed class name). That markup is part of the note-type contract below.
- Cloze highlighting, type-in-answer, audio buttons and `{{FrontSide}}` handling are still produced or expected by the backend render. The native reviewer adds audio buttons and type-answer on top (`render_av_buttons`, `type_answer_*`, `reviewer.py`). A client must handle at least the AV tags that the render returns, unless dedicated types exclude them. **[INFERENCE]** open decision.

**Template content (what "created to the requirements" means):** a note type is created via `createModel` with `inOrderFields`, `cardTemplates` (`Front`/`Back` per template), `css` and `isCloze` (`actions/models.py:229`). Templates for a dedicated type should contain **only** field references and the minimal wrapper markup: no `<style>`, no `<script>`, no inline event handlers. This applies to the **templates and the stored `css`**. The render output still begins with an empty `<style></style>` (tested, §10), so "no styling" does not mean "no `<style>` element in the HTML the client receives"; it is empty and harmless.

**Mockup fields versus Anki fields:** the mockup shows `front`, `hint`, `back`, `example` (`DESIGN.md` §5). Anki has no such concept: a note has the fields of its note type. Therefore the dedicated type needs those four fields, and the client can either render **from the fields** (`cardsInfo`/`notesInfo`) or **from the rendered HTML**:

| Approach | Gets | Loses / needs |
|---|---|---|
| Rendered HTML (`question()`/`answer()`) inserted into the design's card container | Backend render of templates, conditionals, cloze, AV tags; one code path for all dedicated types | The client depends on the markup the templates emit; styling by class selectors |
| Client renders from fields | Full control of layout, matches the mockups exactly | Must reimplement the template logic the types use (conditionals on empty hint/example, cloze, type-in-answer). With simple 4-field types this is small; **[INFERENCE]** it grows with each new type |

**Decision (follows from the rule, not from a measurement):** the client shows the **server-rendered HTML** (`question()`/`answer()`) inside the design's card container and styles it with the design's own classes. Rendering from fields is rejected: it would require reimplementing cloze, AV tags, type-in-answer and template conditionals in the client, which the rule "dedicated types without CSS or JS" is meant to avoid. Field-based rendering remains an option only for a type whose templates are trivial.

**Consequences to settle (not decided here):**
1. **Which dedicated types exist.** Minimum from the design: Basic (front/back) and a variant with hint and example (4 fields). Whether a cloze type, a reversed type or a type-in-answer type is needed is a product decision.
2. **Existing cards.** Cards of other note types (for example Anki's default Basic) are not shown in the design under this rule. What happens to them (hidden, shown in the old reviewer, converted with `changeNotetype`) is open. **ungeprüft**: whether conversion preserves scheduling is not investigated here.
3. **Enforcement.** The client or the server must filter decks and queues to dedicated types. The queue (`get_queued_cards`) is per deck, not per note type. A deck that mixes types would need a search filter (`note:<name>`); how that interacts with Anki's queue rules and counts is **ungeprüft**.
4. **Who creates and updates the types**, and whether templates are versioned so that a client change in markup can be rolled out (`updateModelTemplates`).

## 4. What is strictly required from the Anki library (belegt unless marked)

Everything below runs in the `anki` Python package / Rust backend, on the server:

| Need | API (read in `anki` 26.9.2 and in `reviewer.py`) | Why it cannot move to the client |
|---|---|---|
| Next card + states + context | `col.sched.get_queued_cards(fetch_limit=1)`; returns card, `states`, `context` | Implements the v3 queue: learning, review, new, limits, burying, siblings |
| Counts (new / learning / review) | `col.sched.counts()` or counts from the queued-cards response | Derived from the same queue |
| Render question/answer HTML | `card.question()`, `card.answer()`, `card.render_output()` (also gives `question_av_tags`, `answer_av_tags`, `css`) | Templates (fields, conditionals, filters, cloze, hints, type-in-answer) are rendered by the Rust backend. With dedicated types `css` is empty. |
| Start timer before answering | `card.start_timer()` (the code comments say this is REQUIRED because `build_answer()` calls `card.time_taken()`) | Time taken is recorded in the review log |
| Interval labels for the 4 buttons | `col.sched.describe_next_states(states)`, or `cardsInfo.nextReviews` per card (tested, no GUI) | Derived from scheduling states (FSRS or SM-2 per deck config); a client cannot compute them itself |
| Answer | `col.sched.build_answer(card, states, rating)` then `col.sched.answer_card(answer)` | Writes card state and review log, returns undoable `OpChanges` |
| Type-in-answer compare | `compare_answer` via ankiweb's `type_answer` helpers | Diff rendering done by the backend |
| Media | media folder files served over HTTP (`retrieveMediaFile` or a media route) | Cards reference files by name |
| Mutations during review | suspend, bury (card/note), flag, mark, set due, forget, delete note, undo | Each is a backend operation with undo support |

**Not required** for studying: the vendored SvelteKit pages, `editor.js` (except for editing), the `/ws` bridge, MathJax on the server. MathJax is a browser-side renderer; the card HTML contains MathJax markup that a client must typeset. **[INFERENCE]** based on the native reviewer loading MathJax assets (`README.md` mentions MathJax as a retained asset).

**Needed for the design** (from `DESIGN.md` and the mockups):
- Streak and progress meter: purely client-side, no backend data needed except the daily counts for the progress total (from queue counts).
- Four ease tiles with intervals: needs `describe_next_states` labels (server).
- Deck list with due/new counts and progress: `getDeckStats` or `deck_due_tree()` (belegt: `col.sched.deck_due_tree()` is used in `notify/engine.py`). Whether `getDeckStats` returns the same counts as the deck browser: **ungeprüft**.
- Actions sheet (mark, flag, bury, suspend, undo, set due, card info, delete note): all exist as AnkiConnect or ankiweb RPC operations; card info page uses `card_stats` via passthrough.
- Quick-add (Front/Back required by the view; Hint/Example may be left empty): `addNote` (an AnkiConnect action; presence in the 122 was not itemized here, **ungeprüft**), plus a note type with the right fields. A note type has a fixed field list, so the dedicated type has all four fields and the empty ones are stored as empty strings; the current mockup assumes them. See `DESIGN.md` §5.F and `RESEARCH-enrichment.md`.
- Rendering of card HTML in the client: with dedicated types without CSS or JS, insert the server HTML into the design's card container and style it with the design's own classes. See §3a. No iframe or shadow root is needed for isolation.

## 5. Minimal server surface for an independent client

**[INFERENCE]** based on §3 and §4. This is a proposal, not an investigation result.

| Endpoint | Purpose | Built on |
|---|---|---|
| `GET /api/decks` | deck tree with new/learn/review counts | `deck_due_tree()` |
| `POST /api/study/next?deck=` (stateful, **not** a GET) | take the queue head: id, question HTML, answer HTML, css, AV tags, counts, 4 interval labels. **Side effects by design:** stores the card and its scheduling states in the server session and **starts the answer timer**. Calling it again for the same card restarts the timer | `load_question`, `render_answer` pattern |
| `GET /api/study/peek?deck=` (optional, no side effects) | counts and, if wanted, the queue head's rendered sides and labels **without** `start_timer` and without writing the session. Needed only if a client wants to show a card before the student is actually studying it | `get_queued_cards`, `describe_next_states`; **not built or tested** |
| `POST /api/study/answer` | answer by card id, ease and token; returns next card or finished | `answer_current` / `answerCards` logic |
| `POST /api/study/action` | bury, suspend, flag, mark, set due, forget, delete, undo | existing action implementations |
| `GET /media/<file>` | media | existing media handling |
| `POST /api/notes` | add note (Front/Back/Hint/Example) | `addNote` |

Open points: whether scheduling states can be re-fetched per card (`get_scheduling_states(cid)` is used in `answerCards`, so a stateless token may not be needed). The spike (§11) used **server-held state** (one in-flight card per process, like the native reviewer) instead of a token and worked; whether a stateless token yields identical intervals is **ungeprüft**. Authentication (AnkiConnect key versus session cookie versus a new token) is still open.

## 6. Frameworks

Findings from search summaries (web sources, secondary, not benchmarked by me):
- Svelte and SolidJS are reported to have the smallest production bundles for a PWA (about 27 KB gzipped each in one comparison, versus about 91 KB for React). Preact is reported as light, with no figures in the source.
- The two sources that quantified bundle size are blog comparisons. The numbers are for a sample app, not for this one. **ungeprüft** for ankiweb.

Fit with this project:

| Option | Pros | Cons / unknowns |
|---|---|---|
| **Svelte / SvelteKit** | Reported small bundles. The vendored Anki pages are SvelteKit builds (belegt, `UPSTREAM.md`), though they are version-pinned and separate from any new client. Plain Svelte + Vite can build a static client | Not measured on this project; vendored pages are not reusable for a new design |
| **SolidJS** | Small, fast fine-grained reactivity; JSX | Smaller ecosystem (reported 2-5% usage) |
| **Preact (+ signals)** | Small, React-like API | Fewer built-in features than Svelte |
| **React** | Largest ecosystem | Larger bundle per the same sources |
| **Vanilla JS + web components** | No framework; matches the existing prototypes (static HTML + one shared JS file) | More manual state handling; no data in the sources about it |
| **Keep Jinja + Datastar (PWA client online-only)** | Already in the repo (`datastar-py`; 12 of the 13 modules under `http_datastar/` use `DatastarResponse`; `datastar.js` is loaded in `shell.html.jinja`). Server-rendered; no second client codebase, no CORS or key-vs-cookie auth question (same origin, session cookie). Matches the dedicated-note-type decision (§3a): the server already holds the rendered HTML. Offline is not required (`RESEARCH-pwa.md` §5 scenario 1 or 2) | Every interaction is a server round trip; reveal and rating latency depend on the network. The design's local-only effects (streak, progress, stack animation, `*word*` highlight) stay in small client scripts or Datastar signals. Needs a TLS endpoint for installability (`RESEARCH-pwa.md` §1). The study loop itself (next card, answer) is **not built yet**: today only the native reviewer implements it, over the `/ws` bridge, not as Datastar handlers |

Constraints that matter more than the framework:
- **Card HTML rendering** under the dedicated-types rule needs stable markup in the templates, handling of media URLs and AV tags, and MathJax only if the dedicated types use math. This is framework-independent.
- **TypeScript**: the repo already uses TypeScript (`package.json`) and Tailwind 4 + daisyUI 5 (`shell_src/app.css`). The design tokens in the mockups are plain CSS variables, so they can be ported to any option.
- **Build**: a static client could be served by FastAPI (`StaticFiles` is already mounted in `app.py`) or hosted separately; separate hosting needs CORS and a decision on cookie versus key auth.
- **Offline**: not a goal. The collection and scheduler live on the server (`RESEARCH-pwa.md` §5), so the PWA is an installable online client. That removes the main argument for a separate static SPA with its own data store, and makes Jinja + Datastar a valid choice.

**Conclusion on frameworks:** with offline out of scope and dedicated note types without CSS/JS, **Jinja + Datastar is a viable and the lowest-change option**: a new study route would return the card region as an HTML fragment (SSE `patch_elements`) and take the rating as a Datastar action, both on top of `get_queued_cards`, `card.question()/answer()` and `answer_card`. This is an [INFERENCE] from the repo's existing pattern (`overview.py`, `fields.py`); I did not prototype it. A separate SPA (Svelte, Solid, Preact) remains an option if the client should be usable without the Jinja shell or hosted on another origin. Criteria that decide it: whether a second codebase is wanted, tolerance for round-trip latency on mobile networks, and team familiarity (not known to me). No evidence here separates the SPA candidates from each other.

## 7. Other things an independent client needs (not investigated in depth)

- **Auth**: choose between reusing the web session cookie, the AnkiConnect `X-API-Key`, or a new token. HTTPS requirements are in `RESEARCH-pwa.md`.
- **CORS**: see §3. The default origin list is `["http://localhost"]`; a client on another origin must be added to `webCorsOriginList` (or `"*"`, which weakens protection).
- **Localization**: the UI strings come from `tr.*` in the server (`reviewer.py` `_ease_names`, button labels). A separate client needs its own i18n or an endpoint exposing labels. **ungeprüft.**
- **Sync**: out of scope by design (`README.md`). The client uses this single-user server's API and does not need the Anki sync protocol (rslib), which exists for Anki clients syncing a collection. A search summary notes that third-party sync servers lag behind protocol changes; that does not affect an API-based client and no further conclusion was drawn.
- **Version pin**: the `anki` package, vendored frontend and buildhash must match (`UPSTREAM.md`). A new API built on `anki.sched` should be re-verified when the pin is bumped.

## 8. Open questions

- ~~What `cardsInfo` returns~~ **Answered by test:** `question`, `answer`, `css`, `nextReviews` (the four interval labels, e.g. `<1 Min.`, `<6 Min.`, `<10 Min.`, `4 Tg.`), `queue`, `type`, `interval`, `reps`, `fields`. No separate AV-tag list was returned; whether AV tags appear is untested because the dedicated type has no audio.
- `getDeckStats` returns `new_count`, `learn_count`, `review_count`, `total_in_deck` per deck (tested on a 3-card deck). Whether the counts match `deck_due_tree()` and the deck browser for a real collection is **still untested**.
- Whether scheduling states re-fetched per card are equivalent to the queue's states. (The spike avoided this by holding the queue head's states in server memory; §11.)
- `undo` and flag/bury/mark without a GUI are **untested**. `addNote`, `createModel`, `answerCards`, `findCards`, `areDue`, `modelStyling` and `deleteDecks` worked without a browser reviewer. `guiCurrentCard` failed with "Gui review is not currently active", as read in the code.
- Whether the dedicated types need cloze, type-in-answer or audio, and how the client renders them (§3a).
- How existing cards of other note types are handled (§3a point 2) and whether queue counts stay correct when decks mix types (§3a point 3).
- How MathJax is typeset, if the dedicated types use math at all.
- Security: exposing a new JSON API and CORS alongside the existing DNS-rebinding Host guard.

## 9. Suggested next step if pursued

**Done as a throwaway spike, see §11.** The queue-head endpoint and an answer endpoint work against a throwaway collection. Still open: rendering the response in a browser, media, AV tags and MathJax.

## 10. Test run (throwaway server)

**Setup:** `ANKIWEB_COLLECTION`, `HOME`, `XDG_DATA_HOME` pointed at a temporary directory, web port 18000 and AnkiConnect port 18765, so the user's collection was never touched. The server, the temporary directory and the helper file were removed afterwards.

| Check | Result |
|---|---|
| `createModel` for `AnkiWeb Vocab` (4 fields, 1 template, `css=""`) | accepted; fields, styling and templates read back as sent |
| Rendered HTML with empty Hint/Example | conditional elements omitted |
| Rendered HTML with Hint and Example | both elements present; `*word*` unchanged |
| Raw `<` and `&` stored as typed | **finding:** returned unescaped. This shows the server does not escape; it is the reason the view must escape on save. It is **not** a pass for the view, which does not exist yet |
| `css` in `cardsInfo` / `<style>` in `question` | **finding:** `css` is `""`, but an empty `<style></style>` is still prepended. The templates and type carry no styling; the render output is not free of the tag |
| `addNote` empty note / duplicate | both rejected with a message |
| `cardsInfo.nextReviews` | four labels per card, no GUI needed |
| `answerCards` (ease 3) | worked; card moved to learning (`queue 1`, `type 1`, `reps 1`) |
| `getDeckStats` | `new_count 3`, `learn_count 0`, `review_count 0`, `total_in_deck 3` |
| `guiCurrentCard` with no reviewer | error "Gui review is not currently active" |
| `deleteModel` with notes / after `deleteDecks` | refused ("3 note(s) still use it") / `true`; type gone from `modelNames` |

**Not tested in this run:** next card in queue order with counts (covered by the spike in §11), media, AV tags, MathJax, rendering in a browser, a quick-add view that escapes on save (none exists), and any non-German collection data. The time-taken question was **measured in §11**.

## 11. Spike: study JSON API (throwaway server, code not kept in the server)

**What was built:** a temporary router (`GET /api/study/next?deck=`, `POST /api/study/answer`) that reuses the native reviewer's own functions `load_question`, `render_answer` and `answer_current` (`http_screens/reviewer.py`) with one `ReviewerSession` held in memory, and returns JSON. **Design flaw in the spike:** `next` was a `GET` although `load_question` starts the timer and writes the session, so it changes state. A real endpoint must be a `POST` (or another clearly stateful call), with a separate side-effect-free peek if one is needed (§5). The router had to be mounted **before** the media router, which is a `/{path}` catch-all (`app.py`), and it was mounted unconditionally during the test only. Afterwards it was **removed from the server code** (`app.py` restored via `git checkout`, new package deleted; a search of `ankiweb/` finds no trace), so no study endpoint runs on a real port. The code is archived as `study-api-spike.py` in this folder and is not imported anywhere. A real version must not mount a writing route without an explicit switch. It is a spike, not a design.

**Setup:** same isolation as §10 (own collection, `HOME`, `XDG_DATA_HOME`, ports 18100 and 18865); server, data and files removed afterwards.

| Check | Result |
|---|---|
| `GET /next?deck=` | queue head with `cardId`, `question`, `answer`, four `labels`, `counts` (`new`, `learning`, `review`) in one call, status 200 |
| Study loop, 10 answers with mixed ratings on 5 new cards | new cards in creation order; a card rated Again or Hard returned later; `new` fell 5 to 0, `learning` rose to 4 then fell to 1; labels changed with the card's state |
| Counts after the loop vs `getDeckStats` | both `learn_count`/`learning` 1, `new` 0, `review` 0 |
| Queue-head labels vs `cardsInfo.nextReviews` (one card in learning) | identical |
| Wrong card id / `ease` 0 or 5 / unknown deck | 409 / 422 / 404; the card in flight stayed the same |
| Recorded answer time, 3000 ms of reading | spike path **3013 ms**; `answerCards` after `/next` **0 ms** |
| `guiCurrentCard` with no reviewer | still fails ("Gui review is not currently active") |

**What this establishes:** the queue gap from §3 can be closed with a small server router built on existing functions; no scheduler logic had to be reimplemented. The recorded answer time is correct only when the timer starts when the question is loaded, as `load_question` does; plain `answerCards` loses it.

**Limits (do not over-read):**
- Five new cards in a fresh collection, one deck, one note type. Review cards due on later days, daily limits, burying, siblings, filtered decks and FSRS were **not** exercised.
- The label comparison covers **one** card in the learning state, not every state.
- `counts` come from `col.sched.counts(card)`, which in this `anki` version ignores its argument and calls `get_queued_cards()` again (read in `anki/scheduler/v3.py`). Each `/next` therefore fetches the queue twice. Harmless here; a real endpoint should read the counts from the same response as the card.
- One in-flight card per process: two clients or two tabs would overwrite each other's card. The 409 check rejects a stale answer but does not make parallel use work.
- `/next` called twice for the same card **restarts the timer** (`load_question` calls `start_timer()`), so a page reload resets the measured reading time. Read from the code, not tested. This is why `next` must not be a `GET`: a prefetch, a retry or a browser reload would silently change the recorded time.
- No browser rendering, no authentication, no media, no AV tags, no MathJax.
- Strings such as `<⁨1⁩ Min.` contain Unicode isolation marks (U+2068/U+2069) and a no-break space; a client should expect them.
