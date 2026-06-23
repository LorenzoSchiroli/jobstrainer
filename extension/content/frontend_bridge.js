// Injected on the jobstrainer frontend to capture the selected job + auth token.
// Content scripts share chrome.storage with the rest of the extension, so we write
// the job directly to storage (no service-worker round-trip — the SW may be asleep
// or its message handler unregistered). The panel reads `activeJob` from storage.
//
// Diagnostic keys (read by the panel debug strip):
//   bridgeLoadedAt  — proves this content script was injected on the page
//   lastBridgeEvent — the most recent tailorer_pending click + whether a token was found

try {
  chrome.storage?.local?.set({ bridgeLoadedAt: Date.now() });
} catch (_) {}

window.addEventListener('message', (e) => {
  if (e.source !== window || e.data?.type !== 'tailorer_pending') return;
  try {
    const token = localStorage.getItem('access_token');
    chrome.storage.local.set({
      activeJob: token ? { job_id: e.data.job_id, token } : null,
      lastBridgeEvent: { job_id: e.data.job_id, hadToken: !!token, at: Date.now() },
    });
    // Best-effort: also notify the SW so it can auto-open the side panel.
    chrome.runtime.sendMessage({ type: 'register_pending', job_id: e.data.job_id, token });
  } catch (err) {
    try { chrome.storage?.local?.set({ bridgeError: String(err) }); } catch (_) {}
  }
});
