import { useState, useEffect, useCallback } from 'react';

export function useConfirmation(confirmationData, onStreamEvent) {
  const [countdown, setCountdown] = useState(60);
  const [isEditingPlan, setIsEditingPlan] = useState(false);
  const [editedPlanJson, setEditedPlanJson] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!confirmationData) {
      setCountdown(60);
      setIsEditingPlan(false);
      setIsSubmitting(false);
      return;
    }

    const initTimeout = confirmationData.timeout || confirmationData.remaining_seconds || 60;
    setCountdown(initTimeout);
    setIsSubmitting(false);
    const initialSteps = confirmationData.steps || confirmationData.plan?.steps || [];
    setEditedPlanJson(JSON.stringify(initialSteps, null, 2));

    const timer = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          clearInterval(timer);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [confirmationData]);

  const submitDecision = useCallback(async (decision) => {
    if (!confirmationData || isSubmitting) return;

    let parsedSteps = null;
    if (decision === 'proceed' && isEditingPlan && editedPlanJson.trim()) {
      try {
        parsedSteps = JSON.parse(editedPlanJson);
      } catch (err) {
        alert('Invalid JSON format in edited plan steps.');
        return;
      }
    }

    try {
      setIsSubmitting(true);
      const response = await fetch('/confirm?stream=true', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
        body: JSON.stringify({
          confirmation_id: confirmationData.id,
          decision,
          edited_steps: parsedSteps,
        }),
      });

      if (!response.ok) {
        throw new Error(`Confirmation error: ${response.statusText}`);
      }

      if (response.headers.get('Content-Type')?.includes('text/event-stream')) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          const lines = buffer.split('\n\n');
          buffer = lines.pop();

          for (const block of lines) {
            const line = block.trim();
            if (line.startsWith('data:')) {
              try {
                const eventObj = JSON.parse(line.replace(/^data:\s*/, ''));
                if (onStreamEvent) onStreamEvent(eventObj);
              } catch (err) {
                console.warn('[CONFIRM SSE] Parse error:', err);
              }
            }
          }
        }
      } else {
        const result = await response.json();
        if (onStreamEvent) {
          if (decision === 'cancel') {
            onStreamEvent({ stage: 'done', status: 'cancelled', message: result.message || 'Action cancelled.' });
          } else {
            onStreamEvent({ stage: 'completed', result });
          }
        }
      }
    } catch (err) {
      console.error('[CONFIRM] Failed to send decision:', err);
    } finally {
      setIsSubmitting(false);
    }
  }, [confirmationData, isSubmitting, isEditingPlan, editedPlanJson, onStreamEvent]);

  return {
    countdown,
    isEditingPlan,
    setIsEditingPlan,
    editedPlanJson,
    setEditedPlanJson,
    isSubmitting,
    submitDecision,
  };
}
