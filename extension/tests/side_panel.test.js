import '../content/side_panel.js';
const { initPanel, openPanel, closePanel, showStartButton, setStatusBar, appendLogEntry, restorePanel } = globalThis;

beforeEach(() => {
  document.body.innerHTML = '';
  document.body.style.removeProperty('margin-right');
  initPanel();
});

afterEach(() => {
  delete globalThis.chrome;
});

test('initPanel appends tailorer-host to body', () => {
  expect(document.getElementById('tailorer-host')).not.toBeNull();
});

test('initPanel creates shadow root with panel element', () => {
  const host = document.getElementById('tailorer-host');
  expect(host.shadowRoot).not.toBeNull();
  expect(host.shadowRoot.getElementById('tailorer-panel')).not.toBeNull();
});

test('openPanel sets margin-right 320px on body', () => {
  openPanel();
  expect(document.body.style.marginRight).toBe('320px');
});

test('openPanel shows the panel and hides the toggle tab', () => {
  openPanel();
  const host = document.getElementById('tailorer-host');
  const panel = host.shadowRoot.getElementById('tailorer-panel');
  const toggle = host.shadowRoot.getElementById('tailorer-toggle');
  expect(panel.style.display).not.toBe('none');
  expect(toggle.style.display).toBe('none');
});

test('closePanel removes margin-right from body', () => {
  openPanel();
  closePanel();
  expect(document.body.style.marginRight).toBe('');
});

test('closePanel hides the panel and shows the toggle tab', () => {
  openPanel();
  closePanel();
  const host = document.getElementById('tailorer-host');
  const panel = host.shadowRoot.getElementById('tailorer-panel');
  const toggle = host.shadowRoot.getElementById('tailorer-toggle');
  expect(panel.style.display).toBe('none');
  expect(toggle.style.display).not.toBe('none');
});

test('clicking close button calls closePanel', () => {
  openPanel();
  const host = document.getElementById('tailorer-host');
  host.shadowRoot.querySelector('.tailorer-close').click();
  expect(document.body.style.marginRight).toBe('');
});

test('clicking toggle tab calls openPanel', () => {
  openPanel();
  closePanel();
  const host = document.getElementById('tailorer-host');
  host.shadowRoot.getElementById('tailorer-toggle').click();
  expect(document.body.style.marginRight).toBe('320px');
});

test('initPanel is idempotent — second call replaces the first host', () => {
  initPanel(); // second call
  expect(document.querySelectorAll('#tailorer-host')).toHaveLength(1);
});

test('showStartButton renders a Start Agent button', () => {
  const host = document.getElementById('tailorer-host');
  showStartButton('job-42', 'tok123');
  const btn = host.shadowRoot.querySelector('.tailorer-btn--start');
  expect(btn).not.toBeNull();
  expect(btn.textContent).toContain('Start Agent');
});

test('showStartButton clicking sends start_session and clears the button', () => {
  globalThis.chrome = { runtime: { sendMessage: jest.fn() } };
  const host = document.getElementById('tailorer-host');
  showStartButton('job-42', 'tok123');
  host.shadowRoot.querySelector('.tailorer-btn--start').click();
  expect(globalThis.chrome.runtime.sendMessage).toHaveBeenCalledWith({
    type: 'start_session', job_id: 'job-42', token: 'tok123',
  });
  expect(host.shadowRoot.querySelector('.tailorer-btn--start')).toBeNull();
});

test('setStatusBar updates status text', () => {
  setStatusBar('navigating');
  const bar = document.getElementById('tailorer-host').shadowRoot.getElementById('tailorer-status');
  expect(bar.textContent).toContain('Navigating');
});

test('appendLogEntry done=true renders ✓ entry', () => {
  const host = document.getElementById('tailorer-host');
  appendLogEntry({ kind: 'step', text: 'Filled name', done: true });
  const entry = host.shadowRoot.querySelector('.tailorer-entry--done');
  expect(entry).not.toBeNull();
  expect(entry.textContent).toContain('Filled name');
  expect(entry.textContent).toContain('✓');
});

test('appendLogEntry done=false renders ⟳ entry', () => {
  const host = document.getElementById('tailorer-host');
  appendLogEntry({ kind: 'step', text: 'Navigating…', done: false });
  const entry = host.shadowRoot.querySelector('.tailorer-entry--pending');
  expect(entry).not.toBeNull();
  expect(entry.textContent).toContain('Navigating');
});

test('multiple appendLogEntry calls grow the log in order', () => {
  const host = document.getElementById('tailorer-host');
  appendLogEntry({ kind: 'step', text: 'Step 1', done: true });
  appendLogEntry({ kind: 'step', text: 'Step 2', done: true });
  const entries = host.shadowRoot.querySelectorAll('.tailorer-entry');
  expect(entries).toHaveLength(2);
  expect(entries[0].textContent).toContain('Step 1');
  expect(entries[1].textContent).toContain('Step 2');
});

test('appendLogEntry confirm renders summary and approve button', () => {
  const host = document.getElementById('tailorer-host');
  appendLogEntry({ kind: 'confirm', summary: 'Filled 3 fields', uncertain_fields: ['salary'] });
  const block = host.shadowRoot.querySelector('.tailorer-confirm-block');
  expect(block).not.toBeNull();
  expect(block.textContent).toContain('Filled 3 fields');
  expect(block.textContent).toContain('salary');
  expect(block.querySelector('.tailorer-btn--approve')).not.toBeNull();
});

test('appendLogEntry confirm — approve button sends user_approved', () => {
  globalThis.chrome = { runtime: { sendMessage: jest.fn() } };
  const host = document.getElementById('tailorer-host');
  appendLogEntry({ kind: 'confirm', summary: 'Test', uncertain_fields: [] });
  host.shadowRoot.querySelector('.tailorer-btn--approve').click();
  expect(globalThis.chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: 'user_approved' });
  expect(host.shadowRoot.querySelector('.tailorer-confirm-block')).toBeNull();
});

test('appendLogEntry confirm — correction input sends user_correction on Enter', () => {
  globalThis.chrome = { runtime: { sendMessage: jest.fn() } };
  const host = document.getElementById('tailorer-host');
  appendLogEntry({ kind: 'confirm', summary: 'Test', uncertain_fields: [] });
  const input = host.shadowRoot.querySelector('.tailorer-correction-input');
  input.value = 'use remote instead';
  input.dispatchEvent(Object.assign(new Event('keydown'), { key: 'Enter' }));
  expect(globalThis.chrome.runtime.sendMessage).toHaveBeenCalledWith({
    type: 'user_correction', text: 'use remote instead',
  });
});

test('appendLogEntry stuck renders message and unblock button', () => {
  const host = document.getElementById('tailorer-host');
  appendLogEntry({ kind: 'stuck', message: 'Cannot find apply link' });
  const block = host.shadowRoot.querySelector('.tailorer-stuck-block');
  expect(block).not.toBeNull();
  expect(block.textContent).toContain('Cannot find apply link');
  expect(block.querySelector('.tailorer-btn--unblock')).not.toBeNull();
});

test('appendLogEntry stuck — unblock button sends stuck_unblocked', () => {
  globalThis.chrome = { runtime: { sendMessage: jest.fn() } };
  const host = document.getElementById('tailorer-host');
  appendLogEntry({ kind: 'stuck', message: 'Test' });
  host.shadowRoot.querySelector('.tailorer-btn--unblock').click();
  expect(globalThis.chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: 'stuck_unblocked' });
  expect(host.shadowRoot.querySelector('.tailorer-stuck-block')).toBeNull();
});

test('appendLogEntry done renders done entry and download links', () => {
  const host = document.getElementById('tailorer-host');
  appendLogEntry({
    kind: 'done', message: 'Application submitted!',
    thread_id: 'tid-1', token: 'tok-abc',
  });
  const entry = host.shadowRoot.querySelector('.tailorer-entry--done-final');
  expect(entry).not.toBeNull();
  expect(entry.textContent).toContain('Application submitted!');
  const links = host.shadowRoot.querySelectorAll('.tailorer-download-link');
  expect(links).toHaveLength(2);
  expect(links[0].href).toContain('tid-1');
  expect(links[0].href).toContain('tok-abc');
});

test('appendLogEntry error renders error entry', () => {
  const host = document.getElementById('tailorer-host');
  appendLogEntry({ kind: 'error', message: 'WebSocket failed' });
  const entry = host.shadowRoot.querySelector('.tailorer-entry--error');
  expect(entry).not.toBeNull();
  expect(entry.textContent).toContain('WebSocket failed');
});

test('restorePanel re-renders all entries in order', () => {
  const host = document.getElementById('tailorer-host');
  restorePanel([
    { kind: 'step', text: 'Step 1', done: true },
    { kind: 'step', text: 'Step 2', done: false },
  ], 'navigating');
  const entries = host.shadowRoot.querySelectorAll('.tailorer-entry');
  expect(entries).toHaveLength(2);
  expect(entries[0].textContent).toContain('Step 1');
  expect(entries[1].textContent).toContain('Step 2');
});

test('restorePanel clears previous entries before re-rendering', () => {
  const host = document.getElementById('tailorer-host');
  appendLogEntry({ kind: 'step', text: 'Old', done: true });
  restorePanel([{ kind: 'step', text: 'New', done: true }], 'navigating');
  const entries = host.shadowRoot.querySelectorAll('.tailorer-entry');
  expect(entries).toHaveLength(1);
  expect(entries[0].textContent).toContain('New');
});

test('show_apply_button message initialises and opens panel with start button', () => {
  // simulate chrome message dispatch manually
  const { initPanel: init, showStartButton: ssb, openPanel: op } = globalThis;
  // Call the same code path the listener would: init + showStartButton + open
  init();
  ssb('job-5', 'tok-5');
  op();
  const host = document.getElementById('tailorer-host');
  expect(host.shadowRoot.querySelector('.tailorer-btn--start')).not.toBeNull();
  expect(document.body.style.marginRight).toBe('320px');
});

test('restore_panel message re-renders log and opens panel', () => {
  const { initPanel: init, restorePanel: rp, openPanel: op } = globalThis;
  init();
  rp([{ kind: 'step', text: 'Resumed', done: true }], 'navigating');
  op();
  const host = document.getElementById('tailorer-host');
  expect(host.shadowRoot.querySelector('.tailorer-entry--done')).not.toBeNull();
  expect(host.shadowRoot.querySelector('.tailorer-entry--done').textContent).toContain('Resumed');
});
