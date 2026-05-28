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

1. User clicks a job link in the jobstrainer frontend. Before `window.open()`, the frontend writes `localStorage.tailorer_pending = { job_id }`.
2. Job board page opens in a new tab. The extension service worker detects the new tab via `chrome.tabs.onCreated`, reads `tailorer_pending` from the opener tab via `chrome.scripting.executeScript`.
3. Extension injects `overlay.js` into the new tab, showing a floating **"Apply with Agent"** button on the job board page.
4. User clicks it → extension opens WebSocket `GET /tailorer/ws/{job_id}?token=JWT` → agent starts. The backend sends a `session_started` message with the generated `thread_id`; the extension stores this for file download URLs.

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

Both are stored as files under `{TAILORER_FILES_DIR}/{thread_id}/` (configurable env var, defaults to `/tmp/tailorer/`). The filesystem path is stored in LangGraph state. The extension downloads them via a signed endpoint when a file upload field is encountered.

**③ fill_page**  
Receives a `dom_snapshot` from the extension. The LLM maps each detected field to the best value from: `ApplicantProfile` fields, tailored document text, or `extra_qa` JSONB. Sends `fill_field`, `file_upload`, and `click` commands back. Fields the agent is uncertain about are flagged in the subsequent `show_confirm` message.

**⏸ confirm_with_user** *(LangGraph interrupt)*  
Sends `show_confirm` to the extension. The extension injects a fixed-position overlay banner at the bottom of the page: *"Filled N fields — ready to continue?"*. Uncertain fields are highlighted. Waits for one of:
- `user_approved` → transitions to `navigate_next`
- `user_correction` (natural language, e.g. "change years to 5+") → re-fills affected fields → re-confirms
- `user_manual_edit` (user typed directly in form) → updates state → re-confirms

**④ navigate_next**  
Clicks the "Next" or "Submit" button. Detects whether more pages remain or the application is complete. If more pages → back to `fill_page`. If done → `done` node.

**⚡ stuck_handler**  
Reachable from any node after 2 failed retries. Sends `show_stuck` with a human-readable message ("Can't find the Apply button — can you click it for me?"). Waits for `stuck_unblocked` from the extension, then resumes from the node that failed.

**✓ done**  
Inserts a row into `applications (user_id, job_id)` to record the completed application.

### LangGraph State Object

Persisted automatically by `AsyncPostgresSaver` (LangGraph's Postgres checkpointer):

```python
apply_url: str
current_page: int
filled_fields: dict[str, str]
cv_path: str
cl_path: str
retry_count: int
failed_node: str | None   # set before entering stuck_handler so it knows where to resume
status: str               # navigating | filling | awaiting_user | stuck | done | failed
```

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

**File upload note:** tailored CV/CL bytes are never sent over the WebSocket. The agent stores them server-side and sends a signed `download_url`. The extension fetches the file as a `Blob` and sets it programmatically on the `<input type="file">` element.

**Auth:** JWT token passed as `?token=` query param on the WebSocket handshake. The extension reconnects with exponential backoff on disconnect.

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
id             UUID PK
user_id        FK → users UNIQUE
first_name     TEXT
last_name      TEXT
email          TEXT
phone          TEXT
city           TEXT
country        TEXT
work_auth      TEXT          -- e.g. "EU citizen, no sponsorship needed"
urls           JSONB         -- {"linkedin": "…", "github": "…", "website": "…"}
extra_qa       JSONB         -- {"notice_period": "2 weeks", "salary_expectation": "80k"}
cv_text        TEXT          -- migrated from users.cv_text
updated_at     TIMESTAMP
```

Managed via `PUT /tailorer/profile`. The existing `cv` router (`/users/cv`) is updated to read/write `applicant_profile.cv_text` instead of `user.cv_text`.

### New: `applications`

Junction table tracking which user applied to which job.

```
user_id     FK → users   )
job_id      FK → jobs    )  PRIMARY KEY (user_id, job_id)
applied_at  TIMESTAMP DEFAULT now()
```

Presence of a row = applied. Inserted by the agent's `done` node. Extensible: a `status` ENUM column (`applied`, `interviewing`, `rejected`, `offer`) can be added later without changing the core flow.

### Alembic Migrations

- `007_applicant_profile.py` — create `applicant_profile`, copy `users.cv_text` → `applicant_profile.cv_text`, drop `cv_text` from `users`
- `008_applications.py` — create `applications` junction table

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
```

No new Python dependencies for the extension (vanilla JS, no build step required for v1).

---

## Out of Scope (v1)

- Workday / Taleo (obfuscated DOMs) — screenshot/vision fallback is a v2 concern
- Login automation — if the apply page requires login, the stuck handler asks the user to log in manually
- Multi-user job ownership (jobs are effectively single-user for now)
- Firefox-specific MV3 quirks beyond standard WebExtensions API compatibility
