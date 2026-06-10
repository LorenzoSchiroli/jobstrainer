/**
 * Waits for webNavigation.onCompleted on the main frame.
 * Must be called BEFORE the action that triggers navigation to avoid missing fast navigations.
 */
export function waitForNavCompleted(tabId: number, timeoutMs = 8000): Promise<void> {
  return new Promise(resolve => {
    const onCompleted = (details: { tabId: number; frameId: number }) => {
      if (details.tabId !== tabId || details.frameId !== 0) return;
      chrome.webNavigation.onCompleted.removeListener(onCompleted as any);
      resolve();
    };
    chrome.webNavigation.onCompleted.addListener(onCompleted as any);
    setTimeout(() => {
      chrome.webNavigation.onCompleted.removeListener(onCompleted as any);
      resolve();
    }, timeoutMs);
  });
}

/**
 * Clicks an element and detects whether a full or SPA navigation was committed.
 * Registers webNavigation listeners BEFORE the click so fast navigations are never missed.
 * Returns true if the page navigated, false if the DOM changed in-place only.
 */
export async function clickAndDetectNavigation(
  tabId: number,
  clickFn: () => Promise<void>,
): Promise<boolean> {
  let committed = false;
  let resolveCommit!: () => void;
  let resolveComplete!: () => void;

  const commitPromise = new Promise<void>(r => { resolveCommit = r; });
  const completePromise = new Promise<void>(r => { resolveComplete = r; });

  const cleanup = () => {
    chrome.webNavigation.onCommitted.removeListener(onCommitted as any);
    chrome.webNavigation.onCompleted.removeListener(onCompleted as any);
    chrome.webNavigation.onHistoryStateUpdated.removeListener(onHistoryStateUpdated as any);
  };

  const onCommitted = (details: { tabId: number; frameId: number }) => {
    if (details.tabId !== tabId || details.frameId !== 0) return;
    committed = true;
    chrome.webNavigation.onCommitted.removeListener(onCommitted as any);
    resolveCommit();
  };
  const onCompleted = (details: { tabId: number; frameId: number }) => {
    if (details.tabId !== tabId || details.frameId !== 0) return;
    chrome.webNavigation.onCompleted.removeListener(onCompleted as any);
    resolveComplete();
  };
  // SPA route change via history.pushState/replaceState — treat as both committed and complete.
  const onHistoryStateUpdated = (details: { tabId: number; frameId: number }) => {
    if (details.tabId !== tabId || details.frameId !== 0) return;
    committed = true;
    chrome.webNavigation.onHistoryStateUpdated.removeListener(onHistoryStateUpdated as any);
    resolveCommit();
    resolveComplete();
  };

  chrome.webNavigation.onCommitted.addListener(onCommitted as any);
  chrome.webNavigation.onCompleted.addListener(onCompleted as any);
  chrome.webNavigation.onHistoryStateUpdated.addListener(onHistoryStateUpdated as any);

  await clickFn();

  const didCommit = await Promise.race([
    commitPromise.then(() => true as boolean),
    new Promise<boolean>(r => setTimeout(() => r(false), 1000)),
  ]);

  if (!didCommit) {
    cleanup();
    return false;
  }

  await Promise.race([
    completePromise,
    new Promise<void>(r => setTimeout(r, 8000)),
  ]);
  cleanup();
  return true;
}
