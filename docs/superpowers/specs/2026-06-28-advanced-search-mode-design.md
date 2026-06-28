# Advanced Search Mode — Design

Date: 2026-06-28

## 1. Overview & scope

Add a second **Advanced** search mode alongside the current one-shot **Basic** search.
Basic search (`POST /jobs/search`) is unchanged. Advanced mode is a LangGraph-orchestrated
flow with human-in-the-loop clarification, one bounded auto-refine pass, per-result fit
evaluation, and an editable per-user preference memory distilled from past searches.

Advanced flow, end to end:

1. **Clarify** — an LLM inspects query + CV + preference memory and asks the user 1-2 short
   clarifying questions. The graph pauses here via LangGraph `interrupt` (two-call round-trip).
2. **Search + auto-refine** — extract filters → hybrid retrieve → rerank; an LLM critiques the
   result set and performs **at most one** refine-and-re-search pass if the results are weak
   ("very few steps").
3. **Fit evaluation** — for the top results, an LLM produces a **fit score (0-100) + short
   rationale + gaps** per job, using CV + preference memory; results are re-sorted by fit score.
4. **Memory distill** — after the session completes, an LLM updates the user's **editable
   preference memory** from this session's query / filters / clarify answers.

A new persistent left **sidebar** carries the Basic/Advanced toggle, user identity + logout,
nav (Search / CV), and the editable preference-memory view.

## 2. Data model changes

One new table (Alembic migration in `backend/alembic/`):

- **`preference_memory`** — one row per user:
  - `id` (UUID, PK)
  - `user_id` (UUID, FK → `users.id`, `ondelete=CASCADE`, unique)
  - `memory_text` (Text) — the LLM-summarized preference blob
  - `user_edited` (Boolean, default false) — when true, the distill step treats the existing
    text as authoritative and only appends new signals rather than rewriting it
  - `created_at`, `updated_at` (timezone-aware, server defaults like other models)

LangGraph checkpoint state is persisted via **`AsyncPostgresSaver`**
(`langgraph-checkpoint-postgres`) keyed by `thread_id`, so the graph can pause at the clarify
interrupt and resume on the second call across restarts/workers. Dev/test fallback:
`MemorySaver`. The checkpointer owns its own tables; we do not model session rows ourselves.

> Note: a `search_session` table was considered and deliberately dropped. The distill step is
> incremental (current memory + just-completed session → new memory), so raw past sessions never
> need to be re-read, and `thread_id` for resume is already held by the checkpointer. It would be
> a write-only log nothing consumes (YAGNI).

## 3. Backend — LangGraph flow & API

New package: `backend/backend/search/advanced/`.

### Graph

A LangGraph `StateGraph` whose state is roughly:

```
{
  cv_text, query,
  preference_memory,
  clarify_questions, clarify_answers,
  filters, hits,
  refined_once: bool,
  results,            # fit-scored
}
```

Nodes are plain async functions. We keep calling the **Groq SDK directly** inside nodes and
reuse the existing `extract_filters`, `hybrid_retrieve`, and `rerank` functions — LangGraph
does not require LangChain model wrappers.

Node/edge flow:

```
clarify → interrupt → extract_filters → retrieve → rerank → critique
   → (conditional edge) ── weak & not refined_once ──→ retrieve   (one re-search, sets refined_once)
   → (conditional edge) ── otherwise ────────────────→ fit_score → END
```

- `clarify` — LLM proposes 1-2 clarifying questions from query + CV + preference memory.
- `interrupt` — graph pauses; questions surface to the client.
- `extract_filters` — reuse `search/query_understanding.py`, now also conditioned on clarify
  answers + preference memory.
- `retrieve` / `rerank` — reuse `search/retrieval.py` and `search/reranker.py`.
- `critique` — LLM judges result-set quality; may rewrite the semantic query/filters once.
- `fit_score` — LLM scores top results: `fit_score` (0-100), `fit_rationale`, `fit_gaps`.

### Endpoints

Added to the search router; Basic `/jobs/search` is untouched.

- `POST /jobs/search/advanced`
  - body: `{ query }`
  - runs the graph to the clarify interrupt
  - returns: `{ thread_id, clarify_questions: string[] }`
- `POST /jobs/search/advanced/resume`
  - body: `{ thread_id, clarify_answers: string[] }`
  - resumes the graph from the interrupt to completion
  - returns: fit-scored `JobSearchResponse[]`, each extended with
    `fit_score`, `fit_rationale`, `fit_gaps`

Reuses `ApplicantProfile.cv_text` and the same biencoder / reranker / opensearch / current-user
dependencies as Basic. Requires a CV uploaded (same 400 as Basic).

## 4. Backend — preference memory lifecycle

New module `backend/backend/search/advanced/preference_memory.py` (or sibling):

- `get_memory(session, user) -> str | None`
- `set_memory(session, user, text)` — user edit; sets `user_edited = True`
- `update_memory_from_session(session, user, query, filters, clarify_qa)` — the distill step

Distill runs **after `resume` completes**, as a non-blocking step (does not delay the response).
It feeds **current memory + this session** (query, final filters, clarify Q&A) into an LLM to
produce the updated blob. When `user_edited` is true, the prompt is instructed to preserve the
user's statements and only append newly observed signals.

Endpoints (new small router, e.g. `/me`):

- `GET /me/preference-memory` → `{ memory_text, user_edited }`
- `PUT /me/preference-memory` → body `{ memory_text }`; sets editable text, `user_edited = True`

## 5. Frontend — sidebar, modes, clarify UX

- **`components/Sidebar.tsx`** — new persistent left sidebar wrapping authenticated routes:
  - username + logout (moved out of the inline link at the bottom of Search)
  - nav links: Search / CV
  - **Basic / Advanced toggle**, persisted in `localStorage`
  - editable **preference-memory** textarea; Save → `PUT /me/preference-memory`,
    loaded via `GET /me/preference-memory`
- **`pages/Search.tsx`** — when Advanced is on:
  - submit calls `POST /jobs/search/advanced`, stores `thread_id`, renders the clarify
    questions inline as a simple form
  - answering calls `POST /jobs/search/advanced/resume` and renders fit-scored cards
  - Basic path (current behavior) unchanged when the toggle is off
- **`components/JobCard.tsx`** — in advanced results, show a fit-score badge + rationale + gaps.
- **`api/search.ts`** — add `searchAdvanced(query)`, `resumeAdvanced(threadId, answers)`, and the
  extended `Job` fit fields; new `api/preferences.ts` for the memory endpoints.

## 6. Testing

Match existing test conventions (Groq, OpenSearch, and ML models mocked; live Postgres test DB):

- Graph nodes unit-tested with mocked Groq/OpenSearch.
- Clarify → resume round-trip (interrupt fires, resume returns fit-scored results).
- `critique` triggers at most one re-search (`refined_once` guard holds).
- Memory distill respects `user_edited` (does not overwrite user statements).
- New endpoints: advanced, resume, GET/PUT preference-memory (auth + missing-CV paths).
- Frontend: sidebar toggle persists; advanced submit renders clarify form then fit-scored cards.

## 7. Out of scope (YAGNI)

- Streaming / SSE / WebSocket progress (two-call round-trip only).
- Thumbs-up/down or saved/dismissed feedback learning.
- Explicit preference toggles (preferences are LLM-summarized + user-editable text only).
- Multi-facet sub-query decomposition.
- More than one auto-refine pass.
- A `search_session` audit table.
