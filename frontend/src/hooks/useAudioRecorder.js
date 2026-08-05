import { useState, useRef, useCallback } from 'react';

export function useAudioRecorder() {
  const [isRecording, setIsRecording] = useState(false);
  const [micStatusText, setMicStatusText] = useState('');
  const [recordingDuration, setRecordingDuration] = useState(0);

  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const timerIntervalRef = useRef(null);
  const audioContextRef = useRef(null);
  const isAudioUnlockedRef = useRef(false);

  // Unlock Web Audio API context on first click
  const unlockAudio = useCallback(async () => {
    if (isAudioUnlockedRef.current) return;
    try {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) {
        isAudioUnlockedRef.current = true;
        return;
      }
      if (!audioContextRef.current) {
        audioContextRef.current = new AudioContextClass();
      }
      if (audioContextRef.current.state === 'suspended') {
        await audioContextRef.current.resume();
      }
      const buffer = audioContextRef.current.createBuffer(1, 1, audioContextRef.current.sampleRate);
      const source = audioContextRef.current.createBufferSource();
      source.buffer = buffer;
      source.connect(audioContextRef.current.destination);
      source.start(0);
      isAudioUnlockedRef.current = true;
    } catch (err) {
      console.warn('[AUDIO] Audio unlock error:', err);
    }
  }, []);

  const startRecording = useCallback(async (onAudioRecorded) => {
    await unlockAudio();
    audioChunksRef.current = [];

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      let mimeType = 'audio/webm';
      if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
        mimeType = 'audio/webm;codecs=opus';
      } else if (MediaRecorder.isTypeSupported('audio/ogg;codecs=opus')) {
        mimeType = 'audio/ogg;codecs=opus';
      }

      const recorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      recorder.onstop = () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: recorder.mimeType || 'audio/webm' });
        stream.getTracks().forEach((track) => track.stop());
        setIsRecording(false);
        setMicStatusText('');
        clearInterval(timerIntervalRef.current);
        setRecordingDuration(0);

        if (onAudioRecorded && audioBlob.size > 0) {
          onAudioRecorded(audioBlob);
        }
      };

      recorder.start(100);
      setIsRecording(true);
      setMicStatusText('Recording audio...');
      setRecordingDuration(0);

      timerIntervalRef.current = setInterval(() => {
        setRecordingDuration((prev) => prev + 1);
      }, 1000);
    } catch (err) {
      console.error('[RECORDER] Access denied or error:', err);
      setMicStatusText('Microphone access denied');
      setIsRecording(false);
    }
  }, [unlockAudio]);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
      setMicStatusText('Processing recording...');
    }
  }, []);

  return {
    isRecording,
    micStatusText,
    recordingDuration,
    startRecording,
    stopRecording,
    unlockAudio,
  };
}
