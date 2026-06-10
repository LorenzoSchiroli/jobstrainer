import { sessionManager } from '../session/manager';
import { executeAction } from '../browser/actions';
import { waitForNavCompleted } from '../browser/navigation';
import type { Session, LogEntry } from '../session/types';

const API_BASE = 'http://localhost:8000';

function safeHostname(url: string): string {
  try { return new URL(url).hostname; } catch { return url; }
}

type Handler = (
  tabId: number,
  session: Session,
  msg: Record<string, unknown>,
) => Promise<void>;

const HANDLERS: Record<string, Handler> = {
  session_started: async (tabId, session, msg) => {
    session.thread_id = msg.thread_id as string;
    session.currentStatus = 'navigating';
    sessionManager.appendLog(tabId, { kind: 'step', text: 'Session started', done: true });
    sessionManager.sendToPanel(tabId, { type: 'set_status', status: 'navigating' });
  },

  navigate: async (tabId, session, msg) => {
    session.currentStatus = 'navigating';
    await session.page.detach();
    const navDone = waitForNavCompleted(tabId);
    await chrome.tabs.update(tabId, { url: msg.url as string });
    await navDone;
    await session.page.attach();
    const snap = await session.page.snapshot();
    sessionManager.appendLog(tabId, { kind: 'step', text: `Navigated to ${safeHostname(msg.url as string)}`, done: true });
    session.ws.send(JSON.stringify(snap));
  },

  request_snapshot: async (_tabId, session) => {
    await session.page.attach();
    const snap = await session.page.snapshot();
    session.ws.send(JSON.stringify(snap));
  },

  execute_actions: async (tabId, session, msg) => {
    session.currentStatus = 'navigating';
    await session.page.attach();
    for (const action of msg.actions as Record<string, unknown>[]) {
      const { navigated } = await executeAction(session.page, action, tabId);
      if (navigated) {
        await session.page.detach();
        await session.page.attach();
        break;
      }
    }
    const snap = await session.page.snapshot();
    session.ws.send(JSON.stringify(snap));
  },

  fill_and_confirm: async (tabId, session, msg) => {
    session.currentStatus = 'filling';
    await session.page.attach();
    const commands = msg.commands as Record<string, unknown>[];

    for (const cmd of commands) {
      if (cmd.action === 'file_upload' || cmd.value === '__CV__' || cmd.value === '__COVER_LETTER__') continue;
      try {
        if (cmd.action === 'input_text') {
          await session.page.typeText(cmd.index as number, cmd.value as string);
        } else if (cmd.action === 'select_option') {
          await session.page.selectOption(cmd.index as number, ((cmd.text ?? cmd.value) as string));
        }
      } catch (e) {
        console.warn('[tailorer] fill cmd failed', cmd, e);
      }
    }

    const fileLinks = commands
      .filter(c => c.action === 'file_upload' || c.value === '__CV__' || c.value === '__COVER_LETTER__')
      .map(c => ({
        field_id: c.index as number,
        label: c.value === '__CV__' ? 'tailored_cv.docx' : 'cover_letter.docx',
        url: `${API_BASE}/tailorer/files/${session.thread_id}/${c.value === '__CV__' ? 'cv' : 'cover_letter'}?token=${encodeURIComponent(session.token)}`,
      }));

    const confirmCmds = (msg.confirm_commands ?? commands) as Record<string, unknown>[];
    const uncertain = confirmCmds.filter(c => c.uncertain).map(c => `[${c.index}]`);

    session.currentStatus = 'awaiting_user';
    sessionManager.appendLog(tabId, {
      kind: 'confirm',
      summary: (msg.summary as string) || 'Ready to fill',
      uncertain_fields: uncertain,
      file_links: fileLinks,
    });
    sessionManager.sendToPanel(tabId, { type: 'set_status', status: 'awaiting_user' });
  },

  show_confirm: async (tabId, session, msg) => {
    session.currentStatus = 'awaiting_user';
    sessionManager.appendLog(tabId, {
      kind: 'confirm',
      summary: msg.summary as string,
      uncertain_fields: (msg.uncertain_fields as string[]) ?? [],
      file_links: (msg.file_links as any[]) ?? [],
    });
    sessionManager.sendToPanel(tabId, { type: 'set_status', status: 'awaiting_user' });
  },

  navigate_next: async (tabId, session) => {
    session.currentStatus = 'navigating';
    sessionManager.appendLog(tabId, { kind: 'step', text: 'Submitting page…', done: false });
    await new Promise(r => setTimeout(r, 1000));
    session.ws.send(JSON.stringify({ submitted: true }));
  },

  show_stuck: async (tabId, session, msg) => {
    session.currentStatus = 'show_stuck';
    sessionManager.appendLog(tabId, { kind: 'stuck', message: msg.message as string });
    sessionManager.sendToPanel(tabId, { type: 'set_status', status: 'show_stuck' });
  },

  done: async (tabId, session, msg) => {
    session.currentStatus = 'done';
    sessionManager.appendLog(tabId, {
      kind: 'done',
      message: msg.message as string,
      thread_id: session.thread_id ?? '',
      token: session.token,
    });
    sessionManager.sendToPanel(tabId, { type: 'set_status', status: 'done' });
    sessionManager.removeSession(tabId);
  },

  error: async (tabId, session, msg) => {
    session.currentStatus = 'error';
    sessionManager.appendLog(tabId, { kind: 'error', message: msg.message as string });
    sessionManager.sendToPanel(tabId, { type: 'set_status', status: 'error' });
    sessionManager.removeSession(tabId);
  },
};

export async function handleAgentMessage(
  tabId: number,
  msg: Record<string, unknown>,
): Promise<void> {
  const session = sessionManager.get(tabId);
  if (!session) return;
  const handler = HANDLERS[msg.type as string];
  if (!handler) return;
  await handler(tabId, session, msg);
}
