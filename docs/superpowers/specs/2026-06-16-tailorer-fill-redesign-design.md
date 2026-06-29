# Tailorer Fill Redesign

**Date:** 2026-06-16
**Status:** Approved design, pending implementation plan

## Goal

The tailorer currently tries to do three hard things in one agent: navigate arbitrary
career sites to *find* the application form, tailor documents, and fill the form. The
navigation stage is the most failure-prone, and the fill stage silently fails on the
custom widgets real application forms use. This redesign **drops navigation entirely**
and makes **filling** the single, robust, simple responsibility of the agent.

The user manually opens the application page and clicks **Fill** (an alias for typing
"fill the form" in the bar — the extension is text-first). The agent fills the current
page only. For multi-page forms the user advances the site's own Next/Continue button and
clicks Fill again. **There is no explicit approve step: proceeding to the next page is
itself the confirmation.** If the user is unhappy, they type a correction in the bar and
the agent re-fills.

## Scope decisions (locked)

- **Fill button is job-tied.** It still runs against an active job session (`job_id` +
  token) so it can tailor the CV / cover letter and upload the files. It just skips the
  "hunt for the form" step.
- **Single page at a time.** No multi-page auto-advance. `navigate_next`,
  `current_page`, and submit-detection-for-advancing are removed.
- **Whole-page view.** The model sees the entire page's interactive elements, not just
  the visible viewport. Scroll actions are removed.
- **Declarative fills.** The LLM returns `{index, value}` (plus `generate` for document
  fields). The extension decides the mechanism per widget. The LLM never names an action.
- **Re-snapshot-and-diff retries.** After applying fills, re-read the page and compare
  each field's actual value to what was intended; retry mismatches autonomously before
  showing the user anything.
- **Documents are fields.** The CV / cover letter upload is just another field the LLM
  maps. The LLM decides — from context, not from a rule/regex — whether to (re)generate
  the document this pass. Regeneration rebuilds the whole document; no surgical diffing.
- **Real automated file upload.** The extension downloads the generated docx to the local
  filesystem and sets it on the file input via CDP. Download links remain only as a
  fallback when no usable file input is found.
- **Text-first, no approve step.** The input bar is the primary interface and is always
  active. Any typed text is an instruction/correction fed into the mapping LLM as
  "user feedback this round" — including the canonical "fill the form" that triggers a
  pass. No field-vs-tailoring classifier and no approve keyword: the LLM naturally
  re-emits the right commands. Approval is implicit (the user proceeding to the next page).
- **Buttons are text shortcuts.** The **Fill** button injects "fill the form" and submits
  it as if typed. The **New Session** button tears down the current session so the next
  Fill starts clean.
- **Application record only on detected submit.** No row is written during fills or
  corrections. The extension watches for the user actually submitting; on detection it signals the backend,
  which writes one `Application(user_id, job_id)` row. If detection misses, no row is
  written (accepted trade-off). No schema migration needed.

## Architecture

### Backend graph (`agent.py`)

Collapses from 7 nodes to 2 single-purpose nodes. **LangGraph does all looping via
conditional edges** — no internal `while`, no phase flags, no blocking confirm node. The
guiding rule: **one `interrupt()` per node** (so LangGraph's resume-replays-the-node-from-
the-top behaviour never re-runs an LLM call).

```
entry → map → apply → (mismatch & retries left?) ─ yes ─→ apply
                          │ no
                          ▼
                         END   (emit non-blocking summary to panel)
```

- **`map`** — pure LLM, no interrupt. Reads `last_snapshot`, returns the full list of
  fill commands for *every* visible field (re-mapped from scratch each pass — no
  per-field dedup, no surgical correction). For document upload fields it emits
  `{index, value: "__CV__"|"__COVER_LETTER__", generate: bool}`. The prompt is given the
  current document status ("CV: already generated; Cover letter: not yet") and the user's
  typed instruction/feedback this round, and the LLM decides `generate`. When any command
  has `generate: true`, `map` calls the existing `generate_tailored_documents` and rebuilds
  that document wholesale, updating `cv_bytes`/`cl_bytes`/`cl_text`.
- **`apply`** — one interrupt (`apply_fills`). The extension applies all commands
  (including real file upload for document fields) and returns a post-fill snapshot plus
  each targeted field's actual value/state. The backend diffs intended vs. actual. Any
  mismatch with retries remaining → conditional edge loops back to `apply` (re-send
  everything). Bounded by `retry_count` (max 2). Otherwise → END.

There is **no blocking confirm/approve node.** Reaching `END` ends one fill *pass* and
emits a non-blocking summary entry to the panel ("Filled N fields · M uncertain: …" plus
any upload-fallback links). The user reviews the real filled form on the page, then either
types a correction (→ a fresh `map → apply` pass with that feedback) or proceeds to the
next page and clicks Fill again (the implicit confirmation). Reaching `END` does **not**
close the session — the router keeps the WebSocket open and re-invokes the graph on the
same `thread_id` for the next typed instruction or Fill click.

### State (`state.py`)

Removed: all `nav_*` fields, `apply_url`, `current_page`, `filled_fields`,
`no_progress_count`, scroll fields.

Kept / changed:

```python
class TailorerState(TypedDict):
    job_id: str
    user_id: str
    job_title: str
    job_description: str
    profile: dict
    cv_text: str
    cv_bytes: bytes
    cl_bytes: bytes
    cl_text: str
    last_snapshot: dict | None      # whole-page snapshot
    fill_commands: list[dict]       # mapped commands for the current pass
    last_feedback: str | None       # user's typed instruction/correction fed into map
    retry_count: int                # apply-diff retry counter, reset each map
    status: str                     # mapping | applying | filled | failed
```

### Router / session lifecycle (`router.py`)

- WS endpoint stays keyed by `job_id` (must exist in DB), same auth.
- First typed instruction ("fill the form", or the Fill button) opens the WS, assigns
  `thread_id`, runs the graph.
- The run loop invokes the graph until `END`. On `END` it does **not** close the socket
  and does **not** write an Application row: it emits a non-blocking "filled" summary to
  the panel and waits for the next message (next typed instruction / Fill click →
  re-invoke on same `thread_id`, with the typed text as `last_feedback`).
- A `submitted` message from the extension (submit detected) writes the
  `Application(user_id, job_id)` row, once, idempotently.
- A `new_session` message tears down the WS/thread.
- Session ends on Stop, tab close, or disconnect.
- One interrupt handler: `apply_fills`. It replaces today's
  `request_snapshot`/`execute_actions`/`navigate`/`navigate_next`/`show_stuck`/
  `fill_and_confirm` set.

**Snapshot sourcing (no standalone snapshot interrupt).** There is deliberately no
`request_snapshot` interrupt. The whole-page snapshot enters the graph two ways:
- The triggering message: the extension captures the whole-page snapshot and includes it
  in the `start_or_fill` message, which the router passes as `last_snapshot` in the graph
  input. This is what `map` reads.
- The `apply_fills` interrupt response: the extension applies the commands and returns the
  post-fill snapshot (with per-field actual values). That becomes `last_snapshot` for the
  diff.

This keeps the "one interrupt per node" rule: `map` has none, `apply` has `apply_fills`.

### Extension fill mechanics (`page.ts`)

Replace `typeText` / `selectOption` / manual file handling with one method, `applyFill`,
built on **detection-first dispatch** — inspect the element once, route directly to the
single correct mechanism. No blind trying.

```
applyFill(index, value):
  el = _locateHandle(index)        # existing iframe + shadow-DOM traversal, unchanged

  # 1. Detect element kind from its own properties (deterministic, no guessing):
  #    tagName, input.type, role, aria-haspopup/expanded, contenteditable, <option> children
  # 2. Dispatch to the ONE matching mechanism:
    input[checkbox|radio]              → set checked = truthy(value); click to fire events
    select + <option> children         → match option by text/value; set; dispatch change
    role=combobox|listbox / aria-haspopup / div-popup
                                       → click to open → click option matching value
    input[file] (__CV__/__COVER_LETTER__) → real upload (see below)
    contenteditable                    → focus + insert text
    everything else text-like          → React-safe native-setter + input/change events
```

The detected mechanism is the first and usually only attempt. A field only enters the
**escalation fallback** (below) if the re-read diff shows the value didn't stick, or the
element couldn't be classified (e.g. a `<div>` dropdown with no role/aria).

**Escalation fallback (verified-failure only, still no LLM).** Some failures are runtime
behaviour invisible in the markup — a masking/validation library reverting `.value` on
blur, or an unclassifiable custom widget. For just those fields, escalate the *mechanism*
for the same intended value, e.g. text: set `.value` → focus+retype → CDP keyboard
char-by-char; dropdown: native → click-open-and-pick → type-to-filter+Enter. If the
strongest mechanism still fails, the field is flagged `uncertain` in the pass summary for
the user to correct via the bar. The escalation ladder is bounded by `retry_count` (max 2)
and is what the `apply` self-loop drives.

Unchanged because they already work: `_locateHandle` (iframe + shadow DOM) and the
React-safe value setter.

`apply` itself remains LLM-free: detection, dispatch, the diff check, and the escalation
ladder are all pure script. The only LLM call in a pass is in `map`. Semantically wrong
values (right mechanism, wrong answer) are not something the script can detect — those are
corrected by the user typing in the bar (→ a fresh `map` pass).

### File upload (the auto-upload chain)

Replaces today's "download link the user uploads manually." Feasibility confirmed:
`chrome.debugger` exposes the DOM CDP domain (so `DOM.setFileInputFiles` /
`ElementHandle.uploadFile` work), and `chrome.downloads` returns the absolute local path.

```
1. Backend already serves the docx at /tailorer/files/{thread_id}/{cv|cover_letter}?token=…
2. chrome.downloads.download({ url, filename: "tailorer/<name>.docx" })   # under Downloads/
3. chrome.downloads.onChanged → state "complete"
4. chrome.downloads.search({ id }) → DownloadItem.filename = absolute path
5. elementHandle.uploadFile(absolutePath)   # CDP DOM.setFileInputFiles, fires input/change
6. chrome.downloads.removeFile(id) + erase   # cleanup
```

- Requires the `downloads` permission in `manifest.json`.
- Files land under the user's **Downloads/tailorer/** folder (Chrome cannot write to an
  arbitrary OS temp dir); cleaned up after upload.
- Works for real `input[type=file]` (including ones hidden behind a styled dropzone).
  Pure non-input drag-drop zones fall back to the download link.

### Submit detection (extension)

After a fill pass, the extension watches the page (CDP attached) for a real
submission and signals the backend:

- Detect via: navigation to a new URL combined with a completion-keyword / "thank you"
  page (reuse the existing `_COMPLETION_KEYWORDS`), or the form/file inputs disappearing.
- On detection, send `{ type: "submitted" }` over the WS → router writes the Application
  row once.
- Best-effort: SPA confirmations may be missed or mis-fired; `started`-style intermediate
  state is intentionally not recorded, per the locked scope decision.

### Whole-page snapshot (`page.ts`, `dom/service.ts`)

`snapshot()` calls `getClickableElements(tabId, url, true, /*focus*/ -1,
/*viewportExpansion*/ -1)`. `buildDomTree.js` already treats `viewportExpansion === -1`
as "all elements in viewport / all top elements," so the whole page is serialized with no
screenshots and no scrolling. `getScrollInfo` and the `scroll_*` snapshot fields and Page
scroll methods are removed.

### UI (`App.tsx`)

Text-first: the input bar is the primary interface and is **always active** (no
`isWaiting`/`disabled` gating).

- Remove the "⚡ Start Agent" button and the `pendingJob` detection flow.
- The bar submits whatever the user types as `start_or_fill` with the text attached as the
  instruction/feedback. On first submit it opens the session; otherwise it re-invokes on
  the live `thread_id`.
- Add a **Fill** button immediately above the bar, always rendered, that injects
  "fill the form" into the bar and submits it (pure alias — no separate code path).
- Add a **New Session** button in the header that sends `new_session`.
- Keep the Stop button. After each pass the panel appends a **non-blocking summary** entry
  (filled count, uncertain fields, any upload-fallback download links) — not a modal, not a
  blocking confirm. No approve control.

## Data flow (one Fill pass)

1. User types "fill the form" (or clicks Fill) → extension snapshots the whole page →
   `start_or_fill` (with the typed text) → backend `map`.
2. `map`: LLM returns all fill commands; (re)generates documents if it decided to.
3. `apply`: extension applies every command via `applyFill` (incl. real file upload),
   returns post-fill values.
4. Backend diffs; mismatches re-applied up to 2× automatically.
5. END → panel appends a non-blocking summary (filled count, uncertain fields, any
   fallback links). No DB write, no blocking wait.
6. User either types a correction (→ a fresh `map → apply` pass) or proceeds to the next
   page and clicks Fill again (implicit confirmation of this page).
7. Independently: when the extension detects the user submitted → `submitted` → backend
   writes the Application row once.

## Error handling

- **Fill didn't take:** caught by the apply-diff; retried automatically (bounded), then
  surfaced to the user as an uncertain field if still wrong.
- **Locate failure:** `_locateHandle` already retries once with a fresh snapshot; on final
  failure the command is reported as failed and shown as uncertain.
- **Upload failure** (no real file input, download error, CDP rejection): fall back to
  emitting the download link in the pass summary entry.
- **LLM/JSON parse failure in `map`:** fall back to an empty command list and surface an
  error entry, rather than crashing the pass (mirrors today's `tailor.py` guard).
- **Document generation failure:** reuse prior bytes if present; otherwise report the
  field as needing manual handling.

## Testing

- Backend node tests (`tests/tailorer/test_nodes.py` style — mocked LLM + mocked
  `interrupt`): `map` emits mixed-widget commands incl. a document field with `generate`;
  `apply` loops back on a diffed mismatch and stops at the retry cap, then ends the pass; a
  follow-up invocation with `last_feedback` set re-runs `map` (correction = new pass);
  `submitted` message writes exactly one Application row (idempotent on repeat).
- Extension unit tests for `applyFill` per widget branch (checkbox, native select, custom
  listbox, text, file-upload with mocked `chrome.downloads` + `uploadFile`, and the
  download-link fallback).
- Submit-detection unit test (completion keyword / form-gone heuristics).
- Snapshot test asserting `viewportExpansion = -1` is passed through.

## Out of scope

- Finding/navigating to the application form (deleted; user navigates manually).
- Multi-page auto-advance.
- Programmatic upload to pure non-input drag-drop zones (download-link fallback only).
- Inline document preview in the panel.
- Recording an Application row when submit is not detected.
