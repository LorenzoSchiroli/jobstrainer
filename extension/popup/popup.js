const STATUS_LABELS = {
  connecting:    'Connecting...',
  navigating:    'Navigating...',
  filling:       'Filling form...',
  awaiting_user: 'Waiting for you ⏸',
  done:          'Done ✓',
  error:         'Error ✗',
  show_stuck:    'Stuck — action needed ⚠',
};

(async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) return;

  const tabId = tab.id;
  const stored = await chrome.storage.local.get([`status_${tabId}`, `session_${tabId}`]);
  const status = stored[`status_${tabId}`];
  const session = stored[`session_${tabId}`];

  const statusEl = document.getElementById('status');
  if (status) {
    statusEl.textContent = STATUS_LABELS[status] || status;
    statusEl.className = `st-${status}`;
  }

  if (status === 'done' && session?.thread_id && session?.token) {
    const base = 'http://localhost:8000';
    const tok = encodeURIComponent(session.token || '');
    const tid = encodeURIComponent(session.thread_id);
    document.getElementById('cv-link').href = `${base}/tailorer/files/${tid}/cv?token=${tok}`;
    document.getElementById('cl-link').href = `${base}/tailorer/files/${tid}/cover_letter?token=${tok}`;
    document.getElementById('files').style.display = 'block';
  }
})();
