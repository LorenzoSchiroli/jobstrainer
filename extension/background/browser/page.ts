import {
  connect,
  ExtensionTransport,
  type HTTPRequest,
  type HTTPResponse,
  type ProtocolType,
} from 'puppeteer-core/lib/esm/puppeteer/puppeteer-core-browser.js';
import type { Browser } from 'puppeteer-core/lib/esm/puppeteer/api/Browser.js';
import type { Page as PuppeteerPage } from 'puppeteer-core/lib/esm/puppeteer/api/Page.js';
import type { ElementHandle } from 'puppeteer-core/lib/esm/puppeteer/api/ElementHandle.js';
import {
  getClickableElements,
  getScrollInfo,
  injectBuildDomTreeScripts,
} from './dom/service';
import { type DOMState, DOMElementNode } from './dom/views';

const logger = { info: console.log, error: console.error };

// Page-settle tuning (seconds), ported from nanobrowser defaults.
const WAIT_FOR_NETWORK_IDLE = 0.5; // quiet window before considering the network idle
const MINIMUM_WAIT_PAGE_LOAD = 0.25; // minimum settle floor after any action
const MAXIMUM_WAIT_PAGE_LOAD = 5.0; // hard cap so we never block forever

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
  private _lastSelectorMap: Map<number, DOMElementNode> | null = null;

  constructor(tabId: number) {
    this._tabId = tabId;
  }

  get tabId(): number {
    return this._tabId;
  }

  async attach(): Promise<void> {
    // Staleness probe: if we think we're attached, verify the connection is live.
    if (this._page) {
      try {
        await this._page.evaluate('1');
        return; // Connection healthy — nothing to do.
      } catch {
        // CDP session went stale (e.g. cross-origin navigation).
        // Fall through to reconnect after clearing stale handles.
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

  async snapshot(): Promise<PageSnapshot> {
    // Wait for the page to settle before reading the URL/DOM. Without this, a
    // snapshot taken right after a click (especially SPA route changes that do
    // not trigger a full navigation) captures the stale URL and stale element
    // indices — which the backend then misreads as "no progress / stuck".
    await this.waitForPageAndFramesLoad();
    const tab = await chrome.tabs.get(this._tabId);
    const url = tab.url ?? '';
    const title = tab.title ?? '';
    const domState: DOMState = await getClickableElements(this._tabId, url, true);
    // Cache so clickElement uses the same indices the LLM will see in this snapshot.
    this._lastSelectorMap = domState.selectorMap;
    const elements = domState.elementTree.clickableElementsToString();
    const [scroll_y, viewport_height, scroll_height] = await getScrollInfo(this._tabId);
    return { url, title, elements, scroll_y, viewport_height, scroll_height };
  }

  private _requirePage(): PuppeteerPage {
    if (!this._page) throw new Error('Page not attached — call attach() first');
    return this._page;
  }

  // Waits until network requests have been quiet for WAIT_FOR_NETWORK_IDLE seconds,
  // or MAXIMUM_WAIT_PAGE_LOAD elapses. Ported (simplified) from nanobrowser's
  // _waitForStableNetwork — ignores analytics/streaming/data URLs so background
  // chatter never blocks the snapshot.
  private async _waitForStableNetwork(): Promise<void> {
    const page = this._page;
    if (!page) return;

    const RELEVANT_RESOURCE_TYPES = new Set(['document', 'stylesheet', 'image', 'font', 'script', 'iframe']);
    const IGNORED_URL_PATTERNS = [
      'analytics', 'tracking', 'telemetry', 'beacon', 'metrics',
      'doubleclick', 'adsystem', 'adserver', 'advertising',
      'facebook.com/plugins', 'platform.twitter', 'linkedin.com/embed',
      'livechat', 'zendesk', 'intercom', 'crisp.chat', 'hotjar',
      'onesignal', 'pushwoosh', 'heartbeat', 'ping', 'alive',
    ];

    const pendingRequests = new Set<HTTPRequest>();
    let lastActivity = Date.now();

    const onRequest = (request: HTTPRequest) => {
      const resourceType = request.resourceType();
      if (!RELEVANT_RESOURCE_TYPES.has(resourceType)) return;
      const url = request.url().toLowerCase();
      if (url.startsWith('data:') || url.startsWith('blob:')) return;
      if (IGNORED_URL_PATTERNS.some(p => url.includes(p))) return;
      pendingRequests.add(request);
      lastActivity = Date.now();
    };
    const onResponse = (response: HTTPResponse) => {
      const request = response.request();
      if (!pendingRequests.has(request)) return;
      pendingRequests.delete(request);
      lastActivity = Date.now();
    };

    page.on('request', onRequest);
    page.on('response', onResponse);
    try {
      const startTime = Date.now();
      while (true) {
        await new Promise(r => setTimeout(r, 100));
        const now = Date.now();
        const idleFor = (now - lastActivity) / 1000;
        if (pendingRequests.size === 0 && idleFor >= WAIT_FOR_NETWORK_IDLE) break;
        if ((now - startTime) / 1000 > MAXIMUM_WAIT_PAGE_LOAD) break;
      }
    } finally {
      page.off('request', onRequest);
      page.off('response', onResponse);
    }
  }

  // Settle the page after a navigation/action: wait for the network to go quiet,
  // then enforce a minimum wait floor. Failures are non-fatal — we still snapshot.
  async waitForPageAndFramesLoad(): Promise<void> {
    const startTime = Date.now();
    try {
      await this._waitForStableNetwork();
    } catch (e) {
      logger.error('[Page] waitForStableNetwork failed, continuing', e);
    }
    const elapsed = (Date.now() - startTime) / 1000;
    const remaining = Math.max(MINIMUM_WAIT_PAGE_LOAD - elapsed, 0);
    if (remaining > 0) await new Promise(r => setTimeout(r, remaining * 1000));
  }

  // Locate a DOM element by its highlight index using the cached snapshot's selectorMap.
  // Falls back to a fresh DOM scan if the cache is missing, then tries XPath if CSS fails.
  private async _locateElement(index: number): Promise<ElementHandle> {
    const page = this._requirePage();

    // Prefer the cached map so [index] matches what the LLM saw in the snapshot.
    let elementNode = this._lastSelectorMap?.get(index) ?? null;
    if (!elementNode) {
      const tab = await chrome.tabs.get(this._tabId);
      const domState = await getClickableElements(this._tabId, tab.url ?? '', false);
      elementNode = domState.selectorMap.get(index) ?? null;
    }
    if (!elementNode) throw new Error(`Element [${index}] not found in DOM state`);

    const cssSelector = elementNode.getEnhancedCssSelector();
    let el: ElementHandle | null = await page.$(cssSelector);

    // XPath fallback — more stable than CSS on dynamic React pages.
    if (!el && elementNode.xpath) {
      const xpath = elementNode.xpath.startsWith('/') ? elementNode.xpath : `/${elementNode.xpath}`;
      el = await page.$(`::-p-xpath(${xpath})`);
    }

    if (!el) throw new Error(`Element [${index}] could not be located (css: ${cssSelector})`);
    return el;
  }

  // Uses Puppeteer's CDP-based click (dispatches real mousedown/mouseup/click events),
  // which is required for SPA frameworks like React that rely on the full mouse event sequence.
  async clickElement(index: number): Promise<void> {
    const el = await this._locateElement(index);
    await el.click();
  }

  async typeText(index: number, text: string): Promise<void> {
    const el = await this._locateElement(index);
    // Use React's native setter trick so synthetic onChange fires correctly.
    await el.evaluate((node: Element, val: string) => {
      if (!(node instanceof HTMLInputElement) && !(node instanceof HTMLTextAreaElement)) return;
      node.focus();
      node.select();
      const proto = node instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
      if (setter) setter.call(node, val);
      else (node as HTMLInputElement).value = val;
      node.dispatchEvent(new Event('input', { bubbles: true }));
      node.dispatchEvent(new Event('change', { bubbles: true }));
    }, text);
  }

  async selectOption(index: number, text: string): Promise<void> {
    const el = await this._locateElement(index);
    await el.evaluate((node: Element, val: string) => {
      if (!(node instanceof HTMLSelectElement)) return;
      const opt = Array.from(node.options).find(o => o.text === val || o.value === val);
      if (opt) node.value = opt.value;
      node.dispatchEvent(new Event('change', { bubbles: true }));
    }, text);
  }

  async scrollDown(): Promise<void> {
    await chrome.scripting.executeScript({
      target: { tabId: this._tabId },
      func: () => window.scrollBy(0, window.innerHeight * 0.9),
    });
  }

  async scrollUp(): Promise<void> {
    await chrome.scripting.executeScript({
      target: { tabId: this._tabId },
      func: () => window.scrollBy(0, -window.innerHeight * 0.9),
    });
  }

  async scrollToTop(): Promise<void> {
    await chrome.scripting.executeScript({
      target: { tabId: this._tabId },
      func: () => window.scrollTo(0, 0),
    });
  }

  async scrollToBottom(): Promise<void> {
    await chrome.scripting.executeScript({
      target: { tabId: this._tabId },
      func: () => window.scrollTo(0, document.body.scrollHeight),
    });
  }

  async sendKeys(keys: string): Promise<void> {
    const page = this._requirePage();
    await page.keyboard.press(keys as Parameters<typeof page.keyboard.press>[0]);
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

  private async _addAntiDetectionScripts(): Promise<void> {
    if (!this._page) return;
    await this._page.evaluateOnNewDocument(`
      Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
      window.chrome = { runtime: {} };
      const _origAttachShadow = Element.prototype.attachShadow;
      Element.prototype.attachShadow = function(options) {
        return _origAttachShadow.call(this, { ...options, mode: 'open' });
      };
    `);
  }
}
