# Extension Redesign — Nanobrowser DOM Layer + Updated Agent Protocol

**Date:** 2026-06-04  
**Status:** Approved for implementation

## Goal

Replace the current shallow DOM inspection and synthetic-event interaction layer with nanobrowser's production-grade browser control stack. Update the backend agent prompts and WebSocket protocol to match. The result: the agent can reliably navigate and fill job application forms on any ATS platform, including React-based ones (Greenhouse, Lever, Workday) that ignore synthetic events.

## Scope

- **Extension**: full rewrite in TypeScript + React + Vite (Chrome MV3 only — Firefox dropped)
- **Backend**: targeted updates to `state.py`, `nodes.py`, `router.py` — LangGraph graph structure, interrupt pattern, and checkpointing unchanged

---

## Architecture

### What stays the same

- LangGraph `StateGraph` with Postgres checkpointing
- `interrupt()` pattern for human-in-the-loop (confirm fills, stuck, user corrections)
- WebSocket at `/tailorer/ws/{job_id}` as the transport
- Node graph: `navigate_to_apply → confirm_apply → tailor_documents → fetch_snapshot → fill_page → navigate_next → done`
- `tailor_documents` node (CV + cover letter generation)

### What changes

| Layer | Before | After |
|---|---|---|
| DOM inspection | shallow `dom_inspector.js` (form fields + links + buttons + innerText) | nanobrowser's `buildDomTree.js` (full interactive tree, iframes, Shadow DOM, viewport-aware) |
| Element addressing | HTML `id` attribute (`field_id`) — fragile, often missing | stable numeric `highlightIndex` assigned by buildDomTree |
| Click/fill interactions | synthesized DOM events via content script | puppeteer-core + ExtensionTransport (real CDP events) via service worker |
| Content scripts | `dom_inspector.js`, `form_filler.js` | deleted — all DOM work in service worker via CDP |
| Firefox support | partial (sidebar_action) | dropped |
| Panel UI | plain HTML/CSS/JS | React + Vite, actor feed design |
| Agent prompt structure | flat decision per step | nanobrowser navigator structure: `{evaluation_previous_goal, memory, next_goal, action[]}` |
| Action batching | one action per interrupt | up to 3 actions per LLM call, executed in sequence |
| Action schema | navigate, click (CSS selector), fill (field_id) | click_element (index), input_text (index), select_option (index), scroll_to_bottom/top, send_keys, go_back, wait |

---

## Extension

### File structure

```
extension/
├── manifest.json              # Chrome MV3 only
├── package.json               # puppeteer-core, react, vite, typescript
├── tsconfig.json
├── vite.config.ts             # two entry points: service_worker (IIFE, not ESM — MV3 requirement) + sidepanel (React)
│
├── public/
│   └── buildDomTree.js        # copied verbatim from nanobrowser
│
├── background/
│   ├── service_worker.ts      # session lifecycle, WebSocket, action dispatch
│   └── browser/               # ported from nanobrowser
│       ├── page.ts            # puppeteer-core + ExtensionTransport
│       ├── dom/
│       │   ├── service.ts     # injects buildDomTree.js, getClickableElements()
│       │   ├── views.ts       # DOMElementNode, clickableElementsToString()
│       │   ├── raw_types.ts
│       │   └── clickable/service.ts
│       └── util.ts
│
├── sidepanel/
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       └── components/
│           ├── LogEntry.tsx
│           ├── ConfirmBlock.tsx
│           ├── StuckBlock.tsx
│           ├── StartButton.tsx
│           └── StatusBar.tsx
│
└── content/
    └── frontend_bridge.js     # unchanged
```

### Snapshot format (extension → backend)

Replaces `{fields, links, buttons, page_text}`:

```json
{
  "url": "https://greenhouse.io/apply/123",
  "title": "Apply — Software Engineer",
  "elements": "[0]<a href=/jobs >Jobs />\n[1]<button >Apply Now />\n[2]<input type=text placeholder='First name' />\n[3]<input type=file />\n[4]<select >Full-time />",
  "scroll_y": 0,
  "scroll_height": 2400,
  "viewport_height": 800
}
```

`elements` is produced by `DOMElementNode.clickableElementsToString()`. Every interactive element has a stable numeric index for the current page load. New elements since last snapshot are marked `*[n]`.

### Action protocol (backend → extension)

New `execute_actions` interrupt type replaces `click_and_snapshot` and `fill_and_search`:

```json
{
  "type": "execute_actions",
  "actions": [
    {"action": "click_element", "index": 1},
    {"action": "input_text", "index": 2, "text": "John"},
    {"action": "select_option", "index": 4, "text": "Full-time"},
    {"action": "scroll_to_bottom"},
    {"action": "send_keys", "keys": "Tab"},
    {"action": "go_back"},
    {"action": "wait", "seconds": 2}
  ]
}
```

The extension executes actions in sequence. If a page navigation is detected mid-sequence, it stops and returns a snapshot immediately. `fill_and_confirm` commands change from `{field_id, value}` to `{index, value, action}`.

Unchanged interrupt types: `navigate`, `request_snapshot`, `show_confirm`, `navigate_next`, `show_stuck`.

### Panel UI

Actor feed design (nanobrowser-inspired sky/slate aesthetic):

- **Header**: logo + name + status pill (e.g. "Navigating…" / "⏸ Waiting for you")
- **Feed**: messages labeled AGENT only (no SYSTEM distinction). Minimal logging — key milestones only (navigated, reached form, tailoring, page submitted). No per-field fill logs.
- **Confirm block**: shown inline in the feed when agent needs approval. Shows only uncertain fields (amber) and file upload links. Everything else is visible directly in the browser.
- **Bottom bar**: always present. Input + send button disabled/grayed while agent is running; enabled when agent is waiting. Stop button always active, bottom right.
- **Interaction model**: user types `ok` to approve, or free-text to correct. No separate approve/correct buttons.

---

## Backend

### `state.py`

Two changes:
1. `last_snapshot: dict | None` — shape updated to `{url, title, elements, scroll_y, scroll_height, viewport_height}`
2. New field: `nav_memory: str` — running memory string persisted across LangGraph replays in `navigate_to_apply`

### `nodes.py`

**`navigate_to_apply` — `_decide_next_navigation()` rewrite:**

LLM receives: elements string + scroll info + current URL + nav history + job title.  
LLM responds with nanobrowser navigator structure:
```json
{
  "current_state": {
    "evaluation_previous_goal": "Success — found apply button at index 1",
    "memory": "Navigated homepage → careers page → job detail. Apply button found.",
    "next_goal": "Click apply button"
  },
  "action": [
    {"action": "click_element", "index": 1}
  ]
}
```
`nav_memory` is persisted in state. Up to 3 actions returned per step.  
Interrupt becomes `{type: "execute_actions", actions: [...]}`.

**`fill_page` — `_map_fields_sync()` rewrite:**

LLM receives: elements string + profile + cv_text excerpt + cl_text excerpt.  
LLM responds with index-based commands:
```json
[
  {"index": 2, "value": "John", "action": "input_text"},
  {"index": 4, "action": "select_option", "text": "Full-time"},
  {"index": 7, "action": "file_upload", "value": "__CV__", "uncertain": false},
  {"index": 9, "action": "input_text", "value": "???", "uncertain": true}
]
```
Uncertain fields and file uploads surfaced in confirm block. All other fills happen silently in the browser.

### `router.py`

New `execute_actions` interrupt handler in `_handle_interrupt()`:
- Iterates actions array
- Sends each to extension over WebSocket
- Waits for snapshot response after each page-changing action (navigate, click, send_keys with Enter)
- Returns final snapshot to agent

`fill_and_confirm` updated: sends index-based fill commands. Confirm message to panel contains only uncertain fields and file links.

---

## Dependencies added

| Package | Where | Purpose |
|---|---|---|
| `puppeteer-core` | extension | CDP browser control via ExtensionTransport |
| `react`, `react-dom` | extension/sidepanel | panel UI |
| `vite`, `@vitejs/plugin-react` | extension | build tooling |
| `typescript` | extension | type safety across ported nanobrowser code |

---

## Out of scope

- Nanobrowser's Planner agent (not needed — task is fully defined)
- Nanobrowser's multi-agent executor (agent stays on backend)
- Session history / replay (nanobrowser feature, not needed here)
- Firefox support (dropped for this iteration)
