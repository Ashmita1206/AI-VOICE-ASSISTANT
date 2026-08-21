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
    isSubmitting,
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

  const isContactConfirm = confirmationData.confirmation_type === 'telegram_confirmation' || confirmationData.confirmation_type === 'telegram_contact_confirmation' || confirmationData.confirmation_type === 'contact_disambiguation';
  const isSendConfirm = confirmationData.confirmation_type === 'telegram_send_confirmation' || confirmationData.confirmation_type === 'final_send_confirmation';
  const isPlanExecutionConfirm = !isContactConfirm && !isSendConfirm;

  const approveLabel = isSendConfirm ? 'Send Message' : (isContactConfirm ? 'Yes, Continue' : 'Approve & Execute');
  const cancelLabel = isSendConfirm ? 'Cancel' : 'No / Cancel';

  const summaryText = confirmationData.message || confirmationData.summary || confirmationData.action || 'I will perform these actions to execute your request:';
  const stepsToDisplay = confirmationData.steps || confirmationData.plan?.steps || [];

  return (
    <div className="glass-card animate-fade-in" style={{
      border: isContactConfirm || isSendConfirm ? '1px solid #0088cc' : '1px solid var(--border-soft)',
      backgroundColor: isContactConfirm || isSendConfirm ? 'rgba(0, 136, 204, 0.08)' : 'rgba(255, 255, 255, 0.03)',
      marginBottom: '20px',
      padding: '20px',
      borderRadius: '12px'
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: isContactConfirm || isSendConfirm ? '#0088cc' : 'var(--warning-text, #f59e0b)', marginBottom: '12px' }}>
        <AlertTriangle size={22} />
        <h3 style={{ fontSize: '1.1rem', fontWeight: 700 }}>
          {isSendConfirm ? 'Telegram Send Confirmation' : (isContactConfirm ? 'Telegram Contact Confirmation' : 'Confirmation Required')}
        </h3>
      </div>

      <div style={{ fontSize: '1.05rem', color: 'var(--text-primary)', marginBottom: '16px', fontWeight: 600 }}>
        {summaryText}
      </div>

      {isContactConfirm && confirmationData.candidates && confirmationData.candidates.length > 1 && (
        <div style={{ marginBottom: '16px', padding: '12px', background: 'rgba(0, 136, 204, 0.05)', borderRadius: '8px', border: '1px solid rgba(0, 136, 204, 0.2)' }}>
          <div style={{ fontSize: '0.85rem', color: '#0088cc', marginBottom: '8px', fontWeight: 600 }}>Available Contacts:</div>
          <ol style={{ paddingLeft: '20px', margin: 0, color: 'var(--text-primary)', fontSize: '0.95rem' }}>
            {confirmationData.candidates.map((c, i) => (
              <li key={i} style={{ marginBottom: '4px' }}>
                {typeof c === 'string' ? c : (c.name || c.display_name || JSON.stringify(c))}
              </li>
            ))}
          </ol>
        </div>
      )}

      {isPlanExecutionConfirm && (
        !isEditingPlan ? (
          <div style={{ marginBottom: '16px' }}>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: 600 }}>Planned Execution Steps:</div>
            <pre className="json-pre">
              {JSON.stringify(stepsToDisplay, null, 2)}
            </pre>
          </div>
        ) : (
          <div style={{ marginBottom: '16px' }}>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: 600 }}>Edit Execution Steps (JSON):</div>
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
        )
      )}

      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center', marginBottom: '16px' }}>
        <Button onClick={handleApprove} variant="primary" icon={CheckCircle} isLoading={isSubmitting} disabled={isSubmitting}>
          {approveLabel}
        </Button>
        <Button onClick={handleCancel} variant="danger" icon={XCircle} disabled={isSubmitting}>
          {cancelLabel}
        </Button>
        {isPlanExecutionConfirm && (
          <Button
            onClick={() => setIsEditingPlan(!isEditingPlan)}
            variant="secondary"
            icon={Edit3}
          >
            {isEditingPlan ? 'View Plan' : 'Edit Plan'}
          </Button>
        )}
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
