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

const PANEL_GLOBALS = ['setStatusBar', 'setStopButton', 'setInputArea', 'showIdleState', 'showStartButton', 'appendLogEntry', 'restorePanel', '_handleMessage'];

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

describe('appendLogEntry — no setStatusBar side effects', () => {
  beforeEach(() => {
    globalThis.chrome = undefined;
    setupDOM();
    loadPanel();
  });

  it('confirm entry does NOT call setStatusBar (status driven by set_status message)', () => {
    globalThis.setStatusBar('navigating');
    const barText = document.getElementById('tailorer-status')?.textContent;
    globalThis.appendLogEntry({ kind: 'confirm', summary: 'Fill form', uncertain_fields: [], file_links: [] });
    expect(document.getElementById('tailorer-status')?.textContent).toBe(barText);
  });

  it('stuck entry does NOT call setStatusBar', () => {
    globalThis.setStatusBar('navigating');
    const barText = document.getElementById('tailorer-status')?.textContent;
    globalThis.appendLogEntry({ kind: 'stuck', message: 'Need help' });
    expect(document.getElementById('tailorer-status')?.textContent).toBe(barText);
  });

  it('done entry does NOT call setStatusBar', () => {
    globalThis.setStatusBar('navigating');
    const barText = document.getElementById('tailorer-status')?.textContent;
    globalThis.appendLogEntry({ kind: 'done', message: 'All done', thread_id: 't1', token: 'tok' });
    expect(document.getElementById('tailorer-status')?.textContent).toBe(barText);
  });

  it('error entry does NOT call setStatusBar', () => {
    globalThis.setStatusBar('navigating');
    const barText = document.getElementById('tailorer-status')?.textContent;
    globalThis.appendLogEntry({ kind: 'error', message: 'Oops' });
    expect(document.getElementById('tailorer-status')?.textContent).toBe(barText);
  });
});

describe('appendLogEntry confirm card — correction row always visible', () => {
  beforeEach(() => {
    globalThis.chrome = undefined;
    setupDOM();
    loadPanel();
  });

  it('renders correction input visible by default (no display:none)', () => {
    globalThis.appendLogEntry({ kind: 'confirm', summary: 'Fill form', uncertain_fields: [], file_links: [] });
    const row = document.querySelector('.tailorer-correction-row');
    expect(row).not.toBeNull();
    expect(row.style.display).not.toBe('none');
  });
});

describe('optimistic handlers — setStatusBar navigating', () => {
  beforeEach(() => {
    globalThis.chrome = undefined;
    setupDOM();
    loadPanel();
    globalThis.__testPort = { postMessage: vi.fn() };
    globalThis.setStatusBar('awaiting_user');
  });

  it('approve button calls setStatusBar("navigating")', () => {
    globalThis.appendLogEntry({ kind: 'confirm', summary: 'Fill form', uncertain_fields: [], file_links: [] });
    const barText = document.getElementById('tailorer-status')?.textContent;
    document.querySelector('.tailorer-btn--approve').click();
    expect(document.getElementById('tailorer-status')?.textContent).not.toBe(barText);
    expect(document.getElementById('tailorer-status')?.textContent).toContain('Navigating');
  });

  it('unblock button calls setStatusBar("navigating")', () => {
    globalThis.setStatusBar('show_stuck');
    globalThis.appendLogEntry({ kind: 'stuck', message: 'Need help' });
    const barText = document.getElementById('tailorer-status')?.textContent;
    document.querySelector('.tailorer-btn--unblock').click();
    expect(document.getElementById('tailorer-status')?.textContent).not.toBe(barText);
    expect(document.getElementById('tailorer-status')?.textContent).toContain('Navigating');
  });

  it('correction Enter calls setStatusBar("navigating")', () => {
    globalThis.appendLogEntry({ kind: 'confirm', summary: 'Fill form', uncertain_fields: [], file_links: [] });
    const barText = document.getElementById('tailorer-status')?.textContent;
    const input = document.querySelector('.tailorer-correction-input');
    input.value = 'fix this';
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(document.getElementById('tailorer-status')?.textContent).not.toBe(barText);
    expect(document.getElementById('tailorer-status')?.textContent).toContain('Navigating');
  });
});

describe('appendLogEntry done/error — disables stale confirm/stuck cards', () => {
  beforeEach(() => {
    globalThis.chrome = undefined;
    setupDOM();
    loadPanel();
    globalThis.__testPort = { postMessage: vi.fn() };
  });

  it('done entry disables buttons in pre-existing confirm blocks', () => {
    globalThis.appendLogEntry({ kind: 'confirm', summary: 'Fill form', uncertain_fields: [], file_links: [] });
    globalThis.appendLogEntry({ kind: 'done', message: 'All done', thread_id: 't1', token: 'tok' });
    const btns = document.querySelectorAll('.tailorer-confirm-block button');
    btns.forEach(btn => expect(btn.disabled).toBe(true));
  });

  it('done entry disables inputs in pre-existing confirm blocks', () => {
    globalThis.appendLogEntry({ kind: 'confirm', summary: 'Fill form', uncertain_fields: [], file_links: [] });
    globalThis.appendLogEntry({ kind: 'done', message: 'All done', thread_id: 't1', token: 'tok' });
    const inputs = document.querySelectorAll('.tailorer-confirm-block input');
    inputs.forEach(inp => expect(inp.disabled).toBe(true));
  });

  it('error entry disables buttons in pre-existing stuck blocks', () => {
    globalThis.appendLogEntry({ kind: 'stuck', message: 'Stuck here' });
    globalThis.appendLogEntry({ kind: 'error', message: 'Failed' });
    const btns = document.querySelectorAll('.tailorer-stuck-block button');
    btns.forEach(btn => expect(btn.disabled).toBe(true));
  });

  it('error entry disables buttons in pre-existing confirm blocks', () => {
    globalThis.appendLogEntry({ kind: 'confirm', summary: 'Fill form', uncertain_fields: [], file_links: [] });
    globalThis.appendLogEntry({ kind: 'error', message: 'Failed' });
    const btns = document.querySelectorAll('.tailorer-confirm-block button');
    btns.forEach(btn => expect(btn.disabled).toBe(true));
  });
});

describe('appendLogEntry done/error — clears pending spinners', () => {
  beforeEach(() => {
    globalThis.chrome = undefined;
    setupDOM();
    loadPanel();
  });

  it('done entry removes tailorer-entry--pending class from all pending steps', () => {
    globalThis.appendLogEntry({ kind: 'step', text: 'Submitting page…', done: false });
    globalThis.appendLogEntry({ kind: 'done', message: 'All done', thread_id: 't1', token: 'tok' });
    const pending = document.querySelectorAll('.tailorer-entry--pending');
    expect(pending.length).toBe(0);
  });

  it('done entry adds tailorer-entry--done to formerly-pending steps', () => {
    globalThis.appendLogEntry({ kind: 'step', text: 'Submitting page…', done: false });
    globalThis.appendLogEntry({ kind: 'done', message: 'All done', thread_id: 't1', token: 'tok' });
    const steps = document.querySelectorAll('.tailorer-entry--done');
    expect(steps.length).toBeGreaterThanOrEqual(1);
  });

  it('error entry clears pending spinners', () => {
    globalThis.appendLogEntry({ kind: 'step', text: 'Submitting page…', done: false });
    globalThis.appendLogEntry({ kind: 'error', message: 'Failed' });
    const pending = document.querySelectorAll('.tailorer-entry--pending');
    expect(pending.length).toBe(0);
  });
});

describe('optimistic handlers — send append_optimistic_log', () => {
  beforeEach(() => {
    globalThis.chrome = undefined;
    setupDOM();
    loadPanel();
    globalThis.__testPort = { postMessage: vi.fn() };
    globalThis.setStatusBar('awaiting_user');
  });

  it('approve button sends append_optimistic_log with Confirmed step', () => {
    globalThis.appendLogEntry({ kind: 'confirm', summary: 'Fill form', uncertain_fields: [], file_links: [] });
    document.querySelector('.tailorer-btn--approve').click();
    const calls = globalThis.__testPort.postMessage.mock.calls;
    const optimisticCall = calls.find(([msg]) => msg.type === 'append_optimistic_log');
    expect(optimisticCall).toBeDefined();
    expect(optimisticCall[0].entry).toMatchObject({ kind: 'step', text: 'Confirmed', done: true });
  });

  it('correction Enter sends append_optimistic_log with Corrected step', () => {
    globalThis.appendLogEntry({ kind: 'confirm', summary: 'Fill form', uncertain_fields: [], file_links: [] });
    const input = document.querySelector('.tailorer-correction-input');
    input.value = 'please fix this';
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    const calls = globalThis.__testPort.postMessage.mock.calls;
    const optimisticCall = calls.find(([msg]) => msg.type === 'append_optimistic_log');
    expect(optimisticCall).toBeDefined();
    expect(optimisticCall[0].entry).toMatchObject({ kind: 'step', text: 'Corrected', done: true });
  });

  it('unblock button sends append_optimistic_log with Unblocked step', () => {
    globalThis.setStatusBar('show_stuck');
    globalThis.appendLogEntry({ kind: 'stuck', message: 'Need help' });
    document.querySelector('.tailorer-btn--unblock').click();
    const calls = globalThis.__testPort.postMessage.mock.calls;
    const optimisticCall = calls.find(([msg]) => msg.type === 'append_optimistic_log');
    expect(optimisticCall).toBeDefined();
    expect(optimisticCall[0].entry).toMatchObject({ kind: 'step', text: 'Unblocked', done: true });
  });
});

describe('_sendUserInput — empty Enter does nothing', () => {
  beforeEach(() => {
    globalThis.chrome = undefined;
    setupDOM();
    loadPanel();
    globalThis.__testPort = { postMessage: vi.fn() };
    globalThis.setStatusBar('awaiting_user');
  });

  it('does not send any message when input is empty', () => {
    const chatInput = document.getElementById('tailorer-chat-input');
    expect(chatInput).not.toBeNull();
    chatInput.value = '';
    chatInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(globalThis.__testPort.postMessage).not.toHaveBeenCalled();
  });

  it('sends user_correction when input has text', () => {
    const chatInput = document.getElementById('tailorer-chat-input');
    chatInput.value = 'please fix the email field';
    chatInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    const calls = globalThis.__testPort.postMessage.mock.calls;
    const correctionCall = calls.find(([msg]) => msg.type === 'user_correction');
    expect(correctionCall).toBeDefined();
    expect(correctionCall[0].text).toBe('please fix the email field');
  });
});

describe('confirm card — no file links rendered', () => {
  beforeEach(() => {
    globalThis.chrome = undefined;
    setupDOM();
    loadPanel();
  });

  it('does not render .tailorer-file-links inside confirm card', () => {
    globalThis.appendLogEntry({
      kind: 'confirm',
      summary: 'Fill form',
      uncertain_fields: [],
      file_links: [{ url: 'http://localhost:8000/tailorer/files/t1/cv?token=tok', label: 'tailored_cv.docx' }],
    });
    const links = document.querySelector('.tailorer-confirm-block .tailorer-file-links');
    expect(links).toBeNull();
  });
});
