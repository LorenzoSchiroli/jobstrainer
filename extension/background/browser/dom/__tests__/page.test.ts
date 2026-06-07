import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Stubs ──────────────────────────────────────────────────────────────────

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

// ── Module mocks (must be before any dynamic import of Page) ──────────────

vi.mock('puppeteer-core/lib/esm/puppeteer/puppeteer-core-browser.js', () => ({
  connect: vi.fn(),
  ExtensionTransport: { connectTab: vi.fn().mockResolvedValue({}) },
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
