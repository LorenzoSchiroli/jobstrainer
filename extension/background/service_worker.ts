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
        sessionManager.sendToPanel(tabId, { type: 'set_status', status: 'idle' });
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
