// Expose jest as a globalThis property for ESM test files
// (--experimental-vm-modules does not inject jest into module scope automatically)
import { jest as _jest } from '@jest/globals';
globalThis.jest = _jest;

if (!globalThis.CSS) globalThis.CSS = {};
if (!globalThis.CSS.escape) {
  globalThis.CSS.escape = (value) =>
    String(value).replace(/([!"#$%&'()*+,.\/:;<=>?@[\\\]^`{|}~])/g, '\\$1').replace(/^(\d)/, '\\3$1 ');
}

if (!HTMLElement.prototype.attachShadow) {
  HTMLElement.prototype.attachShadow = function () {
    const shadow = document.createElement('div');
    shadow.__isShadowRoot = true;
    this.appendChild(shadow);
    Object.defineProperty(this, 'shadowRoot', { get: () => shadow, configurable: true });
    // Forward getElementById/querySelector to shadow root
    shadow.getElementById = (id) => shadow.querySelector(`#${id}`);
    return shadow;
  };
}
