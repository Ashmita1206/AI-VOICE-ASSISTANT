import React from 'react';
import { Loader2 } from 'lucide-react';

export function Button({
  children,
  onClick,
  variant = 'primary',
  isLoading = false,
  disabled = false,
  icon: Icon,
  className = '',
  style = {},
  ...props
}) {
  const getVariantStyles = () => {
    switch (variant) {
      case 'primary':
        return {
          background: 'var(--accent-blue-strong)',
          color: '#ffffff',
          border: 'none',
          boxShadow: '0 4px 12px rgba(37, 99, 235, 0.2)',
        };
      case 'secondary':
        return {
          background: 'var(--surface-beige)',
          color: 'var(--text-primary)',
          border: '1px solid var(--border-soft)',
        };
      case 'danger':
        return {
          background: 'var(--error-background)',
          color: 'var(--error-text)',
          border: '1px solid #ffcdd2',
        };
      case 'outline':
        return {
          background: 'var(--surface-primary)',
          color: 'var(--text-primary)',
          border: '1px solid var(--border-soft)',
        };
      default:
        return {};
    }
  };

  return (
    <button
      onClick={onClick}
      disabled={disabled || isLoading}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '8px',
        padding: '10px 18px',
        borderRadius: 'var(--radius-md)',
        fontSize: '0.875rem',
        fontWeight: 600,
        cursor: disabled || isLoading ? 'not-allowed' : 'pointer',
        opacity: disabled || isLoading ? 0.6 : 1,
        transition: 'all 200ms ease',
        ...getVariantStyles(),
        ...style,
      }}
      className={className}
      {...props}
    >
      {isLoading ? (
        <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} />
      ) : Icon ? (
        <Icon size={16} />
      ) : null}
      {children}
    </button>
  );
}
