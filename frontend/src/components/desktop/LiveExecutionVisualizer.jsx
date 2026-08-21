import React, { useState, useEffect } from 'react';
import { Mic, BarChart3, Target, Tag, ClipboardList, Loader2, CheckCircle2, AlertCircle, Layers, LayoutList } from 'lucide-react';
import { Card } from '../common/Card';
import { Badge } from '../common/Badge';

/**
 * Pipeline phase configuration for the interactive step tabs.
 */
const PHASE_CONFIG = [
  { key: 'transcript', icon: Mic, label: 'Transcript', color: 'var(--accent-blue-strong)' },
  { key: 'accuracy', icon: BarChart3, label: 'Metrics', color: 'var(--success-text)' },
  { key: 'intent', icon: Target, label: 'Intent', color: 'var(--accent-blue-strong)' },
  { key: 'entities', icon: Tag, label: 'Entities', color: 'var(--accent-blue-strong)' },
  { key: 'planner', icon: ClipboardList, label: 'Planner', color: 'var(--warning-text)' },
  { key: 'execution', icon: Loader2, label: 'Execution', color: 'var(--accent-blue-strong)' },
  { key: 'response', icon: CheckCircle2, label: 'Response', color: 'var(--success-text)' },
];

function SuccessCheckmark() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--success-text)', fontSize: '0.8rem', fontWeight: 600 }}>
      <CheckCircle2 size={15} />
    </div>
  );
}

export function LiveExecutionVisualizer({
  transcript,
  translatedText,
  accuracy,
  intent,
  entities,
  plannerOutput,
  executionLogs,
  responseText,
  audioUrl,
  audioPlayerRef,
  isProcessing,
}) {
  const [selectedTab, setSelectedTab] = useState('transcript');
  const [userSelected, setUserSelected] = useState(false);
  const [viewMode, setViewMode] = useState('tabbed'); // 'tabbed' | 'stacked'

  // Determine completion and active status for each phase
  const phases = PHASE_CONFIG.map((cfg) => {
    let isComplete = false;
    let isActive = false;
    let hasData = false;
    let isFailed = false;

    switch (cfg.key) {
      case 'transcript':
        isComplete = !!transcript;
        hasData = !!transcript;
        isActive = isProcessing && !transcript;
        break;
      case 'translation':
        isComplete = !!translatedText;
        hasData = !!translatedText;
        isActive = !!transcript && !translatedText && isProcessing;
        break;
      case 'accuracy':
        isComplete = !!accuracy;
        hasData = !!accuracy;
        isActive = !!translatedText && !accuracy && isProcessing;
        break;
      case 'intent':
        isComplete = !!intent;
        hasData = !!intent;
        isActive = !!accuracy && !intent && isProcessing;
        break;
      case 'entities':
        isComplete = entities !== null && entities !== undefined;
        hasData = entities !== null && entities !== undefined;
        isActive = !!intent && (entities === null || entities === undefined) && isProcessing;
        break;
      case 'planner':
        isComplete = !!plannerOutput;
        hasData = !!plannerOutput;
        isActive = (entities !== null && entities !== undefined) && !plannerOutput && isProcessing;
        break;
      case 'execution': {
        const hasLogs = Array.isArray(executionLogs) && executionLogs.length > 0;
        const hasFailedLog = hasLogs && executionLogs.some((log) => {
          if (typeof log === 'object' && log !== null) {
            return log.success === false || log.status === 'failed' || log.status === 'error' || log.state === 'failure';
          }
          if (typeof log === 'string') {
            return log.includes('failed') || log.includes('error');
          }
          return false;
        });
        isComplete = hasLogs && !isProcessing && !hasFailedLog;
        hasData = hasLogs;
        isActive = !!plannerOutput && (!Array.isArray(executionLogs) || executionLogs.length === 0) && isProcessing;
        isFailed = hasFailedLog && !isProcessing;
        break;
      }
      case 'response':
        isComplete = !!responseText;
        hasData = !!responseText;
        isActive = Array.isArray(executionLogs) && executionLogs.length > 0 && !responseText && isProcessing;
        break;
      default:
        break;
    }

    return { ...cfg, isComplete, isActive, hasData, isFailed };
  });

  // Auto-advance tab to the latest active/completed phase (unless user manually selected a tab)
  useEffect(() => {
    if (userSelected) return;
    const activePhase = [...phases].reverse().find((p) => p.hasData || p.isActive);
    if (activePhase) {
      setSelectedTab(activePhase.key);
    }
  }, [transcript, translatedText, accuracy, intent, entities, plannerOutput, executionLogs, responseText, isProcessing, userSelected]);

  const handleTabClick = (key) => {
    setSelectedTab(key);
    setUserSelected(true);
  };

  // ── Card Renderer Functions ──

  const renderTranscriptCard = () => {
    const text = typeof transcript === 'object' ? (transcript.text || transcript.transcription || JSON.stringify(transcript)) : transcript;
    return (
      <Card title="Transcript" badge={<Badge variant="success"><SuccessCheckmark /></Badge>}>
        <div style={{ fontSize: '0.95rem', color: 'var(--text-primary)', lineHeight: 1.6, fontWeight: 500 }}>
          "{text || 'No transcript available'}"
        </div>
      </Card>
    );
  };

  const renderTranslationCard = () => {
    const text = typeof translatedText === 'object' ? (translatedText.translated_text || translatedText.text || JSON.stringify(translatedText)) : translatedText;
    return (
      <Card title="English Translation" badge={<Badge variant="success"><SuccessCheckmark /></Badge>}>
        <div style={{ fontSize: '0.95rem', color: 'var(--text-primary)', lineHeight: 1.6, fontWeight: 500 }}>
          "{text || 'No translation available'}"
        </div>
      </Card>
    );
  };

  const renderAccuracyCard = () => {
    let model = 'N/A';
    let confidence = 'N/A';
    let processingTime = 'N/A';

    if (typeof accuracy === 'object' && accuracy !== null) {
      model = accuracy.model || accuracy.stt_model || 'Faster-Whisper';
      if (accuracy.confidence != null) {
        const conf = accuracy.confidence;
        if (typeof conf === 'number') {
          confidence = conf <= 1 ? `${(conf * 100).toFixed(1)}%` : `${conf}%`;
        } else {
          confidence = String(conf);
        }
      }
      if (accuracy.processingTime) {
        processingTime = String(accuracy.processingTime);
      } else if (accuracy.processing_time_ms != null) {
        processingTime = `${(accuracy.processing_time_ms / 1000).toFixed(2)}s`;
      }
    } else if (typeof accuracy === 'string' || typeof accuracy === 'number') {
      confidence = String(accuracy);
    }

    return (
      <Card title="Accuracy & Metrics" badge={<Badge variant="info">STT</Badge>}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px' }}>
          {[
            { label: 'Model', value: model, color: 'var(--text-primary)' },
            { label: 'Confidence', value: confidence, color: 'var(--success-text)' },
            { label: 'Processing Time', value: processingTime, color: 'var(--text-primary)' },
          ].map((m) => (
            <div key={m.label}>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 600 }}>{m.label}</div>
              <div style={{ fontSize: '0.9rem', fontWeight: 600, color: m.color }}>{m.value}</div>
            </div>
          ))}
        </div>
      </Card>
    );
  };

  const renderIntentCard = () => {
    let intentName = 'Unknown';
    let confidenceStr = '';

    if (typeof intent === 'object' && intent !== null) {
      intentName = intent.name || intent.intent || intent.label || JSON.stringify(intent);
      if (intent.confidence != null) {
        const c = intent.confidence;
        confidenceStr = typeof c === 'number' ? (c <= 1 ? `${(c * 100).toFixed(1)}%` : `${c}%`) : String(c);
      }
    } else if (typeof intent === 'string') {
      intentName = intent;
    }

    return (
      <Card title="Intent" badge={<Badge variant="info">NLP</Badge>}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)' }}>Detected Intent:</span>
          <span style={{
            display: 'inline-block',
            padding: '4px 14px',
            borderRadius: 'var(--radius-full)',
            fontSize: '0.85rem',
            fontWeight: 600,
            background: 'var(--surface-blue)',
            color: 'var(--accent-blue-strong)',
            border: '1px solid var(--border-blue)',
          }}>
            {intentName}
          </span>
          {confidenceStr && (
            <span style={{ fontSize: '0.78rem', color: 'var(--success-text)', fontWeight: 600 }}>
              ({confidenceStr} confidence)
            </span>
          )}
        </div>
      </Card>
    );
  };

  const renderEntitiesCard = () => {
    const entEntries = (entities && typeof entities === 'object' && !Array.isArray(entities))
      ? Object.entries(entities)
      : (Array.isArray(entities) ? entities.map((item, idx) => [idx, typeof item === 'object' ? JSON.stringify(item) : String(item)]) : []);

    return (
      <Card title="Entities & Parameters" badge={<Badge variant="info">Extracted</Badge>}>
        {entEntries.length > 0 ? (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            {entEntries.map(([key, value]) => (
              <div key={key} style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '6px 14px',
                borderRadius: 'var(--radius-full)',
                background: 'var(--surface-blue-soft)',
                border: '1px solid var(--border-blue)',
                fontSize: '0.8rem',
              }}>
                <span style={{ color: 'var(--text-secondary)' }}>{key}:</span>
                <span style={{ fontWeight: 600, color: 'var(--accent-blue-strong)' }}>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</span>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>
            No entities extracted for this command (operated with default parameters).
          </div>
        )}
      </Card>
    );
  };

  const renderPlannerCard = () => {
    let planData = plannerOutput;
    if (typeof planData === 'string') {
      try {
        planData = JSON.parse(planData);
      } catch (e) {
        planData = { reasoning: plannerOutput };
      }
    }
    const reasoning = planData?.reasoning || planData?.thought || planData?.description;
    const steps = planData?.steps || planData?.plan?.steps || planData?.actions || [];

    return (
      <Card title="Execution Plan" badge={<Badge variant="warning">Scheduled</Badge>}>
        {reasoning && (
          <div style={{
            fontSize: '0.85rem',
            color: 'var(--text-secondary)',
            marginBottom: '12px',
            padding: '10px 14px',
            background: 'var(--surface-yellow-soft)',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid #ffe082',
            lineHeight: 1.5,
          }}>
            {reasoning}
          </div>
        )}
        {steps && Array.isArray(steps) && steps.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {steps.map((step, idx) => (
              <div key={idx} style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: '12px',
                padding: '10px 14px',
                background: 'var(--background-secondary)',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-soft)',
              }}>
                <div style={{
                  width: '24px',
                  height: '24px',
                  borderRadius: '50%',
                  background: 'var(--surface-blue)',
                  color: 'var(--accent-blue-strong)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '0.75rem',
                  fontWeight: 700,
                  flexShrink: 0,
                }}>
                  {idx + 1}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                    {step.tool || step.action || step.name || 'action'}
                  </div>
                  {step.args && (
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', marginTop: '2px', wordBreak: 'break-word' }}>
                      {typeof step.args === 'object'
                        ? Object.entries(step.args).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · ')
                        : String(step.args)}
                    </div>
                  )}
                  {(step.description || step.summary) && (
                    <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '3px' }}>{step.description || step.summary}</div>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <pre className="json-pre">{JSON.stringify(planData, null, 2)}</pre>
        )}
      </Card>
    );
  };

  const renderExecutionCard = () => {
    const logs = Array.isArray(executionLogs) ? executionLogs : [];
    return (
      <Card title="Execution Logs" badge={<Badge variant={isProcessing ? "warning" : "success"} pulse={isProcessing}>{isProcessing ? 'Running...' : 'Complete'}</Badge>}>
        {logs.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {logs.map((log, idx) => {
              const isSuccess = typeof log === 'object' && (log.status === 'success' || log.success);
              const isFail = typeof log === 'object' && (log.status === 'error' || log.status === 'failed');
              const msg = typeof log === 'string' ? log : (log.message || log.log || log.step || JSON.stringify(log));
              return (
                <div key={idx} style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '10px',
                  fontSize: '0.8rem',
                  fontFamily: 'var(--font-mono)',
                  backgroundColor: isSuccess ? 'var(--success-background)' : isFail ? 'var(--error-background)' : 'var(--background-secondary)',
                  padding: '8px 12px',
                  borderRadius: 'var(--radius-sm)',
                  color: isSuccess ? 'var(--success-text)' : isFail ? 'var(--error-text)' : 'var(--text-primary)',
                  borderLeft: `3px solid ${isSuccess ? 'var(--success-text)' : isFail ? 'var(--error-text)' : 'var(--accent-blue-strong)'}`,
                }}>
                  <span style={{ flexShrink: 0, marginTop: '1px' }}>
                    {isSuccess ? <CheckCircle2 size={14} /> : isFail ? <AlertCircle size={14} /> : <Loader2 size={14} style={isProcessing && idx === logs.length - 1 ? { animation: 'spin 1s linear infinite' } : {}} />}
                  </span>
                  <span style={{ wordBreak: 'break-word' }}>
                    {msg}
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
          <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>
            No execution logs emitted for this phase yet.
          </div>
        )}
      </Card>
    );
  };

  const renderResponseCard = () => {
    const text = typeof responseText === 'object' ? (responseText.text || responseText.message || JSON.stringify(responseText)) : responseText;
    return (
      <Card title="Response" badge={<Badge variant="success"><SuccessCheckmark /></Badge>}>
        <div style={{ fontSize: '0.95rem', color: 'var(--text-primary)', lineHeight: 1.6, fontWeight: 500 }}>
          {text || 'Response generated.'}
        </div>
        {audioUrl && (
          <audio
            ref={audioPlayerRef}
            controls
            style={{ marginTop: '12px', width: '100%', height: '36px' }}
          >
            <source src={audioUrl} />
          </audio>
        )}
      </Card>
    );
  };

  const renderEmptyStepCard = (title, message) => (
    <Card title={title} badge={<Badge variant="secondary">Pending</Badge>}>
      <div style={{
        padding: '16px',
        textAlign: 'center',
        background: 'var(--background-secondary)',
        borderRadius: 'var(--radius-md)',
        border: '1px dashed var(--border-soft)',
        color: 'var(--text-muted)',
        fontSize: '0.85rem'
      }}>
        {message}
      </div>
    </Card>
  );

  const renderStepContent = (key) => {
    switch (key) {
      case 'transcript':
        return transcript ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {renderTranscriptCard()}
            {translatedText && renderTranslationCard()}
          </div>
        ) : renderEmptyStepCard('Transcript', 'Speech-to-text transcript is processing or pending input...');
      case 'accuracy':
        return accuracy ? renderAccuracyCard() : renderEmptyStepCard('Metrics & Accuracy', 'STT performance metrics pending transcription completion...');
      case 'intent':
        return intent ? renderIntentCard() : renderEmptyStepCard('Intent', 'Intent classification pending STT completion...');
      case 'entities':
        return (entities !== null && entities !== undefined) ? renderEntitiesCard() : renderEmptyStepCard('Entities & Parameters', 'Entity extraction pending intent classification...');
      case 'planner':
        return plannerOutput ? renderPlannerCard() : renderEmptyStepCard('Execution Plan', 'Execution planner generating step-by-step plan...');
      case 'execution':
        return (Array.isArray(executionLogs) && executionLogs.length > 0) ? renderExecutionCard() : renderEmptyStepCard('Execution Logs', 'Action execution logs pending plan confirmation...');
      case 'response':
        return responseText ? renderResponseCard() : renderEmptyStepCard('Response', 'Assistant response text and TTS audio generating...');
      default:
        return null;
    }
  };

  return (
    <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>

      {/* ── Interactive Step Navigation Bar ── */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '8px 12px',
        background: 'var(--surface-primary)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-xl)',
        boxShadow: 'var(--shadow-soft)',
        overflowX: 'auto',
        gap: '6px'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', overflowX: 'auto', flex: 1 }}>
          {phases.map((phase) => {
            const Icon = phase.icon;
            const isSelected = selectedTab === phase.key && viewMode === 'tabbed';

            return (
              <button
                key={phase.key}
                onClick={() => handleTabClick(phase.key)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '7px 12px',
                  borderRadius: 'var(--radius-md)',
                  border: isSelected ? '1px solid var(--border-blue)' : '1px solid transparent',
                  background: isSelected ? 'var(--surface-blue)' : phase.hasData ? 'var(--surface-blue-soft)' : 'transparent',
                  color: isSelected ? 'var(--accent-blue-strong)' : phase.hasData ? 'var(--text-primary)' : 'var(--text-secondary)',
                  fontSize: '0.78rem',
                  fontWeight: isSelected ? 700 : 500,
                  cursor: 'pointer',
                  whiteSpace: 'nowrap',
                  transition: 'all 180ms ease',
                }}
              >
                {phase.isFailed ? (
                  <AlertCircle size={14} color="var(--error-text)" />
                ) : phase.isComplete ? (
                  <CheckCircle2 size={14} color="var(--success-text)" />
                ) : (
                  <Icon size={14} color={phase.isActive ? phase.color : 'var(--text-muted)'} style={phase.isActive ? { animation: 'pulse-ring 1.8s infinite' } : {}} />
                )}
                <span>{phase.label}</span>
              </button>
            );
          })}
        </div>

        {/* View mode toggle button: Tabbed vs Stacked */}
        <button
          onClick={() => setViewMode(viewMode === 'tabbed' ? 'stacked' : 'tabbed')}
          title={viewMode === 'tabbed' ? 'Switch to All Steps Stacked View' : 'Switch to Tabbed Step View'}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
            padding: '6px 10px',
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--border-soft)',
            background: 'var(--background-secondary)',
            color: 'var(--text-secondary)',
            fontSize: '0.72rem',
            fontWeight: 600,
            cursor: 'pointer',
            flexShrink: 0
          }}
        >
          {viewMode === 'tabbed' ? <Layers size={14} /> : <LayoutList size={14} />}
          <span>{viewMode === 'tabbed' ? 'Tab View' : 'All Steps'}</span>
        </button>
      </div>

      {/* ── Step Details Container Box ── */}
      {viewMode === 'tabbed' ? (
        <div className="animate-fade-in">
          {renderStepContent(selectedTab)}
        </div>
      ) : (
        /* Stacked View showing all completed/active steps in order */
        <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {transcript && renderTranscriptCard()}
          {translatedText && renderTranslationCard()}
          {accuracy && renderAccuracyCard()}
          {intent && renderIntentCard()}
          {(entities !== null && entities !== undefined) && renderEntitiesCard()}
          {plannerOutput && renderPlannerCard()}
          {Array.isArray(executionLogs) && executionLogs.length > 0 && renderExecutionCard()}
          {responseText && renderResponseCard()}
        </div>
      )}
    </div>
  );
}
