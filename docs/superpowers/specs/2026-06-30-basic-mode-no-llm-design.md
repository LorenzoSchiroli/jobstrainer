# Basic Mode: Non-LLM Query Parsing

**Date:** 2026-06-30
**Status:** Approved (design)

## Goal

Remove the LLM from basic search mode. Basic search must be fast, free, reliable
(no Groq dependency, no JSON-parse failure path), and deliberately "dumber" than
advanced mode. CV-aware retrieval becomes an advanced-mode-only advantage.

Advanced mode is **unchanged** — it keeps the LLM (`extract_filters`, clarify,
critique, fit-score, preference memory).

## Background: how basic mode uses the CV today

The CV is never used directly in retrieval — it is never embedded, stored as a
vector, or sent to OpenSearch. Its only role is as **context for the LLM** in
`extract_filters`:

- `routers/search.py` → `extract_filters(groq_client, profile.cv_text, body.query)`
- `query_understanding.py` → user message = `f"CV:\n{cv_text}\n\nSearch query:\n{query}"`

From that context the CV influences results two ways:

1. **Shapes `semantic_query` (primary).** The LLM produces a "keyword-rich string
   combining CV skills and job intent" — e.g. CV full of PyTorch/NLP + query
   "engineer" → `"machine learning engineer pytorch nlp ..."`. Only this string
   is embedded (`biencoder.encode(filters.semantic_query)`) and used for BM25 +
   rerank. The raw CV text plays no further part.
2. **May leak into inferred filters.** Because the whole CV is in the prompt, the
   LLM may set fields the query never stated (e.g. `seniority` from experience,
   `country` from CV location, `languages_required`).

**Net effect of going non-LLM:** basic mode loses CV-driven query expansion and
CV-inferred filters. A bare query like "engineer" stays "engineer" instead of
becoming "ML engineer pytorch...". Retrieval mechanics (hybrid BM25 + k-NN +
rerank) are unchanged; only the query text feeding them gets simpler. This is the
intended tier split.

## Architecture

- **New module** `backend/backend/search/query_parsing.py` with one pure
  function: `parse_query(query: str) -> SearchFilters`. Deterministic, no I/O, no
  LLM, no CV.
- **`query_understanding.py` is untouched** — advanced mode keeps using
  `extract_filters`. This is the tier split.
- **`routers/search.py`** swaps `extract_filters(groq_client, cv_text, query)` →
  `parse_query(body.query)` and drops the `groq_client` dependency.
- **`SearchFilters`** schema is unchanged; basic mode leaves inferred fields
  `null`.

## What `parse_query` does

Single pass over the query, in order:

1. **Detect + extract control tokens**, setting filter fields:
   - `strict` ← "strictly" / "exact" / "only" / "no exceptions"
   - `max_age_hours` ← "last/past N hours/days/weeks" (e.g. "last 3 days" → 72)
   - `location_type` ← remote / hybrid / on-site / "on site"
   - `employment_type` ← full-time / part-time / contract / internship / stage /
     freelance
   - `seniority` ← junior / mid / senior / lead / principal / staff / director
   - `languages_required` ← "in English", "German-speaking", … matched against a
     known-language list
   - `is_startup` ← "startup" (negation "no startup" → `false`)
   - `is_consulting` ← "consulting" (negation "no consulting" → `false`)
   - `country` ← tokens matched against a known-country list
   - `min_financial_health_score` / `min_review_score` ← **explicit phrasing
     only** (e.g. "financial health above 7"); otherwise `null`
2. **Strip** matched control tokens from the query string (conservatively — see
   below).
3. The cleaned remainder becomes `semantic_query`. It still carries free-form
   content like "fintech" or "python developer", so industry/skills are handled
   naturally by the hybrid pipeline — **industry is never a structured filter in
   basic mode.**
4. **Empty-result guard:** if stripping leaves the query blank, fall back to the
   original raw query as `semantic_query` (never embed an empty string).

## Parsing robustness

The parser is intentionally powerful, not naive substring matching. Techniques:

- **Word-boundary regex** (`\bremote\b`), never raw `in` substring checks, so
  content words don't false-trigger ("remotely", "delivery").
- **Lexicons with synonyms / abbreviations** per filter:
  - location_type: remote ← "wfh", "work from home"; on-site ← "on site", "onsite".
  - employment_type: internship ← "intern"; freelance ← "freelancer", "contractor";
    contract ← "contract".
  - seniority: "sr."→senior, "jr."→junior, "entry-level"→junior, "mid-level"→mid.
- **Negation detection** via preceding tokens: "no / not / without / non- /
  excluding startup" → `is_startup=false`.
- **Number-word + unit normalization** for time: digits and spelled numbers
  ("last three weeks", "past 48 hours", "within 2 days"), plus relative phrases
  ("today" → 24, "yesterday" → 48, "this week" → 168).
- **Multi-word matching** for countries ("United Kingdom", "United States") and
  languages ("German-speaking", "fluent in French", "English and German" → list).
- **Operator-aware numeric thresholds:** "financial health ≥ 7 / above 7 / at
  least 7 / minimum 7".

### Conservative stripping (precision vs. recall)

Some keywords are also legitimate content words ("contract" in "contract law",
"stage", "lead", "staff"). Because non-strict filters are applied as **soft
boosts** (not hard filters), the parser favors precision of the content query:

- **Unambiguous control phrases are stripped** from `semantic_query`: time
  windows, "strictly", "remote"/"wfh", "hybrid", "on-site", explicit
  language/country phrases, explicit numeric-threshold phrases.
- **Ambiguous content-ish words are NOT stripped**: they set the filter boost but
  stay in `semantic_query` (e.g. "contract law" → `employment_type=contract` boost
  AND `semantic_query="contract law"`). This gets the boost without amputating
  the content search.
- Each lexicon entry is tagged `strip` or `keep` to encode this distinction; the
  default for content-noun-collision-prone terms is `keep`.

### Worked example

Input: `"senior remote python developer at a startup, last 3 days, strictly"`

Output:
- `seniority = "senior"`
- `location_type = "remote"`
- `is_startup = true`
- `max_age_hours = 72`
- `strict = true`
- `semantic_query ≈ "python developer"` (control tokens removed; incidental
  filler like "at a" may remain — embedding/BM25 are robust to it)

## Filters NOT extracted in basic mode

Left `null` (advanced-mode only): `industry` (flows through hybrid search instead),
and the numeric score thresholds unless explicitly phrased. CV-inferred values for
any field are gone by design.

## Behavior change: CV no longer required

Basic mode currently returns HTTP 400 ("No CV uploaded") when the user has no CV.
Since basic no longer uses the CV, **drop that requirement** — basic search works
with no CV. Advanced mode still requires a CV.

## CV management moves into the sidebar

Today the only place to manage a CV is the standalone `/cv` page, which also acts
as a forced onboarding gate (`Login.tsx` redirects new users to `/cv` when
`has_cv` is false; the page's "Go to Search →" button is disabled until a CV
exists). With basic mode no longer needing a CV, that forced gate is pointless
friction. CV management moves into the sidebar so it is always reachable
regardless of mode, and the standalone page is removed.

Backend is unchanged here — `GET/POST /users/cv` and `ApplicantProfile` stay as
is; this is a frontend consolidation reusing `api/cv.ts`.

- **New CV section in `Sidebar.tsx`** (mirrors the existing "Preferences (learned)"
  box):
  - On mount, `getCV()` → show status: `CV loaded (N chars)` or `No CV`.
  - **Upload / Replace** control reusing `uploadCV(file)` (file picker;
    `.pdf/.docx/.txt`), with uploading + error states.
  - Collapsible **View** toggle showing `cv_text` in a read-only textarea.
- **`Login.tsx`** always redirects to `/search` (drop the
  `has_cv ? '/search' : '/cv'` branch).
- **Remove** the standalone CV page: delete `pages/CV.tsx`, its route in
  `App.tsx`, and the `CV` nav link in `Sidebar.tsx`. The sidebar becomes the
  single place to manage the CV.

### Collapsible sidebar

The sidebar is currently a fixed, always-visible 240px column (`AppLayout.tsx`
renders it inline in a flex row). Make it a classic open/close side panel:

- **Toggle state** lives in a small `localStorage`-backed hook
  `useSidebarOpen` (mirrors `useSearchMode`): key `sidebar_open`, default open.
- **Toggle button** (hamburger ☰) always visible: in the sidebar header when
  open; as a floating button in the top-left of `<main>` when closed.
- **Open/close behavior:** when closed the panel collapses (slide out /
  `width: 0`) and `<main>` takes the full width; a short CSS transition for the
  slide. State persists across reloads via the hook.

## Testing

Going non-LLM makes basic mode fully deterministic and unit-testable — a key win.

- **New** `tests/search/test_query_parsing.py`: table-driven cases for each filter,
  synonyms/abbreviations ("wfh", "sr.", "intern"), negations ("no startup", "not
  remote"), spelled-number + relative time windows ("last three weeks", "today"),
  multi-word countries/languages, operator-aware numeric thresholds, multi-filter
  queries, the empty-result guard, and queries with no filters at all.
- **Precision cases:** ambiguous content words must NOT be amputated —
  e.g. "contract law" keeps `semantic_query="contract law"` while still setting the
  `employment_type=contract` boost; "remotely" must not trigger `location_type`.
- **Update** `tests/` for the basic search endpoint: no longer mock the Groq
  client; assert the endpoint works without an uploaded CV.
- Existing `tests/search/test_filters.py` (clause building) is unaffected —
  `SearchFilters` and `build_clauses` don't change.
- **Frontend** changes (sidebar CV section, login redirect, page removal) are
  verified manually: upload/view a CV from the sidebar, basic search with no CV,
  advanced still prompts for a CV via the sidebar.

## Out of scope

- Any change to advanced mode.
- Any change to ingestion (LLM extraction of `is_consulting`, `industry`, etc. on
  ingest stays).
- Any change to retrieval/rerank mechanics or the `SearchFilters` schema.
