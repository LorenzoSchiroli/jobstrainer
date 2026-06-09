# Tailorer Refactor — Design Spec

**Date:** 2026-06-09
**Scope:** Backend `tailorer/` package + extension `background/` layer

---

## Goal

Aggressively refactor the tailorer codebase for simplicity, modularity, and maintainability. The backend remains the agent brain (LangGraph + interrupt stays). The extension gets a proper module structure with a `SessionManager` class, a typed action registry, and a message dispatch map — replacing 460 lines of mixed concerns in a single file.

---

## Backend

### Current problems

- `nodes.py` (370 lines) mixes LLM factory, prompt strings, navigation phase logic, and form-filling logic.
- `router.py`'s `_handle_interrupt` is a 60-line if/elif chain — one branch per interrupt type, no separation.
- Prompts are buried inside functions, making them hard to find and edit.
- `import logging` appears at line 149, after every function that uses `_log`.

### New file layout

```
backend/backend/tailorer/
  __init__.py
  state.py        (unchanged)
  models.py       (unchanged)
  schemas.py      (unchanged)
  agent.py        (unchanged — graph definition + routing functions)
  tailor.py       (unchanged — CV + cover letter generation)
  llm.py          NEW — LLM factory + all system prompt constants
  navigation.py   NEW — navigate_to_apply node + navigation helpers
  form.py         NEW — fill_page, fetch_snapshot, navigate_next + form helpers
  router.py       REFACTOR — interrupt dispatch map, one handler per type
  nodes.py        DELETE — replaced by navigation.py + form.py
```

### `llm.py`

Owns everything LLM-related that is currently scattered:

```python
import os
from langchain_openai import ChatOpenAI

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"

def make_llm(model: str) -> ChatOpenAI:
    return ChatOpenAI(model=model, api_key=os.environ["GROQ_API_KEY"], base_url=_GROQ_BASE_URL)

def base_llm() -> ChatOpenAI:
    return make_llm(os.environ["GROQ_MODEL_BASE"])

def large_llm() -> ChatOpenAI:
    return make_llm(os.environ["GROQ_MODEL_LARGE"])

# All system prompts as module-level constants
NAV_SYSTEM_PROMPT = """You are navigating a company website..."""
FILL_SYSTEM_PROMPT = """You fill job application form fields..."""
CORRECTION_SYSTEM_PROMPT = """Correct job application fill commands..."""
```

### `navigation.py`

Contains only navigation concerns:

- `navigate_to_apply(state)` — the LangGraph node (phase state machine unchanged: `start → deciding → executing → snapshot → nav_done`)
- `_decide_next_navigation(llm, snapshot, job_title, nav_history, nav_memory, stuck_hint)` → `dict`
- `_next_no_progress(prev_snapshot, new_snapshot, prior_count)` → `int`
- `_resolve_url(href, base_url)` → `str`
- Constants: `_MAX_NAV_STEPS`, `_STUCK_NUDGE_THRESHOLD`, `_STUCK_USER_THRESHOLD`, `_STUCK_HINT`

Imports `large_llm` from `llm.py`.

### `form.py`

Contains only form-filling concerns:

- `fill_page(state)` — LangGraph node
- `fetch_snapshot(state)` — LangGraph node
- `navigate_next(state)` — LangGraph node
- `node_done(state)` — LangGraph node
- `confirm_apply(state)` — LangGraph node
- `tailor_documents(state)` — LangGraph node
- `_map_fields(llm, snapshot, state)` → `list[dict]`
- `_apply_correction(llm, correction_text, commands, state)` → `list[dict]`
- Constant: `_COMPLETION_KEYWORDS`

Imports `large_llm` from `llm.py`.

### `agent.py` changes

Update imports only:

```python
from backend.tailorer.navigation import navigate_to_apply
from backend.tailorer.form import (
    confirm_apply, tailor_documents, fetch_snapshot,
    fill_page, navigate_next, node_done,
)
```

### `router.py` refactor

Replace `_handle_interrupt` if/elif chain with a dispatch map. Each interrupt type gets its own async function:

```python
async def _handle_navigate(ws, val, **kw) -> dict: ...
async def _handle_request_snapshot(ws, val, **kw) -> dict: ...
async def _handle_execute_actions(ws, val, **kw) -> dict: ...
async def _handle_fill_and_confirm(ws, val, thread_id, token, **kw) -> dict: ...
async def _handle_show_confirm(ws, val, **kw) -> dict: ...
async def _handle_navigate_next(ws, val, **kw) -> dict: ...
async def _handle_show_stuck(ws, val, **kw) -> dict: ...

_INTERRUPT_HANDLERS: dict[str, Callable] = {
    "navigate":          _handle_navigate,
    "request_snapshot":  _handle_request_snapshot,
    "execute_actions":   _handle_execute_actions,
    "fill_and_confirm":  _handle_fill_and_confirm,
    "show_confirm":      _handle_show_confirm,
    "navigate_next":     _handle_navigate_next,
    "show_stuck":        _handle_show_stuck,
}

async def _handle_interrupt(ws, interrupt_val, thread_id="", token="") -> dict:
    itype = interrupt_val.get("type")
    handler = _INTERRUPT_HANDLERS.get(itype)
    if not handler:
        return {"type": "unknown"}
    return await handler(ws, interrupt_val, thread_id=thread_id, token=token)
```

---

## Extension

### Current problems

- `service_worker.ts` (460 lines) mixes: tab lifecycle, keepalive alarm, WebSocket management, agent message dispatch, browser action execution, navigation detection, and log management.
- Module-level globals (`sessions`, `pendingJobs`, `panelPorts`) make state management fragile.
- `handleAgentMessage` is a 120-line if/else chain.
- `executeAction` is a 30-line if/else chain mixed into the session layer.
- Navigation detection helpers (`waitForNavCompleted`, `clickAndDetectNavigation`) are co-located with session logic.

### New file layout

```
extension/background/
  service_worker.ts           THIN — tab lifecycle + keepalive only (~80 lines)
  session/
    types.ts                  LogEntry, Session, PendingJob interfaces
    manager.ts                SessionManager class (singleton)
  agent/
    messageHandler.ts         dispatch map: msg.type → handler
  browser/
    page.ts                   (unchanged)
    actions.ts                NEW — typed action registry
    navigation.ts             NEW — waitForNavCompleted, clickAndDetectNavigation
    dom/                      (unchanged)
```

### `session/types.ts`

All shared types in one place:

```typescript
export type LogEntry =
  | { kind: 'step'; text: string; done: boolean }
  | { kind: 'confirm'; summary: string; uncertain_fields: string[]; file_links: FileLink[] }
  | { kind: 'stuck'; message: string }
  | { kind: 'done'; message: string; thread_id: string; token: string }
  | { kind: 'error'; message: string };

export interface FileLink { field_id: number; label: string; url: string; }

export interface Session {
  job_id: string;
  token: string;
  thread_id: string | null;
  ws: WebSocket;
  page: Page;
  log: LogEntry[];
  currentStatus: string;
}

export interface PendingJob { job_id: string; token: string; }
```

### `session/manager.ts`

Single class owns all session state. Replaces three module-level maps.

```typescript
import Page from '../browser/page';
import { handleAgentMessage } from '../agent/messageHandler';
import type { Session, PendingJob, LogEntry } from './types';

export class SessionManager {
  private sessions = new Map<number, Session>();
  private pendingJobs = new Map<number, PendingJob>();
  private ports = new Map<number, chrome.runtime.Port>();

  // Port management
  registerPort(tabId: number, port: chrome.runtime.Port): void
  removePort(tabId: number): void
  sendToPanel(tabId: number, msg: unknown): void

  // Pending job management
  setPending(tabId: number, job: PendingJob): void
  getPending(tabId: number): PendingJob | undefined
  clearPending(tabId: number): void

  // Session lifecycle
  open(tabId: number, jobId: string, token: string): void   // creates WS + Page, wires handlers
  stop(tabId: number, reason: string): void                  // closes WS + detaches Page
  get(tabId: number): Session | undefined
  has(tabId: number): boolean

  // Log
  appendLog(tabId: number, entry: LogEntry): void            // pushes to session.log + sends to panel
  cleanupTab(tabId: number): void                            // called from onRemoved
}

export const sessionManager = new SessionManager();
```

The `open()` method encapsulates what is currently spread across `openSession()`:
- Creates the `WebSocket` and `Page`
- Wires `ws.onmessage → handleAgentMessage`
- Wires `ws.onclose → stop()`
- Stores the session

### `browser/navigation.ts`

Extracted from `service_worker.ts`. Navigation detection helpers that belong at the browser layer:

```typescript
export function waitForNavCompleted(tabId: number, timeoutMs = 8000): Promise<void>
export async function clickAndDetectNavigation(tabId: number, clickFn: () => Promise<void>): Promise<boolean>
```

No changes to logic — pure extraction.

### `browser/actions.ts`

Replaces the `executeAction` if/else chain with a typed registry:

```typescript
import Page from './page';
import { waitForNavCompleted, clickAndDetectNavigation } from './navigation';

interface ActionResult { navigated: boolean; }
type ActionFn = (page: Page, action: Record<string, any>, tabId: number) => Promise<ActionResult>;

const nav = (tabId: number, url: string): Promise<ActionResult> =>
  waitForNavCompleted(tabId).then(() => ({ navigated: true }));

const no_nav = (fn: () => Promise<unknown>): Promise<ActionResult> =>
  fn().then(() => ({ navigated: false }));

const ACTIONS: Record<string, ActionFn> = {
  click_element:    (page, a, tabId) => clickAndDetectNavigation(tabId, () => page.clickElement(a.index)).then(navigated => ({ navigated })),
  input_text:       (page, a) => no_nav(() => page.typeText(a.index, a.text ?? '')),
  select_option:    (page, a) => no_nav(() => page.selectOption(a.index, a.text ?? '')),
  scroll_to_bottom: (page)   => no_nav(() => page.scrollToBottom()),
  scroll_to_top:    (page)   => no_nav(() => page.scrollToTop()),
  next_page:        (page)   => no_nav(() => page.scrollDown()),
  previous_page:    (page)   => no_nav(() => page.scrollUp()),
  send_keys:        (page, a) => no_nav(() => page.sendKeys(a.keys ?? '')),
  go_back: async (page, _a, tabId) => {
    const navDone = waitForNavCompleted(tabId);
    await page.goBack();
    await navDone;
    return { navigated: true };
  },
  go_to_url: async (page, a, tabId) => {
    const navDone = waitForNavCompleted(tabId);
    await page.navigate(a.url);
    await navDone;
    return { navigated: true };
  },
  wait: (page, a) => no_nav(() => page.wait(a.seconds ?? 2)),
};

export async function executeAction(page: Page, action: Record<string, any>, tabId: number): Promise<ActionResult> {
  const fn = ACTIONS[action.action];
  if (!fn) {
    console.warn('[actions] unknown action', action.action);
    return { navigated: false };
  }
  return fn(page, action, tabId);
}
```

### `agent/messageHandler.ts`

Replaces the 10-branch if/else in `handleAgentMessage` with a typed dispatch map:

```typescript
import { sessionManager } from '../session/manager';
import { executeAction } from '../browser/actions';
import type { Session } from '../session/types';

type Handler = (tabId: number, session: Session, msg: Record<string, any>) => Promise<void>;

const HANDLERS: Record<string, Handler> = {
  session_started: async (tabId, session, msg) => { ... },
  navigate:        async (tabId, session, msg) => { ... },
  request_snapshot: async (tabId, session, _msg) => { ... },
  execute_actions:  async (tabId, session, msg) => { ... },
  fill_and_confirm: async (tabId, session, msg) => { ... },
  show_confirm:     async (tabId, session, msg) => { ... },
  navigate_next:    async (tabId, session, msg) => { ... },
  show_stuck:       async (tabId, session, msg) => { ... },
  done:             async (tabId, session, msg) => { ... },
  error:            async (tabId, session, msg) => { ... },
};

export async function handleAgentMessage(tabId: number, msg: Record<string, any>): Promise<void> {
  const session = sessionManager.get(tabId);
  if (!session) return;
  const handler = HANDLERS[msg.type];
  if (!handler) return;
  await handler(tabId, session, msg);
}
```

### `service_worker.ts` (after refactor)

Reduced to ~80 lines — only Chrome extension lifecycle wiring:

```typescript
import { sessionManager } from './session/manager';

// Keepalive
chrome.alarms.create('keepalive', { periodInMinutes: 0.4 });
chrome.alarms.onAlarm.addListener(...); // saves activeSessions to storage

// Tab lifecycle
chrome.tabs.onCreated.addListener(...);   // reads tailorer_pending, calls sessionManager.setPending()
chrome.tabs.onUpdated.addListener(...);   // opens side panel, calls sessionManager.sendToPanel()
chrome.tabs.onRemoved.addListener(...);   // calls sessionManager.cleanupTab()

// Panel ports
chrome.runtime.onConnect.addListener((port) => {
  // register port, wire port.onMessage → sessionManager.open() / sessionManager.stop()
});
```

---

## Data flow (unchanged)

The WebSocket protocol between backend and extension is **not changed**. Wire format, interrupt types, and response shapes stay identical. This refactor is purely structural.

```
Backend LangGraph node
  → interrupt(payload)
  → router._handle_interrupt(ws, payload)   [now dispatch map]
  → ws.send_json(msg)
  → service_worker ws.onmessage
  → handleAgentMessage(tabId, msg)           [now dispatch map]
  → HANDLERS[msg.type](tabId, session, msg)
  → executeAction(page, action, tabId)       [now action registry]
  → page.clickElement / typeText / …
  → ws.send(JSON.stringify(snap))
  → router resumes LangGraph with Command(resume=snap)
```

---

## What is NOT changing

- `page.ts` — the Puppeteer CDP abstraction is already clean
- `browser/dom/` — unchanged
- `sidepanel/` — unchanged
- `agent.py` — graph structure unchanged
- `state.py` — TypedDict unchanged
- `tailor.py` — document generation unchanged
- `models.py`, `schemas.py` — unchanged
- Wire protocol — identical
- Backend tests — updated imports only

---

## File deletion list

| File | Reason |
|------|--------|
| `backend/backend/tailorer/nodes.py` | Replaced by `navigation.py` + `form.py` |

---

## Testing

- Backend: update imports in `tests/tailorer/test_nodes.py` to import from `navigation` / `form`
- Extension: existing Vitest tests for `page.ts` unchanged; new tests for `executeAction` in `actions.ts` (action registry is pure and easy to unit test)
