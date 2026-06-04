import React, { useEffect, useRef, useState, useCallback } from 'react';
import LogEntry from './components/LogEntry';
import ConfirmBlock from './components/ConfirmBlock';
import StatusBar from './components/StatusBar';

type LogItem =
  | { kind: 'step'; text: string; done: boolean }
  | { kind: 'confirm'; summary: string; uncertain_fields: string[]; file_links: { field_id: number; label: string; url: string }[] }
  | { kind: 'stuck'; message: string }
  | { kind: 'done'; message: string; thread_id: string; token: string }
  | { kind: 'error'; message: string };

export default function App() {
  const [log, setLog] = useState<LogItem[]>([]);
  const [status, setStatus] = useState('idle');
  const [pendingJob, setPendingJob] = useState<{ job_id: string; token: string } | null>(null);
  const [inputText, setInputText] = useState('');
  const portRef = useRef<chrome.runtime.Port | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);

  const isWaiting = status === 'awaiting_user' || status === 'show_stuck';

  useEffect(() => {
    chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
      if (!tab?.id) return;
      const port = chrome.runtime.connect({ name: `panel-${tab.id}` });
      portRef.current = port;

      port.onMessage.addListener((msg: any) => {
        if (msg.type === 'idle') { setStatus('idle'); setLog([]); return; }
        if (msg.type === 'show_apply_button') { setPendingJob({ job_id: msg.job_id, token: msg.token }); return; }
        if (msg.type === 'restore_panel') { setLog(msg.log ?? []); setStatus(msg.status ?? 'idle'); return; }
        if (msg.type === 'append_log') { setLog(prev => [...prev, msg.entry]); return; }
        if (msg.type === 'status') { setStatus(msg.status); return; }
      });

      port.onDisconnect.addListener(() => { portRef.current = null; });
    });
  }, []);

  useEffect(() => { logEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [log]);

  const sendMsg = useCallback((msg: any) => { portRef.current?.postMessage(msg); }, []);

  const handleStart = useCallback(() => {
    if (!pendingJob) return;
    setPendingJob(null);
    setLog([]);
    setStatus('connecting');
    sendMsg({ type: 'start_session', job_id: pendingJob.job_id, token: pendingJob.token });
  }, [pendingJob, sendMsg]);

  const handleSend = useCallback(() => {
    const text = inputText.trim();
    if (!text || !isWaiting) return;
    setInputText('');
    if (status === 'show_stuck') {
      sendMsg({ type: 'stuck_unblocked', text });
    } else {
      const lower = text.toLowerCase();
      if (lower === 'ok' || lower === 'yes' || lower === 'approve') {
        sendMsg({ type: 'user_approved' });
      } else {
        sendMsg({ type: 'user_correction', text });
      }
    }
  }, [inputText, isWaiting, status, sendMsg]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#0f172a', color: '#f1f5f9', fontFamily: 'system-ui, sans-serif', fontSize: 12 }}>
      {/* Header */}
      <div style={{ padding: '8px 12px', display: 'flex', alignItems: 'center', gap: 8, borderBottom: '1px solid rgba(14,165,233,0.2)', flexShrink: 0 }}>
        <div style={{ width: 22, height: 22, background: '#0ea5e9', borderRadius: '50%' }} />
        <span style={{ fontWeight: 700, color: '#7dd3fc', fontSize: 13 }}>Tailorer</span>
        <div style={{ marginLeft: 'auto' }}>
          <StatusBar status={status} />
        </div>
      </div>

      {/* Feed */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        {status === 'idle' && log.length === 0 && (
          <div style={{ color: '#475569', textAlign: 'center', marginTop: 40, lineHeight: 1.6 }}>
            No active job — browse to a job listing to apply.
          </div>
        )}

        {pendingJob && (
          <div style={{ padding: '12px 0' }}>
            <div style={{ color: '#94a3b8', marginBottom: 10 }}>Job detected — ready to apply</div>
            <button onClick={handleStart} style={{ background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, padding: '9px 16px', fontWeight: 600, fontSize: 13, cursor: 'pointer', width: '100%' }}>
              ⚡ Start Agent
            </button>
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
                  if (entry.kind === 'confirm') return <ConfirmBlock key={i} summary={entry.summary} uncertain_fields={entry.uncertain_fields} file_links={entry.file_links} />;
                  if (entry.kind === 'stuck') return <div key={i} style={{ color: '#fca5a5', background: '#1c1f2e', borderLeft: '3px solid #ef4444', borderRadius: 4, padding: '8px 10px' }}>{entry.message}</div>;
                  if (entry.kind === 'done') return <div key={i} style={{ color: '#86efac', fontWeight: 600 }}>✓ {entry.message}</div>;
                  if (entry.kind === 'error') return <div key={i} style={{ color: '#fca5a5' }}>✗ {entry.message}</div>;
                  return null;
                })}
              </div>
            </div>
          </div>
        )}
        <div ref={logEndRef} />
      </div>

      {/* Bottom bar */}
      <div style={{ borderTop: '1px solid #1e293b', padding: '8px 10px', display: 'flex', gap: 7, alignItems: 'center', flexShrink: 0 }}>
        <input
          value={inputText}
          onChange={e => setInputText(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSend()}
          disabled={!isWaiting}
          placeholder={isWaiting ? 'ok / describe a correction / …' : 'Waiting for agent…'}
          style={{ flex: 1, background: isWaiting ? '#1e293b' : '#0f172a', border: `1px solid ${isWaiting ? '#334155' : '#1e293b'}`, borderRadius: 6, padding: '6px 9px', color: isWaiting ? '#f1f5f9' : '#334155', fontSize: 12, fontFamily: 'system-ui', outline: 'none', cursor: isWaiting ? 'text' : 'not-allowed' }}
        />
        <button
          onClick={handleSend}
          disabled={!isWaiting || !inputText.trim()}
          style={{ background: isWaiting && inputText.trim() ? '#0ea5e9' : '#1e293b', color: isWaiting && inputText.trim() ? '#fff' : '#334155', border: 'none', borderRadius: 6, padding: '6px 12px', fontSize: 12, cursor: isWaiting && inputText.trim() ? 'pointer' : 'not-allowed', flexShrink: 0 }}
        >▶</button>
        <button
          onClick={() => sendMsg({ type: 'stop_session' })}
          style={{ background: '#7f1d1d', color: '#fca5a5', border: '1px solid #991b1b', borderRadius: 5, padding: '6px 10px', fontSize: 11, cursor: 'pointer', flexShrink: 0 }}
        >■ Stop</button>
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
