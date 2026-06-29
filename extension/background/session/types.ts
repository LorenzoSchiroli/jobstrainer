import type Page from '../browser/page';

export interface FileLink {
  field_id: number;
  label: string;
  url: string;
}

export type LogEntry =
  | { kind: 'step'; text: string; done: boolean }
  | { kind: 'summary'; filled_count: number; uncertain_fields: string[]; file_links: FileLink[] }
  | { kind: 'error'; message: string };

export interface Session {
  job_id: string;
  token: string;
  thread_id: string | null;
  ws: WebSocket;
  page: Page;
  log: LogEntry[];
  currentStatus: string;
}
