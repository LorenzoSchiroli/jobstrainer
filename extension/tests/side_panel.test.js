import '../content/side_panel.js';
const { initPanel, openPanel, closePanel, showStartButton, setStatusBar, appendLogEntry } = globalThis;

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
