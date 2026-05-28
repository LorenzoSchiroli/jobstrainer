export function fillField(fieldId, value) {
  const el = document.getElementById(fieldId);
  if (!el) return;

  if (el.tagName === 'SELECT') {
    const match = Array.from(el.options).find((o) => o.text === value || o.value === value);
    if (match) el.value = match.value;
  } else {
    // Use native setter so React's synthetic event system detects the change
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    if (setter) setter.call(el, value);
    else el.value = value;
  }

  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

export function clickElement(selector) {
  document.querySelector(selector)?.click();
}

export function setFileOnInput(fieldId, filename, buffer) {
  const el = document.getElementById(fieldId);
  if (!el || el.type !== 'file') return;
  const file = new File([buffer], filename, {
    type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  });
  const dt = new DataTransfer();
  dt.items.add(file);
  el.files = dt.files;
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

const SUBMIT_KEYWORDS = ['submit', 'apply', 'send application', 'complete'];
const NEXT_KEYWORDS = ['next', 'continue', 'proceed', 'save'];

export function clickNextOrSubmit() {
  const buttons = Array.from(
    document.querySelectorAll('button, input[type="submit"]')
  );

  const submitBtn = buttons.find((b) => {
    const text = (b.textContent || b.value || '').toLowerCase();
    return SUBMIT_KEYWORDS.some((kw) => text.includes(kw));
  });
  if (submitBtn) {
    submitBtn.click();
    return { submitted: true };
  }

  const nextBtn = buttons.find((b) => {
    const text = (b.textContent || b.value || '').toLowerCase();
    return NEXT_KEYWORDS.some((kw) => text.includes(kw));
  });
  if (nextBtn) {
    nextBtn.click();
    return { submitted: false };
  }

  // Fallback: click first form button
  const fallback = buttons[0];
  if (fallback) {
    fallback.click();
    return { submitted: false };
  }

  return { submitted: false };
}

// Listen for commands from service worker
if (typeof chrome !== 'undefined') {
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type === 'fill_field') {
      fillField(msg.field_id, msg.value);
    } else if (msg.type === 'click') {
      clickElement(msg.selector);
    } else if (msg.type === 'do_file_upload') {
      setFileOnInput(msg.field_id, msg.filename, msg.buffer);
    } else if (msg.type === 'navigate_next') {
      sendResponse(clickNextOrSubmit());
      return true;
    }
  });
}
