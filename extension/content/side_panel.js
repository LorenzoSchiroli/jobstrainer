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

if (typeof chrome !== 'undefined') {
  chrome.runtime.onMessage.addListener((_msg) => {});
} else {
  globalThis.initPanel = initPanel;
  globalThis.openPanel = openPanel;
  globalThis.closePanel = closePanel;
}
