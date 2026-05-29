import '../content/overlay.js';
const { showApplyButton, showConfirmBanner, showStuckBanner, showDoneBanner, removeAllBanners } = globalThis;

beforeEach(() => {
  document.body.innerHTML = '';
  removeAllBanners();
});

test('showApplyButton injects button with correct data attribute', () => {
  showApplyButton('job-123', 'tok');
  const btn = document.getElementById('tailorer-apply-btn');
  expect(btn).not.toBeNull();
  expect(btn.dataset.jobId).toBe('job-123');
});

test('showConfirmBanner injects banner containing summary text', () => {
  showConfirmBanner('Filled 5 fields on page 1', ['salary']);
  const banner = document.getElementById('tailorer-confirm-banner');
  expect(banner).not.toBeNull();
  expect(banner.textContent).toContain('Filled 5 fields');
});

test('showConfirmBanner lists uncertain fields', () => {
  showConfirmBanner('Done', ['salary', 'notice_period']);
  expect(document.getElementById('tailorer-confirm-banner').textContent).toContain('salary');
});

test('showStuckBanner injects banner with message', () => {
  showStuckBanner("Can't find careers page");
  const banner = document.getElementById('tailorer-stuck-banner');
  expect(banner).not.toBeNull();
  expect(banner.textContent).toContain("Can't find");
});

test('showDoneBanner injects done banner', () => {
  showDoneBanner('Application submitted!');
  expect(document.getElementById('tailorer-done-banner')).not.toBeNull();
});

test('removeAllBanners removes all injected elements', () => {
  showApplyButton('job-1', 'tok');
  showConfirmBanner('Test', []);
  removeAllBanners();
  expect(document.getElementById('tailorer-apply-btn')).toBeNull();
  expect(document.getElementById('tailorer-confirm-banner')).toBeNull();
});

test('showApplyButton replaces existing apply button', () => {
  showApplyButton('job-1', 'tok');
  showApplyButton('job-2', 'tok');
  expect(document.querySelectorAll('#tailorer-apply-btn')).toHaveLength(1);
  expect(document.getElementById('tailorer-apply-btn').dataset.jobId).toBe('job-2');
});
