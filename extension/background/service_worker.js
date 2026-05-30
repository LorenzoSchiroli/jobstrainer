const API_BASE = 'http://localhost:8000';

const pendingJobs = {};  // tabId -> { job_id, token }
const sessions = {};     // tabId -> { job_id, token, thread_id, ws, pendingNavigate, reconnectDelay, log, currentStatus }
const injectedTabs = new Set();
const panelPorts = {};   // tabId -> port
let pendingNextTab = null;

if (chrome.sidePanel?.setPanelBehavior) {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
}

// ── Tab detection ──────────────────────────────────────────────────────────

chrome.tabs.onCreated.addListener(async (tab) => {
  if (tab.openerTabId) {
    try {
      const [result] = await chrome.scripting.executeScript({
        target: { tabId: tab.openerTabId },
        func: () => ({
          pending: localStorage.getItem('tailorer_pending'),
          token: localStorage.getItem('access_token'),
        }),
      });
      const { pending, token } = result.result;
      if (pending && token) {
        const { job_id } = JSON.parse(pending);
        await chrome.scripting.executeScript({
          target: { tabId: tab.openerTabId },
          func: () => localStorage.removeItem('tailorer_pending'),
        });
        pendingJobs[tab.id] = { job_id, token };
        // Auto-open side panel in Chrome while we are still in the user-gesture context
        if (chrome.sidePanel?.open) {
          chrome.sidePanel.open({ tabId: tab.id }).catch(() => {});
        }
        return;
      }
    } catch (_) {}
  }

  if (pendingNextTab) {
    pendingJobs[tab.id] = pendingNextTab;
    pendingNextTab = null;
  }
});

// ── Content script injection ───────────────────────────────────────────────

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo) => {
  if (changeInfo.url) injectedTabs.delete(tabId);

  if (changeInfo.status !== 'complete') return;
  if (!pendingJobs[tabId] && !sessions[tabId]) return;

  if (!injectedTabs.has(tabId)) {
    try {
      const files = ['content/dom_inspector.js', 'content/form_filler.js'];
      // On Firefox (no chrome.sidePanel), inject the trigger button instead of auto-opening
      if (!chrome.sidePanel) files.push('content/firefox_trigger.js');
      await chrome.scripting.executeScript({ target: { tabId }, files });
      injectedTabs.add(tabId);
    } catch (_) {
      return;
    }
  }

  // Fallback open attempt for Chrome (onCreated may have been the primary attempt)
  if (chrome.sidePanel?.open) {
    chrome.sidePanel.open({ tabId }).catch(() => {});
  }

  if (pendingJobs[tabId]) {
    const { job_id, token } = pendingJobs[tabId];
    sendToPanel(tabId, { type: 'show_apply_button', job_id, token });
    return;
  }

  const session = sessions[tabId];
  if (!session) return;

  const wasNavigating = session.pendingNavigate;
  if (wasNavigating) {
    session.pendingNavigate = false;
    const last = session.log[session.log.length - 1];
    if (last?.kind === 'step' && !last.done) last.done = true;
  }

  sendToPanel(tabId, {
    type: 'restore_panel',
    log: session.log,
    status: session.currentStatus,
  });

  if (wasNavigating) {
    requestSnapshotAndSend(tabId);
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (sessions[tabId]) {
    sessions[tabId].ws?.close();
    delete sessions[tabId];
  }
  delete pendingJobs[tabId];
  delete panelPorts[tabId];
  injectedTabs.delete(tabId);
});

// ── Messages from content scripts ─────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender) => {
  const tabId = sender.tab?.id;
  if (!tabId) return;

  if (msg.type === 'register_pending') {
    pendingNextTab = { job_id: msg.job_id, token: msg.token };
    return;
  }

  // Firefox only: user clicked the trigger button in the page
  if (msg.type === 'open_sidebar') {
    if (typeof browser !== 'undefined' && browser.sidebarAction?.open) {
      browser.sidebarAction.open().catch(() => {});
    }
  }
});

// ── Panel port connections ─────────────────────────────────────────────────

chrome.runtime.onConnect.addListener((port) => {
  const match = port.name.match(/^panel-(\d+)$/);
  if (!match) return;
  const tabId = parseInt(match[1]);
  panelPorts[tabId] = port;

  port.onDisconnect.addListener(() => {
    if (panelPorts[tabId] === port) delete panelPorts[tabId];
  });

  // Send current state to the newly connected panel
  if (pendingJobs[tabId]) {
    const { job_id, token } = pendingJobs[tabId];
    port.postMessage({ type: 'show_apply_button', job_id, token });
  } else if (sessions[tabId]) {
    const s = sessions[tabId];
    port.postMessage({ type: 'restore_panel', log: s.log, status: s.currentStatus });
  } else {
    port.postMessage({ type: 'idle' });
  }

  port.onMessage.addListener((msg) => {
    if (msg.type === 'start_session') {
      delete pendingJobs[tabId];
      openSession(tabId, msg.job_id, msg.token);
      return;
    }
    const session = sessions[tabId];
    if (!session?.ws || session.ws.readyState !== WebSocket.OPEN) return;
    if (msg.type === 'user_approved') {
      const idx = session.log.findLastIndex((e) => e.kind === 'confirm');
      if (idx !== -1) session.log[idx] = { kind: 'step', text: 'Confirmed', done: true };
      session.ws.send(JSON.stringify(msg));
    } else if (msg.type === 'user_correction') {
      const idx = session.log.findLastIndex((e) => e.kind === 'confirm');
      if (idx !== -1) session.log[idx] = { kind: 'step', text: 'Corrected', done: true };
      session.ws.send(JSON.stringify(msg));
    } else if (msg.type === 'stuck_unblocked') {
      const idx = session.log.findLastIndex((e) => e.kind === 'stuck');
      if (idx !== -1) session.log[idx] = { kind: 'step', text: 'Unblocked', done: true };
      session.ws.send(JSON.stringify(msg));
    } else if (msg.type === 'user_manual_edit') {
      session.ws.send(JSON.stringify(msg));
    }
  });
});

// ── WebSocket session lifecycle ────────────────────────────────────────────

function openSession(tabId, job_id, token) {
  const wsUrl = `ws://localhost:8000/tailorer/ws/${job_id}?token=${encodeURIComponent(token)}`;
  const ws = new WebSocket(wsUrl);

  sessions[tabId] = {
    job_id, token, thread_id: null,
    ws, pendingNavigate: false, reconnectDelay: 1000,
    log: [], currentStatus: 'connecting',
  };

  let opened = false;
  ws.onopen = () => { opened = true; };

  ws.onmessage = async (event) => {
    try { await handleAgentMessage(tabId, JSON.parse(event.data)); } catch (_) {}
  };

  ws.onclose = (ev) => {
    const s = sessions[tabId];
    if (!s) return;
    if (!opened || ev.code === 1015 || ev.code === 4001) {
      const entry = { kind: 'error', message: `WebSocket failed (code ${ev.code})` };
      s.log.push(entry);
      sendToPanel(tabId, { type: 'append_log', entry });
      delete sessions[tabId];
      return;
    }
    const delay = s.reconnectDelay;
    s.reconnectDelay = Math.min(delay * 2, 30000);
    setTimeout(() => { if (sessions[tabId]) openSession(tabId, s.job_id, s.token); }, delay);
  };

  ws.onerror = () => {};
}

// ── Agent message dispatch ─────────────────────────────────────────────────

async function handleAgentMessage(tabId, msg) {
  const session = sessions[tabId];
  if (!session) return;

  if (msg.type === 'session_started') {
    session.thread_id = msg.thread_id;
    session.reconnectDelay = 1000;
    session.currentStatus = 'navigating';
    const entry = { kind: 'step', text: 'Session started', done: true };
    session.log.push(entry);
    sendToPanel(tabId, { type: 'append_log', entry });
    return;
  }

  if (msg.type === 'navigate') {
    session.currentStatus = 'navigating';
    session.pendingNavigate = true;
    let hostname = msg.url;
    try { hostname = new URL(msg.url).hostname; } catch (_) {}
    const entry = { kind: 'step', text: `Navigating to ${hostname}…`, done: false };
    session.log.push(entry);
    sendToPanel(tabId, { type: 'append_log', entry });
    chrome.tabs.update(tabId, { url: msg.url });
    return;
  }

  if (msg.type === 'request_snapshot') {
    requestSnapshotAndSend(tabId);
    return;
  }

  if (msg.field_id !== undefined) {
    if (msg.type === 'file' || msg.value === '__CV__' || msg.value === '__COVER_LETTER__') {
      await handleFileUpload(tabId, msg);
    } else {
      session.currentStatus = 'filling';
      const entry = { kind: 'step', text: `Filling "${msg.field_id}"…`, done: true };
      session.log.push(entry);
      sendToPanel(tabId, { type: 'append_log', entry });
      chrome.tabs.sendMessage(tabId, { type: 'fill_field', field_id: msg.field_id, value: msg.value });
    }
    return;
  }

  if (msg.type === 'navigate_next') {
    session.currentStatus = 'navigating';
    const entry = { kind: 'step', text: 'Submitting page…', done: true };
    session.log.push(entry);
    sendToPanel(tabId, { type: 'append_log', entry });
    chrome.tabs.sendMessage(tabId, { type: 'navigate_next' }, (response) => {
      const liveSession = sessions[tabId];
      if (liveSession?.ws?.readyState === WebSocket.OPEN) {
        liveSession.ws.send(JSON.stringify(response || { submitted: false }));
      }
    });
    return;
  }

  if (msg.type === 'show_confirm') {
    session.currentStatus = 'awaiting_user';
    const entry = { kind: 'confirm', summary: msg.summary, uncertain_fields: msg.uncertain_fields || [] };
    session.log.push(entry);
    sendToPanel(tabId, { type: 'append_log', entry });
    return;
  }

  if (msg.type === 'show_stuck') {
    session.currentStatus = 'show_stuck';
    const entry = { kind: 'stuck', message: msg.message };
    session.log.push(entry);
    sendToPanel(tabId, { type: 'append_log', entry });
    return;
  }

  if (msg.type === 'done') {
    session.currentStatus = 'done';
    const { thread_id, token } = session;
    const entry = { kind: 'done', message: msg.message, thread_id, token };
    session.log.push(entry);
    sendToPanel(tabId, { type: 'append_log', entry });
    injectedTabs.delete(tabId);
    delete sessions[tabId];
    return;
  }

  if (msg.type === 'error') {
    session.currentStatus = 'error';
    const entry = { kind: 'error', message: msg.message };
    session.log.push(entry);
    sendToPanel(tabId, { type: 'append_log', entry });
    injectedTabs.delete(tabId);
    delete sessions[tabId];
    return;
  }
}

// ── Helpers ────────────────────────────────────────────────────────────────

function requestSnapshotAndSend(tabId) {
  chrome.tabs.sendMessage(tabId, { type: 'request_snapshot' }, (snapshot) => {
    const liveSession = sessions[tabId];
    if (snapshot && liveSession?.ws?.readyState === WebSocket.OPEN) {
      liveSession.ws.send(JSON.stringify(snapshot));
    }
  });
}

function sendToPanel(tabId, msg) {
  panelPorts[tabId]?.postMessage(msg);
}

async function handleFileUpload(tabId, msg) {
  const session = sessions[tabId];
  if (!session?.thread_id) return;
  const fileType = msg.value === '__CV__' ? 'cv' : 'cover_letter';
  const filename = fileType === 'cv' ? 'tailored_cv.docx' : 'cover_letter.docx';
  const url = `${API_BASE}/tailorer/files/${session.thread_id}/${fileType}?token=${encodeURIComponent(session.token)}`;
  try {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const buffer = await resp.arrayBuffer();
    chrome.tabs.sendMessage(tabId, { type: 'do_file_upload', field_id: msg.field_id, filename, buffer });
  } catch (_) {}
}
