// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { dirname } from 'path';

const __dirname_panel = dirname(dirname(new URL(import.meta.url).pathname));

function setupDOM() {
  document.body.innerHTML = '<div id="tailorer-log" class="tailorer-log"></div>';
}

function loadPanel() {
  const src = readFileSync(resolve(__dirname_panel, 'panel.js'), 'utf8');
  // eslint-disable-next-line no-new-func
  new Function(src)();
}

describe('panel bootstrap', () => {
  beforeEach(() => {
    globalThis.chrome = undefined;
    setupDOM();
    loadPanel();
  });

  it('exports setStatusBar globally when chrome is not present', () => {
    expect(typeof globalThis.setStatusBar).toBe('function');
  });
});
