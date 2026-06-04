# Extension Nanobrowser Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the shallow DOM inspection + synthetic-event extension with nanobrowser's production-grade browser control stack (buildDomTree.js + puppeteer-core CDP), update the WebSocket protocol to use indexed elements and batched actions, rewrite the panel in React, and update backend agent prompts to match.

**Architecture:** The extension becomes a TypeScript + React + Vite project. The service worker ports nanobrowser's `browser/` layer (Page class + DOMService) and drives all browser interaction via CDP instead of content scripts. The backend LangGraph nodes are updated to use the new indexed-element snapshot format and nanobrowser-style multi-action batched prompts; the graph structure and interrupt pattern are unchanged.

**Tech Stack:** TypeScript, React 18, Vite 5, puppeteer-core (ExtensionTransport), Chrome MV3, Python/FastAPI (backend), LangGraph, pytest, vitest

**Nanobrowser source reference:** `/tmp/nanobrowser/chrome-extension/` (already cloned)

---

## File Map

### Extension — new/rewritten
| File | Action | Purpose |
|---|---|---|
| `extension/package.json` | Create | deps: puppeteer-core, react, vite, typescript, vitest |
| `extension/tsconfig.json` | Create | TypeScript config |
| `extension/vite.config.ts` | Create | Two builds: SW (IIFE) + sidepanel (React) |
| `extension/manifest.json` | Modify | Chrome MV3 only, add debugger+webNavigation perms, module SW |
| `extension/public/buildDomTree.js` | Copy from nanobrowser | Injected into pages for DOM tree building |
| `extension/background/browser/dom/raw_types.ts` | Port | Raw DOM node types from buildDomTree output |
| `extension/background/browser/dom/history/view.ts` | Port | HashedDomElement, CoordinateSet, ViewportInfo |
| `extension/background/browser/dom/history/service.ts` | Port | ClickableElementProcessor, element hashing |
| `extension/background/browser/dom/views.ts` | Port | DOMElementNode, DOMTextNode, clickableElementsToString() |
| `extension/background/browser/dom/service.ts` | Port | injectBuildDomTreeScripts(), getClickableElements(), getScrollInfo() |
| `extension/background/browser/dom/clickable/service.ts` | Port | getClickableElements(), hashDomElement() |
| `extension/background/browser/util.ts` | Port | isNewTabPage(), capTextLength() |
| `extension/background/browser/page.ts` | Port + adapt | Page class: attachPuppeteer, snapshot(), clickElement(), typeText(), selectOption(), scroll(), sendKeys(), navigate(), goBack(), wait() |
| `extension/background/service_worker.ts` | Rewrite | Session lifecycle, WS, action dispatch via Page |
| `extension/sidepanel/index.html` | Rewrite | React mount point |
| `extension/sidepanel/src/main.tsx` | Create | React entry |
| `extension/sidepanel/src/App.tsx` | Create | Port connection, session state machine |
| `extension/sidepanel/src/components/LogEntry.tsx` | Create | Single feed message |
| `extension/sidepanel/src/components/ConfirmBlock.tsx` | Create | Uncertain fields + file links |
| `extension/sidepanel/src/components/StuckBlock.tsx` | Create | Stuck message (rendered as LogEntry variant) |
| `extension/sidepanel/src/components/StatusBar.tsx` | Create | Status pill in header |
| `extension/content/dom_inspector.js` | Delete | |
| `extension/content/form_filler.js` | Delete | |

### Backend — modified
| File | Action | Purpose |
|---|---|---|
| `backend/backend/tailorer/state.py` | Modify | Snapshot shape + nav_memory field |
| `backend/backend/tailorer/router.py` | Modify | execute_actions handler, index-based fill_and_confirm |
| `backend/backend/tailorer/nodes.py` | Modify | Rewrite _decide_next_navigation + _map_fields_sync, add nav_memory |
| `backend/tests/tailorer/test_nodes.py` | Modify | Update existing tests + add new ones |

---

## Task 1: Extension build tooling

**Files:**
- Create: `extension/package.json`
- Create: `extension/tsconfig.json`
- Create: `extension/vite.config.ts`

- [ ] **Step 1: Create package.json**

```json
{
  "name": "jobstrainer-tailorer-extension",
  "version": "0.2.0",
  "private": true,
  "scripts": {
    "build": "vite build",
    "build:watch": "vite build --watch",
    "test": "vitest run"
  },
  "dependencies": {
    "puppeteer-core": "^23.0.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@types/chrome": "^0.0.268",
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.3",
    "vite": "^5.3.4",
    "vitest": "^2.0.3"
  }
}
```

- [ ] **Step 2: Create tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "strict": true,
    "skipLibCheck": true,
    "jsx": "react-jsx",
    "baseUrl": ".",
    "paths": {
      "@background/*": ["./background/*"],
      "@sidepanel/*": ["./sidepanel/src/*"]
    }
  },
  "include": ["background/**/*", "sidepanel/src/**/*", "content/**/*"]
}
```

- [ ] **Step 3: Create vite.config.ts**

The service worker must be built as a self-contained IIFE (no dynamic imports at runtime). The sidepanel is a standard React app.

```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';

export default defineConfig(({ mode }) => {
  const isServiceWorker = process.env.ENTRY === 'sw';

  if (isServiceWorker) {
    return {
      build: {
        outDir: 'dist',
        emptyOutDir: false,
        lib: {
          entry: resolve(__dirname, 'background/service_worker.ts'),
          name: 'ServiceWorker',
          formats: ['iife'],
          fileName: () => 'background/service_worker.js',
        },
        rollupOptions: {
          output: { inlineDynamicImports: true },
        },
      },
      resolve: {
        alias: { '@background': resolve(__dirname, 'background') },
      },
    };
  }

  return {
    plugins: [react()],
    build: {
      outDir: 'dist/sidepanel',
      emptyOutDir: false,
      rollupOptions: {
        input: resolve(__dirname, 'sidepanel/index.html'),
      },
    },
    resolve: {
      alias: { '@sidepanel': resolve(__dirname, 'sidepanel/src') },
    },
  };
});
```

- [ ] **Step 4: Update package.json scripts for dual build**

Replace the `build` script with:
```json
"build": "cp manifest.json dist/ && cp -r public/* dist/ && ENTRY=sw vite build && vite build",
"build:watch": "ENTRY=sw vite build --watch"
```

- [ ] **Step 5: Install dependencies**

```bash
cd /Users/loryschi/projects/jobstrainer/extension
npm install
```

Expected: `node_modules/` created, no errors.

- [ ] **Step 6: Create minimal stubs to verify build compiles**

Create `extension/background/service_worker.ts`:
```typescript
console.log('service worker loaded');
```

Create `extension/sidepanel/index.html`:
```html
<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Tailorer</title></head>
<body><div id="root"></div><script type="module" src="/sidepanel/src/main.tsx"></script></body>
</html>
```

Create `extension/sidepanel/src/main.tsx`:
```typescript
import React from 'react';
import { createRoot } from 'react-dom/client';
createRoot(document.getElementById('root')!).render(<div>Tailorer</div>);
```

- [ ] **Step 7: Run the build**

```bash
cd /Users/loryschi/projects/jobstrainer/extension
mkdir -p dist
npm run build
```

Expected: `dist/background/service_worker.js` and `dist/sidepanel/index.html` created. No errors.

- [ ] **Step 8: Commit**

```bash
cd /Users/loryschi/projects/jobstrainer
git add extension/package.json extension/tsconfig.json extension/vite.config.ts extension/sidepanel/index.html extension/sidepanel/src/main.tsx extension/background/service_worker.ts
git commit -m "feat(extension): add TypeScript + React + Vite build tooling"
```

---

## Task 2: Port DOM types and history

**Files:**
- Create: `extension/background/browser/dom/raw_types.ts`
- Create: `extension/background/browser/dom/history/view.ts`
- Create: `extension/background/browser/dom/history/service.ts`
- Create: `extension/background/browser/util.ts`

- [ ] **Step 1: Copy raw_types.ts verbatim from nanobrowser**

```bash
cp /tmp/nanobrowser/chrome-extension/src/background/browser/dom/raw_types.ts \
   /Users/loryschi/projects/jobstrainer/extension/background/browser/dom/raw_types.ts
```

- [ ] **Step 2: Copy history/view.ts verbatim from nanobrowser**

```bash
mkdir -p /Users/loryschi/projects/jobstrainer/extension/background/browser/dom/history
cp /tmp/nanobrowser/chrome-extension/src/background/browser/dom/history/view.ts \
   /Users/loryschi/projects/jobstrainer/extension/background/browser/dom/history/view.ts
```

- [ ] **Step 3: Copy history/service.ts verbatim from nanobrowser**

```bash
cp /tmp/nanobrowser/chrome-extension/src/background/browser/dom/history/service.ts \
   /Users/loryschi/projects/jobstrainer/extension/background/browser/dom/history/service.ts
```

- [ ] **Step 4: Create util.ts**

```typescript
export function isNewTabPage(url: string): boolean {
  return (
    url === 'chrome://newtab/' ||
    url === 'about:blank' ||
    url === 'about:newtab' ||
    url.startsWith('chrome://') ||
    url.startsWith('edge://')
  );
}

export function capTextLength(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return text.substring(0, maxLength) + '…';
}
```

- [ ] **Step 5: Verify TypeScript compiles**

```bash
cd /Users/loryschi/projects/jobstrainer/extension
npx tsc --noEmit
```

Expected: No errors for the new files (ignore errors in files not yet created).

- [ ] **Step 6: Commit**

```bash
cd /Users/loryschi/projects/jobstrainer
git add extension/background/browser/dom/raw_types.ts \
        extension/background/browser/dom/history/ \
        extension/background/browser/util.ts
git commit -m "feat(extension): port DOM raw types, history, and util from nanobrowser"
```

---

## Task 3: Port DOM views + test clickableElementsToString

**Files:**
- Create: `extension/background/browser/dom/views.ts`
- Create: `extension/background/browser/dom/clickable/service.ts`
- Create: `extension/background/browser/dom/__tests__/views.test.ts`

- [ ] **Step 1: Copy views.ts from nanobrowser**

```bash
cp /tmp/nanobrowser/chrome-extension/src/background/browser/dom/views.ts \
   /Users/loryschi/projects/jobstrainer/extension/background/browser/dom/views.ts
```

Fix the import path (nanobrowser uses `@src/` alias, we use relative imports):

In `views.ts`, change:
```typescript
import type { CoordinateSet, HashedDomElement, ViewportInfo } from './history/view';
import { HistoryTreeProcessor } from './history/service';
import { capTextLength } from '../util';
```
These paths should already be correct as relative imports. Verify and fix if the aliases differ.

- [ ] **Step 2: Copy clickable/service.ts from nanobrowser**

```bash
mkdir -p /Users/loryschi/projects/jobstrainer/extension/background/browser/dom/clickable
cp /tmp/nanobrowser/chrome-extension/src/background/browser/dom/clickable/service.ts \
   /Users/loryschi/projects/jobstrainer/extension/background/browser/dom/clickable/service.ts
```

- [ ] **Step 3: Write failing test for clickableElementsToString**

Create `extension/background/browser/dom/__tests__/views.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import { DOMElementNode, DOMTextNode } from '../views';

function makeElement(params: {
  tagName: string;
  highlightIndex?: number | null;
  attributes?: Record<string, string>;
  isVisible?: boolean;
  isInteractive?: boolean;
  isTopElement?: boolean;
  isInViewport?: boolean;
}): DOMElementNode {
  return new DOMElementNode({
    tagName: params.tagName,
    xpath: `/${params.tagName}`,
    attributes: params.attributes ?? {},
    children: [],
    isVisible: params.isVisible ?? true,
    isInteractive: params.isInteractive ?? true,
    isTopElement: params.isTopElement ?? true,
    isInViewport: params.isInViewport ?? true,
    highlightIndex: params.highlightIndex ?? null,
    parent: null,
  });
}

describe('clickableElementsToString', () => {
  it('serialises a button with highlightIndex', () => {
    const root = makeElement({ tagName: 'div', highlightIndex: null });
    const btn = makeElement({ tagName: 'button', highlightIndex: 1, attributes: { type: 'submit' } });
    const txt = new DOMTextNode('Apply Now', true, btn);
    btn.children.push(txt);
    btn.parent = root;
    root.children.push(btn);

    const result = root.clickableElementsToString();
    expect(result).toContain('[1]');
    expect(result).toContain('button');
    expect(result).toContain('Apply Now');
  });

  it('serialises a file input', () => {
    const root = makeElement({ tagName: 'div', highlightIndex: null });
    const input = makeElement({ tagName: 'input', highlightIndex: 3, attributes: { type: 'file' } });
    input.parent = root;
    root.children.push(input);

    const result = root.clickableElementsToString();
    expect(result).toContain('[3]');
    expect(result).toContain('type=file');
  });

  it('omits elements with no highlightIndex', () => {
    const root = makeElement({ tagName: 'div', highlightIndex: null });
    const span = makeElement({ tagName: 'span', highlightIndex: null });
    root.children.push(span);

    const result = root.clickableElementsToString();
    expect(result).toBe('');
  });

  it('marks new elements with asterisk prefix', () => {
    const root = makeElement({ tagName: 'div', highlightIndex: null });
    const btn = makeElement({ tagName: 'button', highlightIndex: 0 });
    btn.isNew = true;
    btn.parent = root;
    root.children.push(btn);

    const result = root.clickableElementsToString();
    expect(result).toContain('*[0]');
  });
});
```

- [ ] **Step 4: Run test to confirm it fails**

```bash
cd /Users/loryschi/projects/jobstrainer/extension
npx vitest run background/browser/dom/__tests__/views.test.ts
```

Expected: FAIL (views.ts not yet properly set up or import errors).

- [ ] **Step 5: Fix import aliases in views.ts to use relative paths**

Open `extension/background/browser/dom/views.ts`. Replace any `@src/` prefixed imports with relative paths:
- `@src/background/browser/dom/history/view` → `./history/view`
- `@src/background/browser/dom/history/service` → `./history/service`  
- `@src/background/browser/util` → `../util`

- [ ] **Step 6: Run test again to confirm it passes**

```bash
cd /Users/loryschi/projects/jobstrainer/extension
npx vitest run background/browser/dom/__tests__/views.test.ts
```

Expected: 4 tests PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/loryschi/projects/jobstrainer
git add extension/background/browser/dom/views.ts \
        extension/background/browser/dom/clickable/ \
        extension/background/browser/dom/__tests__/
git commit -m "feat(extension): port DOMElementNode + clickableElementsToString, add unit tests"
```

---

## Task 4: Port DOM service + copy buildDomTree.js

**Files:**
- Create: `extension/background/browser/dom/service.ts`
- Copy: `extension/public/buildDomTree.js`

- [ ] **Step 1: Copy buildDomTree.js from nanobrowser**

```bash
cp /tmp/nanobrowser/chrome-extension/public/buildDomTree.js \
   /Users/loryschi/projects/jobstrainer/extension/public/buildDomTree.js
```

- [ ] **Step 2: Copy dom/service.ts from nanobrowser and fix imports**

```bash
cp /tmp/nanobrowser/chrome-extension/src/background/browser/dom/service.ts \
   /Users/loryschi/projects/jobstrainer/extension/background/browser/dom/service.ts
```

Fix imports in `service.ts` — replace `@src/` prefixed imports and `createLogger` references:
- Remove `import { createLogger } from '@src/background/log'` — replace with `const logger = { info: console.log, debug: console.debug, error: console.error, warning: console.warn };`
- `@src/background/browser/dom/raw_types` → `./raw_types`
- `@src/background/browser/dom/views` → `./views`
- `@src/background/browser/dom/history/view` → `./history/view`
- `@src/background/browser/util` → `../util`

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd /Users/loryschi/projects/jobstrainer/extension
npx tsc --noEmit 2>&1 | grep "browser/dom/service"
```

Expected: No errors for `service.ts`.

- [ ] **Step 4: Commit**

```bash
cd /Users/loryschi/projects/jobstrainer
git add extension/background/browser/dom/service.ts extension/public/buildDomTree.js
git commit -m "feat(extension): port DOMService and add buildDomTree.js from nanobrowser"
```

---

## Task 5: Port and adapt the Page class

**Files:**
- Create: `extension/background/browser/page.ts`

The Page class wraps puppeteer-core's `Page` and `ExtensionTransport`. We adapt it to expose only the methods needed by the service worker: `snapshot()`, `clickElement()`, `typeText()`, `selectOption()`, `scrollDown()`, `scrollUp()`, `scrollToTop()`, `scrollToBottom()`, `sendKeys()`, `navigate()`, `goBack()`, `wait()`.

- [ ] **Step 1: Create page.ts**

```typescript
import {
  connect,
  ExtensionTransport,
  type ProtocolType,
} from 'puppeteer-core/lib/esm/puppeteer/puppeteer-core-browser.js';
import type { Browser } from 'puppeteer-core/lib/esm/puppeteer/api/Browser.js';
import type { Page as PuppeteerPage } from 'puppeteer-core/lib/esm/puppeteer/api/Page.js';
import {
  getClickableElements,
  getScrollInfo,
  injectBuildDomTreeScripts,
  removeHighlights,
} from './dom/service';
import type { DOMElementNode, DOMState } from './dom/views';

const logger = { info: console.log, error: console.error };

export interface PageSnapshot {
  url: string;
  title: string;
  elements: string;
  scroll_y: number;
  scroll_height: number;
  viewport_height: number;
}

export default class Page {
  private _tabId: number;
  private _browser: Browser | null = null;
  private _page: PuppeteerPage | null = null;

  constructor(tabId: number) {
    this._tabId = tabId;
  }

  get tabId(): number {
    return this._tabId;
  }

  async attach(): Promise<void> {
    if (this._page) return;
    logger.info('[Page] attaching puppeteer to tab', this._tabId);
    const browser = await connect({
      transport: await ExtensionTransport.connectTab(this._tabId),
      defaultViewport: null,
      protocol: 'cdp' as ProtocolType,
    });
    this._browser = browser;
    const [page] = await browser.pages();
    this._page = page;
    await this._addAntiDetectionScripts();
  }

  async detach(): Promise<void> {
    if (this._browser) {
      await this._browser.disconnect();
      this._browser = null;
      this._page = null;
    }
  }

  async snapshot(): Promise<PageSnapshot> {
    const tab = await chrome.tabs.get(this._tabId);
    const url = tab.url ?? '';
    const title = tab.title ?? '';
    const domState: DOMState = await getClickableElements(this._tabId, url, true);
    const elements = domState.elementTree.clickableElementsToString();
    const [scroll_y, viewport_height, scroll_height] = await getScrollInfo(this._tabId);
    return { url, title, elements, scroll_y, viewport_height, scroll_height };
  }

  private _requirePage(): PuppeteerPage {
    if (!this._page) throw new Error('Page not attached — call attach() first');
    return this._page;
  }

  private _getElementByIndex(index: number, domState: DOMState): DOMElementNode | null {
    return domState.selectorMap.get(index) ?? null;
  }

  async clickElement(index: number): Promise<void> {
    const page = this._requirePage();
    const tab = await chrome.tabs.get(this._tabId);
    const domState = await getClickableElements(this._tabId, tab.url ?? '', false);
    const el = this._getElementByIndex(index, domState);
    if (!el) throw new Error(`Element [${index}] not found`);
    const selector = el.getEnhancedCssSelector();
    await page.click(selector);
  }

  async typeText(index: number, text: string): Promise<void> {
    const page = this._requirePage();
    const tab = await chrome.tabs.get(this._tabId);
    const domState = await getClickableElements(this._tabId, tab.url ?? '', false);
    const el = this._getElementByIndex(index, domState);
    if (!el) throw new Error(`Element [${index}] not found`);
    const selector = el.getEnhancedCssSelector();
    await page.click(selector, { clickCount: 3 });
    await page.type(selector, text, { delay: 20 });
  }

  async selectOption(index: number, text: string): Promise<void> {
    const page = this._requirePage();
    const tab = await chrome.tabs.get(this._tabId);
    const domState = await getClickableElements(this._tabId, tab.url ?? '', false);
    const el = this._getElementByIndex(index, domState);
    if (!el) throw new Error(`Element [${index}] not found`);
    const selector = el.getEnhancedCssSelector();
    await page.select(selector, text);
  }

  async scrollDown(): Promise<void> {
    const page = this._requirePage();
    await page.evaluate(() => window.scrollBy(0, window.innerHeight * 0.9));
  }

  async scrollUp(): Promise<void> {
    const page = this._requirePage();
    await page.evaluate(() => window.scrollBy(0, -window.innerHeight * 0.9));
  }

  async scrollToTop(): Promise<void> {
    const page = this._requirePage();
    await page.evaluate(() => window.scrollTo(0, 0));
  }

  async scrollToBottom(): Promise<void> {
    const page = this._requirePage();
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  }

  async sendKeys(keys: string): Promise<void> {
    const page = this._requirePage();
    await page.keyboard.press(keys as any);
  }

  async navigate(url: string): Promise<void> {
    await chrome.tabs.update(this._tabId, { url });
  }

  async goBack(): Promise<void> {
    const page = this._requirePage();
    await page.goBack();
  }

  async wait(seconds: number): Promise<void> {
    await new Promise(resolve => setTimeout(resolve, seconds * 1000));
  }

  async uploadFile(index: number, fileBlob: Blob, filename: string): Promise<void> {
    const page = this._requirePage();
    const tab = await chrome.tabs.get(this._tabId);
    const domState = await getClickableElements(this._tabId, tab.url ?? '', false);
    const el = this._getElementByIndex(index, domState);
    if (!el) throw new Error(`File input [${index}] not found`);
    const selector = el.getEnhancedCssSelector();
    const input = await page.$(selector);
    if (!input) throw new Error(`File input selector not found: ${selector}`);
    // Convert blob to a temp file path via data URL approach
    const arrayBuffer = await fileBlob.arrayBuffer();
    const uint8 = new Uint8Array(arrayBuffer);
    // Use puppeteer's uploadFile if available, else inject via CDP
    await (input as any).uploadFile({ name: filename, payload: Buffer.from(uint8).toString('base64'), mimeType: 'application/octet-stream' });
  }

  private async _addAntiDetectionScripts(): Promise<void> {
    if (!this._page) return;
    await this._page.evaluateOnNewDocument(`
      Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
      window.chrome = { runtime: {} };
      const originalAttachShadow = Element.prototype.attachShadow;
      Element.prototype.attachShadow = function(options) {
        return originalAttachShadow.call(this, { ...options, mode: 'open' });
      };
    `);
  }
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /Users/loryschi/projects/jobstrainer/extension
npx tsc --noEmit 2>&1 | grep "browser/page"
```

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/loryschi/projects/jobstrainer
git add extension/background/browser/page.ts
git commit -m "feat(extension): add Page class wrapping puppeteer-core ExtensionTransport"
```

---

## Task 6: Rewrite service_worker.ts

**Files:**
- Modify: `extension/background/service_worker.ts`

The service worker manages one `Page` instance per tab. It handles the WebSocket session and dispatches actions to the `Page` class. All content script injection and direct DOM manipulation is removed.

- [ ] **Step 1: Rewrite service_worker.ts**

```typescript
import Page, { type PageSnapshot } from './browser/page';

const API_BASE = 'http://localhost:8000';

interface Session {
  job_id: string;
  token: string;
  thread_id: string | null;
  ws: WebSocket;
  page: Page;
  log: LogEntry[];
  currentStatus: string;
}

interface LogEntry {
  kind: 'step' | 'confirm' | 'stuck' | 'done' | 'error';
  text?: string;
  done?: boolean;
  summary?: string;
  uncertain_fields?: string[];
  file_links?: { field_id: number; label: string; url: string }[];
  message?: string;
  thread_id?: string;
  token?: string;
}

const sessions: Record<number, Session> = {};
const pendingJobs: Record<number, { job_id: string; token: string }> = {};
const panelPorts: Record<number, chrome.runtime.Port> = {};

// ── Keepalive ──────────────────────────────────────────────────────────────

chrome.alarms.create('keepalive', { periodInMinutes: 0.4 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== 'keepalive') return;
  const activeSessions = Object.entries(sessions).map(([tabId, s]) => ({
    tabId: parseInt(tabId), job_id: s.job_id, token: s.token,
    log: s.log, currentStatus: s.currentStatus,
  }));
  chrome.storage.local.set({ activeSessions });
});

// ── Tab detection ──────────────────────────────────────────────────────────

chrome.tabs.onCreated.addListener(async (tab) => {
  if (!tab.openerTabId || !tab.id) return;
  try {
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: tab.openerTabId },
      func: () => ({
        pending: localStorage.getItem('tailorer_pending'),
        token: localStorage.getItem('access_token'),
      }),
    });
    const { pending, token } = result.result as any;
    if (pending && token) {
      const { job_id } = JSON.parse(pending);
      await chrome.scripting.executeScript({
        target: { tabId: tab.openerTabId },
        func: () => localStorage.removeItem('tailorer_pending'),
      });
      pendingJobs[tab.id] = { job_id, token };
      chrome.sidePanel?.open?.({ tabId: tab.id }).catch(() => {});
    }
  } catch (_) {}
});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo) => {
  if (changeInfo.status !== 'complete') return;
  if (!pendingJobs[tabId] && !sessions[tabId]) return;
  chrome.sidePanel?.open?.({ tabId }).catch(() => {});
  if (pendingJobs[tabId]) {
    const { job_id, token } = pendingJobs[tabId];
    sendToPanel(tabId, { type: 'show_apply_button', job_id, token });
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  const s = sessions[tabId];
  if (s) {
    s.ws.close();
    s.page.detach().catch(() => {});
    delete sessions[tabId];
  }
  delete pendingJobs[tabId];
  delete panelPorts[tabId];
});

// ── Panel ports ────────────────────────────────────────────────────────────

chrome.runtime.onConnect.addListener((port) => {
  const match = port.name.match(/^panel-(\d+)$/);
  if (!match) return;
  const tabId = parseInt(match[1]);
  panelPorts[tabId] = port;

  port.onDisconnect.addListener(() => {
    if (panelPorts[tabId] === port) delete panelPorts[tabId];
  });

  if (pendingJobs[tabId]) {
    const { job_id, token } = pendingJobs[tabId];
    port.postMessage({ type: 'show_apply_button', job_id, token });
  } else if (sessions[tabId]) {
    const s = sessions[tabId];
    port.postMessage({ type: 'restore_panel', log: s.log, status: s.currentStatus });
  } else {
    chrome.storage.local.get('activeSessions', ({ activeSessions }) => {
      const saved = (activeSessions || []).find((s: any) => s.tabId === tabId);
      if (saved) {
        port.postMessage({ type: 'restore_panel', log: [...saved.log, { kind: 'error', message: 'Connection lost — restart session.' }], status: 'error' });
      } else {
        port.postMessage({ type: 'idle' });
      }
    });
  }

  port.onMessage.addListener((msg) => {
    if (msg.type === 'start_session') {
      delete pendingJobs[tabId];
      openSession(tabId, msg.job_id, msg.token);
      return;
    }
    if (msg.type === 'stop_session') {
      stopSession(tabId, 'Stopped by user.');
      return;
    }
    const s = sessions[tabId];
    if (!s?.ws || s.ws.readyState !== WebSocket.OPEN) return;
    if (['user_approved', 'user_correction', 'stuck_unblocked', 'user_manual_edit'].includes(msg.type)) {
      s.ws.send(JSON.stringify(msg));
    }
  });
});

// ── WebSocket session ──────────────────────────────────────────────────────

function openSession(tabId: number, job_id: string, token: string): void {
  const wsUrl = `ws://localhost:8000/tailorer/ws/${job_id}?token=${encodeURIComponent(token)}`;
  const ws = new WebSocket(wsUrl);
  const page = new Page(tabId);

  sessions[tabId] = {
    job_id, token, thread_id: null,
    ws, page, log: [], currentStatus: 'connecting',
  };

  ws.onmessage = async (event) => {
    try { await handleAgentMessage(tabId, JSON.parse(event.data)); } catch (e) {
      console.error('[tailorer] handleAgentMessage error', e);
    }
  };

  ws.onclose = (ev) => {
    const s = sessions[tabId];
    if (!s) return;
    if (ev.code === 4001 || ev.code === 1015) {
      appendLog(tabId, { kind: 'error', message: `Auth error (${ev.code})` });
      delete sessions[tabId];
      return;
    }
    appendLog(tabId, { kind: 'error', message: 'Connection lost — restart session.' });
    s.page.detach().catch(() => {});
    delete sessions[tabId];
  };

  ws.onerror = () => {};
}

// ── Agent message dispatch ─────────────────────────────────────────────────

async function handleAgentMessage(tabId: number, msg: any): Promise<void> {
  const s = sessions[tabId];
  if (!s) return;

  if (msg.type === 'session_started') {
    s.thread_id = msg.thread_id;
    s.currentStatus = 'navigating';
    appendLog(tabId, { kind: 'step', text: 'Session started', done: true });
    sendToPanel(tabId, { type: 'status', status: 'navigating' });
    return;
  }

  if (msg.type === 'navigate') {
    s.currentStatus = 'navigating';
    const hostname = safeHostname(msg.url);
    appendLog(tabId, { kind: 'step', text: `Navigating to ${hostname}…`, done: false });
    await chrome.tabs.update(tabId, { url: msg.url });
    // Wait for tab to finish loading
    await waitForTabLoad(tabId);
    await s.page.attach();
    const snapshot = await s.page.snapshot();
    s.ws.send(JSON.stringify(snapshot));
    return;
  }

  if (msg.type === 'request_snapshot') {
    await s.page.attach();
    const snapshot = await s.page.snapshot();
    s.ws.send(JSON.stringify(snapshot));
    return;
  }

  if (msg.type === 'execute_actions') {
    s.currentStatus = 'navigating';
    await s.page.attach();
    for (const action of (msg.actions as any[])) {
      const navigated = await executeAction(tabId, s, action);
      if (navigated) {
        await waitForTabLoad(tabId);
        await s.page.attach();
        break;
      }
    }
    const snapshot = await s.page.snapshot();
    s.ws.send(JSON.stringify(snapshot));
    return;
  }

  if (msg.type === 'fill_and_confirm') {
    s.currentStatus = 'filling';
    await s.page.attach();
    // Execute non-file fill commands silently
    for (const cmd of (msg.commands as any[])) {
      if (cmd.action === 'file_upload') continue;
      try {
        if (cmd.action === 'input_text') await s.page.typeText(cmd.index, cmd.value);
        else if (cmd.action === 'select_option') await s.page.selectOption(cmd.index, cmd.text ?? cmd.value);
      } catch (e) {
        console.warn('[tailorer] fill cmd failed', cmd, e);
      }
    }
    // Show confirm with only uncertain fields + file links
    const uncertain = (msg.commands as any[]).filter((c: any) => c.uncertain).map((c: any) => `[${c.index}]`);
    const fileLinks = (msg.commands as any[])
      .filter((c: any) => c.action === 'file_upload')
      .map((c: any) => {
        const fileType = c.value === '__CV__' ? 'cv' : 'cover_letter';
        const label = fileType === 'cv' ? 'tailored_cv.docx' : 'cover_letter.docx';
        const url = `${API_BASE}/tailorer/files/${s.thread_id}/${fileType}?token=${encodeURIComponent(s.token)}`;
        return { field_id: c.index, label, url };
      });
    s.currentStatus = 'awaiting_user';
    appendLog(tabId, { kind: 'confirm', summary: msg.summary || 'Ready to fill', uncertain_fields: uncertain, file_links: fileLinks });
    sendToPanel(tabId, { type: 'status', status: 'awaiting_user' });
    return;
  }

  if (msg.type === 'show_confirm') {
    s.currentStatus = 'awaiting_user';
    appendLog(tabId, { kind: 'confirm', summary: msg.summary, uncertain_fields: [], file_links: [] });
    sendToPanel(tabId, { type: 'status', status: 'awaiting_user' });
    return;
  }

  if (msg.type === 'navigate_next') {
    s.currentStatus = 'navigating';
    appendLog(tabId, { kind: 'step', text: 'Submitting page…', done: false });
    // Backend expects a response; let the page navigate naturally via the filled form submit
    // Wait briefly for navigation then return
    await new Promise(r => setTimeout(r, 1000));
    s.ws.send(JSON.stringify({ submitted: true }));
    return;
  }

  if (msg.type === 'show_stuck') {
    s.currentStatus = 'show_stuck';
    appendLog(tabId, { kind: 'stuck', message: msg.message });
    sendToPanel(tabId, { type: 'status', status: 'show_stuck' });
    return;
  }

  if (msg.type === 'done') {
    s.currentStatus = 'done';
    appendLog(tabId, { kind: 'done', message: msg.message, thread_id: s.thread_id ?? '', token: s.token });
    sendToPanel(tabId, { type: 'status', status: 'done' });
    await s.page.detach();
    delete sessions[tabId];
    return;
  }

  if (msg.type === 'error') {
    s.currentStatus = 'error';
    appendLog(tabId, { kind: 'error', message: msg.message });
    sendToPanel(tabId, { type: 'status', status: 'error' });
    await s.page.detach();
    delete sessions[tabId];
    return;
  }
}

async function executeAction(tabId: number, s: Session, action: any): Promise<boolean> {
  const act = action.action as string;
  const logStep = (text: string) => appendLog(tabId, { kind: 'step', text, done: true });

  if (act === 'click_element') {
    logStep(`Clicking [${action.index}]`);
    await s.page.clickElement(action.index);
    return true; // may cause navigation
  }
  if (act === 'input_text') {
    await s.page.typeText(action.index, action.text ?? '');
    return false;
  }
  if (act === 'select_option') {
    await s.page.selectOption(action.index, action.text ?? '');
    return false;
  }
  if (act === 'scroll_to_bottom') { await s.page.scrollToBottom(); return false; }
  if (act === 'scroll_to_top') { await s.page.scrollToTop(); return false; }
  if (act === 'next_page') { await s.page.scrollDown(); return false; }
  if (act === 'previous_page') { await s.page.scrollUp(); return false; }
  if (act === 'send_keys') { await s.page.sendKeys(action.keys ?? ''); return false; }
  if (act === 'go_back') { await s.page.goBack(); return true; }
  if (act === 'go_to_url') {
    logStep(`Navigating to ${safeHostname(action.url)}`);
    await s.page.navigate(action.url);
    return true;
  }
  if (act === 'wait') { await s.page.wait(action.seconds ?? 2); return false; }

  console.warn('[tailorer] unknown action', act);
  return false;
}

// ── Helpers ────────────────────────────────────────────────────────────────

function waitForTabLoad(tabId: number): Promise<void> {
  return new Promise((resolve) => {
    const listener = (updatedTabId: number, info: chrome.tabs.TabChangeInfo) => {
      if (updatedTabId === tabId && info.status === 'complete') {
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
    setTimeout(resolve, 8000); // fallback
  });
}

function safeHostname(url: string): string {
  try { return new URL(url).hostname; } catch { return url; }
}

function appendLog(tabId: number, entry: LogEntry): void {
  const s = sessions[tabId];
  if (!s) return;
  s.log.push(entry);
  sendToPanel(tabId, { type: 'append_log', entry });
}

function sendToPanel(tabId: number, msg: any): void {
  panelPorts[tabId]?.postMessage(msg);
}

function stopSession(tabId: number, reason: string): void {
  const s = sessions[tabId];
  if (!s) return;
  s.ws.close();
  s.page.detach().catch(() => {});
  appendLog(tabId, { kind: 'error', message: reason });
  delete sessions[tabId];
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /Users/loryschi/projects/jobstrainer/extension
npx tsc --noEmit 2>&1 | head -30
```

Expected: No errors (or only errors in files not yet created).

- [ ] **Step 3: Build the extension**

```bash
cd /Users/loryschi/projects/jobstrainer/extension
npm run build
```

Expected: `dist/background/service_worker.js` built successfully.

- [ ] **Step 4: Commit**

```bash
cd /Users/loryschi/projects/jobstrainer
git add extension/background/service_worker.ts
git commit -m "feat(extension): rewrite service worker with Page-based CDP action dispatch"
```

---

## Task 7: React panel

**Files:**
- Modify: `extension/sidepanel/index.html`
- Modify: `extension/sidepanel/src/main.tsx`
- Create: `extension/sidepanel/src/App.tsx`
- Create: `extension/sidepanel/src/components/LogEntry.tsx`
- Create: `extension/sidepanel/src/components/ConfirmBlock.tsx`
- Create: `extension/sidepanel/src/components/StuckBlock.tsx`
- Create: `extension/sidepanel/src/components/StatusBar.tsx`

- [ ] **Step 1: Create LogEntry.tsx**

```typescript
import React from 'react';

interface Props {
  text: string;
  done: boolean;
}

export default function LogEntry({ text, done }: Props) {
  return (
    <div className="log-entry" style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 12, lineHeight: 1.5 }}>
      <span style={{ color: done ? '#22c55e' : '#38bdf8', flexShrink: 0, width: 14, textAlign: 'center', animation: done ? undefined : 'spin 1s linear infinite', display: 'inline-block' }}>
        {done ? '✓' : '⟳'}
      </span>
      <span style={{ color: done ? '#94a3b8' : '#f1f5f9' }}>{text}</span>
    </div>
  );
}
```

- [ ] **Step 2: Create ConfirmBlock.tsx**

Shows only uncertain fields (amber) and file upload links. Nothing else.

```typescript
import React from 'react';

interface FileLink { field_id: number; label: string; url: string; }

interface Props {
  summary: string;
  uncertain_fields: string[];
  file_links: FileLink[];
}

export default function ConfirmBlock({ summary, uncertain_fields, file_links }: Props) {
  return (
    <div style={{ background: '#1c1f2e', borderLeft: '3px solid #f59e0b', borderRadius: 4, padding: '9px 11px' }}>
      <div style={{ color: '#fde68a', fontWeight: 600, marginBottom: 6, fontSize: 12 }}>{summary}</div>
      {uncertain_fields.length > 0 && (
        <div style={{ marginBottom: 6 }}>
          {uncertain_fields.map((f) => (
            <div key={f} style={{ color: '#fbbf24', fontSize: 11, lineHeight: 1.8 }}>
              {f} → <em>not sure</em>
            </div>
          ))}
        </div>
      )}
      {file_links.length > 0 && (
        <div>
          {file_links.map((fl) => (
            <div key={fl.field_id}>
              <a href={fl.url} target="_blank" rel="noreferrer" style={{ color: '#60a5fa', fontSize: 11, textDecoration: 'none' }}>
                {fl.label} ↗
              </a>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Create StatusBar.tsx**

```typescript
import React from 'react';

const STATUS_CONFIG: Record<string, { text: string; dot: boolean; color: string; bg: string }> = {
  connecting:    { text: 'Connecting…',       dot: true,  color: '#7dd3fc', bg: '#172554' },
  navigating:    { text: 'Navigating…',       dot: true,  color: '#7dd3fc', bg: '#172554' },
  filling:       { text: 'Filling form…',     dot: true,  color: '#7dd3fc', bg: '#172554' },
  awaiting_user: { text: '⏸ Waiting for you', dot: false, color: '#fbbf24', bg: '#451a03' },
  show_stuck:    { text: '⚠ Action needed',   dot: false, color: '#fca5a5', bg: '#450a0a' },
  done:          { text: '✓ Done',            dot: false, color: '#86efac', bg: '#14532d' },
  error:         { text: '✗ Error',           dot: false, color: '#fca5a5', bg: '#450a0a' },
  idle:          { text: 'No active session', dot: false, color: '#64748b', bg: '#1e293b' },
};

export default function StatusBar({ status }: { status: string }) {
  const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG.idle;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: cfg.bg, padding: '3px 8px', borderRadius: 4 }}>
      {cfg.dot && (
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: cfg.color, display: 'inline-block', animation: 'pulse 1.2s ease-in-out infinite' }} />
      )}
      <span style={{ color: cfg.color, fontSize: 11 }}>{cfg.text}</span>
    </div>
  );
}
```

- [ ] **Step 4: Create App.tsx**

```typescript
import React, { useEffect, useRef, useState, useCallback } from 'react';
import LogEntry from './components/LogEntry';
import ConfirmBlock from './components/ConfirmBlock';
import StatusBar from './components/StatusBar';

type LogItem =
  | { kind: 'step'; text: string; done: boolean }
  | { kind: 'confirm'; summary: string; uncertain_fields: string[]; file_links: { field_id: number; label: string; url: string }[] }
  | { kind: 'stuck'; message: string }
  | { kind: 'done'; message: string; thread_id: string; token: string }
  | { kind: 'error'; message: string };

export default function App() {
  const [log, setLog] = useState<LogItem[]>([]);
  const [status, setStatus] = useState('idle');
  const [pendingJob, setPendingJob] = useState<{ job_id: string; token: string } | null>(null);
  const [inputText, setInputText] = useState('');
  const portRef = useRef<chrome.runtime.Port | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);

  const isWaiting = status === 'awaiting_user' || status === 'show_stuck';

  useEffect(() => {
    chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
      if (!tab?.id) return;
      const port = chrome.runtime.connect({ name: `panel-${tab.id}` });
      portRef.current = port;

      port.onMessage.addListener((msg: any) => {
        if (msg.type === 'idle') { setStatus('idle'); setLog([]); return; }
        if (msg.type === 'show_apply_button') { setPendingJob({ job_id: msg.job_id, token: msg.token }); return; }
        if (msg.type === 'restore_panel') { setLog(msg.log ?? []); setStatus(msg.status ?? 'idle'); return; }
        if (msg.type === 'append_log') { setLog(prev => [...prev, msg.entry]); return; }
        if (msg.type === 'status') { setStatus(msg.status); return; }
      });

      port.onDisconnect.addListener(() => { portRef.current = null; });
    });
  }, []);

  useEffect(() => { logEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [log]);

  const sendMsg = useCallback((msg: any) => { portRef.current?.postMessage(msg); }, []);

  const handleStart = useCallback(() => {
    if (!pendingJob) return;
    setPendingJob(null);
    setLog([]);
    setStatus('connecting');
    sendMsg({ type: 'start_session', job_id: pendingJob.job_id, token: pendingJob.token });
  }, [pendingJob, sendMsg]);

  const handleSend = useCallback(() => {
    const text = inputText.trim();
    if (!text || !isWaiting) return;
    setInputText('');
    if (status === 'show_stuck') {
      sendMsg({ type: 'stuck_unblocked', text });
    } else {
      const lower = text.toLowerCase();
      if (lower === 'ok' || lower === 'yes' || lower === 'approve') {
        sendMsg({ type: 'user_approved' });
      } else {
        sendMsg({ type: 'user_correction', text });
      }
    }
  }, [inputText, isWaiting, status, sendMsg]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#0f172a', color: '#f1f5f9', fontFamily: 'system-ui, sans-serif', fontSize: 12 }}>
      {/* Header */}
      <div style={{ padding: '8px 12px', display: 'flex', alignItems: 'center', gap: 8, borderBottom: '1px solid rgba(14,165,233,0.2)', flexShrink: 0 }}>
        <div style={{ width: 22, height: 22, background: '#0ea5e9', borderRadius: '50%' }} />
        <span style={{ fontWeight: 700, color: '#7dd3fc', fontSize: 13 }}>Tailorer</span>
        <div style={{ marginLeft: 'auto' }}>
          <StatusBar status={status} />
        </div>
      </div>

      {/* Feed */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        {status === 'idle' && log.length === 0 && (
          <div style={{ color: '#475569', textAlign: 'center', marginTop: 40, lineHeight: 1.6 }}>
            No active job — browse to a job listing to apply.
          </div>
        )}

        {pendingJob && (
          <div style={{ padding: '12px 0' }}>
            <div style={{ color: '#94a3b8', marginBottom: 10 }}>Job detected — ready to apply</div>
            <button onClick={handleStart} style={{ background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, padding: '9px 16px', fontWeight: 600, fontSize: 13, cursor: 'pointer', width: '100%' }}>
              ⚡ Start Agent
            </button>
          </div>
        )}

        {/* Agent actor label shown once at top when session is active */}
        {log.length > 0 && (
          <div style={{ display: 'flex', gap: 8 }}>
            <div style={{ width: 24, height: 24, borderRadius: '50%', background: '#0c4a6e', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, color: '#38bdf8', fontWeight: 700 }}>A</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#0ea5e9', marginBottom: 5, letterSpacing: '0.04em' }}>AGENT</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {log.map((entry, i) => {
                  if (entry.kind === 'step') return <LogEntry key={i} text={entry.text} done={entry.done} />;
                  if (entry.kind === 'confirm') return <ConfirmBlock key={i} summary={entry.summary} uncertain_fields={entry.uncertain_fields} file_links={entry.file_links} />;
                  if (entry.kind === 'stuck') return <div key={i} style={{ color: '#fca5a5', background: '#1c1f2e', borderLeft: '3px solid #ef4444', borderRadius: 4, padding: '8px 10px', fontSize: 12 }}>{entry.message}</div>;
                  if (entry.kind === 'done') return <div key={i} style={{ color: '#86efac', fontWeight: 600 }}>✓ {entry.message}</div>;
                  if (entry.kind === 'error') return <div key={i} style={{ color: '#fca5a5' }}>✗ {entry.message}</div>;
                  return null;
                })}
              </div>
            </div>
          </div>
        )}
        <div ref={logEndRef} />
      </div>

      {/* Bottom bar */}
      <div style={{ borderTop: '1px solid #1e293b', padding: '8px 10px', display: 'flex', gap: 7, alignItems: 'center', flexShrink: 0 }}>
        <input
          value={inputText}
          onChange={e => setInputText(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSend()}
          disabled={!isWaiting}
          placeholder={isWaiting ? 'ok / describe a correction / …' : 'Waiting for agent…'}
          style={{ flex: 1, background: isWaiting ? '#1e293b' : '#0f172a', border: `1px solid ${isWaiting ? '#334155' : '#1e293b'}`, borderRadius: 6, padding: '6px 9px', color: isWaiting ? '#f1f5f9' : '#334155', fontSize: 12, fontFamily: 'system-ui', outline: 'none', cursor: isWaiting ? 'text' : 'not-allowed' }}
        />
        <button
          onClick={handleSend}
          disabled={!isWaiting || !inputText.trim()}
          style={{ background: isWaiting && inputText.trim() ? '#0ea5e9' : '#1e293b', color: isWaiting && inputText.trim() ? '#fff' : '#334155', border: 'none', borderRadius: 6, padding: '6px 12px', fontSize: 12, cursor: isWaiting && inputText.trim() ? 'pointer' : 'not-allowed', flexShrink: 0 }}
        >▶</button>
        <button
          onClick={() => sendMsg({ type: 'stop_session' })}
          style={{ background: '#7f1d1d', color: '#fca5a5', border: '1px solid #991b1b', borderRadius: 5, padding: '6px 10px', fontSize: 11, cursor: 'pointer', flexShrink: 0 }}
        >■ Stop</button>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #0f172a; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
      `}</style>
    </div>
  );
}
```

- [ ] **Step 5: Update main.tsx**

```typescript
import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';

createRoot(document.getElementById('root')!).render(<App />);
```

- [ ] **Step 6: Update sidepanel/index.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Tailorer</title>
</head>
<body>
  <div id="root"></div>
  <script type="module" src="/sidepanel/src/main.tsx"></script>
</body>
</html>
```

- [ ] **Step 7: Build and verify**

```bash
cd /Users/loryschi/projects/jobstrainer/extension
npm run build
```

Expected: `dist/sidepanel/index.html` created with bundled React app. No TypeScript errors.

- [ ] **Step 8: Commit**

```bash
cd /Users/loryschi/projects/jobstrainer
git add extension/sidepanel/
git commit -m "feat(extension): React panel with actor feed, disable input when agent running"
```

---

## Task 8: Update manifest.json

**Files:**
- Modify: `extension/manifest.json`

- [ ] **Step 1: Rewrite manifest.json**

```json
{
  "manifest_version": 3,
  "name": "Jobstrainer Tailorer",
  "version": "0.2.0",
  "description": "AI-powered job application assistant",
  "permissions": [
    "tabs",
    "scripting",
    "sidePanel",
    "alarms",
    "storage",
    "debugger",
    "webNavigation"
  ],
  "host_permissions": [
    "http://localhost:8000/*",
    "https://*/*",
    "http://*/*"
  ],
  "content_security_policy": {
    "extension_pages": "script-src 'self' 'wasm-unsafe-eval'; object-src 'self'; connect-src ws://localhost:8000 http://localhost:8000"
  },
  "background": {
    "service_worker": "background/service_worker.js",
    "type": "module"
  },
  "side_panel": {
    "default_path": "sidepanel/index.html"
  },
  "action": {
    "default_title": "Tailorer"
  },
  "icons": {
    "16": "icons/icon16.png",
    "48": "icons/icon48.png",
    "128": "icons/icon128.png"
  },
  "content_scripts": [
    {
      "matches": ["http://localhost:3000/*"],
      "js": ["content/frontend_bridge.js"],
      "run_at": "document_end"
    }
  ],
  "web_accessible_resources": [
    {
      "resources": ["buildDomTree.js"],
      "matches": ["<all_urls>"]
    }
  ]
}
```

Notes: `debugger` permission required for `ExtensionTransport.connectTab()`. `webNavigation` required for `chrome.webNavigation.getAllFrames()` in DOMService. `wasm-unsafe-eval` in CSP required for puppeteer-core. `type: "module"` allows ES imports in the SW. Firefox-specific `sidebar_action` and `browser_specific_settings` removed.

- [ ] **Step 2: Rebuild to copy updated manifest to dist/**

```bash
cd /Users/loryschi/projects/jobstrainer/extension
npm run build
```

Expected: `dist/manifest.json` has new content.

- [ ] **Step 3: Delete old content scripts**

```bash
rm /Users/loryschi/projects/jobstrainer/extension/content/dom_inspector.js
rm /Users/loryschi/projects/jobstrainer/extension/content/form_filler.js
```

- [ ] **Step 4: Commit**

```bash
cd /Users/loryschi/projects/jobstrainer
git add extension/manifest.json
git rm extension/content/dom_inspector.js extension/content/form_filler.js
git commit -m "feat(extension): Chrome MV3 only, add debugger+webNavigation perms, remove content scripts"
```

---

## Task 9: Backend — state.py

**Files:**
- Modify: `backend/backend/tailorer/state.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/tailorer/test_nodes.py`:

```python
def test_make_state_has_new_fields():
    from backend.tailorer.state import TailorerState
    # Verify new fields exist in the TypedDict definition
    import typing
    hints = typing.get_type_hints(TailorerState)
    assert 'nav_memory' in hints
    assert 'last_snapshot' in hints
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd /Users/loryschi/projects/jobstrainer/backend
uv run pytest tests/tailorer/test_nodes.py::test_make_state_has_new_fields -v
```

Expected: FAIL — `AssertionError: assert 'nav_memory' in hints`.

- [ ] **Step 3: Update state.py**

Replace the entire `state.py` content:

```python
from typing import TypedDict


class TailorerState(TypedDict):
    # Session context (set at start, read-only)
    job_id: str
    user_id: str
    job_title: str
    job_description: str
    company_homepage: str
    profile: dict
    cv_text: str

    # Agent state (mutated during execution)
    apply_url: str
    current_page: int
    filled_fields: dict[str, str]
    cv_bytes: bytes
    cl_bytes: bytes
    cl_text: str
    # last_snapshot shape: {url, title, elements, scroll_y, viewport_height, scroll_height}
    last_snapshot: dict | None
    pending_correction: str | None
    retry_count: int
    status: str  # navigating | tailoring | filling | filling_correction | done | failed

    # Navigation phase tracking
    nav_phase: str        # "start" | "deciding" | "executing" | "snapshot" | "nav_done"
    nav_snapshot: dict | None
    nav_action: dict | None
    nav_history: list
    nav_memory: str       # running memory string maintained across navigate_to_apply steps
```

- [ ] **Step 4: Update _make_state helper in test_nodes.py**

Add `nav_memory` to the base state dict:

```python
def _make_state(**overrides):
    base = {
        "job_id": "abc",
        "user_id": "user1",
        "job_title": "ML Engineer",
        "job_description": "Build ML systems",
        "company_homepage": "https://stripe.com",
        "profile": {"first_name": "Lorenzo", "email": "l@test.com"},
        "cv_text": "Lorenzo Schiroli, ML Engineer",
        "apply_url": "",
        "current_page": 0,
        "filled_fields": {},
        "cv_bytes": b"",
        "cl_bytes": b"",
        "cl_text": "",
        "last_snapshot": None,
        "pending_correction": None,
        "retry_count": 0,
        "status": "navigating",
        "nav_phase": "start",
        "nav_snapshot": None,
        "nav_action": None,
        "nav_history": [],
        "nav_memory": "",
    }
    return {**base, **overrides}
```

- [ ] **Step 5: Run test to confirm it passes**

```bash
cd /Users/loryschi/projects/jobstrainer/backend
uv run pytest tests/tailorer/test_nodes.py::test_make_state_has_new_fields -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/loryschi/projects/jobstrainer
git add backend/backend/tailorer/state.py backend/tests/tailorer/test_nodes.py
git commit -m "feat(backend): add nav_memory to TailorerState, update snapshot shape docs"
```

---

## Task 10: Backend — router.py execute_actions handler

**Files:**
- Modify: `backend/backend/tailorer/router.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/tailorer/test_ws.py` (or create if not exists):

```python
import pytest
import json
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_handle_interrupt_execute_actions_returns_snapshot():
    """execute_actions sends each action to WS and returns the final snapshot."""
    from backend.tailorer.router import _handle_interrupt

    ws = AsyncMock()
    snapshot = {"url": "https://example.com", "title": "Test", "elements": "[1]<button >Apply />", "scroll_y": 0, "scroll_height": 100, "viewport_height": 800}
    ws.receive_json = AsyncMock(return_value=snapshot)

    interrupt_val = {
        "type": "execute_actions",
        "actions": [
            {"action": "click_element", "index": 1},
        ]
    }

    result = await _handle_interrupt(ws, interrupt_val)

    ws.send_json.assert_called()
    sent = ws.send_json.call_args[0][0]
    assert sent["type"] == "execute_actions"
    assert result == snapshot


@pytest.mark.asyncio
async def test_handle_interrupt_fill_and_confirm_sends_index_commands():
    """fill_and_confirm sends index-based commands and confirm message."""
    from backend.tailorer.router import _handle_interrupt

    ws = AsyncMock()
    ws.receive_json = AsyncMock(return_value={"type": "user_approved"})

    interrupt_val = {
        "type": "fill_and_confirm",
        "commands": [
            {"index": 2, "value": "John", "action": "input_text", "uncertain": False},
            {"index": 7, "value": "__CV__", "action": "file_upload"},
        ],
        "summary": "Filling page 1",
    }

    result = await _handle_interrupt(ws, interrupt_val, thread_id="t1", token="tok")

    calls = [c[0][0] for c in ws.send_json.call_args_list]
    # Should send the fill commands first
    assert any(c.get("action") == "input_text" for c in calls)
    # Should send show_confirm with file_links
    confirm_call = next(c for c in calls if c.get("type") == "show_confirm")
    assert len(confirm_call["file_links"]) == 1
    assert result == {"type": "user_approved"}
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/loryschi/projects/jobstrainer/backend
uv run pytest tests/tailorer/test_ws.py::test_handle_interrupt_execute_actions_returns_snapshot tests/tailorer/test_ws.py::test_handle_interrupt_fill_and_confirm_sends_index_commands -v
```

Expected: FAIL.

- [ ] **Step 3: Update _handle_interrupt in router.py**

Replace the `_handle_interrupt` function:

```python
async def _handle_interrupt(ws: WebSocket, interrupt_val: dict, thread_id: str = "", token: str = "") -> dict:
    itype = interrupt_val.get("type")

    if itype == "navigate":
        await ws.send_json({"type": "navigate", "url": interrupt_val["url"]})
        return await ws.receive_json()

    elif itype == "request_snapshot":
        await ws.send_json({"type": "request_snapshot"})
        return await ws.receive_json()

    elif itype == "execute_actions":
        await ws.send_json({"type": "execute_actions", "actions": interrupt_val.get("actions", [])})
        return await ws.receive_json()

    elif itype == "fill_and_confirm":
        all_cmds = interrupt_val.get("commands", [])
        file_cmds = [c for c in all_cmds if c.get("action") == "file_upload" or c.get("value") in ("__CV__", "__COVER_LETTER__")]
        regular_cmds = [c for c in all_cmds if c not in file_cmds]

        for cmd in regular_cmds:
            await ws.send_json(cmd)

        file_links = []
        for fc in file_cmds:
            file_type = "cv" if fc.get("value") == "__CV__" else "cover_letter"
            label = "tailored_cv.docx" if file_type == "cv" else "cover_letter.docx"
            url = f"{_API_BASE}/tailorer/files/{thread_id}/{file_type}?token={quote(token)}"
            file_links.append({"field_id": fc["index"], "label": label, "url": url})

        uncertain = [f'[{c["index"]}]' for c in all_cmds if c.get("uncertain")]

        await ws.send_json({
            "type": "show_confirm",
            "summary": interrupt_val.get("summary", ""),
            "uncertain_fields": uncertain,
            "file_links": file_links,
        })
        response = await ws.receive_json()

        if response.get("type") == "user_approved":
            for cmd in file_cmds:
                await ws.send_json(cmd)

        return response

    elif itype == "show_confirm":
        await ws.send_json(interrupt_val)
        return await ws.receive_json()

    elif itype == "navigate_next":
        await ws.send_json({"type": "navigate_next"})
        return await ws.receive_json()

    elif itype == "show_stuck":
        await ws.send_json({"type": "show_stuck", "message": interrupt_val["message"]})
        return await ws.receive_json()

    return {"type": "unknown"}
```

Also remove now-unused `click_and_snapshot` and `fill_and_search` handlers that were previously in this function.

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /Users/loryschi/projects/jobstrainer/backend
uv run pytest tests/tailorer/test_ws.py::test_handle_interrupt_execute_actions_returns_snapshot tests/tailorer/test_ws.py::test_handle_interrupt_fill_and_confirm_sends_index_commands -v
```

Expected: PASS.

- [ ] **Step 5: Run full backend test suite**

```bash
cd /Users/loryschi/projects/jobstrainer/backend
uv run pytest tests/ -v
```

Expected: All previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/loryschi/projects/jobstrainer
git add backend/backend/tailorer/router.py backend/tests/tailorer/test_ws.py
git commit -m "feat(backend): add execute_actions handler, update fill_and_confirm to index-based commands"
```

---

## Task 11: Backend — nodes.py navigate_to_apply rewrite

**Files:**
- Modify: `backend/backend/tailorer/nodes.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/tailorer/test_nodes.py`:

```python
def test_decide_next_navigation_returns_batched_actions():
    """_decide_next_navigation returns a dict with current_state + action array."""
    import json
    from unittest.mock import patch, MagicMock

    mock_resp = MagicMock()
    mock_resp.content = json.dumps({
        "current_state": {
            "evaluation_previous_goal": "Unknown - first step",
            "memory": "Starting navigation to Stripe careers page.",
            "next_goal": "Find apply button"
        },
        "action": [{"action": "click_element", "index": 1}]
    })

    with patch("backend.tailorer.nodes.ChatOpenAI") as MockLLM:
        instance = MockLLM.return_value
        instance.invoke.return_value = mock_resp
        from backend.tailorer.nodes import _decide_next_navigation
        snapshot = {
            "url": "https://stripe.com/jobs/123",
            "title": "Software Engineer",
            "elements": "[1]<button >Apply Now />\n[2]<a href=/careers >Careers />",
            "scroll_y": 0,
            "scroll_height": 1000,
            "viewport_height": 800,
        }
        result = _decide_next_navigation(instance, snapshot, "Software Engineer", [], "")

    assert "current_state" in result
    assert "action" in result
    assert isinstance(result["action"], list)
    assert result["action"][0]["action"] == "click_element"


def test_navigate_to_apply_stores_nav_memory():
    """navigate_to_apply persists memory from LLM response into nav_memory."""
    import json
    from unittest.mock import patch, MagicMock
    from langgraph.types import interrupt as lg_interrupt

    mock_resp = MagicMock()
    mock_resp.content = json.dumps({
        "current_state": {
            "evaluation_previous_goal": "Unknown",
            "memory": "On careers page, found apply button at index 1.",
            "next_goal": "Click apply"
        },
        "action": [{"action": "at_form"}]
    })

    with patch("backend.tailorer.nodes.ChatOpenAI") as MockLLM, \
         patch("backend.tailorer.nodes.interrupt") as mock_interrupt:
        instance = MockLLM.return_value
        instance.invoke.return_value = mock_resp
        mock_interrupt.return_value = {
            "url": "https://stripe.com/apply",
            "title": "Apply",
            "elements": "[2]<input type=text />",
            "scroll_y": 0, "scroll_height": 500, "viewport_height": 800
        }
        from backend.tailorer.nodes import navigate_to_apply
        state = _make_state(
            nav_phase="deciding",
            nav_snapshot={"url": "https://stripe.com/jobs/123", "elements": "[1]<button >Apply />", "scroll_y": 0, "scroll_height": 1000, "viewport_height": 800},
            nav_memory="",
            nav_history=["https://stripe.com"],
        )
        result = navigate_to_apply(state)

    assert result["nav_memory"] == "On careers page, found apply button at index 1."
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/loryschi/projects/jobstrainer/backend
uv run pytest tests/tailorer/test_nodes.py::test_decide_next_navigation_returns_batched_actions tests/tailorer/test_nodes.py::test_navigate_to_apply_stores_nav_memory -v
```

Expected: FAIL.

- [ ] **Step 3: Rewrite _decide_next_navigation in nodes.py**

Replace the `_decide_next_navigation` function:

```python
def _decide_next_navigation(llm, snapshot: dict, job_title: str, nav_history: list, nav_memory: str) -> dict:
    """Ask LLM what to do next. Returns {current_state: {...}, action: [...]}."""
    elements = snapshot.get("elements", "")
    current_url = snapshot.get("url", "")
    scroll_y = snapshot.get("scroll_y", 0)
    scroll_height = snapshot.get("scroll_height", 0)
    viewport_height = snapshot.get("viewport_height", 800)
    history_str = " → ".join(nav_history[-8:]) if nav_history else "none"
    can_scroll_down = scroll_y + viewport_height < scroll_height - 50

    _log.info("[_decide_next_navigation] url=%s scroll=%d/%d", current_url, scroll_y, scroll_height)

    resp = llm.invoke([
        SystemMessage(content=(
            "You are navigating a company website to find the job application form.\n\n"
            "# Input Format\n"
            "Interactive elements are listed as: [index]<type attributes>text</>\n"
            "Only elements with [index] are interactive. Use the index to reference them.\n\n"
            "# Response Format\n"
            'Return ONLY valid JSON:\n'
            '{"current_state": {"evaluation_previous_goal": "<Success|Failed|Unknown — why>", '
            '"memory": "<what you have done, what remains>", '
            '"next_goal": "<immediate next action>"}, '
            '"action": [{"action": "<name>", ...params}]}\n\n'
            "# Available actions\n"
            '{"action": "click_element", "index": N}\n'
            '{"action": "go_to_url", "url": "<absolute url>"}\n'
            '{"action": "scroll_to_bottom"}  -- scroll down to reveal more elements\n'
            '{"action": "scroll_to_top"}\n'
            '{"action": "next_page"}  -- scroll one page down\n'
            '{"action": "input_text", "index": N, "text": "<value>"}  -- fill a search/filter field\n'
            '{"action": "send_keys", "keys": "Enter"}  -- press a key\n'
            '{"action": "go_back"}  -- navigate back\n'
            '{"action": "at_form"}  -- you are ON the application form, ready to fill it\n'
            '{"action": "stuck", "reason": "<why blocked>"}\n\n'
            "# Rules\n"
            "- Return at_form if you see actual application form fields: name, email, phone, file upload for resume/CV\n"
            "- A file input (type=file) for resume is a DEFINITIVE signal — return at_form immediately\n"
            "- Do NOT return at_form for login-only pages\n"
            "- Avoid URLs/actions already in navigation history\n"
            "- Use scroll_to_bottom or next_page if the page might have more links below\n"
            "- Return stuck only as last resort\n"
            "- Return up to 2 actions maximum\n"
            "- Return ONLY valid JSON, no prose, no markdown"
        )),
        HumanMessage(content=(
            f"Goal: find and open the application form for: \"{job_title}\"\n"
            f"Current URL: {current_url}\n"
            f"Navigation history: {history_str}\n"
            f"Memory: {nav_memory or 'none'}\n"
            f"Can scroll down: {can_scroll_down}\n\n"
            f"Interactive elements:\n{elements}"
        ))
    ])
    raw = re.sub(r"```(?:json)?\s*|\s*```", "", resp.content.strip())
    _log.info("[_decide_next_navigation] raw=%s", raw)
    return json.loads(raw)
```

- [ ] **Step 4: Update navigate_to_apply to use new format and store nav_memory**

In the `navigate_to_apply` function, update the `deciding` phase block:

```python
    if phase == "deciding":
        if nav_steps >= _MAX_NAV_STEPS:
            return {**state, "nav_phase": "executing",
                    "nav_action": {"action": [{"action": "stuck", "reason": "Reached maximum navigation steps."}]}}

        current_url = (snapshot or {}).get("url", "")
        if nav_history.count(current_url) >= 2:
            return {**state, "nav_phase": "executing",
                    "nav_action": {"current_state": {}, "action": [{"action": "stuck", "reason": f"Stuck in loop at {current_url}"}]}}

        try:
            decision = _decide_next_navigation(llm, snapshot, state["job_title"], nav_history, state.get("nav_memory") or "")
        except Exception as e:
            _log.warning("[navigate_to_apply] LLM failed: %s", e)
            decision = {"current_state": {}, "action": [{"action": "stuck", "reason": f"LLM error: {e}"}]}

        # Extract and persist memory
        memory = (decision.get("current_state") or {}).get("memory", "")
        _log.info("[navigate_to_apply] decision=%s memory=%s", decision, memory)
        return {**state, "nav_phase": "executing", "nav_action": decision, "nav_memory": memory}
```

Update the `executing` phase to handle action arrays:

```python
    if phase == "executing":
        actions = state.get("nav_action") or {}
        action_list = actions.get("action") or []
        if not action_list:
            return {**state, "nav_phase": "nav_done", "apply_url": (snapshot or {}).get("url", ""), "status": "tailoring"}

        first_action = action_list[0] if action_list else {}
        act = first_action.get("action")

        if act == "at_form":
            _log.info("[navigate_to_apply] at_form url=%s", (snapshot or {}).get("url"))
            return {**state, "nav_phase": "nav_done", "apply_url": (snapshot or {}).get("url", ""), "status": "tailoring"}

        if act == "stuck":
            reason = first_action.get("reason", "Unable to proceed.")
            interrupt({"type": "show_stuck", "message": f"{reason} Please navigate to the application form."})
            return {**state, "nav_phase": "snapshot", "nav_snapshot": None, "nav_action": None, "retry_count": 0}

        if act == "go_to_url":
            url = _resolve_url(first_action.get("url", ""), (snapshot or {}).get("url", ""))
            snap = interrupt({"type": "execute_actions", "actions": action_list})
            return {**state, "nav_phase": "deciding", "nav_snapshot": snap, "nav_action": None,
                    "nav_history": nav_history + [url], "retry_count": nav_steps + 1}

        # For all other actions (click_element, scroll, input_text, etc.)
        snap = interrupt({"type": "execute_actions", "actions": action_list})
        url_after = snap.get("url", current_url) if isinstance(snap, dict) else current_url
        return {**state, "nav_phase": "deciding", "nav_snapshot": snap, "nav_action": None,
                "nav_history": nav_history + [url_after], "retry_count": nav_steps + 1}
```

Also update the `start` phase to use new snapshot format:
```python
    if phase == "start":
        snap = interrupt({"type": "navigate", "url": state["company_homepage"]})
        return {**state, "nav_phase": "deciding", "nav_snapshot": snap, "nav_action": None,
                "nav_history": [state["company_homepage"]], "retry_count": 0, "nav_memory": ""}
```

Remove helper functions `_find_best_link_in_snapshot` and `_find_apply_url_in_snapshot` — they are no longer used.

- [ ] **Step 5: Run tests**

```bash
cd /Users/loryschi/projects/jobstrainer/backend
uv run pytest tests/tailorer/test_nodes.py -v
```

Expected: All tests PASS including the two new ones. The old `test_find_best_link_*` tests should be deleted since `_find_best_link_in_snapshot` is removed.

- [ ] **Step 6: Delete obsolete tests**

Remove `test_find_best_link_returns_url` and `test_find_best_link_returns_none_when_no_match` from `test_nodes.py` since the functions they test no longer exist.

- [ ] **Step 7: Run full backend suite**

```bash
cd /Users/loryschi/projects/jobstrainer/backend
uv run pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
cd /Users/loryschi/projects/jobstrainer
git add backend/backend/tailorer/nodes.py backend/tests/tailorer/test_nodes.py
git commit -m "feat(backend): rewrite navigate_to_apply with indexed elements + nav_memory + batched actions"
```

---

## Task 12: Backend — nodes.py fill_page rewrite

**Files:**
- Modify: `backend/backend/tailorer/nodes.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/tailorer/test_nodes.py`:

```python
def test_map_fields_sync_returns_index_based_commands():
    """_map_fields_sync returns commands with index (int) not field_id (str)."""
    import json
    from unittest.mock import patch, MagicMock

    mock_resp = MagicMock()
    mock_resp.content = json.dumps([
        {"index": 2, "value": "Lorenzo", "action": "input_text", "uncertain": False},
        {"index": 7, "value": "__CV__", "action": "file_upload", "uncertain": False},
        {"index": 9, "value": "???", "action": "input_text", "uncertain": True},
    ])

    with patch("backend.tailorer.nodes.ChatOpenAI") as MockLLM:
        instance = MockLLM.return_value
        instance.invoke.return_value = mock_resp
        from backend.tailorer.nodes import _map_fields_sync
        state = _make_state()
        snapshot = {
            "url": "https://greenhouse.io/apply",
            "elements": "[2]<input type=text placeholder='First name' />\n[7]<input type=file />\n[9]<input type=text placeholder='Work auth' />",
            "scroll_y": 0, "scroll_height": 1000, "viewport_height": 800,
        }
        cmds = _map_fields_sync(instance, snapshot, state)

    assert cmds[0]["index"] == 2
    assert cmds[0]["action"] == "input_text"
    assert cmds[1]["value"] == "__CV__"
    assert cmds[2]["uncertain"] is True
    # Must NOT have field_id
    assert "field_id" not in cmds[0]


def test_fill_page_confirm_shows_only_uncertain_and_files():
    """fill_page interrupt shows only uncertain fields and file upload commands."""
    import json
    from unittest.mock import patch, MagicMock
    from langgraph.types import interrupt as lg_interrupt

    mock_resp = MagicMock()
    mock_resp.content = json.dumps([
        {"index": 2, "value": "Lorenzo", "action": "input_text", "uncertain": False},
        {"index": 7, "value": "__CV__", "action": "file_upload", "uncertain": False},
        {"index": 9, "value": "???", "action": "input_text", "uncertain": True},
    ])

    with patch("backend.tailorer.nodes.ChatOpenAI") as MockLLM, \
         patch("backend.tailorer.nodes.interrupt") as mock_interrupt:
        instance = MockLLM.return_value
        instance.invoke.return_value = mock_resp
        mock_interrupt.return_value = {"type": "user_approved"}
        from backend.tailorer.nodes import fill_page
        state = _make_state(
            last_snapshot={
                "url": "https://greenhouse.io/apply",
                "elements": "[2]<input type=text />\n[7]<input type=file />\n[9]<input type=text />",
                "scroll_y": 0, "scroll_height": 1000, "viewport_height": 800,
            },
            filled_fields={},
        )
        fill_page(state)

    interrupt_call = mock_interrupt.call_args[0][0]
    # Only uncertain + file commands in the confirm payload
    assert interrupt_call["type"] == "fill_and_confirm"
    confirm_cmds = interrupt_call["commands"]
    shown_indices = {c["index"] for c in confirm_cmds}
    # Index 2 (not uncertain, not file) should NOT appear
    assert 2 not in shown_indices
    # Index 7 (file) and 9 (uncertain) SHOULD appear
    assert 7 in shown_indices
    assert 9 in shown_indices
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/loryschi/projects/jobstrainer/backend
uv run pytest tests/tailorer/test_nodes.py::test_map_fields_sync_returns_index_based_commands tests/tailorer/test_nodes.py::test_fill_page_confirm_shows_only_uncertain_and_files -v
```

Expected: FAIL.

- [ ] **Step 3: Rewrite _map_fields_sync in nodes.py**

Replace the `_map_fields_sync` function:

```python
def _map_fields_sync(llm, snapshot: dict, state: TailorerState) -> list[dict]:
    SYSTEM = (
        "You fill job application form fields from the applicant's profile and CV.\n\n"
        "Interactive elements are listed as: [index]<type attributes>text</>\n"
        "Use the numeric index to reference each element.\n\n"
        "Return a JSON array of fill commands:\n"
        '  {"index": N, "value": "<value>", "action": "input_text", "uncertain": false}\n'
        '  {"index": N, "action": "select_option", "text": "<option text>", "uncertain": false}\n'
        '  {"index": N, "value": "__CV__", "action": "file_upload"}  -- for CV/resume file input\n'
        '  {"index": N, "value": "__COVER_LETTER__", "action": "file_upload"}  -- for cover letter\n\n'
        "Rules:\n"
        "- NEVER fill authentication/login fields\n"
        "- uncertain=true if you are not sure of the correct value\n"
        "- Omit fields you have no data for\n"
        "- For select dropdowns, use exact option text\n"
        "- Return ONLY the JSON array, no prose\n"
    )
    profile_str = json.dumps(state["profile"], indent=2)
    elements = snapshot.get("elements", "")

    resp = llm.invoke([
        SystemMessage(content=SYSTEM),
        HumanMessage(content=(
            f"Profile:\n{profile_str}\n\n"
            f"CV (excerpt):\n{state['cv_text'][:1500]}\n\n"
            f"Cover letter:\n{state['cl_text'][:400]}\n\n"
            f"Interactive elements:\n{elements}"
        ))
    ])
    raw = re.sub(r"```(?:json)?\s*|\s*```", "", resp.content.strip())
    return json.loads(raw)
```

- [ ] **Step 4: Rewrite fill_page to use new format**

Replace the `fill_page` function:

```python
def fill_page(state: TailorerState) -> TailorerState:
    llm = _make_llm(_LARGE())
    snapshot = state["last_snapshot"]

    elements = (snapshot or {}).get("elements", "")
    _log.info("[fill_page] url=%s elements_len=%d", (snapshot or {}).get("url", "?"), len(elements))

    if not elements:
        page_text = (snapshot or {}).get("page_text", "").lower()
        if any(kw in page_text for kw in _COMPLETION_KEYWORDS):
            _log.info("[fill_page] completion page detected via page_text")
            return {**state, "status": "done"}
        # No elements and no completion signal — check URL/title
        title = (snapshot or {}).get("title", "").lower()
        if any(kw in title for kw in _COMPLETION_KEYWORDS):
            return {**state, "status": "done"}
        _log.info("[fill_page] no elements, treating as completion")
        return {**state, "status": "done"}

    already_filled = state.get("filled_fields") or {}
    all_commands = _map_fields_sync(llm, snapshot, state)
    _log.info("[fill_page] _map_fields_sync returned %d commands", len(all_commands))

    # Skip already-filled indices
    commands = [c for c in all_commands if str(c.get("index")) not in already_filled]

    if state["pending_correction"]:
        commands = _apply_correction_sync(llm, state["pending_correction"], commands, state)

    # Commands to send in fill_and_confirm: uncertain + file uploads only
    # (regular fills happen silently in the extension)
    confirm_commands = [
        c for c in commands
        if c.get("uncertain") or c.get("action") == "file_upload" or c.get("value") in ("__CV__", "__COVER_LETTER__")
    ]

    page_label = f"page {state['current_page'] + 1}"

    response = interrupt({
        "type": "fill_and_confirm",
        "commands": commands,         # all commands sent to extension for execution
        "confirm_commands": confirm_commands,  # subset shown to user
        "summary": f"Filling {page_label} — check uncertain fields below",
        "uncertain_fields": [str(c["index"]) for c in commands if c.get("uncertain")],
    })

    rtype = (response or {}).get("type")
    if rtype == "user_approved":
        updated_fields = {**already_filled, **{str(c["index"]): c.get("value", "") for c in commands}}
        return {**state, "filled_fields": updated_fields, "last_snapshot": None, "pending_correction": None, "status": "navigating"}
    elif rtype == "user_correction":
        return {**state, "pending_correction": response["text"], "status": "filling_correction"}
    elif rtype == "user_manual_edit":
        updated_fields = {**already_filled, str(response["index"]): response["value"]}
        return {**state, "filled_fields": updated_fields, "pending_correction": None, "status": "filling_correction"}
    return {**state, "status": "failed"}
```

Update `_apply_correction_sync` to work with index-based commands (the signature stays the same, but the prompt references `index` not `field_id`):

```python
def _apply_correction_sync(llm, correction_text: str, original_commands: list[dict], state: TailorerState) -> list[dict]:
    resp = llm.invoke([
        SystemMessage(content="Correct job application fill commands based on user feedback. Commands use 'index' (int) to reference form elements. Return the corrected JSON array only."),
        HumanMessage(content=(
            f"Original commands:\n{json.dumps(original_commands, indent=2)}\n\n"
            f"User correction: {correction_text}\n\n"
            f"Profile:\n{json.dumps(state['profile'], indent=2)}"
        ))
    ])
    raw = re.sub(r"```(?:json)?\s*|\s*```", "", resp.content.strip())
    return json.loads(raw)
```

- [ ] **Step 5: Update router.py fill_and_confirm to use new confirm_commands key**

In `router.py` `_handle_interrupt`, the `fill_and_confirm` handler should use `confirm_commands` (the subset shown to user) for `show_confirm`, and `commands` (the full set) for sending fills to the extension:

```python
    elif itype == "fill_and_confirm":
        all_cmds = interrupt_val.get("commands", [])
        # Use confirm_commands subset if provided, else fall back to all_cmds
        confirm_cmds = interrupt_val.get("confirm_commands", all_cmds)

        file_cmds = [c for c in confirm_cmds if c.get("action") == "file_upload" or c.get("value") in ("__CV__", "__COVER_LETTER__")]
        regular_cmds = [c for c in all_cmds if c.get("action") != "file_upload" and c.get("value") not in ("__CV__", "__COVER_LETTER__")]

        for cmd in regular_cmds:
            await ws.send_json(cmd)

        file_links = []
        for fc in file_cmds:
            file_type = "cv" if fc.get("value") == "__CV__" else "cover_letter"
            label = "tailored_cv.docx" if file_type == "cv" else "cover_letter.docx"
            url = f"{_API_BASE}/tailorer/files/{thread_id}/{file_type}?token={quote(token)}"
            file_links.append({"field_id": fc["index"], "label": label, "url": url})

        uncertain = [f'[{c["index"]}]' for c in confirm_cmds if c.get("uncertain")]

        await ws.send_json({
            "type": "show_confirm",
            "summary": interrupt_val.get("summary", ""),
            "uncertain_fields": uncertain,
            "file_links": file_links,
        })
        response = await ws.receive_json()

        if response.get("type") == "user_approved":
            for cmd in file_cmds:
                await ws.send_json(cmd)

        return response
```

- [ ] **Step 6: Run all tests**

```bash
cd /Users/loryschi/projects/jobstrainer/backend
uv run pytest tests/ -v
```

Expected: All tests pass, including the two new fill_page tests.

- [ ] **Step 7: Commit**

```bash
cd /Users/loryschi/projects/jobstrainer
git add backend/backend/tailorer/nodes.py backend/backend/tailorer/router.py backend/tests/tailorer/test_nodes.py
git commit -m "feat(backend): rewrite fill_page with indexed elements, show only uncertain+files in confirm"
```

---

## Task 13: Integration smoke test

**Goal:** Load the rebuilt extension in Chrome, open the jobstrainer app, trigger a session, and verify the agent can navigate and fill a form.

- [ ] **Step 1: Start backend**

```bash
cd /Users/loryschi/projects/jobstrainer
docker compose up -d postgres
cd backend && uv run uvicorn backend.main:app --reload
```

Expected: Backend running on `http://localhost:8000`.

- [ ] **Step 2: Build the extension**

```bash
cd /Users/loryschi/projects/jobstrainer/extension
npm run build
```

Expected: `dist/` directory populated.

- [ ] **Step 3: Load extension in Chrome**

1. Open Chrome → `chrome://extensions`
2. Enable Developer Mode
3. Click "Load unpacked" → select `extension/dist/`
4. Verify extension loads without errors in the Extensions page

- [ ] **Step 4: Verify side panel opens**

1. Click the Tailorer extension icon in the toolbar
2. The side panel should open showing "No active job — browse to a job listing to apply."

- [ ] **Step 5: Verify CDP attach works**

1. Navigate to any HTTPS page (e.g. `https://example.com`)
2. Open Chrome DevTools → Application → Service Workers → confirm Tailorer SW is active
3. In the SW console, no errors about debugger permissions

- [ ] **Step 6: Trigger an apply session via the webapp**

1. Start the frontend (if available) or manually set `localStorage.setItem('tailorer_pending', JSON.stringify({job_id: '<valid-job-uuid>'}))` and `localStorage.setItem('access_token', '<valid-jwt>')` in the browser console
2. Open a new tab — the service worker should detect the pending job
3. Side panel should show the "Start Agent" button
4. Click "Start Agent"
5. Watch the panel feed: should show "Session started", then navigation steps

- [ ] **Step 7: Verify snapshot format in backend logs**

In the backend terminal, look for log lines from `tailorer`:
```
[tailorer] iteration=1 invoking graph
```
And in `navigate_to_apply`:
```
[_decide_next_navigation] url=https://... scroll=0/...
```

Verify the snapshot received by the backend has the new format `{url, title, elements, scroll_y, ...}` instead of `{fields, links, buttons, page_text}`.

- [ ] **Step 8: Commit final integration notes**

```bash
cd /Users/loryschi/projects/jobstrainer
git add -A
git commit -m "chore: integration verified — extension dist + backend protocol aligned"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| Chrome MV3 only, drop Firefox | Task 8 |
| buildDomTree.js from nanobrowser | Task 4 |
| DOM types, views, service ported | Tasks 2, 3, 4 |
| Page class with puppeteer-core CDP | Task 5 |
| service_worker.ts rewritten | Task 6 |
| React panel, actor feed | Task 7 |
| Input disabled when agent running | Task 7 |
| Only uncertain+files in confirm | Tasks 7, 12 |
| state.py nav_memory field | Task 9 |
| router.py execute_actions handler | Task 10 |
| nodes.py navigate_to_apply indexed elements + batched actions | Task 11 |
| nodes.py fill_page index-based commands | Task 12 |
| debugger + webNavigation permissions | Task 8 |
| dom_inspector.js + form_filler.js deleted | Task 8 |

**No placeholders** — all steps contain actual code.

**Type consistency** — `index: number` used throughout extension; `index: int` in backend commands; `nav_memory: str` consistent between state.py Task 9 and nodes.py Task 11.
