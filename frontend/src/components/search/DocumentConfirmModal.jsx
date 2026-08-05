import React from 'react';
import { ShieldAlert } from 'lucide-react';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';

export function DocumentConfirmModal({ docConfirmData, onConfirm, onCancel }) {
  if (!docConfirmData) return null;

  return (
    <Modal isOpen={!!docConfirmData} onClose={onCancel} title="Permission Confirmation" maxWidth="480px">
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <ShieldAlert size={28} color="var(--warning-text)" />
          <div style={{ fontSize: '0.95rem', color: 'var(--text-primary)', lineHeight: 1.5 }}>
            {docConfirmData.message || `Are you sure you want to open this document?`}
          </div>
        </div>

        {docConfirmData.filePath && (
          <div style={{
            backgroundColor: 'var(--background-secondary)',
            padding: '10px 14px',
            borderRadius: 'var(--radius-sm)',
            fontFamily: 'var(--font-mono)',
            fontSize: '0.8rem',
            color: 'var(--text-secondary)',
            wordBreak: 'break-all',
            border: '1px solid var(--border-soft)'
          }}>
            {docConfirmData.filePath}
          </div>
        )}

        <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end', marginTop: '8px' }}>
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => onConfirm && onConfirm(docConfirmData.filePath)}>
            Open
          </Button>
        </div>
      </div>
    </Modal>
  );
}
