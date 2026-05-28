export function resolveLabel(el) {
  if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();
  if (el.id) {
    const lbl = document.querySelector(`label[for="${el.id}"]`);
    if (lbl) return lbl.textContent.trim();
  }
  if (el.placeholder) return el.placeholder.trim();
  return '';
}

export function buildSnapshot() {
  let autoId = 0;
  const fields = [];

  document
    .querySelectorAll(
      'input:not([type="hidden"]):not([type="submit"]):not([type="button"])' +
      ':not([type="reset"]), select, textarea'
    )
    .forEach((el) => {
      if (!el.id) el.id = `field_${autoId++}`;
      const label = resolveLabel(el);
      const type = el.tagName === 'SELECT' ? 'select' : (el.type || 'text');

      if (type === 'file') {
        fields.push({ id: el.id, label, type: 'file' });
        return;
      }
      if (type === 'select') {
        fields.push({
          id: el.id,
          label,
          type: 'select',
          value: el.value,
          options: Array.from(el.options).map((o) => o.text),
        });
        return;
      }
      fields.push({ id: el.id, label, type, value: el.value });
    });

  const links = Array.from(document.querySelectorAll('a[href]')).map((a) => ({
    text: a.textContent.trim(),
    label: a.textContent.trim(),
    href: a.getAttribute('href'),
  }));

  const buttons = [];
  document.querySelectorAll('button, input[type="submit"]').forEach((btn, i) => {
    const label = btn.textContent?.trim() || btn.value?.trim() || '';
    if (!btn.id) btn.id = `btn_${i}`;
    buttons.push({ label, selector: `#${btn.id}` });
  });

  return {
    url: typeof location !== 'undefined' ? location.href : '',
    fields,
    links,
    buttons,
  };
}

// Respond to snapshot requests from the service worker
if (typeof chrome !== 'undefined') {
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type === 'request_snapshot') {
      sendResponse(buildSnapshot());
    }
  });
}
