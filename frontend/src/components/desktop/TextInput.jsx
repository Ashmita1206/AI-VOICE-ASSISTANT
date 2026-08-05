import React, { useState } from 'react';
import { Send, Upload } from 'lucide-react';

export function TextInput({ onSubmitText, onFileUpload, isProcessing }) {
  const [text, setText] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (text.trim() && !isProcessing) {
      onSubmitText(text.trim());
      setText('');
    }
  };

  const handleFileChange = (e) => {
    const file = e.target.files?.[0];
    if (file && onFileUpload) {
      onFileUpload(file);
    }
  };

  return (
    <form onSubmit={handleSubmit} style={{
      display: 'flex',
      gap: '10px',
      width: '100%',
      maxWidth: '680px',
      margin: '0 auto'
    }}>
      <input
        type="text"
        placeholder="Type a voice command or request (e.g. 'Open Notepad and type Hello World')..."
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={isProcessing}
        style={{
          flex: 1,
          padding: '12px 18px',
          borderRadius: 'var(--radius-full)',
          background: 'var(--surface-primary)',
          border: '1px solid var(--border-soft)',
          color: 'var(--text-primary)',
          fontSize: '0.9rem',
          outline: 'none',
          boxShadow: '0 2px 6px rgba(36, 52, 71, 0.04)',
          transition: 'border-color 200ms ease'
        }}
      />
      <button
        type="submit"
        disabled={!text.trim() || isProcessing}
        style={{
          width: '42px',
          height: '42px',
          borderRadius: '50%',
          background: 'var(--accent-blue-strong)',
          border: 'none',
          color: '#fff',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: text.trim() && !isProcessing ? 'pointer' : 'not-allowed',
          opacity: text.trim() && !isProcessing ? 1 : 0.5,
          transition: 'all 200ms ease',
          boxShadow: '0 4px 10px rgba(37, 99, 235, 0.2)'
        }}
      >
        <Send size={18} />
      </button>

      <label style={{
        width: '42px',
        height: '42px',
        borderRadius: '50%',
        background: 'var(--surface-primary)',
        border: '1px solid var(--border-soft)',
        color: 'var(--text-secondary)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: 'pointer',
        transition: 'all 200ms ease',
        boxShadow: '0 2px 6px rgba(36, 52, 71, 0.04)'
      }} title="Upload Audio File">
        <Upload size={18} />
        <input
          type="file"
          accept="audio/*"
          onChange={handleFileChange}
          style={{ display: 'none' }}
        />
      </label>
    </form>
  );
}
