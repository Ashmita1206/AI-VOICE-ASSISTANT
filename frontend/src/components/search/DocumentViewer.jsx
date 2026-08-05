import React, { useState } from 'react';
import { FileText, ExternalLink } from 'lucide-react';
import { Card } from '../common/Card';

export function DocumentViewer({ filePath }) {
  const [isLoading, setIsLoading] = useState(true);

  if (!filePath) return null;

  const encodedPath = encodeURIComponent(filePath);
  const viewUrl = `/view_document?path=${encodedPath}`;

  return (
    <Card title="Document Preview" hint={filePath}>
      <div style={{ position: 'relative', minHeight: '300px' }}>
        {isLoading && (
          <div style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: 'var(--background-secondary)',
            borderRadius: 'var(--radius-sm)',
            color: 'var(--text-secondary)',
            fontSize: '0.9rem',
            zIndex: 1
          }}>
            <FileText size={20} style={{ marginRight: '8px' }} /> Loading preview...
          </div>
        )}
        <iframe
          src={viewUrl}
          title="Document Preview"
          onLoad={() => setIsLoading(false)}
          style={{
            width: '100%',
            height: '400px',
            border: '1px solid var(--border-soft)',
            borderRadius: 'var(--radius-sm)',
            backgroundColor: '#fff'
          }}
        />
        <div style={{ marginTop: '10px', display: 'flex', justifyContent: 'flex-end' }}>
          <a
            href={viewUrl}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: '0.8rem',
              color: 'var(--accent-blue-strong)',
              textDecoration: 'none',
              fontWeight: 600
            }}
          >
            Open in new tab <ExternalLink size={14} />
          </a>
        </div>
      </div>
    </Card>
  );
}
