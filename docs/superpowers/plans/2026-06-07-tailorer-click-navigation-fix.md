# Tailorer Extension — Click/Navigation Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the browser extension so the AI agent can reliably click elements and navigate on any job site — including off-screen elements, iframe-embedded application widgets, SPA navigations, and connection failures.

**Architecture:** All fixes are confined to two files in the extension. `page.ts` is the Puppeteer/CDP automation layer — it needs scroll-into-view, iframe traversal, click fallback, and safe connection management. `service_worker.ts` is the WebSocket session layer — it needs the navigation log entry fixed and error handling that prevents the backend from hanging. No Python backend changes required.

**Tech Stack:** TypeScript, Puppeteer-core v23 (ExtensionTransport/CDP), Chrome MV3 Extension APIs (`webNavigation`, `scripting`, `tabs`), Vite (build), Vitest (tests)

---

## Root Cause Summary (Context Only)

Five cumulative bugs cause "Clicking [7]" to silently fail:

| # | Root cause | Location |
|---|-----------|----------|
| 1 | No `scrollIntoView` before click — off-screen elements are never reached | `page.ts:clickElement` |
| 2 | No fallback click — some SPA frameworks ignore CDP synthetic events | `page.ts:clickElement` |
| 3 | No iframe traversal — embedded apply widgets (Greenhouse, Workday) live in iframes that `page.$()` can't reach | `page.ts:_locateElement` |
| 4 | `navigate()` calls `chrome.tabs.update` while Puppeteer CDP is attached — cross-origin navigations corrupt the session | `page.ts:navigate` |
| 5 | Stale `_page` guard blocks reconnection — `if (this._page) return` skips re-attach after silent disconnects | `page.ts:attach` |
| 6 | Any exception → backend hangs forever (no response sent) | `service_worker.ts` |
| 7 | Navigation log entry stays `done: false` forever (cosmetic, but confusing) | `service_worker.ts` |

---

## File Map

| File | What changes |
|------|-------------|
| `extension/background/browser/page.ts` | Major refactor: split `_locateElement` into `_getElementNode` + `_locateHandle`, add `_scrollIntoViewIfNeeded`, fix `clickElement` with scroll+fallback+timeout, fix `navigate()`, fix `attach()`/`detach()` |
| `extension/background/service_worker.ts` | Fix navigation log `done` flag; add error-recovery response to prevent backend hang |
| `extension/background/browser/dom/__tests__/page.test.ts` | New file: unit tests for `_getElementNode`, `_locateHandle`, `_scrollIntoViewIfNeeded`, `clickElement` fallback |
| `extension/background/service_worker.js` | **Delete** — dead legacy file, replaced by compiled TypeScript; keeping it causes confusion |

---

## Task 1: Delete Dead Legacy File

> Removes the source `service_worker.js` that predates the TypeScript rewrite. Chrome loads from `dist/`, where Vite compiles `service_worker.ts` to `dist/background/service_worker.js`. The source `.js` is never executed and confuses anyone reading the codebase.

**Files:**
- Delete: `extension/background/service_worker.js`

- [ ] **Step 1: Confirm the file is not referenced anywhere**

```bash
grep -r "service_worker.js" /Users/loryschi/projects/jobstrainer/extension --include="*.ts" --include="*.json" --include="*.html"
```

Expected output: only `manifest.json` (which references the *built* output, not the source) and `vite.config.ts` (which references `.ts`). If any other `.ts` file imports it, stop and investigate.

- [ ] **Step 2: Delete the file**

```bash
rm /Users/loryschi/projects/jobstrainer/extension/background/service_worker.js
```

- [ ] **Step 3: Verify build still works**

```bash
cd /Users/loryschi/projects/jobstrainer/extension && npm run build 2>&1 | tail -20
```

Expected: Build succeeds. `dist/background/service_worker.js` still exists (it's the compiled output from `service_worker.ts`).

- [ ] **Step 4: Commit**

```bash
git add -A extension/background/service_worker.js
git commit -m "chore(extension): remove dead legacy service_worker.js source file"
```

---

## Task 2: Safe Connection Foundation — `attach()` and `detach()`

> Two separate bugs: `detach()` throws if the connection already dropped (unhandled); `attach()` trusts a stale `_page` because its guard is `if (this._page) return`. Fix both before building on top of them.

**Files:**
- Modify: `extension/background/browser/page.ts` (lines 48–68)

- [ ] **Step 1: Write failing test**

Create `extension/background/browser/dom/__tests__/page.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Minimal stubs — we only need the shape, not real implementations
const makeElementHandle = (overrides: Record<string, unknown> = {}) => ({
  click: vi.fn().mockResolvedValue(undefined),
  evaluate: vi.fn().mockResolvedValue(true),
  boundingBox: vi.fn().mockResolvedValue({ x: 10, y: 10, width: 100, height: 40 }),
  dispose: vi.fn().mockResolvedValue(undefined),
  ...overrides,
});

const makePuppeteerPage = (overrides: Record<string, unknown> = {}) => ({
  evaluate: vi.fn().mockResolvedValue(undefined),
  $: vi.fn().mockResolvedValue(null),
  on: vi.fn(),
  off: vi.fn(),
  url: vi.fn().mockReturnValue('https://example.com'),
  title: vi.fn().mockResolvedValue('Example'),
  evaluateOnNewDocument: vi.fn().mockResolvedValue(undefined),
  keyboard: { press: vi.fn() },
  goBack: vi.fn(),
  ...overrides,
});

const makeBrowser = (page: ReturnType<typeof makePuppeteerPage>) => ({
  pages: vi.fn().mockResolvedValue([page]),
  disconnect: vi.fn().mockResolvedValue(undefined),
});

// Mock puppeteer-core and chrome APIs before importing Page
vi.mock('puppeteer-core/lib/esm/puppeteer/puppeteer-core-browser.js', () => ({
  connect: vi.fn(),
  ExtensionTransport: { connectTab: vi.fn().mockResolvedValue({}) },
}));

vi.stubGlobal('chrome', {
  tabs: { get: vi.fn().mockResolvedValue({ url: 'https://example.com', title: 'Example' }) },
  scripting: { executeScript: vi.fn().mockResolvedValue([{ result: null }]) },
});

// Import AFTER mocks are set up
const { connect } = await import('puppeteer-core/lib/esm/puppeteer/puppeteer-core-browser.js');

describe('Page.attach() staleness probe', () => {
  it('re-attaches when _page.evaluate throws (stale connection)', async () => {
    const { default: Page } = await import('../../../page');
    const page = new Page(1);

    const stalePage = makePuppeteerPage({ evaluate: vi.fn().mockRejectedValue(new Error('Target closed')) });
    const freshPage = makePuppeteerPage();
    const browser = makeBrowser(stalePage);
    const freshBrowser = makeBrowser(freshPage);

    vi.mocked(connect)
      .mockResolvedValueOnce(browser as any)   // first attach
      .mockResolvedValueOnce(freshBrowser as any); // re-attach

    await page.attach();
    // Simulate the stale-probe path: calling attach again should detect stale + reconnect
    await page.attach();

    // connect was called twice (initial + re-attach after stale detection)
    expect(vi.mocked(connect)).toHaveBeenCalledTimes(2);
  });
});

describe('Page.detach() safety', () => {
  it('does not throw when browser.disconnect() rejects', async () => {
    const { default: Page } = await import('../../../page');
    const page = new Page(1);

    const puppeteerPage = makePuppeteerPage();
    const browser = makeBrowser(puppeteerPage);
    browser.disconnect = vi.fn().mockRejectedValue(new Error('Already disconnected'));
    vi.mocked(connect).mockResolvedValue(browser as any);

    await page.attach();
    // Should NOT throw even though disconnect() rejects
    await expect(page.detach()).resolves.toBeUndefined();
  });
});
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd /Users/loryschi/projects/jobstrainer/extension && npx vitest run background/browser/dom/__tests__/page.test.ts 2>&1 | tail -30
```

Expected: Tests fail — Page class does not yet re-attach on staleness or swallow disconnect errors.

- [ ] **Step 3: Implement the fixes in `page.ts`**

Replace the `attach()` and `detach()` methods (lines 48–68) with:

```typescript
async attach(): Promise<void> {
  // Staleness probe: if we think we're attached, verify the connection is live.
  if (this._page) {
    try {
      await this._page.evaluate('1');
      return; // Connection healthy — nothing to do.
    } catch {
      // CDP session went stale (e.g. cross-origin navigation).
      // Fall through to reconnect after clearing the old handles.
      this._browser = null;
      this._page = null;
      this._lastSelectorMap = null;
    }
  }

  logger.info('[Page] attaching to tab', this._tabId);
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
  if (!this._browser) return;
  try {
    await this._browser.disconnect();
  } catch {
    // Connection may already be gone — swallow and clean up handles.
  } finally {
    this._browser = null;
    this._page = null;
    this._lastSelectorMap = null;
  }
}
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /Users/loryschi/projects/jobstrainer/extension && npx vitest run background/browser/dom/__tests__/page.test.ts 2>&1 | tail -20
```

Expected: Both tests pass.

- [ ] **Step 5: Commit**

```bash
git add extension/background/browser/page.ts extension/background/browser/dom/__tests__/page.test.ts
git commit -m "fix(extension): safe attach/detach — stale probe + disconnect error swallow"
```

---

## Task 3: Refactor Element Location — `_getElementNode` + `_locateHandle` + Iframe Traversal

> Split the current `_locateElement(index)` into two focused helpers:
> - `_getElementNode(index)` — returns the `DOMElementNode` from the selector map cache, or a fresh DOM scan. Pure business logic, no Puppeteer.
> - `_locateHandle(node)` — traverses any iframe ancestors, then finds the `ElementHandle` via CSS/XPath. Uses the full Puppeteer frame tree.
>
> This separation makes each piece independently testable and enables iframe traversal (critical for embedded job apply widgets). After this task, `typeText` and `selectOption` are also updated to use the new helpers.

**Files:**
- Modify: `extension/background/browser/page.ts` (lines 1–16 imports, 161–184 `_locateElement`)
- Modify: `extension/background/browser/dom/__tests__/page.test.ts` (add tests)

- [ ] **Step 1: Add import for `Frame` type at top of `page.ts`**

The file currently ends its imports at line 16. Add one line:

```typescript
import type { Frame } from 'puppeteer-core/lib/esm/puppeteer/api/Frame.js';
```

Full import block after the change (replace lines 1–16):

```typescript
import {
  connect,
  ExtensionTransport,
  type HTTPRequest,
  type HTTPResponse,
  type ProtocolType,
} from 'puppeteer-core/lib/esm/puppeteer/puppeteer-core-browser.js';
import type { Browser } from 'puppeteer-core/lib/esm/puppeteer/api/Browser.js';
import type { Page as PuppeteerPage } from 'puppeteer-core/lib/esm/puppeteer/api/Page.js';
import type { Frame } from 'puppeteer-core/lib/esm/puppeteer/api/Frame.js';
import type { ElementHandle } from 'puppeteer-core/lib/esm/puppeteer/api/ElementHandle.js';
import {
  getClickableElements,
  getScrollInfo,
  injectBuildDomTreeScripts,
} from './dom/service';
import { type DOMState, DOMElementNode } from './dom/views';
```

- [ ] **Step 2: Write failing tests for `_getElementNode` and `_locateHandle`**

Add to `extension/background/browser/dom/__tests__/page.test.ts` (append after existing tests):

```typescript
describe('Page._getElementNode', () => {
  it('returns node from cache when present', async () => {
    const { default: Page } = await import('../../../page');
    const page = new Page(1);

    // Inject a fake selectorMap directly
    const fakeNode = new (await import('../views')).DOMElementNode({
      tagName: 'button', xpath: '/button', attributes: {}, children: [],
      isVisible: true, isInteractive: true, isTopElement: true, isInViewport: true,
      highlightIndex: 7, parent: null,
    });
    // @ts-expect-error accessing private for test
    page._lastSelectorMap = new Map([[7, fakeNode]]);

    // @ts-expect-error accessing private for test
    const result = await page._getElementNode(7);
    expect(result).toBe(fakeNode);
  });

  it('throws when index not found even after fresh scan', async () => {
    const { default: Page } = await import('../../../page');
    const page = new Page(1);
    // No cache, fresh scan returns empty map
    vi.mocked(chrome.scripting.executeScript).mockResolvedValue([{
      result: { map: {}, rootId: '0' }, frameId: 0, documentId: '',
    }] as any);

    // @ts-expect-error accessing private for test
    await expect(page._getElementNode(99)).rejects.toThrow('Element [99] not found');
  });
});

describe('Page._locateHandle iframe traversal', () => {
  it('queries inside iframe frame when element has iframe ancestor', async () => {
    const { default: Page } = await import('../../../page');
    const { DOMElementNode } = await import('../views');

    const p = new Page(1);

    const puppeteerPage = makePuppeteerPage();
    const browser = makeBrowser(puppeteerPage);
    vi.mocked(connect).mockResolvedValue(browser as any);
    await p.attach();

    // Build a DOMElementNode inside an iframe parent
    const iframeNode = new DOMElementNode({
      tagName: 'iframe', xpath: '/iframe', attributes: {}, children: [],
      isVisible: true, isInteractive: false, isTopElement: true, isInViewport: true,
      highlightIndex: null, parent: null,
    });
    const buttonNode = new DOMElementNode({
      tagName: 'button', xpath: '/button', attributes: {}, children: [],
      isVisible: true, isInteractive: true, isTopElement: true, isInViewport: true,
      highlightIndex: 3, parent: iframeNode,
    });
    iframeNode.children.push(buttonNode);

    // page.$() finds the iframe element, contentFrame() returns a fake frame
    const fakeHandle = makeElementHandle();
    const fakeIframeHandle = {
      contentFrame: vi.fn().mockResolvedValue({
        $: vi.fn().mockResolvedValue(fakeHandle),
      }),
    };
    puppeteerPage.$ = vi.fn()
      .mockResolvedValueOnce(fakeIframeHandle)   // iframe lookup
      .mockResolvedValueOnce(null);              // button via top-level (should not be called)

    // @ts-expect-error accessing private for test
    const result = await p._locateHandle(buttonNode);
    expect(result).toBe(fakeHandle);
  });
});
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
cd /Users/loryschi/projects/jobstrainer/extension && npx vitest run background/browser/dom/__tests__/page.test.ts 2>&1 | tail -30
```

Expected: New tests fail — `_getElementNode` and `_locateHandle` methods don't exist yet.

- [ ] **Step 4: Replace `_locateElement` with `_getElementNode` + `_locateHandle` in `page.ts`**

Delete the entire `_locateElement` method (lines 159–184) and replace with two methods:

```typescript
// Returns the DOMElementNode for the given highlight index, using the cached
// selectorMap from the last snapshot. Falls back to a fresh DOM scan if the
// cache is empty (e.g. first action after attach with no prior snapshot).
private async _getElementNode(index: number): Promise<DOMElementNode> {
  let node = this._lastSelectorMap?.get(index) ?? null;
  if (!node) {
    const tab = await chrome.tabs.get(this._tabId);
    const domState = await getClickableElements(this._tabId, tab.url ?? '', false);
    node = domState.selectorMap.get(index) ?? null;
  }
  if (!node) throw new Error(`Element [${index}] not found in DOM state`);
  return node;
}

// Returns an ElementHandle for the given DOMElementNode. Handles iframe ancestors:
// walks up the parent chain to build the frame traversal path, then queries inside
// the deepest matching frame. Falls back from CSS selector to XPath on failure.
private async _locateHandle(node: DOMElementNode): Promise<ElementHandle> {
  const page = this._requirePage();

  // Build the iframe chain by walking up the parent tree.
  const iframes: DOMElementNode[] = [];
  let current: DOMElementNode | null = node.parent;
  while (current) {
    if (current.tagName === 'iframe') iframes.unshift(current);
    current = current.parent;
  }

  // Traverse into each iframe frame in order (top → deepest).
  let frame: PuppeteerPage | Frame = page;
  for (const iframeNode of iframes) {
    const iframeSelector = iframeNode.getEnhancedCssSelector();
    const iframeEl = await frame.$(iframeSelector);
    if (!iframeEl) throw new Error(`iframe not found: ${iframeSelector}`);
    const childFrame = await (iframeEl as ElementHandle).contentFrame();
    if (!childFrame) throw new Error(`iframe frame inaccessible: ${iframeSelector}`);
    frame = childFrame as Frame;
  }

  // Query the target element inside the resolved frame.
  const cssSelector = node.getEnhancedCssSelector();
  let el: ElementHandle | null = await frame.$(cssSelector);

  if (!el && node.xpath) {
    const xpath = node.xpath.startsWith('/') ? node.xpath : `/${node.xpath}`;
    el = await frame.$(`::-p-xpath(${xpath})`);
  }

  if (!el) throw new Error(`Element not located (css: ${cssSelector})`);
  return el;
}
```

- [ ] **Step 5: Update all callers of old `_locateElement` to use the two new helpers**

In `page.ts`, the methods `clickElement`, `typeText`, and `selectOption` called `_locateElement`. Update each:

**`clickElement`** (lines 188–191) — update to call both helpers (full fix in Task 4):
```typescript
// Temporary: updated to compile — full click logic added in Task 4
async clickElement(index: number): Promise<void> {
  const node = await this._getElementNode(index);
  const el = await this._locateHandle(node);
  await el.click();
}
```

**`typeText`** (lines 193–209) — update first two lines:
```typescript
async typeText(index: number, text: string): Promise<void> {
  const node = await this._getElementNode(index);
  const el = await this._locateHandle(node);
  // ... rest of method unchanged
```

**`selectOption`** (lines 211–219) — update first two lines:
```typescript
async selectOption(index: number, text: string): Promise<void> {
  const node = await this._getElementNode(index);
  const el = await this._locateHandle(node);
  // ... rest of method unchanged
```

- [ ] **Step 6: Run tests to confirm they pass**

```bash
cd /Users/loryschi/projects/jobstrainer/extension && npx vitest run background/browser/dom/__tests__/page.test.ts 2>&1 | tail -20
```

Expected: All tests pass.

- [ ] **Step 7: Build to verify TypeScript compiles**

```bash
cd /Users/loryschi/projects/jobstrainer/extension && npm run build 2>&1 | grep -E "error|warning|✓" | head -20
```

Expected: Build succeeds, no TypeScript errors.

- [ ] **Step 8: Commit**

```bash
git add extension/background/browser/page.ts extension/background/browser/dom/__tests__/page.test.ts
git commit -m "refactor(extension): split _locateElement into _getElementNode + _locateHandle with iframe traversal"
```

---

## Task 4: Scroll-Into-View + Fallback Click

> The most impactful fix. Adds `_scrollIntoViewIfNeeded` (ported from nanobrowser) and rewrites `clickElement` with:
> 1. Scroll element into view
> 2. Puppeteer CDP click with 2 s timeout
> 3. Fallback to `el.evaluate(() => el.click())` if CDP click fails

**Files:**
- Modify: `extension/background/browser/page.ts`
- Modify: `extension/background/browser/dom/__tests__/page.test.ts`

- [ ] **Step 1: Write failing tests**

Append to `extension/background/browser/dom/__tests__/page.test.ts`:

```typescript
describe('Page._scrollIntoViewIfNeeded', () => {
  it('calls scrollIntoView when element is off-screen', async () => {
    const { default: Page } = await import('../../../page');
    const p = new Page(1);
    const puppeteerPage = makePuppeteerPage();
    const browser = makeBrowser(puppeteerPage);
    vi.mocked(connect).mockResolvedValue(browser as any);
    await p.attach();

    // First call: off-screen (returns false → triggers scroll)
    // Second call: in-viewport (returns true → done)
    const scrollIntoViewMock = vi.fn();
    const el = makeElementHandle({
      evaluate: vi.fn()
        .mockResolvedValueOnce(false)  // not in viewport, scroll triggered inside evaluate
        .mockResolvedValueOnce(true),  // now in viewport
    });

    // @ts-expect-error accessing private for test
    await p._scrollIntoViewIfNeeded(el as any);
    // Evaluate was called at least twice (once off-screen, once confirming in-view)
    expect(el.evaluate).toHaveBeenCalledTimes(2);
  });
});

describe('Page.clickElement fallback', () => {
  it('falls back to evaluate click when CDP click throws', async () => {
    const { default: Page } = await import('../../../page');
    const { DOMElementNode } = await import('../views');

    const p = new Page(1);
    const puppeteerPage = makePuppeteerPage();
    const browser = makeBrowser(puppeteerPage);
    vi.mocked(connect).mockResolvedValue(browser as any);
    await p.attach();

    const node = new DOMElementNode({
      tagName: 'button', xpath: '/button', attributes: {}, children: [],
      isVisible: true, isInteractive: true, isTopElement: true, isInViewport: true,
      highlightIndex: 5, parent: null,
    });
    // @ts-expect-error accessing private for test
    p._lastSelectorMap = new Map([[5, node]]);

    const evaluateMock = vi.fn()
      .mockResolvedValueOnce(true)         // _scrollIntoViewIfNeeded: already in viewport
      .mockResolvedValueOnce(undefined);   // fallback click via evaluate

    const el = makeElementHandle({
      click: vi.fn().mockRejectedValue(new Error('Node is detached')),
      evaluate: evaluateMock,
    });
    puppeteerPage.$ = vi.fn().mockResolvedValue(el);

    await expect(p.clickElement(5)).resolves.toBeUndefined();
    // evaluate was called for fallback click
    expect(evaluateMock).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/loryschi/projects/jobstrainer/extension && npx vitest run background/browser/dom/__tests__/page.test.ts 2>&1 | tail -20
```

Expected: New tests fail.

- [ ] **Step 3: Add `_scrollIntoViewIfNeeded` method to `page.ts`**

Insert after the `_waitForStableNetwork` closing brace, before `waitForPageAndFramesLoad`:

```typescript
// Scrolls the element into the viewport if it is off-screen. Polls up to
// `timeoutMs` (default 1 s) then gives up silently — better to attempt the
// click than to block indefinitely on a hidden element.
private async _scrollIntoViewIfNeeded(element: ElementHandle, timeoutMs = 1000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const isVisible: boolean = await element.evaluate(el => {
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return false;
      const style = window.getComputedStyle(el);
      if (style.visibility === 'hidden' || style.display === 'none' || style.opacity === '0') {
        return false;
      }
      const inViewport =
        rect.top >= 0 && rect.left >= 0 &&
        rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
        rect.right <= (window.innerWidth || document.documentElement.clientWidth);
      if (!inViewport) {
        el.scrollIntoView({ behavior: 'auto', block: 'center', inline: 'center' });
      }
      return inViewport;
    });
    if (isVisible) return;
    await new Promise(r => setTimeout(r, 100));
  }
}
```

- [ ] **Step 4: Rewrite `clickElement` with scroll + timeout + fallback**

Replace the temporary `clickElement` from Task 3 with:

```typescript
// Dispatches a real CDP click (mousedown/mouseup/click). Before clicking:
//   1. Scroll the element into view so coordinates land inside the viewport.
//   2. Try Puppeteer click with a 2 s timeout (handles hung click promises).
//   3. Fall back to direct DOM dispatch if CDP click is rejected — covers React
//      portals and elements that intercept synthetic pointer events.
async clickElement(index: number): Promise<void> {
  const node = await this._getElementNode(index);
  const el = await this._locateHandle(node);
  await this._scrollIntoViewIfNeeded(el);
  try {
    await Promise.race([
      el.click(),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('click timeout')), 2000)
      ),
    ]);
  } catch {
    // CDP click timed out or was rejected — dispatch directly on the DOM node.
    await el.evaluate((node: Element) => (node as HTMLElement).click());
  }
}
```

- [ ] **Step 5: Run tests**

```bash
cd /Users/loryschi/projects/jobstrainer/extension && npx vitest run background/browser/dom/__tests__/page.test.ts 2>&1 | tail -20
```

Expected: All tests pass.

- [ ] **Step 6: Build**

```bash
cd /Users/loryschi/projects/jobstrainer/extension && npm run build 2>&1 | grep -E "error|✓" | head -10
```

Expected: Clean build.

- [ ] **Step 7: Commit**

```bash
git add extension/background/browser/page.ts extension/background/browser/dom/__tests__/page.test.ts
git commit -m "fix(extension): scroll-into-view + fallback click — main click reliability fix"
```

---

## Task 5: Fix `navigate()` to Detach Before Navigation

> When `go_to_url` is executed inside `execute_actions`, `s.page.navigate(url)` is called while Puppeteer is still attached. Cross-origin navigations invalidate the CDP session, causing silent failures. The fix: `navigate()` detaches before calling `chrome.tabs.update`, so the caller's `detach()+attach()` in `service_worker.ts` is always a clean reconnect.

**Files:**
- Modify: `extension/background/browser/page.ts` (lines 254–256)

- [ ] **Step 1: Replace `navigate()` in `page.ts`**

Find the current implementation (around line 254):
```typescript
async navigate(url: string): Promise<void> {
  await chrome.tabs.update(this._tabId, { url });
}
```

Replace with:
```typescript
// Detaches the Puppeteer session before instructing Chrome to navigate. When
// chrome.tabs.update triggers a cross-origin navigation the CDP session would be
// invalidated mid-flight anyway — detaching first makes the failure explicit and
// clean. The caller (service_worker.ts executeAction) always re-attaches after
// receiving the navigation-complete signal.
async navigate(url: string): Promise<void> {
  await this.detach();
  await chrome.tabs.update(this._tabId, { url });
}
```

- [ ] **Step 2: Build**

```bash
cd /Users/loryschi/projects/jobstrainer/extension && npm run build 2>&1 | grep -E "error|✓" | head -10
```

Expected: Clean build, no TypeScript errors.

- [ ] **Step 3: Commit**

```bash
git add extension/background/browser/page.ts
git commit -m "fix(extension): detach puppeteer before chrome.tabs.update in navigate()"
```

---

## Task 6: Fix Navigation Log Entry — Remove Infinite Spinner

> `appendLog(tabId, { ..., done: false })` is written before navigation starts, and never updated to `done: true`. The panel renders `done: false` entries with an animated spinner that persists forever. Fix: write the log entry *after* navigation completes with `done: true`, or log it as done immediately (since the user sees it only after it's complete). The second approach avoids any log-update mechanism.

**Files:**
- Modify: `extension/background/service_worker.ts` (lines 186–198)

- [ ] **Step 1: Move the log entry in the `navigate` handler**

Find the `navigate` message handler (around line 186):

```typescript
if (msg.type === 'navigate') {
  s.currentStatus = 'navigating';
  appendLog(tabId, { kind: 'step', text: `Navigating to ${safeHostname(msg.url)}…`, done: false });
  await s.page.detach();
  const navDone = waitForNavCompleted(tabId);
  await chrome.tabs.update(tabId, { url: msg.url });
  await navDone;
  await s.page.attach();
  const snap = await s.page.snapshot();
  s.ws.send(JSON.stringify(snap));
  return;
}
```

Replace with (log entry moved to after navigation, `done: true`):

```typescript
if (msg.type === 'navigate') {
  s.currentStatus = 'navigating';
  await s.page.detach();
  const navDone = waitForNavCompleted(tabId);
  await chrome.tabs.update(tabId, { url: msg.url });
  await navDone;
  await s.page.attach();
  const snap = await s.page.snapshot();
  appendLog(tabId, { kind: 'step', text: `Navigated to ${safeHostname(msg.url)}`, done: true });
  s.ws.send(JSON.stringify(snap));
  return;
}
```

- [ ] **Step 2: Build**

```bash
cd /Users/loryschi/projects/jobstrainer/extension && npm run build 2>&1 | grep -E "error|✓" | head -10
```

Expected: Clean build.

- [ ] **Step 3: Commit**

```bash
git add extension/background/service_worker.ts
git commit -m "fix(extension): mark navigation log entry as done after nav completes"
```

---

## Task 7: Fix Error Handler to Prevent Backend Hang

> When any exception is thrown inside `handleAgentMessage`, the outer `ws.onmessage` catches it and logs it — but never sends a response back. The backend's `interrupt()` call blocks indefinitely waiting for a snapshot. Fix: detect which message types require a response and send a safe empty snapshot on error. The backend will see `no_progress_count` increment (identical URL + empty elements), and after 4 no-progress steps it will surface a "stuck" message to the user — far better than hanging forever.

**Files:**
- Modify: `extension/background/service_worker.ts` (lines 149–153)

- [ ] **Step 1: Replace the `ws.onmessage` error handler**

Find (around line 149):

```typescript
ws.onmessage = async (event) => {
  try { await handleAgentMessage(tabId, JSON.parse(event.data)); } catch (e) {
    console.error('[tailorer] handleAgentMessage error', e);
  }
};
```

Replace with:

```typescript
ws.onmessage = async (event) => {
  let msg: any;
  try {
    msg = JSON.parse(event.data);
    await handleAgentMessage(tabId, msg);
  } catch (e) {
    console.error('[tailorer] handleAgentMessage error', e);
    // Message types that require a snapshot response. If we swallow the error
    // without responding, the backend's interrupt() blocks forever.
    const needsResponse = msg && ['navigate', 'request_snapshot', 'execute_actions'].includes(msg.type);
    const s = sessions[tabId];
    if (needsResponse && s?.ws.readyState === WebSocket.OPEN) {
      const tab = await chrome.tabs.get(tabId).catch(() => null);
      const url = tab?.url ?? '';
      s.ws.send(JSON.stringify({ url, title: tab?.title ?? '', elements: '', scroll_y: 0, scroll_height: 0, viewport_height: 0 }));
    }
  }
};
```

- [ ] **Step 2: Build**

```bash
cd /Users/loryschi/projects/jobstrainer/extension && npm run build 2>&1 | grep -E "error|✓" | head -10
```

Expected: Clean build.

- [ ] **Step 3: Run all extension tests**

```bash
cd /Users/loryschi/projects/jobstrainer/extension && npm test 2>&1 | tail -20
```

Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add extension/background/service_worker.ts
git commit -m "fix(extension): send empty snapshot on error to prevent backend hang"
```

---

## Task 8: Final Build, Load, and Integration Verification

> Build the full extension, load it in Chrome developer mode, and verify the golden path: navigate to a job site, agent navigates to the apply form, clicks elements, and the UI shows completed (✓) log entries.

**Files:**
- No code changes — build + manual verification only.

- [ ] **Step 1: Full clean build**

```bash
cd /Users/loryschi/projects/jobstrainer/extension && npm run build 2>&1
```

Expected:
- No TypeScript errors
- `dist/background/service_worker.js` updated (check mtime)
- `dist/sidepanel/` updated

- [ ] **Step 2: Verify the compiled output contains key new code**

```bash
grep -c "scrollIntoView" /Users/loryschi/projects/jobstrainer/extension/dist/background/service_worker.js
grep -c "contentFrame" /Users/loryschi/projects/jobstrainer/extension/dist/background/service_worker.js
grep -c "click timeout" /Users/loryschi/projects/jobstrainer/extension/dist/background/service_worker.js
```

Expected: Each command returns `1` (or more). If any returns `0`, the corresponding fix didn't make it into the build.

- [ ] **Step 3: Load extension in Chrome**

1. Open `chrome://extensions`
2. Enable "Developer mode" (top right toggle)
3. Click "Load unpacked" → select `extension/dist/`
4. Confirm the extension loads without errors in the Extensions page

- [ ] **Step 4: Manual integration test — click a real apply button**

1. Start the backend: `cd backend && uv run uvicorn backend.main:app --reload`
2. Navigate to a job listing on the frontend (`http://localhost:3000`)
3. Click the "Apply" button to open the Tailorer side panel
4. Click "⚡ Start Agent"
5. Observe the panel:
   - "Session started" ✓ (done)
   - "Navigated to [company].com" ✓ (done — no infinite spinner)
   - "Clicking [N]" ✓ — and the page **actually changes** (button responds)
6. Confirm the agent reaches the application form without getting stuck

- [ ] **Step 5: Test with an embedded iframe form**

Navigate to a job on a company that uses Greenhouse or Lever (embedded iframe). Confirm:
- Elements inside the iframe are listed in the snapshot
- Clicking them works (iframe traversal)

Common sites to test: greenhouse.io hosted jobs (e.g. `boards.greenhouse.io/company/jobs/jobid`), Lever (`jobs.lever.co`), or Workday.

- [ ] **Step 6: Commit final build note**

```bash
git add -A
git commit -m "chore(extension): rebuild dist after click/navigation fixes"
```

---

## Self-Review

### Spec Coverage Checklist

| Requirement | Covered by |
|------------|-----------|
| Off-screen elements not clicked | Task 4 (`_scrollIntoViewIfNeeded`) |
| SPA buttons ignoring CDP click | Task 4 (fallback `evaluate(() => el.click())`) |
| Iframe-embedded apply widgets | Task 3 (`_locateHandle` iframe traversal) |
| Cross-origin navigation corrupts CDP | Task 5 (`navigate()` detaches first) |
| Stale connection prevents reattach | Task 2 (staleness probe in `attach()`) |
| Backend hangs on extension error | Task 7 (empty snapshot on error) |
| Navigation spinner never clears | Task 6 (log entry moved to after nav, `done: true`) |
| Dead source file causes confusion | Task 1 (delete `service_worker.js`) |
| `detach()` throws on broken conn | Task 2 (`try/finally` in `detach()`) |

### Placeholder Scan

No TBD, TODO, "similar to", or "handle edge cases" phrases present. All code blocks are complete.

### Type Consistency Check

- `_getElementNode(index: number): Promise<DOMElementNode>` — defined Task 3, called in Task 4 (`clickElement`), `typeText`, `selectOption`
- `_locateHandle(node: DOMElementNode): Promise<ElementHandle>` — defined Task 3, same callers
- `_scrollIntoViewIfNeeded(element: ElementHandle, timeoutMs?: number): Promise<void>` — defined Task 4, called in `clickElement` only
- `Frame` imported in Task 3, used as `PuppeteerPage | Frame` type for `currentFrame` — consistent
- `detach()` is now safe to call multiple times (Task 2) — `navigate()` calls it (Task 5), service_worker calls it — consistent
