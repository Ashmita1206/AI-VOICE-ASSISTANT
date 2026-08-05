import React from 'react';
import { Globe, Calculator, Terminal, FolderOpen, Settings, MessageSquare, Send, Mail, Music } from 'lucide-react';

const QUICK_SHORTCUTS = [
  { id: 'open_browser',    label: 'Browser',    icon: Globe,         command: 'Open Google Chrome' },
  { id: 'open_calculator', label: 'Calculator',  icon: Calculator,    command: 'Open Calculator' },
  { id: 'open_terminal',   label: 'Terminal',    icon: Terminal,      command: 'Open Command Prompt' },
  { id: 'open_explorer',   label: 'Explorer',    icon: FolderOpen,    command: 'Open File Explorer' },
  { id: 'open_settings',   label: 'Settings',    icon: Settings,      command: 'Open Settings' },
  { id: 'open_whatsapp',   label: 'WhatsApp',    icon: MessageSquare, command: 'Open WhatsApp' },
  { id: 'open_telegram',   label: 'Telegram',    icon: Send,          command: 'Open Telegram' },
  { id: 'open_gmail',      label: 'Gmail',       icon: Mail,          command: 'Open Gmail' },
  { id: 'open_spotify',    label: 'Spotify',     icon: Music,         command: 'Open Spotify' },
];

export function QuickShortcuts({ onSendCommand }) {
  const handleShortcutClick = (shortcut) => {
    if (onSendCommand && shortcut.command) {
      onSendCommand(shortcut.command);
    }
  };

  return (
    <div className="glass-card" style={{ padding: '16px' }}>
      <div style={{
        fontSize: '0.8rem',
        fontWeight: 600,
        color: 'var(--text-secondary)',
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
        marginBottom: '12px'
      }}>
        Quick Launch
      </div>
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(100px, 1fr))',
        gap: '10px'
      }}>
        {QUICK_SHORTCUTS.map((shortcut) => {
          const { id, label, icon: Icon } = shortcut;
          return (
            <button
              key={id}
              onClick={() => handleShortcutClick(shortcut)}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '8px',
                padding: '14px 10px',
                borderRadius: 'var(--radius-md)',
                background: 'var(--surface-primary)',
                border: '1px solid var(--border-soft)',
                color: 'var(--text-primary)',
                fontSize: '0.75rem',
                fontWeight: 600,
                cursor: 'pointer',
                boxShadow: 'var(--shadow-soft)',
                transition: 'all 200ms ease'
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = 'var(--border-blue)';
                e.currentTarget.style.transform = 'translateY(-2px)';
                e.currentTarget.style.boxShadow = '0 6px 16px rgba(37, 99, 235, 0.12)';
                e.currentTarget.style.backgroundColor = 'var(--surface-blue-soft)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = 'var(--border-soft)';
                e.currentTarget.style.transform = 'translateY(0)';
                e.currentTarget.style.boxShadow = 'var(--shadow-soft)';
                e.currentTarget.style.backgroundColor = 'var(--surface-primary)';
              }}
            >
              <Icon size={22} color="var(--accent-blue-strong)" />
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

