import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ── Stubs ──────────────────────────────────────────────────────────────────

const makeElementHandle = (overrides: Record<string, unknown> = {}) => ({
  click: vi.fn().mockResolvedValue(undefined),
  evaluate: vi.fn().mockResolvedValue(true),
  boundingBox: vi.fn().mockResolvedValue({ x: 10, y: 10, width: 100, height: 40 }),
  dispose: vi.fn().mockResolvedValue(undefined),
  ...overrides,
});

// Wraps an ElementHandle (or null) in a Puppeteer JSHandle-shaped mock.
// evaluateHandle() returns JSHandle, not ElementHandle directly — callers
// must call .asElement() to get the ElementHandle (or null if not an element).
const makeJsHandle = (element: ReturnType<typeof makeElementHandle> | null) => ({
  asElement: vi.fn().mockReturnValue(element),
  dispose: vi.fn().mockResolvedValue(undefined),
});

const makePuppeteerPage = (overrides: Record<string, unknown> = {}) => ({
  evaluate: vi.fn().mockResolvedValue(undefined),
  evaluateHandle: vi.fn().mockResolvedValue(makeJsHandle(null)),
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

// ── Module mocks (must be before any dynamic import of Page) ──────────────

vi.mock('puppeteer-core/lib/esm/puppeteer/puppeteer-core-browser.js', () => ({
  connect: vi.fn(),
  ExtensionTransport: { connectTab: vi.fn().mockResolvedValue({}) },
}));

vi.mock('../service', () => ({
  getClickableElements: vi.fn().mockResolvedValue({
    selectorMap: new Map(),
    elementTree: { clickableElementsToString: () => '' },
  }),
  injectBuildDomTreeScripts: vi.fn().mockResolvedValue(undefined),
}));

vi.stubGlobal('chrome', {
  tabs: {
    get: vi.fn().mockResolvedValue({ url: 'https://example.com', title: 'Example' }),
  },
  scripting: {
    executeScript: vi.fn().mockResolvedValue([{ result: null, frameId: 0, documentId: '' }]),
  },
  alarms: { create: vi.fn(), onAlarm: { addListener: vi.fn() } },
  storage: { local: { set: vi.fn(), get: vi.fn() } },
});

// ── Tests ─────────────────────────────────────────────────────────────────

describe('Page.attach() staleness probe', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('re-attaches when _page.evaluate throws (stale connection)', async () => {
    const { connect } = await import('puppeteer-core/lib/esm/puppeteer/puppeteer-core-browser.js');
    const { default: Page } = await import('../../page');

    const stalePuppeteerPage = makePuppeteerPage({
      evaluate: vi.fn().mockRejectedValue(new Error('Target closed')),
    });
    const freshPuppeteerPage = makePuppeteerPage();
    const staleBrowser = makeBrowser(stalePuppeteerPage);
    const freshBrowser = makeBrowser(freshPuppeteerPage);

    vi.mocked(connect)
      .mockResolvedValueOnce(staleBrowser as any)
      .mockResolvedValueOnce(freshBrowser as any);

    const page = new Page(1);
    await page.attach();           // first attach — installs stale connection
    await page.attach();           // second attach — should detect stale + reconnect

    expect(vi.mocked(connect)).toHaveBeenCalledTimes(2);
  });
});

describe('Page.attach() — stale probe disconnects browser before clearing refs', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('calls browser.disconnect() when staleness probe throws', async () => {
    const { connect } = await import('puppeteer-core/lib/esm/puppeteer/puppeteer-core-browser.js');
    const { default: Page } = await import('../../page');

    const stalePuppeteerPage = makePuppeteerPage({
      evaluate: vi.fn().mockRejectedValue(new Error('Target closed')),
    });
    const freshPuppeteerPage = makePuppeteerPage();
    const staleBrowser = makeBrowser(stalePuppeteerPage);
    const freshBrowser = makeBrowser(freshPuppeteerPage);

    vi.mocked(connect)
      .mockResolvedValueOnce(staleBrowser as any)
      .mockResolvedValueOnce(freshBrowser as any);

    const page = new Page(1);
    await page.attach();          // sets up stale connection
    await page.attach();          // probe fails → should disconnect before clearing

    expect(staleBrowser.disconnect).toHaveBeenCalledTimes(1);
  });

  it('does not throw if disconnect() rejects during stale cleanup', async () => {
    const { connect } = await import('puppeteer-core/lib/esm/puppeteer/puppeteer-core-browser.js');
    const { default: Page } = await import('../../page');

    const stalePuppeteerPage = makePuppeteerPage({
      evaluate: vi.fn().mockRejectedValue(new Error('Target closed')),
    });
    const freshPuppeteerPage = makePuppeteerPage();
    const staleBrowser = makeBrowser(stalePuppeteerPage);
    staleBrowser.disconnect = vi.fn().mockRejectedValue(new Error('Already gone'));
    const freshBrowser = makeBrowser(freshPuppeteerPage);

    vi.mocked(connect)
      .mockResolvedValueOnce(staleBrowser as any)
      .mockResolvedValueOnce(freshBrowser as any);

    const page = new Page(1);
    await page.attach();
    await expect(page.attach()).resolves.toBeUndefined();
  });
});

describe('Page.detach() safety', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('does not throw when browser.disconnect() rejects', async () => {
    const { connect } = await import('puppeteer-core/lib/esm/puppeteer/puppeteer-core-browser.js');
    const { default: Page } = await import('../../page');

    const puppeteerPage = makePuppeteerPage();
    const browser = makeBrowser(puppeteerPage);
    browser.disconnect = vi.fn().mockRejectedValue(new Error('Already disconnected'));
    vi.mocked(connect).mockResolvedValue(browser as any);

    const page = new Page(1);
    await page.attach();
    await expect(page.detach()).resolves.toBeUndefined();
  });

  it('is safe to call when not attached', async () => {
    const { default: Page } = await import('../../page');
    const page = new Page(1);
    await expect(page.detach()).resolves.toBeUndefined();
  });
});

describe('Page.detach() — settle delay', () => {
  beforeEach(() => { vi.clearAllMocks(); vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it('waits ~50 ms after disconnect before resolving', async () => {
    const { connect } = await import('puppeteer-core/lib/esm/puppeteer/puppeteer-core-browser.js');
    const { default: Page } = await import('../../page');

    const puppeteerPage = makePuppeteerPage();
    const browser = makeBrowser(puppeteerPage);
    vi.mocked(connect).mockResolvedValue(browser as any);

    const page = new Page(1);
    await page.attach();

    let resolved = false;
    const detachPromise = page.detach().then(() => { resolved = true; });

    await vi.advanceTimersByTimeAsync(49);
    expect(resolved).toBe(false);

    await vi.advanceTimersByTimeAsync(2);
    await detachPromise;
    expect(resolved).toBe(true);
  });
});

// ── Test helpers used across multiple test suites ─────────────────────────

async function getConnectMock() {
  const mod = await import('puppeteer-core/lib/esm/puppeteer/puppeteer-core-browser.js');
  return vi.mocked(mod.connect);
}

// ── _getElementNode ───────────────────────────────────────────────────────

describe('Page._getElementNode', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('returns node from cache when present', async () => {
    const { default: Page } = await import('../../page');
    const { DOMElementNode } = await import('../views');

    const p = new Page(1);
    const node = new DOMElementNode({
      tagName: 'button', xpath: '/button', attributes: {}, children: [],
      isVisible: true, isInteractive: true, isTopElement: true, isInViewport: true,
      highlightIndex: 7, parent: null,
    });
    // @ts-expect-error private field access for test
    p._lastSelectorMap = new Map([[7, node]]);

    // @ts-expect-error private method access for test
    const result = await p._getElementNode(7);
    expect(result).toBe(node);
  });

  it('throws when index not found in cache and fresh scan', async () => {
    const connectMock = await getConnectMock();
    const { default: Page } = await import('../../page');

    const p = new Page(1);
    // No cache; mock scripting.executeScript to return an empty DOM tree
    vi.mocked(chrome.scripting.executeScript).mockResolvedValue([{
      result: { map: { '0': { tagName: 'body', xpath: '', attributes: {}, children: [], isVisible: false, isInteractive: false, isTopElement: false, isInViewport: false } }, rootId: '0' },
      frameId: 0, documentId: '',
    }] as any);

    // @ts-expect-error private method access for test
    await expect(p._getElementNode(99)).rejects.toThrow('Element [99] not found');
  });
});

// ── _locateHandle iframe traversal ────────────────────────────────────────

describe('Page._locateHandle', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('queries inside iframe frame when element has iframe ancestor', async () => {
    const connectMock = await getConnectMock();
    const { default: Page } = await import('../../page');
    const { DOMElementNode } = await import('../views');

    const p = new Page(1);
    const puppeteerPage = makePuppeteerPage();
    const browser = makeBrowser(puppeteerPage);
    connectMock.mockResolvedValue(browser as any);
    await p.attach();

    // Build a DOMElementNode inside an iframe parent
    const iframeNode = new DOMElementNode({
      tagName: 'iframe', xpath: '/iframe', attributes: {}, children: [],
      isVisible: true, isInteractive: false, isTopElement: true, isInViewport: true,
      highlightIndex: null, parent: null,
    });
    const buttonNode = new DOMElementNode({
      tagName: 'button', xpath: '/html/body/button', attributes: {}, children: [],
      isVisible: true, isInteractive: true, isTopElement: true, isInViewport: true,
      highlightIndex: 3, parent: iframeNode,
    });
    iframeNode.children.push(buttonNode);

    // _locateHandle uses frame.$() for CSS lookup.
    // Top page: $ finds the iframe element; child frame: $ finds the button via CSS.
    const buttonHandle = makeElementHandle();
    const childFrame = {
      $: vi.fn().mockResolvedValue(buttonHandle),
      evaluateHandle: vi.fn().mockResolvedValue(makeJsHandle(null)),
    };
    const fakeIframeEl = makeElementHandle({
      contentFrame: vi.fn().mockResolvedValue(childFrame),
    });
    (puppeteerPage as any).$ = vi.fn().mockResolvedValue(fakeIframeEl);

    // @ts-expect-error private method access for test
    const result = await p._locateHandle(buttonNode);
    expect(result).toBe(buttonHandle);
  });

  it('falls back to XPath when CSS selector returns null', async () => {
    const connectMock = await getConnectMock();
    const { default: Page } = await import('../../page');
    const { DOMElementNode } = await import('../views');

    const p = new Page(1);
    const puppeteerPage = makePuppeteerPage();
    const browser = makeBrowser(puppeteerPage);
    connectMock.mockResolvedValue(browser as any);
    await p.attach();

    const buttonNode = new DOMElementNode({
      tagName: 'button', xpath: '/html/body/button',
      attributes: {}, children: [],
      isVisible: true, isInteractive: true, isTopElement: true, isInViewport: true,
      highlightIndex: 5, parent: null,
    });

    const buttonHandle = makeElementHandle();
    // CSS miss (default $ returns null) → XPath hit on the first evaluateHandle call.
    puppeteerPage.evaluateHandle = vi.fn()
      .mockResolvedValueOnce(makeJsHandle(buttonHandle));

    // @ts-expect-error private method access for test
    const result = await p._locateHandle(buttonNode);
    expect(result).toBe(buttonHandle);
  });

  it('traverses nested iframes in top-to-bottom order', async () => {
    const connectMock = await getConnectMock();
    const { default: Page } = await import('../../page');
    const { DOMElementNode } = await import('../views');

    const p = new Page(1);
    const topPage = makePuppeteerPage();
    const browser = makeBrowser(topPage);
    connectMock.mockResolvedValue(browser as any);
    await p.attach();

    // Structure: outerIframe > innerIframe > button
    const outerIframe = new DOMElementNode({
      tagName: 'iframe', xpath: '/iframe[1]', attributes: { id: 'outer' }, children: [],
      isVisible: true, isInteractive: false, isTopElement: true, isInViewport: true,
      highlightIndex: null, parent: null,
    });
    const innerIframe = new DOMElementNode({
      tagName: 'iframe', xpath: '/iframe[1]', attributes: { id: 'inner' }, children: [],
      isVisible: true, isInteractive: false, isTopElement: true, isInViewport: true,
      highlightIndex: null, parent: outerIframe,
    });
    const buttonNode = new DOMElementNode({
      tagName: 'button', xpath: '/button', attributes: {}, children: [],
      isVisible: true, isInteractive: true, isTopElement: true, isInViewport: true,
      highlightIndex: 8, parent: innerIframe,
    });
    outerIframe.children.push(innerIframe);
    innerIframe.children.push(buttonNode);

    const buttonHandle = makeElementHandle();

    // _locateHandle uses frame.$() for iframe and CSS element lookup.
    // innerFrame: $ finds the button element via CSS.
    const innerFrameMock = {
      $: vi.fn().mockResolvedValue(buttonHandle),
      evaluateHandle: vi.fn().mockResolvedValue(makeJsHandle(null)),
    };
    // outerFrame: $ finds the inner iframe element handle
    const innerIframeEl = makeElementHandle({
      contentFrame: vi.fn().mockResolvedValue(innerFrameMock),
    });
    const outerFrameMock = {
      $: vi.fn().mockResolvedValue(innerIframeEl),
      evaluateHandle: vi.fn().mockResolvedValue(makeJsHandle(null)),
    };
    // top-level page: $ finds the outer iframe element handle
    const outerIframeEl = makeElementHandle({
      contentFrame: vi.fn().mockResolvedValue(outerFrameMock),
    });
    (topPage as any).$ = vi.fn().mockResolvedValue(outerIframeEl);

    // @ts-expect-error private method access for test
    const result = await p._locateHandle(buttonNode);

    expect(result).toBe(buttonHandle);
    // Verify traversal order: top page → outer frame → inner frame
    expect((topPage as any).$).toHaveBeenCalledTimes(1);     // outer iframe from top page
    expect(outerFrameMock.$).toHaveBeenCalledTimes(1);        // inner iframe from outer frame
    expect(innerFrameMock.$).toHaveBeenCalledTimes(1);        // button from inner frame
  });
});

// ── _scrollIntoViewIfNeeded ───────────────────────────────────────────────

describe('Page._scrollIntoViewIfNeeded', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('returns immediately when element is already in viewport', async () => {
    const connectMock = await getConnectMock();
    const { default: Page } = await import('../../page');

    const p = new Page(1);
    const puppeteerPage = makePuppeteerPage();
    const browser = makeBrowser(puppeteerPage);
    connectMock.mockResolvedValue(browser as any);
    await p.attach();

    const el = makeElementHandle({ evaluate: vi.fn().mockResolvedValue(true) });

    // @ts-expect-error private method access for test
    await p._scrollIntoViewIfNeeded(el as any);

    expect(el.evaluate).toHaveBeenCalledTimes(1);
  });

  it('calls evaluate again after off-screen result until in-viewport', async () => {
    const connectMock = await getConnectMock();
    const { default: Page } = await import('../../page');

    const p = new Page(1);
    const puppeteerPage = makePuppeteerPage();
    const browser = makeBrowser(puppeteerPage);
    connectMock.mockResolvedValue(browser as any);
    await p.attach();

    // First call: off-screen; second call: in-viewport
    const el = makeElementHandle({
      evaluate: vi.fn()
        .mockResolvedValueOnce(false)
        .mockResolvedValueOnce(true),
    });

    // @ts-expect-error private method access for test
    await p._scrollIntoViewIfNeeded(el as any);

    expect(el.evaluate).toHaveBeenCalledTimes(2);
  });
});

// ── clickElement fallback ─────────────────────────────────────────────────

describe('Page.clickElement', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('falls back to evaluate click when CDP click throws', async () => {
    const connectMock = await getConnectMock();
    const { default: Page } = await import('../../page');
    const { DOMElementNode } = await import('../views');

    const p = new Page(1);
    const puppeteerPage = makePuppeteerPage();
    const browser = makeBrowser(puppeteerPage);
    connectMock.mockResolvedValue(browser as any);
    await p.attach();

    const node = new DOMElementNode({
      tagName: 'button', xpath: '/button', attributes: {}, children: [],
      isVisible: true, isInteractive: true, isTopElement: true, isInViewport: true,
      highlightIndex: 5, parent: null,
    });
    // @ts-expect-error private field access for test
    p._lastSelectorMap = new Map([[5, node]]);

    let evaluateCallCount = 0;
    const el = makeElementHandle({
      click: vi.fn().mockRejectedValue(new Error('Node is detached')),
      evaluate: vi.fn().mockImplementation(() => {
        evaluateCallCount++;
        // First call is from _scrollIntoViewIfNeeded (returns true = in viewport)
        // Second call is from fallback click
        return Promise.resolve(evaluateCallCount === 1 ? true : undefined);
      }),
    });
    // _locateHandle uses frame.$() for CSS lookup — override the default null mock.
    (puppeteerPage as any).$ = vi.fn().mockResolvedValue(el);

    await expect(p.clickElement(5)).resolves.toBeUndefined();
    // evaluate must have been called at least twice
    expect(evaluateCallCount).toBeGreaterThanOrEqual(2);
  });

  it('succeeds with primary CDP click when it does not throw', async () => {
    const connectMock = await getConnectMock();
    const { default: Page } = await import('../../page');
    const { DOMElementNode } = await import('../views');

    const p = new Page(1);
    const puppeteerPage = makePuppeteerPage();
    const browser = makeBrowser(puppeteerPage);
    connectMock.mockResolvedValue(browser as any);
    await p.attach();

    const node = new DOMElementNode({
      tagName: 'button', xpath: '/button', attributes: {}, children: [],
      isVisible: true, isInteractive: true, isTopElement: true, isInViewport: true,
      highlightIndex: 6, parent: null,
    });
    // @ts-expect-error private field access for test
    p._lastSelectorMap = new Map([[6, node]]);

    const clickMock = vi.fn().mockResolvedValue(undefined);
    const el = makeElementHandle({
      click: clickMock,
      evaluate: vi.fn().mockResolvedValue(true), // in viewport
    });
    // _locateHandle uses frame.$() for CSS lookup — override the default null mock.
    (puppeteerPage as any).$ = vi.fn().mockResolvedValue(el);

    await p.clickElement(6);
    expect(clickMock).toHaveBeenCalledTimes(1);
  });
});

// ── _locateHandle stale snapshot retry ───────────────────────────────────

describe('Page._locateHandle — stale snapshot retry', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('invalidates cache and retries locate on first miss', async () => {
    const { connect } = await import('puppeteer-core/lib/esm/puppeteer/puppeteer-core-browser.js');
    const { default: Page } = await import('../../page');
    const { DOMElementNode } = await import('../views');
    const domService = await import('../service');

    const p = new Page(1);
    const puppeteerPage = makePuppeteerPage();
    const browser = makeBrowser(puppeteerPage);
    vi.mocked(connect).mockResolvedValue(browser as any);
    await p.attach();

    const staleNode = new DOMElementNode({
      tagName: 'button', xpath: 'html/body/div[3]/button',
      attributes: {}, children: [],
      isVisible: true, isInteractive: true, isTopElement: true, isInViewport: true,
      highlightIndex: 4, parent: null,
    });

    const freshNode = new DOMElementNode({
      tagName: 'button', xpath: 'html/body/div[1]/button',
      attributes: {}, children: [],
      isVisible: true, isInteractive: true, isTopElement: true, isInViewport: true,
      highlightIndex: 4, parent: null,
    });

    // @ts-expect-error private
    p._lastSelectorMap = new Map([[4, staleNode]]);

    const freshButtonHandle = makeElementHandle();

    // Stale locate fails (CSS via frame.$, XPath via evaluateHandle — both return null).
    // Fresh locate: CSS via frame.$ returns null, XPath via evaluateHandle succeeds.
    // frame.$ already returns null by default (makePuppeteerPage default).
    puppeteerPage.evaluateHandle = vi.fn()
      .mockResolvedValueOnce(makeJsHandle(null))           // stale XPath miss
      .mockResolvedValueOnce(makeJsHandle(freshButtonHandle)); // fresh XPath hit

    vi.spyOn(domService, 'getClickableElements').mockResolvedValue({
      selectorMap: new Map([[4, freshNode]]),
      elementTree: { clickableElementsToString: () => '[4]<button>Apply</button>' } as any,
    });

    // @ts-expect-error private
    const result = await p._locateHandle(staleNode);
    expect(result).toBe(freshButtonHandle);
    expect(domService.getClickableElements).toHaveBeenCalled();
  });
});
