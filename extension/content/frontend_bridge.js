// Injected on localhost:3000 to bridge job link clicks to the service worker.
// Uses window.postMessage because content scripts and page JS run in separate worlds.
window.addEventListener('message', (e) => {
  if (e.source !== window || e.data?.type !== 'tailorer_pending') return;
  try {
    const token = localStorage.getItem('access_token');
    if (!token) return;
    chrome.runtime.sendMessage({ type: 'register_pending', job_id: e.data.job_id, token });
  } catch (_) {}
});
