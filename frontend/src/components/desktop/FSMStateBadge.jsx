import React from 'react';
import { Badge } from '../common/Badge';

export function FSMStateBadge({ fsmState }) {
  if (!fsmState || fsmState === 'Idle') return null;

  const getVariant = (state) => {
    switch (state.toLowerCase()) {
      case 'listening':
      case 'transcribing':
      case 'understanding':
      case 'planning':
        return 'info';
      case 'executing':
      case 'verifying':
        return 'warning';
      case 'awaiting confirmation':
        return 'warning';
      case 'completed':
        return 'success';
      case 'failed':
      case 'cancelled':
        return 'danger';
      default:
        return 'info';
    }
  };

  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', marginBottom: '12px' }}>
      <span style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-secondary)', fontWeight: 600, letterSpacing: '0.04em' }}>
        Agent State:
      </span>
      <Badge variant={getVariant(fsmState)} pulse={['listening', 'transcribing', 'planning', 'executing'].includes(fsmState.toLowerCase())}>
        {fsmState}
      </Badge>
    </div>
  );
}
