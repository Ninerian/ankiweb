# Research: Free Enrichment Sources for Hint and Example Sentence

**Question**: Is there a public-domain enrichment service that fills the card's **Hint** and **Example sentence** from Front/Back?
**Scope**: research only, no code in the project changed.
**Context**: Card model `{ front, hint?, back, example? }` (see `DESIGN.md` §5).

---

## 1. Short answer

No single free service that returns both fields from a front/back pair was found. Free data sources exist that can be combined. Only one is true public domain (CC0), and it covers the hint only.

Status: **probably feasible; works for common German nouns in a 10-word sample; coverage for a full vocabulary is not proven.**

## 2. Sources compared

| Source | Provides | License | Access | Fit |
|---|---|---|---|---|
| Wikidata Lexemes | part of speech, grammatical gender, word forms incl. plural | **CC0** (public domain) | SPARQL, Wikidata Query Service | Hint: yes. Example sentences: no |
| Wiktionary via kaikki.org (Wiktextract) | `pos`, `forms`, partly examples | CC BY-SA | JSON Lines downloads per language | Hint and examples, but Share-Alike |
| Tatoeba | example sentences with translations | CC BY 2.0 FR (attribution required) | REST API (`api.tatoeba.org`) or download | Example sentences, with translation |
| tatoeba-to-anki (GitHub) | Anki cards from Tatoeba, dictionary on the back | open source | standalone tool | Shows the combination works; not an API service |

Notes from the sources (not independently verified beyond the probe in §4):
- Tatoeba's API returns `textLicence` per sentence (`CC BY 2.0 FR`). Terms of use: the only restriction is attribution; the reuser must circulate the sentence with its licence. Audio is licensed separately.
- Wiktextract data has no dedicated `gender` field per the sources consulted; gender would have to be derived from `forms`/tags. Not tested.
- No source describes a ready-made query returning part of speech, gender and plural together for German lexemes.

## 3. Licence consequences for the design

- **Wikidata (CC0)**: no obligations. Cleanest source for the hint (`Noun, feminine (Plural: ...)`).
- **Tatoeba (CC BY)**: the author must be credited. If a suggested example sentence is stored, the source (sentence id / author / licence) must be stored and shown too. The card model has **no field for this today**.
- **Wiktionary (CC BY-SA)**: Share-Alike may apply to derived data collections. Whether copying a single entry into a card triggers it is a legal question not answered here; clarify before using it.

## 4. Probe: 10 German words (read-only)

Queried Wikidata (SPARQL, German lexemes by lemma) and Tatoeba (`from=deu`, `to=eng`) from a browser context. Words: Sehnsucht, Tisch, Schadenfreude, Fernweh, Haus, laufen, schnell, Fingerspitzengefühl, Mädchen, Bank.

### Wikidata (hint)
- 10 of 10 words found, all with part of speech.
- All 7 nouns had gender (`f`/`m`/`n`) and a forms list including plural. Example: `Sehnsucht` -> noun, `f`, plural `Sehnsüchte`.
- Verb (`laufen`) and adjective (`schnell`) returned an unlabelled list of forms and no gender. A hint like "strong verb, lief, gelaufen" would need extra logic.
- `Bank` returned two nouns with different plurals (`Bänke` / `Banken`). The user must pick the meaning; it cannot be derived from the back ("bench") automatically.

### Tatoeba (example sentence)
- All 10 words returned at least one sentence. Each result had licence field, author and a translation.
- Hit counts vary widely: `Fernweh` 1, `Fingerspitzengefühl` 1, `Schadenfreude` 6, `Sehnsucht` 20, `Bank` 501, `Tisch`/`Haus`/`laufen`/`schnell`/`Mädchen` capped at 1000.
- First hit is often poor: `Haus!`, `Zu Tisch!`, `Lauft!`, `Schnell!`; for `Fingerspitzengefühl` a long dialogue of about 150 characters. Usable suggestions need filtering (length, relevance).

## 5. Limits and open questions

- Sample is 10 words, mostly nouns. This shows the approach works; it does not prove coverage for a whole vocabulary.
- Not tested: whether a sentence matches an inflected form (`Sehnsüchte`), needed for the `*word*` highlight in `example`.
- CORS worked from the browser context used. Not tested from `file://`, a real domain, or under load. Wikidata Query Service rate limits not checked.
- Gender derivation from Wiktextract tags/head templates not tested.
- Legal reading of CC BY-SA for card content not clarified.

## 6. Options if pursued

1. **Suggest, never auto-fill**: a "Suggest" button in the editor step 2 fetches a hint (Wikidata) and example candidates (Tatoeba); the user picks or edits. Needed because of ambiguity (`Bank`) and weak first hits.
2. **Store attribution**: extend the card model with a source field for Tatoeba sentences (id, author, licence) and display it.
3. **Sentence filter**: test length and match-in-base-form rules on a larger word list before building UI.
4. **Verbs/adjectives**: decide whether the hint is limited to nouns first.

The research steps themselves (web searches and the read-only probe) did not modify any file. The mockups (`mockup.html`, `editor-mockup.html`, `decks-mockup.html`, `card-render.js`, `DESIGN.md`) were changed earlier in the same session by the four-field editor work (Hint / Example), not by this research.

---

## 7. Python libraries and datasets (multilingual)

No library was found that returns hint and example sentence from a front/back pair. The pieces below would have to be combined. **Nothing here was installed or run**; entries come from search summaries and two pages read directly (HF dataset card, Tatoeba corpus page).

Legend: **belegt** = stated by a source I read or a search result; **ungeprüft** = not stated, or not tested.

### 7.1 Dictionary data (hint: part of speech, gender, plural)

| Component | Multilingual | Provides | Licence | Notes |
|---|---|---|---|---|
| wiktextract (Python, GitHub) | belegt: all Wiktionary languages, several editions (`--edition`) | `pos`, `forms`, examples, translations | data CC BY-SA (belegt) | Parses Wiktionary **dumps offline**; not a live lookup service. Installation shown from the repo (`git clone` + `pip install -e .`); **being a pip package is ungeprüft**. Gender as a field: ungeprüft |
| kaikki.org (ready-made wiktextract output) | belegt: downloads per language | same data as wiktextract | CC BY-SA (belegt) | Large files; a lookup must be built on top |
| Wikidata Lexemes | belegt: many languages; only German probed | part of speech, gender (P5185), forms | CC0 (belegt) | Probe worked with plain SPARQL over HTTP. WikibaseIntegrator, tfsl, LexData are named as tools for **editing** lexemes; LexData is stated inactive; maintenance of the others ungeprüft; reading support ungeprüft |
| Scribe-Data (CLI) | belegt per search: e.g. German nouns, French verbs | lexicographical data packs from Wikidata | ungeprüft | Maturity and licence ungeprüft |

### 7.2 Example sentences

| Component | Multilingual | Licence | Per-sentence author/licence | Access |
|---|---|---|---|---|
| Tatoeba REST API | belegt: 400+ languages (Wikipedia result) | CC BY 2.0 FR (belegt) | **belegt**: probe returned `user` and `license` per sentence | HTTP; no pip client found |
| Hugging Face `Helsinki-NLP/tatoeba` | belegt: 359 languages, 3,403 bitexts | `cc-by-2.0` on dataset level (belegt) | **belegt: not available.** Features are only `id` and `translation`; the card's Data Fields section is empty | `load_dataset("tatoeba", lang1=..., lang2=...)` |
| Helsinki-NLP/Tatoeba-Challenge | belegt: language pairs as files | ungeprüft | ungeprüft | files on GitHub |

Consequence: the HF dataset is suited for bulk access but **cannot provide the per-sentence attribution** CC BY requires. Attribution needs the REST API or Tatoeba's own downloads (fields in the downloads not checked).

### 7.3 NLP tools (lemma, part of speech, morphology)

| Library | Languages | Provides | Licence | Notes |
|---|---|---|---|---|
| Simplemma | belegt: 54 partly or fully supported | lemmatization only | ungeprüft | pure Python, no dependencies (belegt). No gender or part of speech |
| Stanza | counts conflict between sources (80 vs 66); likely version difference | part of speech, lemma, UD features such as Gender and Number (belegt) | **ungeprüft** (the source does not state it) | |
| spaCy | per-language pipelines; list not seen | morphology (gender, number), lemmatizer (belegt) | trained pipelines MIT (belegt per search); library licence not checked | |

These work on running text, so for a single word without context they are less reliable than a dictionary entry. A fitting use is matching a Tatoeba sentence to the word in an inflected form (for the `*word*` highlight). Whether Simplemma covers all German inflections is ungeprüft.

### 7.4 Still open

- Quality and coverage for languages other than German (only German was probed).
- Whether Tatoeba's own bulk downloads include author per sentence.
- Licences of Stanza, Tatoeba-Challenge data and Scribe-Data.
- Gender derivation from wiktextract tags.
