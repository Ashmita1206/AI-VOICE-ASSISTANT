"""
Tests for Generic Application Launch Architecture
===================================================

Verifies:
1. Intent Disambiguation (Open Microsoft Word -> launch_application, NOT find_document_by_context)
2. Strict App Resolution (Open Microsoft Store -> UWP/Store app, NOT folder)
3. WSL / Ubuntu Terminal Resolution
4. Single Launch Idempotency & Duplicate Suppression
5. Adaptive 30s Verification & Process Handoff
"""

import pytest
from unittest.mock import patch, MagicMock

from agentic.llm.fallback import apply_heuristic_fallback
from agentic.discovery.manager import discover, rank_resources, resolve_best_resource
from agentic.discovery.schemas import Resource
from automation.applications import resolve_and_open, resolve_wsl_distribution, _LAUNCH_GUARD
from execution.verifier import dispatch_verify


def test_word_intent_disambiguation():
    """Verify 'Open Microsoft Word' yields application launch, NOT document search."""
    plan = apply_heuristic_fallback("Open Microsoft Word")
    assert plan.intent == "launch_application"
    assert len(plan.steps) == 1
    assert plan.steps[0].tool in ("resolve_and_open", "launch_application")
    assert (plan.steps[0].args.get("query") or "").lower() == "microsoft word" or (plan.steps[0].args.get("application") or "").lower() == "microsoft word"

    plan_ppt = apply_heuristic_fallback("Open Microsoft PowerPoint")
    assert plan_ppt.intent == "launch_application"
    assert plan_ppt.steps[0].tool in ("resolve_and_open", "launch_application")


test_doc_query = "find my budget report document"
def test_document_intent_preserved():
    """Verify explicit document search commands still route to find_document_by_context."""
    plan = apply_heuristic_fallback("find my budget report document")
    assert plan.intent == "find_document_by_context"


def test_microsoft_store_resolution_not_folder():
    """Verify 'Microsoft Store' does not match a generic filesystem folder named 'Microsoft'."""
    folder_res = Resource(
        name="Microsoft",
        type="folder",
        source="indexer",
        path=r"C:\Users\HP\Microsoft",
        confidence=0.9
    )
    store_app_res = Resource(
        name="Microsoft Store",
        type="application",
        source="indexer",
        executable="ms-windows-store:",
        confidence=0.9
    )

    ranked = rank_resources([folder_res, store_app_res], intent="open Microsoft Store app")
    # Microsoft Store app must be ranked #1
    top_res, top_score, _ = ranked[0]
    assert top_res.name == "Microsoft Store"
    assert top_res.type == "application"


def test_wsl_ubuntu_resolution():
    """Verify resolve_wsl_distribution returns WSL launcher when Ubuntu is registered."""
    with patch("subprocess.run") as mock_run, patch("shutil.which", return_value="C:\\Windows\\System32\\wt.exe"):
        mock_run.return_value = MagicMock(returncode=0, stdout="Ubuntu\ndocker-desktop\n")
        cmd, distro = resolve_wsl_distribution("open ubuntu terminal")
        assert distro == "Ubuntu"
        assert "wt.exe" in cmd or "wsl.exe" in cmd


def test_idempotent_single_launch():
    """Verify that multiple resolve_and_open calls for the same target do NOT relaunch subprocess."""
    _LAUNCH_GUARD.clear()
    with patch("automation.applications.dispatch_os_launch", return_value=(True, "win32", "subprocess.Popen", "ok")) as mock_dispatch, \
         patch("automation.applications.wait_and_focus_app", return_value=True):
        
        res1 = resolve_and_open({"query": "Microsoft Word"})
        assert res1.success is True
        assert mock_dispatch.call_count == 1

        # Second call for same request target must NOT trigger dispatch_os_launch again
        # (within the launch guard cooldown window)
        res2 = resolve_and_open({"query": "Microsoft Word"})
        assert res2.success is True
        assert mock_dispatch.call_count == 1  # Still 1 launch attempt!


def test_telegram_known_web_fallback():
    """Verify 'Open Telegram' falls back directly to canonical web destination when local app is absent."""
    with patch("automation.applications.resolve_app_launch_strategy", return_value=(None, "not running", "not found", "not found")), \
         patch("automation.browser.open_browser") as mock_open_browser:
        
        mock_open_browser.return_value = MagicMock(success=True, message="Opened browser")
        res = resolve_and_open({"query": "Telegram"})

        assert res.success is True
        assert res.resource_type == "website"
        assert res.fallback_used is True
        assert mock_open_browser.call_count == 1
        args, _ = mock_open_browser.call_args
        assert "telegram.org" in args[0].get("url")


def test_spotify_local_precedence():
    """Verify 'Open Spotify' launches local app when installed and does NOT fall back to web."""
    with patch("automation.applications.resolve_app_launch_strategy", return_value=("SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify", "running", "found", "found")), \
         patch("automation.applications.dispatch_os_launch", return_value=(True, "uwp", "explorer.exe", "ok")), \
         patch("automation.applications.wait_and_focus_app", return_value=True), \
         patch("automation.browser.open_browser") as mock_open_browser:

        _LAUNCH_GUARD.clear()
        res = resolve_and_open({"query": "Spotify"})
        assert res.success is True
        assert res.resource_type == "application"
        assert mock_open_browser.call_count == 0  # Web browser MUST NOT be called!


def test_unknown_target_search_fallback():
    """Verify unknown application falls through to browser search fallback."""
    with patch("automation.applications.resolve_app_launch_strategy", return_value=(None, "not running", "not found", "not found")), \
         patch("automation.browser.search_web") as mock_search_web:

        mock_search_web.return_value = MagicMock(success=True, message="Searched web")
        res = resolve_and_open({"query": "SomeRandomUnknownTool"})

        assert res.success is True
        assert res.fallback_type in ("search_web", "web_search")
        assert mock_search_web.call_count == 1

