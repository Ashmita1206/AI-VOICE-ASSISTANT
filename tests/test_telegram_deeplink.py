"""
Unit Tests for Telegram Deep Link Generation & URL Encoding
============================================================

Tests deep link construction and safe URL encoding for spaces, ?, &, #,
emojis, Hindi Unicode text, and newlines.
"""

import pytest
import urllib.parse
from automation.telegram.telegram_automation import TelegramService


class TestTelegramDeepLinkEncoding:
    """Tests for TelegramService.build_deep_link()."""

    def test_basic_username_and_message(self):
        url = TelegramService.build_deep_link("harshita123", "hello world")
        assert url == "https://t.me/harshita123?text=hello%20world"

    def test_special_characters_encoding(self):
        msg = "Ready? Yes & No #100 % discount"
        url = TelegramService.build_deep_link("user99", msg)
        assert "text=" in url
        parsed_qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert parsed_qs["text"][0] == msg

    def test_hindi_unicode_text_encoding(self):
        msg = "main 10 min me aa rha hu, kya aap tayar ho?"
        url = TelegramService.build_deep_link("harshita_s", msg)
        parsed_qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert parsed_qs["text"][0] == msg

    def test_emoji_encoding(self):
        msg = "Happy Birthday! 🎂🎉🥳"
        url = TelegramService.build_deep_link("rahul_v", msg)
        parsed_qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert parsed_qs["text"][0] == msg

    def test_newlines_encoding(self):
        msg = "Line 1\nLine 2\nLine 3"
        url = TelegramService.build_deep_link("test_user", msg)
        parsed_qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert parsed_qs["text"][0] == msg

    def test_empty_username_raises_value_error(self):
        with pytest.raises(ValueError, match="username is empty"):
            TelegramService.build_deep_link("", "hello")
