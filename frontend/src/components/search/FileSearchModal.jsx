import React from 'react';
import { FileText, FolderOpen, ExternalLink } from 'lucide-react';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';

export function FileSearchModal({ fileSearchData, onClose, onOpenResult }) {
  if (!fileSearchData) return null;

  const { query, results, voicePrompt } = fileSearchData;

  return (
    <Modal isOpen={!!fileSearchData} onClose={onClose} title="I found the following matching files:" maxWidth="620px">
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '20px' }}>
        {results && results.length > 0 ? (
          results.map((result, idx) => (
            <div
              key={idx}
              className="glass-card"
              style={{
                padding: '14px',
                cursor: 'pointer',
                border: '1px solid var(--border-soft)',
                borderRadius: 'var(--radius-md)',
                backgroundColor: 'var(--surface-primary)',
                boxShadow: 'var(--shadow-soft)',
                transition: 'all 200ms ease',
              }}
              onClick={() => onOpenResult && onOpenResult(result, idx + 1)}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = 'var(--border-blue)';
                e.currentTarget.style.backgroundColor = 'var(--surface-blue-soft)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = 'var(--border-soft)';
                e.currentTarget.style.backgroundColor = 'var(--surface-primary)';
              }}
            >
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
                <div style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: 'var(--radius-sm)',
                  background: 'var(--surface-blue)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                  color: 'var(--accent-blue-strong)',
                  fontWeight: 700,
                  fontSize: '0.85rem'
                }}>
                  {idx + 1}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <FileText size={14} />
                    {result.filename || result.name || `Result ${idx + 1}`}
                  </div>
                  {result.path && (
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {result.path}
                    </div>
                  )}
                  {result.snippet && (
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '6px', lineHeight: 1.4 }}>
                      {result.snippet}
                    </div>
                  )}
                  {result.score != null && (
                    <div style={{ fontSize: '0.7rem', color: 'var(--accent-blue-strong)', marginTop: '4px', fontWeight: 600 }}>
                      Relevance: {(result.score * 100).toFixed(0)}%
                    </div>
                  )}
                </div>
                <ExternalLink size={16} color="var(--text-muted)" style={{ flexShrink: 0, marginTop: '4px' }} />
              </div>
            </div>
          ))
        ) : (
          <div style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: '20px' }}>
            No matching files found for "{query}".
          </div>
        )}
      </div>

      {voicePrompt && (
        <div style={{ borderTop: '1px solid var(--border-soft)', paddingTop: '14px' }}>
          <div style={{ fontWeight: 500, fontSize: '0.9rem', color: 'var(--text-primary)', marginBottom: '10px' }}>
            Speak or type:
          </div>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            {results && results.map((_, idx) => (
              <Button
                key={idx}
                variant="outline"
                onClick={() => onOpenResult && onOpenResult(results[idx], idx + 1)}
                style={{ fontSize: '0.8rem', padding: '6px 14px' }}
              >
                Open #{idx + 1}
              </Button>
            ))}
            <Button variant="outline" onClick={onClose} style={{ fontSize: '0.8rem', padding: '6px 14px' }}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
