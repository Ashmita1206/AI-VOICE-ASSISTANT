"""
Remote Whisper STT Client
==========================

Sends an audio file to the Colab-hosted Faster-Whisper Flask API and
returns a result dict that is **byte-for-byte compatible** with the local
``WhisperSTT.transcribe()`` contract so every downstream caller
(services.py, stream_service.py, tests) works without modification.

Expected response shape from the Colab server:
    {
        "text":                 str,
        "raw_text":             str,
        "language":             str,
        "language_probability": float,
        "duration":             float,
        "processing_time":      float,
        "segments":             list
    }

Configuration (via .env):
    STT_API_URL      — full URL to the /transcribe endpoint
                       e.g. https://abcd1234.ngrok-free.app/transcribe
    STT_API_TIMEOUT  — request timeout in seconds (default: 60)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)

# ── Type alias (matches local WhisperSTT) ────────────────────────────
TranscriptionResult = dict[str, Any]


class RemoteWhisperSTT:
    """Transcription client that delegates to the Colab GPU server.

    Drop-in replacement for :class:`stt.whisper_engine.WhisperSTT`.
    Both expose the same ``transcribe(audio_path) -> TranscriptionResult``
    interface so callers need zero changes.

    Parameters
    ----------
    api_url : str, optional
        Full URL to the remote ``/transcribe`` endpoint.
        Defaults to ``config.STT_API_URL``.
    timeout : int, optional
        HTTP request timeout in seconds.
        Defaults to ``config.STT_API_TIMEOUT``.
    """

    def __init__(
        self,
        api_url: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.api_url = (api_url or config.STT_API_URL).rstrip("/")
        self.timeout = timeout or config.STT_API_TIMEOUT

        if not self.api_url:
            raise ValueError(
                "STT_API_URL is not set. "
                "Add it to your .env file: STT_API_URL=https://<ngrok-url>/transcribe"
            )

        logger.info(
            "RemoteWhisperSTT configured — api_url=%s  timeout=%ds",
            self.api_url,
            self.timeout,
        )

    # ── Public interface ─────────────────────────────────────────────

    def transcribe(self, audio_path: str) -> TranscriptionResult:
        """Send *audio_path* to the Colab API and return a structured result.

        Parameters
        ----------
        audio_path : str
            Path to any audio file (WAV, MP3, WebM, OGG, FLAC …).

        Returns
        -------
        TranscriptionResult
            Same shape as ``WhisperSTT.transcribe()`` — guaranteed to
            contain at minimum: ``text``, ``language``,
            ``language_probability``, ``duration``, ``processing_time``.

        Raises
        ------
        FileNotFoundError
            If *audio_path* does not exist.
        RuntimeError
            On any network error, timeout, HTTP error, or server-side
            transcription failure.
        """
        if not os.path.isfile(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        file_size_kb = os.path.getsize(audio_path) / 1024
        logger.info(
            "Sending audio to remote STT API: %s (%.1f KB) → %s",
            os.path.basename(audio_path),
            file_size_kb,
            self.api_url,
        )
        print(f"[REMOTE STT] Uploading audio...")
        print(f"[REMOTE STT] POST {self.api_url}")
        print(f"[REMOTE STT] Payload size: {file_size_kb:.1f} KB")

        t_start = time.perf_counter()

        try:
            with open(audio_path, "rb") as audio_file:
                filename = os.path.basename(audio_path)
                response = requests.post(
                    self.api_url,
                    files={"audio": (filename, audio_file)},
                    timeout=self.timeout,
                )
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError(
                f"Cannot reach the Colab STT server at {self.api_url}. "
                f"Is the Colab notebook still running? Original error: {exc}"
            ) from exc
        except requests.exceptions.Timeout:
            raise RuntimeError(
                f"Colab STT server timed out after {self.timeout}s. "
                f"The audio file may be too large, or the GPU is busy. "
                f"Try increasing STT_API_TIMEOUT in your .env."
            )
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(
                f"Network error while contacting Colab STT API: {exc}"
            ) from exc

        round_trip_ms = int((time.perf_counter() - t_start) * 1000)
        response_size_kb = len(response.content) / 1024

        print(f"[REMOTE STT] Response received in {round_trip_ms / 1000:.2f} sec")
        print(f"[REMOTE STT] HTTP status: {response.status_code}")
        print(f"[REMOTE STT] Response size: {response_size_kb:.1f} KB")

        # ── HTTP error handling ───────────────────────────────────────
        if response.status_code != 200:
            try:
                err_body = response.json()
                server_msg = err_body.get("error", response.text[:200])
            except Exception:
                server_msg = response.text[:200]

            raise RuntimeError(
                f"Colab STT server returned HTTP {response.status_code}: {server_msg}"
            )

        # ── Parse JSON ───────────────────────────────────────────────
        try:
            data: dict[str, Any] = response.json()
        except Exception as exc:
            raise RuntimeError(
                f"Colab STT server returned invalid JSON: {exc}"
            ) from exc

        if "error" in data:
            raise RuntimeError(f"Colab STT server error: {data['error']}")

        # ── Normalise / fill defaults ─────────────────────────────────
        result: TranscriptionResult = {
            "text":                 data.get("text", ""),
            "translated_text":     data.get("translated_text", data.get("text", "")),
            "raw_text":             data.get("raw_text", data.get("text", "")),
            "segments":             data.get("segments", []),
            "language":             data.get("language", ""),
            "language_probability": float(data.get("language_probability", 0.0)),
            "duration":             float(data.get("duration", 0.0)),
            "processing_time":      float(data.get("processing_time", 0.0)),
        }

        logger.info(
            "Remote transcription done — lang=%s (%.0f%%)  "
            "server_time=%.2fs  round_trip=%dms  text='%s'",
            result["language"],
            result["language_probability"] * 100,
            result["processing_time"],
            round_trip_ms,
            result["text"][:80],
        )
        print(f"[REMOTE STT] Latency (server): {result['processing_time']:.2f} sec")
        print(f"[REMOTE STT] Latency (round-trip): {round_trip_ms / 1000:.2f} sec")
        print(f"[REMOTE STT] Text: \"{result['text'][:120]}\"")
        return result

    # ── Health check ─────────────────────────────────────────────────

    def check_health(self) -> bool:
        """Return ``True`` if the remote server responds to ``GET /health``.

        This is a best-effort check; it does not raise on failure.
        """
        health_url = self.api_url.rsplit("/transcribe", 1)[0] + "/health"
        try:
            resp = requests.get(health_url, timeout=5)
            return resp.status_code == 200
        except Exception:
            return False
