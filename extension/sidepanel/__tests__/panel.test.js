// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
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

const PANEL_GLOBALS = ['setStatusBar', 'showIdleState', 'showStartButton', 'appendLogEntry', 'restorePanel', '_handleMessage'];

afterEach(() => {
  PANEL_GLOBALS.forEach(k => { delete globalThis[k]; });
  delete globalThis.__testPort;
});

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
