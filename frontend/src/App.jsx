import React, { useState, useCallback, useRef, useEffect } from 'react';
import { Header } from './components/common/Header';
import { Button } from './components/common/Button';
import { MicRecorder } from './components/desktop/MicRecorder';
import { FSMStateBadge } from './components/desktop/FSMStateBadge';
import { ConfirmationCard } from './components/desktop/ConfirmationCard';
import { CompletionPopup } from './components/desktop/CompletionPopup';
import { LiveExecutionVisualizer } from './components/desktop/LiveExecutionVisualizer';
import { TextInput } from './components/desktop/TextInput';
import { FileSearchModal } from './components/search/FileSearchModal';
import { DocumentConfirmModal } from './components/search/DocumentConfirmModal';
import { QuickShortcuts } from './components/notepad/QuickShortcuts';
import { HistoryView } from './components/history/HistoryView';
import { useAudioRecorder } from './hooks/useAudioRecorder';
import { usePipelineStream } from './hooks/usePipelineStream';
import { useInactivityReset } from './hooks/useInactivityReset';
import { RotateCcw } from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState('assistant');

  const {
    isRecording,
    micStatusText,
    recordingDuration,
    startRecording,
    stopRecording,
  } = useAudioRecorder();

  const {
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
    handleEventData,
    resetState,
  } = usePipelineStream();

  const audioPlayerRef = useRef(null);

  // Auto-play TTS when audio URL arrives
  useEffect(() => {
    if (audioUrl && audioPlayerRef.current) {
      audioPlayerRef.current.src = audioUrl;
      audioPlayerRef.current.play().catch(() => {});
    }
  }, [audioUrl]);

  // Terminal state evaluation for 60s inactivity auto-reset
  const isTerminalState =
    fsmState === 'Completed' ||
    fsmState === 'Failed' ||
    completionPopup !== null ||
    (Boolean(responseText || executionLogs.length > 0) && !isProcessing);

  const isBlocked = isProcessing || isRecording || confirmationData !== null || docConfirmData !== null;

  const handleResetToHome = useCallback(() => {
    resetState();
    setConfirmationData(null);
    setFileSearchData(null);
    setDocConfirmData(null);
    setCompletionPopup(null);
  }, [resetState, setConfirmationData, setFileSearchData, setDocConfirmData, setCompletionPopup]);

  // Setup 60s inactivity timer
  useInactivityReset({
    isTerminalState,
    isBlocked,
    onReset: handleResetToHome,
    timeoutMs: 60000,
  });

  const handleAudioRecorded = useCallback(
    (audioBlob) => {
      sendPipelineRequest({ audioBlob });
    },
    [sendPipelineRequest]
  );

  const handleQuickCommand = useCallback(
    (text) => {
      sendPipelineRequest({ textInput: text });
    },
    [sendPipelineRequest]
  );

  const handleMicStart = useCallback(() => {
    startRecording(handleAudioRecorded);
  }, [startRecording, handleAudioRecorded]);

  const handleConfirmationDecision = useCallback(
    (decision) => {
      if (decision === 'cancel') {
        setConfirmationData(null);
      }
    },
    [setConfirmationData]
  );

  const handleConfirmStreamEvent = useCallback(
    (eventData) => {
      setConfirmationData(null);
      if (handleEventData) {
        handleEventData(eventData);
      }
    },
    [setConfirmationData, handleEventData]
  );

  const handleOpenSearchResult = useCallback(
    (result) => {
      if (result.path) {
        setDocConfirmData({
          filePath: result.path,
          message: `Open "${result.filename || result.name}"?`,
        });
      }
    },
    [setDocConfirmData]
  );

  const handleDocConfirmOpen = useCallback(
    (filePath) => {
      const encoded = encodeURIComponent(filePath);
      window.open(`/view_document?path=${encoded}`, '_blank');
      setDocConfirmData(null);
      setFileSearchData(null);
    },
    [setDocConfirmData, setFileSearchData]
  );

  const hasResults = Boolean(transcript || accuracy || intent || entities || plannerOutput || executionLogs.length > 0 || responseText);

  return (
    <div style={{ minHeight: '100vh', backgroundColor: 'var(--background-main)' }}>
      {/* ── Fixed Full-Width Top Navbar ── */}
      <Header activeTab={activeTab} setActiveTab={setActiveTab} />

      <div className="app-container" style={{ paddingTop: '20px' }}>
        {activeTab === 'assistant' ? (
          <div className="main-content">
            {/* FSM State Badge */}
            <FSMStateBadge fsmState={fsmState} />

            {/* Status Message */}
            {statusMessage && (
              <div style={{ textAlign: 'center', fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                {statusMessage}
              </div>
            )}

            {/* ── Pure Voice Assistant Recorder Zone ── */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px', margin: '12px 0 16px', width: '100%' }}>
              <MicRecorder
                isRecording={isRecording}
                micStatusText={micStatusText}
                recordingDuration={recordingDuration}
                onStart={handleMicStart}
                onStop={stopRecording}
              />
              <TextInput
                onSubmitText={handleQuickCommand}
                isProcessing={isProcessing || isRecording}
              />
            </div>

            {/* ── Quick Launch Grid (strictly IDLE — no recording, no execution, no results) ── */}
            {!hasResults && !isProcessing && !isRecording && fsmState === 'Idle' && (
              <div className="animate-fade-in">
                <QuickShortcuts onSendCommand={handleQuickCommand} />
              </div>
            )}

            {/* ── Confirmation Card ── */}
            {confirmationData && (
              <ConfirmationCard
                confirmationData={confirmationData}
                onDecision={handleConfirmationDecision}
                onStreamEvent={handleConfirmStreamEvent}
              />
            )}

            {/* ── Persistent Sequential Live Execution Visualizer ── */}
            {hasResults && (
              <>
                {isTerminalState && (
                  <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '8px' }}>
                    <Button variant="secondary" onClick={handleResetToHome} icon={RotateCcw} style={{ fontSize: '0.8rem', padding: '6px 14px' }}>
                      New Command (Home)
                    </Button>
                  </div>
                )}

                <LiveExecutionVisualizer
                  transcript={transcript}
                  accuracy={accuracy}
                  intent={intent}
                  entities={entities}
                  plannerOutput={plannerOutput}
                  executionLogs={executionLogs}
                  responseText={responseText}
                  audioUrl={audioUrl}
                  audioPlayerRef={audioPlayerRef}
                  isProcessing={isProcessing}
                />
              </>
            )}

            {/* Hidden audio player for auto-playback */}
            {!responseText && audioUrl && (
              <audio ref={audioPlayerRef} style={{ display: 'none' }}>
                <source src={audioUrl} />
              </audio>
            )}

            {/* ── Modals ── */}
            <FileSearchModal
              fileSearchData={fileSearchData}
              onClose={() => setFileSearchData(null)}
              onOpenResult={handleOpenSearchResult}
            />
            <DocumentConfirmModal
              docConfirmData={docConfirmData}
              onConfirm={handleDocConfirmOpen}
              onCancel={() => setDocConfirmData(null)}
            />
            <CompletionPopup
              popupData={completionPopup}
              onClose={() => setCompletionPopup(null)}
            />
          </div>
        ) : (
          <HistoryView />
        )}
      </div>
    </div>
  );
}
