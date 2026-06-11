# Tailorer Extension Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Break `service_worker.ts` (460-line monolith) into focused modules: typed session interfaces, a `SessionManager` class, a browser action registry, a navigation helper module, and a dispatch-map message handler — leaving `service_worker.ts` as a thin ~80-line orchestrator.

**Architecture:** `SessionManager` (singleton) owns all mutable state (`sessions`, `pendingJobs`, `ports`). The browser action registry replaces the if/else `executeAction` chain with a typed `Record<string, ActionFn>`. The message handler replaces the 10-branch `handleAgentMessage` with a `Record<string, Handler>` dispatch map. `service_worker.ts` only wires Chrome extension lifecycle events. Wire protocol with the backend is not changed.

**Tech Stack:** TypeScript, Puppeteer-core (ExtensionTransport/CDP), Chrome MV3 Extension APIs, Vite (IIFE bundle), Vitest

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `extension/background/session/types.ts` | `LogEntry`, `Session`, `PendingJob`, `FileLink` interfaces |
| Create | `extension/background/browser/navigation.ts` | `waitForNavCompleted`, `clickAndDetectNavigation` |
| Create | `extension/background/browser/actions.ts` | `executeAction` dispatch registry |
| Create | `extension/background/session/manager.ts` | `SessionManager` class + `sessionManager` singleton |
| Create | `extension/background/agent/messageHandler.ts` | `handleAgentMessage` dispatch map |
| Modify | `extension/background/service_worker.ts` | Thin orchestrator — Chrome lifecycle only |

---

### Task 7: Create `session/types.ts`

**Files:**
- Create: `extension/background/session/types.ts`

- [ ] **Step 1: Create the file**

```typescript
import type Page from '../browser/page';

export interface FileLink {
  field_id: number;
  label: string;
  url: string;
}

export type LogEntry =
  | { kind: 'step'; text: string; done: boolean }
  | { kind: 'confirm'; summary: string; uncertain_fields: string[]; file_links: FileLink[] }
  | { kind: 'stuck'; message: string }
  | { kind: 'done'; message: string; thread_id: string; token: string }
  | { kind: 'error'; message: string };

export interface PendingJob {
  job_id: string;
  token: string;
}

export interface Session {
  job_id: string;
  token: string;
  thread_id: string | null;
  ws: WebSocket;
  page: Page;
  log: LogEntry[];
  currentStatus: string;
}
```

- [ ] **Step 2: Verify it compiles (no errors)**

```bash
cd extension && npx tsc --noEmit --strict background/session/types.ts 2>&1 | head -20
```

Expected: no errors (or only "cannot find module" for Page which hasn't moved — that's fine, it means types are valid).

- [ ] **Step 3: Commit**

```bash
git add extension/background/session/types.ts
git commit -m "feat(extension): add session types module"
```

---

### Task 8: Create `browser/navigation.ts`

Extract `waitForNavCompleted` and `clickAndDetectNavigation` verbatim from `service_worker.ts`.

**Files:**
- Create: `extension/background/browser/navigation.ts`

- [ ] **Step 1: Create the file**

```typescript
/**
 * Waits for webNavigation.onCompleted on the main frame.
 * Must be called BEFORE the action that triggers navigation to avoid missing fast navigations.
 */
export function waitForNavCompleted(tabId: number, timeoutMs = 8000): Promise<void> {
  return new Promise(resolve => {
    const onCompleted = (details: { tabId: number; frameId: number }) => {
      if (details.tabId !== tabId || details.frameId !== 0) return;
      chrome.webNavigation.onCompleted.removeListener(onCompleted as any);
      resolve();
    };
    chrome.webNavigation.onCompleted.addListener(onCompleted as any);
    setTimeout(() => {
      chrome.webNavigation.onCompleted.removeListener(onCompleted as any);
      resolve();
    }, timeoutMs);
  });
}

/**
 * Clicks an element and detects whether a full or SPA navigation was committed.
 * Registers webNavigation listeners BEFORE the click so fast navigations are never missed.
 * Returns true if the page navigated, false if the DOM changed in-place only.
 */
export async function clickAndDetectNavigation(
  tabId: number,
  clickFn: () => Promise<void>,
): Promise<boolean> {
  let committed = false;
  let resolveCommit!: () => void;
  let resolveComplete!: () => void;

  const commitPromise = new Promise<void>(r => { resolveCommit = r; });
  const completePromise = new Promise<void>(r => { resolveComplete = r; });

  const cleanup = () => {
    chrome.webNavigation.onCommitted.removeListener(onCommitted as any);
    chrome.webNavigation.onCompleted.removeListener(onCompleted as any);
    chrome.webNavigation.onHistoryStateUpdated.removeListener(onHistoryStateUpdated as any);
  };

  const onCommitted = (details: { tabId: number; frameId: number }) => {
    if (details.tabId !== tabId || details.frameId !== 0) return;
    committed = true;
    chrome.webNavigation.onCommitted.removeListener(onCommitted as any);
    resolveCommit();
  };
  const onCompleted = (details: { tabId: number; frameId: number }) => {
    if (details.tabId !== tabId || details.frameId !== 0) return;
    chrome.webNavigation.onCompleted.removeListener(onCompleted as any);
    resolveComplete();
  };
  // SPA route change via history.pushState/replaceState — treat as both committed and complete.
  const onHistoryStateUpdated = (details: { tabId: number; frameId: number }) => {
    if (details.tabId !== tabId || details.frameId !== 0) return;
    committed = true;
    chrome.webNavigation.onHistoryStateUpdated.removeListener(onHistoryStateUpdated as any);
    resolveCommit();
    resolveComplete();
  };

  chrome.webNavigation.onCommitted.addListener(onCommitted as any);
  chrome.webNavigation.onCompleted.addListener(onCompleted as any);
  chrome.webNavigation.onHistoryStateUpdated.addListener(onHistoryStateUpdated as any);

  await clickFn();

  const didCommit = await Promise.race([
    commitPromise.then(() => true as boolean),
    new Promise<boolean>(r => setTimeout(() => r(false), 1000)),
  ]);

  if (!didCommit) {
    cleanup();
    return false;
  }

  await Promise.race([
    completePromise,
    new Promise<void>(r => setTimeout(r, 8000)),
  ]);
  cleanup();
  return true;
}
```

- [ ] **Step 2: Build to verify it compiles**

```bash
cd extension && ENTRY=sw npm run build 2>&1 | grep -E "error|✓" | head -10
```

Expected: build succeeds (navigation.ts is not yet imported by anything, so warnings about unused are fine).

- [ ] **Step 3: Commit**

```bash
git add extension/background/browser/navigation.ts
git commit -m "feat(extension): extract navigation helpers to browser/navigation.ts"
```

---

### Task 9: Create `browser/actions.ts`

**Files:**
- Create: `extension/background/browser/actions.ts`

- [ ] **Step 1: Create the file**

```typescript
import Page from './page';
import { waitForNavCompleted, clickAndDetectNavigation } from './navigation';

export interface ActionResult {
  navigated: boolean;
}

type ActionFn = (
  page: Page,
  action: Record<string, unknown>,
  tabId: number,
) => Promise<ActionResult>;

const done = (fn: () => Promise<unknown>): Promise<ActionResult> =>
  fn().then(() => ({ navigated: false }));

const ACTIONS: Record<string, ActionFn> = {
  click_element: (page, a, tabId) =>
    clickAndDetectNavigation(tabId, () => page.clickElement(a.index as number))
      .then(navigated => ({ navigated })),

  input_text: (page, a) =>
    done(() => page.typeText(a.index as number, (a.text ?? '') as string)),

  select_option: (page, a) =>
    done(() => page.selectOption(a.index as number, ((a.text ?? a.value) ?? '') as string)),

  scroll_to_bottom: (page) => done(() => page.scrollToBottom()),
  scroll_to_top:    (page) => done(() => page.scrollToTop()),
  next_page:        (page) => done(() => page.scrollDown()),
  previous_page:    (page) => done(() => page.scrollUp()),
  send_keys:        (page, a) => done(() => page.sendKeys((a.keys ?? '') as string)),
  wait:             (page, a) => done(() => page.wait((a.seconds ?? 2) as number)),

  go_back: async (page, _a, tabId) => {
    const navDone = waitForNavCompleted(tabId);
    await page.goBack();
    await navDone;
    return { navigated: true };
  },

  go_to_url: async (page, a, tabId) => {
    const navDone = waitForNavCompleted(tabId);
    await page.navigate(a.url as string);
    await navDone;
    return { navigated: true };
  },
};

export async function executeAction(
  page: Page,
  action: Record<string, unknown>,
  tabId: number,
): Promise<ActionResult> {
  const fn = ACTIONS[action.action as string];
  if (!fn) {
    console.warn('[actions] unknown action', action.action);
    return { navigated: false };
  }
  return fn(page, action, tabId);
}
```

- [ ] **Step 2: Build to verify it compiles**

```bash
cd extension && ENTRY=sw npm run build 2>&1 | grep -E "error|✓" | head -10
```

Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add extension/background/browser/actions.ts
git commit -m "feat(extension): action registry in browser/actions.ts"
```

---

### Task 10: Create `session/manager.ts`

**Files:**
- Create: `extension/background/session/manager.ts`

- [ ] **Step 1: Create the file**

```typescript
import Page from '../browser/page';
import type { Session, PendingJob, LogEntry } from './types';

export type MessageHandler = (
  tabId: number,
  msg: Record<string, unknown>,
) => Promise<void>;

export class SessionManager {
  private readonly sessions = new Map<number, Session>();
  private readonly pendingJobs = new Map<number, PendingJob>();
  private readonly ports = new Map<number, chrome.runtime.Port>();

  // ── Ports ──────────────────────────────────────────────────────────────────

  registerPort(tabId: number, port: chrome.runtime.Port): void {
    this.ports.set(tabId, port);
  }

  removePort(tabId: number): void {
    this.ports.delete(tabId);
  }

  sendToPanel(tabId: number, msg: unknown): void {
    this.ports.get(tabId)?.postMessage(msg);
  }

  // ── Pending jobs ───────────────────────────────────────────────────────────

  setPending(tabId: number, job: PendingJob): void {
    this.pendingJobs.set(tabId, job);
  }

  getPending(tabId: number): PendingJob | undefined {
    return this.pendingJobs.get(tabId);
  }

  clearPending(tabId: number): void {
    this.pendingJobs.delete(tabId);
  }

  // ── Sessions ───────────────────────────────────────────────────────────────

  get(tabId: number): Session | undefined {
    return this.sessions.get(tabId);
  }

  has(tabId: number): boolean {
    return this.sessions.has(tabId);
  }

  open(tabId: number, jobId: string, token: string, onMessage: MessageHandler): void {
    const wsUrl = `ws://localhost:8000/tailorer/ws/${jobId}?token=${encodeURIComponent(token)}`;
    const ws = new WebSocket(wsUrl);
    const page = new Page(tabId);

    const session: Session = {
      job_id: jobId, token, thread_id: null,
      ws, page, log: [], currentStatus: 'connecting',
    };
    this.sessions.set(tabId, session);

    ws.onmessage = async (event) => {
      let msg: Record<string, unknown> | undefined;
      try {
        msg = JSON.parse(event.data as string) as Record<string, unknown>;
        await onMessage(tabId, msg);
      } catch (e) {
        console.error('[tailorer] onMessage error type=%s err=%s', msg?.type, (e as Error)?.message);
        const needsResponse = msg && ['navigate', 'request_snapshot', 'execute_actions'].includes(msg.type as string);
        if (needsResponse && ws.readyState === WebSocket.OPEN) {
          const tab = await chrome.tabs.get(tabId).catch(() => null);
          ws.send(JSON.stringify({
            url: tab?.url ?? '', title: tab?.title ?? '',
            elements: '', scroll_y: 0, scroll_height: 0, viewport_height: 0,
          }));
        }
      }
    };

    ws.onclose = (ev) => {
      const s = this.sessions.get(tabId);
      if (!s) return;
      const msg = ev.code === 4001 || ev.code === 1015
        ? `Auth error (${ev.code})`
        : 'Connection lost — restart session.';
      this.appendLog(tabId, { kind: 'error', message: msg });
      s.page.detach().catch(() => {});
      this.sessions.delete(tabId);
    };

    ws.onerror = () => {};
  }

  stop(tabId: number, reason: string): void {
    const s = this.sessions.get(tabId);
    if (!s) return;
    s.ws.close();
    s.page.detach().catch(() => {});
    this.appendLog(tabId, { kind: 'error', message: reason });
    this.sessions.delete(tabId);
  }

  removeSession(tabId: number): void {
    const s = this.sessions.get(tabId);
    if (s) {
      s.page.detach().catch(() => {});
      this.sessions.delete(tabId);
    }
  }

  // ── Log ────────────────────────────────────────────────────────────────────

  appendLog(tabId: number, entry: LogEntry): void {
    const s = this.sessions.get(tabId);
    if (!s) return;
    s.log.push(entry);
    this.sendToPanel(tabId, { type: 'append_log', entry });
  }

  // ── Cleanup ────────────────────────────────────────────────────────────────

  cleanupTab(tabId: number): void {
    const s = this.sessions.get(tabId);
    if (s) {
      s.ws.close();
      s.page.detach().catch(() => {});
      this.sessions.delete(tabId);
    }
    this.pendingJobs.delete(tabId);
    this.ports.delete(tabId);
  }

  // ── Keepalive snapshot ─────────────────────────────────────────────────────

  activeSessions(): Array<{
    tabId: number; job_id: string; token: string;
    log: LogEntry[]; currentStatus: string;
  }> {
    return Array.from(this.sessions.entries()).map(([tabId, s]) => ({
      tabId, job_id: s.job_id, token: s.token, log: s.log, currentStatus: s.currentStatus,
    }));
  }
}

export const sessionManager = new SessionManager();
```

- [ ] **Step 2: Build to verify it compiles**

```bash
cd extension && ENTRY=sw npm run build 2>&1 | grep -E "error|✓" | head -10
```

Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add extension/background/session/manager.ts
git commit -m "feat(extension): SessionManager class in session/manager.ts"
```

---

### Task 11: Create `agent/messageHandler.ts`

**Files:**
- Create: `extension/background/agent/messageHandler.ts`

- [ ] **Step 1: Create the file**

```typescript
import { sessionManager } from '../session/manager';
import { executeAction } from '../browser/actions';
import { waitForNavCompleted } from '../browser/navigation';
import type { Session, LogEntry } from '../session/types';

const API_BASE = 'http://localhost:8000';

function safeHostname(url: string): string {
  try { return new URL(url).hostname; } catch { return url; }
}

type Handler = (
  tabId: number,
  session: Session,
  msg: Record<string, unknown>,
) => Promise<void>;

const HANDLERS: Record<string, Handler> = {
  session_started: async (tabId, session, msg) => {
    session.thread_id = msg.thread_id as string;
    session.currentStatus = 'navigating';
    sessionManager.appendLog(tabId, { kind: 'step', text: 'Session started', done: true });
    sessionManager.sendToPanel(tabId, { type: 'set_status', status: 'navigating' });
  },

  navigate: async (tabId, session, msg) => {
    session.currentStatus = 'navigating';
    await session.page.detach();
    const navDone = waitForNavCompleted(tabId);
    await chrome.tabs.update(tabId, { url: msg.url as string });
    await navDone;
    await session.page.attach();
    const snap = await session.page.snapshot();
    sessionManager.appendLog(tabId, { kind: 'step', text: `Navigated to ${safeHostname(msg.url as string)}`, done: true });
    session.ws.send(JSON.stringify(snap));
  },

  request_snapshot: async (_tabId, session) => {
    await session.page.attach();
    const snap = await session.page.snapshot();
    session.ws.send(JSON.stringify(snap));
  },

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

  fill_and_confirm: async (tabId, session, msg) => {
    session.currentStatus = 'filling';
    await session.page.attach();
    const commands = msg.commands as Record<string, unknown>[];

    for (const cmd of commands) {
      if (cmd.action === 'file_upload' || cmd.value === '__CV__' || cmd.value === '__COVER_LETTER__') continue;
      try {
        if (cmd.action === 'input_text') {
          await session.page.typeText(cmd.index as number, cmd.value as string);
        } else if (cmd.action === 'select_option') {
          await session.page.selectOption(cmd.index as number, ((cmd.text ?? cmd.value) as string));
        }
      } catch (e) {
        console.warn('[tailorer] fill cmd failed', cmd, e);
      }
    }

    const fileLinks = commands
      .filter(c => c.action === 'file_upload' || c.value === '__CV__' || c.value === '__COVER_LETTER__')
      .map(c => ({
        field_id: c.index as number,
        label: c.value === '__CV__' ? 'tailored_cv.docx' : 'cover_letter.docx',
        url: `${API_BASE}/tailorer/files/${session.thread_id}/${c.value === '__CV__' ? 'cv' : 'cover_letter'}?token=${encodeURIComponent(session.token)}`,
      }));

    const confirmCmds = (msg.confirm_commands ?? commands) as Record<string, unknown>[];
    const uncertain = confirmCmds.filter(c => c.uncertain).map(c => `[${c.index}]`);

    session.currentStatus = 'awaiting_user';
    sessionManager.appendLog(tabId, {
      kind: 'confirm',
      summary: (msg.summary as string) || 'Ready to fill',
      uncertain_fields: uncertain,
      file_links: fileLinks,
    });
    sessionManager.sendToPanel(tabId, { type: 'set_status', status: 'awaiting_user' });
  },

  show_confirm: async (tabId, session, msg) => {
    session.currentStatus = 'awaiting_user';
    sessionManager.appendLog(tabId, {
      kind: 'confirm',
      summary: msg.summary as string,
      uncertain_fields: (msg.uncertain_fields as string[]) ?? [],
      file_links: (msg.file_links as any[]) ?? [],
    });
    sessionManager.sendToPanel(tabId, { type: 'set_status', status: 'awaiting_user' });
  },

  navigate_next: async (tabId, session) => {
    session.currentStatus = 'navigating';
    sessionManager.appendLog(tabId, { kind: 'step', text: 'Submitting page…', done: false });
    await new Promise(r => setTimeout(r, 1000));
    session.ws.send(JSON.stringify({ submitted: true }));
  },

  show_stuck: async (tabId, session, msg) => {
    session.currentStatus = 'show_stuck';
    sessionManager.appendLog(tabId, { kind: 'stuck', message: msg.message as string });
    sessionManager.sendToPanel(tabId, { type: 'set_status', status: 'show_stuck' });
  },

  done: async (tabId, session, msg) => {
    session.currentStatus = 'done';
    sessionManager.appendLog(tabId, {
      kind: 'done',
      message: msg.message as string,
      thread_id: session.thread_id ?? '',
      token: session.token,
    });
    sessionManager.sendToPanel(tabId, { type: 'set_status', status: 'done' });
    sessionManager.removeSession(tabId);
  },

  error: async (tabId, session, msg) => {
    session.currentStatus = 'error';
    sessionManager.appendLog(tabId, { kind: 'error', message: msg.message as string });
    sessionManager.sendToPanel(tabId, { type: 'set_status', status: 'error' });
    sessionManager.removeSession(tabId);
  },
};

export async function handleAgentMessage(
  tabId: number,
  msg: Record<string, unknown>,
): Promise<void> {
  const session = sessionManager.get(tabId);
  if (!session) return;
  const handler = HANDLERS[msg.type as string];
  if (!handler) return;
  await handler(tabId, session, msg);
}
```

- [ ] **Step 2: Build to verify it compiles**

```bash
cd extension && ENTRY=sw npm run build 2>&1 | grep -E "error|✓" | head -10
```

Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add extension/background/agent/messageHandler.ts
git commit -m "feat(extension): message handler dispatch map in agent/messageHandler.ts"
```

---

### Task 12: Refactor `service_worker.ts` to thin orchestrator

Replace the entire content of `service_worker.ts` with the wiring-only version below.

**Files:**
- Modify: `extension/background/service_worker.ts`

- [ ] **Step 1: Replace the full file content**

```typescript
import { sessionManager } from './session/manager';
import { handleAgentMessage } from './agent/messageHandler';

// ── Keepalive ──────────────────────────────────────────────────────────────
chrome.alarms.create('keepalive', { periodInMinutes: 0.4 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== 'keepalive') return;
  chrome.storage.local.set({ activeSessions: sessionManager.activeSessions() });
});

// ── Tab lifecycle ──────────────────────────────────────────────────────────
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
    const { pending, token } = result.result as { pending: string | null; token: string | null };
    if (pending && token) {
      const { job_id } = JSON.parse(pending) as { job_id: string };
      await chrome.scripting.executeScript({
        target: { tabId: tab.openerTabId },
        func: () => localStorage.removeItem('tailorer_pending'),
      });
      sessionManager.setPending(tab.id, { job_id, token });
      chrome.sidePanel?.open?.({ tabId: tab.id }).catch(() => {});
    }
  } catch (_) {}
});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo) => {
  if (changeInfo.status !== 'complete') return;
  const pending = sessionManager.getPending(tabId);
  const session = sessionManager.get(tabId);
  if (!pending && !session) return;
  chrome.sidePanel?.open?.({ tabId }).catch(() => {});
  if (pending) {
    sessionManager.sendToPanel(tabId, { type: 'show_apply_button', job_id: pending.job_id, token: pending.token });
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  sessionManager.cleanupTab(tabId);
});

// ── Panel ports ────────────────────────────────────────────────────────────
chrome.runtime.onConnect.addListener((port) => {
  const match = port.name.match(/^panel-(\d+)$/);
  if (!match) return;
  const tabId = parseInt(match[1]);
  sessionManager.registerPort(tabId, port);

  port.onDisconnect.addListener(() => {
    sessionManager.removePort(tabId);
  });

  const pending = sessionManager.getPending(tabId);
  const session = sessionManager.get(tabId);
  if (pending) {
    port.postMessage({ type: 'show_apply_button', job_id: pending.job_id, token: pending.token });
  } else if (session) {
    port.postMessage({ type: 'restore_panel', log: session.log, status: session.currentStatus });
  } else {
    chrome.storage.local.get('activeSessions', ({ activeSessions }) => {
      const saved = (activeSessions as any[] || []).find((s: any) => s.tabId === tabId);
      if (saved) {
        port.postMessage({
          type: 'restore_panel',
          log: [...saved.log, { kind: 'error', message: 'Connection lost — restart session.' }],
          status: 'error',
        });
      } else {
        port.postMessage({ type: 'idle' });
      }
    });
  }

  port.onMessage.addListener((msg: any) => {
    if (msg.type === 'start_session') {
      sessionManager.clearPending(tabId);
      sessionManager.open(tabId, msg.job_id as string, msg.token as string, handleAgentMessage);
      return;
    }
    if (msg.type === 'stop_session') {
      if (sessionManager.has(tabId)) {
        sessionManager.stop(tabId, 'Stopped by user.');
      } else {
        sessionManager.sendToPanel(tabId, { type: 'idle' });
      }
      return;
    }
    const session = sessionManager.get(tabId);
    if (!session?.ws || session.ws.readyState !== WebSocket.OPEN) return;
    if (['user_approved', 'user_correction', 'stuck_unblocked', 'user_manual_edit'].includes(msg.type)) {
      session.ws.send(JSON.stringify(msg));
    }
  });
});
```

- [ ] **Step 2: Build the service worker**

```bash
cd extension && ENTRY=sw npm run build 2>&1
```

Expected: build succeeds with no TypeScript errors. `dist/background/service_worker.js` updated.

- [ ] **Step 3: Build the sidepanel**

```bash
cd extension && npm run build 2>&1
```

Expected: both builds succeed.

- [ ] **Step 4: Verify the compiled output has key symbols from all new modules**

```bash
grep -c "SessionManager\|sessionManager" extension/dist/background/service_worker.js
grep -c "executeAction\|ACTIONS" extension/dist/background/service_worker.js
grep -c "clickAndDetectNavigation\|waitForNavCompleted" extension/dist/background/service_worker.js
grep -c "handleAgentMessage\|HANDLERS" extension/dist/background/service_worker.js
```

Expected: each returns 1 or more (symbols were included in the bundle).

- [ ] **Step 5: Run existing tests**

```bash
cd extension && npm test 2>&1 | tail -30
```

Expected: all tests pass (DOM tests for page.ts and dom service unchanged).

- [ ] **Step 6: Commit**

```bash
git add extension/background/service_worker.ts
git commit -m "refactor(extension): service_worker.ts reduced to thin orchestrator (~80 lines)"
```

---

### Task 13: Final verification

- [ ] **Step 1: Full clean build**

```bash
cd extension && rm -rf dist && ENTRY=sw npm run build && npm run build
```

Expected: no errors, `dist/background/service_worker.js` and `dist/sidepanel/` both present.

- [ ] **Step 2: Run full test suite**

```bash
cd extension && npm test
```

Expected: all tests pass.

- [ ] **Step 3: Line count check — confirm service_worker.ts is lean**

```bash
wc -l extension/background/service_worker.ts
```

Expected: under 100 lines.

- [ ] **Step 4: Commit final build artifacts**

```bash
git add -A extension/dist/
git commit -m "chore(extension): rebuild dist after modular refactor"
```
