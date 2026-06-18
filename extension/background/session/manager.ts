import Page from '../browser/page';
import type { Session, PendingJob, LogEntry } from './types';

export type MessageHandler = (
  tabId: number,
  msg: Record<string, unknown>,
) => Promise<void>;

export class SessionManager {
  private readonly sessions = new Map<number, Session>();
  private readonly pendingJobs = new Map<number, PendingJob>();
  private readonly ports = new Map<number, chrome.runtime.Port>();

  // ── Ports ──────────────────────────────────────────────────────────────────

  registerPort(tabId: number, port: chrome.runtime.Port): void {
    this.ports.set(tabId, port);
  }

  removePort(tabId: number): void {
    this.ports.delete(tabId);
  }

  sendToPanel(tabId: number, msg: unknown): void {
    this.ports.get(tabId)?.postMessage(msg);
  }

  // ── Pending jobs ───────────────────────────────────────────────────────────

  setPending(tabId: number, job: PendingJob): void {
    this.pendingJobs.set(tabId, job);
  }

  getPending(tabId: number): PendingJob | undefined {
    return this.pendingJobs.get(tabId);
  }

  clearPending(tabId: number): void {
    this.pendingJobs.delete(tabId);
  }

  // ── Sessions ───────────────────────────────────────────────────────────────

  get(tabId: number): Session | undefined {
    return this.sessions.get(tabId);
  }

  has(tabId: number): boolean {
    return this.sessions.has(tabId);
  }

  open(tabId: number, jobId: string, token: string, onMessage: MessageHandler): void {
    const wsUrl = `ws://localhost:8000/tailorer/ws/${jobId}?token=${encodeURIComponent(token)}`;
    const ws = new WebSocket(wsUrl);
    const page = new Page(tabId);

    const session: Session = {
      job_id: jobId, token, thread_id: null,
      ws, page, log: [], currentStatus: 'connecting',
    };
    this.sessions.set(tabId, session);

    ws.onmessage = async (event) => {
      let msg: Record<string, unknown> | undefined;
      try {
        msg = JSON.parse(event.data as string) as Record<string, unknown>;
        await onMessage(tabId, msg);
      } catch (e) {
        console.error('[tailorer] onMessage error type=%s err=%s', msg?.type, (e as Error)?.message);
        const needsResponse = msg && ['navigate', 'request_snapshot', 'execute_actions'].includes(msg.type as string);
        if (needsResponse && ws.readyState === WebSocket.OPEN) {
          const tab = await chrome.tabs.get(tabId).catch(() => null);
          ws.send(JSON.stringify({
            url: tab?.url ?? '', title: tab?.title ?? '', elements: '',
          }));
        }
      }
    };

    ws.onclose = (ev) => {
      const s = this.sessions.get(tabId);
      if (!s) return;
      const msg = ev.code === 4001 || ev.code === 1015
        ? `Auth error (${ev.code})`
        : 'Connection lost — restart session.';
      this.appendLog(tabId, { kind: 'error', message: msg });
      s.page.detach().catch(() => {});
      this.sessions.delete(tabId);
    };

    ws.onerror = () => {};
  }

  stop(tabId: number, reason: string): void {
    const s = this.sessions.get(tabId);
    if (!s) return;
    s.ws.close();
    s.page.detach().catch(() => {});
    this.appendLog(tabId, { kind: 'error', message: reason });
    this.sessions.delete(tabId);
  }

  removeSession(tabId: number): void {
    const s = this.sessions.get(tabId);
    if (s) {
      s.page.detach().catch(() => {});
      this.sessions.delete(tabId);
    }
  }

  // ── Log ────────────────────────────────────────────────────────────────────

  appendLog(tabId: number, entry: LogEntry): void {
    const s = this.sessions.get(tabId);
    if (!s) return;
    s.log.push(entry);
    this.sendToPanel(tabId, { type: 'append_log', entry });
  }

  // ── Cleanup ────────────────────────────────────────────────────────────────

  cleanupTab(tabId: number): void {
    const s = this.sessions.get(tabId);
    if (s) {
      s.ws.close();
      s.page.detach().catch(() => {});
      this.sessions.delete(tabId);
    }
    this.pendingJobs.delete(tabId);
    this.ports.delete(tabId);
  }

  // ── Keepalive snapshot ─────────────────────────────────────────────────────

  activeSessions(): Array<{
    tabId: number; job_id: string; token: string;
    log: LogEntry[]; currentStatus: string;
  }> {
    return Array.from(this.sessions.entries()).map(([tabId, s]) => ({
      tabId, job_id: s.job_id, token: s.token, log: s.log, currentStatus: s.currentStatus,
    }));
  }
}

export const sessionManager = new SessionManager();
