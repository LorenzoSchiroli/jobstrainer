import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockSendToPanel = vi.fn();
const mockHas = vi.fn();
const mockStop = vi.fn();

vi.mock('../session/manager', () => ({
  sessionManager: {
    has: mockHas,
    stop: mockStop,
    sendToPanel: mockSendToPanel,
    registerPort: vi.fn(),
    removePort: vi.fn(),
    get: vi.fn(),
    getPending: vi.fn(),
    clearPending: vi.fn(),
    open: vi.fn(),
    cleanupTab: vi.fn(),
    activeSessions: vi.fn().mockReturnValue([]),
    setPending: vi.fn(),
  },
}));

vi.mock('../agent/messageHandler', () => ({
  handleAgentMessage: vi.fn(),
}));

function stopSessionHandler(tabId: number) {
  if (mockHas(tabId)) {
    mockStop(tabId, 'Stopped by user.');
  } else {
    mockSendToPanel(tabId, { type: 'set_status', status: 'idle' });
  }
}

describe('stop_session — no live session', () => {
  beforeEach(() => vi.clearAllMocks());

  it('sends set_status idle (not type:idle) when no session exists', () => {
    mockHas.mockReturnValue(false);
    stopSessionHandler(1);
    expect(mockSendToPanel).toHaveBeenCalledWith(1, { type: 'set_status', status: 'idle' });
  });

  it('does NOT send type:idle message', () => {
    mockHas.mockReturnValue(false);
    stopSessionHandler(1);
    const calls = mockSendToPanel.mock.calls;
    const hasIdleMsg = calls.some(([, msg]) => msg.type === 'idle');
    expect(hasIdleMsg).toBe(false);
  });

  it('calls stop when session exists', () => {
    mockHas.mockReturnValue(true);
    stopSessionHandler(1);
    expect(mockStop).toHaveBeenCalledWith(1, 'Stopped by user.');
    expect(mockSendToPanel).not.toHaveBeenCalled();
  });
});

describe('restore_panel — dead WS gets error status', () => {
  function buildRestoreMsg(ws: { readyState: number }, currentStatus: string) {
    const status = ws.readyState === WebSocket.OPEN ? currentStatus : 'error';
    return { type: 'restore_panel', log: [], status };
  }

  it('uses error status when WS is closed', () => {
    const msg = buildRestoreMsg({ readyState: WebSocket.CLOSED }, 'navigating');
    expect(msg.status).toBe('error');
  });

  it('uses error status when WS is connecting', () => {
    const msg = buildRestoreMsg({ readyState: WebSocket.CONNECTING }, 'filling');
    expect(msg.status).toBe('error');
  });

  it('preserves currentStatus when WS is open', () => {
    const msg = buildRestoreMsg({ readyState: WebSocket.OPEN }, 'awaiting_user');
    expect(msg.status).toBe('awaiting_user');
  });
});
