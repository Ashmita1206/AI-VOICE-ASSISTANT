import React from 'react';
import { AlertTriangle, CheckCircle, XCircle, Edit3 } from 'lucide-react';
import { Button } from '../common/Button';
import { useConfirmation } from '../../hooks/useConfirmation';

export function ConfirmationCard({ confirmationData, onDecision, onStreamEvent }) {
  const {
    countdown,
    isEditingPlan,
    setIsEditingPlan,
    editedPlanJson,
    setEditedPlanJson,
    submitDecision,
  } = useConfirmation(confirmationData, onStreamEvent);

  if (!confirmationData) return null;

  const progressPercent = Math.max(0, Math.min(100, (countdown / (confirmationData.timeout || 60)) * 100));

  const handleApprove = () => {
    submitDecision('proceed');
    if (onDecision) onDecision('proceed');
  };

  const handleCancel = () => {
    submitDecision('cancel');
    if (onDecision) onDecision('cancel');
  };

  return (
    <div className="glass-card animate-fade-in" style={{
      border: '1px solid #ffe082',
      backgroundColor: 'var(--surface-yellow-soft)',
      marginBottom: '20px',
      padding: '20px'
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--warning-text)', marginBottom: '12px' }}>
        <AlertTriangle size={22} />
        <h3 style={{ fontSize: '1.1rem', fontWeight: 600 }}>Confirmation Required</h3>
      </div>

      <div style={{ fontSize: '0.95rem', color: 'var(--text-primary)', marginBottom: '12px' }}>
        <strong>Action:</strong> {confirmationData.summary || confirmationData.action}
      </div>

      {!isEditingPlan ? (
        <div style={{ marginBottom: '16px' }}>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '6px' }}>Planned Execution Steps:</div>
          <pre className="json-pre">
            {JSON.stringify(confirmationData.steps || [], null, 2)}
          </pre>
        </div>
      ) : (
        <div style={{ marginBottom: '16px' }}>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '6px' }}>Edit Execution Steps (JSON):</div>
          <textarea
            value={editedPlanJson}
            onChange={(e) => setEditedPlanJson(e.target.value)}
            style={{
              width: '100%',
              height: '160px',
              padding: '10px',
              fontFamily: 'var(--font-mono)',
              fontSize: '0.85rem',
              backgroundColor: 'var(--surface-primary)',
              color: 'var(--text-primary)',
              border: '1px solid var(--border-soft)',
              borderRadius: 'var(--radius-sm)',
              outline: 'none'
            }}
          />
        </div>
      )}

      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center', marginBottom: '16px' }}>
        <Button onClick={handleApprove} variant="primary" icon={CheckCircle}>
          Approve & Execute
        </Button>
        <Button onClick={handleCancel} variant="danger" icon={XCircle}>
          Cancel
        </Button>
        <Button
          onClick={() => setIsEditingPlan(!isEditingPlan)}
          variant="secondary"
          icon={Edit3}
        >
          {isEditingPlan ? 'View Plan' : 'Edit Plan'}
        </Button>
      </div>

      {/* Countdown Timer Bar */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '4px' }}>
          <span>Auto-cancel countdown</span>
          <span style={{ fontWeight: 600, color: 'var(--warning-text)' }}>{countdown}s</span>
        </div>
        <div style={{ width: '100%', height: '6px', backgroundColor: '#fff8e1', borderRadius: 'var(--radius-full)', overflow: 'hidden', border: '1px solid #ffe082' }}>
          <div style={{
            height: '100%',
            width: `${progressPercent}%`,
            backgroundColor: 'var(--warning-text)',
            transition: 'width 1s linear'
          }} />
        </div>
      </div>
    </div>
  );
}
