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
} from './dom/service';
import type { DOMState } from './dom/views';

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

  private async _getElementSelector(index: number): Promise<string> {
    const tab = await chrome.tabs.get(this._tabId);
    const domState = await getClickableElements(this._tabId, tab.url ?? '', false);
    const el = domState.selectorMap.get(index);
    if (!el) throw new Error(`Element [${index}] not found in DOM state`);
    return el.getEnhancedCssSelector();
  }

  async clickElement(index: number): Promise<void> {
    const page = this._requirePage();
    const selector = await this._getElementSelector(index);
    await page.click(selector);
  }

  async typeText(index: number, text: string): Promise<void> {
    const page = this._requirePage();
    const selector = await this._getElementSelector(index);
    await page.click(selector, { clickCount: 3 });
    await page.type(selector, text, { delay: 20 });
  }

  async selectOption(index: number, text: string): Promise<void> {
    const page = this._requirePage();
    const selector = await this._getElementSelector(index);
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
