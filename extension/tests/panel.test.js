import '../sidepanel/panel.js';
const { setStatusBar, showIdleState, showStartButton, appendLogEntry, restorePanel } = globalThis;

beforeEach(() => {
  document.body.innerHTML = `
    <div id="tailorer-panel">
      <div class="tailorer-header"><span class="tailorer-title">⚡ Tailorer</span></div>
      <div id="tailorer-status" class="tailorer-status tailorer-status--blue"></div>
      <div id="tailorer-log" class="tailorer-log"></div>
    </div>
  `;
});

afterEach(() => {
  delete globalThis.__testPort;
});

test('setStatusBar updates text', () => {
  setStatusBar('navigating');
  expect(document.getElementById('tailorer-status').textContent).toContain('Navigating');
});

test('setStatusBar sets amber class for awaiting_user', () => {
  setStatusBar('awaiting_user');
  expect(document.getElementById('tailorer-status').className).toContain('tailorer-status--amber');
});

test('showIdleState renders idle message', () => {
  showIdleState();
  expect(document.querySelector('.tailorer-idle')).not.toBeNull();
});

test('showStartButton renders Start Agent button', () => {
  showStartButton('job-1', 'tok-1');
  expect(document.querySelector('.tailorer-btn--start')).not.toBeNull();
  expect(document.querySelector('.tailorer-btn--start').textContent).toContain('Start Agent');
});

test('showStartButton click sends start_session via port', () => {
  globalThis.__testPort = { postMessage: jest.fn() };
  showStartButton('job-42', 'tok-abc');
  document.querySelector('.tailorer-btn--start').click();
  expect(globalThis.__testPort.postMessage).toHaveBeenCalledWith({
    type: 'start_session', job_id: 'job-42', token: 'tok-abc',
  });
});

test('appendLogEntry done=true renders ✓ entry', () => {
  appendLogEntry({ kind: 'step', text: 'Filled name', done: true });
  const entry = document.querySelector('.tailorer-entry--done');
  expect(entry).not.toBeNull();
  expect(entry.textContent).toContain('Filled name');
  expect(entry.textContent).toContain('✓');
});

test('appendLogEntry done=false renders ⟳ entry', () => {
  appendLogEntry({ kind: 'step', text: 'Navigating…', done: false });
  const entry = document.querySelector('.tailorer-entry--pending');
  expect(entry).not.toBeNull();
  expect(entry.textContent).toContain('Navigating');
});

test('multiple appendLogEntry calls grow the log in order', () => {
  appendLogEntry({ kind: 'step', text: 'Step 1', done: true });
  appendLogEntry({ kind: 'step', text: 'Step 2', done: true });
  const entries = document.querySelectorAll('.tailorer-entry');
  expect(entries).toHaveLength(2);
  expect(entries[0].textContent).toContain('Step 1');
  expect(entries[1].textContent).toContain('Step 2');
});

test('appendLogEntry confirm renders summary and approve button', () => {
  appendLogEntry({ kind: 'confirm', summary: 'Filled 3 fields', uncertain_fields: ['salary'] });
  const block = document.querySelector('.tailorer-confirm-block');
  expect(block).not.toBeNull();
  expect(block.textContent).toContain('Filled 3 fields');
  expect(block.textContent).toContain('salary');
  expect(block.querySelector('.tailorer-btn--approve')).not.toBeNull();
});

test('appendLogEntry confirm — approve sends user_approved via port', () => {
  globalThis.__testPort = { postMessage: jest.fn() };
  appendLogEntry({ kind: 'confirm', summary: 'Test', uncertain_fields: [] });
  document.querySelector('.tailorer-btn--approve').click();
  expect(globalThis.__testPort.postMessage).toHaveBeenCalledWith({ type: 'user_approved' });
  expect(document.querySelector('.tailorer-confirm-block')).toBeNull();
});

test('appendLogEntry confirm — correction sends user_correction on Enter', () => {
  globalThis.__testPort = { postMessage: jest.fn() };
  appendLogEntry({ kind: 'confirm', summary: 'Test', uncertain_fields: [] });
  const input = document.querySelector('.tailorer-correction-input');
  input.value = 'use remote instead';
  input.dispatchEvent(Object.assign(new Event('keydown'), { key: 'Enter' }));
  expect(globalThis.__testPort.postMessage).toHaveBeenCalledWith({
    type: 'user_correction', text: 'use remote instead',
  });
});

test('appendLogEntry stuck renders message and unblock button', () => {
  appendLogEntry({ kind: 'stuck', message: 'Cannot find apply link' });
  const block = document.querySelector('.tailorer-stuck-block');
  expect(block).not.toBeNull();
  expect(block.textContent).toContain('Cannot find apply link');
  expect(block.querySelector('.tailorer-btn--unblock')).not.toBeNull();
});

test('appendLogEntry stuck — unblock sends stuck_unblocked via port', () => {
  globalThis.__testPort = { postMessage: jest.fn() };
  appendLogEntry({ kind: 'stuck', message: 'Test' });
  document.querySelector('.tailorer-btn--unblock').click();
  expect(globalThis.__testPort.postMessage).toHaveBeenCalledWith({ type: 'stuck_unblocked' });
  expect(document.querySelector('.tailorer-stuck-block')).toBeNull();
});

test('appendLogEntry done renders done entry and download links', () => {
  appendLogEntry({ kind: 'done', message: 'Application submitted!', thread_id: 'tid-1', token: 'tok-abc' });
  const entry = document.querySelector('.tailorer-entry--done-final');
  expect(entry).not.toBeNull();
  expect(entry.textContent).toContain('Application submitted!');
  const links = document.querySelectorAll('.tailorer-download-link');
  expect(links).toHaveLength(2);
  expect(links[0].href).toContain('tid-1');
  expect(links[0].href).toContain('tok-abc');
});

test('appendLogEntry error renders error entry', () => {
  appendLogEntry({ kind: 'error', message: 'WebSocket failed' });
  const entry = document.querySelector('.tailorer-entry--error');
  expect(entry).not.toBeNull();
  expect(entry.textContent).toContain('WebSocket failed');
});

test('restorePanel re-renders all entries in order', () => {
  restorePanel([
    { kind: 'step', text: 'Step 1', done: true },
    { kind: 'step', text: 'Step 2', done: false },
  ], 'navigating');
  const entries = document.querySelectorAll('.tailorer-entry');
  expect(entries).toHaveLength(2);
  expect(entries[0].textContent).toContain('Step 1');
  expect(entries[1].textContent).toContain('Step 2');
});

test('restorePanel clears previous entries', () => {
  appendLogEntry({ kind: 'step', text: 'Old', done: true });
  restorePanel([{ kind: 'step', text: 'New', done: true }], 'navigating');
  const entries = document.querySelectorAll('.tailorer-entry');
  expect(entries).toHaveLength(1);
  expect(entries[0].textContent).toContain('New');
});
