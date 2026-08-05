import { useEffect, useRef } from 'react';

/**
 * Custom hook to reset the UI to clean Home state after 60 seconds of inactivity
 * following task completion or failure.
 */
export function useInactivityReset({
  isTerminalState,
  isBlocked,
  onReset,
  timeoutMs = 60000
}) {
  const timerRef = useRef(null);

  useEffect(() => {
    // Do not run inactivity timer if task is active/recording/awaiting confirmation
    if (isBlocked || !isTerminalState) {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      return;
    }

    const resetTimer = () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
      timerRef.current = setTimeout(() => {
        if (onReset) {
          onReset();
        }
      }, timeoutMs);
    };

    // Start timer initially when entering terminal state
    resetTimer();

    // Listen to user interactions to reset timer
    const activityEvents = ['mousemove', 'keydown', 'click', 'scroll', 'touchstart'];
    const handleUserActivity = () => {
      resetTimer();
    };

    activityEvents.forEach((event) => {
      window.addEventListener(event, handleUserActivity, { passive: true });
    });

    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      activityEvents.forEach((event) => {
        window.removeEventListener(event, handleUserActivity);
      });
    };
  }, [isTerminalState, isBlocked, onReset, timeoutMs]);
}
