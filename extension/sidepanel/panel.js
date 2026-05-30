const API_BASE = 'http://localhost:8000';

const STATUS_CONFIG = {
  connecting:    { text: 'Connecting…',      dot: true,  cls: 'blue'  },
  navigating:    { text: 'Navigating…',       dot: true,  cls: 'blue'  },
  filling:       { text: 'Filling form…',     dot: true,  cls: 'blue'  },
  awaiting_user: { text: '⏸ Waiting for you', dot: false, cls: 'amber' },
  show_stuck:    { text: '⚠ Action needed',   dot: false, cls: 'red'   },
  done:          { text: '✓ Done',            dot: false, cls: 'green' },
  error:         { text: '✗ Error',           dot: false, cls: 'red'   },
  idle:          { text: 'No active session', dot: false, cls: 'slate' },
};

function setStatusBar(status) {
  const bar = document.getElementById('tailorer-status');
  if (!bar) return;
  const cfg = STATUS_CONFIG[status] || { text: status, dot: true, cls: 'blue' };
  bar.className = `tailorer-status tailorer-status--${cfg.cls}`;
  bar.innerHTML = '';
  if (cfg.dot) {
    const dot = document.createElement('span');
    dot.className = 'tailorer-dot';
    bar.appendChild(dot);
  }
  const txt = document.createElement('span');
  txt.textContent = cfg.text;
  bar.appendChild(txt);
}

function showIdleState() {
  const log = document.getElementById('tailorer-log');
  if (!log) return;
  log.innerHTML = '';
  const el = document.createElement('div');
  el.className = 'tailorer-idle';
  el.textContent = 'No active job — browse to a job listing to apply.';
  log.appendChild(el);
  setStatusBar('idle');
}

function showStartButton(job_id, token) {
  const log = document.getElementById('tailorer-log');
  if (!log) return;
  log.innerHTML = '';
  const area = document.createElement('div');
  area.className = 'tailorer-start-area';
  const hint = document.createElement('div');
  hint.className = 'tailorer-start-hint';
  hint.textContent = 'Job detected — ready to apply';
  const btn = document.createElement('button');
  btn.className = 'tailorer-btn tailorer-btn--start';
  btn.textContent = '⚡ Start Agent';
  btn.addEventListener('click', () => {
    sendMsg({ type: 'start_session', job_id, token });
    log.innerHTML = '';
    setStatusBar('connecting');
  });
  area.append(hint, btn);
  log.appendChild(area);
}

function _makeStepEntry(text, done) {
  const el = document.createElement('div');
  el.className = `tailorer-entry tailorer-entry--${done ? 'done' : 'pending'}`;
  const icon = document.createElement('span');
  icon.className = 'tailorer-entry-icon';
  icon.textContent = done ? '✓' : '⟳';
  const txt = document.createElement('span');
  txt.className = 'tailorer-entry-text';
  txt.textContent = text;
  el.append(icon, txt);
  return el;
}

function appendLogEntry(entry) {
  const log = document.getElementById('tailorer-log');
  if (!log) return;
  let el;

  if (entry.kind === 'step') {
    el = _makeStepEntry(entry.text, entry.done);

  } else if (entry.kind === 'confirm') {
    el = document.createElement('div');
    el.className = 'tailorer-confirm-block';
    const summary = document.createElement('div');
    summary.className = 'tailorer-confirm-summary';
    summary.textContent = entry.summary;
    el.appendChild(summary);
    if (entry.uncertain_fields?.length) {
      const unc = document.createElement('div');
      unc.className = 'tailorer-confirm-uncertain';
      unc.textContent = `Uncertain: ${entry.uncertain_fields.join(', ')}`;
      el.appendChild(unc);
    }
    const input = document.createElement('input');
    input.className = 'tailorer-correction-input';
    input.placeholder = 'Correction? Type + Enter…';
    input.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      const text = input.value.trim();
      if (!text) return;
      sendMsg({ type: 'user_correction', text });
      el.replaceWith(_makeStepEntry('Corrected', true));
    });
    const approveBtn = document.createElement('button');
    approveBtn.className = 'tailorer-btn tailorer-btn--approve';
    approveBtn.textContent = 'Looks good ✓';
    approveBtn.addEventListener('click', () => {
      sendMsg({ type: 'user_approved' });
      el.replaceWith(_makeStepEntry('Confirmed', true));
    });
    el.append(input, approveBtn);

  } else if (entry.kind === 'stuck') {
    el = document.createElement('div');
    el.className = 'tailorer-stuck-block';
    const msg = document.createElement('div');
    msg.className = 'tailorer-stuck-message';
    msg.textContent = entry.message;
    const unblockBtn = document.createElement('button');
    unblockBtn.className = 'tailorer-btn tailorer-btn--unblock';
    unblockBtn.textContent = 'Done, continue ▶';
    unblockBtn.addEventListener('click', () => {
      sendMsg({ type: 'stuck_unblocked' });
      el.replaceWith(_makeStepEntry('Unblocked', true));
    });
    el.append(msg, unblockBtn);

  } else if (entry.kind === 'done') {
    el = document.createElement('div');
    el.className = 'tailorer-entry tailorer-entry--done-final';
    const icon = document.createElement('span');
    icon.className = 'tailorer-entry-icon';
    icon.textContent = '✓';
    const txt = document.createElement('span');
    txt.className = 'tailorer-entry-text';
    txt.textContent = entry.message;
    el.append(icon, txt);
    if (entry.thread_id && entry.token) {
      const tok = encodeURIComponent(entry.token);
      const tid = encodeURIComponent(entry.thread_id);
      const downloads = document.createElement('div');
      downloads.className = 'tailorer-downloads';
      const cvLink = document.createElement('a');
      cvLink.className = 'tailorer-download-link';
      cvLink.href = `${API_BASE}/tailorer/files/${tid}/cv?token=${tok}`;
      cvLink.target = '_blank';
      cvLink.textContent = '↓ Tailored CV (.docx)';
      const clLink = document.createElement('a');
      clLink.className = 'tailorer-download-link';
      clLink.href = `${API_BASE}/tailorer/files/${tid}/cover_letter?token=${tok}`;
      clLink.target = '_blank';
      clLink.textContent = '↓ Cover Letter (.docx)';
      downloads.append(cvLink, clLink);
      el.appendChild(downloads);
    }
    setStatusBar('done');

  } else if (entry.kind === 'error') {
    el = document.createElement('div');
    el.className = 'tailorer-entry tailorer-entry--error';
    const icon = document.createElement('span');
    icon.className = 'tailorer-entry-icon';
    icon.textContent = '✗';
    const txt = document.createElement('span');
    txt.className = 'tailorer-entry-text';
    txt.textContent = entry.message;
    el.append(icon, txt);
    setStatusBar('error');
  }

  if (!el) return;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
}

function restorePanel(log, status) {
  const logEl = document.getElementById('tailorer-log');
  if (!logEl) return;
  logEl.innerHTML = '';
  for (const entry of log) appendLogEntry(entry);
  if (status) setStatusBar(status);
}

function sendMsg(msg) {
  (_port || globalThis.__testPort)?.postMessage(msg);
}

// ── Port connection ────────────────────────────────────────────────────────

let _port = null;

function _connectWithTab(tabId) {
  if (_port) {
    _port.onMessage.removeListener(_handleMessage);
    _port.disconnect();
  }
  const port = chrome.runtime.connect({ name: `panel-${tabId}` });
  _port = port;
  port.onMessage.addListener(_handleMessage);
  port.onDisconnect.addListener(() => {
    // Only reconnect if this port is still the active one (not superseded by a tab switch)
    if (_port !== port) return;
    _port = null;
    setTimeout(() => _connectWithTab(tabId), 500);
  });
}

function _handleMessage(msg) {
  if (msg.type === 'show_apply_button') {
    showStartButton(msg.job_id, msg.token);
    setStatusBar('connecting');
  } else if (msg.type === 'restore_panel') {
    restorePanel(msg.log || [], msg.status);
  } else if (msg.type === 'append_log') {
    appendLogEntry(msg.entry);
  } else if (msg.type === 'set_status') {
    setStatusBar(msg.status);
  } else if (msg.type === 'idle') {
    showIdleState();
  }
}

if (typeof chrome !== 'undefined' && chrome.runtime?.connect) {
  (async () => {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) return;
    _connectWithTab(tab.id);
  })();

  chrome.tabs.onActivated.addListener(({ tabId }) => {
    _connectWithTab(tabId);
  });
} else {
  globalThis.setStatusBar = setStatusBar;
  globalThis.showIdleState = showIdleState;
  globalThis.showStartButton = showStartButton;
  globalThis.appendLogEntry = appendLogEntry;
  globalThis.restorePanel = restorePanel;
}
