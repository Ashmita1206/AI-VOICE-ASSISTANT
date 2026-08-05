import React from 'react';
import { FileEdit, Save, Trash2, ClipboardCopy, ClipboardPaste, RotateCcw, RotateCw, Type, CornerDownLeft, CheckSquare, X } from 'lucide-react';

const NOTEPAD_ACTIONS = [
  { id: 'notepad_open',       label: 'Open',       icon: FileEdit,       color: 'var(--accent-blue-strong)' },
  { id: 'notepad_type',       label: 'Type',       icon: Type,           color: 'var(--accent-blue-strong)' },
  { id: 'notepad_press_enter',label: 'Enter',      icon: CornerDownLeft, color: 'var(--text-secondary)' },
  { id: 'notepad_select_all', label: 'Select All', icon: CheckSquare,    color: 'var(--text-secondary)' },
  { id: 'notepad_copy',       label: 'Copy',       icon: ClipboardCopy,  color: 'var(--text-secondary)' },
  { id: 'notepad_paste',      label: 'Paste',      icon: ClipboardPaste, color: 'var(--text-secondary)' },
  { id: 'notepad_undo',       label: 'Undo',       icon: RotateCcw,      color: 'var(--warning-text)' },
  { id: 'notepad_redo',       label: 'Redo',       icon: RotateCw,       color: 'var(--warning-text)' },
  { id: 'notepad_save',       label: 'Save',       icon: Save,           color: 'var(--success-text)' },
  { id: 'notepad_clear',      label: 'Clear',      icon: Trash2,         color: 'var(--error-text)' },
  { id: 'notepad_close',      label: 'Close',      icon: X,              color: 'var(--error-text)' },
];

export function NotepadControls({ onSendCommand }) {
  const handleAction = (actionId) => {
    if (onSendCommand) {
      onSendCommand(actionId);
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
        Notepad Controls
      </div>
      <div style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: '8px'
      }}>
        {NOTEPAD_ACTIONS.map(({ id, label, icon: Icon, color }) => (
          <button
            key={id}
            onClick={() => handleAction(id)}
            title={label}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 12px',
              borderRadius: 'var(--radius-sm)',
              background: 'var(--surface-primary)',
              border: '1px solid var(--border-soft)',
              color: 'var(--text-primary)',
              fontSize: '0.8rem',
              fontWeight: 500,
              cursor: 'pointer',
              boxShadow: '0 1px 3px rgba(36, 52, 71, 0.04)',
              transition: 'all 200ms ease'
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = 'var(--border-blue)';
              e.currentTarget.style.backgroundColor = 'var(--surface-blue-soft)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = 'var(--border-soft)';
              e.currentTarget.style.backgroundColor = 'var(--surface-primary)';
            }}
          >
            <Icon size={14} color={color} />
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
