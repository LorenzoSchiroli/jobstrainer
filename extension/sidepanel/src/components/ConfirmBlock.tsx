import React from 'react';

interface FileLink { field_id: number; label: string; url: string; }

interface Props {
  summary: string;
  uncertain_fields: string[];
  file_links: FileLink[];
}

export default function ConfirmBlock({ summary, uncertain_fields, file_links }: Props) {
  return (
    <div style={{ background: '#1c1f2e', borderLeft: '3px solid #f59e0b', borderRadius: 4, padding: '9px 11px' }}>
      <div style={{ color: '#fde68a', fontWeight: 600, marginBottom: 6, fontSize: 12 }}>{summary}</div>
      {uncertain_fields.length > 0 && (
        <div style={{ marginBottom: 6 }}>
          {uncertain_fields.map((f) => (
            <div key={f} style={{ color: '#fbbf24', fontSize: 11, lineHeight: 1.8 }}>
              {f} → <em>not sure</em>
            </div>
          ))}
        </div>
      )}
      {file_links.length > 0 && (
        <div>
          {file_links.map((fl) => (
            <div key={fl.field_id}>
              <a href={fl.url} target="_blank" rel="noreferrer" style={{ color: '#60a5fa', fontSize: 11, textDecoration: 'none' }}>
                {fl.label} ↗
              </a>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
