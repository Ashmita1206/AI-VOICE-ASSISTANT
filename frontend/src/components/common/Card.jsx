import React from 'react';

export function Card({ title, badge, hint, children, className = '', style = {} }) {
  return (
    <div className={`glass-card animate-fade-in ${className}`} style={{ marginBottom: '16px', ...style }}>
      {title && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: children ? '12px' : '0',
          paddingBottom: hint ? '0' : '8px',
          borderBottom: children ? '1px solid var(--border-soft)' : 'none'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h3 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text-primary)' }}>{title}</h3>
            {badge}
          </div>
        </div>
      )}
      {hint && (
        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '12px' }}>
          {hint}
        </div>
      )}
      {children}
    </div>
  );
}
