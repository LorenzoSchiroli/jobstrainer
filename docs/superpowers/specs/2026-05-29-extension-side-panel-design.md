# Extension Side Panel Design

**Goal:** Replace the scattered overlay banners and popup with a single right-side panel (Shadow DOM) that shows all agent activity and accepts user input in one place.

**Architecture:** A Shadow DOM host element is injected into each job application page. The panel pushes the page body left via `margin-right`. The service worker accumulates a step log per session and replays it into the panel after every page navigation, so the full history persists across navigations.

**Tech Stack:** Vanilla JS (no framework), Shadow DOM, WebExtension MV3, Chrome + Firefox.

---

## File Changes

### New
- `content/side_panel.js` — Shadow DOM panel: all UI states, step log, user interaction handlers.
- `content/side_panel.css` — Styles injected into the shadow root (fully isolated from the host page).
- `tests/side_panel.test.js` — Jest tests replacing `tests/overlay.test.js`.

### Deleted
- `content/overlay.js` — replaced by `side_panel.js`.
- `content/overlay.css` — replaced by `side_panel.css`.
- `popup/popup.html` — removed; status lives entirely in the panel.
- `popup/popup.js` — removed.
- `tests/overlay.test.js` — replaced by `tests/side_panel.test.js`.

### Modified
- `manifest.json` — remove `default_popup` from `action`; swap `overlay.js/css` → `side_panel.js/css` in injected files.
- `background/service_worker.js` — add `log: []` to session object; send `restore_panel` on re-injection; emit `append_log` for each agent event.

---

## Panel Structure

The panel is a fixed 320 px element attached to the right edge of the viewport. When open, `document.body.style.marginRight = '320px'` pushes the page left. When closed, a 28 px wide `⚡` toggle tab remains on the right edge; clicking it reopens the panel.

```
┌────────────────────────────────┐
│ ⚡ Tailorer              [✕]   │  ← header (always visible)
├────────────────────────────────┤
│  ● Filling form…               │  ← status bar (animated dot)
├────────────────────────────────┤
│  ✓ Navigated to careers page   │
│  ✓ Clicked "Apply Now"         │  ← step log (scrollable, grows down)
│  ✓ Filled "Full Name"          │
│  ⟳ Filling "Phone"…            │  ← current step (spinning icon)
│                                │
│  [inline confirm / stuck UI    │  ← appended when agent pauses
│   appears here when needed]    │
└────────────────────────────────┘
```

---

## Panel States

### 1. Ready
Shown immediately when a tab with a pending job finishes loading (before the user starts the agent). Displays a single "⚡ Start Agent" button. Step log is empty.

### 2. Running
Shown once the user clicks "Start Agent". The status bar shows an animated dot + current action label. The step log grows downward as the agent works. The current step has a spinning `⟳` icon; completed steps show `✓`.

### 3. Awaiting confirm
Status bar shows "⏸ Waiting for you". At the bottom of the step log, an inline block appears with:
- Summary text (e.g. "Filled 3 fields — looks good?")
- Uncertain fields listed in small text
- A text input for corrections (pressing Enter or clicking the button sends a `user_correction` message)
- A "Looks good ✓" button (sends `user_approved`)

Once the user acts, the block is replaced by a `✓ Confirmed` log entry and the agent continues.

### 4. Stuck
Status bar shows "⚠ Action needed". An inline block appears at the bottom of the log with:
- The stuck message from the agent
- A "Done, continue ▶" button (sends `stuck_unblocked`)

### 5. Done
Status bar turns green and shows "✓ Done". A final `✓` log entry is appended. Below the log, a download section appears with links to the tailored CV and cover letter (fetched via `GET /tailorer/files/{thread_id}/{cv|cover_letter}?token=…`).

### 6. Error
Status bar turns red and shows "✗ Error". An error log entry is appended with the error message. No download links.

### 7. Collapsed
The open panel is hidden. The page body `margin-right` is removed. A 28 px `⚡` toggle tab stays fixed to the right edge. Clicking it restores the panel and re-applies `margin-right`.

---

## Step Log Entries

Each entry is a plain object stored in `sessions[tabId].log` in the service worker:

```js
{ kind: 'step',    text: 'Navigated to careers page', done: true  }
{ kind: 'step',    text: 'Filling "Phone"…',          done: false }  // current step
{ kind: 'confirm', summary: 'Filled 3 fields',        uncertain_fields: ['salary'] }
{ kind: 'stuck',   message: 'Cannot find apply link' }
{ kind: 'done',    message: 'Application submitted!'  }
{ kind: 'error',   message: 'WebSocket failed (code 1015)' }
```

Only one `confirm` or `stuck` entry can be pending at a time (the previous one is resolved before the next arrives).

When the user acts on a `confirm` or `stuck` entry, the service worker replaces that entry in `sessions[tabId].log` with `{ kind:'step', text:'Confirmed' | 'Unblocked', done:true }` before appending the next entry. This ensures `restore_panel` after navigation never shows a stale interactive block.

---

## Service Worker Changes

Each session object gains a `log: []` array and a `currentStatus: 'navigating'` string. The service worker appends entries, updates `currentStatus` on each state change, and forwards messages to the live tab via `chrome.tabs.sendMessage`.

| Agent message         | Log entry appended                                | Message sent to tab              |
|-----------------------|---------------------------------------------------|----------------------------------|
| `session_started`     | `{ kind:'step', text:'Session started', done:true }` | `{ type:'append_log', entry }` + `{ type:'set_status', status:'navigating' }` |
| `navigate`            | `{ kind:'step', text:'Navigating to <hostname>…', done:false }` | `{ type:'append_log', entry }` |
| navigate complete (onUpdated status=complete after pendingNavigate) | update last step `done:true` | `{ type:'step_done' }` |
| fill command          | `{ kind:'step', text:'Filling "<field_id>"…', done:true }` | `{ type:'append_log', entry }` |
| `navigate_next`       | `{ kind:'step', text:'Submitting page…', done:true }` | `{ type:'append_log', entry }` |
| `show_confirm`        | `{ kind:'confirm', summary, uncertain_fields }`   | `{ type:'append_log', entry }`  |
| `show_stuck`          | `{ kind:'stuck', message }`                       | `{ type:'append_log', entry }`  |
| `done`                | `{ kind:'done', message }`                        | `{ type:'append_log', entry }`  |
| `error`               | `{ kind:'error', message }`                       | `{ type:'append_log', entry }`  |

### Re-injection after navigation

When the tab navigates (URL change), `injectedTabs.delete(tabId)` as today. When the page finishes loading and scripts are re-injected, the service worker sends:

```js
chrome.tabs.sendMessage(tabId, {
  type: 'restore_panel',
  log: sessions[tabId].log,
  status: sessions[tabId].currentStatus,   // 'navigating' | 'filling' | 'awaiting_user' | etc.
});
```

`side_panel.js` renders all log entries from scratch on receiving `restore_panel`.

---

## Body Push Mechanism

```js
// Open panel
document.body.style.setProperty('margin-right', '320px', 'important');

// Close / collapse panel
document.body.style.removeProperty('margin-right');
```

The `!important` flag is needed to override inline styles set by some job sites. This works identically on Chrome and Firefox.

---

## Message Protocol (content script → service worker)

Unchanged from today:
- `start_session` — user clicks "Start Agent"
- `user_approved` — user clicks "Looks good ✓"
- `user_correction` — user submits a correction
- `stuck_unblocked` — user clicks "Done, continue"
- `register_pending` — Firefox noopener path (frontend_bridge.js, unchanged)

---

## Shadow DOM Setup

```js
const host = document.createElement('div');
host.id = 'tailorer-host';
Object.assign(host.style, {
  position: 'fixed', top: '0', right: '0',
  width: '320px', height: '100vh',
  zIndex: '2147483647', fontFamily: 'system-ui, sans-serif',
});
document.body.appendChild(host);

const shadow = host.attachShadow({ mode: 'open' });

// Inject CSS into shadow root
const styleEl = document.createElement('link');
styleEl.rel = 'stylesheet';
styleEl.href = chrome.runtime.getURL('content/side_panel.css');
shadow.appendChild(styleEl);
```

Firefox and Chrome both support `attachShadow` with `mode: 'open'` in content scripts. `chrome.runtime.getURL` is available in both via the `browser` / `chrome` compatibility shim already in use.

---

## Testing

`tests/side_panel.test.js` covers:

- Panel is created and appended to `document.body` when `initPanel()` is called
- `appendLogEntry({ kind:'step', text, done:true })` adds a `✓` entry to the log
- `appendLogEntry({ kind:'step', text, done:false })` adds a `⟳` entry
- `appendLogEntry({ kind:'confirm', ... })` appends inline confirm block with approve button and correction input
- `appendLogEntry({ kind:'stuck', ... })` appends inline stuck block with unblock button
- `appendLogEntry({ kind:'done', ... })` appends done entry and shows download links
- `appendLogEntry({ kind:'error', ... })` appends error entry
- `restorePanel(log, status)` renders all entries in order
- Clicking ✕ removes `margin-right` from body and shows the toggle tab
- Clicking the toggle tab restores `margin-right` and shows the panel
- `chrome.runtime.sendMessage` is called with correct type when approve/correction/unblock buttons are clicked

Shadow DOM note: jsdom does not support `attachShadow`. Tests use a lightweight stub that replaces `attachShadow` with a regular `div` child, so all DOM assertions work normally.
