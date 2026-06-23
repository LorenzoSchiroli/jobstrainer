import { sessionManager } from './session/manager';
import { handleAgentMessage } from './agent/messageHandler';

// ── Keepalive ──────────────────────────────────────────────────────────────
chrome.alarms.create('keepalive', { periodInMinutes: 0.4 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== 'keepalive') return;
  chrome.storage.local.set({ activeSessions: sessionManager.activeSessions() });
});

// Set by frontend_bridge content script (register_pending) before/as the job tab
// opens. The JobCard link uses rel="noopener", which severs tab.openerTabId, so the
// localStorage-via-opener path below cannot run — this variable is the real path.
let pendingNextTab: { job_id: string; token: string } | null = null;

// ── register_pending from the frontend content script ───────────────────────
chrome.runtime.onMessage.addListener((msg) => {
  if (msg?.type === 'register_pending' && msg.job_id && msg.token) {
    pendingNextTab = { job_id: msg.job_id as string, token: msg.token as string };
    console.log('[tailorer] register_pending stored for next tab, job_id=%s', msg.job_id);
  }
});

// ── Tab lifecycle ──────────────────────────────────────────────────────────
chrome.tabs.onCreated.addListener(async (tab) => {
  if (!tab.id) return;

  // Chrome path: opener tab accessible, read pending from its localStorage.
  if (tab.openerTabId) {
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
        return;
      }
    } catch (_) {}
  }

  // noopener path: openerTabId is severed; frontend_bridge already forwarded the
  // job + token via register_pending. Claim it for this newly opened tab.
  if (pendingNextTab) {
    sessionManager.setPending(tab.id, pendingNextTab);
    pendingNextTab = null;
    console.log('[tailorer] pending claimed via register_pending for tab', tab.id);
    chrome.sidePanel?.open?.({ tabId: tab.id }).catch(() => {});
  }
});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo) => {
  if (changeInfo.status !== 'complete') return;
  const pending = sessionManager.getPending(tabId);
  const session = sessionManager.get(tabId);
  if (!pending && !session) return;
  chrome.sidePanel?.open?.({ tabId }).catch(() => {});
  if (pending) {
    sessionManager.sendToPanel(tabId, { type: 'show_job_context', job_id: pending.job_id, token: pending.token });
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
    port.postMessage({ type: 'show_job_context', job_id: pending.job_id, token: pending.token });
  } else if (session) {
    const wsAlive = session.ws.readyState === WebSocket.OPEN;
    port.postMessage({
      type: 'restore_panel',
      log: session.log,
      status: wsAlive ? session.currentStatus : 'error',
    });
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

  port.onMessage.addListener(async (msg: any) => {
    if (msg.type === 'stop_session') {
      if (sessionManager.has(tabId)) {
        sessionManager.stop(tabId, 'Stopped by user.');
      }
      sessionManager.sendToPanel(tabId, { type: 'set_status', status: 'idle' });
      return;
    }

    if (msg.type === 'new_session') {
      if (sessionManager.has(tabId)) {
        sessionManager.stop(tabId, 'New session started.');
      }
      sessionManager.sendToPanel(tabId, { type: 'idle' });
      return;
    }

    if (msg.type === 'append_optimistic_log') {
      const s = sessionManager.get(tabId);
      if (s) s.log.push(msg.entry as any);
      return;
    }

    if (msg.type === 'start_or_fill') {
      const feedbackText: string = msg.text ?? '';
      const pending = sessionManager.getPending(tabId);
      const session = sessionManager.get(tabId);

      const job_id: string = session?.job_id ?? pending?.job_id ?? (msg.job_id as string) ?? '';
      const token: string = session?.token ?? pending?.token ?? (msg.token as string) ?? '';

      if (!job_id || !token) {
        sessionManager.sendToPanel(tabId, { type: 'error_toast', message: 'No active job — open a job first.' });
        return;
      }

      // Open session (and WS) if not already open
      if (!session) {
        sessionManager.clearPending(tabId);
        sessionManager.open(tabId, job_id, token, handleAgentMessage);
      }

      // Wait for the session to exist
      const activeSession = sessionManager.get(tabId);
      if (!activeSession) return;

      // Capture whole-page snapshot
      try {
        sessionManager.appendLog(tabId, { kind: 'step', text: 'Capturing page snapshot…', done: false });
        await activeSession.page.attach();
        const snapshot = await activeSession.page.snapshot();
        sessionManager.appendLog(tabId, { kind: 'step', text: 'Capturing page snapshot…', done: true });

        const wsMsg = JSON.stringify({ type: 'start_or_fill', text: feedbackText, snapshot });
        const wsState = activeSession.ws.readyState;
        console.log('[tailorer] start_or_fill wsState=%d elements=%d', wsState, (snapshot.elements.match(/^\[/gm) ?? []).length);

        if (wsState === WebSocket.OPEN) {
          activeSession.ws.send(wsMsg);
          sessionManager.appendLog(tabId, { kind: 'step', text: 'Analyzing form with AI…', done: false });
        } else {
          sessionManager.appendLog(tabId, { kind: 'step', text: 'Waiting for backend connection…', done: false });
          activeSession.ws.addEventListener('open', () => {
            activeSession.ws.send(wsMsg);
            sessionManager.appendLog(tabId, { kind: 'step', text: 'Analyzing form with AI…', done: false });
          }, { once: true });
        }
      } catch (e) {
        console.error('[tailorer] snapshot failed during start_or_fill', e);
        sessionManager.appendLog(tabId, { kind: 'error', message: `Snapshot failed: ${(e as Error).message}` });
        sessionManager.sendToPanel(tabId, { type: 'set_status', status: 'error' });
      }
      return;
    }

    // Forward submitted signal
    if (msg.type === 'submitted') {
      const s = sessionManager.get(tabId);
      if (s?.ws.readyState === WebSocket.OPEN) {
        s.ws.send(JSON.stringify({ type: 'submitted' }));
      }
      return;
    }
  });
});
