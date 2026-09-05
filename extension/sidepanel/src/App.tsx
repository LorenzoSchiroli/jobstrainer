import React, { useEffect, useRef, useState, useCallback } from 'react';
import LogEntry from './components/LogEntry';
import StatusBar from './components/StatusBar';
import type { LogEntry as LogItem } from '../../background/session/types';

const API_BASE = 'http://localhost:8000';

interface ActiveJob { job_id: string; job_title: string; }
type LinkState = 'checking' | 'linked' | 'unlinked' | 'expired';

export default function App() {
  const [log, setLog] = useState<LogItem[]>([]);
  const [status, setStatus] = useState('idle');
  const [token, setToken] = useState<string | null>(null);
  const [activeJob, setActiveJob] = useState<ActiveJob | null>(null);
  const [username, setUsername] = useState<string | null>(null);
  const [authState, setAuthState] = useState<'checking' | 'ok' | 'fail'>('checking');
  const [inputText, setInputText] = useState('');
  const portRef = useRef<chrome.runtime.Port | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);

  const isActive = ['connecting', 'filling'].includes(status);
  const hasJob = activeJob !== null;

  // ── The user↔offer link: storage is the single source of truth ──────────────
  useEffect(() => {
    chrome.storage.local.get(['token', 'activeJob'], ({ token, activeJob }) => {
      setToken(token ?? null);
      setActiveJob(activeJob ?? null);
    });
    const onChanged = (
      changes: Record<string, chrome.storage.StorageChange>,
      area: string,
    ) => {
      if (area !== 'local') return;
      if ('token' in changes) setToken(changes.token.newValue ?? null);
      if ('activeJob' in changes) setActiveJob(changes.activeJob.newValue ?? null);
    };
    chrome.storage.onChanged.addListener(onChanged);
    return () => chrome.storage.onChanged.removeListener(onChanged);
  }, []);

  // Resolve the user from the token — also a live auth check (401 ⇒ expired link).
  useEffect(() => {
    if (!token) { setUsername(null); setAuthState('fail'); return; }
    let cancelled = false;
    setAuthState('checking');
    fetch(`${API_BASE}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(data => { if (!cancelled) { setUsername(data.username ?? null); setAuthState('ok'); } })
      .catch(() => { if (!cancelled) { setUsername(null); setAuthState('fail'); } });
    return () => { cancelled = true; };
  }, [token]);

  const linkState: LinkState =
    !activeJob || !token ? 'unlinked'
    : authState === 'checking' ? 'checking'
    : authState === 'fail' ? 'expired'
    : 'linked';

  // ── Session port (per-tab fill flow) ────────────────────────────────────────
  useEffect(() => {
    chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
      if (!tab?.id) return;
      const port = chrome.runtime.connect({ name: `panel-${tab.id}` });
      portRef.current = port;

      port.onMessage.addListener((msg: any) => {
        if (msg.type === 'idle') { setStatus('idle'); setLog([]); return; }
        if (msg.type === 'restore_panel') { setLog(msg.log ?? []); setStatus(msg.status ?? 'idle'); return; }
        if (msg.type === 'append_log') { setLog(prev => [...prev, msg.entry]); return; }
        if (msg.type === 'set_status') { setStatus(msg.status); return; }
        if (msg.type === 'error_toast') {
          setLog(prev => [...prev, { kind: 'error', message: msg.message }]);
          return;
        }
      });

      port.onDisconnect.addListener(() => { portRef.current = null; });
    });
  }, []);

  useEffect(() => { logEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [log]);

  const sendMsg = useCallback((msg: any) => { portRef.current?.postMessage(msg); }, []);

  const handleSend = useCallback((overrideText?: string) => {
    const text = (overrideText ?? inputText).trim();
    if (!text) return;
    setInputText('');
    setLog(prev => [...prev, { kind: 'step', text, done: false }]);
    sendMsg({ type: 'start_or_fill', text, job_id: activeJob?.job_id, token });
  }, [inputText, sendMsg, activeJob, token]);

  const handleNewSession = useCallback(() => {
    setLog([]);
    setStatus('idle');
    sendMsg({ type: 'new_session' });
  }, [sendMsg]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#0f172a', color: '#f1f5f9', fontFamily: 'system-ui, sans-serif', fontSize: 12 }}>
      {/* Header */}
      <div style={{ padding: '8px 12px', display: 'flex', alignItems: 'center', gap: 8, borderBottom: '1px solid rgba(14,165,233,0.2)', flexShrink: 0 }}>
        <div style={{ width: 22, height: 22, background: '#0ea5e9', borderRadius: '50%' }} />
        <span style={{ fontWeight: 700, color: '#7dd3fc', fontSize: 13 }}>Tailorer</span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
          <StatusBar status={status} />
          <button
            onClick={handleNewSession}
            style={{ background: '#1e293b', color: '#94a3b8', border: '1px solid #334155', borderRadius: 5, padding: '3px 8px', fontSize: 11, cursor: 'pointer' }}
          >New Session</button>
        </div>
      </div>

      {/* Link status — which user / which job */}
      <LinkBanner state={linkState} username={username} job={activeJob} />

      {/* Feed */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        {status === 'idle' && log.length === 0 && (
          <div style={{ color: '#475569', textAlign: 'center', marginTop: 40, lineHeight: 1.6 }}>
            {hasJob ? 'Navigate to the application form, then click Fill.' : 'No active job — browse to a job listing in Jobsifty.'}
          </div>
        )}

        {log.length > 0 && (
          <div style={{ display: 'flex', gap: 8 }}>
            <div style={{ width: 24, height: 24, borderRadius: '50%', background: '#0c4a6e', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, color: '#38bdf8', fontWeight: 700 }}>A</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#0ea5e9', marginBottom: 5, letterSpacing: '0.04em' }}>AGENT</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {log.map((entry, i) => {
                  if (entry.kind === 'step') return <LogEntry key={i} text={entry.text} done={entry.done} />;
                  if (entry.kind === 'summary') return (
                    <div key={i} style={{ background: '#1e293b', borderRadius: 6, padding: '8px 10px', fontSize: 11 }}>
                      <div style={{ color: '#86efac', fontWeight: 600, marginBottom: 4 }}>✓ Filled {entry.filled_count} field{entry.filled_count !== 1 ? 's' : ''}</div>
                      {entry.uncertain_fields.length > 0 && (
                        <div style={{ color: '#fcd34d' }}>Uncertain: fields [{entry.uncertain_fields.join(', ')}] — check manually</div>
                      )}
                      {entry.file_links.map((fl, j) => (
                        <div key={j} style={{ marginTop: 4 }}>
                          <a href={fl.url} download={fl.label} style={{ color: '#38bdf8', textDecoration: 'none' }}>↓ {fl.label}</a>
                        </div>
                      ))}
                    </div>
                  );
                  if (entry.kind === 'error') return <div key={i} style={{ color: '#fca5a5' }}>✗ {entry.message}</div>;
                  return null;
                })}
              </div>
            </div>
          </div>
        )}
        <div ref={logEndRef} />
      </div>

      {/* Fill shortcut + input bar */}
      <div style={{ borderTop: '1px solid #1e293b', padding: '6px 10px 8px', flexShrink: 0 }}>
        <button
          onClick={() => handleSend('fill the form')}
          style={{ width: '100%', background: '#0ea5e9', color: '#fff', border: 'none', borderRadius: 6, padding: '7px', fontWeight: 600, fontSize: 12, cursor: 'pointer', marginBottom: 6 }}
        >Fill</button>
        <div style={{ display: 'flex', gap: 7, alignItems: 'center' }}>
          <input
            value={inputText}
            onChange={e => setInputText(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSend()}
            placeholder={isActive ? 'Filling…' : 'Type an instruction or correction…'}
            style={{ flex: 1, background: '#1e293b', border: '1px solid #334155', borderRadius: 6, padding: '6px 9px', color: '#f1f5f9', fontSize: 12, fontFamily: 'system-ui', outline: 'none' }}
          />
          <button
            onClick={() => handleSend()}
            disabled={!inputText.trim() || isActive}
            style={{ background: inputText.trim() && !isActive ? '#0ea5e9' : '#1e293b', color: inputText.trim() && !isActive ? '#fff' : '#334155', border: 'none', borderRadius: 6, padding: '6px 12px', fontSize: 12, cursor: inputText.trim() && !isActive ? 'pointer' : 'not-allowed', flexShrink: 0 }}
          >▶</button>
          <button
            onClick={() => sendMsg({ type: 'stop_session' })}
            disabled={!isActive}
            style={{ background: isActive ? '#7f1d1d' : '#1e293b', color: isActive ? '#fca5a5' : '#334155', border: `1px solid ${isActive ? '#991b1b' : '#1e293b'}`, borderRadius: 5, padding: '6px 10px', fontSize: 11, cursor: isActive ? 'pointer' : 'not-allowed', flexShrink: 0 }}
          >■ Stop</button>
        </div>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #0f172a; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
      `}</style>
    </div>
  );
}

function LinkBanner({ state, username, job }: { state: LinkState; username: string | null; job: ActiveJob | null }) {
  const base: React.CSSProperties = {
    padding: '6px 12px', fontSize: 11, borderBottom: '1px solid #1e293b',
    display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0,
  };

  if (state === 'unlinked') {
    return <div style={{ ...base, color: '#64748b' }}>Not linked — open a job in Jobsifty.</div>;
  }
  if (state === 'expired') {
    return <div style={{ ...base, color: '#fca5a5' }}>Session expired — re-open the job in Jobsifty.</div>;
  }
  return (
    <div style={base}>
      <span style={{ color: '#94a3b8' }}>
        👤 <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{state === 'checking' ? '…' : username}</span>
      </span>
      <span style={{ color: '#334155' }}>·</span>
      <span style={{ color: '#94a3b8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        💼 <span style={{ color: '#7dd3fc' }}>{job?.job_title || job?.job_id?.slice(0, 8)}</span>
      </span>
    </div>
  );
}
