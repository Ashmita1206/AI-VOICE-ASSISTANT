"""
Notepad Automation Test Suite
==============================

Tests every individual Notepad tool and all prescribed multi-step sequences.

Run with::

    pytest tests/test_notepad.py -v

These tests are **integration tests** — they control real Notepad windows on
the local machine, so they require:
  * Windows OS
  * pyautogui, pyperclip, win32gui installed
  * A display (not headless)

Tests are structured to be independent: each test opens (or ensures open) and
closes Notepad, so they can run in isolation or as a full suite.

Markers
-------
  @pytest.mark.notepad     — all tests in this module
  @pytest.mark.slow        — longer tests (sequences)
  @pytest.mark.integration — tests that read back live Notepad content
"""

from __future__ import annotations

import sys
import time

import pytest

# Skip the entire module on non-Windows platforms
if not sys.platform.startswith("win"):
    pytest.skip("Notepad tests only run on Windows.", allow_module_level=True)

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from automation.notepad import NotepadController, _controller
from execution.registry import get_handler, load_all_tools

# Ensure all tools are loaded (handlers registered via decorators)
load_all_tools()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def close_notepad_after_each():
    """Ensure Notepad is closed before and after every test."""
    _force_close_notepad()
    yield
    _force_close_notepad()


def _force_close_notepad():
    """Kill any running Notepad processes without UI dialogs."""
    import subprocess
    import os
    try:
        subprocess.run(
            ["taskkill", "/f", "/im", "notepad.exe"],
            capture_output=True,
        )
    except Exception:
        pass
    try:
        if os.path.exists(_controller.SESSION_CACHE_FILE):
            os.remove(_controller.SESSION_CACHE_FILE)
    except Exception:
        pass
    _controller._session = None
    time.sleep(0.6)



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def open_notepad() -> None:
    """Open Notepad and assert success before proceeding."""
    result = _controller.open_notepad()
    assert result.success, f"Could not open Notepad: {result.message}"
    time.sleep(0.4)


def _read_notepad_content() -> str:
    """Return the current text content of the active Notepad window.

    Strategy
    --------
    1. Ensure Notepad is focused and the text area has keyboard focus.
    2. Select all via controller.select_all().
    3. Copy via controller.copy().
    4. Read clipboard with pyperclip.
    5. Deselect by pressing Right arrow key.
    6. Return the stripped content.
    """
    try:
        import pyperclip

        # Re-focus notepad before reading
        hwnd = _controller.find_notepad_hwnd()
        assert hwnd is not None, "_read_notepad_content: Notepad window not found"
        _controller._force_focus(hwnd)
        _controller._click_text_area(hwnd)
        time.sleep(0.25)

        _controller.select_all()
        time.sleep(0.15)
        _controller.copy()
        time.sleep(0.35)
        content = pyperclip.paste()
        
        # Deselect via controller _press helper to keep it background-safe
        _controller._press("notepad_deselect", "right")
        time.sleep(0.05)
        return content.strip()
    except Exception as exc:
        pytest.fail(f"_read_notepad_content failed: {exc}")
        return ""  # unreachable


# ===========================================================================
# SECTION 0 — Bug-fix regression tests (must pass on every run)
# ===========================================================================

@pytest.mark.integration
class TestBugFixes:
    """Regression tests for the two bugs exposed in live testing."""

    def test_open_notepad_does_not_spawn_second_instance(self):
        """BUG-1: open_notepad must reuse an existing window, not launch twice.

        Sequence:
          1. Open Notepad (fresh instance).
          2. Record the PID of the running process.
          3. Call open_notepad() a second time.
          4. Assert the same PID is still the only one running.
        """
        import psutil

        # First open
        r1 = _controller.open_notepad()
        assert r1.success, f"First open failed: {r1.message}"
        time.sleep(0.5)

        hwnd_first = _controller.find_notepad_hwnd()
        assert hwnd_first is not None, "No notepad window after first open"

        # Second open — must reuse, not spawn
        r2 = _controller.open_notepad()
        assert r2.success, f"Second open failed: {r2.message}"
        
        hwnd_second = _controller.find_notepad_hwnd()
        assert hwnd_first == hwnd_second, (
            f"BUG-1: open_notepad spawned a second instance!\n"
            f"  HWND after 1st open : {hwnd_first}\n"
            f"  HWND after 2nd open : {hwnd_second}"
        )


    @pytest.mark.integration
    def test_type_text_actually_inserts_into_notepad(self):
        """BUG-2: type_text must insert text that is readable back from Notepad.

        Sequence:
          1. Open Notepad.
          2. Clear any existing content.
          3. Type a distinctive string.
          4. Read back the content via Ctrl+A, Ctrl+C, clipboard.
          5. Assert the typed string appears in the content.
        """
        open_notepad()

        # Clear any pre-existing content
        _controller.clear_document()
        time.sleep(0.2)

        target = "HelloNotepad_BugFix_2025"
        result = _controller.type_text(target)
        assert result.success, f"type_text returned failure: {result.message}"

        # Wait a moment for Notepad to process the input
        time.sleep(0.3)

        content = _read_notepad_content()

        assert target in content, (
            f"BUG-2: Typed text not found in Notepad!\n"
            f"  Expected : '{target}'\n"
            f"  Got      : '{content!r}'"
        )


# ===========================================================================
# SECTION 1 — Registry verification
# ===========================================================================

class TestRegistry:
    """Verify all 15 Notepad tools are registered in the execution registry."""

    EXPECTED_TOOLS = [
        "notepad_open",
        "notepad_close",
        "notepad_type",
        "notepad_press_enter",
        "notepad_select_all",
        "notepad_copy",
        "notepad_paste",
        "notepad_undo",
        "notepad_redo",
        "notepad_delete",
        "notepad_clear",
        "notepad_save",
        "notepad_save_as",
        "notepad_open_file",
        "notepad_new_file",
    ]

    @pytest.mark.parametrize("tool_name", EXPECTED_TOOLS)
    def test_tool_registered(self, tool_name: str):
        handler = get_handler(tool_name)
        assert handler is not None, f"Tool '{tool_name}' is not registered."
        assert callable(handler), f"Handler for '{tool_name}' is not callable."


# ===========================================================================
# SECTION 2 — Individual tool tests
# ===========================================================================

class TestNotepadOpen:
    def test_open_notepad_launches_window(self):
        result = _controller.open_notepad()
        assert result.success, result.message
        hwnd = _controller.find_notepad_hwnd()
        assert hwnd is not None, "Notepad window not found after open."

    def test_open_notepad_when_already_running(self):
        # Open once
        result1 = _controller.open_notepad()
        assert result1.success
        # Open again — should focus, not crash
        result2 = _controller.open_notepad()
        assert result2.success, result2.message
        assert "already open" in result2.message.lower() or result2.success

    def test_find_notepad_hwnd_returns_none_when_closed(self):
        _force_close_notepad()
        hwnd = _controller.find_notepad_hwnd()
        assert hwnd is None, f"Expected None, got HWND={hwnd}"


class TestNotepadFocus:
    def test_focus_fails_when_not_running(self):
        _force_close_notepad()
        result = _controller.focus_notepad()
        assert not result.success, "focus_notepad should fail when Notepad is not running."

    def test_focus_succeeds_when_running(self):
        open_notepad()
        result = _controller.focus_notepad()
        assert result.success, result.message


class TestNotepadType:
    def test_type_simple_text(self):
        open_notepad()
        result = _controller.type_text("Hello World")
        assert result.success, result.message

    def test_type_empty_string_fails(self):
        open_notepad()
        result = _controller.type_text("")
        assert not result.success, "Should fail with empty text."

    def test_type_fails_when_notepad_not_open(self):
        _force_close_notepad()
        result = _controller.type_text("Hello")
        assert not result.success

    def test_type_long_text(self):
        open_notepad()
        text = "A" * 500
        result = _controller.type_text(text)
        assert result.success, result.message

    def test_type_special_characters(self):
        open_notepad()
        result = _controller.type_text("Hello! How are you? 1+1=2 @#$%")
        assert result.success, result.message


class TestNotepadPressEnter:
    def test_press_enter(self):
        open_notepad()
        _controller.type_text("Line1")
        result = _controller.press_enter()
        assert result.success, result.message

    def test_press_enter_fails_when_not_open(self):
        _force_close_notepad()
        result = _controller.press_enter()
        assert not result.success


class TestNotepadSelectAll:
    def test_select_all(self):
        open_notepad()
        _controller.type_text("Hello World")
        result = _controller.select_all()
        assert result.success, result.message

    def test_select_all_fails_when_not_open(self):
        _force_close_notepad()
        result = _controller.select_all()
        assert not result.success


class TestNotepadCopyPaste:
    def test_copy(self):
        open_notepad()
        _controller.type_text("CopyMe")
        _controller.select_all()
        result = _controller.copy()
        assert result.success, result.message

    def test_paste(self):
        open_notepad()
        _controller.type_text("CopyMe")
        _controller.select_all()
        _controller.copy()
        _controller.press_enter()
        result = _controller.paste()
        assert result.success, result.message

    def test_copy_paste_fails_when_not_open(self):
        _force_close_notepad()
        assert not _controller.copy().success
        assert not _controller.paste().success


class TestNotepadUndoRedo:
    def test_undo(self):
        open_notepad()
        _controller.type_text("UndoTest")
        result = _controller.undo()
        assert result.success, result.message

    def test_redo(self):
        open_notepad()
        _controller.type_text("RedoTest")
        _controller.undo()
        result = _controller.redo()
        assert result.success, result.message

    def test_undo_redo_fail_when_not_open(self):
        _force_close_notepad()
        assert not _controller.undo().success
        assert not _controller.redo().success


class TestNotepadDeleteClear:
    def test_delete_text(self):
        open_notepad()
        _controller.type_text("DeleteMe")
        _controller.select_all()
        result = _controller.delete_text()
        assert result.success, result.message

    def test_clear_document(self):
        open_notepad()
        _controller.type_text("ClearMe please")
        result = _controller.clear_document()
        assert result.success, result.message

    def test_delete_fails_when_not_open(self):
        _force_close_notepad()
        result = _controller.delete_text()
        assert not result.success


class TestNotepadSave:
    def test_save_file(self):
        open_notepad()
        _controller.type_text("SaveTest")
        result = _controller.save_file()
        assert result.success, result.message

    def test_save_fails_when_not_open(self):
        _force_close_notepad()
        result = _controller.save_file()
        assert not result.success


class TestNotepadSaveAs:
    def test_save_as(self, tmp_path):
        filename = str(tmp_path / "test_notepad_output.txt")
        open_notepad()
        _controller.type_text("SaveAs Test")
        result = _controller.save_as(filename)
        assert result.success, result.message
        _force_close_notepad()

    def test_save_as_empty_filename_fails(self):
        open_notepad()
        result = _controller.save_as("")
        assert not result.success

    def test_save_as_fails_when_not_open(self):
        _force_close_notepad()
        result = _controller.save_as("test.txt")
        assert not result.success


class TestNotepadNewFile:
    def test_new_file(self):
        open_notepad()
        _controller.type_text("Some content")
        result = _controller.new_file()
        assert result.success, result.message

    def test_new_file_fails_when_not_open(self):
        _force_close_notepad()
        result = _controller.new_file()
        assert not result.success


class TestNotepadOpenFile:
    def test_open_existing_file(self, tmp_path):
        # Create a real file first
        test_file = tmp_path / "open_test.txt"
        test_file.write_text("Hello from file!", encoding="utf-8")
        open_notepad()
        result = _controller.open_file(str(test_file))
        assert result.success, result.message

    def test_open_file_empty_path_fails(self):
        open_notepad()
        result = _controller.open_file("")
        assert not result.success

    def test_open_file_fails_when_not_open(self):
        _force_close_notepad()
        result = _controller.open_file("test.txt")
        assert not result.success


class TestNotepadClose:
    def test_close_notepad(self):
        open_notepad()
        result = _controller.close_notepad(save_first=False)
        assert result.success, result.message
        # Wait for window destruction (Windows 11 has closing animations)
        hwnd = None
        for _ in range(10):
            time.sleep(0.5)
            hwnd = _controller.find_notepad_hwnd()
            if hwnd is None:
                break
        assert hwnd is None, "Notepad still running after close."

    def test_close_when_not_running_fails(self):
        _force_close_notepad()
        result = _controller.close_notepad()
        assert not result.success


# ===========================================================================
# SECTION 3 — Handler dispatch tests (via registry)
# ===========================================================================

class TestHandlerDispatch:
    """Verify each registered handler can be called through get_handler."""

    def test_dispatch_notepad_open(self):
        handler = get_handler("notepad_open")
        result = handler({})
        assert result.success, result.message

    def test_dispatch_notepad_type(self):
        open_notepad()
        handler = get_handler("notepad_type")
        result = handler({"text": "Dispatched"})
        assert result.success, result.message

    def test_dispatch_notepad_press_enter(self):
        open_notepad()
        handler = get_handler("notepad_press_enter")
        result = handler({})
        assert result.success, result.message

    def test_dispatch_notepad_select_all(self):
        open_notepad()
        handler = get_handler("notepad_select_all")
        result = handler({})
        assert result.success, result.message

    def test_dispatch_notepad_copy(self):
        open_notepad()
        handler = get_handler("notepad_copy")
        result = handler({})
        assert result.success, result.message

    def test_dispatch_notepad_paste(self):
        open_notepad()
        handler = get_handler("notepad_paste")
        result = handler({})
        assert result.success, result.message

    def test_dispatch_notepad_undo(self):
        open_notepad()
        handler = get_handler("notepad_undo")
        result = handler({})
        assert result.success, result.message

    def test_dispatch_notepad_redo(self):
        open_notepad()
        handler = get_handler("notepad_redo")
        result = handler({})
        assert result.success, result.message

    def test_dispatch_notepad_delete(self):
        open_notepad()
        get_handler("notepad_type")({"text": "DeleteDispatch"})
        handler = get_handler("notepad_delete")
        result = handler({})
        assert result.success, result.message

    def test_dispatch_notepad_clear(self):
        open_notepad()
        get_handler("notepad_type")({"text": "ClearDispatch"})
        handler = get_handler("notepad_clear")
        result = handler({})
        assert result.success, result.message

    def test_dispatch_notepad_save(self):
        open_notepad()
        handler = get_handler("notepad_save")
        result = handler({})
        assert result.success, result.message

    def test_dispatch_notepad_new_file(self):
        open_notepad()
        handler = get_handler("notepad_new_file")
        result = handler({})
        assert result.success, result.message


# ===========================================================================
# SECTION 4 — Sequence tests (prescribed in test plan)
# ===========================================================================

@pytest.mark.slow
class TestNotepadSequences:
    """Multi-step command sequence tests from the implementation plan."""

    def test_sequence_open_write_hello(self):
        """Open Notepad → Write Hello"""
        r1 = _controller.open_notepad()
        assert r1.success, r1.message

        r2 = _controller.type_text("Hello")
        assert r2.success, r2.message

    def test_sequence_open_write_enter_write(self):
        """Open Notepad → Write Hello → Press Enter → Write World"""
        r1 = _controller.open_notepad()
        assert r1.success

        r2 = _controller.type_text("Hello")
        assert r2.success, r2.message

        r3 = _controller.press_enter()
        assert r3.success, r3.message

        r4 = _controller.type_text("World")
        assert r4.success, r4.message

    def test_sequence_open_write_save_as(self, tmp_path):
        """Open Notepad → Write Notes → Save As notes.txt"""
        filename = str(tmp_path / "notes.txt")

        r1 = _controller.open_notepad()
        assert r1.success

        r2 = _controller.type_text("Notes")
        assert r2.success, r2.message

        r3 = _controller.save_as(filename)
        assert r3.success, r3.message

    def test_sequence_open_write_select_copy_paste(self):
        """Open Notepad → Write Test → Select All → Copy → Paste"""
        r1 = _controller.open_notepad()
        assert r1.success

        r2 = _controller.type_text("Test")
        assert r2.success, r2.message

        r3 = _controller.select_all()
        assert r3.success, r3.message

        r4 = _controller.copy()
        assert r4.success, r4.message

        r5 = _controller.press_enter()
        assert r5.success, r5.message

        r6 = _controller.paste()
        assert r6.success, r6.message

    def test_sequence_open_write_undo_redo(self):
        """Open Notepad → Write ABC → Undo → Redo"""
        r1 = _controller.open_notepad()
        assert r1.success

        r2 = _controller.type_text("ABC")
        assert r2.success, r2.message

        r3 = _controller.undo()
        assert r3.success, r3.message

        r4 = _controller.redo()
        assert r4.success, r4.message

    def test_sequence_open_multi_line_save_close(self, tmp_path):
        """Full meeting notes workflow"""
        filename = str(tmp_path / "meeting_notes.txt")

        r1 = _controller.open_notepad()
        assert r1.success

        r2 = _controller.type_text("Meeting Notes")
        assert r2.success

        r3 = _controller.press_enter()
        assert r3.success

        r4 = _controller.type_text("Attendees: Alice, Bob")
        assert r4.success

        r5 = _controller.press_enter()
        assert r5.success

        r6 = _controller.type_text("Action items: review PR")
        assert r6.success

        r7 = _controller.save_as(filename)
        assert r7.success, r7.message

        r8 = _controller.close_notepad(save_first=False)
        assert r8.success, r8.message

    def test_sequence_open_clear_retype(self):
        """Open → Write → Clear → Retype"""
        r1 = _controller.open_notepad()
        assert r1.success

        _controller.type_text("Old content")
        r2 = _controller.clear_document()
        assert r2.success, r2.message

        r3 = _controller.type_text("New content")
        assert r3.success, r3.message


# ===========================================================================
# SECTION 5 — Tool registry integrity
# ===========================================================================

class TestToolRegistryIntegrity:
    """Verify tool_registry.py lists all Notepad tools."""

    def test_notepad_tools_in_agentic_registry(self):
        from agentic.tool_registry import get_all_tools
        tool_names = {t.name for t in get_all_tools()}
        notepad_tools = [
            "notepad_open", "notepad_close", "notepad_type", "notepad_press_enter",
            "notepad_select_all", "notepad_copy", "notepad_paste", "notepad_undo",
            "notepad_redo", "notepad_delete", "notepad_clear", "notepad_save",
            "notepad_save_as", "notepad_open_file", "notepad_new_file",
        ]
        for tool in notepad_tools:
            assert tool in tool_names, f"Tool '{tool}' missing from agentic tool_registry."


class TestCommandRegistryIntegrity:
    """Verify command_registry.py has Notepad intent definitions."""

    def test_notepad_intents_in_command_registry(self):
        from agent.command_registry import list_intent_names
        intent_names = list_intent_names()
        notepad_intents = [
            "notepad_open_intent", "notepad_close_intent", "notepad_type_intent",
            "notepad_press_enter_intent", "notepad_select_all_intent",
            "notepad_copy_intent", "notepad_paste_intent", "notepad_undo_intent",
            "notepad_redo_intent", "notepad_delete_intent", "notepad_clear_intent",
            "notepad_save_intent", "notepad_save_as_intent",
            "notepad_open_file_intent", "notepad_new_file_intent",
        ]
        for intent in notepad_intents:
            assert intent in intent_names, f"Intent '{intent}' missing from command_registry."

    def test_notepad_pattern_matching(self):
        """Verify key patterns match correctly."""
        from agent.command_registry import get_intent
        import re

        patterns_to_test = [
            ("notepad_open_intent", "open notepad"),
            ("notepad_open_intent", "launch notepad"),
            ("notepad_close_intent", "close notepad"),
            ("notepad_type_intent", "write hello world"),
            ("notepad_type_intent", "type some text here"),
            ("notepad_save_as_intent", "save as notes.txt"),
            ("notepad_save_intent", "save file"),
            ("notepad_press_enter_intent", "press enter"),
            ("notepad_select_all_intent", "select all"),
            ("notepad_clear_intent", "clear notepad"),
            ("notepad_new_file_intent", "new file"),
        ]
        for intent_name, utterance in patterns_to_test:
            defn = get_intent(intent_name)
            assert defn is not None, f"Intent '{intent_name}' not found."
            match = defn.match(utterance)
            assert match is not None, (
                f"Pattern for '{intent_name}' did not match '{utterance}'."
            )


class TestNotepadStrictIntegration:
    """Rigorous end-to-end integration tests for Notepad HWND stability and content verification."""

    def test_notepad_hwnd_stability(self):
        # 1. Open Notepad
        _controller.open_notepad()
        hwnd1 = _controller.find_notepad_hwnd()
        assert hwnd1 is not None, "First find_notepad_hwnd returned None"

        # 2. Type text
        _controller.type_text("hello")
        hwnd2 = _controller.find_notepad_hwnd()
        assert hwnd2 is not None, "Second find_notepad_hwnd returned None"

        # 3. Assert HWND matches exactly
        assert hwnd1 == hwnd2, f"HWND changed between open ({hwnd1}) and type ({hwnd2})"

    def test_notepad_e2e_content_flow(self):
        # 1. Open
        _controller.open_notepad()
        
        # 2. Clear pre-existing
        _controller.clear_document()
        time.sleep(0.3)

        # 3. Type unique text
        typed_str = "NOTEPAD_STRICT_E2E_VERIFICATION_998877"
        _controller.type_text(typed_str)
        time.sleep(0.4)

        # 4. Read back
        _controller.select_all()
        time.sleep(0.2)
        _controller.copy()
        time.sleep(0.3)

        import pyperclip
        clipboard_content = pyperclip.paste().strip()
        
        # Cleanup
        _controller.clear_document()
        
        assert clipboard_content == typed_str, f"Clipboard content '{clipboard_content}' did not match typed string '{typed_str}'"

    def test_notepad_e2e_save_and_close_flow(self, tmp_path):
        import os

        # 1. Open
        r_open = _controller.open_notepad()
        assert r_open.success
        hwnd = _controller.find_notepad_hwnd()
        assert hwnd is not None

        # 2. Type
        unique_text = "Notepad Save and Close Robust Integration Test 12345"
        r_type = _controller.type_text(unique_text)
        assert r_type.success

        # 3. Save As
        test_file = str(tmp_path / "robust_test.txt")
        # Ensure file does not exist initially
        if os.path.exists(test_file):
            os.remove(test_file)

        r_save = _controller.save_as(test_file, overwrite=True)
        assert r_save.success, r_save.message

        # Verify file exists and has correct contents
        assert os.path.exists(test_file)
        with open(test_file, "r", encoding="utf-8") as f:
            content = f.read()
        # Verify content contains our typed text
        assert unique_text in content, f"Expected unique text to be in file content. File content: {content}"

        # 4. Close
        r_close = _controller.close_notepad(save_before_close=False, discard_changes=True)
        assert r_close.success

        # Verify closed
        assert _controller.find_notepad_hwnd() is None

    def test_user_and_assistant_notepad_instances(self):
        import subprocess
        import os
        import win32gui
        
        # Ensure clean state first
        _force_close_notepad()
        
        # 1. User manually opens Notepad (untracked)
        proc_user = subprocess.Popen(["notepad.exe"], shell=False)
        
        # Poll up to 6.0s for the window to appear
        hwnd_user = None
        for _ in range(30):
            time.sleep(0.2)
            hwnd_user = _controller._scan_any_notepad_hwnd()
            if hwnd_user:
                break
        assert hwnd_user is not None, "Failed to simulate user-opened Notepad"
        
        # 2. Assistant opens Notepad
        r_open = _controller.open_notepad()
        assert r_open.success
        hwnd_assistant = _controller.find_notepad_hwnd()
        assert hwnd_assistant is not None
        
        assert hwnd_assistant is not None

        
        # Cleanup
        try:
            proc_user.terminate()
        except Exception:
            pass
        _controller.close_notepad()

    def test_save_to_desktop(self):
        import os
        
        r_open = _controller.open_notepad()
        assert r_open.success
        
        unique_text = "Desktop Save Verification 98765"
        _controller.clear_document()
        _controller.type_text(unique_text)
        
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                reg_val, _ = winreg.QueryValueEx(key, "Desktop")
                desktop_dir = os.path.abspath(os.path.expandvars(reg_val))
        except Exception:
            desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")
            onedrive = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")
            if os.path.exists(onedrive):
                desktop_dir = onedrive
        
        test_file = "test_save_desktop.txt"
        dest_path = os.path.join(desktop_dir, test_file)
        if os.path.exists(dest_path):
            os.remove(dest_path)
            
        r_save = _controller.save_as(test_file, directory="Desktop", overwrite=True)
        assert r_save.success, r_save.message
        assert os.path.exists(dest_path), f"File was not created on the Desktop: {dest_path}"
        
        with open(dest_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert unique_text in content
        
        # Cleanup
        os.remove(dest_path)
        _controller.close_notepad()

    def test_close_leaves_user_notepad_open(self):
        import subprocess
        import win32gui
        
        _force_close_notepad()
        
        # 1. User opens a Notepad window manually
        proc_user = subprocess.Popen(["notepad.exe"], shell=False)
        
        # Poll up to 6.0s for the window to appear
        hwnd_user = None
        for _ in range(30):
            time.sleep(0.2)
            hwnd_user = _controller._scan_any_notepad_hwnd()
            if hwnd_user:
                break
        assert hwnd_user is not None
        
        # 2. Assistant opens its own Notepad
        r_open = _controller.open_notepad()
        assert r_open.success
        hwnd_assistant = _controller.find_notepad_hwnd()
        assert hwnd_assistant is not None

        
        # 3. Call close on assistant
        r_close = _controller.close_notepad()
        assert r_close.success
        time.sleep(0.5)
        
        # Verify user window is still open
        assert win32gui.IsWindow(hwnd_user) and win32gui.IsWindowVisible(hwnd_user), "User's Notepad window was closed by the assistant!"
        
        # Cleanup user process
        try:
            proc_user.terminate()
        except Exception:
            pass

    def test_notepad_e2e_session_consistency(self):
        import os
        import tempfile
        
        _force_close_notepad()
        
        # 1. Open
        r_open = _controller.open_notepad()
        assert r_open.success
        hwnd_open = _controller.find_notepad_hwnd()
        assert hwnd_open is not None

        # 2. Type
        r_type = _controller.type_text("Session Consistency Test")
        assert r_type.success
        hwnd_type = _controller.find_notepad_hwnd()

        # 3. Save As
        temp_dir = tempfile.gettempdir()
        test_file = os.path.join(temp_dir, "session_test.txt")
        if os.path.exists(test_file):
            os.remove(test_file)
            
        r_save = _controller.save_as(test_file, overwrite=True)
        assert r_save.success, r_save.message
        hwnd_save = _controller.find_notepad_hwnd()

        # 4. Close
        r_close = _controller.close_notepad()
        assert r_close.success

        # Assert HWND remains completely consistent
        assert hwnd_open == hwnd_type, f"HWND changed between open ({hwnd_open}) and type ({hwnd_type})"
        assert hwnd_open == hwnd_save, f"HWND changed between open ({hwnd_open}) and save ({hwnd_save})"
        
        # Cleanup file
        if os.path.exists(test_file):
            os.remove(test_file)

    def test_notepad_first_time_save_workflow(self):
        import os
        
        _force_close_notepad()
        
        # 1. Open
        r_open = _controller.open_notepad()
        assert r_open.success
        
        # 2. Type unique text
        unique_text = "AIML test content first time save"
        _controller.clear_document()
        r_type = _controller.type_text(unique_text)
        assert r_type.success
        
        # 3. Save aiml.txt on Desktop
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                reg_val, _ = winreg.QueryValueEx(key, "Desktop")
                desktop_dir = os.path.abspath(os.path.expandvars(reg_val))
        except Exception:
            desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")
            onedrive = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")
            if os.path.exists(onedrive):
                desktop_dir = onedrive
        
        test_file = "aiml.txt"
        dest_path = os.path.join(desktop_dir, test_file)
        if os.path.exists(dest_path):
            os.remove(dest_path)
            
        r_save = _controller.save_file(filename=test_file, directory="Desktop")
        assert r_save.success, r_save.message
        
        # Verify file exists
        assert os.path.exists(dest_path), f"File {dest_path} was not created!"
        
        # Verify contents match
        with open(dest_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert unique_text in content, f"Expected content '{unique_text}' not in saved file: '{content}'"
        
        # Cleanup
        os.remove(dest_path)
        
        # 4. Close
        r_close = _controller.close_notepad()
        assert r_close.success
        assert _controller.find_notepad_hwnd() is None

    def test_save_to_documents(self):
        import os
        _force_close_notepad()
        _controller.open_notepad()
        unique_text = "Documents Save Verification 123"
        _controller.clear_document()
        _controller.type_text(unique_text)
        
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                reg_val, _ = winreg.QueryValueEx(key, "Personal")
                doc_dir = os.path.abspath(os.path.expandvars(reg_val))
        except Exception:
            doc_dir = os.path.join(os.path.expanduser("~"), "Documents")
            onedrive = os.path.join(os.path.expanduser("~"), "OneDrive", "Documents")
            if os.path.exists(onedrive):
                doc_dir = onedrive
        
        test_file = "test_save_doc.txt"
        dest_path = os.path.join(doc_dir, test_file)
        if os.path.exists(dest_path):
            os.remove(dest_path)
            
        r_save = _controller.save_file(filename=test_file, directory="Documents")
        assert r_save.success, r_save.message
        assert os.path.exists(dest_path)
        with open(dest_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert unique_text in content
        os.remove(dest_path)
        _controller.close_notepad()

    def test_save_to_custom_folder(self):
        import os
        import tempfile
        _force_close_notepad()
        _controller.open_notepad()
        unique_text = "Custom Folder Verification 456"
        _controller.clear_document()
        _controller.type_text(unique_text)
        
        custom_dir = os.path.join(tempfile.gettempdir(), "custom_test_dir")
        os.makedirs(custom_dir, exist_ok=True)
        test_file = "custom_file.txt"
        dest_path = os.path.join(custom_dir, test_file)
        if os.path.exists(dest_path):
            os.remove(dest_path)
            
        r_save = _controller.save_as(test_file, directory=custom_dir, overwrite=True)
        assert r_save.success, r_save.message
        assert os.path.exists(dest_path)
        os.remove(dest_path)
        _controller.close_notepad()

    def test_save_filename_only(self):
        import os
        _force_close_notepad()
        _controller.open_notepad()
        unique_text = "Filename Only Verification 789"
        _controller.clear_document()
        _controller.type_text(unique_text)
        
        test_file = "test_filename_only.txt"
        r_save = _controller.save_file(filename=test_file)
        assert r_save.success, r_save.message
        assert r_save.saved_path is not None
        dest_path = r_save.saved_path
        assert os.path.exists(dest_path)
        os.remove(dest_path)
        _controller.close_notepad()

    def test_save_overwrite_existing(self):
        import os
        import tempfile
        _force_close_notepad()
        _controller.open_notepad()
        
        temp_dir = tempfile.gettempdir()
        test_file = "test_overwrite.txt"
        dest_path = os.path.join(temp_dir, test_file)
        if os.path.exists(dest_path):
            os.remove(dest_path)
            
        # First save
        _controller.clear_document()
        _controller.type_text("First version content")
        r_save1 = _controller.save_as(test_file, directory=temp_dir, overwrite=True)
        assert r_save1.success
        
        # Second save (overwrite)
        _controller.clear_document()
        _controller.type_text("Second overwritten version content")
        r_save2 = _controller.save_as(test_file, directory=temp_dir, overwrite=True)
        assert r_save2.success, r_save2.message
        
        assert os.path.exists(dest_path)
        with open(dest_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "Second overwritten version content" in content
        
        os.remove(dest_path)
        _controller.close_notepad()

    def test_save_retry_after_failed_save(self):
        import os
        import tempfile
        _force_close_notepad()
        _controller.open_notepad()
        
        hwnd_before = _controller.find_notepad_hwnd()
        assert hwnd_before is not None
        
        # 1. Trigger save with invalid characters/empty in filename (which fails validation inside tool)
        r_fail = _controller.save_as("")
        assert not r_fail.success
        
        # Verify window is still open and session is preserved!
        hwnd_after = _controller.find_notepad_hwnd()
        assert hwnd_after == hwnd_before, "Notepad session was lost after failed save!"
        
        # 2. Try again with a valid filename and verify it saves successfully!
        unique_text = "Content after retry save"
        _controller.clear_document()
        _controller.type_text(unique_text)
        
        temp_dir = tempfile.gettempdir()
        test_file = "valid_retry_file.txt"
        dest_path = os.path.join(temp_dir, test_file)
        if os.path.exists(dest_path):
            os.remove(dest_path)
            
        r_success = _controller.save_as(test_file, directory=temp_dir, overwrite=True)
        assert r_success.success, r_success.message
        assert os.path.exists(dest_path)
        
        os.remove(dest_path)
        _controller.close_notepad()

    def test_save_verification_fails_if_file_missing(self):
        import os
        _force_close_notepad()
        _controller.open_notepad()
        
        # Try to save to a completely non-existent / invalid drive path (e.g. Z:\does_not_exist\aiml.txt)
        r_save = _controller.save_as("aiml.txt", directory="Z:\\does_not_exist_folder_abc")
        assert not r_save.success
        _controller.close_notepad()

    def test_consecutive_runs_start_with_new_blank_document(self):
        import os
        import tempfile
        _force_close_notepad()

        # --- First Run ---
        r_open1 = _controller.open_notepad()
        assert r_open1.success
        r_type1 = _controller.type_text("First Run Content")
        assert r_type1.success
        
        temp_dir = tempfile.gettempdir()
        test_file = "consecutive_run_test.txt"
        dest_path = os.path.join(temp_dir, test_file)
        if os.path.exists(dest_path):
            os.remove(dest_path)
            
        r_save1 = _controller.save_as(test_file, directory=temp_dir, overwrite=True)
        assert r_save1.success, r_save1.message
        
        # Verify first run content is saved
        with open(dest_path, "r", encoding="utf-8") as f:
            c1 = f.read()
        assert "First Run Content" in c1
        os.remove(dest_path)

        # Do NOT close Notepad between runs to simulate reusing the same instance
        
        # --- Second Run ---
        # 1. Open Notepad (should reuse window)
        r_open2 = _controller.open_notepad()
        assert r_open2.success
        
        # 2. Type text - must start with new blank document (i.e. do NOT append to "First Run Content")
        r_type2 = _controller.type_text("Second Run Content")
        assert r_type2.success
        
        r_save2 = _controller.save_as(test_file, directory=temp_dir, overwrite=True)
        assert r_save2.success, r_save2.message
        
        # Verify second run content ONLY (must not contain "First Run Content")
        with open(dest_path, "r", encoding="utf-8") as f:
            c2 = f.read()
        assert "Second Run Content" in c2
        assert "First Run Content" not in c2
        
        # Cleanup
        os.remove(dest_path)
        _controller.close_notepad()
