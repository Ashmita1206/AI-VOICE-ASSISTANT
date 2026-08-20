import { useState, useRef, useCallback } from 'react';

export function usePipelineStream() {
  const [fsmState, setFsmState] = useState('Idle');
  const [statusMessage, setStatusMessage] = useState('');
  const [transcript, setTranscript] = useState('');
  const [translatedText, setTranslatedText] = useState('');
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
    setTranslatedText('');
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
    const status = data.status;

    switch (stage) {
      case 'transcribing':
      case 'transcript': {
        if (status === 'processing') {
          setFsmState('Transcribing');
          setStatusMessage('Processing request...');
        } else if (status === 'completed') {
          setFsmState('Understanding');
          setStatusMessage('Processing request...');
        }
        const textVal = data.transcript || payload.text || payload.transcription;
        if (textVal) setTranscript(textVal);

        const transVal = payload.translated_text || data.translated_text;
        if (transVal) setTranslatedText(transVal);

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
        setFsmState('Understanding');
        setStatusMessage('Processing request...');
        const intentVal = payload.name || payload.intent || data.intent;
        if (intentVal) setIntent(intentVal);
        if (payload.entities) setEntities(payload.entities);
        if (data.entities) setEntities(data.entities);
        break;
      }

      case 'entities': {
        setFsmState('Understanding');
        setStatusMessage('Processing request...');
        const entObj = payload.entities !== undefined ? payload.entities : (data.entities !== undefined ? data.entities : payload);
        if (entObj !== undefined && entObj !== null) setEntities(entObj);
        break;
      }

      case 'discovery': {
        setFsmState('Planning');
        setStatusMessage('Processing request...');
        break;
      }

      case 'planner': {
        if (status === 'failed') {
          setFsmState('Failed');
          setStatusMessage('Failed');
          setIsProcessing(false);
        } else {
          setFsmState('Planning');
          setStatusMessage('Processing request...');
        }
        const planObj = payload.planner || (payload.steps || payload.reasoning || payload.thought ? payload : data.planner);
        if (planObj) setPlannerOutput(planObj);
        break;
      }

      case 'confirmation': {
        const confObj = payload.confirmation || (payload.id ? payload : null) || data.confirmation;
        if (confObj && (confObj.id || data.confirmation_id)) {
          setConfirmationData({
            id: confObj.id || data.confirmation_id,
            confirmation_type: confObj.confirmation_type || data.confirmation_type || null,
            action: confObj.message || data.action_name || 'Action Execution',
            summary: confObj.message || data.action_summary || 'Confirmation Required',
            message: confObj.message || data.message,
            contact: confObj.contact || data.contact,
            message_text: confObj.message_text || data.message_text,
            steps: confObj.plan?.steps || data.steps || confObj.steps || confObj.estimated_actions || [],
            timeout: confObj.remaining_seconds || data.timeout_seconds || 60,
          });
          setFsmState('Awaiting Confirmation');
          setStatusMessage('Awaiting Confirmation');
          setIsProcessing(false);
        }
        break;
      }

      case 'execution': {
        if (status === 'running') {
          setFsmState('Executing');
          setStatusMessage('Executing...');
        } else if (status === 'failed' || status === 'error') {
          setFsmState('Failed');
          setStatusMessage('Failed');
          setIsProcessing(false);
        } else if (status === 'completed') {
          setFsmState('Executing');
          setStatusMessage('Executing...');
        }

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
        if (status === 'processing') {
          setStatusMessage('Processing request...');
        }
        const respText = payload.text || payload.response_text || data.response_text;
        if (respText) setResponseText(respText);
        const url = payload.audio_url || data.audio_url;
        if (url) setAudioUrl(url);
        break;
      }

      case 'done':
      case 'completed': {
        const confObj = payload.confirmation || (payload.data && payload.data.confirmation);
        if (status === 'requires_confirmation' || confObj) {
          const conf = confObj || data;
          setConfirmationData({
            id: conf.id || data.confirmation_id,
            confirmation_type: conf.confirmation_type || data.confirmation_type || null,
            action: conf.message || data.action_name || 'Action Execution',
            summary: conf.message || data.action_summary || 'Confirmation Required',
            message: conf.message || data.message,
            contact: conf.contact || data.contact,
            message_text: conf.message_text || data.message_text,
            steps: conf.plan?.steps || data.steps || conf.steps || conf.estimated_actions || [],
            timeout: conf.remaining_seconds || data.timeout_seconds || 60,
          });
          setFsmState('Awaiting Confirmation');
          setStatusMessage('Awaiting Confirmation');
          setIsProcessing(false);
          break;
        }

        if (status === 'error' || status === 'failed' || payload.status === 'error') {
          setFsmState('Failed');
          setStatusMessage('Failed');
          setIsProcessing(false);
        } else if (status === 'cancelled' || data.result?.message === 'Action cancelled.' || payload.message === 'Action cancelled.' || data.message === 'Action cancelled.') {
          setFsmState('Cancelled');
          setStatusMessage('Cancelled');
          setIsProcessing(false);
        } else {
          setFsmState('Completed');
          setStatusMessage('Completed');
          setIsProcessing(false);
        }

        if (payload) {
          if (payload.transcription && !transcript) setTranscript(payload.transcription);
          if (payload.translated_text && !translatedText) setTranslatedText(payload.translated_text);
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
            title: status === 'error' || status === 'failed' ? 'Task Failed' : (status === 'cancelled' ? 'Task Cancelled' : 'Task Completed'),
            response: respText || (status === 'cancelled' ? 'Action cancelled.' : 'Action executed.'),
            summary: data.summary || payload.summary || data.logs || [],
            error: data.error || (status === 'error' ? data.message : null),
            isError: status === 'error' || status === 'failed',
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
    setStatusMessage('Processing request...');

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

      setIsProcessing(false);
      setFsmState((prev) => {
        if (prev === 'Awaiting Confirmation' || prev === 'Failed' || prev === 'Cancelled' || prev === 'Completed') {
          return prev;
        }
        return 'Completed';
      });
      setStatusMessage((prev) => {
        if (prev === 'Awaiting Confirmation' || prev === 'Failed' || prev === 'Cancelled' || prev === 'Completed') {
          return prev;
        }
        return 'Completed';
      });
    } catch (err) {
      if (err.name !== 'AbortError') {
        console.error('[PIPELINE] Stream error:', err);
        setFsmState('Failed');
        setStatusMessage('Failed');
      } else {
        setFsmState('Cancelled');
        setStatusMessage('Cancelled');
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
    setFsmState,
    statusMessage,
    setStatusMessage,
    transcript,
    translatedText,
    accuracy,
    intent,
    entities,
    plannerOutput,
    executionLogs,
    responseText,
    audioUrl,
    isProcessing,
    setIsProcessing,
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
