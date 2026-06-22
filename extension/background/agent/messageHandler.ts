import { sessionManager } from '../session/manager';
import type { Session } from '../session/types';

const API_BASE = 'http://localhost:8000';

type Handler = (
  tabId: number,
  session: Session,
  msg: Record<string, unknown>,
) => Promise<void>;

const HANDLERS: Record<string, Handler> = {
  session_started: async (_tabId, session, msg) => {
    session.thread_id = msg.thread_id as string;
    session.currentStatus = 'idle';
  },

  apply_fills: async (tabId, session, msg) => {
    session.currentStatus = 'filling';
    const commands = msg.commands as Record<string, unknown>[];
    console.log('[tailorer] apply_fills received commands=%d', commands.length);

    sessionManager.appendLog(tabId, { kind: 'step', text: 'Analyzing form with AI…', done: true });

    await session.page.attach();

    const threadId = (msg.thread_id as string) ?? session.thread_id ?? '';
    const token = (msg.token as string) ?? session.token;

    sessionManager.appendLog(tabId, { kind: 'step', text: `Filling ${commands.length} fields…`, done: false });

    const fieldValues: Record<string, string> = {};
    const fileFailedIndices = new Set<string>();

    for (const cmd of commands) {
      const idx = cmd.index as number;
      const value = cmd.value as string;
      try {
        await session.page.applyFill(idx, value, threadId, token);
        fieldValues[String(idx)] = await session.page.readFieldValue(idx);
      } catch (e) {
        console.warn('[tailorer] applyFill failed', cmd, e);
        if (value === '__CV__' || value === '__COVER_LETTER__') {
          fileFailedIndices.add(String(idx));
        }
        fieldValues[String(idx)] = '';
      }
    }

    // Persist file commands + failures so the filled handler can build download links
    (session as any)._lastFileCommands = commands.filter(
      (c) => c.value === '__CV__' || c.value === '__COVER_LETTER__',
    );
    (session as any)._lastFileFailedIndices = fileFailedIndices;

    const snap = await session.page.snapshot();

    sessionManager.appendLog(tabId, { kind: 'step', text: `Filling ${commands.length} fields…`, done: true });

    session.ws.send(JSON.stringify({
      type: 'fill_result',
      snapshot: snap,
      field_values: fieldValues,
    }));
  },

  filled: async (tabId, session, msg) => {
    session.currentStatus = 'idle';
    const filledCount = (msg.filled_count as number) ?? 0;
    const uncertainFields = (msg.uncertain_fields as string[]) ?? [];

    // Build download links for file commands where upload failed
    const lastFileCmds: Array<Record<string, unknown>> = (session as any)._lastFileCommands ?? [];
    const failedIds: Set<string> = (session as any)._lastFileFailedIndices ?? new Set();
    const fileLinks = lastFileCmds
      .filter((c) => failedIds.has(String(c.index)))
      .map((c) => ({
        field_id: c.index as number,
        label: c.value === '__CV__' ? 'tailored_cv.docx' : 'cover_letter.docx',
        url: `${API_BASE}/tailorer/files/${session.thread_id}/${c.value === '__CV__' ? 'cv' : 'cover_letter'}?token=${encodeURIComponent(session.token)}`,
      }));

    sessionManager.appendLog(tabId, {
      kind: 'summary',
      filled_count: filledCount,
      uncertain_fields: uncertainFields,
      file_links: fileLinks,
    });
    sessionManager.sendToPanel(tabId, { type: 'set_status', status: 'idle' });
  },

  application_recorded: async (tabId, _session, _msg) => {
    sessionManager.appendLog(tabId, { kind: 'step', text: 'Application recorded', done: true });
  },

  error: async (tabId, session, msg) => {
    session.currentStatus = 'error';
    sessionManager.appendLog(tabId, { kind: 'error', message: msg.message as string });
    sessionManager.sendToPanel(tabId, { type: 'set_status', status: 'error' });
  },
};

export async function handleAgentMessage(
  tabId: number,
  msg: Record<string, unknown>,
): Promise<void> {
  console.log('[tailorer] handleAgentMessage type=%s', msg.type);
  const session = sessionManager.get(tabId);
  if (!session) return;
  const handler = HANDLERS[msg.type as string];
  if (!handler) {
    console.warn('[tailorer] unhandled message type:', msg.type);
    return;
  }
  await handler(tabId, session, msg);
}
