import Page, { type PageSnapshot } from './browser/page';

const API_BASE = 'http://localhost:8000';

interface FileLink { field_id: number; label: string; url: string; }

type LogEntry =
  | { kind: 'step'; text: string; done: boolean }
  | { kind: 'confirm'; summary: string; uncertain_fields: string[]; file_links: FileLink[] }
  | { kind: 'stuck'; message: string }
  | { kind: 'done'; message: string; thread_id: string; token: string }
  | { kind: 'error'; message: string };

interface Session {
  job_id: string;
  token: string;
  thread_id: string | null;
  ws: WebSocket;
  page: Page;
  log: LogEntry[];
  currentStatus: string;
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

// ── Session lifecycle ──────────────────────────────────────────────────────

function openSession(tabId: number, job_id: string, token: string): void {
  const wsUrl = `ws://localhost:8000/tailorer/ws/${job_id}?token=${encodeURIComponent(token)}`;
  const ws = new WebSocket(wsUrl);
  const page = new Page(tabId);

  sessions[tabId] = {
    job_id, token, thread_id: null,
    ws, page, log: [], currentStatus: 'connecting',
  };

  ws.onmessage = async (event) => {
    let msg: any;
    try {
      msg = JSON.parse(event.data);
      await handleAgentMessage(tabId, msg);
    } catch (e) {
      console.error('[tailorer] handleAgentMessage error', e);
      // Message types that require a snapshot response — if we swallow the error
      // without responding, the backend's interrupt() blocks forever.
      const needsResponse = msg && ['navigate', 'request_snapshot', 'execute_actions'].includes(msg.type);
      const s = sessions[tabId];
      if (needsResponse && s?.ws.readyState === WebSocket.OPEN) {
        const tab = await chrome.tabs.get(tabId).catch(() => null);
        const url = tab?.url ?? '';
        s.ws.send(JSON.stringify({
          url,
          title: tab?.title ?? '',
          elements: '',
          scroll_y: 0,
          scroll_height: 0,
          viewport_height: 0,
        }));
      }
    }
  };

  ws.onclose = (ev) => {
    const s = sessions[tabId];
    if (!s) return;
    if (ev.code === 4001 || ev.code === 1015) {
      appendLog(tabId, { kind: 'error', message: `Auth error (${ev.code})` });
      s.page.detach().catch(() => {});
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
    await s.page.detach();
    // Register listener BEFORE triggering navigation to avoid the race where
    // the page finishes loading before we start listening.
    const navDone = waitForNavCompleted(tabId);
    await chrome.tabs.update(tabId, { url: msg.url });
    await navDone;
    await s.page.attach();
    const snap = await s.page.snapshot();
    appendLog(tabId, { kind: 'step', text: `Navigated to ${safeHostname(msg.url)}`, done: true });
    s.ws.send(JSON.stringify(snap));
    return;
  }

  if (msg.type === 'request_snapshot') {
    await s.page.attach();
    const snap = await s.page.snapshot();
    s.ws.send(JSON.stringify(snap));
    return;
  }

  if (msg.type === 'execute_actions') {
    s.currentStatus = 'navigating';
    await s.page.attach();
    for (const action of (msg.actions as any[])) {
      const navigated = await executeAction(tabId, s, action);
      if (navigated) {
        // Navigation is already complete (waited inside executeAction).
        // Just reconnect Puppeteer to the new page.
        await s.page.detach();
        await s.page.attach();
        break;
      }
    }
    const snap = await s.page.snapshot();
    s.ws.send(JSON.stringify(snap));
    return;
  }

  if (msg.type === 'fill_and_confirm') {
    s.currentStatus = 'filling';
    await s.page.attach();
    for (const cmd of (msg.commands as any[])) {
      if (cmd.action === 'file_upload' || cmd.value === '__CV__' || cmd.value === '__COVER_LETTER__') continue;
      try {
        if (cmd.action === 'input_text') await s.page.typeText(cmd.index, cmd.value);
        else if (cmd.action === 'select_option') await s.page.selectOption(cmd.index, cmd.text ?? cmd.value);
      } catch (e) {
        console.warn('[tailorer] fill cmd failed', cmd, e);
      }
    }
    const fileLinks: FileLink[] = (msg.commands as any[])
      .filter((c: any) => c.action === 'file_upload' || c.value === '__CV__' || c.value === '__COVER_LETTER__')
      .map((c: any) => {
        const fileType = c.value === '__CV__' ? 'cv' : 'cover_letter';
        const label = fileType === 'cv' ? 'tailored_cv.docx' : 'cover_letter.docx';
        const url = `${API_BASE}/tailorer/files/${s.thread_id}/${fileType}?token=${encodeURIComponent(s.token)}`;
        return { field_id: c.index, label, url };
      });
    const uncertain = (msg.confirm_commands ?? msg.commands as any[])
      .filter((c: any) => c.uncertain)
      .map((c: any) => `[${c.index}]`);
    s.currentStatus = 'awaiting_user';
    appendLog(tabId, { kind: 'confirm', summary: msg.summary || 'Ready to fill', uncertain_fields: uncertain, file_links: fileLinks });
    sendToPanel(tabId, { type: 'status', status: 'awaiting_user' });
    return;
  }

  if (msg.type === 'show_confirm') {
    s.currentStatus = 'awaiting_user';
    appendLog(tabId, { kind: 'confirm', summary: msg.summary, uncertain_fields: msg.uncertain_fields ?? [], file_links: msg.file_links ?? [] });
    sendToPanel(tabId, { type: 'status', status: 'awaiting_user' });
    return;
  }

  if (msg.type === 'navigate_next') {
    s.currentStatus = 'navigating';
    appendLog(tabId, { kind: 'step', text: 'Submitting page…', done: false });
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
  const act: string = action.action;
  if (act === 'click_element') {
    appendLog(tabId, { kind: 'step', text: `Clicking [${action.index}]`, done: true });
    // Register navigation listeners BEFORE the click (nanobrowser pattern) to avoid the
    // race where the page finishes loading before we start listening.
    return await clickAndDetectNavigation(tabId, () => s.page.clickElement(action.index));
  }
  if (act === 'input_text') { await s.page.typeText(action.index, action.text ?? ''); return false; }
  if (act === 'select_option') { await s.page.selectOption(action.index, action.text ?? ''); return false; }
  if (act === 'scroll_to_bottom') { await s.page.scrollToBottom(); return false; }
  if (act === 'scroll_to_top') { await s.page.scrollToTop(); return false; }
  if (act === 'next_page') { await s.page.scrollDown(); return false; }
  if (act === 'previous_page') { await s.page.scrollUp(); return false; }
  if (act === 'send_keys') { await s.page.sendKeys(action.keys ?? ''); return false; }
  if (act === 'go_back') {
    const navDone = waitForNavCompleted(tabId);
    await s.page.goBack();
    await navDone;
    return true;
  }
  if (act === 'go_to_url') {
    appendLog(tabId, { kind: 'step', text: `Navigating to ${safeHostname(action.url)}`, done: true });
    const navDone = waitForNavCompleted(tabId);
    await s.page.navigate(action.url);
    await navDone;
    return true;
  }
  if (act === 'wait') { await s.page.wait(action.seconds ?? 2); return false; }
  console.warn('[tailorer] unknown action', act);
  return false;
}

// ── Navigation helpers ─────────────────────────────────────────────────────

// Waits for webNavigation.onCompleted on the main frame. Must be called BEFORE
// the action that triggers navigation to avoid missing fast navigations.
function waitForNavCompleted(tabId: number, timeoutMs = 8000): Promise<void> {
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

// Clicks an element and detects whether a navigation was committed.
// Registers webNavigation listeners BEFORE the click so fast navigations are
// never missed (the core race condition fix).
async function clickAndDetectNavigation(tabId: number, clickFn: () => Promise<void>): Promise<boolean> {
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
  // SPA route change via history.pushState/replaceState. There is no separate
  // "completed" event for these, so treat it as both committed and complete —
  // snapshot()'s settle wait handles the actual content render.
  const onHistoryStateUpdated = (details: { tabId: number; frameId: number }) => {
    if (details.tabId !== tabId || details.frameId !== 0) return;
    committed = true;
    chrome.webNavigation.onHistoryStateUpdated.removeListener(onHistoryStateUpdated as any);
    resolveCommit();
    resolveComplete();
  };

  // Register BEFORE the click
  chrome.webNavigation.onCommitted.addListener(onCommitted as any);
  chrome.webNavigation.onCompleted.addListener(onCompleted as any);
  chrome.webNavigation.onHistoryStateUpdated.addListener(onHistoryStateUpdated as any);

  await clickFn();

  // Wait up to 1s to see if a navigation was committed
  const didCommit = await Promise.race([
    commitPromise.then(() => true as boolean),
    new Promise<boolean>(r => setTimeout(() => r(false), 1000)),
  ]);

  if (!didCommit) {
    cleanup();
    return false; // no navigation and no SPA route change — in-place DOM update only
  }

  // Navigation committed — wait for it to fully complete (up to 8s)
  await Promise.race([
    completePromise,
    new Promise<void>(r => setTimeout(r, 8000)),
  ]);
  cleanup();
  return true;
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
