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
  }
  if (!el) return;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
}

if (typeof chrome !== 'undefined') {
  chrome.runtime.onMessage.addListener((_msg) => {});
} else {
  globalThis.initPanel = initPanel;
  globalThis.openPanel = openPanel;
  globalThis.closePanel = closePanel;
  globalThis.showStartButton = showStartButton;
  globalThis.setStatusBar = setStatusBar;
  globalThis.appendLogEntry = appendLogEntry;
}
