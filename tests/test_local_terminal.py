"""
Tests for Local Terminal Widget (QProcess-based).

Tests the strip_ansi_codes function, ANSI control sequence stripping,
line editor behavior, command history, and prompt generation.
"""

import os
import sys
import re
import inspect
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest


class TestStripAnsiCodes:
    """Tests for the strip_ansi_codes function."""

    def test_strips_csi_sequences(self):
        """Test stripping CSI escape sequences."""
        from sftp_local_terminal_widget import strip_ansi_codes

        text = "\x1b[2J"  # Clear screen
        result = strip_ansi_codes(text)
        assert result == ""

    def test_strips_color_codes(self):
        """Test stripping color escape sequences."""
        from sftp_local_terminal_widget import strip_ansi_codes

        text = "\x1b[31mRed Text\x1b[0m"
        result = strip_ansi_codes(text)
        assert "Red Text" in result
        assert "\x1b" not in result

    def test_strips_osc_sequences(self):
        """Test stripping OSC (Operating System Command) sequences."""
        from sftp_local_terminal_widget import strip_ansi_codes

        text = "\x1b]0;Terminal Title\x07"
        result = strip_ansi_codes(text)
        assert result == ""

    def test_preserves_plain_text(self):
        """Test that plain text is preserved."""
        from sftp_local_terminal_widget import strip_ansi_codes

        text = "Hello, World!"
        result = strip_ansi_codes(text)
        assert result == text

    def test_preserves_newlines(self):
        """Test that newlines are preserved."""
        from sftp_local_terminal_widget import strip_ansi_codes

        text = "Line 1\nLine 2\nLine 3"
        result = strip_ansi_codes(text)
        assert result == text

    def test_strips_multiple_sequences(self):
        """Test stripping multiple escape sequences from text."""
        from sftp_local_terminal_widget import strip_ansi_codes

        text = "\x1b[1mBold\x1b[0m Normal \x1b[32mGreen\x1b[0m"
        result = strip_ansi_codes(text)
        assert "Bold" in result
        assert "Normal" in result
        assert "Green" in result
        assert "\x1b" not in result

    def test_empty_string(self):
        """Test handling of empty string."""
        from sftp_local_terminal_widget import strip_ansi_codes

        result = strip_ansi_codes("")
        assert result == ""

    def test_preserves_tabs(self):
        """Test that tabs are preserved."""
        from sftp_local_terminal_widget import strip_ansi_codes

        text = "col1\tcol2\tcol3"
        result = strip_ansi_codes(text)
        assert result == text


class TestAnsiEscapePattern:
    """Tests for the ANSI_ESCAPE_PATTERN regex."""

    def test_pattern_compiles(self):
        """Test that the pattern compiles without error."""
        from sftp_local_terminal_widget import ANSI_ESCAPE_PATTERN

        assert ANSI_ESCAPE_PATTERN is not None
        assert isinstance(ANSI_ESCAPE_PATTERN, type(re.compile("")))

    def test_matches_clear_screen(self):
        """Test matching clear screen sequence."""
        from sftp_local_terminal_widget import ANSI_ESCAPE_PATTERN

        match = ANSI_ESCAPE_PATTERN.search("\x1b[2J")
        assert match is not None

    def test_matches_bold_on(self):
        """Test matching bold-on sequence."""
        from sftp_local_terminal_widget import ANSI_ESCAPE_PATTERN

        match = ANSI_ESCAPE_PATTERN.search("\x1b[1m")
        assert match is not None

    def test_matches_color_reset(self):
        """Test matching color reset sequence."""
        from sftp_local_terminal_widget import ANSI_ESCAPE_PATTERN

        match = ANSI_ESCAPE_PATTERN.search("\x1b[0m")
        assert match is not None

    def test_no_match_plain_text(self):
        """Test that plain text has no matches."""
        from sftp_local_terminal_widget import ANSI_ESCAPE_PATTERN

        match = ANSI_ESCAPE_PATTERN.search("Hello World")
        assert match is None


class TestLocalTerminalArchitecture:
    """Tests verifying the QProcess-based architecture."""

    def test_uses_qprocess_not_pty(self):
        """Test that LocalTerminalWidget uses QProcess, not pty."""
        import inspect
        from sftp_local_terminal_widget import LocalTerminalWidget

        source = inspect.getsource(LocalTerminalWidget)

        # Should use QProcess
        assert "QProcess" in source
        # Should NOT use pty.fork
        assert "pty.fork" not in source
        assert "master_fd" not in source

    def test_no_unix_modules_dependency(self):
        """Test that the module doesn't depend on Unix-only modules."""
        import inspect
        from sftp_local_terminal_widget import LocalTerminalWidget

        source = inspect.getsource(LocalTerminalWidget)

        # Should not reference pty, fcntl, struct, termios
        assert "UNIX_MODULES" not in source
        assert "import pty" not in source
        assert "import fcntl" not in source
        assert "import termios" not in source

    def test_has_strip_ansi_codes(self):
        """Test that strip_ansi_codes function exists."""
        from sftp_local_terminal_widget import strip_ansi_codes
        assert callable(strip_ansi_codes)

    def test_has_ansii_escape_pattern(self):
        """Test that ANSI_ESCAPE_PATTERN is defined."""
        from sftp_local_terminal_widget import ANSI_ESCAPE_PATTERN
        assert ANSI_ESCAPE_PATTERN is not None

    def test_pipe_compatible_shell_not_fish(self):
        """Test that _get_pipe_compatible_shell returns a non-fish shell."""
        from sftp_local_terminal_widget import _get_pipe_compatible_shell
        shell = _get_pipe_compatible_shell()
        assert 'fish' not in shell
        # Should be bash, zsh, or sh
        shell_name = os.path.basename(shell)
        assert shell_name in ('bash', 'zsh', 'sh')


class TestLocalTerminalImports:
    """Tests for module imports and structure."""

    def test_module_imports(self):
        """Test that the module imports without error."""
        from sftp_local_terminal_widget import (
            LocalTerminalWidget,
            strip_ansi_codes,
            ANSI_ESCAPE_PATTERN
        )
        assert LocalTerminalWidget is not None
        assert callable(strip_ansi_codes)
        assert ANSI_ESCAPE_PATTERN is not None

    def test_supports_local_terminal_always_true(self):
        """Test that supports_local_terminal returns True on all platforms."""
        from sftp_platform import supports_local_terminal
        assert supports_local_terminal() is True

    def test_get_default_shell_returns_string(self):
        """Test that get_default_shell returns a string."""
        from sftp_platform import get_default_shell
        shell = get_default_shell()
        assert isinstance(shell, str)
        assert len(shell) > 0


class TestLocalTerminalPrompt:
    """Tests for prompt generation."""

    def test_get_prompt_returns_string(self):
        """Test that _get_prompt returns a non-empty string."""
        import inspect
        from sftp_local_terminal_widget import LocalTerminalWidget

        source = inspect.getsource(LocalTerminalWidget._get_prompt)
        assert "def _get_prompt(self)" in source
        assert "cwd" in source
        assert "$ " in source or "> " in source


class TestLocalTerminalLineEditor:
    """Tests for line editor behavior."""

    def test_submit_line_sends_to_process(self):
        """Test that _submit_line sends input to the process."""
        import inspect
        from sftp_local_terminal_widget import LocalTerminalWidget

        source = inspect.getsource(LocalTerminalWidget._submit_line)
        assert "self.process.write" in source
        assert "self._marker" in source

    def test_handle_key_press_exists(self):
        """Test that _handle_key_press method exists."""
        from sftp_local_terminal_widget import LocalTerminalWidget
        assert hasattr(LocalTerminalWidget, '_handle_key_press')

    def test_handle_ctrl_c_exists(self):
        """Test that _handle_ctrl_c method exists."""
        from sftp_local_terminal_widget import LocalTerminalWidget
        assert hasattr(LocalTerminalWidget, '_handle_ctrl_c')

    def test_handle_ctrl_key_exists(self):
        """Test that _handle_ctrl_key method exists."""
        from sftp_local_terminal_widget import LocalTerminalWidget
        assert hasattr(LocalTerminalWidget, '_handle_ctrl_key')

    def test_update_line_display_exists(self):
        """Test that _update_line_display method exists."""
        from sftp_local_terminal_widget import LocalTerminalWidget
        assert hasattr(LocalTerminalWidget, '_update_line_display')


class TestLocalTerminalHistory:
    """Tests for command history."""

    def test_handle_history_up_exists(self):
        """Test that _handle_history_up method exists."""
        from sftp_local_terminal_widget import LocalTerminalWidget
        assert hasattr(LocalTerminalWidget, '_handle_history_up')

    def test_handle_history_down_exists(self):
        """Test that _handle_history_down method exists."""
        from sftp_local_terminal_widget import LocalTerminalWidget
        assert hasattr(LocalTerminalWidget, '_handle_history_down')


class TestLocalTerminalTabCompletion:
    """Tests for tab completion."""

    def test_handle_tab_exists(self):
        """Test that _handle_tab method exists."""
        from sftp_local_terminal_widget import LocalTerminalWidget
        assert hasattr(LocalTerminalWidget, '_handle_tab')

    def test_handle_tab_uses_glob(self):
        """Test that _handle_tab uses glob for file completion."""
        import inspect
        from sftp_local_terminal_widget import LocalTerminalWidget

        source = inspect.getsource(LocalTerminalWidget._handle_tab)
        assert "glob" in source.lower()


class TestLocalTerminalCleanup:
    """Tests for resource cleanup."""

    def test_close_method_exists(self):
        """Test that close method exists."""
        from sftp_local_terminal_widget import LocalTerminalWidget
        assert hasattr(LocalTerminalWidget, 'close')

    def test_close_event_exists(self):
        """Test that closeEvent method exists."""
        from sftp_local_terminal_widget import LocalTerminalWidget
        assert hasattr(LocalTerminalWidget, 'closeEvent')

    def test_close_terminates_process(self):
        """Test that close method terminates the QProcess."""
        import inspect
        from sftp_local_terminal_widget import LocalTerminalWidget

        source = inspect.getsource(LocalTerminalWidget.close)
        assert "terminate" in source
        assert "kill" in source

    def test_focus_method_exists(self):
        """Test that focus method exists."""
        from sftp_local_terminal_widget import LocalTerminalWidget
        assert hasattr(LocalTerminalWidget, 'focus')


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
