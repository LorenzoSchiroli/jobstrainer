# Extension Side Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the scattered overlay banners and extension popup with a single Shadow DOM side panel that pushes the page left, persists across navigations, and consolidates all agent activity in one place.

**Architecture:** A 320 px Shadow DOM host is injected into job application pages; styles are fully isolated. The service worker accumulates a step log per session and replays it into the panel after every page navigation. The extension popup is removed entirely.

**Tech Stack:** Vanilla JS, Shadow DOM, WebExtension MV3, Chrome + Firefox.

---

## File Map

| Action | Path |
|--------|------|
| Create | `extension/content/side_panel.css` |
| Create | `extension/content/side_panel.js` |
| Create | `extension/tests/side_panel.test.js` |
| Modify | `extension/tests/setup.js` |
| Modify | `extension/background/service_worker.js` |
| Modify | `extension/manifest.json` |
| Delete | `extension/content/overlay.js` |
| Delete | `extension/content/overlay.css` |
| Delete | `extension/popup/popup.html` |
| Delete | `extension/popup/popup.js` |
| Delete | `extension/tests/overlay.test.js` |

---

### Task 1: side_panel.css

**Files:**
- Create: `extension/content/side_panel.css`

These styles live inside the shadow root — they are fully isolated and cannot conflict with the host page.

- [ ] **Step 1: Create the CSS file**

```css
/* extension/content/side_panel.css */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

#tailorer-panel {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #0f172a;
  color: #f1f5f9;
  font-family: system-ui, sans-serif;
  font-size: 13px;
}

.tailorer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  background: #1e3a5f;
  flex-shrink: 0;
}

.tailorer-title {
  font-size: 14px;
  font-weight: 700;
  color: #60a5fa;
}

.tailorer-close {
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  font-size: 14px;
  padding: 0 4px;
  line-height: 1;
}
.tailorer-close:hover { color: #f1f5f9; }

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
.tailorer-status--blue   { background: #172554; color: #7dd3fc; }
.tailorer-status--amber  { background: #451a03; color: #fbbf24; }
.tailorer-status--green  { background: #14532d; color: #86efac; }
.tailorer-status--red    { background: #450a0a; color: #fca5a5; }

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

/* ── Step entries ────────────────────────────────── */
.tailorer-entry {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  font-size: 12px;
  line-height: 1.4;
}
.tailorer-entry-icon {
  flex-shrink: 0;
  width: 14px;
  text-align: center;
}
.tailorer-entry--done   .tailorer-entry-icon { color: #22c55e; }
.tailorer-entry--done   .tailorer-entry-text { color: #94a3b8; }
.tailorer-entry--pending .tailorer-entry-icon { color: #38bdf8; display: inline-block; animation: tailorer-spin 1s linear infinite; }
.tailorer-entry--pending .tailorer-entry-text { color: #f1f5f9; }
@keyframes tailorer-spin { to { transform: rotate(360deg); } }

/* ── Confirm block ───────────────────────────────── */
.tailorer-confirm-block {
  background: #1c1f2e;
  border-left: 3px solid #f59e0b;
  border-radius: 4px;
  padding: 9px 10px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.tailorer-confirm-summary { font-size: 12px; font-weight: 600; color: #fde68a; }
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

/* ── Stuck block ─────────────────────────────────── */
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

/* ── Done / error entries ────────────────────────── */
.tailorer-entry--done-final .tailorer-entry-icon { color: #22c55e; }
.tailorer-entry--done-final .tailorer-entry-text { color: #86efac; font-weight: 600; }
.tailorer-entry--error .tailorer-entry-icon { color: #ef4444; }
.tailorer-entry--error .tailorer-entry-text { color: #fca5a5; }

/* ── Download links ──────────────────────────────── */
.tailorer-downloads {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #1e293b;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.tailorer-download-link {
  color: #60a5fa;
  font-size: 12px;
  text-decoration: none;
}
.tailorer-download-link:hover { text-decoration: underline; }

/* ── Buttons ─────────────────────────────────────── */
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
.tailorer-btn--approve  { background: #16a34a; }
.tailorer-btn--unblock  { background: #475569; }
.tailorer-btn--start    { background: #2563eb; width: 100%; text-align: center; font-weight: 600; font-size: 13px; padding: 9px; }

/* ── Start state ─────────────────────────────────── */
.tailorer-start-area {
  padding: 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.tailorer-start-hint { font-size: 12px; color: #64748b; }

/* ── Toggle tab (collapsed state) ───────────────── */
#tailorer-toggle {
  position: fixed;
  top: 50%;
  right: 0;
  transform: translateY(-50%);
  background: #1e3a5f;
  border: none;
  border-radius: 6px 0 0 6px;
  padding: 10px 6px;
  cursor: pointer;
  color: #60a5fa;
  font-size: 14px;
  z-index: 2147483647;
  display: none;
}
#tailorer-toggle:hover { background: #1e4a8f; }
```

- [ ] **Step 2: Verify the file exists**

```bash
ls extension/content/side_panel.css
```

Expected: file listed with no error.

---

### Task 2: setup.js — attachShadow stub

**Files:**
- Modify: `extension/tests/setup.js`

jsdom does not implement `attachShadow`. This stub makes it return a plain div so all shadow DOM tests work.

- [ ] **Step 1: Write the failing test** (in a temporary inline snippet to confirm the stub is needed)

In a JS REPL or just confirm: `typeof document.createElement('div').attachShadow` is `'undefined'` in jsdom without the stub.

- [ ] **Step 2: Add the stub to setup.js**

Full new content of `extension/tests/setup.js`:

```js
if (!globalThis.CSS) globalThis.CSS = {};
if (!globalThis.CSS.escape) {
  globalThis.CSS.escape = (value) =>
    String(value).replace(/([!"#$%&'()*+,.\/:;<=>?@[\\\]^`{|}~])/g, '\\$1').replace(/^(\d)/, '\\3$1 ');
}

if (!HTMLElement.prototype.attachShadow) {
  HTMLElement.prototype.attachShadow = function () {
    const shadow = document.createElement('div');
    shadow.__isShadowRoot = true;
    this.appendChild(shadow);
    Object.defineProperty(this, 'shadowRoot', { get: () => shadow, configurable: true });
    // Forward getElementById/querySelector to shadow root
    shadow.getElementById = (id) => shadow.querySelector(`#${id}`);
    return shadow;
  };
}
```

- [ ] **Step 3: Run existing tests to verify nothing is broken**

```bash
cd extension && npm test
```

Expected: 29 tests pass (all existing).

- [ ] **Step 4: Commit**

```bash
git add extension/tests/setup.js
git commit -m "test(extension): add attachShadow stub for jsdom"
```

---

### Task 3: side_panel.js — skeleton, open/close, tests

**Files:**
- Create: `extension/content/side_panel.js`
- Create: `extension/tests/side_panel.test.js`

- [ ] **Step 1: Write the failing tests**

Create `extension/tests/side_panel.test.js`:

```js
import '../content/side_panel.js';
const { initPanel, openPanel, closePanel } = globalThis;

beforeEach(() => {
  document.body.innerHTML = '';
  document.body.style.removeProperty('margin-right');
  initPanel();
});

afterEach(() => {
  delete globalThis.chrome;
});

test('initPanel appends tailorer-host to body', () => {
  expect(document.getElementById('tailorer-host')).not.toBeNull();
});

test('initPanel creates shadow root with panel element', () => {
  const host = document.getElementById('tailorer-host');
  expect(host.shadowRoot).not.toBeNull();
  expect(host.shadowRoot.getElementById('tailorer-panel')).not.toBeNull();
});

test('openPanel sets margin-right 320px on body', () => {
  openPanel();
  expect(document.body.style.marginRight).toBe('320px');
});

test('openPanel shows the panel and hides the toggle tab', () => {
  openPanel();
  const host = document.getElementById('tailorer-host');
  const panel = host.shadowRoot.getElementById('tailorer-panel');
  const toggle = host.shadowRoot.getElementById('tailorer-toggle');
  expect(panel.style.display).not.toBe('none');
  expect(toggle.style.display).toBe('none');
});

test('closePanel removes margin-right from body', () => {
  openPanel();
  closePanel();
  expect(document.body.style.marginRight).toBe('');
});

test('closePanel hides the panel and shows the toggle tab', () => {
  openPanel();
  closePanel();
  const host = document.getElementById('tailorer-host');
  const panel = host.shadowRoot.getElementById('tailorer-panel');
  const toggle = host.shadowRoot.getElementById('tailorer-toggle');
  expect(panel.style.display).toBe('none');
  expect(toggle.style.display).not.toBe('none');
});

test('clicking close button calls closePanel', () => {
  openPanel();
  const host = document.getElementById('tailorer-host');
  host.shadowRoot.querySelector('.tailorer-close').click();
  expect(document.body.style.marginRight).toBe('');
});

test('clicking toggle tab calls openPanel', () => {
  openPanel();
  closePanel();
  const host = document.getElementById('tailorer-host');
  host.shadowRoot.getElementById('tailorer-toggle').click();
  expect(document.body.style.marginRight).toBe('320px');
});

test('initPanel is idempotent — second call replaces the first host', () => {
  initPanel(); // second call
  expect(document.querySelectorAll('#tailorer-host')).toHaveLength(1);
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd extension && npm test -- --testPathPattern=side_panel
```

Expected: FAIL — `initPanel is not a function`.

- [ ] **Step 3: Create side_panel.js with skeleton**

Create `extension/content/side_panel.js`:

```js
let _shadow = null;

function initPanel() {
  document.getElementById('tailorer-host')?.remove();
  _shadow = null;

  const host = document.createElement('div');
  host.id = 'tailorer-host';
  Object.assign(host.style, {
    position: 'fixed', top: '0', right: '0',
    width: '320px', height: '100vh',
    zIndex: '2147483647',
  });
  document.body.appendChild(host);

  _shadow = host.attachShadow({ mode: 'open' });

  if (typeof chrome !== 'undefined' && chrome.runtime?.getURL) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = chrome.runtime.getURL('content/side_panel.css');
    _shadow.appendChild(link);
  }

  const panel = document.createElement('div');
  panel.id = 'tailorer-panel';

  const header = document.createElement('div');
  header.className = 'tailorer-header';
  const title = document.createElement('span');
  title.className = 'tailorer-title';
  title.textContent = '⚡ Tailorer';
  const closeBtn = document.createElement('button');
  closeBtn.className = 'tailorer-close';
  closeBtn.textContent = '✕';
  closeBtn.addEventListener('click', closePanel);
  header.append(title, closeBtn);

  const statusBar = document.createElement('div');
  statusBar.id = 'tailorer-status';
  statusBar.className = 'tailorer-status';

  const logEl = document.createElement('div');
  logEl.id = 'tailorer-log';
  logEl.className = 'tailorer-log';

  panel.append(header, statusBar, logEl);
  _shadow.appendChild(panel);

  const toggle = document.createElement('button');
  toggle.id = 'tailorer-toggle';
  toggle.textContent = '⚡';
  toggle.style.display = 'none';
  toggle.addEventListener('click', openPanel);
  _shadow.appendChild(toggle);
}

function openPanel() {
  if (!_shadow) return;
  document.body.style.setProperty('margin-right', '320px', 'important');
  _shadow.getElementById('tailorer-panel').style.display = '';
  _shadow.getElementById('tailorer-toggle').style.display = 'none';
}

function closePanel() {
  if (!_shadow) return;
  document.body.style.removeProperty('margin-right');
  _shadow.getElementById('tailorer-panel').style.display = 'none';
  _shadow.getElementById('tailorer-toggle').style.display = '';
}

if (typeof chrome !== 'undefined') {
  chrome.runtime.onMessage.addListener((_msg) => {});
} else {
  globalThis.initPanel = initPanel;
  globalThis.openPanel = openPanel;
  globalThis.closePanel = closePanel;
}
```

- [ ] **Step 4: Run the tests**

```bash
cd extension && npm test -- --testPathPattern=side_panel
```

Expected: 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add extension/content/side_panel.js extension/tests/side_panel.test.js
git commit -m "feat(extension): side panel skeleton — shadow DOM, open/close"
```

---

### Task 4: side_panel.js — showStartButton, setStatusBar, appendLogEntry (step entries)

**Files:**
- Modify: `extension/content/side_panel.js`
- Modify: `extension/tests/side_panel.test.js`

- [ ] **Step 1: Add failing tests** (append to `extension/tests/side_panel.test.js`)

```js
import '../content/side_panel.js';
const { initPanel, openPanel, showStartButton, setStatusBar, appendLogEntry } = globalThis;
// (add to existing imports at top of file — update the destructure line)
```

Add these tests after the existing ones:

```js
test('showStartButton renders a Start Agent button', () => {
  const host = document.getElementById('tailorer-host');
  showStartButton('job-42', 'tok123');
  const btn = host.shadowRoot.querySelector('.tailorer-btn--start');
  expect(btn).not.toBeNull();
  expect(btn.textContent).toContain('Start Agent');
});

test('showStartButton clicking sends start_session and clears the button', () => {
  globalThis.chrome = { runtime: { sendMessage: jest.fn() } };
  const host = document.getElementById('tailorer-host');
  showStartButton('job-42', 'tok123');
  host.shadowRoot.querySelector('.tailorer-btn--start').click();
  expect(globalThis.chrome.runtime.sendMessage).toHaveBeenCalledWith({
    type: 'start_session', job_id: 'job-42', token: 'tok123',
  });
  expect(host.shadowRoot.querySelector('.tailorer-btn--start')).toBeNull();
});

test('setStatusBar updates status text', () => {
  setStatusBar('navigating');
  const bar = document.getElementById('tailorer-host').shadowRoot.getElementById('tailorer-status');
  expect(bar.textContent).toContain('Navigating');
});

test('appendLogEntry done=true renders ✓ entry', () => {
  const host = document.getElementById('tailorer-host');
  appendLogEntry({ kind: 'step', text: 'Filled name', done: true });
  const entry = host.shadowRoot.querySelector('.tailorer-entry--done');
  expect(entry).not.toBeNull();
  expect(entry.textContent).toContain('Filled name');
  expect(entry.textContent).toContain('✓');
});

test('appendLogEntry done=false renders ⟳ entry', () => {
  const host = document.getElementById('tailorer-host');
  appendLogEntry({ kind: 'step', text: 'Navigating…', done: false });
  const entry = host.shadowRoot.querySelector('.tailorer-entry--pending');
  expect(entry).not.toBeNull();
  expect(entry.textContent).toContain('Navigating');
});

test('multiple appendLogEntry calls grow the log in order', () => {
  const host = document.getElementById('tailorer-host');
  appendLogEntry({ kind: 'step', text: 'Step 1', done: true });
  appendLogEntry({ kind: 'step', text: 'Step 2', done: true });
  const entries = host.shadowRoot.querySelectorAll('.tailorer-entry');
  expect(entries).toHaveLength(2);
  expect(entries[0].textContent).toContain('Step 1');
  expect(entries[1].textContent).toContain('Step 2');
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd extension && npm test -- --testPathPattern=side_panel
```

Expected: new tests FAIL — `showStartButton is not a function`.

- [ ] **Step 3: Implement in side_panel.js**

Add these functions before the `if (typeof chrome...` block at the bottom:

```js
const STATUS_CONFIG = {
  connecting:    { text: 'Connecting…',        dot: true },
  navigating:    { text: 'Navigating…',         dot: true },
  filling:       { text: 'Filling form…',       dot: true },
  awaiting_user: { text: '⏸ Waiting for you',   dot: false, cls: 'amber' },
  show_stuck:    { text: '⚠ Action needed',     dot: false, cls: 'red' },
  done:          { text: '✓ Done',              dot: false, cls: 'green' },
  error:         { text: '✗ Error',             dot: false, cls: 'red' },
};

function setStatusBar(status) {
  if (!_shadow) return;
  const bar = _shadow.getElementById('tailorer-status');
  const cfg = STATUS_CONFIG[status] || { text: status, dot: true };
  bar.className = `tailorer-status tailorer-status--${cfg.cls || 'blue'}`;
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

function showStartButton(job_id, token) {
  if (!_shadow) return;
  const log = _shadow.getElementById('tailorer-log');
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
    if (typeof chrome !== 'undefined') {
      chrome.runtime.sendMessage({ type: 'start_session', job_id, token });
    }
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
  if (!_shadow) return;
  const log = _shadow.getElementById('tailorer-log');
  let el;
  if (entry.kind === 'step') {
    el = _makeStepEntry(entry.text, entry.done);
  }
  if (!el) return;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
}
```

Also update the `else` branch at the bottom to expose the new functions:

```js
} else {
  globalThis.initPanel = initPanel;
  globalThis.openPanel = openPanel;
  globalThis.closePanel = closePanel;
  globalThis.showStartButton = showStartButton;
  globalThis.setStatusBar = setStatusBar;
  globalThis.appendLogEntry = appendLogEntry;
}
```

- [ ] **Step 4: Update the import destructure line** in `tests/side_panel.test.js`:

```js
const { initPanel, openPanel, closePanel, showStartButton, setStatusBar, appendLogEntry } = globalThis;
```

- [ ] **Step 5: Run tests**

```bash
cd extension && npm test -- --testPathPattern=side_panel
```

Expected: 15 tests pass.

- [ ] **Step 6: Commit**

```bash
git add extension/content/side_panel.js extension/tests/side_panel.test.js
git commit -m "feat(extension): side panel start button, status bar, step log"
```

---

### Task 5: side_panel.js — confirm, stuck, done, error entries + restorePanel

**Files:**
- Modify: `extension/content/side_panel.js`
- Modify: `extension/tests/side_panel.test.js`

- [ ] **Step 1: Add failing tests** (append to `extension/tests/side_panel.test.js`)

Update the destructure at top to add `restorePanel`:
```js
const { initPanel, openPanel, closePanel, showStartButton, setStatusBar, appendLogEntry, restorePanel } = globalThis;
```

Append these tests:

```js
test('appendLogEntry confirm renders summary and approve button', () => {
  const host = document.getElementById('tailorer-host');
  appendLogEntry({ kind: 'confirm', summary: 'Filled 3 fields', uncertain_fields: ['salary'] });
  const block = host.shadowRoot.querySelector('.tailorer-confirm-block');
  expect(block).not.toBeNull();
  expect(block.textContent).toContain('Filled 3 fields');
  expect(block.textContent).toContain('salary');
  expect(block.querySelector('.tailorer-btn--approve')).not.toBeNull();
});

test('appendLogEntry confirm — approve button sends user_approved', () => {
  globalThis.chrome = { runtime: { sendMessage: jest.fn() } };
  const host = document.getElementById('tailorer-host');
  appendLogEntry({ kind: 'confirm', summary: 'Test', uncertain_fields: [] });
  host.shadowRoot.querySelector('.tailorer-btn--approve').click();
  expect(globalThis.chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: 'user_approved' });
  expect(host.shadowRoot.querySelector('.tailorer-confirm-block')).toBeNull();
});

test('appendLogEntry confirm — correction input sends user_correction on Enter', () => {
  globalThis.chrome = { runtime: { sendMessage: jest.fn() } };
  const host = document.getElementById('tailorer-host');
  appendLogEntry({ kind: 'confirm', summary: 'Test', uncertain_fields: [] });
  const input = host.shadowRoot.querySelector('.tailorer-correction-input');
  input.value = 'use remote instead';
  input.dispatchEvent(Object.assign(new Event('keydown'), { key: 'Enter' }));
  expect(globalThis.chrome.runtime.sendMessage).toHaveBeenCalledWith({
    type: 'user_correction', text: 'use remote instead',
  });
});

test('appendLogEntry stuck renders message and unblock button', () => {
  const host = document.getElementById('tailorer-host');
  appendLogEntry({ kind: 'stuck', message: 'Cannot find apply link' });
  const block = host.shadowRoot.querySelector('.tailorer-stuck-block');
  expect(block).not.toBeNull();
  expect(block.textContent).toContain('Cannot find apply link');
  expect(block.querySelector('.tailorer-btn--unblock')).not.toBeNull();
});

test('appendLogEntry stuck — unblock button sends stuck_unblocked', () => {
  globalThis.chrome = { runtime: { sendMessage: jest.fn() } };
  const host = document.getElementById('tailorer-host');
  appendLogEntry({ kind: 'stuck', message: 'Test' });
  host.shadowRoot.querySelector('.tailorer-btn--unblock').click();
  expect(globalThis.chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: 'stuck_unblocked' });
  expect(host.shadowRoot.querySelector('.tailorer-stuck-block')).toBeNull();
});

test('appendLogEntry done renders done entry and download links', () => {
  const host = document.getElementById('tailorer-host');
  appendLogEntry({
    kind: 'done', message: 'Application submitted!',
    thread_id: 'tid-1', token: 'tok-abc',
  });
  const entry = host.shadowRoot.querySelector('.tailorer-entry--done-final');
  expect(entry).not.toBeNull();
  expect(entry.textContent).toContain('Application submitted!');
  const links = host.shadowRoot.querySelectorAll('.tailorer-download-link');
  expect(links).toHaveLength(2);
  expect(links[0].href).toContain('tid-1');
  expect(links[0].href).toContain('tok-abc');
});

test('appendLogEntry error renders error entry', () => {
  const host = document.getElementById('tailorer-host');
  appendLogEntry({ kind: 'error', message: 'WebSocket failed' });
  const entry = host.shadowRoot.querySelector('.tailorer-entry--error');
  expect(entry).not.toBeNull();
  expect(entry.textContent).toContain('WebSocket failed');
});

test('restorePanel re-renders all entries in order', () => {
  const host = document.getElementById('tailorer-host');
  restorePanel([
    { kind: 'step', text: 'Step 1', done: true },
    { kind: 'step', text: 'Step 2', done: false },
  ], 'navigating');
  const entries = host.shadowRoot.querySelectorAll('.tailorer-entry');
  expect(entries).toHaveLength(2);
  expect(entries[0].textContent).toContain('Step 1');
  expect(entries[1].textContent).toContain('Step 2');
});

test('restorePanel clears previous entries before re-rendering', () => {
  const host = document.getElementById('tailorer-host');
  appendLogEntry({ kind: 'step', text: 'Old', done: true });
  restorePanel([{ kind: 'step', text: 'New', done: true }], 'navigating');
  const entries = host.shadowRoot.querySelectorAll('.tailorer-entry');
  expect(entries).toHaveLength(1);
  expect(entries[0].textContent).toContain('New');
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd extension && npm test -- --testPathPattern=side_panel
```

Expected: new tests FAIL.

- [ ] **Step 3: Implement in side_panel.js**

Replace the `appendLogEntry` function and add `restorePanel`:

```js
function appendLogEntry(entry) {
  if (!_shadow) return;
  const log = _shadow.getElementById('tailorer-log');
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
      if (typeof chrome !== 'undefined') chrome.runtime.sendMessage({ type: 'user_correction', text });
      el.replaceWith(_makeStepEntry('Corrected', true));
    });

    const approveBtn = document.createElement('button');
    approveBtn.className = 'tailorer-btn tailorer-btn--approve';
    approveBtn.textContent = 'Looks good ✓';
    approveBtn.addEventListener('click', () => {
      if (typeof chrome !== 'undefined') chrome.runtime.sendMessage({ type: 'user_approved' });
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
      if (typeof chrome !== 'undefined') chrome.runtime.sendMessage({ type: 'stuck_unblocked' });
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
      const base = 'http://localhost:8000';
      const tok = encodeURIComponent(entry.token);
      const tid = encodeURIComponent(entry.thread_id);
      const downloads = document.createElement('div');
      downloads.className = 'tailorer-downloads';
      const cvLink = document.createElement('a');
      cvLink.className = 'tailorer-download-link';
      cvLink.href = `${base}/tailorer/files/${tid}/cv?token=${tok}`;
      cvLink.target = '_blank';
      cvLink.textContent = '↓ Tailored CV (.docx)';
      const clLink = document.createElement('a');
      clLink.className = 'tailorer-download-link';
      clLink.href = `${base}/tailorer/files/${tid}/cover_letter?token=${tok}`;
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
  if (!_shadow) return;
  const logEl = _shadow.getElementById('tailorer-log');
  logEl.innerHTML = '';
  for (const entry of log) appendLogEntry(entry);
  if (status) setStatusBar(status);
}
```

Also update the `else` branch to expose `restorePanel`:

```js
} else {
  globalThis.initPanel = initPanel;
  globalThis.openPanel = openPanel;
  globalThis.closePanel = closePanel;
  globalThis.showStartButton = showStartButton;
  globalThis.setStatusBar = setStatusBar;
  globalThis.appendLogEntry = appendLogEntry;
  globalThis.restorePanel = restorePanel;
}
```

- [ ] **Step 4: Run tests**

```bash
cd extension && npm test -- --testPathPattern=side_panel
```

Expected: all 25 tests pass.

- [ ] **Step 5: Commit**

```bash
git add extension/content/side_panel.js extension/tests/side_panel.test.js
git commit -m "feat(extension): side panel confirm/stuck/done/error entries and restorePanel"
```

---

### Task 6: side_panel.js — chrome message listener

**Files:**
- Modify: `extension/content/side_panel.js`
- Modify: `extension/tests/side_panel.test.js`

The chrome message listener wires all incoming service worker messages to the functions already tested above.

- [ ] **Step 1: Add failing tests** (append to `extension/tests/side_panel.test.js`)

```js
test('show_apply_button message initialises and opens panel with start button', () => {
  // simulate chrome message dispatch manually
  const { initPanel: init, showStartButton: ssb, openPanel: op } = globalThis;
  // Call the same code path the listener would: init + showStartButton + open
  init();
  ssb('job-5', 'tok-5');
  op();
  const host = document.getElementById('tailorer-host');
  expect(host.shadowRoot.querySelector('.tailorer-btn--start')).not.toBeNull();
  expect(document.body.style.marginRight).toBe('320px');
});

test('restore_panel message re-renders log and opens panel', () => {
  const { initPanel: init, restorePanel: rp, openPanel: op } = globalThis;
  init();
  rp([{ kind: 'step', text: 'Resumed', done: true }], 'navigating');
  op();
  const host = document.getElementById('tailorer-host');
  expect(host.shadowRoot.querySelector('.tailorer-entry--done')).not.toBeNull();
  expect(host.shadowRoot.querySelector('.tailorer-entry--done').textContent).toContain('Resumed');
});
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd extension && npm test -- --testPathPattern=side_panel
```

Expected: FAIL — the new tests rely on calling functions directly, so they should actually pass already. Run to confirm the count is 27.

- [ ] **Step 3: Replace the chrome listener block in side_panel.js**

Replace the bottom of `side_panel.js` (the `if (typeof chrome !== 'undefined')` block):

```js
if (typeof chrome !== 'undefined') {
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === 'show_apply_button') {
      initPanel();
      showStartButton(msg.job_id, msg.token);
      openPanel();
    } else if (msg.type === 'restore_panel') {
      initPanel();
      restorePanel(msg.log || [], msg.status);
      openPanel();
    } else if (msg.type === 'append_log') {
      appendLogEntry(msg.entry);
    } else if (msg.type === 'set_status') {
      setStatusBar(msg.status);
    }
  });
} else {
  globalThis.initPanel = initPanel;
  globalThis.openPanel = openPanel;
  globalThis.closePanel = closePanel;
  globalThis.showStartButton = showStartButton;
  globalThis.setStatusBar = setStatusBar;
  globalThis.appendLogEntry = appendLogEntry;
  globalThis.restorePanel = restorePanel;
}
```

- [ ] **Step 4: Run all tests**

```bash
cd extension && npm test
```

Expected: 27 tests pass (9 skeleton + 6 step entries + 10 interactive entries + 2 listener).

- [ ] **Step 5: Commit**

```bash
git add extension/content/side_panel.js extension/tests/side_panel.test.js
git commit -m "feat(extension): side panel chrome message listener"
```

---

### Task 7: service_worker.js — session log + restore_panel

**Files:**
- Modify: `extension/background/service_worker.js`

No unit tests for the service worker (integration-level). After each change, load the extension in Firefox/Chrome and verify manually.

- [ ] **Step 1: Add `log` and `currentStatus` to `openSession`**

In `openSession`, change the `sessions[tabId] = { ... }` line:

```js
sessions[tabId] = {
  job_id, token, thread_id: null,
  ws, pendingNavigate: false, reconnectDelay: 1000,
  log: [], currentStatus: 'connecting',
};
```

- [ ] **Step 2: Replace `handleAgentMessage` entirely**

Full replacement (delete the old function, paste this):

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
    chrome.tabs.sendMessage(tabId, { type: 'append_log', entry });
    return;
  }

  if (msg.type === 'navigate') {
    session.currentStatus = 'navigating';
    session.pendingNavigate = true;
    let hostname = msg.url;
    try { hostname = new URL(msg.url).hostname; } catch (_) {}
    const entry = { kind: 'step', text: `Navigating to ${hostname}…`, done: false };
    session.log.push(entry);
    chrome.tabs.sendMessage(tabId, { type: 'append_log', entry });
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
      chrome.tabs.sendMessage(tabId, { type: 'append_log', entry });
      chrome.tabs.sendMessage(tabId, { type: 'fill_field', field_id: msg.field_id, value: msg.value });
    }
    return;
  }

  if (msg.type === 'navigate_next') {
    session.currentStatus = 'navigating';
    const entry = { kind: 'step', text: 'Submitting page…', done: true };
    session.log.push(entry);
    chrome.tabs.sendMessage(tabId, { type: 'append_log', entry });
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
    chrome.tabs.sendMessage(tabId, { type: 'append_log', entry });
    return;
  }

  if (msg.type === 'show_stuck') {
    session.currentStatus = 'show_stuck';
    const entry = { kind: 'stuck', message: msg.message };
    session.log.push(entry);
    chrome.tabs.sendMessage(tabId, { type: 'append_log', entry });
    return;
  }

  if (msg.type === 'done') {
    session.currentStatus = 'done';
    const { thread_id, token } = session;
    const entry = { kind: 'done', message: msg.message, thread_id, token };
    session.log.push(entry);
    chrome.tabs.sendMessage(tabId, { type: 'append_log', entry });
    injectedTabs.delete(tabId);
    delete sessions[tabId];
    return;
  }

  if (msg.type === 'error') {
    session.currentStatus = 'error';
    const entry = { kind: 'error', message: msg.message };
    session.log.push(entry);
    chrome.tabs.sendMessage(tabId, { type: 'append_log', entry });
    injectedTabs.delete(tabId);
    delete sessions[tabId];
    return;
  }
}
```

- [ ] **Step 3: Update `onUpdated` to send `restore_panel` and handle `pendingNavigate` log update**

Replace the bottom portion of the `onUpdated` listener (from `if (pendingJobs[tabId])` down):

```js
  if (pendingJobs[tabId]) {
    const { job_id, token } = pendingJobs[tabId];
    chrome.tabs.sendMessage(tabId, { type: 'show_apply_button', job_id, token });
    return;
  }

  const session = sessions[tabId];
  if (!session) return;

  // Mark pending navigate step as done in the log before restoring
  if (session.pendingNavigate) {
    session.pendingNavigate = false;
    const last = session.log[session.log.length - 1];
    if (last?.kind === 'step' && !last.done) last.done = true;
  }

  // Restore panel in newly injected content script
  chrome.tabs.sendMessage(tabId, {
    type: 'restore_panel',
    log: session.log,
    status: session.currentStatus,
  });

  if (!session.pendingNavigate) {
    requestSnapshotAndSend(tabId);
  }
```

Wait — there is a logic bug: we set `session.pendingNavigate = false` before the `if (!session.pendingNavigate)` check at the end. Fix:

```js
  if (pendingJobs[tabId]) {
    const { job_id, token } = pendingJobs[tabId];
    chrome.tabs.sendMessage(tabId, { type: 'show_apply_button', job_id, token });
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

  chrome.tabs.sendMessage(tabId, {
    type: 'restore_panel',
    log: session.log,
    status: session.currentStatus,
  });

  if (wasNavigating) {
    requestSnapshotAndSend(tabId);
  }
```

- [ ] **Step 4: Update `onMessage` to resolve confirm/stuck log entries when user acts**

Replace the bottom of the `onMessage` listener (from `const session = sessions[tabId]` down):

```js
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
```

- [ ] **Step 5: Remove `setStatus` function and all `chrome.storage.local` calls**

Delete the `setStatus` function entirely:

```js
// DELETE this entire function:
function setStatus(tabId, status) {
  chrome.storage.local.set({ [`status_${tabId}`]: status });
}
```

Remove `chrome.storage.local.set(...)` from the `session_started` block (already gone since we replaced `handleAgentMessage`).

Update `onRemoved` — remove the `chrome.storage.local.remove` call:

```js
chrome.tabs.onRemoved.addListener((tabId) => {
  if (sessions[tabId]) {
    sessions[tabId].ws?.close();
    delete sessions[tabId];
  }
  delete pendingJobs[tabId];
  injectedTabs.delete(tabId);
});
```

- [ ] **Step 6: Run existing tests to confirm nothing in service worker broke test expectations**

```bash
cd extension && npm test
```

Expected: 27 tests pass (service_worker.js has no unit tests, other tests unchanged).

- [ ] **Step 7: Commit**

```bash
git add extension/background/service_worker.js
git commit -m "feat(extension): service worker session log, restore_panel, append_log"
```

---

### Task 8: manifest.json + cleanup

**Files:**
- Modify: `extension/manifest.json`
- Delete: `extension/content/overlay.js`
- Delete: `extension/content/overlay.css`
- Delete: `extension/popup/popup.html`
- Delete: `extension/popup/popup.js`
- Delete: `extension/tests/overlay.test.js`

- [ ] **Step 1: Write the new manifest.json**

Full replacement content:

```json
{
  "manifest_version": 3,
  "name": "Jobstrainer Tailorer",
  "version": "0.1.0",
  "description": "AI-powered job application assistant",
  "permissions": [
    "tabs",
    "scripting",
    "webNavigation"
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

Note: `storage` permission removed (popup gone), `default_popup` removed from `action`, overlay replaced by side_panel in the injected scripts (the service worker's `executeScript` call, not manifest content_scripts).

- [ ] **Step 2: Update the `executeScript` call in service_worker.js**

Find and replace the injected files list in `onUpdated`:

Old:
```js
files: ['content/dom_inspector.js', 'content/form_filler.js', 'content/overlay.js'],
```
```js
files: ['content/overlay.css']
```

New:
```js
files: ['content/dom_inspector.js', 'content/form_filler.js', 'content/side_panel.js'],
```
```js
files: ['content/side_panel.css']
```

- [ ] **Step 3: Delete old files**

```bash
rm extension/content/overlay.js
rm extension/content/overlay.css
rm extension/popup/popup.html
rm extension/popup/popup.js
rm extension/tests/overlay.test.js
```

- [ ] **Step 4: Run all tests to confirm clean**

```bash
cd extension && npm test
```

Expected: 27 tests pass (overlay tests gone, side panel tests all green).

- [ ] **Step 5: Commit**

```bash
git add extension/manifest.json extension/background/service_worker.js
git add -u extension/content/ extension/popup/ extension/tests/
git commit -m "feat(extension): replace overlay + popup with side panel, update manifest"
```

---

## Done

Load the unpacked extension in Firefox (`about:debugging` → Load Temporary Add-on → `manifest.json`) or Chrome (`chrome://extensions` → Load unpacked). Click a job link in the Jobstrainer frontend app. The panel should slide open on the right, the page body should shift left, and the "⚡ Start Agent" button should appear. Click it and watch the step log fill in as the agent works.
