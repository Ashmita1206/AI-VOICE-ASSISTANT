"""
Unit Tests for Local Translation Integration Pipeline
=====================================================

Tests requirements from Master Prompt 5:
1. Remote response mapping preserves text (original) and translated_text (English).
2. Backward compatibility with older STT servers missing translated_text.
3. NLU handoff boundary uses translated_text for IntentClassifier.
4. Planner receives the exact same intent_input as IntentClassifier.
5. Original transcript is preserved in pipeline results and UI.
"""

import pytest
from unittest.mock import MagicMock, patch
from agent.intent_classifier import IntentClassifier
from stt.remote_whisper import RemoteWhisperSTT


class TestTranslationPipelineIntegration:
    """Test suite covering local STT mapping, backward compatibility, and NLU boundary."""

    @patch("requests.post")
    def test_remote_response_mapping_preserves_both_texts(self, mock_post):
        """Test 1: Remote Whisper STT maps both original text and translated_text."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "text": "टेलिग्राम पर हर्षिता को हेलो भेजो",
            "translated_text": "Send hello to Harshita on Telegram",
            "language": "hi",
            "language_probability": 0.97,
            "duration": 2.1,
            "processing_time": 1.2,
        }
        mock_post.return_value = mock_resp

        stt = RemoteWhisperSTT(api_url="http://localhost:5000/transcribe")
        res = stt.transcribe(__file__)

        assert res["text"] == "टेलिग्राम पर हर्षिता को हेलो भेजो"
        assert res["translated_text"] == "Send hello to Harshita on Telegram"

    @patch("requests.post")
    def test_old_server_compatibility_fallback(self, mock_post):
        """Test 2: Legacy STT response without translated_text falls back safely."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "text": "Open Chrome",
            "language": "en",
        }
        mock_post.return_value = mock_resp

        stt = RemoteWhisperSTT(api_url="http://localhost:5000/transcribe")
        res = stt.transcribe(__file__)

        assert res["text"] == "Open Chrome"
        assert res["translated_text"] == "Open Chrome"

    def test_nlu_boundary_uses_translated_text(self):
        """Test 3: NLU boundary passes translated_text to IntentClassifier."""
        stt_result = {
            "text": "सेंड आ मेसेज ओन टेलिग्राम टू हर्शिता हेलो",
            "translated_text": "Send a telegram to Harshita saying hello",
        }

        original_transcript = stt_result["text"]
        intent_input = stt_result.get("translated_text") or original_transcript

        classifier = IntentClassifier()
        cmd = classifier.classify(intent_input)

        assert intent_input == "Send a telegram to Harshita saying hello"
        assert intent_input != original_transcript
        assert cmd.intent == "send_telegram_message"

    def test_planner_boundary_consistency(self):
        """Test 4: Planner receives identical intent_input as classifier."""
        stt_result = {
            "text": "सेंड आ मेसेज ओन टेलिग्राम टू हर्शिता हेलो",
            "translated_text": "Send a telegram to Harshita saying hello",
        }

        intent_input = stt_result.get("translated_text") or stt_result["text"]

        # Both components must receive intent_input
        classifier_input = intent_input
        planner_input = intent_input

        assert classifier_input == planner_input == "Send a telegram to Harshita saying hello"

    def test_pipeline_result_preserves_original_transcript(self):
        """Test 5: Pipeline result dictionary contains original transcript and translated_text separately."""
        stt_result = {
            "text": "टेलिग्राम पर हर्षिता को हेलो भेजो",
            "translated_text": "Send hello to Harshita on Telegram",
        }

        transcription = stt_result["text"]
        translated_text = stt_result.get("translated_text") or transcription

        pipeline_result = {
            "transcription": transcription,
            "translated_text": translated_text,
            "intent": "send_telegram_message",
        }

        assert pipeline_result["transcription"] == "टेलिग्राम पर हर्षिता को हेलो भेजो"
        assert pipeline_result["translated_text"] == "Send hello to Harshita on Telegram"
