let _shadow = null;

function initPanel() {
  document.getElementById('tailorer-host')?.remove();
  _shadow = null;

  const host = document.createElement('div');
  host.id = 'tailorer-host';
  Object.assign(host.style, {
    position: 'fixed', top: '0', right: '0',
    width: '320px', height: '100vh',
    zIndex: '2147483647',
  });
  document.body.appendChild(host);

  _shadow = host.attachShadow({ mode: 'open' });

  if (typeof chrome !== 'undefined' && chrome.runtime?.getURL) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = chrome.runtime.getURL('content/side_panel.css');
    _shadow.appendChild(link);
  }

  const panel = document.createElement('div');
  panel.id = 'tailorer-panel';

  const header = document.createElement('div');
  header.className = 'tailorer-header';
  const title = document.createElement('span');
  title.className = 'tailorer-title';
  title.textContent = '⚡ Tailorer';
  const closeBtn = document.createElement('button');
  closeBtn.className = 'tailorer-close';
  closeBtn.textContent = '✕';
  closeBtn.addEventListener('click', closePanel);
  header.append(title, closeBtn);

  const statusBar = document.createElement('div');
  statusBar.id = 'tailorer-status';
  statusBar.className = 'tailorer-status';

  const logEl = document.createElement('div');
  logEl.id = 'tailorer-log';
  logEl.className = 'tailorer-log';

  panel.append(header, statusBar, logEl);
  _shadow.appendChild(panel);

  const toggle = document.createElement('button');
  toggle.id = 'tailorer-toggle';
  toggle.textContent = '⚡';
  toggle.style.display = 'none';
  toggle.addEventListener('click', openPanel);
  _shadow.appendChild(toggle);
}

function openPanel() {
  if (!_shadow) return;
  document.body.style.setProperty('margin-right', '320px', 'important');
  _shadow.getElementById('tailorer-panel').style.display = '';
  _shadow.getElementById('tailorer-toggle').style.display = 'none';
}

function closePanel() {
  if (!_shadow) return;
  document.body.style.removeProperty('margin-right');
  _shadow.getElementById('tailorer-panel').style.display = 'none';
  _shadow.getElementById('tailorer-toggle').style.display = '';
}

const STATUS_CONFIG = {
  connecting:    { text: 'Connecting…',        dot: true },
  navigating:    { text: 'Navigating…',         dot: true },
  filling:       { text: 'Filling form…',       dot: true },
  awaiting_user: { text: '⏸ Waiting for you',   dot: false, cls: 'amber' },
  show_stuck:    { text: '⚠ Action needed',     dot: false, cls: 'red' },
  done:          { text: '✓ Done',              dot: false, cls: 'green' },
  error:         { text: '✗ Error',             dot: false, cls: 'red' },
};

function setStatusBar(status) {
  if (!_shadow) return;
  const bar = _shadow.getElementById('tailorer-status');
  const cfg = STATUS_CONFIG[status] || { text: status, dot: true };
  bar.className = `tailorer-status tailorer-status--${cfg.cls || 'blue'}`;
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

function showStartButton(job_id, token) {
  if (!_shadow) return;
  const log = _shadow.getElementById('tailorer-log');
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
    if (typeof chrome !== 'undefined') {
      chrome.runtime.sendMessage({ type: 'start_session', job_id, token });
    }
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
  if (!_shadow) return;
  const log = _shadow.getElementById('tailorer-log');
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
      if (typeof chrome !== 'undefined') chrome.runtime.sendMessage({ type: 'user_correction', text });
      el.replaceWith(_makeStepEntry('Corrected', true));
    });

    const approveBtn = document.createElement('button');
    approveBtn.className = 'tailorer-btn tailorer-btn--approve';
    approveBtn.textContent = 'Looks good ✓';
    approveBtn.addEventListener('click', () => {
      if (typeof chrome !== 'undefined') chrome.runtime.sendMessage({ type: 'user_approved' });
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
      if (typeof chrome !== 'undefined') chrome.runtime.sendMessage({ type: 'stuck_unblocked' });
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
      const base = 'http://localhost:8000';
      const tok = encodeURIComponent(entry.token);
      const tid = encodeURIComponent(entry.thread_id);
      const downloads = document.createElement('div');
      downloads.className = 'tailorer-downloads';
      const cvLink = document.createElement('a');
      cvLink.className = 'tailorer-download-link';
      cvLink.href = `${base}/tailorer/files/${tid}/cv?token=${tok}`;
      cvLink.target = '_blank';
      cvLink.textContent = '↓ Tailored CV (.docx)';
      const clLink = document.createElement('a');
      clLink.className = 'tailorer-download-link';
      clLink.href = `${base}/tailorer/files/${tid}/cover_letter?token=${tok}`;
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
  if (!_shadow) return;
  const logEl = _shadow.getElementById('tailorer-log');
  logEl.innerHTML = '';
  for (const entry of log) appendLogEntry(entry);
  if (status) setStatusBar(status);
}

function ensurePanelInit() {
  if (!_shadow || !document.getElementById('tailorer-host')) initPanel();
}

if (typeof chrome !== 'undefined') {
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === 'show_apply_button') {
      ensurePanelInit();
      showStartButton(msg.job_id, msg.token);
      openPanel();
    } else if (msg.type === 'restore_panel') {
      ensurePanelInit();
      restorePanel(msg.log || [], msg.status);
      openPanel();
    } else if (msg.type === 'append_log') {
      appendLogEntry(msg.entry);
    } else if (msg.type === 'set_status') {
      setStatusBar(msg.status);
    }
  });
} else {
  globalThis.initPanel = initPanel;
  globalThis.openPanel = openPanel;
  globalThis.closePanel = closePanel;
  globalThis.showStartButton = showStartButton;
  globalThis.setStatusBar = setStatusBar;
  globalThis.appendLogEntry = appendLogEntry;
  globalThis.restorePanel = restorePanel;
}
