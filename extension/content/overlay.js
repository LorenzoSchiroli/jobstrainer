const BANNER_IDS = [
  'tailorer-apply-btn',
  'tailorer-confirm-banner',
  'tailorer-stuck-banner',
  'tailorer-done-banner',
];

function removeAllBanners() {
  BANNER_IDS.forEach((id) => document.getElementById(id)?.remove());
}

function showApplyButton(job_id, token) {
  document.getElementById('tailorer-apply-btn')?.remove();
  const btn = document.createElement('button');
  btn.id = 'tailorer-apply-btn';
  btn.className = 'tailorer-apply-btn';
  btn.textContent = '⚡ Apply with Agent';
  btn.dataset.jobId = job_id;
  btn.addEventListener('click', () => {
    btn.remove();
    if (typeof chrome !== 'undefined') {
      chrome.runtime.sendMessage({ type: 'start_session', job_id, token });
    }
  });
  document.body.appendChild(btn);
}

function showConfirmBanner(summary, uncertainFields) {
  document.getElementById('tailorer-confirm-banner')?.remove();

  const banner = document.createElement('div');
  banner.id = 'tailorer-confirm-banner';
  banner.className = 'tailorer-banner';

  const msg = document.createElement('span');
  msg.className = 'tailorer-banner__msg';
  msg.textContent = uncertainFields.length > 0
    ? `${summary} (uncertain: ${uncertainFields.join(', ')})`
    : summary;

  const approveBtn = document.createElement('button');
  approveBtn.className = 'tailorer-btn tailorer-btn--approve';
  approveBtn.textContent = 'Looks good, proceed';
  approveBtn.addEventListener('click', () => {
    banner.remove();
    if (typeof chrome !== 'undefined') {
      chrome.runtime.sendMessage({ type: 'user_approved' });
    }
  });

  const correctionInput = document.createElement('input');
  correctionInput.type = 'text';
  correctionInput.className = 'tailorer-correction-input';
  correctionInput.placeholder = 'Correct something? Type here and press Enter...';
  correctionInput.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    const text = correctionInput.value.trim();
    if (!text) return;
    banner.remove();
    if (typeof chrome !== 'undefined') {
      chrome.runtime.sendMessage({ type: 'user_correction', text });
    }
  });

  const correctBtn = document.createElement('button');
  correctBtn.className = 'tailorer-btn tailorer-btn--correct';
  correctBtn.textContent = 'Apply correction';
  correctBtn.addEventListener('click', () => {
    const text = correctionInput.value.trim();
    if (!text) return;
    banner.remove();
    if (typeof chrome !== 'undefined') {
      chrome.runtime.sendMessage({ type: 'user_correction', text });
    }
  });

  banner.append(msg, approveBtn, correctionInput, correctBtn);
  document.body.appendChild(banner);
}

function showStuckBanner(message) {
  document.getElementById('tailorer-stuck-banner')?.remove();

  const banner = document.createElement('div');
  banner.id = 'tailorer-stuck-banner';
  banner.className = 'tailorer-banner tailorer-banner--stuck';

  const msg = document.createElement('span');
  msg.className = 'tailorer-banner__msg';
  msg.textContent = `⚠ Agent stuck: ${message}`;

  const unblockBtn = document.createElement('button');
  unblockBtn.className = 'tailorer-btn tailorer-btn--unblock';
  unblockBtn.textContent = 'Done, continue';
  unblockBtn.addEventListener('click', () => {
    banner.remove();
    if (typeof chrome !== 'undefined') {
      chrome.runtime.sendMessage({ type: 'stuck_unblocked' });
    }
  });

  banner.append(msg, unblockBtn);
  document.body.appendChild(banner);
}

function showDoneBanner(message) {
  removeAllBanners();
  const banner = document.createElement('div');
  banner.id = 'tailorer-done-banner';
  banner.className = 'tailorer-banner tailorer-banner--done';
  banner.textContent = `✓ ${message}`;
  document.body.appendChild(banner);
  setTimeout(() => banner.remove(), 5000);
}

if (typeof chrome !== 'undefined') {
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === 'show_apply_button') showApplyButton(msg.job_id, msg.token);
    else if (msg.type === 'show_confirm') showConfirmBanner(msg.summary, msg.uncertain_fields || []);
    else if (msg.type === 'show_stuck') showStuckBanner(msg.message);
    else if (msg.type === 'done') showDoneBanner(msg.message);
  });
} else {
  globalThis.removeAllBanners = removeAllBanners;
  globalThis.showApplyButton = showApplyButton;
  globalThis.showConfirmBanner = showConfirmBanner;
  globalThis.showStuckBanner = showStuckBanner;
  globalThis.showDoneBanner = showDoneBanner;
}
