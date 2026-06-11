import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.stubGlobal('chrome', {
  tabs: { get: vi.fn().mockResolvedValue({ url: 'https://example.com', title: 'Test' }) },
  scripting: { executeScript: vi.fn().mockResolvedValue([]) },
  alarms: { create: vi.fn(), onAlarm: { addListener: vi.fn() } },
  storage: { local: { set: vi.fn(), get: vi.fn() } },
});

const mockAppendLog = vi.fn();
const mockSendToPanel = vi.fn();
const mockGet = vi.fn();

vi.mock('../../session/manager', () => ({
  sessionManager: {
    get: mockGet,
    appendLog: mockAppendLog,
    sendToPanel: mockSendToPanel,
    removeSession: vi.fn(),
  },
}));

const mockExecuteAction = vi.fn().mockResolvedValue({ navigated: false });
vi.mock('../../browser/actions', () => ({
  executeAction: mockExecuteAction,
}));

vi.mock('../../browser/navigation', () => ({
  waitForNavCompleted: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('../../browser/page', () => ({
  default: vi.fn().mockImplementation(() => ({
    attach: vi.fn().mockResolvedValue(undefined),
    detach: vi.fn().mockResolvedValue(undefined),
    snapshot: vi.fn().mockResolvedValue({
      url: 'https://example.com',
      title: 'Test',
      elements: '[1]<button>Apply</>',
      scroll_y: 0,
      scroll_height: 100,
      viewport_height: 800,
    }),
  })),
}));

const makeSession = (overrides = {}) => ({
  job_id: 'job1',
  token: 'tok',
  thread_id: 'thread1',
  ws: { send: vi.fn(), readyState: 1 },
  page: {
    attach: vi.fn().mockResolvedValue(undefined),
    detach: vi.fn().mockResolvedValue(undefined),
    snapshot: vi.fn().mockResolvedValue({
      url: 'https://example.com',
      title: 'Test',
      elements: '[1]<button>Apply</>',
      scroll_y: 0,
      scroll_height: 100,
      viewport_height: 800,
    }),
  },
  log: [],
  currentStatus: 'navigating',
  ...overrides,
});

describe('handleAgentMessage — execute_actions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls appendLog once per action with a step entry', async () => {
    const { handleAgentMessage } = await import('../messageHandler');
    const session = makeSession();
    mockGet.mockReturnValue(session);

    await handleAgentMessage(1, {
      type: 'execute_actions',
      actions: [
        { action: 'click_element', index: 3 },
        { action: 'scroll_to_bottom' },
      ],
    });

    expect(mockAppendLog).toHaveBeenCalledTimes(2);
    const calls = mockAppendLog.mock.calls;
    expect(calls[0][1]).toMatchObject({ kind: 'step', done: true });
    expect(calls[1][1]).toMatchObject({ kind: 'step', done: true });
    expect(calls[0][1].text).toContain('click_element');
    expect(calls[0][1].text).toContain('[3]');
    expect(calls[1][1].text).toContain('scroll_to_bottom');
  });

  it('does not call appendLog when actions array is empty', async () => {
    const { handleAgentMessage } = await import('../messageHandler');
    const session = makeSession();
    mockGet.mockReturnValue(session);

    await handleAgentMessage(1, { type: 'execute_actions', actions: [] });

    expect(mockAppendLog).not.toHaveBeenCalled();
  });

  it('logs action before executeAction is called', async () => {
    const { handleAgentMessage } = await import('../messageHandler');
    const session = makeSession();
    mockGet.mockReturnValue(session);

    const callOrder: string[] = [];
    mockAppendLog.mockImplementation(() => {
      callOrder.push('appendLog');
    });
    mockExecuteAction.mockImplementation(async () => {
      callOrder.push('executeAction');
      return { navigated: false };
    });

    await handleAgentMessage(1, {
      type: 'execute_actions',
      actions: [{ action: 'click_element', index: 5 }],
    });

    expect(callOrder).toEqual(['appendLog', 'executeAction']);
  });
});
