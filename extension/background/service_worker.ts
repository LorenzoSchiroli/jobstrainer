import { sessionManager } from './session/manager';
import { handleAgentMessage } from './agent/messageHandler';

// ── Keepalive ──────────────────────────────────────────────────────────────
chrome.alarms.create('keepalive', { periodInMinutes: 0.4 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== 'keepalive') return;
  chrome.storage.local.set({ activeSessions: sessionManager.activeSessions() });
});

// The user↔offer link lives entirely in chrome.storage.local ({ token, activeJob }),
// written by content/frontend_bridge.js and read by the panel. The service worker no
// longer captures jobs per-tab — it only manages live fill sessions and panel ports.

// ── Tab lifecycle ──────────────────────────────────────────────────────────
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status !== 'complete') return;
  // Re-open the side panel on tabs that already have an active fill session.
  if (sessionManager.get(tabId)) {
    chrome.sidePanel?.open?.({ tabId }).catch(() => {});
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

  const session = sessionManager.get(tabId);
  if (session) {
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
      const session = sessionManager.get(tabId);

      // The job + token come from the panel, which reads them from storage (the
      // single source of truth). A live session keeps its own copy once opened.
      const job_id: string = session?.job_id ?? (msg.job_id as string) ?? '';
      const token: string = session?.token ?? (msg.token as string) ?? '';

      if (!job_id || !token) {
        sessionManager.sendToPanel(tabId, { type: 'error_toast', message: 'No active job — open a job in jobstrainer first.' });
        return;
      }

      // Open session (and WS) if not already open
      if (!session) {
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
