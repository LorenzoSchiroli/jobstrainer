# Tailorer Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 6 diagnosed bugs in the tailorer extension+backend that together cause CDP debugger leaks, silent fill failures, invisible action logs, and suboptimal navigation behaviour.

**Architecture:** All fixes are surgical — no new files, no structural changes. Bugs 1 and 2 touch `extension/background/browser/page.ts`; Bug 3 touches `backend/backend/tailorer/router.py` (protocol fix on the sender side); Bug 4 touches `backend/backend/tailorer/llm.py` (prompt-only change); Bug 5 touches `extension/background/browser/page.ts` again; Bug 6 touches `extension/background/agent/messageHandler.ts`. Each bug has its own task with isolated tests.

**Tech Stack:** TypeScript (Vitest for extension tests), Python 3.12 (pytest + pytest-asyncio for backend tests), Puppeteer-core (MV3 CDP transport), FastAPI WebSocket, LangGraph interrupts.

---

## File map

| File | Bugs addressed |
|------|----------------|
| `extension/background/browser/page.ts` | Bug 1 (CDP leak), Bug 2 (settle delay), Bug 5 (stale snapshot retry) |
| `extension/background/agent/messageHandler.ts` | Bug 6 (action logs) |
| `backend/backend/tailorer/router.py` | Bug 3 (fill protocol) |
| `backend/backend/tailorer/llm.py` | Bug 4 (nav prompt) |
| `extension/background/browser/dom/__tests__/page.test.ts` | Bug 1, Bug 2, Bug 5 |
| `backend/tests/tailorer/test_ws.py` | Bug 3 |

---

## Task 1 — Bug 1: CDP debugger leak on stale probe

**Root cause:** `page.ts` lines 55–60 — the staleness-probe catch block nulls `_browser`/`_page` but never calls `this._browser.disconnect()`. The Chrome debugger attachment leaks, causing "Another debugger is already attached to the tab" on the next `attach()`.

**Files:**
- Modify: `extension/background/browser/page.ts:55-61`
- Test: `extension/background/browser/dom/__tests__/page.test.ts`

- [ ] **Step 1: Write the failing test**

  Open `extension/background/browser/dom/__tests__/page.test.ts`. After the existing `describe('Page.attach() staleness probe', ...)` block, add a new describe block:

  ```typescript
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

      // staleBrowser.disconnect must have been called (CDP leak fix)
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
  ```

- [ ] **Step 2: Run test to verify it fails**

  ```bash
  cd /Users/loryschi/projects/jobstrainer/extension
  npm test -- --reporter=verbose 2>&1 | grep -A 3 "stale probe disconnects"
  ```

  Expected: FAIL — `staleBrowser.disconnect` call count is 0 (disconnect is never called in the catch block today).

- [ ] **Step 3: Apply the fix**

  In `extension/background/browser/page.ts`, replace lines 55–61 (the staleness-probe catch block):

  **Before:**
  ```typescript
      } catch {
        // CDP session went stale (e.g. cross-origin navigation).
        // Fall through to reconnect after clearing stale handles.
        this._browser = null;
        this._page = null;
        this._lastSelectorMap = null;
      }
  ```

  **After:**
  ```typescript
      } catch {
        // CDP session went stale (e.g. cross-origin navigation).
        // Disconnect best-effort so Chrome releases the debugger attachment,
        // then fall through to reconnect.
        try { await this._browser!.disconnect(); } catch { /* already gone */ }
        this._browser = null;
        this._page = null;
        this._lastSelectorMap = null;
      }
  ```

- [ ] **Step 4: Run tests to verify they pass**

  ```bash
  cd /Users/loryschi/projects/jobstrainer/extension
  npm test -- --reporter=verbose 2>&1 | grep -E "(PASS|FAIL|stale probe)"
  ```

  Expected: all tests in `page.test.ts` pass, including the two new ones.

- [ ] **Step 5: Commit**

  ```bash
  cd /Users/loryschi/projects/jobstrainer/extension
  git add background/browser/page.ts background/browser/dom/__tests__/page.test.ts
  git commit -m "fix(extension): disconnect CDP browser on stale probe to prevent debugger leak"
  ```

---

## Task 2 — Bug 2: Race condition on detach/reattach

**Root cause:** `ExtensionTransport.close()` fire-and-forgets `chrome.debugger.detach({tabId})`. So `this._browser.disconnect()` returns before Chrome finishes the detach. Calling `attach()` immediately after racing produces "Another debugger already attached". Additionally, when the tab is closed, the detached promise rejects with an unhandled rejection.

**Files:**
- Modify: `extension/background/browser/page.ts` — `detach()` method
- Modify: `extension/background/session/manager.ts` — `ws.onclose` path (already catches; confirm the `detach().catch` is present)
- Test: `extension/background/browser/dom/__tests__/page.test.ts`

- [ ] **Step 1: Write the failing test**

  Add the following inside `extension/background/browser/dom/__tests__/page.test.ts`, after the existing `describe('Page.detach() safety', ...)` block:

  ```typescript
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

      // Advance time by 49 ms — should NOT be resolved yet
      await vi.advanceTimersByTimeAsync(49);
      expect(resolved).toBe(false);

      // Advance past the 50 ms threshold
      await vi.advanceTimersByTimeAsync(2);
      await detachPromise;
      expect(resolved).toBe(true);
    });
  });
  ```

- [ ] **Step 2: Run test to verify it fails**

  ```bash
  cd /Users/loryschi/projects/jobstrainer/extension
  npm test -- --reporter=verbose 2>&1 | grep -A 3 "settle delay"
  ```

  Expected: FAIL — `resolved` is `true` after only 49 ms (no settle delay today).

- [ ] **Step 3: Apply the fix**

  In `extension/background/browser/page.ts`, replace the `detach()` method (lines 76–87):

  **Before:**
  ```typescript
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

  **After:**
  ```typescript
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
  ```

- [ ] **Step 4: Verify manager.ts already handles detach rejections gracefully**

  Read `extension/background/session/manager.ts` lines 87–89 and 96–101. Both `removeSession` and `stop` already call `s.page.detach().catch(() => {})`, so unhandled rejections from a closed tab are already swallowed. No change needed.

- [ ] **Step 5: Run tests to verify they pass**

  ```bash
  cd /Users/loryschi/projects/jobstrainer/extension
  npm test -- --reporter=verbose 2>&1 | grep -E "(PASS|FAIL|settle delay)"
  ```

  Expected: all tests pass, including the new settle-delay test.

- [ ] **Step 6: Commit**

  ```bash
  cd /Users/loryschi/projects/jobstrainer/extension
  git add background/browser/page.ts background/browser/dom/__tests__/page.test.ts
  git commit -m "fix(extension): add 50 ms settle after detach() to prevent reattach race"
  ```

---

## Task 3 — Bug 3: Fill phase protocol mismatch

**Root cause:** `router.py:_handle_fill_and_confirm` sends each regular fill command as a bare object with no `type` key (line 108: `await ws.send_json(cmd)`). The extension's `handleAgentMessage` dispatches on `msg.type` — finding no `type` on these raw objects, every fill command is silently dropped. The `fill_and_confirm` handler in `messageHandler.ts:59-96` is dead code from the extension's perspective under this bug.

**Chosen fix:** Keep the protocol clean by removing the bare-send of individual commands from `router.py` and instead batch them into a single `fill_and_confirm` message that the extension already handles at `messageHandler.ts:59-96`. The `show_confirm` message (with `type: "show_confirm"`) is already wired correctly in the extension (lines 98–107) and will continue to arrive after the fill is done.

This means `_handle_fill_and_confirm` in `router.py` should:
1. Send one `{"type": "fill_and_confirm", "commands": regular_cmds, "confirm_commands": confirm_cmds, "summary": ...}` message.
2. Wait for the user response (user_approved or user_correction).
3. After `user_approved`, send file commands as individual `{"type": "show_confirm", ...}`-style messages is not needed — the extension's `fill_and_confirm` handler in `messageHandler.ts:75-95` already builds file links and pops the confirm card itself.

So the minimal fix: replace the per-command `await ws.send_json(cmd)` loop in `router.py` with a single batched message, and remove the subsequent `show_confirm` send (the extension handles it internally).

**Files:**
- Modify: `backend/backend/tailorer/router.py:92-136` (`_handle_fill_and_confirm`)
- Test: `backend/tests/tailorer/test_ws.py`

- [ ] **Step 1: Read the current test to understand what it asserts**

  Open `backend/tests/tailorer/test_ws.py` lines 44–70. The existing test `test_handle_interrupt_fill_and_confirm_sends_index_commands` currently asserts that `input_text` is sent as a bare object AND that `show_confirm` is sent. Under the new protocol both behaviours change — we will update this test.

- [ ] **Step 2: Write a new test for the correct protocol**

  Replace the existing `test_handle_interrupt_fill_and_confirm_sends_index_commands` test in `backend/tests/tailorer/test_ws.py` with:

  ```python
  @pytest.mark.asyncio
  async def test_handle_interrupt_fill_and_confirm_sends_batched_message():
      """fill_and_confirm must send a single {type: fill_and_confirm, commands: [...]} message
      (not individual bare objects) so the extension dispatcher can route it."""
      from backend.tailorer.router import _handle_interrupt

      ws = AsyncMock()
      ws.receive_json = AsyncMock(return_value={"type": "user_approved"})

      interrupt_val = {
          "type": "fill_and_confirm",
          "commands": [
              {"index": 2, "value": "John", "action": "input_text", "uncertain": False},
              {"index": 3, "value": "Doe", "action": "input_text", "uncertain": False},
              {"index": 7, "value": "__CV__", "action": "file_upload"},
          ],
          "summary": "Filling page 1",
      }

      result = await _handle_interrupt(ws, interrupt_val, thread_id="t1", token="tok")

      calls = [c[0][0] for c in ws.send_json.call_args_list]

      # There must be exactly one fill_and_confirm message
      fill_calls = [c for c in calls if c.get("type") == "fill_and_confirm"]
      assert len(fill_calls) == 1, f"Expected 1 fill_and_confirm message, got {len(fill_calls)}"

      fill_msg = fill_calls[0]
      # commands list must contain the two regular fill commands (not the file_upload)
      regular = [c for c in fill_msg["commands"] if c.get("action") != "file_upload"
                 and c.get("value") not in ("__CV__", "__COVER_LETTER__")]
      assert len(regular) == 2
      assert regular[0]["index"] == 2
      assert regular[1]["index"] == 3

      # No bare {action: "input_text"} objects must be sent as top-level messages
      bare_fills = [c for c in calls if c.get("action") in ("input_text", "select_option")]
      assert bare_fills == [], f"Unexpected bare fill commands sent: {bare_fills}"

      assert result == {"type": "user_approved"}
  ```

- [ ] **Step 3: Run test to verify it fails**

  ```bash
  cd /Users/loryschi/projects/jobstrainer/backend
  uv run pytest tests/tailorer/test_ws.py::test_handle_interrupt_fill_and_confirm_sends_batched_message -v
  ```

  Expected: FAIL — the current code sends bare objects with no `type`, not a single batched message.

- [ ] **Step 4: Apply the fix in router.py**

  In `backend/backend/tailorer/router.py`, replace `_handle_fill_and_confirm` (lines 92–136) with:

  ```python
  async def _handle_fill_and_confirm(
      ws: WebSocket, val: dict, thread_id: str = "", token: str = "", **_kw: Any
  ) -> dict:
      all_cmds = val.get("commands", [])
      confirm_cmds = val.get("confirm_commands", all_cmds)

      # Send a single batched message so the extension dispatcher can route it
      # via msg.type. Individual bare objects (no type key) are silently dropped.
      await ws.send_json({
          "type": "fill_and_confirm",
          "commands": all_cmds,
          "confirm_commands": confirm_cmds,
          "summary": val.get("summary", ""),
          "thread_id": thread_id,
          "token": token,
      })

      return await ws.receive_json()
  ```

  Note: the extension's `fill_and_confirm` handler (`messageHandler.ts:59-96`) already:
  - Filters out file_upload commands and skips them during fill.
  - Builds `file_links` from `__CV__` / `__COVER_LETTER__` sentinel values.
  - Posts a `confirm` log entry with `summary`, `uncertain_fields`, and `file_links`.
  - Uses `session.thread_id` and `session.token` (set earlier) — so passing them in the message is belt-and-suspenders (the extension has them already).

- [ ] **Step 5: Run all tailorer ws tests**

  ```bash
  cd /Users/loryschi/projects/jobstrainer/backend
  uv run pytest tests/tailorer/test_ws.py -v
  ```

  Expected: all tests pass.

- [ ] **Step 6: Commit**

  ```bash
  cd /Users/loryschi/projects/jobstrainer/backend
  git add backend/tailorer/router.py tests/tailorer/test_ws.py
  git commit -m "fix(backend): send fill_and_confirm as batched typed message so extension dispatcher routes it"
  ```

---

## Task 4 — Bug 4: Agent paginates instead of searching

**Root cause:** `llm.py` `NAV_SYSTEM_PROMPT` line 47 says "Use `scroll_to_bottom` or `next_page` if the page might have more links below" — actively biasing toward pagination. There is no rule telling the agent to use a search input first. Dynamic job-listing pages (Greenhouse, Workday, Lever) all have a keyword search field that, when used, returns 0→N relevant results without needing to page through hundreds of entries.

**Files:**
- Modify: `backend/backend/tailorer/llm.py:43-48` (the `# Rules` section of `NAV_SYSTEM_PROMPT`)
- Test: `backend/tests/tailorer/test_nodes.py` (add a prompt-content test)

- [ ] **Step 1: Write the failing test**

  Open `backend/tests/tailorer/test_nodes.py`. After the existing tests, add:

  ```python
  def test_nav_system_prompt_prioritises_search_over_scroll():
      """NAV_SYSTEM_PROMPT must instruct the agent to search before scrolling/paginating."""
      from backend.tailorer.llm import NAV_SYSTEM_PROMPT
      lower = NAV_SYSTEM_PROMPT.lower()
      # Must mention searching before paginating
      assert "search" in lower, "Prompt must mention search input"
      search_pos = lower.index("search")
      # scroll/next_page rule must appear AFTER the search rule
      for kw in ("scroll_to_bottom", "next_page"):
          kw_pos = lower.find(kw)
          assert kw_pos == -1 or kw_pos > search_pos, (
              f"'{kw}' rule appears before search rule — agent will paginate instead of search"
          )
  ```

- [ ] **Step 2: Run test to verify it fails**

  ```bash
  cd /Users/loryschi/projects/jobstrainer/backend
  uv run pytest tests/tailorer/test_nodes.py::test_nav_system_prompt_prioritises_search_over_scroll -v
  ```

  Expected: FAIL — "search" is not mentioned in the prompt (or `scroll_to_bottom` appears before it).

- [ ] **Step 3: Apply the fix in llm.py**

  In `backend/backend/tailorer/llm.py`, replace the `# Rules` section of `NAV_SYSTEM_PROMPT` (lines 42–50):

  **Before:**
  ```python
      "# Rules\n"
      "- Return at_form if you see application form fields: name, email, phone, file upload for resume/CV\n"
      "- A file input (type=file) for resume is a DEFINITIVE signal — return at_form immediately\n"
      "- Do NOT return at_form for login-only pages\n"
      "- Avoid URLs/actions already in navigation history\n"
      "- Use scroll_to_bottom or next_page if the page might have more links below\n"
      "- Return stuck only as last resort\n"
      "- Return up to 2 actions maximum\n"
      "- Return ONLY valid JSON, no prose, no markdown"
  ```

  **After:**
  ```python
      "# Rules\n"
      "- Return at_form if you see application form fields: name, email, phone, file upload for resume/CV\n"
      "- A file input (type=file) for resume is a DEFINITIVE signal — return at_form immediately\n"
      "- Do NOT return at_form for login-only pages\n"
      "- Avoid URLs/actions already in navigation history\n"
      "- On a careers/job-listings page: FIRST look for a search or keyword input field, "
      "type the job title into it and press Enter — do this BEFORE scrolling or paginating\n"
      "- Use scroll_to_bottom or next_page only if no search input is present and the page might have more links below\n"
      "- Return stuck only as last resort\n"
      "- Return up to 2 actions maximum\n"
      "- Return ONLY valid JSON, no prose, no markdown"
  ```

- [ ] **Step 4: Run test to verify it passes**

  ```bash
  cd /Users/loryschi/projects/jobstrainer/backend
  uv run pytest tests/tailorer/test_nodes.py::test_nav_system_prompt_prioritises_search_over_scroll -v
  ```

  Expected: PASS.

- [ ] **Step 5: Run full tailorer test suite**

  ```bash
  cd /Users/loryschi/projects/jobstrainer/backend
  uv run pytest tests/tailorer/ -v
  ```

  Expected: all tests pass.

- [ ] **Step 6: Commit**

  ```bash
  cd /Users/loryschi/projects/jobstrainer/backend
  git add backend/tailorer/llm.py tests/tailorer/test_nodes.py
  git commit -m "fix(backend): prioritise search input over scrolling in NAV_SYSTEM_PROMPT"
  ```

---

## Task 5 — Bug 5: Stale snapshot causes element-not-found

**Root cause:** CSS/XPath selectors in `_locateHandle` are structural paths frozen at snapshot time. During the seconds of LLM latency, cookie banners, React hydration re-renders, or lazy-loaded components shift `div:nth-of-type(N)` indices. When locate fails, the caller in `manager.ts:69-77` sends the backend a fake empty snapshot (`elements: ''`). The LLM sees a blank page, increments `no_progress_count`, and eventually declares stuck.

**Fix:** In `_locateHandle`, on a final locate failure: invalidate `_lastSelectorMap`, call `snapshot()` to get a fresh DOM scan, re-look up the same index in the new map, and retry locate once. If still not found, throw as before.

**Important:** `snapshot()` calls `waitForPageAndFramesLoad()` which may take up to 5 seconds. So this code path only runs on a miss — it does not add latency on happy-path hits.

**Files:**
- Modify: `extension/background/browser/page.ts` — `_locateHandle` method (lines 212–310) and `_getElementNode` (lines 197–210)
- Test: `extension/background/browser/dom/__tests__/page.test.ts`

- [ ] **Step 1: Write the failing test**

  Add to `extension/background/browser/dom/__tests__/page.test.ts`:

  ```typescript
  describe('Page._locateHandle — stale snapshot retry', () => {
    beforeEach(() => { vi.clearAllMocks(); });

    it('invalidates cache and retries locate on first miss', async () => {
      const { connect } = await import('puppeteer-core/lib/esm/puppeteer/puppeteer-core-browser.js');
      const { default: Page } = await import('../../page');
      const { DOMElementNode } = await import('../views');
      const domService = await import('../../dom/service');

      const p = new Page(1);
      const puppeteerPage = makePuppeteerPage();
      const browser = makeBrowser(puppeteerPage);
      vi.mocked(connect).mockResolvedValue(browser as any);
      await p.attach();

      // Stale node: locateHandle will fail on it
      const staleNode = new DOMElementNode({
        tagName: 'button', xpath: '/html/body/div[3]/button',
        attributes: {}, children: [],
        isVisible: true, isInteractive: true, isTopElement: true, isInViewport: true,
        highlightIndex: 4, parent: null,
      });

      // Fresh node for index 4, with an xpath that succeeds
      const freshNode = new DOMElementNode({
        tagName: 'button', xpath: '/html/body/div[1]/button',
        attributes: {}, children: [],
        isVisible: true, isInteractive: true, isTopElement: true, isInViewport: true,
        highlightIndex: 4, parent: null,
      });

      // Load stale map
      // @ts-expect-error private field access for test
      p._lastSelectorMap = new Map([[4, staleNode]]);

      const freshButtonHandle = makeElementHandle();

      // First CSS/XPath locate attempt (stale) → fails (null)
      // Second CSS/XPath locate attempt (fresh node) → succeeds
      puppeteerPage.evaluateHandle = vi.fn()
        .mockResolvedValueOnce(makeJsHandle(null))   // CSS miss (stale)
        .mockResolvedValueOnce(makeJsHandle(null))   // XPath miss (stale)
        .mockResolvedValueOnce(makeJsHandle(null))   // CSS miss (fresh, fallback 1)
        .mockResolvedValueOnce(makeJsHandle(freshButtonHandle));  // XPath hit (fresh)

      // Mock getClickableElements (used by snapshot() → getClickableElements)
      vi.spyOn(domService, 'getClickableElements').mockResolvedValue({
        selectorMap: new Map([[4, freshNode]]),
        elementTree: { clickableElementsToString: () => '[4]<button>Apply</button>' } as any,
      });
      // Mock getScrollInfo
      vi.spyOn(domService, 'getScrollInfo').mockResolvedValue([0, 800, 3000]);

      // @ts-expect-error private method access for test
      const result = await p._locateHandle(staleNode);
      expect(result).toBe(freshButtonHandle);

      // Cache must have been invalidated (re-scan happened)
      expect(domService.getClickableElements).toHaveBeenCalled();
    });
  });
  ```

- [ ] **Step 2: Run test to verify it fails**

  ```bash
  cd /Users/loryschi/projects/jobstrainer/extension
  npm test -- --reporter=verbose 2>&1 | grep -A 5 "stale snapshot retry"
  ```

  Expected: FAIL — current `_locateHandle` just throws without retrying.

- [ ] **Step 3: Apply the fix in page.ts**

  In `extension/background/browser/page.ts`, modify `_locateHandle` to add a retry on locate failure. Replace the final `if (!el)` throw block (lines 306–310) with:

  ```typescript
    if (!el) {
      logger.info('[Page] _locateHandle FAILED on first attempt — refreshing snapshot and retrying once');
      // Invalidate stale selector map and take a fresh DOM scan via snapshot().
      // snapshot() calls waitForPageAndFramesLoad() so the new map reflects the
      // current DOM after all mutations.
      this._lastSelectorMap = null;
      try {
        await this.snapshot();
      } catch (snapErr) {
        logger.error('[Page] snapshot refresh failed during locate retry', snapErr);
      }
      // Re-look up the node by index in the fresh map.
      const freshNode = this._lastSelectorMap?.get(node.highlightIndex ?? -1) ?? null;
      if (freshNode && freshNode !== node) {
        logger.info('[Page] retrying locate with fresh node for index=%d', node.highlightIndex);
        // Recurse once — fresh node will not hit this retry branch again because it's different.
        return this._locateHandle(freshNode);
      }
      logger.error('[Page] _locateHandle FAILED after retry. css="%s" xpath="%s"', cssSelector, node.xpath);
      throw new Error(`Element not located (css: ${cssSelector})`);
    }
    return el;
  ```

  Also remove the `return el;` that was the original last line (it's now inside the successful branch). Verify the full method ends correctly by reading it after your edit.

- [ ] **Step 4: Run all page tests**

  ```bash
  cd /Users/loryschi/projects/jobstrainer/extension
  npm test -- --reporter=verbose
  ```

  Expected: all tests pass, including the new stale-snapshot-retry test.

- [ ] **Step 5: Commit**

  ```bash
  cd /Users/loryschi/projects/jobstrainer/extension
  git add background/browser/page.ts background/browser/dom/__tests__/page.test.ts
  git commit -m "fix(extension): retry _locateHandle once with fresh DOM scan on element-not-found"
  ```

---

## Task 6 — Bug 6: Action logs not shown in side panel

**Root cause:** The `execute_actions` handler in `messageHandler.ts:44-57` calls `executeAction` in a loop but never calls `sessionManager.appendLog`. The side panel shows only "Session started" and then goes silent for the entire navigation phase.

**Files:**
- Modify: `extension/background/agent/messageHandler.ts:44-57`
- Test: there are no unit tests for `messageHandler.ts` yet — add a new test file.

- [ ] **Step 1: Create test file for messageHandler**

  Create `extension/background/agent/__tests__/messageHandler.test.ts`:

  ```typescript
  import { describe, it, expect, vi, beforeEach } from 'vitest';

  // ── Global stubs ───────────────────────────────────────────────────────────

  vi.stubGlobal('chrome', {
    tabs: { get: vi.fn().mockResolvedValue({ url: 'https://example.com', title: 'Test' }) },
    scripting: { executeScript: vi.fn().mockResolvedValue([]) },
    alarms: { create: vi.fn(), onAlarm: { addListener: vi.fn() } },
    storage: { local: { set: vi.fn(), get: vi.fn() } },
  });

  // ── Module mocks ──────────────────────────────────────────────────────────

  const mockAppendLog = vi.fn();
  const mockSendToPanel = vi.fn();
  const mockGet = vi.fn();

  vi.mock('../../../background/session/manager', () => ({
    sessionManager: {
      get: mockGet,
      appendLog: mockAppendLog,
      sendToPanel: mockSendToPanel,
      removeSession: vi.fn(),
    },
  }));

  const mockExecuteAction = vi.fn().mockResolvedValue({ navigated: false });
  vi.mock('../../../background/browser/actions', () => ({
    executeAction: mockExecuteAction,
  }));

  vi.mock('../../../background/browser/navigation', () => ({
    waitForNavCompleted: vi.fn().mockResolvedValue(undefined),
  }));

  const makeSession = (overrides = {}) => ({
    job_id: 'job1',
    token: 'tok',
    thread_id: 'thread1',
    ws: { send: vi.fn(), readyState: 1 },
    page: {
      attach: vi.fn().mockResolvedValue(undefined),
      detach: vi.fn().mockResolvedValue(undefined),
      snapshot: vi.fn().mockResolvedValue({
        url: 'https://example.com', title: 'Test',
        elements: '[1]<button>Apply</>', scroll_y: 0, scroll_height: 100, viewport_height: 800,
      }),
    },
    log: [],
    currentStatus: 'navigating',
    ...overrides,
  });

  // ── Tests ─────────────────────────────────────────────────────────────────

  describe('handleAgentMessage — execute_actions', () => {
    beforeEach(() => {
      vi.clearAllMocks();
    });

    it('calls appendLog once per action with a step entry', async () => {
      const { handleAgentMessage } = await import('../../messageHandler');
      const session = makeSession();
      mockGet.mockReturnValue(session);

      await handleAgentMessage(1, {
        type: 'execute_actions',
        actions: [
          { action: 'click_element', index: 3 },
          { action: 'scroll_to_bottom' },
        ],
      });

      // One appendLog call per action
      expect(mockAppendLog).toHaveBeenCalledTimes(2);

      // Each log entry must be a step with done: true
      const calls = mockAppendLog.mock.calls;
      expect(calls[0][1]).toMatchObject({ kind: 'step', done: true });
      expect(calls[1][1]).toMatchObject({ kind: 'step', done: true });

      // Log text must describe the action
      expect(calls[0][1].text).toContain('click_element');
      expect(calls[1][1].text).toContain('scroll_to_bottom');
    });

    it('does not call appendLog when actions array is empty', async () => {
      const { handleAgentMessage } = await import('../../messageHandler');
      const session = makeSession();
      mockGet.mockReturnValue(session);

      await handleAgentMessage(1, { type: 'execute_actions', actions: [] });

      expect(mockAppendLog).not.toHaveBeenCalled();
    });
  });
  ```

- [ ] **Step 2: Run test to verify it fails**

  ```bash
  cd /Users/loryschi/projects/jobstrainer/extension
  npm test -- --reporter=verbose 2>&1 | grep -A 5 "execute_actions"
  ```

  Expected: FAIL — `mockAppendLog` is called 0 times.

- [ ] **Step 3: Apply the fix in messageHandler.ts**

  In `extension/background/agent/messageHandler.ts`, replace the `execute_actions` handler (lines 44–57):

  **Before:**
  ```typescript
  execute_actions: async (tabId, session, msg) => {
    session.currentStatus = 'navigating';
    await session.page.attach();
    for (const action of msg.actions as Record<string, unknown>[]) {
      const { navigated } = await executeAction(session.page, action, tabId);
      if (navigated) {
        await session.page.detach();
        await session.page.attach();
        break;
      }
    }
    const snap = await session.page.snapshot();
    session.ws.send(JSON.stringify(snap));
  },
  ```

  **After:**
  ```typescript
  execute_actions: async (tabId, session, msg) => {
    session.currentStatus = 'navigating';
    await session.page.attach();
    for (const action of msg.actions as Record<string, unknown>[]) {
      const actionName = action.action as string;
      const indexSuffix = action.index != null ? ` [${action.index}]` : '';
      sessionManager.appendLog(tabId, {
        kind: 'step',
        text: `Action: ${actionName}${indexSuffix}`,
        done: true,
      });
      const { navigated } = await executeAction(session.page, action, tabId);
      if (navigated) {
        await session.page.detach();
        await session.page.attach();
        break;
      }
    }
    const snap = await session.page.snapshot();
    session.ws.send(JSON.stringify(snap));
  },
  ```

- [ ] **Step 4: Run all extension tests**

  ```bash
  cd /Users/loryschi/projects/jobstrainer/extension
  npm test -- --reporter=verbose
  ```

  Expected: all tests pass, including the two new `execute_actions` tests.

- [ ] **Step 5: Commit**

  ```bash
  cd /Users/loryschi/projects/jobstrainer/extension
  git add background/agent/messageHandler.ts background/agent/__tests__/messageHandler.test.ts
  git commit -m "fix(extension): log each executed action to side panel in execute_actions handler"
  ```

---

## Self-review

### Spec coverage

| Bug | Task |
|-----|------|
| Bug 1 — CDP debugger leak on stale probe | Task 1 |
| Bug 2 — Race condition on detach/reattach | Task 2 |
| Bug 3 — Fill phase protocol mismatch | Task 3 |
| Bug 4 — Agent paginates instead of searching | Task 4 |
| Bug 5 — Stale snapshot causes element-not-found | Task 5 |
| Bug 6 — Action logs not shown in side panel | Task 6 |

All 6 bugs covered.

### Placeholder scan

No TBD, TODO, or "implement later" entries. Every step has concrete code or exact commands.

### Type consistency

- `LogEntry` `kind: 'step'` with `text: string` and `done: boolean` — matches `session/types.ts` definition throughout.
- `sessionManager.appendLog(tabId, entry)` — signature matches `manager.ts:114`.
- `executeAction(session.page, action, tabId)` — matches `actions.ts:50-61`.
- `DOMElementNode` constructor `{ tagName, xpath, attributes, children, ... }` — matches existing test patterns in `page.test.ts`.
- `browser.disconnect()` — matches `makeBrowser` stub shape used in all existing tests.
- `node.highlightIndex` — exists on `DOMElementNode` (used in `_getElementNode` and `snapshot`).

### Edge cases confirmed

- Bug 1 fix: `this._browser!` non-null assertion is safe because the catch block is only reached when `this._page` is set (line 51 guard), which means `_browser` was also set by the earlier `attach()`.
- Bug 5 fix: recursion depth is bounded to 1 because the retry passes a `freshNode` (different object reference) and the second `_locateHandle` call will not enter the retry branch (fresh map is current, locate will either succeed or throw without retry since `freshNode !== node` is `false` on the second call — wait, actually: the second call passes `freshNode` as `node`, so `node.highlightIndex` matches `freshNode.highlightIndex`, and `freshNode === freshNode`, so the guard `freshNode !== node` is false → throws. This is correct — one retry maximum.
- Bug 3: `session.thread_id` and `session.token` are already available in the extension's `fill_and_confirm` handler (set by `session_started` and stored on the `Session` object), so passing them redundantly in the message is safe but not relied upon.
