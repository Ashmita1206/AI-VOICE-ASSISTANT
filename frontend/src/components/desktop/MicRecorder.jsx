import React from 'react';
import { Mic, Square } from 'lucide-react';
import { Button } from '../common/Button';

export function MicRecorder({ isRecording, micStatusText, recordingDuration, onStart, onStop }) {
  const formatDuration = (secs) => {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}:${s < 10 ? '0' : ''}${s}`;
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px' }}>
      <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
        {!isRecording ? (
          <Button
            onClick={onStart}
            variant="primary"
            icon={Mic}
            style={{
              padding: '14px 34px',
              fontSize: '1.05rem',
              fontWeight: 700,
              borderRadius: 'var(--radius-full)',
              background: '#1F2937',
              color: '#FFFFFF',
              boxShadow: '0 8px 24px rgba(31, 41, 55, 0.25)',
              border: '1px solid #111827',
              letterSpacing: '0.02em',
              transition: 'all 200ms ease',
            }}
          >
            Record Audio
          </Button>
        ) : (
          <Button
            onClick={onStop}
            variant="danger"
            icon={Square}
            style={{
              padding: '14px 34px',
              fontSize: '1.05rem',
              fontWeight: 700,
              borderRadius: 'var(--radius-full)',
              background: '#DC2626',
              color: '#FFFFFF',
              boxShadow: '0 8px 24px rgba(220, 38, 38, 0.3)',
              border: '1px solid #B91C1C',
              animation: 'pulse-ring 1.5s infinite'
            }}
          >
            Stop Recording ({formatDuration(recordingDuration)})
          </Button>
        )}
      </div>

      {micStatusText && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          fontSize: '0.85rem',
          fontWeight: 600,
          color: isRecording ? 'var(--error-text)' : '#1F2937'
        }}>
          <span className="pulse-dot" style={{ backgroundColor: isRecording ? 'var(--error-text)' : '#1F2937' }} />
          <span>{micStatusText}</span>
        </div>
      )}
    </div>
  );
}
