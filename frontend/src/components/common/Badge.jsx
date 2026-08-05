import React from 'react';

export function Badge({ children, variant = 'info', pulse = false }) {
  const getColors = () => {
    switch (variant) {
      case 'success':
        return { bg: 'var(--success-background)', text: 'var(--success-text)', border: '#c8e6c9' };
      case 'warning':
        return { bg: 'var(--warning-background)', text: 'var(--warning-text)', border: '#ffe082' };
      case 'danger':
        return { bg: 'var(--error-background)', text: 'var(--error-text)', border: '#ffcdd2' };
      case 'info':
      default:
        return { bg: 'var(--surface-blue-soft)', text: 'var(--accent-blue-strong)', border: 'var(--border-blue)' };
    }
  };

  const { bg, text, border } = getColors();

  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: '6px',
      padding: '4px 10px',
      borderRadius: 'var(--radius-full)',
      fontSize: '0.75rem',
      fontWeight: 600,
      background: bg,
      color: text,
      border: `1px solid ${border}`,
      letterSpacing: '0.03em'
    }}>
      {pulse && (
        <span style={{
          width: '6px',
          height: '6px',
          borderRadius: '50%',
          backgroundColor: text,
          boxShadow: `0 0 6px ${text}`
        }} />
      )}
      {children}
    </span>
  );
}
