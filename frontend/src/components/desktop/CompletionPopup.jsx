import { CheckCircle2, XCircle, AlertCircle } from 'lucide-react';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';

export function CompletionPopup({ popupData, onClose }) {
  if (!popupData) return null;

  const { title, response, summary, error, isError } = popupData;

  return (
    <Modal isOpen={!!popupData} onClose={onClose} title={title || (isError ? 'Task Failed' : 'Task Completed')}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', padding: '4px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {isError ? (
            <XCircle size={32} color="var(--error-text)" />
          ) : (
            <CheckCircle2 size={32} color="var(--success-text)" />
          )}
          <div>
            <div style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text-primary)' }}>
              {response || 'Task processing finished.'}
            </div>
          </div>
        </div>

        {summary && summary.length > 0 && (
          <div style={{ borderTop: '1px solid var(--border-soft)', paddingTop: '12px' }}>
            <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '8px' }}>
              Execution Summary
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {Array.isArray(summary) ? (
                summary.map((item, idx) => (
                  <div key={idx} style={{
                    fontSize: '0.8rem',
                    fontFamily: 'var(--font-mono)',
                    backgroundColor: 'var(--background-secondary)',
                    padding: '8px 12px',
                    borderRadius: 'var(--radius-sm)',
                    color: item.status === 'success' || item.success ? 'var(--success-text)' : 'var(--text-primary)'
                  }}>
                    {typeof item === 'string' ? item : item.log || item.message || JSON.stringify(item)}
                  </div>
                ))
              ) : (
                <pre className="json-pre">{JSON.stringify(summary, null, 2)}</pre>
              )}
            </div>
          </div>
        )}

        {error && (
          <div style={{
            backgroundColor: 'var(--error-background)',
            border: '1px solid #ffcdd2',
            borderRadius: 'var(--radius-sm)',
            padding: '12px'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.85rem', fontWeight: 600, color: 'var(--error-text)', marginBottom: '4px' }}>
              <AlertCircle size={16} /> Error Details
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--error-text)', fontFamily: 'var(--font-mono)' }}>
              {error}
            </div>
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '8px' }}>
          <Button onClick={onClose} variant="primary">
            Close
          </Button>
        </div>
      </div>
    </Modal>
  );
}
