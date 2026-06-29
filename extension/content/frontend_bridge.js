// Runs only on the jobstrainer frontend (localhost:3000). It is the single bridge
// between the web app and the extension: it writes the user's auth token and the
// selected job to chrome.storage.local, which the side panel treats as the one
// source of truth for "which user / which job."
//
// Content scripts share the page's origin, so they can read the page's
// localStorage directly — no service-worker round-trip (the SW may be asleep).

function currentToken() {
  try {
    return localStorage.getItem('access_token');
  } catch (_) {
    return null;
  }
}

// Keep the stored token fresh whenever the user has the app open (login, refresh).
const token = currentToken();
if (token) {
  try { chrome.storage.local.set({ token }); } catch (_) {}
}

// Job selection: the app posts { type: 'tailorer_link', job_id, job_title }.
window.addEventListener('message', (e) => {
  if (e.source !== window || e.data?.type !== 'tailorer_link') return;
  try {
    chrome.storage.local.set({
      token: currentToken(),
      activeJob: { job_id: e.data.job_id, job_title: e.data.job_title ?? '' },
    });
  } catch (_) {}
});
