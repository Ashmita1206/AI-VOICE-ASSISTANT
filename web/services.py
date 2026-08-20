"""
Pipeline Services
=================

Orchestrates the full voice assistant pipeline:
Audio → STT → Intent → Entities → Planner → Executor → Response → TTS

This is the single integration point that the Flask routes call.
"""

import os
import sys
import io
import time
import json
import logging
import tempfile
from typing import Any
from datetime import datetime

# Prevent UnicodeEncodeError on Windows stdout when printing emojis
if sys.platform.startswith("win") and not hasattr(sys.stdout, "_pytest_captured_and_tear_down") and "pytest" not in sys.modules:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import config
from stt.whisper_engine import WhisperSTT
from stt.remote_whisper import RemoteWhisperSTT
from agent.intent_classifier import IntentClassifier
from agent.preprocess import normalize_text
from agentic.schemas import ExecutionPlan, ActionStep
from agentic.llm.manager import get_planner_manager
from agentic.llm.schemas import PlannerOutput
from execution.executor import SystemExecutor
from tts.response_generator import generate_response
from tts.manager import TTSManager
from storage.history_manager import save_session

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
# Singleton Instances (lazy loaded)
# ══════════════════════════════════════════════════════════════════════
_stt: WhisperSTT | RemoteWhisperSTT | None = None
_classifier: IntentClassifier | None = None
_executor: SystemExecutor | None = None
_tts: TTSManager | None = None



def get_stt() -> WhisperSTT | RemoteWhisperSTT:
    """Return the STT engine singleton.

    If ``STT_USE_REMOTE=true`` in the environment, returns a
    :class:`RemoteWhisperSTT` that delegates to the Colab GPU server.
    Otherwise returns the local :class:`WhisperSTT` (default behaviour).
    """
    global _stt
    if _stt is None:
        if config.STT_USE_REMOTE:
            logger.info("STT mode: REMOTE (Colab GPU) → %s", config.STT_API_URL)
            _stt = RemoteWhisperSTT()
        else:
            logger.info("STT mode: LOCAL (Faster-Whisper on %s)", config.DEVICE)
            _stt = WhisperSTT()
    return _stt


def get_classifier() -> IntentClassifier:
    global _classifier
    if _classifier is None:
        _classifier = IntentClassifier()
    return _classifier


def get_executor() -> SystemExecutor:
    global _executor
    if _executor is None:
        _executor = SystemExecutor()
    return _executor


def get_tts() -> TTSManager:
    global _tts
    if _tts is None:
        _tts = TTSManager()
    return _tts


# ══════════════════════════════════════════════════════════════════════
# Main Pipeline
# ══════════════════════════════════════════════════════════════════════

def run_pipeline(audio_path: str) -> dict[str, Any]:
    """Run the full pipeline on an audio file and return the complete result."""
    pipeline_start = time.perf_counter()

    # ── Step 1: STT ──────────────────────────────────────
    stt = get_stt()
    mode_label = "REMOTE" if config.STT_USE_REMOTE else "LOCAL"
    print(f"[VOICE] Sending audio to {mode_label} STT ({os.path.basename(audio_path)})")
    t_stt = time.perf_counter()
    stt_result = stt.transcribe(audio_path)
    stt_ms = int((time.perf_counter() - t_stt) * 1000)

    transcription = stt_result["text"]
    translated_text = stt_result.get("translated_text") or transcription
    intent_input = translated_text or transcription

    if transcription.strip():
        print(f"\n Heard: \"{transcription}\"")
        if translated_text != transcription:
            print(f" Translation: \"{translated_text}\"")
        try:
            from agentic.memory.app_context import AppContextManager, get_active_window_info
            from agentic.memory.session_state import get_session
            info = get_active_window_info()
            if info["active_app"]:
                AppContextManager.set_context(
                    active_app=info["active_app"],
                    window_handle=info["window_handle"],
                    last_command=transcription
                )
                get_session().set_context(app=info["active_app"])
        except Exception:
            pass

    if not transcription.strip():
        print("\nHeard: [Silent / No Speech Detected]")
        return {
            "transcription": "",
            "translated_text": "",
            "stt": {
                "model": config.STT_MODEL_ID,
                "device": config.DEVICE,
                "compute_type": config.COMPUTE_TYPE,
                "language": stt_result.get("language", ""),
                "confidence": round(stt_result.get("language_probability", 0) * 100, 1),
                "processing_time_ms": int(stt_result.get("processing_time", 0) * 1000),
            },
            "intent": {"name": "unknown", "confidence": 0},
            "entities": {},
            "planner": {"thought": "", "steps": []},
            "execution": [],
            "speech": {"text": "I didn't catch that. Could you try again?"},
            "pipeline_time_ms": int((time.perf_counter() - pipeline_start) * 1000),
        }

    # ── Step 2: Intent Classification (fast cross-check) ───────────
    classifier = get_classifier()
    t_intent = time.perf_counter()
    command = classifier.classify(intent_input)
    intent_ms = int((time.perf_counter() - t_intent) * 1000)
    print(f"[INTENT] Detected: {command.intent} (Confidence: {round(command.confidence * 100, 1)}%)  [{intent_ms} ms]")
    print(f"[ENTITY] Detected: {command.entities}")
    print(f" Understanding intent: {command.intent} (Confidence: {round(command.confidence * 100, 1)}%)")

    # ── Step 3: Qwen3-8B Planning ──────────────────────────────
    print(" Generating execution plan...")
    print(f"[REMOTE LLM] Sending to planner...")
    t_plan = time.perf_counter()
    planner = get_planner_manager()
    planner_output = planner.plan(intent_input)
    plan_ms = int((time.perf_counter() - t_plan) * 1000)
    print(f"[REMOTE LLM] Plan received in {plan_ms} ms")

    # Convert PlannerOutput -> ExecutionPlan for the executor
    plan_steps = [
        ActionStep(tool=s.tool, args=s.args)
        for s in planner_output.steps
    ]
    plan = ExecutionPlan(
        thought=planner_output.reasoning,
        steps=plan_steps,
        response=""
    )
    
    print(f" Plan:")
    for idx, s in enumerate(plan_steps, 1):
        print(f"  {idx}. {s.tool}({s.args})")

    # ── Step 4: Execute ─────────────────────────────────────
    print("⚙ Executing task graph...")
    executor = get_executor()
    exec_results = []
    t_exec = time.perf_counter()
    
    for idx, step in enumerate(plan_steps, 1):
        print(f"⚙ [Step {idx}/{len(plan_steps)}] Executing {step.tool}...")
        print(f"[EXECUTOR] Running {step.tool}({step.args})")
        t_step = time.perf_counter()
        res_step = executor.execute_step(step)
        step_ms = int((time.perf_counter() - t_step) * 1000)
        exec_results.append(res_step.to_dict())
        if res_step.success:
            print(f"[Step {idx}/{len(plan_steps)}] {step.tool} completed in {step_ms} ms.")
        elif res_step.requires_confirmation:
            print(f" [Step {idx}/{len(plan_steps)}] {step.tool} requires user confirmation.")
            # Hand over rest of plan to executor to handle confirmation save
            remaining_plan = ExecutionPlan(
                thought=plan.thought,
                steps=plan_steps[idx-1:],
                response=""
            )
            exec_results = executor.execute(remaining_plan)
            break
        else:
            print(f" [Step {idx}/{len(plan_steps)}] {step.tool} failed: {res_step.message}. Triggering automated recovery replan...")
            # Try executor recovery block
            remaining_plan = ExecutionPlan(
                thought=plan.thought,
                steps=plan_steps[idx-1:],
                response=""
            )
            exec_results = executor.execute(remaining_plan)
            break

    print(" Plan execution finished.")
    exec_ms = int((time.perf_counter() - t_exec) * 1000)

    # ── Timing Summary ────────────────────────────────────────
    total_ms = int((time.perf_counter() - pipeline_start) * 1000)
    print("\n--- Pipeline Timing ---")
    print(f"  STT ({mode_label}):  {stt_ms} ms")
    print(f"  Intent:          {intent_ms} ms")
    print(f"  Planner:         {plan_ms} ms")
    print(f"  Executor:        {exec_ms} ms")
    print(f"  Total:           {total_ms} ms")
    print("-----------------------\n")

    # ── Step 4b: Check for pending confirmation ─────────────────────
    # If the executor flagged any step as requires_confirmation,
    # return a structured confirmation response instead of proceeding
    # to TTS and full result assembly.
    confirmation_step = next(
        (r for r in exec_results if r.get("requires_confirmation")),
        None,
    )
    if confirmation_step:
        confirmation_id = confirmation_step.get("confirmation_id")
        confirm_message = confirmation_step.get("message", "Confirm this action?")
        confirm_tool = confirmation_step.get("tool", "unknown")

        # Still save a lightweight history entry
        save_session({
            "transcription": transcription,
            "stt": {
                "model": config.STT_MODEL_ID,
                "device": config.DEVICE,
                "compute_type": config.COMPUTE_TYPE,
                "language": stt_result.get("language", ""),
                "confidence": round(stt_result.get("language_probability", 0) * 100, 1),
                "processing_time_ms": int(stt_result.get("processing_time", 0) * 1000),
            },
            "intent": {
                "name": planner_output.intent,
                "confidence": round(planner_output.confidence * 100, 1),
            },
            "entities": command.entities,
            "planner": planner_output.to_dict(),
            "execution": exec_results,
            "speech": {"text": confirm_message},
            "pipeline_time_ms": int((time.perf_counter() - pipeline_start) * 1000),
            "timestamp": datetime.now().isoformat(),
        })

        # Return the confirmation-specific response
        from agentic.memory.session_state import get_session as _get_session
        pending = _get_session().get_pending_confirmation()

        return {
            "status": "requires_confirmation",
            "transcription": transcription,
            "confirmation": {
                "id": confirmation_id,
                "message": confirm_message,
                "tool": confirm_tool,
                "args": pending["args"] if pending else {},
                "remaining_seconds": pending["remaining_seconds"] if pending else 60,
            },
            "intent": {
                "name": planner_output.intent,
                "confidence": round(planner_output.confidence * 100, 1),
            },
            "entities": command.entities,
            "planner": planner_output.to_dict(),
            "pipeline_time_ms": int((time.perf_counter() - pipeline_start) * 1000),
        }

    # ── Step 5: Generate Response ────────────────────────────────────
    response_text = generate_response(exec_results)

    # ── Step 6: TTS (generate audio file, don't play it server-side)
    tts = get_tts()
    speech_audio_path = _generate_tts_file(response_text)

    # ── Assemble Result ──────────────────────────────────────────────
    result = {
        "transcription": transcription,
        "translated_text": translated_text,
        "stt": {
            "model": config.STT_MODEL_ID,
            "device": config.DEVICE,
            "compute_type": config.COMPUTE_TYPE,
            "language": stt_result.get("language", ""),
            "confidence": round(stt_result.get("language_probability", 0) * 100, 1),
            "processing_time_ms": int(stt_result.get("processing_time", 0) * 1000),
        },
        "intent": {
            "name": planner_output.intent,
            "confidence": round(planner_output.confidence * 100, 1),
        },
        "entities": command.entities,
        "planner": planner_output.to_dict(),
        "execution": exec_results,
        "speech": {
            "text": response_text,
            "audio_url": f"/static/audio/{os.path.basename(speech_audio_path)}" if speech_audio_path else None,
        },
        "pipeline_time_ms": int((time.perf_counter() - pipeline_start) * 1000),
        "timestamp": datetime.now().isoformat(),
    }

    # Persist to SQLite
    save_session(result)

    return result


# _build_steps() has been replaced by the Qwen3-8B PlannerManager.
# The LLM now handles intent-to-tool mapping with multi-step reasoning.


def _generate_tts_file(text: str) -> str | None:
    """Synthesize text to an audio file in static/audio and return the path.
    Falls back to pyttsx3 if edge-tts is not available.
    """
    audio_dir = os.path.join(config.BASE_DIR, "web", "static", "audio")
    os.makedirs(audio_dir, exist_ok=True)

    filename = f"response_{int(time.time() * 1000)}.mp3"
    filepath = os.path.join(audio_dir, filename)

    # 1. Try edge-tts
    try:
        import asyncio
        import edge_tts
        communicate = edge_tts.Communicate(
            text=text,
            voice="en-US-ChristopherNeural",
            rate="+0%",
            volume="+0%",
        )
        asyncio.run(communicate.save(filepath))
        logger.info("Audio Generated: %s", filepath)
        return filepath
    except Exception as edge_err:
        logger.warning(f"Edge TTS file generation failed, trying pyttsx3 fallback: {edge_err}")

    # 2. Try pyttsx3 fallback
    try:
        import pyttsx3
        engine = pyttsx3.init()
        # Since pyttsx3 usually saves as WAV or native format depending on platform, we save as wav
        wav_filename = filename.replace(".mp3", ".wav")
        wav_filepath = os.path.join(audio_dir, wav_filename)
        engine.save_to_file(text, wav_filepath)
        engine.runAndWait()
        logger.info("Audio Generated: %s", wav_filepath)
        return wav_filepath
    except Exception as pyttsx_err:
        logger.error(f"TTS file generation failed for both edge-tts and pyttsx3: {pyttsx_err}")
        return None



def get_health() -> dict[str, Any]:
    """Return system health info."""
    return {
        "status": "ok",
        "model": config.STT_MODEL_ID,
        "device": config.DEVICE,
        "compute_type": config.COMPUTE_TYPE,
        "timestamp": datetime.now().isoformat(),
    }
