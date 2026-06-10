import type Page from '../browser/page';

export interface FileLink {
  field_id: number;
  label: string;
  url: string;
}

export type LogEntry =
  | { kind: 'step'; text: string; done: boolean }
  | { kind: 'confirm'; summary: string; uncertain_fields: string[]; file_links: FileLink[] }
  | { kind: 'stuck'; message: string }
  | { kind: 'done'; message: string; thread_id: string; token: string }
  | { kind: 'error'; message: string };

export interface PendingJob {
  job_id: string;
  token: string;
}

export interface Session {
  job_id: string;
  token: string;
  thread_id: string | null;
  ws: WebSocket;
  page: Page;
  log: LogEntry[];
  currentStatus: string;
}
