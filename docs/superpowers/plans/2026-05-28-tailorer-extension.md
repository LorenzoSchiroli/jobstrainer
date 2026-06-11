# Tailorer Browser Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a WebExtensions Manifest V3 browser extension (Chrome + Firefox) that serves as the "hands" of the Tailorer LangGraph agent — navigating job pages, inspecting DOM fields, executing fill commands, and showing confirmation overlays in response to WebSocket commands from the backend.

**Architecture:** The service worker manages one WebSocket connection per active tab, routing JSON messages between the backend agent and content scripts. Tab activation is triggered when the user clicks a job link in the jobstrainer frontend (which writes `localStorage.tailorer_pending` + `localStorage.access_token`); the service worker detects the new tab via `chrome.tabs.onCreated`, reads those values from the opener tab, and injects content scripts once the tab loads. Three content scripts divide responsibilities: `dom_inspector.js` builds structured field snapshots, `form_filler.js` executes fill/click/file-upload commands, and `overlay.js` renders the Apply button and all user-facing banners.

**Tech Stack:** Vanilla JavaScript (ES modules), WebExtensions MV3, no build step, Jest + jest-environment-jsdom for unit tests

---

## File Structure

```
extension/
  manifest.json               -- MV3 manifest: permissions, service worker, action
  package.json                -- jest devDependency only (no build)
  jest.config.js
  background/
    service_worker.js         -- tab detection, WS session, message routing, file download
  content/
    dom_inspector.js          -- buildSnapshot() + resolveLabel(); responds to request_snapshot
    form_filler.js            -- fillField(), clickElement(), setFileOnInput(), clickNextOrSubmit()
    overlay.js                -- showApplyButton(), showConfirmBanner(), showStuckBanner(), showDoneBanner()
    overlay.css               -- fixed-position banner styles
  popup/
    popup.html                -- extension icon popup
    popup.js                  -- reads chrome.storage.local, renders status
  icons/
    icon16.png
    icon48.png
    icon128.png
  tests/
    dom_inspector.test.js
    form_filler.test.js
    overlay.test.js
```

---

## Background: WebSocket Protocol

The backend sends these message types to the extension (outbound from backend):

| type | fields | what extension does |
|------|--------|---------------------|
| `session_started` | `thread_id` | store thread_id for file downloads |
| `navigate` | `url` | navigate tab, wait for load, send back dom_snapshot |
| `request_snapshot` | — | build snapshot from current page, send back dom_snapshot |
| *(fill command)* | `field_id`, `value`, optional `type:"file"` | fill field or trigger file upload |
| `show_confirm` | `summary`, `uncertain_fields[]` | show confirm banner |
| `navigate_next` | — | click Next/Submit, send back `{submitted: bool}` |
| `show_stuck` | `message` | show stuck banner |
| `done` | `message` | show done banner, close session |
| `error` | `message` | show error banner |

The extension sends these to the backend (inbound to backend):

| type | fields | when |
|------|--------|------|
| dom_snapshot | `url`, `fields[]`, `links[]`, `buttons[]` | response to navigate or request_snapshot |
| `user_approved` | — | user clicks "Looks good, proceed" |
| `user_correction` | `text` | user types correction |
| `user_manual_edit` | `field_id`, `value` | user edits field directly (future) |
| `stuck_unblocked` | — | user clicks "Done, continue" on stuck banner |
| `{submitted: bool}` | — | response to navigate_next |

Fill commands from the backend are raw objects with `field_id` and `value`. If `type === "file"` or `value` is `"__CV__"` / `"__COVER_LETTER__"`, it's a file upload. Otherwise it's a regular field fill. The service worker detects this and handles accordingly.

---

### Task 1: Extension scaffold — manifest.json, icons, package.json, stub files

**Files:**
- Create: `extension/manifest.json`
- Create: `extension/package.json`
- Create: `extension/jest.config.js`
- Create: `extension/icons/icon16.png` (placeholder)
- Create: `extension/icons/icon48.png` (placeholder)
- Create: `extension/icons/icon128.png` (placeholder)
- Create: `extension/background/service_worker.js` (stub)
- Create: `extension/content/dom_inspector.js` (stub)
- Create: `extension/content/form_filler.js` (stub)
- Create: `extension/content/overlay.js` (stub)
- Create: `extension/content/overlay.css` (empty)
- Create: `extension/popup/popup.html` (stub)
- Create: `extension/popup/popup.js` (stub)
- Create: `extension/tests/` (directory)

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p extension/background extension/content extension/popup extension/icons extension/tests
```

- [ ] **Step 2: Create manifest.json**

Create `extension/manifest.json`:
```json
{
  "manifest_version": 3,
  "name": "Jobstrainer Tailorer",
  "version": "0.1.0",
  "description": "AI-powered job application assistant",
  "permissions": [
    "tabs",
    "scripting",
    "storage",
    "webNavigation"
  ],
  "host_permissions": [
    "http://localhost:8000/*",
    "https://*/*",
    "http://*/*"
  ],
  "background": {
    "service_worker": "background/service_worker.js"
  },
  "action": {
    "default_popup": "popup/popup.html",
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

- [ ] **Step 3: Create placeholder icons**

Run from `extension/` directory to create minimal valid PNG placeholder files:

```bash
cd extension && node -e "
const fs = require('fs');
// Minimal valid 1x1 transparent PNG
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64');
fs.writeFileSync('icons/icon16.png', png);
fs.writeFileSync('icons/icon48.png', png);
fs.writeFileSync('icons/icon128.png', png);
console.log('Icons created');
"
```

Expected output: `Icons created`

- [ ] **Step 4: Create package.json and jest.config.js**

Create `extension/package.json`:
```json
{
  "name": "jobstrainer-extension",
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "test": "node --experimental-vm-modules node_modules/.bin/jest"
  },
  "devDependencies": {
    "jest": "^29.7.0",
    "jest-environment-jsdom": "^29.7.0"
  }
}
```

Create `extension/jest.config.js`:
```javascript
export default {
  testEnvironment: 'jsdom',
  transform: {},
};
```

- [ ] **Step 5: Create stub source files**

`extension/background/service_worker.js`:
```javascript
// Tailorer service worker
const API_BASE = 'http://localhost:8000';
```

`extension/content/dom_inspector.js`:
```javascript
// DOM inspector — stub
```

`extension/content/form_filler.js`:
```javascript
// Form filler — stub
```

`extension/content/overlay.js`:
```javascript
// Overlay — stub
```

`extension/content/overlay.css`:
```css
/* Tailorer overlay styles */
```

`extension/popup/popup.html`:
```html
<!doctype html>
<html>
<head><meta charset="utf-8"><title>Tailorer</title></head>
<body>
  <p id="status">Idle</p>
  <script src="popup.js"></script>
</body>
</html>
```

`extension/popup/popup.js`:
```javascript
// Popup — stub
```

- [ ] **Step 6: Install test dependencies**

```bash
cd extension && npm install
```

Expected: `node_modules/` created with jest and jest-environment-jsdom, no errors.

- [ ] **Step 7: Verify extension loads in Chrome**

1. Open `chrome://extensions/` → enable "Developer mode"
2. Click "Load unpacked" → select the `extension/` directory
3. Extension appears in list without errors
4. Click the extension icon → popup shows "Idle"

- [ ] **Step 8: Commit**

```bash
git add extension/
git commit -m "feat(extension): scaffold MV3 extension with manifest, icons, and stubs"
```

---

### Task 2: dom_inspector.js — DOM field scanner and snapshot builder

Scans the current page for form fields and links, resolves labels, and returns a structured snapshot used by the backend agent for field mapping and navigation.

**Files:**
- Modify: `extension/content/dom_inspector.js`
- Create: `extension/tests/dom_inspector.test.js`

**Snapshot format** (what backend `nodes.py` expects):
```json
{
  "url": "https://example.com/apply",
  "fields": [
    {"id": "first_name", "label": "First Name", "type": "text", "value": ""},
    {"id": "country", "label": "Country", "type": "select", "value": "UK", "options": ["US", "UK"]},
    {"id": "resume", "label": "Resume", "type": "file"}
  ],
  "links": [
    {"text": "Apply Now", "label": "Apply Now", "href": "https://example.com/apply"}
  ],
  "buttons": [
    {"label": "Next", "selector": "#btn_0"}
  ]
}
```

`backend/backend/tailorer/nodes.py` uses `snapshot.get("links", [])` with `link.get("label")` / `link.get("text")` / `link.get("href")`. It also uses `snapshot.get("fields", [])` for field mapping.

- [ ] **Step 1: Write the failing test**

Create `extension/tests/dom_inspector.test.js`:
```javascript
import { buildSnapshot, resolveLabel } from '../content/dom_inspector.js';

describe('resolveLabel', () => {
  test('returns aria-label when present', () => {
    document.body.innerHTML = '<input id="f1" aria-label="Full Name" />';
    expect(resolveLabel(document.getElementById('f1'))).toBe('Full Name');
  });

  test('returns label[for] text when present', () => {
    document.body.innerHTML = '<label for="f2">Email</label><input id="f2" />';
    expect(resolveLabel(document.getElementById('f2'))).toBe('Email');
  });

  test('returns placeholder when no label or aria-label', () => {
    document.body.innerHTML = '<input id="f3" placeholder="Enter phone" />';
    expect(resolveLabel(document.getElementById('f3'))).toBe('Enter phone');
  });

  test('returns empty string when nothing available', () => {
    document.body.innerHTML = '<input id="f4" />';
    expect(resolveLabel(document.getElementById('f4'))).toBe('');
  });
});

describe('buildSnapshot', () => {
  test('captures text input with label', () => {
    document.body.innerHTML = `
      <label for="name">Full Name</label>
      <input id="name" type="text" value="Alice" />
    `;
    const snap = buildSnapshot();
    expect(snap.fields).toHaveLength(1);
    expect(snap.fields[0]).toEqual({ id: 'name', label: 'Full Name', type: 'text', value: 'Alice' });
  });

  test('captures select with current value and options list', () => {
    document.body.innerHTML = `
      <label for="country">Country</label>
      <select id="country">
        <option value="US">United States</option>
        <option value="UK" selected>United Kingdom</option>
      </select>
    `;
    const snap = buildSnapshot();
    expect(snap.fields[0].type).toBe('select');
    expect(snap.fields[0].value).toBe('UK');
    expect(snap.fields[0].options).toEqual(['United States', 'United Kingdom']);
  });

  test('captures file input without value property', () => {
    document.body.innerHTML = `
      <label for="resume">Resume</label>
      <input id="resume" type="file" />
    `;
    const snap = buildSnapshot();
    expect(snap.fields[0]).toEqual({ id: 'resume', label: 'Resume', type: 'file' });
    expect(snap.fields[0]).not.toHaveProperty('value');
  });

  test('captures links with text, label, and href', () => {
    document.body.innerHTML = `<a href="/apply">Apply Now</a>`;
    const snap = buildSnapshot();
    expect(snap.links[0]).toEqual({ text: 'Apply Now', label: 'Apply Now', href: '/apply' });
  });

  test('assigns generated id to elements without an id', () => {
    document.body.innerHTML = `<input type="text" placeholder="Name" />`;
    const snap = buildSnapshot();
    expect(snap.fields[0].id).toMatch(/^field_/);
  });

  test('excludes hidden and submit inputs', () => {
    document.body.innerHTML = `
      <input type="hidden" value="secret" />
      <input type="submit" value="Submit" />
      <input id="visible" type="text" value="hello" />
    `;
    const snap = buildSnapshot();
    expect(snap.fields).toHaveLength(1);
    expect(snap.fields[0].id).toBe('visible');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd extension && npm test -- tests/dom_inspector.test.js 2>&1 | tail -20
```

Expected: FAIL — tests error because `buildSnapshot` and `resolveLabel` are not exported from the stub.

- [ ] **Step 3: Implement dom_inspector.js**

Write `extension/content/dom_inspector.js`:
```javascript
export function resolveLabel(el) {
  if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();
  if (el.id) {
    const lbl = document.querySelector(`label[for="${el.id}"]`);
    if (lbl) return lbl.textContent.trim();
  }
  if (el.placeholder) return el.placeholder.trim();
  return '';
}

export function buildSnapshot() {
  let autoId = 0;
  const fields = [];

  document
    .querySelectorAll(
      'input:not([type="hidden"]):not([type="submit"]):not([type="button"])' +
      ':not([type="reset"]), select, textarea'
    )
    .forEach((el) => {
      if (!el.id) el.id = `field_${autoId++}`;
      const label = resolveLabel(el);
      const type = el.tagName === 'SELECT' ? 'select' : (el.type || 'text');

      if (type === 'file') {
        fields.push({ id: el.id, label, type: 'file' });
        return;
      }
      if (type === 'select') {
        fields.push({
          id: el.id,
          label,
          type: 'select',
          value: el.value,
          options: Array.from(el.options).map((o) => o.text),
        });
        return;
      }
      fields.push({ id: el.id, label, type, value: el.value });
    });

  const links = Array.from(document.querySelectorAll('a[href]')).map((a) => ({
    text: a.textContent.trim(),
    label: a.textContent.trim(),
    href: a.getAttribute('href'),
  }));

  const buttons = [];
  document.querySelectorAll('button, input[type="submit"]').forEach((btn, i) => {
    const label = btn.textContent?.trim() || btn.value?.trim() || '';
    if (!btn.id) btn.id = `btn_${i}`;
    buttons.push({ label, selector: `#${btn.id}` });
  });

  return {
    url: typeof location !== 'undefined' ? location.href : '',
    fields,
    links,
    buttons,
  };
}

// Respond to snapshot requests from the service worker
if (typeof chrome !== 'undefined') {
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type === 'request_snapshot') {
      sendResponse(buildSnapshot());
    }
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd extension && npm test -- tests/dom_inspector.test.js
```

Expected: PASS — all 10 tests green.

- [ ] **Step 5: Commit**

```bash
git add extension/content/dom_inspector.js extension/tests/dom_inspector.test.js
git commit -m "feat(extension): dom_inspector — field scanner and snapshot builder"
```

---

### Task 3: form_filler.js — fill commands executor

Executes fill commands dispatched by the service worker: sets field values (dispatching React-compatible synthetic events), clicks elements by CSS selector, sets files on file inputs via `DataTransfer`, and detects/clicks the Next or Submit button on the form.

**Files:**
- Modify: `extension/content/form_filler.js`
- Create: `extension/tests/form_filler.test.js`

Commands received via `chrome.runtime.onMessage`:
- `{ type: "fill_field", field_id, value }` — set value on input/select/textarea
- `{ type: "click", selector }` — click element
- `{ type: "do_file_upload", field_id, filename, buffer }` — reconstruct File and set on input
- `{ type: "navigate_next" }` — click Next/Submit; respond with `{ submitted: bool }`

- [ ] **Step 1: Write the failing test**

Create `extension/tests/form_filler.test.js`:
```javascript
import { fillField, clickElement, clickNextOrSubmit } from '../content/form_filler.js';

describe('fillField', () => {
  test('sets value on text input', () => {
    document.body.innerHTML = '<input id="name" type="text" />';
    fillField('name', 'Alice');
    expect(document.getElementById('name').value).toBe('Alice');
  });

  test('dispatches input and change events for React compatibility', () => {
    document.body.innerHTML = '<input id="email" type="email" />';
    const el = document.getElementById('email');
    const events = [];
    el.addEventListener('input', () => events.push('input'));
    el.addEventListener('change', () => events.push('change'));
    fillField('email', 'alice@example.com');
    expect(events).toEqual(['input', 'change']);
  });

  test('sets value on textarea', () => {
    document.body.innerHTML = '<textarea id="bio"></textarea>';
    fillField('bio', 'Hello world');
    expect(document.getElementById('bio').value).toBe('Hello world');
  });

  test('sets select by matching option text', () => {
    document.body.innerHTML = `
      <select id="country">
        <option value="US">United States</option>
        <option value="UK">United Kingdom</option>
      </select>
    `;
    fillField('country', 'United Kingdom');
    expect(document.getElementById('country').value).toBe('UK');
  });

  test('sets select by matching option value when text not found', () => {
    document.body.innerHTML = `
      <select id="emp">
        <option value="full_time">Full Time</option>
      </select>
    `;
    fillField('emp', 'full_time');
    expect(document.getElementById('emp').value).toBe('full_time');
  });

  test('does nothing silently when field not found', () => {
    expect(() => fillField('nonexistent', 'value')).not.toThrow();
  });
});

describe('clickElement', () => {
  test('clicks element by selector', () => {
    document.body.innerHTML = '<button id="next">Next</button>';
    let clicked = false;
    document.getElementById('next').addEventListener('click', () => { clicked = true; });
    clickElement('#next');
    expect(clicked).toBe(true);
  });

  test('does nothing silently when selector not found', () => {
    expect(() => clickElement('#missing')).not.toThrow();
  });
});

describe('clickNextOrSubmit', () => {
  test('returns submitted:true when clicking a submit button', () => {
    document.body.innerHTML = '<button id="sub">Submit Application</button>';
    const result = clickNextOrSubmit();
    expect(result.submitted).toBe(true);
  });

  test('returns submitted:false when clicking a next button', () => {
    document.body.innerHTML = '<button id="nxt">Next</button>';
    const result = clickNextOrSubmit();
    expect(result.submitted).toBe(false);
  });

  test('returns submitted:false when no button found', () => {
    document.body.innerHTML = '';
    const result = clickNextOrSubmit();
    expect(result.submitted).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd extension && npm test -- tests/form_filler.test.js 2>&1 | tail -20
```

Expected: FAIL — stub has no exports.

- [ ] **Step 3: Implement form_filler.js**

Write `extension/content/form_filler.js`:
```javascript
export function fillField(fieldId, value) {
  const el = document.getElementById(fieldId);
  if (!el) return;

  if (el.tagName === 'SELECT') {
    const match = Array.from(el.options).find((o) => o.text === value || o.value === value);
    if (match) el.value = match.value;
  } else {
    // Use native setter so React's synthetic event system detects the change
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    if (setter) setter.call(el, value);
    else el.value = value;
  }

  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

export function clickElement(selector) {
  document.querySelector(selector)?.click();
}

export function setFileOnInput(fieldId, filename, buffer) {
  const el = document.getElementById(fieldId);
  if (!el || el.type !== 'file') return;
  const file = new File([buffer], filename, {
    type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  });
  const dt = new DataTransfer();
  dt.items.add(file);
  el.files = dt.files;
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

const SUBMIT_KEYWORDS = ['submit', 'apply', 'send application', 'complete'];
const NEXT_KEYWORDS = ['next', 'continue', 'proceed', 'save'];

export function clickNextOrSubmit() {
  const buttons = Array.from(
    document.querySelectorAll('button, input[type="submit"]')
  );

  const submitBtn = buttons.find((b) => {
    const text = (b.textContent || b.value || '').toLowerCase();
    return SUBMIT_KEYWORDS.some((kw) => text.includes(kw));
  });
  if (submitBtn) {
    submitBtn.click();
    return { submitted: true };
  }

  const nextBtn = buttons.find((b) => {
    const text = (b.textContent || b.value || '').toLowerCase();
    return NEXT_KEYWORDS.some((kw) => text.includes(kw));
  });
  if (nextBtn) {
    nextBtn.click();
    return { submitted: false };
  }

  // Fallback: click first form button
  const fallback = buttons[0];
  if (fallback) {
    fallback.click();
    return { submitted: false };
  }

  return { submitted: false };
}

// Listen for commands from service worker
if (typeof chrome !== 'undefined') {
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type === 'fill_field') {
      fillField(msg.field_id, msg.value);
    } else if (msg.type === 'click') {
      clickElement(msg.selector);
    } else if (msg.type === 'do_file_upload') {
      setFileOnInput(msg.field_id, msg.filename, msg.buffer);
    } else if (msg.type === 'navigate_next') {
      sendResponse(clickNextOrSubmit());
      return true;
    }
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd extension && npm test -- tests/form_filler.test.js
```

Expected: PASS — all 11 tests green.

- [ ] **Step 5: Commit**

```bash
git add extension/content/form_filler.js extension/tests/form_filler.test.js
git commit -m "feat(extension): form_filler — fill, click, file upload, and navigate_next"
```

---

### Task 4: overlay.js + overlay.css — Apply button and confirmation banners

Injects all user-facing UI elements into the job page. Four elements, each with a unique DOM id so they can be removed cleanly:

- `tailorer-apply-btn` — floating "⚡ Apply with Agent" button (bottom-right)
- `tailorer-confirm-banner` — full-width bottom bar: fill summary + "Looks good" button + correction input
- `tailorer-stuck-banner` — full-width bottom bar: stuck message + "Done, continue" button
- `tailorer-done-banner` — full-width bottom bar: success message (auto-removes after 5 s)

**Files:**
- Modify: `extension/content/overlay.js`
- Modify: `extension/content/overlay.css`
- Create: `extension/tests/overlay.test.js`

- [ ] **Step 1: Write the failing test**

Create `extension/tests/overlay.test.js`:
```javascript
import {
  showApplyButton,
  showConfirmBanner,
  showStuckBanner,
  showDoneBanner,
  removeAllBanners,
} from '../content/overlay.js';

beforeEach(() => {
  document.body.innerHTML = '';
  removeAllBanners();
});

test('showApplyButton injects button with correct data attribute', () => {
  showApplyButton('job-123', 'tok');
  const btn = document.getElementById('tailorer-apply-btn');
  expect(btn).not.toBeNull();
  expect(btn.dataset.jobId).toBe('job-123');
});

test('showConfirmBanner injects banner containing summary text', () => {
  showConfirmBanner('Filled 5 fields on page 1', ['salary']);
  const banner = document.getElementById('tailorer-confirm-banner');
  expect(banner).not.toBeNull();
  expect(banner.textContent).toContain('Filled 5 fields');
});

test('showConfirmBanner lists uncertain fields', () => {
  showConfirmBanner('Done', ['salary', 'notice_period']);
  expect(document.getElementById('tailorer-confirm-banner').textContent).toContain('salary');
});

test('showStuckBanner injects banner with message', () => {
  showStuckBanner("Can't find careers page");
  const banner = document.getElementById('tailorer-stuck-banner');
  expect(banner).not.toBeNull();
  expect(banner.textContent).toContain("Can't find");
});

test('showDoneBanner injects done banner', () => {
  showDoneBanner('Application submitted!');
  expect(document.getElementById('tailorer-done-banner')).not.toBeNull();
});

test('removeAllBanners removes all injected elements', () => {
  showApplyButton('job-1', 'tok');
  showConfirmBanner('Test', []);
  removeAllBanners();
  expect(document.getElementById('tailorer-apply-btn')).toBeNull();
  expect(document.getElementById('tailorer-confirm-banner')).toBeNull();
});

test('showApplyButton replaces existing apply button', () => {
  showApplyButton('job-1', 'tok');
  showApplyButton('job-2', 'tok');
  expect(document.querySelectorAll('#tailorer-apply-btn')).toHaveLength(1);
  expect(document.getElementById('tailorer-apply-btn').dataset.jobId).toBe('job-2');
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd extension && npm test -- tests/overlay.test.js 2>&1 | tail -20
```

Expected: FAIL — stub has no exports.

- [ ] **Step 3: Implement overlay.js**

Write `extension/content/overlay.js`:
```javascript
const BANNER_IDS = [
  'tailorer-apply-btn',
  'tailorer-confirm-banner',
  'tailorer-stuck-banner',
  'tailorer-done-banner',
];

export function removeAllBanners() {
  BANNER_IDS.forEach((id) => document.getElementById(id)?.remove());
}

export function showApplyButton(job_id, token) {
  document.getElementById('tailorer-apply-btn')?.remove();
  const btn = document.createElement('button');
  btn.id = 'tailorer-apply-btn';
  btn.className = 'tailorer-apply-btn';
  btn.textContent = '⚡ Apply with Agent';
  btn.dataset.jobId = job_id;
  btn.addEventListener('click', () => {
    btn.remove();
    if (typeof chrome !== 'undefined') {
      chrome.runtime.sendMessage({ type: 'start_session', job_id, token });
    }
  });
  document.body.appendChild(btn);
}

export function showConfirmBanner(summary, uncertainFields) {
  document.getElementById('tailorer-confirm-banner')?.remove();

  const banner = document.createElement('div');
  banner.id = 'tailorer-confirm-banner';
  banner.className = 'tailorer-banner';

  const msg = document.createElement('span');
  msg.className = 'tailorer-banner__msg';
  msg.textContent = uncertainFields.length > 0
    ? `${summary} (uncertain: ${uncertainFields.join(', ')})`
    : summary;

  const approveBtn = document.createElement('button');
  approveBtn.className = 'tailorer-btn tailorer-btn--approve';
  approveBtn.textContent = 'Looks good, proceed';
  approveBtn.addEventListener('click', () => {
    banner.remove();
    if (typeof chrome !== 'undefined') {
      chrome.runtime.sendMessage({ type: 'user_approved' });
    }
  });

  const correctionInput = document.createElement('input');
  correctionInput.type = 'text';
  correctionInput.className = 'tailorer-correction-input';
  correctionInput.placeholder = 'Correct something? Type here and press Enter...';
  correctionInput.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    const text = correctionInput.value.trim();
    if (!text) return;
    banner.remove();
    if (typeof chrome !== 'undefined') {
      chrome.runtime.sendMessage({ type: 'user_correction', text });
    }
  });

  const correctBtn = document.createElement('button');
  correctBtn.className = 'tailorer-btn tailorer-btn--correct';
  correctBtn.textContent = 'Apply correction';
  correctBtn.addEventListener('click', () => {
    const text = correctionInput.value.trim();
    if (!text) return;
    banner.remove();
    if (typeof chrome !== 'undefined') {
      chrome.runtime.sendMessage({ type: 'user_correction', text });
    }
  });

  banner.append(msg, approveBtn, correctionInput, correctBtn);
  document.body.appendChild(banner);
}

export function showStuckBanner(message) {
  document.getElementById('tailorer-stuck-banner')?.remove();

  const banner = document.createElement('div');
  banner.id = 'tailorer-stuck-banner';
  banner.className = 'tailorer-banner tailorer-banner--stuck';

  const msg = document.createElement('span');
  msg.className = 'tailorer-banner__msg';
  msg.textContent = `⚠ Agent stuck: ${message}`;

  const unblockBtn = document.createElement('button');
  unblockBtn.className = 'tailorer-btn tailorer-btn--unblock';
  unblockBtn.textContent = 'Done, continue';
  unblockBtn.addEventListener('click', () => {
    banner.remove();
    if (typeof chrome !== 'undefined') {
      chrome.runtime.sendMessage({ type: 'stuck_unblocked' });
    }
  });

  banner.append(msg, unblockBtn);
  document.body.appendChild(banner);
}

export function showDoneBanner(message) {
  removeAllBanners();
  const banner = document.createElement('div');
  banner.id = 'tailorer-done-banner';
  banner.className = 'tailorer-banner tailorer-banner--done';
  banner.textContent = `✓ ${message}`;
  document.body.appendChild(banner);
  setTimeout(() => banner.remove(), 5000);
}

// Listen for messages from the service worker
if (typeof chrome !== 'undefined') {
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === 'show_apply_button') showApplyButton(msg.job_id, msg.token);
    else if (msg.type === 'show_confirm') showConfirmBanner(msg.summary, msg.uncertain_fields || []);
    else if (msg.type === 'show_stuck') showStuckBanner(msg.message);
    else if (msg.type === 'done') showDoneBanner(msg.message);
  });
}
```

- [ ] **Step 4: Implement overlay.css**

Write `extension/content/overlay.css`:
```css
.tailorer-apply-btn {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 2147483647;
  background: #2563eb;
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 12px 20px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);
  font-family: system-ui, sans-serif;
}

.tailorer-apply-btn:hover { background: #1d4ed8; }

.tailorer-banner {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 2147483647;
  background: #1e293b;
  color: #f1f5f9;
  padding: 14px 20px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: system-ui, sans-serif;
  font-size: 14px;
  box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.4);
  flex-wrap: wrap;
}

.tailorer-banner--stuck { background: #7c2d12; }
.tailorer-banner--done  { background: #14532d; }

.tailorer-banner__msg { flex: 1; min-width: 0; }

.tailorer-btn {
  border: none;
  border-radius: 6px;
  padding: 7px 14px;
  cursor: pointer;
  font-size: 13px;
  white-space: nowrap;
  color: #fff;
}

.tailorer-btn--approve  { background: #16a34a; }
.tailorer-btn--correct  { background: #475569; }
.tailorer-btn--unblock  { background: #475569; }
.tailorer-btn:hover     { filter: brightness(1.15); }

.tailorer-correction-input {
  flex: 1;
  min-width: 160px;
  background: #334155;
  color: #f1f5f9;
  border: 1px solid #475569;
  border-radius: 6px;
  padding: 7px 12px;
  font-size: 13px;
  font-family: system-ui, sans-serif;
}
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd extension && npm test -- tests/overlay.test.js
```

Expected: PASS — all 7 tests green.

- [ ] **Step 6: Commit**

```bash
git add extension/content/overlay.js extension/content/overlay.css extension/tests/overlay.test.js
git commit -m "feat(extension): overlay — apply button, confirm/stuck/done banners"
```

---

### Task 5: service_worker.js — WebSocket session manager and message router

The central coordinator. Manages one `sessions[tabId]` entry per active session. All state is in-memory; the WebSocket connection keeps the service worker alive (MV3 service workers are suspended only when idle with no open network connections).

**Files:**
- Modify: `extension/background/service_worker.js`

No unit tests (all logic depends on Chrome APIs and WebSocket — tested manually in Task 7).

**Key data structures:**
```javascript
pendingJobs[tabId] = { job_id, token }        // tab created, waiting to load
sessions[tabId] = {
  job_id, token, thread_id,                   // session identity
  ws,                                          // WebSocket instance
  pendingNavigate,                             // bool: waiting for tab to finish loading after navigate
  reconnectDelay,                              // ms, doubles on each reconnect (max 30 s)
}
```

**Message routing:**
- `chrome.tabs.onCreated` → read `tailorer_pending` + `access_token` from opener tab's localStorage → store in `pendingJobs`
- `chrome.tabs.onUpdated` (status=complete) → inject content scripts → if `pendingJobs`, show Apply button; if `sessions[tabId].pendingNavigate`, request + send snapshot
- `chrome.runtime.onMessage` from content scripts → route to WS or handle `start_session`
- `ws.onmessage` → `handleAgentMessage(tabId, msg)` → dispatch to content scripts or handle internally

**File upload flow:**
Agent sends a fill command where `value === "__CV__"` or `value === "__COVER_LETTER__"` with `type === "file"`. Service worker fetches the file from `GET /tailorer/files/{thread_id}/{cv|cover_letter}?token=...` as `ArrayBuffer`, then sends `{ type: "do_file_upload", field_id, filename, buffer }` to the content script.

- [ ] **Step 1: Implement service_worker.js**

Write `extension/background/service_worker.js`:
```javascript
const API_BASE = 'http://localhost:8000';

const pendingJobs = {};  // tabId -> { job_id, token }
const sessions = {};     // tabId -> { job_id, token, thread_id, ws, pendingNavigate, reconnectDelay }

// ── Tab detection ──────────────────────────────────────────────────────────

chrome.tabs.onCreated.addListener(async (tab) => {
  if (!tab.openerTabId) return;
  try {
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: tab.openerTabId },
      func: () => ({
        pending: localStorage.getItem('tailorer_pending'),
        token: localStorage.getItem('access_token'),
      }),
    });
    const { pending, token } = result.result;
    if (!pending || !token) return;
    const { job_id } = JSON.parse(pending);
    // Clear pending so it doesn't re-trigger on subsequent reloads
    await chrome.scripting.executeScript({
      target: { tabId: tab.openerTabId },
      func: () => localStorage.removeItem('tailorer_pending'),
    });
    pendingJobs[tab.id] = { job_id, token };
  } catch (_) {
    // Opener tab may be inaccessible (different extension origin)
  }
});

// ── Content script injection ───────────────────────────────────────────────

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo) => {
  if (changeInfo.status !== 'complete') return;
  if (!pendingJobs[tabId] && !sessions[tabId]) return;

  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ['content/dom_inspector.js', 'content/form_filler.js', 'content/overlay.js'],
    });
    await chrome.scripting.insertCSS({ target: { tabId }, files: ['content/overlay.css'] });
  } catch (_) {
    return; // Tab not injectable (e.g., chrome:// URL, PDF)
  }

  if (pendingJobs[tabId]) {
    const { job_id, token } = pendingJobs[tabId];
    chrome.tabs.sendMessage(tabId, { type: 'show_apply_button', job_id, token });
    return;
  }

  const session = sessions[tabId];
  if (session?.pendingNavigate) {
    session.pendingNavigate = false;
    requestSnapshotAndSend(tabId);
  }
});

// ── Messages from content scripts ─────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender) => {
  const tabId = sender.tab?.id;
  if (!tabId) return;

  if (msg.type === 'start_session') {
    delete pendingJobs[tabId];
    openSession(tabId, msg.job_id, msg.token);
    return;
  }

  const session = sessions[tabId];
  if (!session?.ws || session.ws.readyState !== WebSocket.OPEN) return;

  if (['user_approved', 'user_correction', 'user_manual_edit', 'stuck_unblocked'].includes(msg.type)) {
    session.ws.send(JSON.stringify(msg));
  }
});

// ── WebSocket session lifecycle ────────────────────────────────────────────

function openSession(tabId, job_id, token) {
  const wsUrl = `ws://localhost:8000/tailorer/ws/${job_id}?token=${encodeURIComponent(token)}`;
  const ws = new WebSocket(wsUrl);

  sessions[tabId] = {
    job_id, token, thread_id: null,
    ws, pendingNavigate: false, reconnectDelay: 1000,
  };

  ws.onmessage = (event) => {
    try { handleAgentMessage(tabId, JSON.parse(event.data)); } catch (_) {}
  };

  ws.onclose = () => {
    const s = sessions[tabId];
    if (!s) return;
    const delay = Math.min(s.reconnectDelay * 2, 30000);
    s.reconnectDelay = delay;
    setTimeout(() => { if (sessions[tabId]) openSession(tabId, s.job_id, s.token); }, delay);
  };

  ws.onerror = () => {};
}

// ── Agent message dispatch ─────────────────────────────────────────────────

async function handleAgentMessage(tabId, msg) {
  const session = sessions[tabId];
  if (!session) return;

  if (msg.type === 'session_started') {
    session.thread_id = msg.thread_id;
    session.reconnectDelay = 1000;
    setStatus(tabId, 'navigating');
    chrome.storage.local.set({
      [`session_${tabId}`]: { job_id: session.job_id, token: session.token, thread_id: msg.thread_id },
    });
    return;
  }

  if (msg.type === 'navigate') {
    setStatus(tabId, 'navigating');
    session.pendingNavigate = true;
    chrome.tabs.update(tabId, { url: msg.url });
    return;
  }

  if (msg.type === 'request_snapshot') {
    requestSnapshotAndSend(tabId);
    return;
  }

  // Fill command: regular field or file upload
  if (msg.field_id !== undefined) {
    if (msg.type === 'file' || msg.value === '__CV__' || msg.value === '__COVER_LETTER__') {
      await handleFileUpload(tabId, msg);
    } else {
      chrome.tabs.sendMessage(tabId, { type: 'fill_field', field_id: msg.field_id, value: msg.value });
    }
    return;
  }

  if (msg.type === 'navigate_next') {
    setStatus(tabId, 'navigating');
    chrome.tabs.sendMessage(tabId, { type: 'navigate_next' }, (response) => {
      if (session.ws.readyState === WebSocket.OPEN) {
        session.ws.send(JSON.stringify(response || { submitted: false }));
      }
    });
    return;
  }

  if (msg.type === 'show_confirm') {
    setStatus(tabId, 'awaiting_user');
    chrome.tabs.sendMessage(tabId, msg);
    return;
  }

  if (msg.type === 'show_stuck') {
    setStatus(tabId, 'show_stuck');
    chrome.tabs.sendMessage(tabId, msg);
    return;
  }

  if (msg.type === 'done') {
    setStatus(tabId, 'done');
    chrome.tabs.sendMessage(tabId, msg);
    chrome.storage.local.remove([`status_${tabId}`]);
    delete sessions[tabId];
    return;
  }

  if (msg.type === 'error') {
    setStatus(tabId, 'error');
    chrome.tabs.sendMessage(tabId, msg);
    return;
  }
}

// ── Helpers ────────────────────────────────────────────────────────────────

function requestSnapshotAndSend(tabId) {
  const session = sessions[tabId];
  chrome.tabs.sendMessage(tabId, { type: 'request_snapshot' }, (snapshot) => {
    if (snapshot && session?.ws?.readyState === WebSocket.OPEN) {
      session.ws.send(JSON.stringify(snapshot));
    }
  });
}

async function handleFileUpload(tabId, msg) {
  const session = sessions[tabId];
  const fileType = msg.value === '__CV__' ? 'cv' : 'cover_letter';
  const filename = fileType === 'cv' ? 'tailored_cv.docx' : 'cover_letter.docx';
  const url = `${API_BASE}/tailorer/files/${session.thread_id}/${fileType}?token=${encodeURIComponent(session.token)}`;
  try {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const buffer = await resp.arrayBuffer();
    chrome.tabs.sendMessage(tabId, { type: 'do_file_upload', field_id: msg.field_id, filename, buffer });
  } catch (err) {
    console.error('[tailorer] file download failed:', err);
  }
}

function setStatus(tabId, status) {
  chrome.storage.local.set({ [`status_${tabId}`]: status });
}
```

- [ ] **Step 2: Reload extension and check service worker console**

1. Go to `chrome://extensions/` → reload the Tailorer extension
2. Click "Service Worker" link → DevTools console opens
3. Check console — should be empty (no errors on load)

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add extension/background/service_worker.js
git commit -m "feat(extension): service_worker — WebSocket session manager and message router"
```

---

### Task 6: popup.html + popup.js — session status display

The extension icon popup shows the current session status for the active tab and, when the session is done, provides links to download the tailored CV and cover letter.

**Files:**
- Modify: `extension/popup/popup.html`
- Modify: `extension/popup/popup.js`

- [ ] **Step 1: Implement popup.html**

Write `extension/popup/popup.html`:
```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Tailorer</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      min-width: 220px;
      padding: 16px;
      font-family: system-ui, sans-serif;
      background: #0f172a;
      color: #f1f5f9;
    }
    h1 { font-size: 15px; font-weight: 700; margin-bottom: 12px; color: #60a5fa; }
    #status {
      font-size: 13px;
      padding: 6px 10px;
      border-radius: 6px;
      background: #1e293b;
      display: inline-block;
    }
    .st-navigating  { background: #1e3a5f; color: #93c5fd; }
    .st-filling     { background: #1e3a5f; color: #93c5fd; }
    .st-awaiting_user { background: #713f12; color: #fde68a; }
    .st-done        { background: #14532d; color: #86efac; }
    .st-error, .st-show_stuck { background: #7f1d1d; color: #fca5a5; }
    #files { margin-top: 12px; display: none; }
    #files a {
      display: block;
      color: #60a5fa;
      font-size: 12px;
      margin-top: 6px;
      text-decoration: none;
    }
    #files a:hover { text-decoration: underline; }
  </style>
</head>
<body>
  <h1>⚡ Tailorer</h1>
  <div id="status">Idle</div>
  <div id="files">
    <a id="cv-link" href="#" target="_blank">↓ Download tailored CV</a>
    <a id="cl-link" href="#" target="_blank">↓ Download cover letter</a>
  </div>
  <script src="popup.js"></script>
</body>
</html>
```

- [ ] **Step 2: Implement popup.js**

Write `extension/popup/popup.js`:
```javascript
const STATUS_LABELS = {
  connecting:    'Connecting...',
  navigating:    'Navigating...',
  filling:       'Filling form...',
  awaiting_user: 'Waiting for you ⏸',
  done:          'Done ✓',
  error:         'Error ✗',
  show_stuck:    'Stuck — action needed ⚠',
};

(async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) return;

  const tabId = tab.id;
  const stored = await chrome.storage.local.get([`status_${tabId}`, `session_${tabId}`]);
  const status = stored[`status_${tabId}`];
  const session = stored[`session_${tabId}`];

  const statusEl = document.getElementById('status');
  if (status) {
    statusEl.textContent = STATUS_LABELS[status] || status;
    statusEl.className = `st-${status}`;
  }

  if (status === 'done' && session?.thread_id) {
    const base = 'http://localhost:8000';
    const tok = encodeURIComponent(session.token || '');
    const tid = session.thread_id;
    document.getElementById('cv-link').href = `${base}/tailorer/files/${tid}/cv?token=${tok}`;
    document.getElementById('cl-link').href = `${base}/tailorer/files/${tid}/cover_letter?token=${tok}`;
    document.getElementById('files').style.display = 'block';
  }
})();
```

- [ ] **Step 3: Verify popup renders**

1. Reload extension in `chrome://extensions/`
2. Open any tab → click the extension icon
3. Popup shows "Idle" for tabs with no active session
4. Status element has no extra CSS class applied in idle state

- [ ] **Step 4: Commit**

```bash
git add extension/popup/popup.html extension/popup/popup.js
git commit -m "feat(extension): popup — session status and file download links"
```

---

### Task 7: Run all extension tests

Run the complete test suite and confirm all tests pass.

**Files:** No changes — verification only.

- [ ] **Step 1: Run all tests**

```bash
cd extension && npm test
```

Expected output:
```
PASS tests/dom_inspector.test.js
PASS tests/form_filler.test.js
PASS tests/overlay.test.js

Test Suites: 3 passed, 3 total
Tests:       28 passed, 28 total
```

If any test fails, fix the relevant source file and re-run before proceeding.

- [ ] **Step 2: Verify extension loads cleanly in Chrome**

1. `chrome://extensions/` → reload the Tailorer extension
2. No errors in the extension card
3. Service worker link → DevTools → Console is empty
4. Click any tab → click extension icon → "Idle" shows

- [ ] **Step 3: Commit**

No code change; if fixes were needed in step 1, commit them:
```bash
git add extension/
git commit -m "fix(extension): test suite fixes"
```

---

### Task 8: End-to-end manual integration test

Verify the complete flow with the backend running: tab detection → Apply button → WebSocket → navigation → fill → confirm → done.

**Prerequisites:**
- Backend running at `http://localhost:8000` (`cd backend && uv run uvicorn backend.main:app --reload`)
- Frontend running at `http://localhost:3000` (`cd frontend && npm run dev`)
- At least one user account with a CV uploaded
- At least one job in the database with a `company.website` set
- Extension loaded in Chrome (Developer mode)

- [ ] **Step 1: Start services**

```bash
# Terminal 1
docker compose up -d postgres opensearch

# Terminal 2
cd backend && uv run alembic upgrade head && uv run uvicorn backend.main:app --reload

# Terminal 3
cd frontend && npm run dev
```

- [ ] **Step 2: Open service worker DevTools**

1. `chrome://extensions/` → find Tailorer → click "Service Worker"
2. DevTools opens. Pin this window — you'll watch the console throughout.

- [ ] **Step 3: Log in and click a job**

1. Go to `http://localhost:3000` → log in → search for jobs
2. Click a job link
3. Service worker console: `pendingJobs` receives an entry (add a `console.log('[tailorer] pending job stored:', tabId, job_id)` temporarily if needed)
4. New tab opens on the job board

Expected: `⚡ Apply with Agent` button appears at bottom-right of the job board page.

- [ ] **Step 4: Verify Apply button activation**

1. Service worker console: no errors
2. Button is visible at bottom-right
3. Popup (click extension icon) shows "Idle" → switches to "Connecting..." after step 5

- [ ] **Step 5: Start session**

1. Click `⚡ Apply with Agent`
2. Service worker console: WebSocket opens, `session_started` message received, `thread_id` logged
3. Backend console (uvicorn): `GET /tailorer/ws/{job_id}` 101 Switching Protocols
4. Popup: shows "Navigating..."

Expected: Agent begins navigating. Tab URL changes to company homepage.

- [ ] **Step 6: Navigate flow**

1. Tab navigates through: company homepage → careers page → job listing → apply form
2. Each navigation: content scripts re-inject automatically, snapshot sent back to backend
3. Backend console: agent processes snapshots, selects navigation targets

Expected: No errors. Tab ends up on the application form URL.

- [ ] **Step 7: Confirm overlay**

1. Confirm banner appears at bottom of the application form page
2. Banner text: "Filled N fields on page 1" + uncertain field names if any
3. Verify form fields are populated with data from the applicant profile

Expected: Fields match profile data (name, email, etc.).

- [ ] **Step 8: Approve and complete**

1. Click "Looks good, proceed"
2. Agent navigates to next page (or submits if single-page form)
3. After final submit: done banner appears: "✓ Application submitted!"
4. Popup: "Done ✓" with download links visible

- [ ] **Step 9: Download tailored files (optional)**

1. Click extension icon → "Done ✓" → "↓ Download tailored CV"
2. File downloads as `tailored_cv.docx`
3. Verify it opens and contains tailored content

- [ ] **Step 10: Commit integration fixes**

If any issues were found and fixed during manual testing, commit them:
```bash
git add extension/
git commit -m "fix(extension): integration fixes from end-to-end test"
```
