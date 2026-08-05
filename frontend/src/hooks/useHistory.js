import { useState, useCallback } from 'react';

export function useHistory() {
  const [history, setHistory] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchHistory = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch('/history');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setHistory(data || []);
    } catch (err) {
      console.error('[HISTORY] Fetch error:', err);
      setError('Failed to load session history.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  const deleteSession = useCallback(async (sessionId) => {
    try {
      const res = await fetch(`/session/${sessionId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Delete failed');
      setHistory((prev) => prev.filter((s) => s.session_id !== sessionId));
    } catch (err) {
      console.error('[HISTORY] Delete error:', err);
    }
  }, []);

  return {
    history,
    isLoading,
    error,
    fetchHistory,
    deleteSession,
  };
}
