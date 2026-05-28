# Tailorer — Design Spec

**Date:** 2026-05-28  
**Status:** Approved

---

## Overview

Tailorer is an AI-powered job application agent integrated into the jobstrainer backend. It automates filling multi-page job application forms in the user's real browser, guided by a LangGraph state machine on the backend and controlled via a browser extension (Chrome + Firefox). The user confirms at each page boundary before the agent proceeds.

---

## Architecture

Four layers:

1. **Browser Extension** — the agent's "hands" in the user's browser. Inspects DOM, executes fill/click/navigate commands, shows the confirmation overlay.
2. **WebSocket layer** — real-time bidirectional JSON protocol between extension and backend agent.
3. **LangGraph Agent** (`backend/backend/tailorer/`) — the brain. Groq-powered state machine that navigates, tailors documents, maps fields, and waits for user approval.
4. **Postgres** — stores `applicant_profile`, `applications`, and LangGraph checkpoint state.

The agent is **agent-driven**: it sends commands to the extension, not the other way around. The extension is a pure executor.

---

## Entry Point / Session Activation

1. User clicks a job link in the jobstrainer frontend. Before `window.open()`, the frontend calls `chrome.runtime.sendMessage(EXTENSION_ID, { type: "tailorer_pending", job_id })` via the extension's `externally_connectable` manifest entry. The service worker stores `{ job_id }` keyed by opener tab ID.
2. Job board page opens in a new tab. The service worker detects it via `chrome.tabs.onCreated`, matches it to the stored `job_id`, and injects `overlay.js`.
3. A floating **"Apply with Agent"** button appears on the job board page.
4. User clicks it → extension opens WebSocket `GET /tailorer/ws/{job_id}?token=JWT` → agent starts. The backend sends a `session_started` message with the generated `thread_id`; the extension stores this for file download URLs.

The extension's `manifest.json` must declare `externally_connectable.matches` for the jobstrainer frontend origin (e.g. `http://localhost:3000/*` for dev, production origin for prod).

No button is added to the jobstrainer frontend itself.

---

## LangGraph State Machine

All nodes use **Groq** as the LLM provider via `langchain-groq` (`ChatGroq`). Model selection per node:

| Node | Model | Reason |
|------|-------|--------|
| `navigate_to_apply` | `GROQ_MODEL_BASE` | Navigation reasoning |
| `tailor_documents` | `GROQ_MODEL_LARGE` | Writing quality |
| `fill_page` | `GROQ_MODEL_BASE` | Field mapping |
| `confirm_with_user` | — | Interrupt, no LLM call |
| `navigate_next` | `GROQ_MODEL_BASE` | Button detection |
| `stuck_handler` | — | Pause, no LLM call |

### Nodes

**① navigate_to_apply**  
Always navigates via the company homepage (from `Company.website` in the DB). Never uses the job board URL as a shortcut — applying directly through the company's own careers page is intentional. Flow: homepage → careers page → matching job posting → apply form. Sends `navigate` commands to the extension. Max 2 retries, then transitions to `stuck_handler`.

**② tailor_documents**  
Runs once per session before the first page fill. Reads `Job.description` + `Job.summary` from the DB and `ApplicantProfile.cv_text`. Calls Groq (`GROQ_MODEL_LARGE`) to produce:
- Tailored CV (docx bytes) — same logic as the existing `tailor/cover_letter.py`
- Tailored cover letter (docx bytes + plain text)

Both are stored as bytes in LangGraph state (`cv_bytes`, `cl_bytes`) and persisted by `AsyncPostgresSaver` into Postgres. No filesystem dependency — files survive container restarts. The file download endpoint reads the bytes directly from the checkpointer state by `thread_id`.

**③ fill_page**  
Receives a `dom_snapshot` from the extension. The LLM maps each detected field to the best value from: `ApplicantProfile` fields, tailored document text, or `extra_qa` JSONB. Sends `fill_field`, `file_upload`, and `click` commands back. Fields the agent is uncertain about are flagged in the subsequent `show_confirm` message.

**⏸ confirm_with_user** *(LangGraph interrupt)*  
Sends `show_confirm` to the extension. The extension injects a fixed-position overlay banner at the bottom of the page: *"Filled N fields — ready to continue?"*. Uncertain fields are highlighted. Waits for one of:
- `user_approved` → transitions to `navigate_next`
- `user_correction` (natural language, e.g. "change years to 5+") → re-fills affected fields → re-confirms
- `user_manual_edit` (user typed directly in form) → updates state → re-confirms

**④ navigate_next**  
Clicks the "Next" or "Submit" button. Detects whether more pages remain or the application is complete. If more pages → back to `fill_page`. If done → `done` node.

**⚡ stuck (inline interrupt, not a separate node)**  
After 2 failed retries, any node calls `interrupt({"type": "stuck", "message": "..."})` directly. The WS layer surfaces this to the extension as `show_stuck`. When the user unblocks and the extension sends `stuck_unblocked`, the client resumes the graph with `Command(resume=stuck_unblocked_value)` and LangGraph re-executes the same node from the top (nodes must be idempotent for this reason). No separate `stuck_handler` node or `failed_node` state field is needed — this is the idiomatic LangGraph pattern for human-in-the-loop interrupts.

**✓ done**  
Inserts a row into `applications (user_id, job_id)` to record the completed application.

### LangGraph State Object

Persisted automatically by `AsyncPostgresSaver` (LangGraph's Postgres checkpointer):

```python
apply_url: str
current_page: int
filled_fields: dict[str, str]
cv_bytes: bytes       # tailored CV docx stored in LangGraph state (Postgres bytea via checkpointer)
cl_bytes: bytes       # tailored cover letter docx
cl_text: str          # plain text cover letter for text fields
retry_count: int
status: str           # navigating | filling | awaiting_user | stuck | done | failed
```

Files (CV, cover letter) are stored as bytes directly in LangGraph state, persisted by `AsyncPostgresSaver` into Postgres. This avoids filesystem dependency and survives container restarts. They are served via the file download endpoint, which reads them from the checkpointer state.

---

## WebSocket Protocol

**Endpoint:** `GET /tailorer/ws/{job_id}?token=JWT`

On connection: backend authenticates JWT, loads `Job` + `Company` + `ApplicantProfile`, generates a fresh `thread_id = UUID()`, starts the LangGraph agent under that thread.

All messages are JSON. Each message includes a `message_id` (UUID) for acknowledgment.

### Extension → Agent (inbound)

| type | fields | when |
|------|--------|------|
| `dom_snapshot` | `url`, `fields[]` (id, label, type, value, options), `buttons[]` | after each navigation |
| `user_approved` | — | user clicks "looks good, proceed" |
| `user_correction` | `text` | user types a natural language correction |
| `user_manual_edit` | `field_id`, `value` | extension detects user edited a field directly |
| `stuck_unblocked` | — | user manually unblocked the agent |

### Agent → Extension (outbound)

| type | fields | effect |
|------|--------|--------|
| `navigate` | `url` | extension navigates the tab |
| `fill_field` | `field_id`, `value` | extension sets field value |
| `click` | `selector` | extension clicks element |
| `file_upload` | `field_id`, `filename`, `download_url` | extension fetches file from backend, sets on input |
| `show_confirm` | `summary`, `uncertain_fields[]` | extension shows confirmation overlay |
| `show_stuck` | `message` | extension shows stuck overlay |
| `done` | `message` | extension shows success banner |

**File upload flow:** The agent sends a `file_upload` message with a `download_url` pointing to `GET /tailorer/files/{thread_id}/{type}?token=JWT`. The **service worker** (not the content script) fetches the file — this avoids CORS since the service worker has extension-level host permissions. It receives an `ArrayBuffer` (not Blob, which is not structured-cloneable across `chrome.runtime` in all browsers), sends it to the content script as `{ type: "do_file_upload", field_id, filename, buffer }`. The content script reconstructs a `File` object via `new File([buffer], filename)` and sets it on the input using `DataTransfer`.

**Auth:** JWT token passed as `?token=` query param on the WebSocket handshake. For the file download endpoint, the same JWT is passed as `?token=` query param. The endpoint is short-lived by design (only accessible while the WS session is active). The extension reconnects with exponential backoff on disconnect.

---

## DOM Inspection Strategy

The extension uses **DOM-based field discovery** (Approach A). For each page, `dom_inspector.js` scans for `<input>`, `<select>`, `<textarea>`, and file inputs. Labels are resolved via: `aria-label` → associated `<label for>` → `placeholder` → nearest preceding text node.

The structured snapshot is sent as `dom_snapshot`. This covers the majority of standard ATS platforms (Greenhouse, Lever, Ashby). Workday and other obfuscated platforms are out of scope for v1.

---

## Data Models

### Modified: `users`

`cv_text` column removed. The table becomes pure auth:

```
id, username, password_hash, created_at, updated_at
```

### New: `applicant_profile`

1:1 with `users` (UNIQUE on `user_id`). Holds all applicant data including the CV.

```
id             UUID PK DEFAULT gen_random_uuid()
user_id        FK → users ON DELETE CASCADE UNIQUE
first_name     TEXT
last_name      TEXT
email          TEXT
phone          TEXT
city           TEXT
country        TEXT
work_auth      TEXT                   -- e.g. "EU citizen, no sponsorship needed"
urls           JSONB                  -- {"linkedin": "…", "github": "…", "website": "…"}
extra_qa       JSONB                  -- {"notice_period": "2 weeks", "salary_expectation": "80k"}
cv_text        TEXT                   -- migrated from users.cv_text
created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
```

Managed via `PUT /tailorer/profile`. The existing `cv` router (`/users/cv`) is updated to read/write `applicant_profile.cv_text` instead of `user.cv_text`.

### New: `applications`

Junction table tracking which user applied to which job.

```
id          UUID PK DEFAULT gen_random_uuid()
user_id     FK → users ON DELETE CASCADE
job_id      FK → jobs ON DELETE CASCADE
applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
status      TEXT NOT NULL DEFAULT 'applied'   -- 'applied' | 'interviewing' | 'rejected' | 'offer'

UNIQUE (user_id, job_id)
```

UUID surrogate PK with a UNIQUE constraint (not composite PK) allows multiple application attempts per user+job in future. `status` is plain `TEXT` with a CHECK constraint rather than a Postgres ENUM — consistent with the project's existing pattern (`Job.employment_type`, `Job.seniority` are plain `Text`). Inserted by the agent's `done` node.

### Alembic Migrations

- `007_applicant_profile.py` — create `applicant_profile`, copy `users.cv_text` → `applicant_profile.cv_text`, drop `cv_text` from `users`
- `008_applications.py` — create `applications` junction table

**Migration 007 code call sites:** The following files all reference `User.cv_text` and must be updated in the same PR as migration 007:
- `backend/backend/routers/cv.py` — reads/writes `current_user.cv_text` directly
- `backend/backend/routers/auth.py` — may reference user fields
- `backend/backend/routers/search.py` — passes CV text to search
- `backend/backend/search/query_understanding.py` — uses CV text for query understanding

---

## Backend Module Layout

New module: `backend/backend/tailorer/`

```
__init__.py
models.py       -- ApplicantProfile, Application ORM models
schemas.py      -- Pydantic request/response schemas
agent.py        -- LangGraph graph definition (nodes + edges)
nodes.py        -- navigate_to_apply, tailor_documents, fill_page, confirm, stuck, done
tailor.py       -- CV + CL generation via Groq (logic lifted from tailor/cover_letter.py)
file_store.py   -- save tailored docs server-side, serve signed download URLs
router.py       -- REST endpoints + WebSocket endpoint
```

Registered in `backend/main.py` alongside existing routers.

### REST Endpoints

```
PUT  /tailorer/profile                    -- upsert applicant_profile for current user
GET  /tailorer/profile                    -- get current user's profile
GET  /tailorer/ws/{job_id}               -- WebSocket (token= query param); generates thread_id on connect
GET  /tailorer/files/{thread_id}/{type}  -- signed file download (cv | cover_letter)
```

---

## Browser Extension Layout

New package: `extension/` at project root. WebExtensions Manifest V3, targets Chrome + Firefox.

```
extension/
  manifest.json
  background/
    service_worker.js   -- manages WebSocket, routes messages via chrome.tabs.sendMessage
  content/
    dom_inspector.js    -- builds dom_snapshot from page DOM
    form_filler.js      -- executes fill_field / click / file_upload commands
    overlay.js          -- injects confirm banner + stuck banner into page
    overlay.css
  popup/
    popup.html          -- extension icon popup: shows current session status
    popup.js
  icons/
```

### Key responsibilities

**`service_worker.js`:** Opens WebSocket to `/tailorer/ws/{job_id}?token=JWT`. Detects new tabs opened from the jobstrainer frontend (via `chrome.tabs.onCreated` + `chrome.scripting.executeScript` to read `localStorage.tailorer_pending`). Forwards agent commands to content scripts via `chrome.tabs.sendMessage`. Forwards content script events back to agent over WS. Reconnects with exponential backoff.

**`dom_inspector.js`:** Scans page for form fields, resolves labels, builds structured snapshot. Sends `dom_snapshot` message to service worker.

**`form_filler.js`:** Executes `fill_field` (sets `.value`, dispatches `input`/`change` events for React-controlled inputs), `click`, and `file_upload` (fetches file as Blob, constructs `File` object, sets on input via `DataTransfer`).

**`overlay.js`:** Injects a fixed-position banner at the bottom of the page on `show_confirm`. Highlights uncertain fields with a subtle outline. Provides "Looks good, proceed" button and a text input for corrections. Removes itself on approval or correction.

---

## New Dependencies

`backend/pyproject.toml`:
```
langgraph
langchain-groq
langchain-core
langgraph-checkpoint-postgres   # AsyncPostgresSaver
psycopg[binary,pool]            # required by langgraph-checkpoint-postgres (NOT asyncpg)
```

`AsyncPostgresSaver` uses `psycopg` (v3) and opens its own connection pool separate from the existing asyncpg/SQLAlchemy pool. It also requires a one-time `await checkpointer.setup()` call at app startup (in the FastAPI lifespan in `main.py`) to create its own tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) in the `jobstrainer` database. This is not an Alembic migration — it is runtime DDL run once.

No new Python dependencies for the extension (vanilla JS, no build step required for v1).

---

## Out of Scope (v1)

- Workday / Taleo (obfuscated DOMs) — screenshot/vision fallback is a v2 concern
- Login automation — if the apply page requires login, the stuck handler asks the user to log in manually
- Multi-user job ownership (jobs are effectively single-user for now)
- Firefox-specific MV3 quirks beyond standard WebExtensions API compatibility
