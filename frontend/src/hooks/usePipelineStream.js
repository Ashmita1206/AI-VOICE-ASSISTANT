import { useState, useRef, useCallback } from 'react';

export function usePipelineStream() {
  const [fsmState, setFsmState] = useState('Idle');
  const [statusMessage, setStatusMessage] = useState('');
  const [transcript, setTranscript] = useState('');
  const [accuracy, setAccuracy] = useState(null);
  const [intent, setIntent] = useState('');
  const [entities, setEntities] = useState(null);
  const [plannerOutput, setPlannerOutput] = useState(null);
  const [executionLogs, setExecutionLogs] = useState([]);
  const [responseText, setResponseText] = useState('');
  const [audioUrl, setAudioUrl] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);

  const [confirmationData, setConfirmationData] = useState(null);
  const [fileSearchData, setFileSearchData] = useState(null);
  const [docConfirmData, setDocConfirmData] = useState(null);
  const [completionPopup, setCompletionPopup] = useState(null);

  const abortControllerRef = useRef(null);

  const resetResults = useCallback(() => {
    setTranscript('');
    setAccuracy(null);
    setIntent('');
    setEntities(null);
    setPlannerOutput(null);
    setExecutionLogs([]);
    setResponseText('');
    setAudioUrl('');
    setConfirmationData(null);
    setFileSearchData(null);
    setDocConfirmData(null);
    setCompletionPopup(null);
  }, []);

  const handleEventData = useCallback((data) => {
    if (!data) return;

    if (data.fsm_state) {
      setFsmState(data.fsm_state);
    }
    if (data.status_message) {
      setStatusMessage(data.status_message);
    }

    const payload = data.data || {};
    const stage = data.stage;

    switch (stage) {
      case 'transcribing':
      case 'transcript': {
        const textVal = data.transcript || payload.text || payload.transcription;
        if (textVal) setTranscript(textVal);

        const sttObj = payload.stt || payload.stt_metrics || data.stt;
        if (sttObj) {
          setAccuracy({
            model: sttObj.model || 'Faster-Whisper',
            confidence: sttObj.confidence != null ? (typeof sttObj.confidence === 'number' ? `${sttObj.confidence}%` : String(sttObj.confidence)) : 'N/A',
            processingTime: sttObj.processing_time_ms != null ? `${(sttObj.processing_time_ms / 1000).toFixed(2)}s` : (sttObj.processingTime || 'N/A'),
          });
        } else if (data.model || data.confidence != null) {
          setAccuracy({
            model: data.model || 'Faster-Whisper',
            confidence: data.confidence != null ? (typeof data.confidence === 'number' && data.confidence <= 1 ? `${(data.confidence * 100).toFixed(1)}%` : `${data.confidence}%`) : 'N/A',
            processingTime: data.time != null ? `${data.time.toFixed(2)}s` : 'N/A',
          });
        }
        break;
      }

      case 'intent': {
        const intentVal = payload.name || payload.intent || data.intent;
        if (intentVal) setIntent(intentVal);
        if (payload.entities) setEntities(payload.entities);
        if (data.entities) setEntities(data.entities);
        break;
      }

      case 'entities': {
        const entObj = payload.entities !== undefined ? payload.entities : (data.entities !== undefined ? data.entities : payload);
        if (entObj !== undefined && entObj !== null) setEntities(entObj);
        break;
      }

      case 'planner': {
        const planObj = payload.planner || (payload.steps || payload.reasoning || payload.thought ? payload : data.planner);
        if (planObj) setPlannerOutput(planObj);
        break;
      }

      case 'confirmation': {
        const confObj = payload.confirmation || (payload.id ? payload : null) || data.confirmation;
        if (confObj && (confObj.id || data.confirmation_id)) {
          setConfirmationData({
            id: confObj.id || data.confirmation_id,
            action: confObj.message || data.action_name || 'Action Execution',
            summary: confObj.message || data.action_summary || 'Confirmation Required',
            steps: confObj.plan?.steps || data.steps || confObj.estimated_actions || [],
            timeout: confObj.remaining_seconds || data.timeout_seconds || 60,
          });
          setFsmState('Awaiting Confirmation');
          setIsProcessing(false);
        }
        break;
      }

      case 'execution': {
        if (data.execution_step || data.log || payload.log || payload.execution_step) {
          const logItem = data.log || data.execution_step || payload.log || payload.execution_step;
          setExecutionLogs((prev) => [...prev, logItem]);
        }
        if (payload.logs || data.logs) {
          setExecutionLogs(payload.logs || data.logs);
        }
        const execSteps = payload.steps || data.steps || [];
        for (const step of execSteps) {
          const stepData = step.data || step.result?.data || {};
          if (stepData.results && Array.isArray(stepData.results)) {
            setFileSearchData({
              query: stepData.query || '',
              results: stepData.results,
              voicePrompt: stepData.voice_prompt || '',
            });
          }
        }
        break;
      }

      case 'file_search':
        if (payload.file_results || payload.results || data.file_results || data.results) {
          setFileSearchData({
            query: payload.query || data.query,
            results: payload.file_results || payload.results || data.file_results || data.results,
            voicePrompt: payload.voice_prompt || data.voice_prompt,
          });
        }
        break;

      case 'doc_confirm':
        if (payload.file_path || data.file_path) {
          setDocConfirmData({
            filePath: payload.file_path || data.file_path,
            title: payload.title || data.title || 'Permission Confirmation',
            message: payload.message || data.message || `Are you sure you want to open ${payload.file_path || data.file_path}?`,
          });
        }
        break;

      case 'response': {
        const respText = payload.text || payload.response_text || data.response_text;
        if (respText) setResponseText(respText);
        const url = payload.audio_url || data.audio_url;
        if (url) setAudioUrl(url);
        break;
      }

      case 'done':
      case 'completed': {
        const confObj = payload.confirmation || (payload.data && payload.data.confirmation);
        if (data.status === 'requires_confirmation' || confObj) {
          const conf = confObj || data;
          setConfirmationData({
            id: conf.id || data.confirmation_id,
            action: conf.message || data.action_name || 'Action Execution',
            summary: conf.message || data.action_summary || 'Confirmation Required',
            steps: conf.plan?.steps || data.steps || conf.estimated_actions || [],
            timeout: conf.remaining_seconds || data.timeout_seconds || 60,
          });
          setFsmState('Awaiting Confirmation');
          setIsProcessing(false);
          break;
        }
        setIsProcessing(false);
        setFsmState('Completed');

        if (payload) {
          if (payload.transcription && !transcript) setTranscript(payload.transcription);
          if (payload.stt && !accuracy) {
            setAccuracy({
              model: payload.stt.model || 'Faster-Whisper',
              confidence: payload.stt.confidence != null ? `${payload.stt.confidence}%` : 'N/A',
              processingTime: payload.stt.processing_time_ms != null ? `${(payload.stt.processing_time_ms / 1000).toFixed(2)}s` : 'N/A',
            });
          }
          if (payload.intent) {
            const intVal = typeof payload.intent === 'object' ? payload.intent.name || payload.intent.intent : payload.intent;
            if (intVal) setIntent(intVal);
          }
          if (payload.entities !== undefined && payload.entities !== null) {
            setEntities(payload.entities);
          }
          if (payload.planner) setPlannerOutput(payload.planner);
          if (payload.execution && Array.isArray(payload.execution) && payload.execution.length > 0) {
            setExecutionLogs(payload.execution);
          }
          if (payload.speech) {
            if (payload.speech.text) setResponseText(payload.speech.text);
            if (payload.speech.audio_url) setAudioUrl(payload.speech.audio_url);
          }
        }

        const speechObj = payload.speech || {};
        const respText = data.response_text || speechObj.text || data.message || payload.text;
        if (respText) setResponseText(respText);
        if (speechObj.audio_url) setAudioUrl(speechObj.audio_url);

        const doneExecSteps = payload.execution || data.execution || [];
        if (Array.isArray(doneExecSteps)) {
          for (const step of doneExecSteps) {
            const stepData = step.data || step.result?.data || {};
            if (stepData.results && Array.isArray(stepData.results)) {
              setFileSearchData({
                query: stepData.query || '',
                results: stepData.results,
                voicePrompt: stepData.voice_prompt || '',
              });
            }
          }
        }

        if (respText || data.summary || payload.summary) {
          setCompletionPopup({
            title: data.status === 'error' ? 'Task Failed' : 'Task Completed',
            response: respText || 'Action executed.',
            summary: data.summary || payload.summary || data.logs || [],
            error: data.error || (data.status === 'error' ? data.message : null),
            isError: data.status === 'error',
          });
        }
        break;
      }

      default:
        break;
    }
  }, [accuracy, transcript]);

  const sendPipelineRequest = useCallback(async ({ audioBlob, textInput }) => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();

    resetResults();
    setIsProcessing(true);
    setFsmState('Transcribing');
    setStatusMessage('Streaming request to assistant server...');

    const formData = new FormData();
    if (audioBlob) {
      formData.append('audio', audioBlob, 'recording.webm');
    } else if (textInput) {
      formData.append('text', textInput);
    } else {
      setIsProcessing(false);
      return;
    }

    try {
      const response = await fetch('/transcribe_stream', {
        method: 'POST',
        body: formData,
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status} ${response.statusText}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n\n');
        buffer = lines.pop(); // keep remaining unfinished line in buffer

        for (const block of lines) {
          const line = block.trim();
          if (line.startsWith('data:')) {
            const jsonStr = line.replace(/^data:\s*/, '');
            try {
              const eventObj = JSON.parse(jsonStr);
              handleEventData(eventObj);
            } catch (err) {
              console.warn('[SSE] JSON parse error:', err, jsonStr);
            }
          }
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        console.error('[PIPELINE] Stream error:', err);
        setFsmState('Failed');
        setStatusMessage(`Pipeline error: ${err.message}`);
      }
      setIsProcessing(false);
    }
  }, [handleEventData, resetResults]);

  const resetState = useCallback(() => {
    resetResults();
    setFsmState('Idle');
    setStatusMessage('');
    setIsProcessing(false);
  }, [resetResults]);

  return {
    fsmState,
    statusMessage,
    transcript,
    accuracy,
    intent,
    entities,
    plannerOutput,
    executionLogs,
    responseText,
    audioUrl,
    isProcessing,
    confirmationData,
    setConfirmationData,
    fileSearchData,
    setFileSearchData,
    docConfirmData,
    setDocConfirmData,
    completionPopup,
    setCompletionPopup,
    sendPipelineRequest,
    resetResults,
    resetState,
    handleEventData,
  };
}
