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
        {/* Brand: Minimal Logo + Buddy + Subtitle + Online Status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          {/* Minimal Rounded Logo Icon */}
          <div style={{
            width: '28px',
            height: '28px',
            borderRadius: '8px',
            background: 'var(--accent-blue-strong)',
            color: '#FFFFFF',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 2px 8px rgba(37, 99, 235, 0.25)',
            flexShrink: 0,
          }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
              <line x1="12" y1="19" x2="12" y2="22" />
            </svg>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.1 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.01em' }}>
                Buddy
              </span>
              <span style={{
                width: '7px',
                height: '7px',
                borderRadius: '50%',
                backgroundColor: 'var(--success-text)',
                boxShadow: '0 0 6px rgba(46, 125, 50, 0.4)'
              }} title="System Ready" />
            </div>
            <span style={{ fontSize: '0.68rem', fontWeight: 500, color: 'var(--text-secondary)', letterSpacing: '0.01em' }}>
              Your Voice Assistant
            </span>
          </div>
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
