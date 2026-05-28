if (!globalThis.CSS) globalThis.CSS = {};
if (!globalThis.CSS.escape) {
  globalThis.CSS.escape = (value) =>
    String(value).replace(/([!"#$%&'()*+,.\/:;<=>?@[\\\]^`{|}~])/g, '\\$1').replace(/^(\d)/, '\\3$1 ');
}
