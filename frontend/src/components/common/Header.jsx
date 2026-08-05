import React from 'react';
import { Mic, Clock } from 'lucide-react';

export function Header({ activeTab, setActiveTab }) {
  return (
    <header style={{
      position: 'sticky',
      top: 0,
      left: 0,
      right: 0,
      width: '100%',
      zIndex: 100,
      background: 'rgba(255, 255, 255, 0.95)',
      backdropFilter: 'blur(8px)',
      borderBottom: '1px solid var(--border-soft)',
      margin: 0,
      padding: '0 24px',
    }}>
      <div style={{
        maxWidth: '1040px',
        margin: '0 auto',
        height: '48px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        {/* Title + Green Online Status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <h1 style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--text-primary)', margin: 0, letterSpacing: '-0.01em' }}>
            AI Voice Assistant
          </h1>
          <span style={{
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            backgroundColor: 'var(--success-text)',
            boxShadow: '0 0 6px rgba(46, 125, 50, 0.4)'
          }} title="System Ready" />
        </div>

        {/* Right side: Nav tabs */}
        <nav style={{ display: 'flex', gap: '4px' }}>
          <button
            onClick={() => setActiveTab('assistant')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '5px 12px',
              borderRadius: 'var(--radius-md)',
              border: activeTab === 'assistant' ? '1px solid var(--border-blue)' : '1px solid transparent',
              background: activeTab === 'assistant' ? 'var(--surface-blue)' : 'transparent',
              color: activeTab === 'assistant' ? 'var(--accent-blue-strong)' : 'var(--text-secondary)',
              fontWeight: 600,
              fontSize: '0.8rem',
              cursor: 'pointer',
              transition: 'all 150ms ease'
            }}
          >
            <Mic size={14} /> Assistant
          </button>

          <button
            onClick={() => setActiveTab('history')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '5px 12px',
              borderRadius: 'var(--radius-md)',
              border: activeTab === 'history' ? '1px solid var(--border-blue)' : '1px solid transparent',
              background: activeTab === 'history' ? 'var(--surface-blue)' : 'transparent',
              color: activeTab === 'history' ? 'var(--accent-blue-strong)' : 'var(--text-secondary)',
              fontWeight: 600,
              fontSize: '0.8rem',
              cursor: 'pointer',
              transition: 'all 150ms ease'
            }}
          >
            <Clock size={14} /> History
          </button>
        </nav>
      </div>
    </header>
  );
}
