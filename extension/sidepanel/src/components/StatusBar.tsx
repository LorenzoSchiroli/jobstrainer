import React from 'react';

const STATUS_CONFIG: Record<string, { text: string; dot: boolean; color: string; bg: string }> = {
  connecting:    { text: 'Connecting…',       dot: true,  color: '#7dd3fc', bg: '#172554' },
  navigating:    { text: 'Navigating…',       dot: true,  color: '#7dd3fc', bg: '#172554' },
  filling:       { text: 'Filling form…',     dot: true,  color: '#7dd3fc', bg: '#172554' },
  awaiting_user: { text: '⏸ Waiting for you', dot: false, color: '#fbbf24', bg: '#451a03' },
  show_stuck:    { text: '⚠ Action needed',   dot: false, color: '#fca5a5', bg: '#450a0a' },
  done:          { text: '✓ Done',            dot: false, color: '#86efac', bg: '#14532d' },
  error:         { text: '✗ Error',           dot: false, color: '#fca5a5', bg: '#450a0a' },
  idle:          { text: 'No active session', dot: false, color: '#64748b', bg: '#1e293b' },
};

export default function StatusBar({ status }: { status: string }) {
  const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG.idle;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: cfg.bg, padding: '3px 8px', borderRadius: 4 }}>
      {cfg.dot && (
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: cfg.color, display: 'inline-block', animation: 'pulse 1.2s ease-in-out infinite' }} />
      )}
      <span style={{ color: cfg.color, fontSize: 11 }}>{cfg.text}</span>
    </div>
  );
}
