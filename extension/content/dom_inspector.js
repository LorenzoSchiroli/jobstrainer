function resolveLabel(el) {
  if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();
  if (el.id) {
    const lbl = document.querySelector(`label[for='${CSS.escape(el.id)}']`);
    if (lbl) return lbl.textContent.trim();
  }
  if (el.placeholder) return el.placeholder.trim();
  return '';
}

function buildSnapshot() {
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
      const type = el.tagName === 'SELECT' ? 'select'
                 : el.tagName === 'TEXTAREA' ? 'textarea'
                 : (el.type || 'text');

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
  let buttonId = 0;
  document.querySelectorAll('button, input[type="submit"]').forEach((btn) => {
    const label = btn.textContent?.trim() || btn.value?.trim() || '';
    if (!btn.id) btn.id = `btn_${buttonId++}`;
    buttons.push({ label, selector: `#${btn.id}` });
  });

  return {
    url: typeof location !== 'undefined' ? location.href : '',
    fields,
    links,
    buttons,
  };
}

if (typeof chrome !== 'undefined') {
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type === 'request_snapshot') {
      sendResponse(buildSnapshot());
    }
  });
} else {
  // Test environment (Jest/jsdom): expose functions via globalThis
  globalThis.resolveLabel = resolveLabel;
  globalThis.buildSnapshot = buildSnapshot;
}
