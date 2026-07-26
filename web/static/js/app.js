/* ═══════════════════════════════════════════════════════════════════
   Voice Assistant — Frontend Application (SSE Streaming)
   ═══════════════════════════════════════════════════════════════════ */

'use strict';

// ── Recording state ─────────────────────────────────────────────────
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

// ── Confirmation state ───────────────────────────────────────────────
let activeConfirmationId = null;
let confirmationTimer = null;
let confirmationCountdown = 60;

// ── SSE abort controller ─────────────────────────────────────────────
let activeStreamController = null;

// ── FSM & Audio states ──────────────────────────────────────────────
const FSM_STATES = {
  IDLE: 'Idle',
  LISTENING: 'Listening',
  TRANSCRIBING: 'Transcribing',
  UNDERSTANDING: 'Understanding',
  PLANNING: 'Planning',
  WAITING_FOR_CONFIRMATION: 'Awaiting Confirmation',
  EXECUTING: 'Executing',
  VERIFYING: 'Verifying',
  COMPLETED: 'Completed',
  FAILED: 'Failed'
};

let lastAudioBlob = null;
let popupAutoCloseTimer = null;
let fsmIdleTimer = null;

// Unlock audio playback on the first user interaction
let isAudioUnlocked = false;
let audioContext = null;

async function unlockAudio() {
  if (isAudioUnlocked) {
    return;
  }

  try {
    const AudioContextClass =
      window.AudioContext || window.webkitAudioContext;

    if (!AudioContextClass) {
      console.warn(
        "[AUDIO] Web Audio API is not supported."
      );

      // Do not block recording if the API is unavailable.
      isAudioUnlocked = true;
      return;
    }

    if (!audioContext) {
      audioContext = new AudioContextClass();
    }

    if (audioContext.state === "suspended") {
      await audioContext.resume();
    }

    const silentBuffer = audioContext.createBuffer(
      1,
      1,
      audioContext.sampleRate
    );

    const silentSource =
      audioContext.createBufferSource();

    silentSource.buffer = silentBuffer;
    silentSource.connect(audioContext.destination);
    silentSource.start(0);

    isAudioUnlocked = true;

    console.log(
      "[AUDIO] Audio playback successfully unlocked."
    );
  } catch (error) {
    console.warn(
      "[AUDIO] Audio unlock failed:",
      error
    );
  }
}

function transitionTo(state) {
  const container = document.getElementById('fsm-status-container');
  const badge = document.getElementById('fsm-state-badge');
  if (!container || badge === null) return;

  console.log(`[FSM] → ${state}`);
  container.style.display = 'flex';
  badge.textContent = state;

  // Reset styles first
  badge.style.backgroundColor = '';
  badge.style.color = '#FFF';

  if (state === FSM_STATES.IDLE) {
    console.log("Returned to idle");
    badge.style.backgroundColor = '#6c757d'; // Grey
  } else if (state === FSM_STATES.LISTENING) {
    badge.style.backgroundColor = '#dc2626'; // Red
  } else if (state === FSM_STATES.TRANSCRIBING) {
    badge.style.backgroundColor = '#0891b2'; // Cyan
  } else if (state === FSM_STATES.UNDERSTANDING) {
    badge.style.backgroundColor = '#2563eb'; // Blue
  } else if (state === FSM_STATES.PLANNING) {
    badge.style.backgroundColor = '#7c3aed'; // Indigo
  } else if (state === FSM_STATES.WAITING_FOR_CONFIRMATION) {
    badge.style.backgroundColor = '#d97706'; // Amber
  } else if (state === FSM_STATES.EXECUTING) {
    badge.style.backgroundColor = '#9333ea'; // Purple
  } else if (state === FSM_STATES.VERIFYING) {
    badge.style.backgroundColor = '#0284c7'; // Light Blue
  } else if (state === FSM_STATES.COMPLETED) {
    badge.style.backgroundColor = '#16a34a'; // Green
  } else if (state === FSM_STATES.FAILED) {
    badge.style.backgroundColor = '#dc2626'; // Red
  }
}


function validatePlanFrontend(confirmation) {
  const errors = [];

  if (!confirmation) {
    errors.push("Confirmation object is missing.");
    return { valid: false, errors };
  }

  if (!confirmation.plan) {
    errors.push("Execution plan is missing.");
    return { valid: false, errors };
  }

  const steps = confirmation.plan.steps || [];
  if (steps.length === 0) {
    errors.push("Plan contains no executable steps.");
  }

  steps.forEach((step, idx) => {
    if (!step.tool) {
      errors.push(`Step ${idx + 1} is missing a tool.`);
    }
  });

  return {
    valid: errors.length === 0,
    errors
  };
}

// ── DOM refs ─────────────────────────────────────────────────────────
const micBtn = document.getElementById('mic-btn');
const uploadInput = document.getElementById('upload-input');
const statusText = document.getElementById('status-text');

const sections = [
  'sec-transcript',
  'sec-accuracy',
  'sec-intent',
  'sec-entities',
  'sec-planner',
  'sec-execution',
  'sec-response',
];

// ══════════════════════════════════════════════════════════════════════
// Recording
// ══════════════════════════════════════════════════════════════════════

micBtn.addEventListener('click', async () => {
  console.log("Record clicked");
  await unlockAudio();
  if (isRecording) {
    stopRecording();
  } else {
    await startRecording();
  }
});

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
    audioChunks = [];

    mediaRecorder.ondataavailable = e => { if (e.data.size > 0) audioChunks.push(e.data); };
    mediaRecorder.onstop = () => {
      console.log("Voice captured");
      const blob = new Blob(audioChunks, { type: 'audio/webm' });
      lastAudioBlob = blob;
      showMicStatus('captured', 'Audio Captured');
      sendAudio(blob, 'recording.webm');
      stream.getTracks().forEach(t => t.stop());
    };

    mediaRecorder.start();
    isRecording = true;
    micBtn.textContent = 'Stop Recording';
    micBtn.classList.add('recording');
    statusText.textContent = '';
    showMicStatus('listening', 'Listening...');
    transitionTo(FSM_STATES.LISTENING);
    resetUI(/* keepMicStatus */ true);

  } catch (err) {
    statusText.textContent = 'Microphone access denied.';
  }
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
  }
  isRecording = false;
  micBtn.textContent = 'Record Audio';
  micBtn.classList.remove('recording');
}

uploadInput.addEventListener('change', async e => {
  const file = e.target.files[0];
  if (file) {
    await unlockAudio();
    lastAudioBlob = file;
    resetUI();
    showMicStatus('captured', 'Audio Captured');
    sendAudio(file, file.name);
    uploadInput.value = '';
  }
});

// ══════════════════════════════════════════════════════════════════════
// UI reset helpers
// ══════════════════════════════════════════════════════════════════════

function resetUI(keepMicStatus = false) {
  // Cancel any active SSE stream
  if (activeStreamController) {
    activeStreamController.abort();
    activeStreamController = null;
  }

  // Close any active confirmation card
  hideConfirmationCard();

  // Close any active completion popup
  hideCompletionPopup();

  hideAllSections();

  if (!keepMicStatus) clearMicStatus();

  const execDiv = document.getElementById('execution-val');
  if (execDiv) execDiv.innerHTML = '';

  // Reset audio player
  const audioEl = document.getElementById('audio-player');
  if (audioEl) {
    audioEl.pause();
    audioEl.src = '';
    audioEl.style.display = 'none';
  }
}


function hideAllSections() {
  sections.forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.className = 'section';
    }
    const badgeId = id.replace('sec-', 'badge-');
    const badgeEl = document.getElementById(badgeId);
    if (badgeEl) {
      badgeEl.className = 'stage-badge';
    }
    const hintId = id.replace('sec-', 'hint-');
    const hintEl = document.getElementById(hintId);
    if (hintEl) {
      hintEl.textContent = '';
    }
  });
}

function setSectionState(sectionId, state) {
  const sectionEl = document.getElementById(sectionId);
  if (!sectionEl) return;

  sectionEl.classList.remove('processing', 'completed', 'failed');
  if (state === 'processing') {
    sectionEl.classList.add('processing');
  } else if (state === 'completed') {
    sectionEl.classList.add('completed');
  } else if (state === 'failed') {
    sectionEl.classList.add('failed');
  }

  const badgeId = sectionId.replace('sec-', 'badge-');
  const badgeEl = document.getElementById(badgeId);
  if (badgeEl) {
    badgeEl.className = 'stage-badge';
    if (state === 'processing') {
      badgeEl.classList.add('working');
    } else if (state === 'completed') {
      badgeEl.classList.add('done');
    } else if (state === 'failed') {
      badgeEl.classList.add('fail');
    }
  }
}

function showProcessingHint(sectionId, text) {
  const hintId = sectionId.replace('sec-', 'hint-');
  const hintEl = document.getElementById(hintId);
  if (hintEl) {
    hintEl.textContent = text;
  }
}

function clearProcessingHint(sectionId) {
  const hintId = sectionId.replace('sec-', 'hint-');
  const hintEl = document.getElementById(hintId);
  if (hintEl) {
    hintEl.textContent = '';
  }
}

function revealSection(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('visible');
}

// ══════════════════════════════════════════════════════════════════════
// Mic status badge
// ══════════════════════════════════════════════════════════════════════

function showMicStatus(state, text) {
  const el = document.getElementById('mic-status');
  const txt = document.getElementById('mic-status-text');
  if (!el || !txt) return;
  el.className = `mic-status ${state}`;   // 'listening' or 'captured'
  txt.textContent = text;
}

function clearMicStatus() {
  const el = document.getElementById('mic-status');
  if (el) el.className = 'mic-status hidden';
}

// ══════════════════════════════════════════════════════════════════════
// SSE Audio submission & stream consumer
// ══════════════════════════════════════════════════════════════════════

async function sendAudio(blob, filename) {
  statusText.textContent = '';
  transitionTo(FSM_STATES.PROCESSING);

  const formData = new FormData();
  formData.append('audio', blob, filename);

  // Abort any previous stream
  if (activeStreamController) activeStreamController.abort();
  activeStreamController = new AbortController();

  try {
    const res = await fetch('/transcribe_stream', {
      method: 'POST',
      body: formData,
      signal: activeStreamController.signal,
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
      statusText.textContent = 'Error: ' + (errData.error || 'Unknown error');
      return;
    }

    await consumeSSEStream(res.body);

  } catch (err) {
    if (err.name === 'AbortError') return; // user started a new recording
    statusText.textContent = 'Network error.';
  }
}

async function consumeSSEStream(body) {
  const reader = body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    let boundary;
    while ((boundary = buffer.indexOf('\n\n')) !== -1) {
      const chunk = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);

      for (const line of chunk.split('\n')) {
        if (!line.startsWith('data: ')) continue;
        try {
          const event = JSON.parse(line.slice(6));
          handleSSEEvent(event);
        } catch (_) { /* malformed JSON — ignore */ }
      }
    }
  }
}

// ══════════════════════════════════════════════════════════════════════
// SSE event dispatcher
// ══════════════════════════════════════════════════════════════════════

function handleSSEEvent(event) {
  console.log("================================================================================");
  console.log("[FRONTEND] Received SSE Event");
  console.log("[FRONTEND] Full event:", JSON.stringify(event, null, 2));
  const { stage, status, data, message } = event;
  console.log("[FRONTEND] Stage:", stage);
  console.log("[FRONTEND] Status:", status);
  console.log("[FRONTEND] Message:", message);
  console.log("[FRONTEND] Data:", data);

  switch (stage) {

    // ── Transcript ──────────────────────────────────────────────────
    case 'transcript': {
      if (status === 'processing') {
        transitionTo(FSM_STATES.TRANSCRIBING);
        revealSection('sec-transcript');
        setSectionState('sec-transcript', 'processing');
        showProcessingHint('sec-transcript', 'Transcribing audio…');
        statusText.textContent = 'Transcribing…';

      } else if (status === 'completed') {
        console.log('Speech recognition completed');
        clearProcessingHint('sec-transcript');
        setSectionState('sec-transcript', 'completed');
        // Populate transcript text and metrics
        const transcriptEl = document.getElementById('transcript-val');
        if (transcriptEl && data) {
          transcriptEl.textContent = data.text || '';
          console.log('Transcript updated: ' + (data.text || ''));
        }
        // Populate accuracy metrics
        if (data && data.stt) {
          const s = data.stt;
          const modelEl = document.getElementById('met-model');
          const confEl = document.getElementById('met-conf');
          const timeEl = document.getElementById('met-time');
          if (modelEl) modelEl.textContent = s.model || '—';
          if (confEl) confEl.textContent = s.confidence != null ? s.confidence + '%' : '—';
          if (timeEl) timeEl.textContent = s.processing_time_ms != null ? s.processing_time_ms + ' ms' : '—';
        }
        revealSection('sec-transcript');
        revealSection('sec-accuracy');
        setSectionState('sec-accuracy', 'completed');
        statusText.textContent = 'Transcript ready';
        transitionTo(FSM_STATES.UNDERSTANDING);
      }
      break;
    }

    // ── Intent ──────────────────────────────────────────────────────
    case 'intent': {
      if (status === 'processing') {
        transitionTo(FSM_STATES.UNDERSTANDING);
        revealSection('sec-intent');
        setSectionState('sec-intent', 'processing');
        showProcessingHint('sec-intent', 'Detecting intent…');
        statusText.textContent = 'Detecting intent…';

      } else if (status === 'completed') {
        console.log('Intent detected: ' + (data?.name || 'unknown'));
        clearProcessingHint('sec-intent');
        setSectionState('sec-intent', 'completed');
        const intentName = data.name || 'unknown';
        document.getElementById('intent-val').textContent = intentName;
        revealSection('sec-intent');
        statusText.textContent = 'Intent: ' + intentName;
        transitionTo(FSM_STATES.PLANNING);
      }
      break;
    }

    // ── Entities ────────────────────────────────────────────────────
    case 'entities': {
      if (status === 'processing') {
        revealSection('sec-entities');
        setSectionState('sec-entities', 'processing');
        showProcessingHint('sec-entities', 'Extracting entities…');
        statusText.textContent = 'Extracting entities…';

      } else if (status === 'completed') {
        clearProcessingHint('sec-entities');
        setSectionState('sec-entities', 'completed');
        // Render entities as key–value chips
        const entitiesEl = document.getElementById('entities-val');
        if (entitiesEl && data && data.entities) {
          const entries = Object.entries(data.entities);
          if (entries.length > 0) {
            entitiesEl.innerHTML = entries.map(([k, v]) =>
              `<span class="entity-chip"><strong>${escapeHtml(k)}:</strong> ${escapeHtml(String(v))}</span>`
            ).join('');
          } else {
            entitiesEl.textContent = 'None detected';
          }
        }
        revealSection('sec-entities');
        statusText.textContent = 'Entities extracted';
      }
      break;
    }

    // ── Discovery ───────────────────────────────────────────────────
    case 'discovery': {
      if (status === 'processing') {
        statusText.textContent = 'Indexing system resources…';
      } else if (status === 'completed') {
        statusText.textContent = 'System context indexed';
      }
      break;
    }

    // ── Planner ─────────────────────────────────────────────────────
    case 'planner': {
      if (status === 'processing') {
        transitionTo(FSM_STATES.PLANNING);
        revealSection('sec-planner');
        setSectionState('sec-planner', 'processing');
        showProcessingHint('sec-planner', 'Building execution plan…');
        statusText.textContent = 'Planning…';
        console.log('Planner generating…');

      } else if (status === 'completed') {
        console.log('Planner generated');
        clearProcessingHint('sec-planner');
        setSectionState('sec-planner', 'completed');
        document.getElementById('planner-val').innerHTML = syntaxHighlight(
          JSON.stringify(data || {}, null, 2)
        );
        revealSection('sec-planner');
        statusText.textContent = 'Plan ready';
        // Stay in PLANNING until confirmation is shown
      } else if (status === 'failed') {
        clearProcessingHint('sec-planner');
        setSectionState('sec-planner', 'failed');
        statusText.textContent = 'Planning failed.';
        transitionTo(FSM_STATES.IDLE);
      }
      break;
    }

    // ── Execution ───────────────────────────────────────────────────
    case 'execution': {
      console.log("[FRONTEND] Execution case - status:", status);
      if (status === 'processing' || status === 'running') {
        console.log("[FRONTEND] Execution processing/running");
        revealSection('sec-execution');
        setSectionState('sec-execution', 'processing');
        appendExecLogRow(message || '…', 'running');
        statusText.textContent = message || 'Executing…';

        if (message && message.includes("Starting execution")) {
          console.log("Execution Started");
        }

        if (message && message.includes("Verifying")) {
          transitionTo(FSM_STATES.VERIFYING);
        } else {
          transitionTo(FSM_STATES.EXECUTING);
        }
        console.log('Executing: ' + (message || '…'));

      } else if (status === 'completed') {
        console.log("[FRONTEND] Execution completed");
        console.log("[FRONTEND] Execution data:", data);
        console.log("[FRONTEND] Execution steps:", data?.steps);
        setSectionState('sec-execution', 'completed');
        finaliseExecLog(data?.steps);

        // Check for file search results
        console.log("[FRONTEND] Checking for file search results...");
        if (data && data.steps) {
          console.log("[FRONTEND] Steps found:", data.steps.length);
          for (const step of data.steps) {
            console.log("[FRONTEND] Checking step:", step);
            console.log("[FRONTEND] Step tool:", step.tool);
            let results = null;
            if (step.tool === 'find_document_by_context') {
              console.log("[FRONTEND] Found find_document_by_context step");
              console.log("[FRONTEND] Step data:", step.data);
              console.log("[FRONTEND] Step output:", step.output);
              if (step.data && step.data.opened && step.data.path) {
                console.log("[FRONTEND] Document opened successfully by backend:", step.data.path);
              }

              if (step.data && step.data.results && step.data.results.length > 0) {
                results = step.data.results;
                console.log("[FRONTEND] Results found in step.data.results:", results.length);
              } else if (step.output && Array.isArray(step.output) && step.output.length > 0) {
                results = step.output;
                console.log("[FRONTEND] Results found in step.output:", results.length);
              } else if (step.output && typeof step.output === 'string' && step.output.trim().startsWith('[')) {
                try {
                  const parsed = JSON.parse(step.output);
                  if (Array.isArray(parsed) && parsed.length > 0) {
                    results = parsed;
                    console.log("[FRONTEND] Results found in parsed step.output:", results.length);
                  }
                } catch (e) {
                  // Non-JSON string output
                }
              }

              if (results) {
                console.log("[FRONTEND] Calling showFileSearchModal with results:", results);
                console.log("[FRONTEND] showFileSearchModal type:", typeof showFileSearchModal);
                if (typeof showFileSearchModal === 'function') {
                  console.log("[FRONTEND] showFileSearchModal is a function, calling it...");
                  showFileSearchModal(results);
                  console.log("[FRONTEND] Returned from showFileSearchModal");
                } else {
                  console.error('[FRONTEND] showFileSearchModal is not a function!');
                }
              } else {
                console.log("[FRONTEND] No results found in this step");
              }
            }
          }
        } else {
          console.log("[FRONTEND] No steps data found");
        }

        // Show completion result row
        appendExecLogRow('Execution Completed ✓', 'success');
        statusText.textContent = 'Execution complete ✓';
        // FSM transition and completion popup are driven by 'done' event at the end

      } else if (status === 'requires_confirmation') {
        setSectionState('sec-execution', 'completed');
        appendExecLogRow(message || 'Awaiting confirmation…', 'confirm');
        revealSection('sec-execution');
        transitionTo(FSM_STATES.WAITING_FOR_CONFIRMATION);

      } else if (status === 'failed') {
        console.log('Execution failed: ' + (message || ''));
        setSectionState('sec-execution', 'failed');
        appendExecLogRow('Execution Failed — ' + (message || 'Unknown error'), 'failure');
        statusText.textContent = 'Execution failed.';
        // FSM transition and completion popup are driven by 'done' event at the end
      }
      break;
    }

    // ── Response ────────────────────────────────────────────────────
    case 'response': {
      if (status === 'processing') {
        revealSection('sec-response');
        setSectionState('sec-response', 'processing');
        showProcessingHint('sec-response', 'Generating assistant response…');
        statusText.textContent = 'Generating response…';

      } else if (status === 'completed') {
        clearProcessingHint('sec-response');
        setSectionState('sec-response', 'completed');
        // Render response text and optional audio player
        const respEl = document.getElementById('response-text');
        const audioEl = document.getElementById('audio-player');
        if (respEl && data) {
          respEl.textContent = data.text || '';
        }
        if (audioEl && data && data.audio_url) {
          audioEl.src = data.audio_url;
          audioEl.style.display = 'block';
          audioEl.load();

          console.log("[AUDIO] Playing TTS response...");
          audioEl.play()
            .then(() => {
              // Note: console log "Audio Playback Started" is handled by event listener
            })
            .catch(err => {
              console.error("Playback Failed", err);
            });
        }
        revealSection('sec-response');
      }
      break;
    }

    // ── Done ────────────────────────────────────────────────────────
    case 'done': {
      if (status === 'success') {
        clearMicStatus();
        statusText.textContent = 'Successfully executed all planned actions.';
        console.log("Execution Finished");

        // Audit execution results to determine overall success/failure
        const executionSteps = data && data.execution ? data.execution : [];
        const taskSuccess = executionSteps.every(step => step.success !== false);
        const requiresInteraction = executionSteps.some(step => step.requires_interaction);

        if (requiresInteraction) {
          transitionTo('Awaiting Selection');
        } else if (taskSuccess) {
          transitionTo(FSM_STATES.COMPLETED);
          showCompletionPopup(data, true);
        } else {
          transitionTo(FSM_STATES.FAILED);
          showCompletionPopup(data, false);
        }

      } else if (status === 'no_speech') {
        statusText.textContent = 'No speech detected. Please try again.';
        // Show response section with fallback message
        const respEl = document.getElementById('response-text');
        const speech = data?.speech || { text: "I didn't catch that. Could you try again?" };
        if (respEl) respEl.textContent = speech.text || '';
        revealSection('sec-response');
        setSectionState('sec-response', 'completed');
        clearMicStatus();
        transitionTo(FSM_STATES.IDLE);

      } else if (status === 'requires_confirmation') {
        console.log('Waiting for confirmation');
        statusText.textContent = 'Awaiting your confirmation…';
        transitionTo(FSM_STATES.WAITING_FOR_CONFIRMATION);
        renderConfirmationCard(data.confirmation);

      } else if (status === 'error') {
        statusText.textContent = 'Error: ' + (message || 'Unknown error');
        sections.forEach(id => {
          const el = document.getElementById(id);
          if (el && el.classList.contains('processing')) {
            setSectionState(id, 'failed');
            clearProcessingHint(id);
          }
        });
        clearMicStatus();
        console.log("Execution Finished");
        transitionTo(FSM_STATES.FAILED);
        showCompletionPopup({ error: message || 'Unknown error' }, false);

        if (data && data.success === false && data.error) {
          renderConfirmationCard({
            id: null,
            message: "❌ Unable to generate a valid execution plan.",
            error: data.error,
            plan: null,
            permissions: null,
            remaining_seconds: 0
          });
        }
      }
      break;
    }

    default: {
      console.warn("Any missing event", stage, event);
      break;
    }
  }
}

// ══════════════════════════════════════════════════════════════════════
// Execution log helpers
// ══════════════════════════════════════════════════════════════════════

function appendExecLogRow(text, type) {
  const execDiv = document.getElementById('execution-val');
  if (!execDiv) return;

  // Ignore confirmation payloads in row layout
  if (text.startsWith('__REQUIRES_CONFIRMATION__:')) return;

  const row = document.createElement('div');
  row.className = 'exec-log-row';

  let iconHtml = '';
  let textClass = '';

  if (type === 'running') {
    iconHtml = '<span class="exec-log-icon">⟳</span>';
  } else if (type === 'confirm') {
    iconHtml = '<span class="exec-log-icon">⚠</span>';
  } else if (type === 'success') {
    iconHtml = '<span class="exec-log-icon">✓</span>';
    textClass = 'success';
  } else if (type === 'failure') {
    iconHtml = '<span class="exec-log-icon">✗</span>';
    textClass = 'failure';
  } else {
    iconHtml = '<span class="exec-log-icon">·</span>';
  }

  if (text.startsWith('Step ')) {
    textClass = 'step-label';
    iconHtml = '<span class="exec-log-icon">➔</span>';
  }

  row.innerHTML = `${iconHtml}<span class="exec-log-text ${textClass}">${escapeHtml(text)}</span>`;
  execDiv.appendChild(row);
}

function finaliseExecLog(steps) {
  const execDiv = document.getElementById('execution-val');
  if (!execDiv) return;

  // Update all ongoing step spinner icons to done
  const rows = execDiv.querySelectorAll('.exec-log-row');
  rows.forEach(row => {
    const iconEl = row.querySelector('.exec-log-icon');
    const textEl = row.querySelector('.exec-log-text');
    if (iconEl && iconEl.textContent === '⟳') {
      iconEl.textContent = '✓';
      if (textEl) {
        textEl.className = 'exec-log-text success';
      }
    }
  });


  // Final completion row — all steps done
}

// ══════════════════════════════════════════════════════════════════════
// Confirmation Card
// ══════════════════════════════════════════════════════════════════════

function renderConfirmationCard(confirmation) {
  console.log("Showing confirmation");
  const card = document.getElementById('confirmation-card');
  const messageEl = document.getElementById('confirm-message');
  const detailsEl = document.getElementById('confirm-details');
  const editTextarea = document.getElementById('confirm-edit-textarea');
  const proceedBtn = document.getElementById('btn-proceed');
  const cancelBtn = document.getElementById('btn-cancel');
  const editBtn = document.getElementById('btn-edit');

  activeConfirmationId = confirmation.id;

  const hasBackendError = !!confirmation.error;
  const validation = hasBackendError ? { valid: false, errors: [confirmation.error] } : validatePlanFrontend(confirmation);
  const proceedEnabled = !hasBackendError && validation.valid && confirmation.plan && confirmation.plan.steps.length > 0;

  // Print FSM / Validation logs
  console.log("-------------------------------------------------");
  console.log("[FRONTEND PLAN VALIDATION LOGS]");
  console.log("Planner Output:", confirmation ? confirmation.plan : null);
  console.log("Validated Plan:", validation.valid);
  console.log("Steps Count:", (confirmation && confirmation.plan && confirmation.plan.steps) ? confirmation.plan.steps.length : 0);
  console.log("Proceed Enabled =", proceedEnabled);
  if (!proceedEnabled) {
    console.log("Reason if false:", validation.errors.join(", "));
  }
  console.log("-------------------------------------------------");

  // Transition to Waiting for User Confirmation state
  transitionTo(FSM_STATES.APPROVAL);

  detailsEl.style.display = '';
  editTextarea.style.display = 'none';
  card.style.display = '';
  card.classList.remove('fading-out');

  // Clone nodes to purge old listeners
  const newProceed = proceedBtn.cloneNode(true);
  const newCancel = cancelBtn.cloneNode(true);
  const newEdit = editBtn.cloneNode(true);
  proceedBtn.parentNode.replaceChild(newProceed, proceedBtn);
  cancelBtn.parentNode.replaceChild(newCancel, cancelBtn);
  editBtn.parentNode.replaceChild(newEdit, editBtn);

  if (!proceedEnabled) {
    // Show validation failure UI
    messageEl.innerHTML = `<span style="color: #dc2626;">❌ Unable to generate a valid execution plan.</span>`;

    let errHtml = `<div class="confirm-error-reason" style="color: #dc2626; font-weight: bold; margin-bottom: 12px; font-size: 14px;">
      Reason:<br>
      <span style="font-weight: normal; color: var(--text);">${escapeHtml(validation.errors.join("<br>"))}</span>
    </div>`;
    detailsEl.innerHTML = errHtml;

    // Proceed button rules: hide Proceed
    newProceed.style.display = 'none';

    // Set Retry button
    newEdit.textContent = 'Retry';
    newEdit.style.backgroundColor = '#2563eb'; // blue
    newEdit.style.color = '#fff';
    newEdit.disabled = false;
    newEdit.style.opacity = '1';

    newCancel.textContent = 'Cancel';
    newCancel.disabled = false;
    newCancel.style.opacity = '1';

    // Hook listeners
    newEdit.addEventListener('click', () => {
      hideConfirmationCard();
      if (lastAudioBlob) {
        statusText.textContent = 'Retrying planning...';
        sendAudio(lastAudioBlob, 'recording.webm');
      } else {
        statusText.textContent = 'No recorded audio available to retry. Please record audio again.';
      }
    });

    newCancel.addEventListener('click', () => {
      hideConfirmationCard();
      transitionTo(FSM_STATES.CANCELLED);
      statusText.textContent = 'Cancelled.';
      setTimeout(() => transitionTo(FSM_STATES.IDLE), 2000);
    });

  } else {
    // Proceed enabled UI: Ask for USER CONFIRMATION only
    messageEl.innerHTML = `<strong>Confirm Task Execution</strong>`;

    if (!confirmation.task_description) {
      const match = (confirmation.message || "").match(/'([^']+)'/);
      confirmation.task_description = match ? match[1] : (confirmation.message || "Execute user request");
    }

    detailsEl.innerHTML = buildConfirmDetails(confirmation);

    newProceed.style.display = 'inline-block';
    newProceed.textContent = 'Proceed';
    newProceed.disabled = false;
    newProceed.style.opacity = '1';

    newCancel.textContent = 'Cancel';
    newCancel.disabled = false;
    newCancel.style.opacity = '1';

    newEdit.textContent = 'Edit Plan';
    newEdit.style.backgroundColor = '#6c757d';
    newEdit.disabled = false;
    newEdit.style.opacity = '1';

    const remaining = confirmation.remaining_seconds || 60;
    startConfirmationTimer(remaining);

    let isEditing = false;
    let currentSteps = confirmation.plan ? (confirmation.plan.steps || []) : [];

    newEdit.addEventListener('click', () => {
      if (!isEditing) {
        isEditing = true;
        detailsEl.style.display = 'none';
        editTextarea.value = JSON.stringify(currentSteps, null, 2);
        editTextarea.style.display = '';
        newEdit.textContent = 'Save Plan';
        newEdit.style.backgroundColor = '#16A34A';
      } else {
        try {
          currentSteps = JSON.parse(editTextarea.value);
          isEditing = false;
          editTextarea.style.display = 'none';

          const updatedConfirmation = {
            ...confirmation,
            plan: { ...confirmation.plan, steps: currentSteps }
          };

          // Re-validate edited steps
          const reValidation = validatePlanFrontend(updatedConfirmation);
          if (!reValidation.valid) {
            alert("Edited plan failed validation: " + reValidation.errors.join(", "));
            isEditing = true;
            editTextarea.style.display = '';
            newEdit.textContent = 'Save Plan';
            newEdit.style.backgroundColor = '#16A34A';
            return;
          }

          detailsEl.innerHTML = buildConfirmDetails(updatedConfirmation);
          detailsEl.style.display = '';
          newEdit.textContent = 'Edit Plan';
          newEdit.style.backgroundColor = '#6c757d';
        } catch (err) {
          alert("Invalid JSON format. Please correct it before saving.");
        }
      }
    });

    newProceed.addEventListener('click', async () => {
      console.log("Proceed clicked");
      if (isEditing) {
        try {
          currentSteps = JSON.parse(editTextarea.value);
        } catch (err) {
          alert("Invalid JSON format. Please correct it before approving.");
          return;
        }
      }
      hideConfirmationCard();
      transitionTo(FSM_STATES.EXECUTING);
      console.log("Starting execution");
      await sendConfirmation('proceed', currentSteps);
    });

    newCancel.addEventListener('click', async () => {
      console.log("Cancel clicked");
      hideConfirmationCard();
      await sendConfirmation('cancel');
      transitionTo(FSM_STATES.IDLE);
    });
  }
}

function buildConfirmDetails(confirmation) {
  let html = '';

  if (confirmation.plan && confirmation.plan.steps) {
    const steps = confirmation.plan.steps;
    if (steps.length === 0) {
      return '<div style="color: #dc2626; font-weight: bold; padding: 12px; border: 1px solid #fecaca; background-color: #fef2f2; border-radius: 6px;">No executable actions generated.</div>';
    }

    // 1. Task Description
    html += `<div class="confirm-section" style="margin-bottom: 12px;">
      <strong style="font-size: 13px; color: var(--text-muted);">Task:</strong>
      <div style="font-size: 14px; font-weight: 600; margin-top: 4px;">${escapeHtml(confirmation.task_description || confirmation.message || "Execute user request")}</div>
    </div>`;

    // 2. Execution Plan
    html += `<div class="confirm-section" style="margin-bottom: 12px;">
      <strong style="font-size: 13px; color: var(--text-muted);">Execution Plan</strong>
      <ol style="margin-top: 6px; padding-left: 20px; list-style: decimal;">`;

    steps.forEach((step, index) => {
      const tool = step.tool || 'unknown';
      const desc = step.description || `Run ${tool.replace(/_/g, ' ')}`;
      html += `<li style="margin-bottom: 4px; font-size: 13px;">${escapeHtml(desc)}</li>`;
    });

    html += `</ol></div>`;

    // 3. Estimated Time
    let minTime = 5;
    let maxTime = 10;
    const hasWhatsApp = steps.some(s => s.tool && s.tool.includes("whatsapp"));
    const hasSpotify = steps.some(s => s.tool && (s.tool.includes("spotify") || s.tool.includes("music")));
    if (hasWhatsApp || hasSpotify) {
      minTime = 15;
      maxTime = 30;
    }
    html += `<div class="confirm-section" style="margin-bottom: 12px;">
      <strong style="font-size: 13px; color: var(--text-muted);">Estimated Time:</strong>
      <div style="font-size: 13px; margin-top: 2px;">${minTime}–${maxTime} seconds</div>
    </div>`;

    // 4. Automation Notice
    html += `<div class="confirm-section" style="margin-bottom: 12px; padding: 10px; border-left: 4px solid var(--primary); background: rgba(var(--primary-rgb), 0.1); border-radius: 4px;">
      <strong style="font-size: 12px; color: var(--primary);">Automation Notice</strong>
      <div style="font-size: 12px; margin-top: 2px; line-height: 1.4;">
        "This assistant will temporarily control your keyboard and mouse while executing the approved task."
      </div>
    </div>`;

    console.log("[FRONTEND] Rendered Steps Count:", steps.length);
    return html;
  }

  return '<div style="color: #dc2626; font-weight: bold; padding: 12px; border: 1px solid #fecaca; background-color: #fef2f2; border-radius: 6px;">No executable actions generated.</div>';
}

function getConfirmButtonLabel(tool) {
  const labels = {
    'send_whatsapp_message': 'Send Message',
    'type_message': 'Send Message',
    'delete_file': 'Delete',
    'delete_folder': 'Delete',
    'shutdown_system': 'Shutdown',
    'reboot_system': 'Reboot',
    'execute_shell': 'Execute',
  };
  return labels[tool] || 'Proceed';
}

function hideConfirmationCard() {
  const card = document.getElementById('confirmation-card');
  card.classList.add('fading-out');

  if (confirmationTimer) {
    clearInterval(confirmationTimer);
    confirmationTimer = null;
  }
  // Do not clear activeConfirmationId here, as sendConfirmation needs it!

  setTimeout(() => {
    card.style.display = 'none';
    card.classList.remove('fading-out');
  }, 350);
}

async function sendConfirmation(decision, editedSteps = null) {
  if (!activeConfirmationId) return;

  const confirmId = activeConfirmationId;
  activeConfirmationId = null;
  const proceedBtn = document.getElementById('btn-proceed');
  const cancelBtn = document.getElementById('btn-cancel');
  const editBtn = document.getElementById('btn-edit');

  proceedBtn.disabled = true;
  cancelBtn.disabled = true;
  editBtn.disabled = true;
  proceedBtn.style.opacity = '0.6';
  cancelBtn.style.opacity = '0.6';
  editBtn.style.opacity = '0.6';

  statusText.textContent = decision === 'proceed' ? 'Executing…' : 'Cancelling…';

  try {
    const payload = {
      confirmation_id: confirmId,
      decision: decision,
    };
    if (editedSteps) {
      payload.edited_steps = editedSteps;
    }

    const res = await fetch('/confirm?stream=true', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream'
      },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const errorText = await res.text();
      throw new Error(`Server returned ${res.status}: ${errorText}`);
    }

    if (decision === 'proceed') {
      hideConfirmationCard();
      const execDiv = document.getElementById('execution-val');
      if (execDiv) execDiv.innerHTML = '';
      await consumeSSEStream(res.body);
    } else {
      hideConfirmationCard();
      statusText.textContent = 'Action cancelled.';
      document.getElementById('sec-response').classList.add('visible');
    }

  } catch (err) {
    hideConfirmationCard();
    statusText.textContent = 'Error during confirmation: ' + err.message;
    transitionTo(FSM_STATES.IDLE);
    console.error("Confirmation error:", err);
  }
}

function startConfirmationTimer(seconds) {
  if (confirmationTimer) clearInterval(confirmationTimer);

  confirmationCountdown = seconds;
  const totalSeconds = seconds;
  const timerText = document.getElementById('confirm-timer-text');
  const timerFill = document.getElementById('confirm-timer-fill');

  timerText.textContent = `${confirmationCountdown}s`;
  timerFill.style.width = `${(confirmationCountdown / totalSeconds) * 100}%`;

  confirmationTimer = setInterval(() => {
    confirmationCountdown--;

    if (confirmationCountdown <= 0) {
      clearInterval(confirmationTimer);
      confirmationTimer = null;

      timerText.textContent = 'Timed out';
      timerFill.style.width = '0%';
      statusText.textContent = 'Confirmation timed out.';

      setTimeout(() => {
        hideConfirmationCard();
        if (activeConfirmationId) {
          fetch('/confirm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              confirmation_id: activeConfirmationId,
              decision: 'cancel',
            }),
          }).catch(() => { });
        }
      }, 1000);
      return;
    }

    timerText.textContent = `${confirmationCountdown}s`;
    timerFill.style.width = `${(confirmationCountdown / totalSeconds) * 100}%`;
  }, 1000);
}

// ══════════════════════════════════════════════════════════════════════
// Page Load: Check for pending confirmations (survives refresh)
// ══════════════════════════════════════════════════════════════════════

async function checkPendingConfirmation() {
  try {
    const res = await fetch('/pending');
    const data = await res.json();
    if (data.confirmation) {
      statusText.textContent = 'Pending confirmation restored.';
      renderConfirmationCard(data.confirmation);
    } else {
      transitionTo(FSM_STATES.IDLE);
    }
  } catch (_) {
    transitionTo(FSM_STATES.IDLE);
  }
}

checkPendingConfirmation();

// ══════════════════════════════════════════════════════════════════════
// Utilities
// ══════════════════════════════════════════════════════════════════════

function syntaxHighlight(json) {
  return json.replace(
    /("(\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g,
    match => {
      let cls = 'json-number';
      if (/^"/.test(match)) {
        cls = /:$/.test(match) ? 'json-key' : 'json-string';
      } else if (/true|false/.test(match)) cls = 'json-boolean';
      else if (/null/.test(match)) cls = 'json-null';
      return '<span class="' + cls + '">' + match + '</span>';
    }
  );
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ══════════════════════════════════════════════════════════════════════
// Execution Completion Popup Helpers
// ══════════════════════════════════════════════════════════════════════

function showCompletionPopup(data, success) {
  console.log("Popup Triggered");
  const popup = document.getElementById('completion-popup');
  const header = document.getElementById('completion-popup-header');
  const icon = document.getElementById('completion-popup-icon');
  const title = document.getElementById('completion-popup-title');
  const responseEl = document.getElementById('completion-popup-response');
  const summaryEl = document.getElementById('completion-popup-summary');
  const errorSection = document.getElementById('completion-popup-error-section');
  const errorEl = document.getElementById('completion-popup-error');

  if (!popup) return;

  // Clear existing timers
  if (popupAutoCloseTimer) clearTimeout(popupAutoCloseTimer);
  if (fsmIdleTimer) clearTimeout(fsmIdleTimer);

  // Setup header styling
  if (success) {
    if (header) header.className = 'completion-popup-header success';
    if (icon) icon.textContent = '✓';
    if (title) title.textContent = 'Task Completed';
  } else {
    if (header) header.className = 'completion-popup-header failure';
    if (icon) icon.textContent = '❌';
    if (title) title.textContent = 'Task Failed';
  }

  // Setup response text
  const responseText = (data && data.speech && data.speech.text) ||
    (data && data.speech && typeof data.speech === 'string' ? data.speech : '') ||
    (success ? 'Task completed successfully.' : 'An error occurred during execution.');
  if (responseEl) responseEl.textContent = responseText;

  // Setup summary
  if (summaryEl) {
    summaryEl.innerHTML = '';
    const executionSteps = (data && data.execution) ? data.execution : [];
    if (executionSteps.length > 0) {
      executionSteps.forEach(step => {
        const row = document.createElement('div');
        row.className = 'completion-popup-step-row';
        const stepName = document.createElement('span');
        stepName.className = 'completion-popup-step-name';
        stepName.textContent = step.tool || 'unknown';

        const stepStatus = document.createElement('span');
        stepStatus.className = 'completion-popup-step-status ' + (step.success ? 'success' : 'failure');
        stepStatus.textContent = step.success ? '✓ Success' : '✗ Failed';

        row.appendChild(stepName);
        row.appendChild(stepStatus);
        summaryEl.appendChild(row);
      });
    } else {
      const fallbackText = document.createElement('div');
      fallbackText.style.fontSize = '12px';
      fallbackText.style.color = 'var(--text-muted)';
      fallbackText.style.fontStyle = 'italic';
      fallbackText.textContent = success ? 'No action steps required (Conversational).' : 'No steps executed.';
      summaryEl.appendChild(fallbackText);
    }
  }

  // Setup error
  if (errorSection && errorEl) {
    const errorMsg = (data && data.error) || '';
    if (errorMsg) {
      errorEl.textContent = errorMsg;
      errorSection.classList.remove('hidden');
    } else {
      errorSection.classList.add('hidden');
    }
  }

  // Show popup
  popup.classList.remove('hidden');
  popup.setAttribute('aria-hidden', 'false');

  // Setup auto-close timers (5 seconds)
  popupAutoCloseTimer = setTimeout(() => {
    hideCompletionPopup();
  }, 5000);

  fsmIdleTimer = setTimeout(() => {
    transitionTo(FSM_STATES.IDLE);
  }, 5000);
}

function hideCompletionPopup() {
  const popup = document.getElementById('completion-popup');
  if (popup && !popup.classList.contains('hidden')) {
    popup.classList.add('hidden');
    popup.setAttribute('aria-hidden', 'true');
    console.log("Popup Closed");
  }
  if (popupAutoCloseTimer) {
    clearTimeout(popupAutoCloseTimer);
    popupAutoCloseTimer = null;
  }
}

// ══════════════════════════════════════════════════════════════════════
// Event Listeners for Completion Popup and Audio Player
// ══════════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
  const closeBtn = document.getElementById('completion-popup-close-btn');
  if (closeBtn) {
    closeBtn.addEventListener('click', async () => {
      await unlockAudio();
      hideCompletionPopup();
    });
  }

  // ============================================================================
  // Audio Player Logging
  // ============================================================================

  const audioPlayer = document.getElementById("audio-player");

  if (audioPlayer) {
    audioPlayer.addEventListener("play", () => {
      console.log("[AUDIO] Playback started");
    });

    audioPlayer.addEventListener("ended", () => {
      console.log("[AUDIO] Playback completed");
    });

    audioPlayer.addEventListener("error", () => {
      const declaredSource =
        audioPlayer.getAttribute("src");

      if (!declaredSource) {
        return;
      }

      const source =
        audioPlayer.currentSrc || declaredSource;

      const error = audioPlayer.error;

      console.error("[AUDIO] Playback failed:", {
        code: error?.code,
        message: error?.message,
        src: source,
        networkState: audioPlayer.networkState,
        readyState: audioPlayer.readyState,
      });

      switch (error?.code) {
        case MediaError.MEDIA_ERR_ABORTED:
          console.error("[AUDIO] Audio loading was aborted.");
          break;

        case MediaError.MEDIA_ERR_NETWORK:
          console.error("[AUDIO] Network error while loading audio.");
          break;

        case MediaError.MEDIA_ERR_DECODE:
          console.error(
            "[AUDIO] Audio file could not be decoded or is corrupted."
          );
          break;

        case MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED:
          console.error(
            "[AUDIO] Audio source is empty, invalid, or unsupported."
          );
          break;

        default:
          console.error("[AUDIO] Unknown playback error.");
      }
    });
  } else {
    console.warn("[AUDIO] #audio-player element not found.");
  }

  // ============================================================================
  // File Search Modal Logic
  // ============================================================================

  function showFileSearchModal(results) {
    console.log(
      "================================================================================"
    );
    console.log("[MODAL] ENTER showFileSearchModal");
    console.log("[MODAL] Results received:", results);
    console.log(
      "[MODAL] Results count:",
      results ? results.length : 0
    );

    const modal = document.getElementById("file-search-modal");
    const resultsContainer =
      document.getElementById("file-search-results");
    const actionsContainer =
      document.getElementById("file-search-actions");

    console.log("[MODAL] Modal element:", modal);
    console.log("[MODAL] Results container:", resultsContainer);
    console.log("[MODAL] Actions container:", actionsContainer);

    if (!modal || !resultsContainer || !actionsContainer) {
      console.error("[MODAL] Missing required elements:");

      if (!modal) {
        console.error("[MODAL] - modal is null");
      }

      if (!resultsContainer) {
        console.error("[MODAL] - resultsContainer is null");
      }

      if (!actionsContainer) {
        console.error("[MODAL] - actionsContainer is null");
      }

      return;
    }

    console.log("[MODAL] All elements found, clearing containers");

    resultsContainer.innerHTML = "";
    actionsContainer.innerHTML = "";

    const safeResults = Array.isArray(results) ? results : [];

    console.log("[MODAL] Processing results...");

    safeResults.forEach((res, index) => {
      console.log(
        `[MODAL] Processing result ${index + 1}:`,
        res
      );

      const num = index + 1;
      const filename =
        res.filename || `Document ${num}`;

      const folderPath =
        res.folder_path ||
        res.folder ||
        "";

      const modifiedDate =
        res.modified_date ||
        (
          res.modified_ts
            ? new Date(
              res.modified_ts * 1000
            ).toDateString()
            : "N/A"
        );

      const confidence =
        res.confidence ||
        (
          res.score
            ? `${Math.round(res.score * 100)}%`
            : "N/A"
        );

      const div = document.createElement("div");

      div.style.padding = "12px";
      div.style.border =
        "1px solid var(--border, #eee)";
      div.style.borderRadius = "8px";
      div.style.background = "#fafafa";

      div.innerHTML = `
        <div
          class="doc-item-title"
          style="
            font-weight: 600;
            color: var(--primary, #007bff);
            cursor: pointer;
          "
        >
          ${num}. ${escapeHtml(filename)}
        </div>

        <div
          style="
            font-size: 0.85rem;
            color: #555;
            margin-top: 4px;
          "
        >
          Folder: ${escapeHtml(folderPath)}
        </div>

        <div
          style="
            font-size: 0.85rem;
            color: #555;
          "
        >
          Modified: ${escapeHtml(modifiedDate)}
        </div>

        <div
          style="
            font-size: 0.85rem;
            color: #555;
          "
        >
          Confidence: ${escapeHtml(confidence)}
        </div>
      `;

      const titleEl =
        div.querySelector(".doc-item-title");

      if (titleEl) {
        titleEl.onclick = () => {
          modal.style.display = "none";

          showDocumentOpenConfirmation(
            num,
            filename
          );
        };
      }

      resultsContainer.appendChild(div);

      console.log(
        `[MODAL] Added result ${num} to container`
      );

      const btn = document.createElement("button");

      btn.className = "btn btn-primary";
      btn.style.padding = "6px 12px";
      btn.style.fontSize = "0.85rem";
      btn.textContent = `Open number ${num}`;

      btn.onclick = () => {
        console.log(
          `[MODAL] Button ${num} clicked. ` +
          "Hiding search modal and showing confirmation popup."
        );

        modal.style.display = "none";

        showDocumentOpenConfirmation(
          num,
          filename
        );
      };

      actionsContainer.appendChild(btn);

      console.log(
        `[MODAL] Added button ${num} to actions`
      );
    });

    const cancelBtn =
      document.createElement("button");

    cancelBtn.className =
      "btn btn-cancel-action";

    cancelBtn.style.padding = "6px 12px";
    cancelBtn.style.fontSize = "0.85rem";
    cancelBtn.textContent = "Cancel";

    cancelBtn.onclick = () => {
      console.log(
        "[MODAL] Cancel button clicked, hiding modal"
      );

      modal.style.display = "none";
      modal.classList.add("hidden");
    };

    actionsContainer.appendChild(cancelBtn);

    console.log("[MODAL] Added cancel button");
    console.log(
      "[MODAL] Setting modal display to flex"
    );

    modal.classList.remove("hidden");
    modal.style.display = "flex";

    console.log("[MODAL] EXIT showFileSearchModal");
  }

  let isOpeningDocument = false;

  async function simulateUserCommand(text) {
    if (isOpeningDocument) {
      return;
    }

    isOpeningDocument = true;

    try {
      const formData = new FormData();
      formData.append("text", text);

      const response = await fetch(
        "/transcribe_stream",
        {
          method: "POST",
          body: formData,
        }
      );

      if (!response.ok) {
        console.error(
          "[DOCUMENT] Command request failed:",
          response.status
        );
        return;
      }

      await consumeSSEStream(response.body);
    } catch (error) {
      console.error(
        "[DOCUMENT] Command execution failed:",
        error
      );
    } finally {
      setTimeout(() => {
        isOpeningDocument = false;
      }, 1000);
    }
  }

  // ============================================================================
  // Permission Layer Confirmation Popup
  // ============================================================================

  function showDocumentOpenConfirmation(
    num,
    filename
  ) {
    const confirmModal =
      document.getElementById("doc-confirm-modal");

    const confirmMessage =
      document.getElementById(
        "doc-confirm-message"
      );

    const openBtn =
      document.getElementById(
        "doc-confirm-open-btn"
      );

    const cancelBtn =
      document.getElementById(
        "doc-confirm-cancel-btn"
      );

    if (!confirmModal || !openBtn || !cancelBtn) {
      console.error(
        "[CONFIRM MODAL] Required elements missing."
      );

      simulateUserCommand(
        `Open number ${num}`
      );

      return;
    }

    if (confirmMessage) {
      confirmMessage.textContent =
        `Are you sure you want to open ` +
        `document ${num} (${filename})?`;
    }

    confirmModal.classList.remove("hidden");
    confirmModal.style.display = "flex";

    openBtn.onclick = () => {
      confirmModal.style.display = "none";
      confirmModal.classList.add("hidden");

      console.log(
        `[CONFIRM MODAL] User confirmed ` +
        `opening document number ${num}`
      );

      simulateUserCommand(
        `Open number ${num}`
      );
    };

    cancelBtn.onclick = () => {
      confirmModal.style.display = "none";
      confirmModal.classList.add("hidden");

      console.log(
        "[CONFIRM MODAL] User cancelled document opening."
      );
    };
  }

  // ============================================================================
  // File Search Modal Helper
  // ============================================================================

  function closeFileSearchModal() {
    const modal =
      document.getElementById("file-search-modal");

    if (modal) {
      modal.style.display = "none";
      modal.classList.add("hidden");
    }
  }

  // ============================================================================
  // Text Command Helper
  // ============================================================================

  function sendTextCommand(text) {
    if (statusText) {
      statusText.textContent = "";
    }

    transitionTo(FSM_STATES.PROCESSING);

    // Abort any previous stream.
    if (activeStreamController) {
      activeStreamController.abort();
    }

    activeStreamController =
      new AbortController();

    const formData = new FormData();
    formData.append("text", text);

    fetch("/transcribe_stream", {
      method: "POST",
      body: formData,
      signal: activeStreamController.signal,
    })
      .then((response) => {
        if (!response.ok) {
          console.error(
            "[TEXT COMMAND] Request failed:",
            response.status
          );
          return;
        }

        return consumeSSEStream(response.body);
      })
      .catch((error) => {
        if (error.name === "AbortError") {
          console.log(
            "[TEXT COMMAND] Previous request aborted."
          );
          return;
        }

        console.error(
          "[TEXT COMMAND] Request error:",
          error
        );
      });
  }

}); 