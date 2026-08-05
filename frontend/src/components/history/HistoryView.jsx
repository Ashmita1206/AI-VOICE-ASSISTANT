import React, { useEffect, useState } from 'react';
import { ChevronDown, Trash2, Clock } from 'lucide-react';
import { useHistory } from '../../hooks/useHistory';

function escapeHtml(str) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' };
  return String(str).replace(/[&<>"]/g, (c) => map[c]);
}

function syntaxHighlightJson(json) {
  return json.replace(
    /("(\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g,
    (match) => {
      let cls = 'json-number';
      if (/^"/.test(match)) cls = /:$/.test(match) ? 'json-key' : 'json-string';
      else if (/true|false/.test(match)) cls = 'json-boolean';
      else if (/null/.test(match)) cls = 'json-null';
      return `<span class="${cls}">${match}</span>`;
    }
  );
}

function groupByDate(sessions) {
  const groups = {};
  sessions.forEach((s) => {
    const d = new Date(s.timestamp);
    const key = d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
    if (!groups[key]) groups[key] = [];
    groups[key].push(s);
  });
  return groups;
}

function DetailRow({ label, children }) {
  return (
    <div style={{ display: 'flex', gap: '12px', marginBottom: '10px', fontSize: '0.85rem' }}>
      <div style={{ width: '120px', flexShrink: 0, color: 'var(--text-secondary)', fontWeight: 600 }}>{label}</div>
      <div style={{ flex: 1, color: 'var(--text-primary)' }}>{children}</div>
    </div>
  );
}

export function HistoryView() {
  const { history, isLoading, error, fetchHistory, deleteSession } = useHistory();
  const [expandedId, setExpandedId] = useState(null);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  if (isLoading) {
    return (
      <div style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: '40px' }}>
        Loading sessions...
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ textAlign: 'center', color: 'var(--error-text)', padding: '40px' }}>
        {error}
      </div>
    );
  }

  if (!history || history.length === 0) {
    return (
      <div style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: '40px' }}>
        No history found. Start talking to your assistant!
      </div>
    );
  }

  const grouped = groupByDate(history);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {Object.entries(grouped).map(([date, items]) => (
        <div key={date}>
          <div style={{
            fontSize: '0.8rem',
            fontWeight: 600,
            color: 'var(--text-secondary)',
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
            marginBottom: '10px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}>
            <Clock size={14} /> {date}
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {items.map((s) => {
              const isExpanded = expandedId === s.session_id;
              const time = new Date(s.timestamp).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });

              return (
                <div key={s.session_id} className="glass-card" style={{ padding: '0', overflow: 'hidden' }}>
                  <div
                    onClick={() => setExpandedId(isExpanded ? null : s.session_id)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '14px 18px',
                      cursor: 'pointer',
                      transition: 'background 200ms ease',
                      backgroundColor: 'var(--surface-primary)'
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-blue-soft)'; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = 'var(--surface-primary)'; }}
                  >
                    <div>
                      <div style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                        {escapeHtml(s.transcript || 'No speech detected')}
                      </div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '4px' }}>{time}</div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          deleteSession(s.session_id);
                        }}
                        title="Delete session"
                        style={{
                          background: 'transparent',
                          border: 'none',
                          color: 'var(--text-muted)',
                          cursor: 'pointer',
                          padding: '4px'
                        }}
                      >
                        <Trash2 size={14} />
                      </button>
                      <ChevronDown
                        size={16}
                        color="var(--text-secondary)"
                        style={{
                          transform: isExpanded ? 'rotate(180deg)' : 'rotate(0)',
                          transition: 'transform 200ms ease'
                        }}
                      />
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="animate-fade-in" style={{ padding: '0 18px 18px', borderTop: '1px solid var(--border-soft)', paddingTop: '14px', backgroundColor: 'var(--surface-primary)' }}>
                      <DetailRow label="Transcript">{s.transcript || '-'}</DetailRow>
                      <DetailRow label="Language">{(s.language || '-').toUpperCase()}</DetailRow>
                      <DetailRow label="Confidence">{s.stt_confidence != null ? `${s.stt_confidence}%` : '-'}</DetailRow>
                      <DetailRow label="Intent">
                        <span style={{
                          display: 'inline-block',
                          padding: '3px 10px',
                          borderRadius: 'var(--radius-full)',
                          fontSize: '0.8rem',
                          fontWeight: 600,
                          background: 'var(--surface-blue-soft)',
                          color: 'var(--accent-blue-strong)',
                          border: '1px solid var(--border-blue)'
                        }}>
                          {s.intent || 'unknown'}
                        </span>
                      </DetailRow>
                      <DetailRow label="Entities">
                        <pre className="json-pre" dangerouslySetInnerHTML={{ __html: syntaxHighlightJson(JSON.stringify(s.entities || {}, null, 2)) }} />
                      </DetailRow>
                      <DetailRow label="Planner">
                        <pre className="json-pre" dangerouslySetInnerHTML={{ __html: syntaxHighlightJson(JSON.stringify(s.planner_output || {}, null, 2)) }} />
                      </DetailRow>
                      <DetailRow label="Execution">
                        <pre className="json-pre" dangerouslySetInnerHTML={{ __html: syntaxHighlightJson(JSON.stringify(s.execution_logs || [], null, 2)) }} />
                      </DetailRow>
                      <DetailRow label="Response">
                        <em style={{ color: 'var(--text-secondary)' }}>{s.response_text || '-'}</em>
                      </DetailRow>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
