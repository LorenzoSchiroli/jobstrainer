# Native Side Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the injected Shadow DOM panel with the browser's native side panel (Chrome Side Panel API + Firefox Sidebar Action) so the panel appears alongside the page rather than overlapping it.

**Architecture:** A `sidepanel/panel.html` extension page replaces the `content/side_panel.js` content script. The panel connects to the service worker via a named `chrome.runtime` port keyed by tab ID; the service worker stores one port per tab and uses `port.postMessage` instead of `chrome.tabs.sendMessage` for all panel messages. Content scripts (`dom_inspector.js`, `form_filler.js`) continue to inject into the page unchanged. Because the panel is a persistent extension page it survives page navigations without re-injection.

**Tech Stack:** Vanilla JS, WebExtension MV3, Chrome Side Panel API (`chrome.sidePanel`), Firefox Sidebar Action (`sidebar_action`), Jest (jsdom) for unit tests.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `extension/sidepanel/panel.html` | Native panel HTML shell |
| Create | `extension/sidepanel/panel.css` | Panel styles (no Shadow DOM, no toggle tab) |
| Create | `extension/sidepanel/panel.js` | Rendering + port-based SW communication |
| Create | `extension/tests/panel.test.js` | Jest tests for panel.js |
| Modify | `extension/manifest.json` | Add `sidePanel` + `sidebar_action`, remove `web_accessible_resources` |
| Modify | `extension/background/service_worker.js` | Port registry, open panel, route panel messages via ports |
| Modify | `extension/tests/setup.js` | Remove Shadow DOM stub |
| Delete | `extension/content/side_panel.js` | Replaced by sidepanel/panel.js |
| Delete | `extension/content/side_panel.css` | Replaced by sidepanel/panel.css |
| Delete | `extension/tests/side_panel.test.js` | Replaced by tests/panel.test.js |

---

### Task 1: manifest.json — native side panel support

**Files:**
- Modify: `extension/manifest.json`

- [ ] **Step 1: Write the new manifest.json**

Full replacement:

```json
{
  "manifest_version": 3,
  "name": "Jobstrainer Tailorer",
  "version": "0.1.0",
  "description": "AI-powered job application assistant",
  "permissions": [
    "tabs",
    "scripting",
    "sidePanel"
  ],
  "host_permissions": [
    "http://localhost:8000/*",
    "https://*/*",
    "http://*/*"
  ],
  "content_security_policy": {
    "extension_pages": "script-src 'self'; object-src 'self'; connect-src ws://localhost:8000 http://localhost:8000"
  },
  "content_scripts": [
    {
      "matches": ["http://localhost:3000/*"],
      "js": ["content/frontend_bridge.js"],
      "run_at": "document_end"
    }
  ],
  "background": {
    "service_worker": "background/service_worker.js",
    "scripts": ["background/service_worker.js"]
  },
  "side_panel": {
    "default_path": "sidepanel/panel.html"
  },
  "sidebar_action": {
    "default_panel": "sidepanel/panel.html",
    "default_title": "Tailorer",
    "default_icon": { "48": "icons/icon48.png" }
  },
  "action": {
    "default_icon": {
      "16": "icons/icon16.png",
      "48": "icons/icon48.png",
      "128": "icons/icon128.png"
    }
  },
  "icons": {
    "16": "icons/icon16.png",
    "48": "icons/icon48.png",
    "128": "icons/icon128.png"
  }
}
```

Changes from current:
- Added `"sidePanel"` to permissions (Chrome)
- Added `"side_panel"` key → `sidepanel/panel.html` (Chrome; Firefox ignores it)
- Added `"sidebar_action"` key → `sidepanel/panel.html` (Firefox; Chrome ignores it)
- Removed `"web_accessible_resources"` — CSS is now bundled with the panel page, no cross-origin fetch needed

- [ ] **Step 2: Commit**

```bash
git add extension/manifest.json
git commit -m "feat(extension): add native side panel to manifest (Chrome + Firefox)"
```

---

### Task 2: `sidepanel/panel.html` + `sidepanel/panel.css`

**Files:**
- Create: `extension/sidepanel/panel.html`
- Create: `extension/sidepanel/panel.css`

- [ ] **Step 1: Create `extension/sidepanel/panel.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <link rel="stylesheet" href="panel.css">
</head>
<body>
  <div id="tailorer-panel">
    <div class="tailorer-header">
      <span class="tailorer-title">⚡ Tailorer</span>
    </div>
    <div id="tailorer-status" class="tailorer-status tailorer-status--blue"></div>
    <div id="tailorer-log" class="tailorer-log"></div>
  </div>
  <script src="panel.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create `extension/sidepanel/panel.css`**

No Shadow DOM scoping needed. No toggle-tab or host-positioning rules. `body` fills the panel area.

```css
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: #0f172a;
  color: #f1f5f9;
  font-family: system-ui, sans-serif;
  font-size: 13px;
  height: 100vh;
  overflow: hidden;
}

#tailorer-panel {
  display: flex;
  flex-direction: column;
  height: 100vh;
}

.tailorer-header {
  display: flex;
  align-items: center;
  padding: 10px 12px;
  background: #1e3a5f;
  flex-shrink: 0;
}

.tailorer-title {
  font-size: 14px;
  font-weight: 700;
  color: #60a5fa;
}

.tailorer-status {
  padding: 6px 12px;
  font-size: 11px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  border-bottom: 1px solid #1e293b;
  min-height: 28px;
}
.tailorer-status--blue  { background: #172554; color: #7dd3fc; }
.tailorer-status--amber { background: #451a03; color: #fbbf24; }
.tailorer-status--green { background: #14532d; color: #86efac; }
.tailorer-status--red   { background: #450a0a; color: #fca5a5; }
.tailorer-status--slate { background: #1e293b; color: #64748b; }

.tailorer-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
  animation: tailorer-pulse 1.2s ease-in-out infinite;
}
@keyframes tailorer-pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.35; }
}

.tailorer-log {
  flex: 1;
  overflow-y: auto;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.tailorer-entry {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  font-size: 12px;
  line-height: 1.4;
}
.tailorer-entry-icon { flex-shrink: 0; width: 14px; text-align: center; }
.tailorer-entry--done    .tailorer-entry-icon { color: #22c55e; }
.tailorer-entry--done    .tailorer-entry-text { color: #94a3b8; }
.tailorer-entry--pending .tailorer-entry-icon { color: #38bdf8; display: inline-block; animation: tailorer-spin 1s linear infinite; }
.tailorer-entry--pending .tailorer-entry-text { color: #f1f5f9; }
@keyframes tailorer-spin { to { transform: rotate(360deg); } }

.tailorer-confirm-block {
  background: #1c1f2e;
  border-left: 3px solid #f59e0b;
  border-radius: 4px;
  padding: 9px 10px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.tailorer-confirm-summary   { font-size: 12px; font-weight: 600; color: #fde68a; }
.tailorer-confirm-uncertain { font-size: 11px; color: #94a3b8; }
.tailorer-correction-input {
  background: #334155;
  color: #f1f5f9;
  border: 1px solid #475569;
  border-radius: 4px;
  padding: 5px 8px;
  font-size: 12px;
  font-family: system-ui, sans-serif;
  width: 100%;
}

.tailorer-stuck-block {
  background: #1c1f2e;
  border-left: 3px solid #ef4444;
  border-radius: 4px;
  padding: 9px 10px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.tailorer-stuck-message { font-size: 12px; color: #fca5a5; }

.tailorer-entry--done-final .tailorer-entry-icon { color: #22c55e; }
.tailorer-entry--done-final .tailorer-entry-text { color: #86efac; font-weight: 600; }
.tailorer-entry--error .tailorer-entry-icon { color: #ef4444; }
.tailorer-entry--error .tailorer-entry-text { color: #fca5a5; }

.tailorer-downloads {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #1e293b;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.tailorer-download-link { color: #60a5fa; font-size: 12px; text-decoration: none; }
.tailorer-download-link:hover { text-decoration: underline; }

.tailorer-btn {
  border: none;
  border-radius: 4px;
  padding: 5px 12px;
  cursor: pointer;
  font-size: 12px;
  font-family: system-ui, sans-serif;
  color: #fff;
  align-self: flex-start;
}
.tailorer-btn:hover { filter: brightness(1.15); }
.tailorer-btn--approve { background: #16a34a; }
.tailorer-btn--unblock { background: #475569; }
.tailorer-btn--start   { background: #2563eb; width: 100%; text-align: center; font-weight: 600; font-size: 13px; padding: 9px; }

.tailorer-start-area { padding: 16px 12px; display: flex; flex-direction: column; gap: 10px; }
.tailorer-start-hint { font-size: 12px; color: #64748b; }

.tailorer-idle {
  padding: 24px 12px;
  font-size: 12px;
  color: #475569;
  text-align: center;
  line-height: 1.6;
}
```

- [ ] **Step 3: Verify directory**

```bash
ls extension/sidepanel/
```

Expected: `panel.html  panel.css`

- [ ] **Step 4: Commit**

```bash
git add extension/sidepanel/panel.html extension/sidepanel/panel.css
git commit -m "feat(extension): native side panel HTML + CSS"
```

---

### Task 3: `sidepanel/panel.js` — rendering functions + tests

**Files:**
- Create: `extension/sidepanel/panel.js`
- Create: `extension/tests/panel.test.js`

The rendering logic is the same as the old `content/side_panel.js` minus Shadow DOM. `sendMsg(msg)` uses `_port` in the browser and `globalThis.__testPort` in tests — no `chrome.runtime.sendMessage` needed.

- [ ] **Step 1: Write the failing tests**

Create `extension/tests/panel.test.js`:

```js
import '../sidepanel/panel.js';
const { setStatusBar, showIdleState, showStartButton, appendLogEntry, restorePanel } = globalThis;

beforeEach(() => {
  document.body.innerHTML = `
    <div id="tailorer-panel">
      <div class="tailorer-header"><span class="tailorer-title">⚡ Tailorer</span></div>
      <div id="tailorer-status" class="tailorer-status tailorer-status--blue"></div>
      <div id="tailorer-log" class="tailorer-log"></div>
    </div>
  `;
});

afterEach(() => {
  delete globalThis.__testPort;
});

test('setStatusBar updates text', () => {
  setStatusBar('navigating');
  expect(document.getElementById('tailorer-status').textContent).toContain('Navigating');
});

test('setStatusBar sets amber class for awaiting_user', () => {
  setStatusBar('awaiting_user');
  expect(document.getElementById('tailorer-status').className).toContain('tailorer-status--amber');
});

test('showIdleState renders idle message', () => {
  showIdleState();
  expect(document.querySelector('.tailorer-idle')).not.toBeNull();
});

test('showStartButton renders Start Agent button', () => {
  showStartButton('job-1', 'tok-1');
  const btn = document.querySelector('.tailorer-btn--start');
  expect(btn).not.toBeNull();
  expect(btn.textContent).toContain('Start Agent');
});

test('showStartButton click sends start_session via port', () => {
  globalThis.__testPort = { postMessage: jest.fn() };
  showStartButton('job-42', 'tok-abc');
  document.querySelector('.tailorer-btn--start').click();
  expect(globalThis.__testPort.postMessage).toHaveBeenCalledWith({
    type: 'start_session', job_id: 'job-42', token: 'tok-abc',
  });
});

test('appendLogEntry done=true renders ✓ entry', () => {
  appendLogEntry({ kind: 'step', text: 'Filled name', done: true });
  const entry = document.querySelector('.tailorer-entry--done');
  expect(entry).not.toBeNull();
  expect(entry.textContent).toContain('Filled name');
  expect(entry.textContent).toContain('✓');
});

test('appendLogEntry done=false renders ⟳ entry', () => {
  appendLogEntry({ kind: 'step', text: 'Navigating…', done: false });
  const entry = document.querySelector('.tailorer-entry--pending');
  expect(entry).not.toBeNull();
  expect(entry.textContent).toContain('Navigating');
});

test('multiple appendLogEntry calls grow the log in order', () => {
  appendLogEntry({ kind: 'step', text: 'Step 1', done: true });
  appendLogEntry({ kind: 'step', text: 'Step 2', done: true });
  const entries = document.querySelectorAll('.tailorer-entry');
  expect(entries).toHaveLength(2);
  expect(entries[0].textContent).toContain('Step 1');
  expect(entries[1].textContent).toContain('Step 2');
});

test('appendLogEntry confirm renders summary and approve button', () => {
  appendLogEntry({ kind: 'confirm', summary: 'Filled 3 fields', uncertain_fields: ['salary'] });
  const block = document.querySelector('.tailorer-confirm-block');
  expect(block).not.toBeNull();
  expect(block.textContent).toContain('Filled 3 fields');
  expect(block.textContent).toContain('salary');
  expect(block.querySelector('.tailorer-btn--approve')).not.toBeNull();
});

test('appendLogEntry confirm — approve sends user_approved via port', () => {
  globalThis.__testPort = { postMessage: jest.fn() };
  appendLogEntry({ kind: 'confirm', summary: 'Test', uncertain_fields: [] });
  document.querySelector('.tailorer-btn--approve').click();
  expect(globalThis.__testPort.postMessage).toHaveBeenCalledWith({ type: 'user_approved' });
  expect(document.querySelector('.tailorer-confirm-block')).toBeNull();
});

test('appendLogEntry confirm — correction sends user_correction on Enter', () => {
  globalThis.__testPort = { postMessage: jest.fn() };
  appendLogEntry({ kind: 'confirm', summary: 'Test', uncertain_fields: [] });
  const input = document.querySelector('.tailorer-correction-input');
  input.value = 'use remote instead';
  input.dispatchEvent(Object.assign(new Event('keydown'), { key: 'Enter' }));
  expect(globalThis.__testPort.postMessage).toHaveBeenCalledWith({
    type: 'user_correction', text: 'use remote instead',
  });
});

test('appendLogEntry stuck renders message and unblock button', () => {
  appendLogEntry({ kind: 'stuck', message: 'Cannot find apply link' });
  const block = document.querySelector('.tailorer-stuck-block');
  expect(block).not.toBeNull();
  expect(block.textContent).toContain('Cannot find apply link');
  expect(block.querySelector('.tailorer-btn--unblock')).not.toBeNull();
});

test('appendLogEntry stuck — unblock sends stuck_unblocked via port', () => {
  globalThis.__testPort = { postMessage: jest.fn() };
  appendLogEntry({ kind: 'stuck', message: 'Test' });
  document.querySelector('.tailorer-btn--unblock').click();
  expect(globalThis.__testPort.postMessage).toHaveBeenCalledWith({ type: 'stuck_unblocked' });
  expect(document.querySelector('.tailorer-stuck-block')).toBeNull();
});

test('appendLogEntry done renders done entry and download links', () => {
  appendLogEntry({ kind: 'done', message: 'Application submitted!', thread_id: 'tid-1', token: 'tok-abc' });
  const entry = document.querySelector('.tailorer-entry--done-final');
  expect(entry).not.toBeNull();
  expect(entry.textContent).toContain('Application submitted!');
  const links = document.querySelectorAll('.tailorer-download-link');
  expect(links).toHaveLength(2);
  expect(links[0].href).toContain('tid-1');
  expect(links[0].href).toContain('tok-abc');
});

test('appendLogEntry error renders error entry', () => {
  appendLogEntry({ kind: 'error', message: 'WebSocket failed' });
  const entry = document.querySelector('.tailorer-entry--error');
  expect(entry).not.toBeNull();
  expect(entry.textContent).toContain('WebSocket failed');
});

test('restorePanel re-renders all entries in order', () => {
  restorePanel([
    { kind: 'step', text: 'Step 1', done: true },
    { kind: 'step', text: 'Step 2', done: false },
  ], 'navigating');
  const entries = document.querySelectorAll('.tailorer-entry');
  expect(entries).toHaveLength(2);
  expect(entries[0].textContent).toContain('Step 1');
  expect(entries[1].textContent).toContain('Step 2');
});

test('restorePanel clears previous entries', () => {
  appendLogEntry({ kind: 'step', text: 'Old', done: true });
  restorePanel([{ kind: 'step', text: 'New', done: true }], 'navigating');
  const entries = document.querySelectorAll('.tailorer-entry');
  expect(entries).toHaveLength(1);
  expect(entries[0].textContent).toContain('New');
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd extension && npm test -- --testPathPattern=tests/panel
```

Expected: FAIL — `setStatusBar is not a function`.

- [ ] **Step 3: Create `extension/sidepanel/panel.js`**

```js
const API_BASE = 'http://localhost:8000';

const STATUS_CONFIG = {
  connecting:    { text: 'Connecting…',      dot: true,  cls: 'blue'  },
  navigating:    { text: 'Navigating…',       dot: true,  cls: 'blue'  },
  filling:       { text: 'Filling form…',     dot: true,  cls: 'blue'  },
  awaiting_user: { text: '⏸ Waiting for you', dot: false, cls: 'amber' },
  show_stuck:    { text: '⚠ Action needed',   dot: false, cls: 'red'   },
  done:          { text: '✓ Done',            dot: false, cls: 'green' },
  error:         { text: '✗ Error',           dot: false, cls: 'red'   },
  idle:          { text: 'No active session', dot: false, cls: 'slate' },
};

function setStatusBar(status) {
  const bar = document.getElementById('tailorer-status');
  if (!bar) return;
  const cfg = STATUS_CONFIG[status] || { text: status, dot: true, cls: 'blue' };
  bar.className = `tailorer-status tailorer-status--${cfg.cls}`;
  bar.innerHTML = '';
  if (cfg.dot) {
    const dot = document.createElement('span');
    dot.className = 'tailorer-dot';
    bar.appendChild(dot);
  }
  const txt = document.createElement('span');
  txt.textContent = cfg.text;
  bar.appendChild(txt);
}

function showIdleState() {
  const log = document.getElementById('tailorer-log');
  if (!log) return;
  log.innerHTML = '';
  const el = document.createElement('div');
  el.className = 'tailorer-idle';
  el.textContent = 'No active job — browse to a job listing to apply.';
  log.appendChild(el);
  setStatusBar('idle');
}

function showStartButton(job_id, token) {
  const log = document.getElementById('tailorer-log');
  if (!log) return;
  log.innerHTML = '';
  const area = document.createElement('div');
  area.className = 'tailorer-start-area';
  const hint = document.createElement('div');
  hint.className = 'tailorer-start-hint';
  hint.textContent = 'Job detected — ready to apply';
  const btn = document.createElement('button');
  btn.className = 'tailorer-btn tailorer-btn--start';
  btn.textContent = '⚡ Start Agent';
  btn.addEventListener('click', () => {
    sendMsg({ type: 'start_session', job_id, token });
    log.innerHTML = '';
    setStatusBar('connecting');
  });
  area.append(hint, btn);
  log.appendChild(area);
}

function _makeStepEntry(text, done) {
  const el = document.createElement('div');
  el.className = `tailorer-entry tailorer-entry--${done ? 'done' : 'pending'}`;
  const icon = document.createElement('span');
  icon.className = 'tailorer-entry-icon';
  icon.textContent = done ? '✓' : '⟳';
  const txt = document.createElement('span');
  txt.className = 'tailorer-entry-text';
  txt.textContent = text;
  el.append(icon, txt);
  return el;
}

function appendLogEntry(entry) {
  const log = document.getElementById('tailorer-log');
  if (!log) return;
  let el;

  if (entry.kind === 'step') {
    el = _makeStepEntry(entry.text, entry.done);

  } else if (entry.kind === 'confirm') {
    el = document.createElement('div');
    el.className = 'tailorer-confirm-block';
    const summary = document.createElement('div');
    summary.className = 'tailorer-confirm-summary';
    summary.textContent = entry.summary;
    el.appendChild(summary);
    if (entry.uncertain_fields?.length) {
      const unc = document.createElement('div');
      unc.className = 'tailorer-confirm-uncertain';
      unc.textContent = `Uncertain: ${entry.uncertain_fields.join(', ')}`;
      el.appendChild(unc);
    }
    const input = document.createElement('input');
    input.className = 'tailorer-correction-input';
    input.placeholder = 'Correction? Type + Enter…';
    input.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      const text = input.value.trim();
      if (!text) return;
      sendMsg({ type: 'user_correction', text });
      el.replaceWith(_makeStepEntry('Corrected', true));
    });
    const approveBtn = document.createElement('button');
    approveBtn.className = 'tailorer-btn tailorer-btn--approve';
    approveBtn.textContent = 'Looks good ✓';
    approveBtn.addEventListener('click', () => {
      sendMsg({ type: 'user_approved' });
      el.replaceWith(_makeStepEntry('Confirmed', true));
    });
    el.append(input, approveBtn);

  } else if (entry.kind === 'stuck') {
    el = document.createElement('div');
    el.className = 'tailorer-stuck-block';
    const msg = document.createElement('div');
    msg.className = 'tailorer-stuck-message';
    msg.textContent = entry.message;
    const unblockBtn = document.createElement('button');
    unblockBtn.className = 'tailorer-btn tailorer-btn--unblock';
    unblockBtn.textContent = 'Done, continue ▶';
    unblockBtn.addEventListener('click', () => {
      sendMsg({ type: 'stuck_unblocked' });
      el.replaceWith(_makeStepEntry('Unblocked', true));
    });
    el.append(msg, unblockBtn);

  } else if (entry.kind === 'done') {
    el = document.createElement('div');
    el.className = 'tailorer-entry tailorer-entry--done-final';
    const icon = document.createElement('span');
    icon.className = 'tailorer-entry-icon';
    icon.textContent = '✓';
    const txt = document.createElement('span');
    txt.className = 'tailorer-entry-text';
    txt.textContent = entry.message;
    el.append(icon, txt);
    if (entry.thread_id && entry.token) {
      const tok = encodeURIComponent(entry.token);
      const tid = encodeURIComponent(entry.thread_id);
      const downloads = document.createElement('div');
      downloads.className = 'tailorer-downloads';
      const cvLink = document.createElement('a');
      cvLink.className = 'tailorer-download-link';
      cvLink.href = `${API_BASE}/tailorer/files/${tid}/cv?token=${tok}`;
      cvLink.target = '_blank';
      cvLink.textContent = '↓ Tailored CV (.docx)';
      const clLink = document.createElement('a');
      clLink.className = 'tailorer-download-link';
      clLink.href = `${API_BASE}/tailorer/files/${tid}/cover_letter?token=${tok}`;
      clLink.target = '_blank';
      clLink.textContent = '↓ Cover Letter (.docx)';
      downloads.append(cvLink, clLink);
      el.appendChild(downloads);
    }
    setStatusBar('done');

  } else if (entry.kind === 'error') {
    el = document.createElement('div');
    el.className = 'tailorer-entry tailorer-entry--error';
    const icon = document.createElement('span');
    icon.className = 'tailorer-entry-icon';
    icon.textContent = '✗';
    const txt = document.createElement('span');
    txt.className = 'tailorer-entry-text';
    txt.textContent = entry.message;
    el.append(icon, txt);
    setStatusBar('error');
  }

  if (!el) return;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
}

function restorePanel(log, status) {
  const logEl = document.getElementById('tailorer-log');
  if (!logEl) return;
  logEl.innerHTML = '';
  for (const entry of log) appendLogEntry(entry);
  if (status) setStatusBar(status);
}

// sendMsg uses the live port in browser context; __testPort in Jest
function sendMsg(msg) {
  (_port || globalThis.__testPort)?.postMessage(msg);
}

// ── Port connection ────────────────────────────────────────────────────────

let _port = null;

function _connectWithTab(tabId) {
  if (_port) {
    _port.onMessage.removeListener(_handleMessage);
    _port.disconnect();
  }
  _port = chrome.runtime.connect({ name: `panel-${tabId}` });
  _port.onMessage.addListener(_handleMessage);
  _port.onDisconnect.addListener(() => {
    _port = null;
    // Reconnect after short delay — service worker may have been killed (MV3 sleep)
    setTimeout(() => _connectWithTab(tabId), 500);
  });
}

function _handleMessage(msg) {
  if (msg.type === 'show_apply_button') {
    showStartButton(msg.job_id, msg.token);
    setStatusBar('connecting');
  } else if (msg.type === 'restore_panel') {
    restorePanel(msg.log || [], msg.status);
  } else if (msg.type === 'append_log') {
    appendLogEntry(msg.entry);
  } else if (msg.type === 'set_status') {
    setStatusBar(msg.status);
  } else if (msg.type === 'idle') {
    showIdleState();
  }
}

if (typeof chrome !== 'undefined' && chrome.runtime?.connect) {
  (async () => {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    _connectWithTab(tab.id);
  })();

  chrome.tabs.onActivated.addListener(({ tabId }) => {
    _connectWithTab(tabId);
  });
} else {
  globalThis.setStatusBar = setStatusBar;
  globalThis.showIdleState = showIdleState;
  globalThis.showStartButton = showStartButton;
  globalThis.appendLogEntry = appendLogEntry;
  globalThis.restorePanel = restorePanel;
}
```

- [ ] **Step 4: Run tests**

```bash
cd extension && npm test -- --testPathPattern=tests/panel
```

Expected: 17 tests pass.

- [ ] **Step 5: Commit**

```bash
git add extension/sidepanel/panel.js extension/tests/panel.test.js
git commit -m "feat(extension): native side panel rendering + tests"
```

---

### Task 4: `service_worker.js` — ports, panel opening, message routing

**Files:**
- Modify: `extension/background/service_worker.js`

This task rewires the service worker to use ports instead of `tabs.sendMessage` for panel communication and to open the native side panel when a job tab is detected.

- [ ] **Step 1: Add `panelPorts` registry and `sendToPanel` helper**

After the `injectedTabs` declaration (line 5), add:

```js
const panelPorts = {}; // tabId -> port
```

After the `requestSnapshotAndSend` function at the bottom, add:

```js
function sendToPanel(tabId, msg) {
  panelPorts[tabId]?.postMessage(msg);
}
```

- [ ] **Step 2: Configure Chrome side panel behavior at startup**

Add at the very top level of the service worker (after the `const` declarations):

```js
// Make the action button open the side panel (Chrome only)
if (typeof chrome !== 'undefined' && chrome.sidePanel?.setPanelBehavior) {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
}
```

- [ ] **Step 3: Add `onConnect` listener for panel ports**

Add a new section after the `chrome.runtime.onMessage` block:

```js
// ── Panel port connections ─────────────────────────────────────────────────

chrome.runtime.onConnect.addListener((port) => {
  const match = port.name.match(/^panel-(\d+)$/);
  if (!match) return;
  const tabId = parseInt(match[1]);
  panelPorts[tabId] = port;

  port.onDisconnect.addListener(() => {
    if (panelPorts[tabId] === port) delete panelPorts[tabId];
  });

  // Send current state to newly connected panel
  if (pendingJobs[tabId]) {
    const { job_id, token } = pendingJobs[tabId];
    port.postMessage({ type: 'show_apply_button', job_id, token });
  } else if (sessions[tabId]) {
    const s = sessions[tabId];
    port.postMessage({ type: 'restore_panel', log: s.log, status: s.currentStatus });
  } else {
    port.postMessage({ type: 'idle' });
  }

  port.onMessage.addListener((msg) => {
    if (msg.type === 'start_session') {
      delete pendingJobs[tabId];
      openSession(tabId, msg.job_id, msg.token);
      return;
    }
    const session = sessions[tabId];
    if (!session?.ws || session.ws.readyState !== WebSocket.OPEN) return;
    if (msg.type === 'user_approved') {
      const idx = session.log.findLastIndex((e) => e.kind === 'confirm');
      if (idx !== -1) session.log[idx] = { kind: 'step', text: 'Confirmed', done: true };
      session.ws.send(JSON.stringify(msg));
    } else if (msg.type === 'user_correction') {
      const idx = session.log.findLastIndex((e) => e.kind === 'confirm');
      if (idx !== -1) session.log[idx] = { kind: 'step', text: 'Corrected', done: true };
      session.ws.send(JSON.stringify(msg));
    } else if (msg.type === 'stuck_unblocked') {
      const idx = session.log.findLastIndex((e) => e.kind === 'stuck');
      if (idx !== -1) session.log[idx] = { kind: 'step', text: 'Unblocked', done: true };
      session.ws.send(JSON.stringify(msg));
    } else if (msg.type === 'user_manual_edit') {
      session.ws.send(JSON.stringify(msg));
    }
  });
});
```

- [ ] **Step 4: Update `onUpdated` — remove side_panel.js injection, open native panel, use `sendToPanel`**

Full replacement of the `onUpdated` listener:

```js
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo) => {
  if (changeInfo.url) injectedTabs.delete(tabId);

  if (changeInfo.status !== 'complete') return;
  if (!pendingJobs[tabId] && !sessions[tabId]) return;

  if (!injectedTabs.has(tabId)) {
    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        files: ['content/dom_inspector.js', 'content/form_filler.js'],
      });
      injectedTabs.add(tabId);
    } catch (_) {
      return;
    }
  }

  // Open native side panel in Chrome (Firefox sidebar is opened manually via browser UI)
  if (chrome.sidePanel?.open) {
    chrome.sidePanel.open({ tabId }).catch(() => {});
  }

  if (pendingJobs[tabId]) {
    const { job_id, token } = pendingJobs[tabId];
    sendToPanel(tabId, { type: 'show_apply_button', job_id, token });
    return;
  }

  const session = sessions[tabId];
  if (!session) return;

  const wasNavigating = session.pendingNavigate;
  if (wasNavigating) {
    session.pendingNavigate = false;
    const last = session.log[session.log.length - 1];
    if (last?.kind === 'step' && !last.done) last.done = true;
  }

  sendToPanel(tabId, {
    type: 'restore_panel',
    log: session.log,
    status: session.currentStatus,
  });

  if (wasNavigating) {
    requestSnapshotAndSend(tabId);
  }
});
```

- [ ] **Step 5: Update `onRemoved` — clean up panel port**

Full replacement of the `onRemoved` listener:

```js
chrome.tabs.onRemoved.addListener((tabId) => {
  if (sessions[tabId]) {
    sessions[tabId].ws?.close();
    delete sessions[tabId];
  }
  delete pendingJobs[tabId];
  delete panelPorts[tabId];
  injectedTabs.delete(tabId);
});
```

- [ ] **Step 6: Update `onMessage` — remove panel action handlers (now handled by port)**

The `onMessage` listener now only handles `register_pending` from `frontend_bridge.js`. Replace the entire listener:

```js
chrome.runtime.onMessage.addListener((msg, sender) => {
  const tabId = sender.tab?.id;
  if (!tabId) return;

  if (msg.type === 'register_pending') {
    pendingNextTab = { job_id: msg.job_id, token: msg.token };
  }
});
```

- [ ] **Step 7: Replace `chrome.tabs.sendMessage` panel calls in `handleAgentMessage` with `sendToPanel`**

Full replacement of `handleAgentMessage`:

```js
async function handleAgentMessage(tabId, msg) {
  const session = sessions[tabId];
  if (!session) return;

  if (msg.type === 'session_started') {
    session.thread_id = msg.thread_id;
    session.reconnectDelay = 1000;
    session.currentStatus = 'navigating';
    const entry = { kind: 'step', text: 'Session started', done: true };
    session.log.push(entry);
    sendToPanel(tabId, { type: 'append_log', entry });
    return;
  }

  if (msg.type === 'navigate') {
    session.currentStatus = 'navigating';
    session.pendingNavigate = true;
    let hostname = msg.url;
    try { hostname = new URL(msg.url).hostname; } catch (_) {}
    const entry = { kind: 'step', text: `Navigating to ${hostname}…`, done: false };
    session.log.push(entry);
    sendToPanel(tabId, { type: 'append_log', entry });
    chrome.tabs.update(tabId, { url: msg.url });
    return;
  }

  if (msg.type === 'request_snapshot') {
    requestSnapshotAndSend(tabId);
    return;
  }

  if (msg.field_id !== undefined) {
    if (msg.type === 'file' || msg.value === '__CV__' || msg.value === '__COVER_LETTER__') {
      await handleFileUpload(tabId, msg);
    } else {
      session.currentStatus = 'filling';
      const entry = { kind: 'step', text: `Filling "${msg.field_id}"…`, done: true };
      session.log.push(entry);
      sendToPanel(tabId, { type: 'append_log', entry });
      chrome.tabs.sendMessage(tabId, { type: 'fill_field', field_id: msg.field_id, value: msg.value });
    }
    return;
  }

  if (msg.type === 'navigate_next') {
    session.currentStatus = 'navigating';
    const entry = { kind: 'step', text: 'Submitting page…', done: true };
    session.log.push(entry);
    sendToPanel(tabId, { type: 'append_log', entry });
    chrome.tabs.sendMessage(tabId, { type: 'navigate_next' }, (response) => {
      const liveSession = sessions[tabId];
      if (liveSession?.ws?.readyState === WebSocket.OPEN) {
        liveSession.ws.send(JSON.stringify(response || { submitted: false }));
      }
    });
    return;
  }

  if (msg.type === 'show_confirm') {
    session.currentStatus = 'awaiting_user';
    const entry = { kind: 'confirm', summary: msg.summary, uncertain_fields: msg.uncertain_fields || [] };
    session.log.push(entry);
    sendToPanel(tabId, { type: 'append_log', entry });
    return;
  }

  if (msg.type === 'show_stuck') {
    session.currentStatus = 'show_stuck';
    const entry = { kind: 'stuck', message: msg.message };
    session.log.push(entry);
    sendToPanel(tabId, { type: 'append_log', entry });
    return;
  }

  if (msg.type === 'done') {
    session.currentStatus = 'done';
    const { thread_id, token } = session;
    const entry = { kind: 'done', message: msg.message, thread_id, token };
    session.log.push(entry);
    sendToPanel(tabId, { type: 'append_log', entry });
    injectedTabs.delete(tabId);
    delete sessions[tabId];
    return;
  }

  if (msg.type === 'error') {
    session.currentStatus = 'error';
    const entry = { kind: 'error', message: msg.message };
    session.log.push(entry);
    sendToPanel(tabId, { type: 'append_log', entry });
    injectedTabs.delete(tabId);
    delete sessions[tabId];
    return;
  }
}
```

- [ ] **Step 8: Update `ws.onclose` to use `sendToPanel`**

In `openSession`, replace the permanent-failure block:

```js
    if (!opened || ev.code === 1015 || ev.code === 4001) {
      const entry = { kind: 'error', message: `WebSocket failed (code ${ev.code})` };
      s.log.push(entry);
      sendToPanel(tabId, { type: 'append_log', entry });
      delete sessions[tabId];
      return;
    }
```

- [ ] **Step 9: Run tests**

```bash
cd extension && npm test
```

Expected: all tests pass (panel.test.js + dom_inspector.test.js + form_filler.test.js).

- [ ] **Step 10: Commit**

```bash
git add extension/background/service_worker.js
git commit -m "feat(extension): service worker port management + native side panel opening"
```

---

### Task 5: Cleanup

**Files:**
- Modify: `extension/tests/setup.js`
- Delete: `extension/content/side_panel.js`
- Delete: `extension/content/side_panel.css`
- Delete: `extension/tests/side_panel.test.js`

- [ ] **Step 1: Remove Shadow DOM stub from `extension/tests/setup.js`**

Full new content:

```js
// Expose jest as a globalThis property for ESM test files
import { jest as _jest } from '@jest/globals';
globalThis.jest = _jest;

if (!globalThis.CSS) globalThis.CSS = {};
if (!globalThis.CSS.escape) {
  globalThis.CSS.escape = (value) =>
    String(value).replace(/([!"#$%&'()*+,.\/:;<=>?@[\\\]^`{|}~])/g, '\\$1').replace(/^(\d)/, '\\3$1 ');
}
```

- [ ] **Step 2: Delete old files**

```bash
rm extension/content/side_panel.js
rm extension/content/side_panel.css
rm extension/tests/side_panel.test.js
```

- [ ] **Step 3: Run full test suite**

```bash
cd extension && npm test
```

Expected: all tests pass. Side_panel tests are gone; panel tests pass.

- [ ] **Step 4: Commit**

```bash
git add extension/tests/setup.js
git add -u extension/content/ extension/tests/
git commit -m "chore(extension): remove Shadow DOM content script, clean up setup.js"
```

---

## Browser behaviour notes (no code required)

**Chrome**: The service worker calls `chrome.sidePanel.open({ tabId })` in `onUpdated`. This works when the tab was opened via a user gesture (clicking a job link). If it fails (e.g. tab opened programmatically), the user can click the extension icon to open the panel — `setPanelBehavior({ openPanelOnActionClick: true })` ensures that click opens the panel instead of a popup.

**Firefox**: `browser.sidebarAction.open()` requires a user gesture and cannot be called from `onUpdated`. Firefox users open the sidebar via the browser's View → Sidebar menu, keyboard shortcut, or the sidebar toggle button. Once open, the panel stays open and updates automatically as the user switches tabs.
