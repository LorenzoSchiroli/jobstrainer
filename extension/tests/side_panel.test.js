import '../content/side_panel.js';
const { initPanel, openPanel, closePanel } = globalThis;

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
