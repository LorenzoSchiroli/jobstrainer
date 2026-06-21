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

      const job_id: string = session?.job_id ?? pending?.job_id ?? '';
      const token: string = session?.token ?? pending?.token ?? '';

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
        await activeSession.page.attach();
        const snapshot = await activeSession.page.snapshot();
        const wsMsg = JSON.stringify({ type: 'start_or_fill', text: feedbackText, snapshot });

        if (activeSession.ws.readyState === WebSocket.OPEN) {
          activeSession.ws.send(wsMsg);
        } else {
          // WS still connecting — queue the send
          activeSession.ws.addEventListener('open', () => activeSession.ws.send(wsMsg), { once: true });
        }
      } catch (e) {
        console.error('[tailorer] snapshot failed during start_or_fill', e);
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
