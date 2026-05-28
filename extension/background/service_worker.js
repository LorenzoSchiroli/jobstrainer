const API_BASE = 'http://localhost:8000';

const pendingJobs = {};  // tabId -> { job_id, token }
const sessions = {};     // tabId -> { job_id, token, thread_id, ws, pendingNavigate, reconnectDelay }
const injectedTabs = new Set();

// ── Tab detection ──────────────────────────────────────────────────────────

chrome.tabs.onCreated.addListener(async (tab) => {
  if (!tab.openerTabId) return;
  try {
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: tab.openerTabId },
      func: () => ({
        pending: localStorage.getItem('tailorer_pending'),
        token: localStorage.getItem('access_token'),
      }),
    });
    const { pending, token } = result.result;
    if (!pending || !token) return;
    const { job_id } = JSON.parse(pending);
    // Clear pending so it doesn't re-trigger on subsequent reloads
    await chrome.scripting.executeScript({
      target: { tabId: tab.openerTabId },
      func: () => localStorage.removeItem('tailorer_pending'),
    });
    pendingJobs[tab.id] = { job_id, token };
  } catch (_) {
    // Opener tab may be inaccessible (different extension origin)
  }
});

// ── Content script injection ───────────────────────────────────────────────

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo) => {
  if (changeInfo.status !== 'complete') return;
  if (!pendingJobs[tabId] && !sessions[tabId]) return;

  if (!injectedTabs.has(tabId)) {
    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        files: ['content/dom_inspector.js', 'content/form_filler.js', 'content/overlay.js'],
      });
      await chrome.scripting.insertCSS({ target: { tabId }, files: ['content/overlay.css'] });
      injectedTabs.add(tabId);
    } catch (_) {
      return; // Tab not injectable (e.g., chrome:// URL, PDF)
    }
  }

  if (pendingJobs[tabId]) {
    const { job_id, token } = pendingJobs[tabId];
    chrome.tabs.sendMessage(tabId, { type: 'show_apply_button', job_id, token });
    return;
  }

  const session = sessions[tabId];
  if (session?.pendingNavigate) {
    session.pendingNavigate = false;
    requestSnapshotAndSend(tabId);
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (sessions[tabId]) {
    sessions[tabId].ws?.close();
    delete sessions[tabId];
  }
  delete pendingJobs[tabId];
  injectedTabs.delete(tabId);
  chrome.storage.local.remove([`status_${tabId}`, `session_${tabId}`]);
});

// ── Messages from content scripts ─────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender) => {
  const tabId = sender.tab?.id;
  if (!tabId) return;

  if (msg.type === 'start_session') {
    delete pendingJobs[tabId];
    openSession(tabId, msg.job_id, msg.token);
    return;
  }

  const session = sessions[tabId];
  if (!session?.ws || session.ws.readyState !== WebSocket.OPEN) return;

  if (['user_approved', 'user_correction', 'user_manual_edit', 'stuck_unblocked'].includes(msg.type)) {
    session.ws.send(JSON.stringify(msg));
  }
});

// ── WebSocket session lifecycle ────────────────────────────────────────────

function openSession(tabId, job_id, token) {
  const wsUrl = `ws://localhost:8000/tailorer/ws/${job_id}?token=${encodeURIComponent(token)}`;
  const ws = new WebSocket(wsUrl);

  sessions[tabId] = {
    job_id, token, thread_id: null,
    ws, pendingNavigate: false, reconnectDelay: 1000,
  };

  ws.onmessage = async (event) => {
    try { await handleAgentMessage(tabId, JSON.parse(event.data)); } catch (_) {}
  };

  ws.onclose = () => {
    const s = sessions[tabId];
    if (!s) return;
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
    setStatus(tabId, 'navigating');
    chrome.storage.local.set({
      [`session_${tabId}`]: { job_id: session.job_id, token: session.token, thread_id: msg.thread_id },
    });
    return;
  }

  if (msg.type === 'navigate') {
    setStatus(tabId, 'navigating');
    session.pendingNavigate = true;
    chrome.tabs.update(tabId, { url: msg.url });
    return;
  }

  if (msg.type === 'request_snapshot') {
    requestSnapshotAndSend(tabId);
    return;
  }

  // Fill command: regular field or file upload
  if (msg.field_id !== undefined) {
    if (msg.type === 'file' || msg.value === '__CV__' || msg.value === '__COVER_LETTER__') {
      await handleFileUpload(tabId, msg);
    } else {
      chrome.tabs.sendMessage(tabId, { type: 'fill_field', field_id: msg.field_id, value: msg.value });
    }
    return;
  }

  if (msg.type === 'navigate_next') {
    setStatus(tabId, 'navigating');
    chrome.tabs.sendMessage(tabId, { type: 'navigate_next' }, (response) => {
      if (session.ws.readyState === WebSocket.OPEN) {
        session.ws.send(JSON.stringify(response || { submitted: false }));
      }
    });
    return;
  }

  if (msg.type === 'show_confirm') {
    setStatus(tabId, 'awaiting_user');
    chrome.tabs.sendMessage(tabId, msg);
    return;
  }

  if (msg.type === 'show_stuck') {
    setStatus(tabId, 'show_stuck');
    chrome.tabs.sendMessage(tabId, msg);
    return;
  }

  if (msg.type === 'done') {
    setStatus(tabId, 'done');
    chrome.tabs.sendMessage(tabId, msg);
    chrome.storage.local.remove([`status_${tabId}`, `session_${tabId}`]);
    injectedTabs.delete(tabId);
    delete sessions[tabId];
    return;
  }

  if (msg.type === 'error') {
    setStatus(tabId, 'error');
    chrome.tabs.sendMessage(tabId, msg);
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

async function handleFileUpload(tabId, msg) {
  const session = sessions[tabId];
  if (!session?.thread_id) {
    console.error('[tailorer] file upload attempted before session_started');
    return;
  }
  const fileType = msg.value === '__CV__' ? 'cv' : 'cover_letter';
  const filename = fileType === 'cv' ? 'tailored_cv.docx' : 'cover_letter.docx';
  const url = `${API_BASE}/tailorer/files/${session.thread_id}/${fileType}?token=${encodeURIComponent(session.token)}`;
  try {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const buffer = await resp.arrayBuffer();
    chrome.tabs.sendMessage(tabId, { type: 'do_file_upload', field_id: msg.field_id, filename, buffer });
  } catch (err) {
    console.error('[tailorer] file download failed:', err);
  }
}

function setStatus(tabId, status) {
  chrome.storage.local.set({ [`status_${tabId}`]: status });
}
