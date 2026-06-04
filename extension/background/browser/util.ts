export function isNewTabPage(url: string): boolean {
  return (
    url === 'chrome://newtab/' ||
    url === 'about:blank' ||
    url === 'about:newtab' ||
    url.startsWith('chrome://') ||
    url.startsWith('edge://')
  );
}

export function capTextLength(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return text.substring(0, maxLength) + '…';
}
