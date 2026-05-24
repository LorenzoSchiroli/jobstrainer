# Design: Move strict mode from UI checkbox to LLM-inferred filter

**Date:** 2026-05-24

## Goal

Remove the manual "Strict mode" checkbox from the frontend. Instead, let the user express strict intent in natural language (e.g. "only remote", "strictly senior roles", "exact match"). The LLM detects this and sets `strict: true` inside `SearchFilters`, alongside all other LLM-extracted filters. If not explicitly requested, `strict` is always `false`.

## Changes

### `backend/backend/search/filters.py`

- Add `strict: bool = False` to `SearchFilters`.
- Remove the `strict` parameter from `build_clauses(filters, strict)` → `build_clauses(filters)`.
- `build_clauses` reads `filters.strict` internally.

### `backend/backend/search/query_understanding.py`

- Add `strict` to `_SYSTEM_PROMPT`:
  ```
  "strict": false — set to true ONLY when the user explicitly requests strict/exact/no-miss matching (e.g. "strictly", "only", "exact", "no exceptions"). Default false.
  ```

### `backend/backend/search/retrieval.py`

- Remove `strict: bool = False` param from `build_hybrid_query` and `hybrid_retrieve`.
- Both functions read `filters.strict` directly from the `SearchFilters` argument.

### `backend/backend/routers/search.py`

- Remove `strict: bool = False` from `SearchRequest` (becomes `query: str` only).
- Update `hybrid_retrieve` call — no longer passes `strict` separately.

### `frontend/src/api/search.ts`

- Remove `strict` param from `searchJobs`. API call becomes `{ query }` only.

### `frontend/src/pages/Search.tsx`

- Remove `strict` state and the checkbox `<label>` block.
- Update `handleSearch` to call `searchJobs(query)`.

## Invariants

- `strict` defaults to `false` at the `SearchFilters` model level — safe even if the LLM omits the field.
- The LLM prompt instructs the model to default to `false`; only explicit user phrasing triggers `true`.
- No other filter logic changes — the behavioral difference between strict/soft filtering stays identical.

## Tests to update

- `backend/tests/search/test_filters.py` — update `build_clauses` calls to remove the `strict` kwarg.
- `backend/tests/search/test_retrieval.py` — update `build_hybrid_query` / `hybrid_retrieve` calls; pass `strict` via `SearchFilters`.
