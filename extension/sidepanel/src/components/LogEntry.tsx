import React from 'react';

interface Props {
  text: string;
  done: boolean;
}

export default function LogEntry({ text, done }: Props) {
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 12, lineHeight: 1.5 }}>
      <span style={{ color: done ? '#22c55e' : '#38bdf8', flexShrink: 0, width: 14, textAlign: 'center', animation: done ? undefined : 'spin 1s linear infinite', display: 'inline-block' }}>
        {done ? '✓' : '⟳'}
      </span>
      <span style={{ color: done ? '#94a3b8' : '#f1f5f9' }}>{text}</span>
    </div>
  );
}
