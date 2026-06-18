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
import type { Frame } from 'puppeteer-core/lib/esm/puppeteer/api/Frame.js';
import {
  getClickableElements,
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
        // Disconnect best-effort so Chrome releases the debugger attachment,
        // then fall through to reconnect.
        try { await this._browser!.disconnect(); } catch { /* already gone */ }
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
    // ExtensionTransport.close() fire-and-forgets chrome.debugger.detach().
    // A brief settle gives Chrome time to finish detaching before any
    // subsequent attach() call, preventing "Another debugger attached" races.
    await new Promise(r => setTimeout(r, 50));
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
    const domState: DOMState = await getClickableElements(this._tabId, url, true, -1, -1);
    // Cache so clickElement uses the same indices the LLM will see in this snapshot.
    this._lastSelectorMap = domState.selectorMap;
    const elements = domState.elementTree.clickableElementsToString();
    return { url, title, elements };
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

  private async _scrollIntoViewIfNeeded(element: ElementHandle, timeoutMs = 1000): Promise<void> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const isVisible = await element.evaluate((el) => {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return false;
        const style = window.getComputedStyle(el);
        if (style.visibility === 'hidden' || style.display === 'none' || style.opacity === '0') return false;
        const inViewport = rect.top >= 0 && rect.left >= 0 &&
          rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
          rect.right <= (window.innerWidth || document.documentElement.clientWidth);
        if (!inViewport) el.scrollIntoView({ behavior: 'auto', block: 'center', inline: 'center' });
        return inViewport;
      });
      if (isVisible) return;
      await new Promise(r => setTimeout(r, 100));
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

  private async _getElementNode(index: number): Promise<DOMElementNode> {
    let node = this._lastSelectorMap?.get(index) ?? null;
    if (!node) {
      logger.info('[Page] _getElementNode cache miss [%d] — fresh DOM scan', index);
      const tab = await chrome.tabs.get(this._tabId);
      const domState = await getClickableElements(this._tabId, tab.url ?? '', false);
      node = domState.selectorMap.get(index) ?? null;
      logger.info('[Page] fresh scan map size=%d, found=%s', domState.selectorMap.size, node != null);
    } else {
      logger.info('[Page] _getElementNode cache hit [%d] tag=%s', index, node.tagName);
    }
    if (!node) throw new Error(`Element [${index}] not found in DOM state`);
    return node;
  }

  private async _locateHandle(node: DOMElementNode): Promise<ElementHandle> {
    const page = this._requirePage();

    // Walk up the parent chain and collect iframe ancestors (top-to-bottom order).
    const iframes: DOMElementNode[] = [];
    let current: DOMElementNode | null = node.parent;
    while (current) {
      if (current.tagName === 'iframe') iframes.unshift(current);
      current = current.parent;
    }

    // Traverse into each iframe frame in order.
    let frame: PuppeteerPage | Frame = page;
    for (const iframeNode of iframes) {
      const iframeSelector = iframeNode.getEnhancedCssSelector();
      logger.info('[Page] traversing iframe: %s', iframeSelector);
      const iframeEl = await frame.$(iframeSelector);
      if (!iframeEl) {
        throw new Error(`iframe not found: ${iframeSelector}`);
      }
      const childFrame = await iframeEl.contentFrame();
      if (!childFrame) throw new Error(`iframe frame inaccessible: ${iframeSelector}`);
      frame = childFrame as Frame;
    }

    const cssSelector = node.getEnhancedCssSelector();
    logger.info('[Page] _locateHandle css="%s" xpath="%s"', cssSelector, node.xpath);

    let el: ElementHandle | null = null;

    if (cssSelector) {
      el = await frame.$(cssSelector);
    }
    logger.info('[Page] CSS selector match: %s', el != null);

    if (!el && node.xpath) {
      // Only try absolute XPath (starts from html). Relative XPaths (no leading html/)
      // indicate the element is inside a Shadow DOM — document.evaluate() cannot cross
      // shadow boundaries, so skip XPath and fall through to the shadow DOM search.
      const xpath = node.xpath.startsWith('/') ? node.xpath : `/${node.xpath}`;
      const isAbsolute = node.xpath.startsWith('html') || node.xpath.startsWith('/html');
      if (isAbsolute) {
        logger.info('[Page] CSS failed — trying absolute XPath: %s', xpath);
        const xpathHandle = await frame.evaluateHandle((xp: string) => {
          const result = document.evaluate(xp, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
          return result.singleNodeValue;
        }, xpath);
        el = xpathHandle.asElement() as ElementHandle | null;
        if (!el) await xpathHandle.dispose();
        logger.info('[Page] XPath match: %s', el != null);
      } else {
        logger.info('[Page] XPath "%s" is relative — element is in Shadow DOM, skipping XPath', node.xpath);
      }
    }

    // Shadow DOM fallback: buildDomTree.js sets shadowRoot:true on the HOST element
    // and adds its shadow root children directly to the host's children list.
    // Walk up the parent chain to find that host, then query within host.shadowRoot.
    if (!el) {
      let shadowHost: DOMElementNode | null = null;
      let ancestor: DOMElementNode | null = node.parent;
      while (ancestor) {
        if (ancestor.shadowRoot) { shadowHost = ancestor; break; }
        ancestor = ancestor.parent;
      }

      if (shadowHost) {
        const hostCss = shadowHost.getEnhancedCssSelector();
        logger.info('[Page] element in shadow DOM — host css="%s" rel-css="%s" rel-xpath="%s"', hostCss, cssSelector, node.xpath);

        if (hostCss) {
          const relCss = cssSelector;
          const relXpath = node.xpath ?? '';
          const shadowHandle = await frame.evaluateHandle((hostSelector: string, relCssSelector: string, relXpathSelector: string) => {
            const host = document.querySelector(hostSelector);
            if (!host || !host.shadowRoot) return null;
            if (relCssSelector) {
              const e = host.shadowRoot.querySelector(relCssSelector);
              if (e) return e;
            }
            try {
              const r = document.evaluate(relXpathSelector, host.shadowRoot, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
              return r.singleNodeValue || null;
            } catch (_) {
              return null;
            }
          }, hostCss, relCss, relXpath);
          el = shadowHandle.asElement() as ElementHandle | null;
          if (!el) await shadowHandle.dispose();
          logger.info('[Page] shadow DOM host query match: %s', el != null);
        }
      }
    }

    if (!el) {
      logger.info('[Page] _locateHandle FAILED on first attempt — refreshing snapshot and retrying once');
      this._lastSelectorMap = null;
      try {
        await this.snapshot();
      } catch (snapErr) {
        logger.error('[Page] snapshot refresh failed during locate retry', snapErr);
      }
      const freshNode = (this._lastSelectorMap as Map<number, DOMElementNode> | null)?.get(node.highlightIndex ?? -1) ?? null;
      if (freshNode && freshNode !== node) {
        logger.info('[Page] retrying locate with fresh node for index=%d', node.highlightIndex);
        return this._locateHandle(freshNode);
      }
      logger.error('[Page] _locateHandle FAILED after retry. css="%s" xpath="%s"', cssSelector, node.xpath);
      throw new Error(`Element not located (css: ${cssSelector})`);
    }
    return el;
  }

  // Uses Puppeteer's CDP-based click (dispatches real mousedown/mouseup/click events),
  // which is required for SPA frameworks like React that rely on the full mouse event sequence.
  // Falls back to a direct DOM click if the CDP click times out or is rejected.
  async clickElement(index: number): Promise<void> {
    logger.info('[Page] clickElement [%d] — resolving node', index);
    const node = await this._getElementNode(index);
    logger.info('[Page] clickElement [%d] — locating handle', index);
    const el = await this._locateHandle(node);
    logger.info('[Page] clickElement [%d] — scrolling into view', index);
    await this._scrollIntoViewIfNeeded(el);
    logger.info('[Page] clickElement [%d] — dispatching CDP click', index);
    try {
      await Promise.race([
        el.click(),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error('click timeout')), 2000)
        ),
      ]);
      logger.info('[Page] clickElement [%d] — CDP click OK', index);
    } catch (e) {
      logger.info('[Page] clickElement [%d] — CDP click failed (%s), falling back to DOM click', index, (e as Error).message);
      // CDP click timed out or was rejected — dispatch directly on the DOM node.
      await el.evaluate((node: Element) => (node as HTMLElement).click());
      logger.info('[Page] clickElement [%d] — DOM fallback click dispatched', index);
    }
  }

  async typeText(index: number, text: string): Promise<void> {
    const node = await this._getElementNode(index);
    const el = await this._locateHandle(node);
    // Use React's native setter trick so synthetic onChange fires correctly.
    await el.evaluate((node: Element, val: string) => {
      if (!(node instanceof HTMLInputElement) && !(node instanceof HTMLTextAreaElement)) return;
      node.focus();
      node.select();
      const proto = node instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const desc = Object.getOwnPropertyDescriptor(proto, 'value');
      const setter = desc?.set;
      if (setter) setter.call(node, val);
      else node.value = val;
      node.dispatchEvent(new Event('input', { bubbles: true }));
      node.dispatchEvent(new Event('change', { bubbles: true }));
    }, text);
  }

  async selectOption(index: number, text: string): Promise<void> {
    const node = await this._getElementNode(index);
    const el = await this._locateHandle(node);
    await el.evaluate((node: Element, val: string) => {
      if (!(node instanceof HTMLSelectElement)) return;
      const opt = Array.from(node.options).find((o) => o.text === val || o.value === val);
      if (opt) node.value = opt.value;
      node.dispatchEvent(new Event('change', { bubbles: true }));
    }, text);
  }

  async applyFill(index: number, value: string, threadId = '', token = ''): Promise<void> {
    const node = await this._getElementNode(index);
    const el = await this._locateHandle(node);
    await this._scrollIntoViewIfNeeded(el);

    const kind = await el.evaluate((node: Element): string => {
      const tag = node.tagName.toLowerCase();
      const type = ((node as HTMLInputElement).type ?? '').toLowerCase();
      const role = (node.getAttribute('role') ?? '').toLowerCase();
      const hasPopup = node.hasAttribute('aria-haspopup');
      const ce = node.getAttribute('contenteditable');
      if (tag === 'input' && (type === 'checkbox' || type === 'radio')) return 'checkbox';
      if (tag === 'select') return 'select';
      if (tag === 'input' && type === 'file') return 'file';
      if (role === 'combobox' || role === 'listbox' || hasPopup) return 'combobox';
      if (ce === 'true' || ce === '') return 'contenteditable';
      return 'text';
    });

    switch (kind) {
      case 'checkbox': {
        const checked = ['true', '1', 'yes'].includes(value.toLowerCase());
        await el.evaluate((node: Element, val: boolean) => {
          const input = node as HTMLInputElement;
          if (input.checked !== val) {
            input.click();
          }
        }, checked);
        break;
      }
      case 'select':
        await el.evaluate((node: Element, val: string) => {
          const select = node as HTMLSelectElement;
          const opt = Array.from(select.options).find((o) => o.text === val || o.value === val);
          if (opt) {
            select.value = opt.value;
            select.dispatchEvent(new Event('change', { bubbles: true }));
          }
        }, value);
        break;
      case 'combobox': {
        await el.click();
        await new Promise((r) => setTimeout(r, 250));
        const page = this._requirePage();
        const matched = await page.evaluate((val: string) => {
          const candidates = document.querySelectorAll('[role="option"], [data-value], li');
          for (const opt of candidates) {
            if ((opt as HTMLElement).innerText?.trim() === val) {
              (opt as HTMLElement).click();
              return true;
            }
          }
          return false;
        }, value);
        if (!matched) logger.error('[Page] combobox: no option matched value="%s"', value);
        break;
      }
      case 'file':
        try {
          await this._uploadFile(el, value, threadId, token);
        } catch (e) {
          logger.error('[Page] file upload failed — caller should fall back to download link', e);
          throw e;
        }
        break;
      case 'contenteditable':
        await el.evaluate((node: Element, val: string) => {
          const el = node as HTMLElement;
          el.focus();
          el.textContent = val;
          el.dispatchEvent(new Event('input', { bubbles: true }));
          el.dispatchEvent(new Event('change', { bubbles: true }));
        }, value);
        break;
      default: {
        // React-safe native setter
        await el.evaluate((node: Element, val: string) => {
          if (!(node instanceof HTMLInputElement) && !(node instanceof HTMLTextAreaElement)) return;
          node.focus();
          node.select();
          const proto = node instanceof HTMLTextAreaElement
            ? HTMLTextAreaElement.prototype
            : HTMLInputElement.prototype;
          const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
          if (setter) setter.call(node, val);
          else node.value = val;
          node.dispatchEvent(new Event('input', { bubbles: true }));
          node.dispatchEvent(new Event('change', { bubbles: true }));
        }, value);
        break;
      }
    }
  }

  async readFieldValue(index: number): Promise<string> {
    try {
      const node = await this._getElementNode(index);
      const el = await this._locateHandle(node);
      return await el.evaluate((node: Element): string => {
        const tag = node.tagName.toLowerCase();
        const type = ((node as HTMLInputElement).type ?? '').toLowerCase();
        if (tag === 'input' && (type === 'checkbox' || type === 'radio')) {
          return (node as HTMLInputElement).checked ? 'true' : 'false';
        }
        if ('value' in node) return (node as HTMLInputElement).value ?? '';
        return (node as HTMLElement).textContent?.trim() ?? '';
      });
    } catch {
      return '';
    }
  }

  async sendKeys(keys: string): Promise<void> {
    const page = this._requirePage();
    await page.keyboard.press(keys as Parameters<typeof page.keyboard.press>[0]);
  }

  async navigate(url: string): Promise<void> {
    // Detach before navigating — cross-origin navigations corrupt the live CDP
    // session if Puppeteer is still attached when chrome.tabs.update fires.
    await this.detach();
    await chrome.tabs.update(this._tabId, { url });
  }

  async goBack(): Promise<void> {
    const page = this._requirePage();
    await page.goBack();
  }

  async wait(seconds: number): Promise<void> {
    await new Promise(resolve => setTimeout(resolve, seconds * 1000));
  }

  private async _uploadFile(el: ElementHandle, value: string, threadId: string, token: string): Promise<void> {
    const fileType = value === '__CV__' ? 'cv' : 'cover_letter';
    const filename = value === '__CV__' ? 'tailored_cv.docx' : 'cover_letter.docx';
    const url = `http://localhost:8000/tailorer/files/${threadId}/${fileType}?token=${encodeURIComponent(token)}`;

    // Hoisted so it's in scope for cleanup after the Promise resolves.
    let trackedId: number | null = null;

    // Register the onChanged listener before starting the download to avoid
    // a race where a fast download completes before the listener is installed.
    const absolutePath = await new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Download timeout')), 30_000);

      const listener = (delta: chrome.downloads.DownloadDelta) => {
        if (trackedId === null || delta.id !== trackedId) return;
        if (delta.state?.current === 'complete') {
          clearTimeout(timer);
          chrome.downloads.onChanged.removeListener(listener);
          chrome.downloads.search({ id: trackedId }, (items) => {
            const path = items[0]?.filename;
            if (path) resolve(path);
            else reject(new Error('Download path not found'));
          });
        } else if (delta.state?.current === 'interrupted') {
          clearTimeout(timer);
          chrome.downloads.onChanged.removeListener(listener);
          reject(new Error('Download interrupted'));
        }
      };
      chrome.downloads.onChanged.addListener(listener);

      chrome.downloads.download(
        { url, filename: `tailorer/${filename}`, conflictAction: 'overwrite' },
        (id) => {
          if (chrome.runtime.lastError) {
            clearTimeout(timer);
            chrome.downloads.onChanged.removeListener(listener);
            reject(new Error(String(chrome.runtime.lastError.message)));
          } else {
            trackedId = id!;
          }
        },
      );
    });

    await el.uploadFile(absolutePath);

    if (trackedId !== null) {
      chrome.downloads.removeFile(trackedId, () => {});
      chrome.downloads.erase({ id: trackedId }, () => {});
    }
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
