"""
Unit Tests for Telegram Contact Search & Matching
===================================================

Tests 0 matches, 1 match, multiple matches, ranking rules (exact username > full name > first name > prefix > contains),
case-insensitivity, and contact without username.
"""

import pytest
from automation.telegram.models import TelegramContact
from automation.telegram.telegram_automation import TelegramService


@pytest.fixture
def sample_contacts():
    return [
        TelegramContact(id=1, name="Harshita Sharma", username="harshita_s", first_name="Harshita", last_name="Sharma"),
        TelegramContact(id=2, name="Harshita Gupta", username="harshita_g", first_name="Harshita", last_name="Gupta"),
        TelegramContact(id=3, name="Harshita", username="harshi04", first_name="Harshita"),
        TelegramContact(id=4, name="Rahul Verma", username="rahul_99", first_name="Rahul", last_name="Verma"),
        TelegramContact(id=5, name="Aman Kumar", username=None, first_name="Aman", last_name="Kumar"),
    ]


class TestTelegramContactMatching:
    """Tests contact normalization and match ranking."""

    def test_zero_matches(self, sample_contacts):
        matches = TelegramService._normalize_and_match("NonExistentUser", sample_contacts)
        assert len(matches) == 0

    def test_single_exact_username_match(self, sample_contacts):
        matches = TelegramService._normalize_and_match("rahul_99", sample_contacts)
        assert len(matches) == 1
        assert matches[0].id == 4
        assert matches[0].name == "Rahul Verma"

    def test_exact_username_case_insensitive(self, sample_contacts):
        matches = TelegramService._normalize_and_match("RAHUL_99", sample_contacts)
        assert len(matches) == 1
        assert matches[0].id == 4

    def test_multiple_matches(self, sample_contacts):
        matches = TelegramService._normalize_and_match("Harshita", sample_contacts)
        assert len(matches) == 3
        # Exact first name / full name "Harshita" should be ranked higher or equal
        names = [c.name for c in matches]
        assert "Harshita Sharma" in names
        assert "Harshita Gupta" in names
        assert "Harshita" in names

    def test_exact_username_preferred_over_full_name(self, sample_contacts):
        # Add a contact whose full name is "rahul_99" but username is different
        extra = TelegramContact(id=9, name="rahul_99", username="other_user", first_name="rahul_99")
        all_contacts = sample_contacts + [extra]
        matches = TelegramService._normalize_and_match("rahul_99", all_contacts)
        # Priority 1 (username match) comes before Priority 2 (full name match)
        assert matches[0].username == "rahul_99"

    def test_contact_without_username(self, sample_contacts):
        matches = TelegramService._normalize_and_match("Aman", sample_contacts)
        assert len(matches) == 1
        assert matches[0].name == "Aman Kumar"
        assert matches[0].username is None

    def test_prefix_matching(self, sample_contacts):
        matches = TelegramService._normalize_and_match("Harsh", sample_contacts)
        assert len(matches) == 3
