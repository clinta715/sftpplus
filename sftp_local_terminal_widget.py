"""
Local Terminal Widget (QProcess-based)

Cross-platform local shell terminal using QProcess with pipes.
Implements custom line editing, command history, and prompt display.

No PTY dependency - works on Windows, macOS, and Linux.
The shell runs in non-interactive mode; all line editing is handled by the widget.
"""

import os
import getpass
import socket
import re
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPlainTextEdit
from PySide6.QtCore import Qt, QProcess, QTimer, QEvent
from PySide6.QtGui import QFont, QTextCursor

from sftp_platform import is_windows, get_default_shell


def _get_pipe_compatible_shell():
    """Get a shell that works with pipe stdin.

    Fish shell does not read from pipe stdin properly.
    Fall back to bash/zsh/sh for QProcess-based terminal.
    """
    shell = get_default_shell()
    shell_name = os.path.basename(shell)

    # Fish doesn't work with pipe stdin
    if shell_name in ('fish',):
        # Try bash first, then zsh, then sh
        for fallback in ('/bin/bash', '/usr/bin/bash', '/bin/zsh', '/bin/sh'):
            if os.path.exists(fallback):
                return fallback
    return shell


# ANSI escape code pattern (same as SSH terminal)
ANSI_ESCAPE_PATTERN = re.compile(
    r'\x1b\[[0-9;?]*[a-zA-Z]|'     # CSI sequences
    r'\x1b\][^\x07]*(?:\x07|$)|'    # OSC sequences (titles, etc.)
    r'\x1b[()][A-Za-z]'              # Character set switches
)


def strip_ansi_codes(text):
    """Remove ANSI escape codes from text."""
    return ANSI_ESCAPE_PATTERN.sub('', text)


class LocalTerminalWidget(QWidget):
    """
    Local terminal using QProcess with pipes.

    Cross-platform shell interaction with built-in line editing.
    No PTY dependency - works on Windows, macOS, and Linux.

    The shell runs in non-interactive mode. The widget handles:
    - Prompt display
    - Line editing (insert, delete, cursor movement)
    - Command history (up/down arrows)
    - Ctrl+C (cancel line), Ctrl+D (exit), Ctrl+L (clear)
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.process = None
        self._running = False

        # Line editor state
        self._line_buffer = ""
        self._cursor_pos = 0

        # Command history
        self._history = []
        self._history_index = -1
        self._saved_line = ""

        # Prompt state
        self._prompt_text = ""
        self._at_prompt = False

        # Marker for detecting command completion
        self._marker = "___SFTP_PROMPT_READY___"

        # Timer for detecting when output has settled
        self._output_timer = QTimer()
        self._output_timer.setSingleShot(True)
        self._output_timer.timeout.connect(self._on_output_settled)

        self._init_ui()
        self._start_shell()

    def _init_ui(self):
        """Initialize the terminal UI."""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.terminal = QPlainTextEdit()
        self.terminal.setReadOnly(False)
        self.terminal.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #cccccc;
                font-family: 'Menlo', 'Courier New', 'Monaco', monospace;
                font-size: 12px;
                border: none;
            }
        """)
        font = QFont('Menlo', 12)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.terminal.setFont(font)
        self.terminal.setMaximumBlockCount(10000)
        self.terminal.installEventFilter(self)
        self.terminal.setPlaceholderText("Starting local shell...")

        layout.addWidget(self.terminal)
        self.setLayout(layout)

    def _start_shell(self):
        """Start the shell process using QProcess."""
        self.process = QProcess()

        # Configure environment to force color output
        env = self.process.processEnvironment()
        env.insert('TERM', 'xterm-256color')
        env.insert('FORCE_COLOR', '1')
        env.insert('CLICOLOR', '1')
        env.insert('CLICOLOR_FORCE', '1')
        if is_windows():
            env.insert('PROMPT', '')
        self.process.setProcessEnvironment(env)

        # Connect signals
        self.process.readyReadStandardOutput.connect(self._on_stdout)
        self.process.readyReadStandardError.connect(self._on_stderr)
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(self._on_error)

        # Start shell (use pipe-compatible shell - fish doesn't work with pipes)
        shell = _get_pipe_compatible_shell()
        self.process.start(shell)
        if self.process.waitForStarted(3000):
            self._running = True
            self.terminal.setPlaceholderText("")
            self._show_prompt()
        else:
            self.terminal.setPlaceholderText("Failed to start shell")

    def _get_prompt(self):
        """Generate prompt string."""
        cwd = os.getcwd()
        home = os.path.expanduser("~")
        if cwd.startswith(home):
            cwd = "~" + cwd[len(home):]

        if is_windows():
            return f"{cwd}> "
        else:
            user = getpass.getuser()
            host = socket.gethostname().split('.')[0]
            return f"{user}@{host}:{cwd}$ "

    def _show_prompt(self):
        """Display the prompt and prepare for input."""
        self._prompt_text = self._get_prompt()
        cursor = self.terminal.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(self._prompt_text)
        self.terminal.setTextCursor(cursor)
        self.terminal.ensureCursorVisible()
        self._at_prompt = True
        self._line_buffer = ""
        self._cursor_pos = 0

    def _update_line_display(self):
        """Update the displayed line to match the line buffer."""
        text = self.terminal.toPlainText()
        prompt_pos = text.rfind(self._prompt_text)
        if prompt_pos < 0:
            cursor = self.terminal.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(self._line_buffer)
            self.terminal.setTextCursor(cursor)
            return

        cursor = self.terminal.textCursor()
        cursor.setPosition(prompt_pos + len(self._prompt_text))
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertText(self._line_buffer)

        cursor.setPosition(prompt_pos + len(self._prompt_text) + self._cursor_pos)
        self.terminal.setTextCursor(cursor)
        self.terminal.ensureCursorVisible()

    def _append_output(self, text):
        """Append output text to the terminal."""
        if not text:
            return
        cursor = self.terminal.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.terminal.setTextCursor(cursor)
        self.terminal.ensureCursorVisible()

    def _on_stdout(self):
        """Handle stdout data from shell."""
        if not self.process:
            return
        data = self.process.readAllStandardOutput().data().decode('utf-8', errors='ignore')
        if not data:
            return

        clean = strip_ansi_codes(data)

        if self._marker in clean:
            parts = clean.split(self._marker)
            output_part = parts[0]
            if output_part:
                self._append_output(output_part)
            self._show_prompt()
            return

        self._append_output(clean)
        self._output_timer.start(150)

    def _on_stderr(self):
        """Handle stderr data from shell."""
        if not self.process:
            return
        data = self.process.readAllStandardError().data().decode('utf-8', errors='ignore')
        if data:
            clean = strip_ansi_codes(data)
            self._append_output(clean)
            self._output_timer.start(150)

    def _on_output_settled(self):
        """Called when no output has arrived for a short period."""
        if not self._at_prompt and self._running:
            self._show_prompt()

    def _on_finished(self, exit_code, exit_status):
        """Handle shell process exit."""
        self._running = False
        self._append_output(f"\nShell exited (code {exit_code})\n")

    def _on_error(self, error):
        """Handle shell process error."""
        self._running = False
        if error == QProcess.ProcessError.FailedToStart:
            self._append_output("Error: Failed to start shell process\n")

    def _submit_line(self):
        """Submit the current line to the shell."""
        line = self._line_buffer
        self._line_buffer = ""
        self._cursor_pos = 0
        self._at_prompt = False

        self._append_output("\n")

        if line.strip():
            self._history.append(line)
            if len(self._history) > 1000:
                self._history.pop(0)
        self._history_index = -1
        self._saved_line = ""

        if self.process and self.process.state() == QProcess.ProcessState.Running:
            self.process.write((line + f'\necho {self._marker}\n').encode('utf-8'))

    def eventFilter(self, obj, event):
        """Capture keyboard input."""
        if obj == self.terminal and event.type() == QEvent.Type.KeyPress:
            return self._handle_key_press(event)
        return super().eventFilter(obj, event)

    def _handle_key_press(self, event):
        """Handle key press events."""
        key = event.key()
        text = event.text()
        modifiers = event.modifiers()

        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_C:
                return self._handle_ctrl_c()
            if not self._running or not self._at_prompt:
                return False
            return self._handle_ctrl_key(key)

        if not self._running or not self._at_prompt:
            return False

        if key in (Qt.Key.Key_Enter, Qt.Key.Key_Return):
            self._submit_line()
            return True

        if key == Qt.Key.Key_Backspace:
            if self._cursor_pos > 0:
                self._line_buffer = (
                    self._line_buffer[:self._cursor_pos - 1] +
                    self._line_buffer[self._cursor_pos:]
                )
                self._cursor_pos -= 1
                self._update_line_display()
            return True

        if key == Qt.Key.Key_Delete:
            if self._cursor_pos < len(self._line_buffer):
                self._line_buffer = (
                    self._line_buffer[:self._cursor_pos] +
                    self._line_buffer[self._cursor_pos + 1:]
                )
                self._update_line_display()
            return True

        if key == Qt.Key.Key_Left:
            if self._cursor_pos > 0:
                self._cursor_pos -= 1
                self._update_line_display()
            return True

        if key == Qt.Key.Key_Right:
            if self._cursor_pos < len(self._line_buffer):
                self._cursor_pos += 1
                self._update_line_display()
            return True

        if key == Qt.Key.Key_Up:
            self._handle_history_up()
            return True

        if key == Qt.Key.Key_Down:
            self._handle_history_down()
            return True

        if key == Qt.Key.Key_Home:
            self._cursor_pos = 0
            self._update_line_display()
            return True

        if key == Qt.Key.Key_End:
            self._cursor_pos = len(self._line_buffer)
            self._update_line_display()
            return True

        if key == Qt.Key.Key_Tab:
            self._handle_tab()
            return True

        if key == Qt.Key.Key_Escape:
            self._line_buffer = ""
            self._cursor_pos = 0
            self._append_output("\n")
            self._show_prompt()
            return True

        if text and text.isprintable():
            self._line_buffer = (
                self._line_buffer[:self._cursor_pos] +
                text +
                self._line_buffer[self._cursor_pos:]
            )
            self._cursor_pos += len(text)
            self._update_line_display()
            return True

        return False

    def _handle_ctrl_key(self, key):
        """Handle Ctrl+key combinations."""
        if key == Qt.Key.Key_D:
            if not self._line_buffer:
                self._append_output("exit\n")
                if self.process:
                    self.process.write(b'exit\n')
            else:
                if self._cursor_pos < len(self._line_buffer):
                    self._line_buffer = (
                        self._line_buffer[:self._cursor_pos] +
                        self._line_buffer[self._cursor_pos + 1:]
                    )
                    self._update_line_display()
            return True

        if key == Qt.Key.Key_L:
            self.terminal.clear()
            self._show_prompt()
            return True

        if key == Qt.Key.Key_A:
            self._cursor_pos = 0
            self._update_line_display()
            return True

        if key == Qt.Key.Key_E:
            self._cursor_pos = len(self._line_buffer)
            self._update_line_display()
            return True

        if key == Qt.Key.Key_U:
            self._line_buffer = self._line_buffer[self._cursor_pos:]
            self._cursor_pos = 0
            self._update_line_display()
            return True

        if key == Qt.Key.Key_K:
            self._line_buffer = self._line_buffer[:self._cursor_pos]
            self._update_line_display()
            return True

        if key == Qt.Key.Key_W:
            before = self._line_buffer[:self._cursor_pos]
            after = self._line_buffer[self._cursor_pos:]
            stripped = before.rstrip()
            if stripped:
                last_space = stripped.rfind(' ')
                if last_space >= 0:
                    before = before[:last_space + 1]
                else:
                    before = ""
            self._line_buffer = before + after
            self._cursor_pos = len(before)
            self._update_line_display()
            return True

        return False

    def _handle_ctrl_c(self):
        """Handle Ctrl+C - cancel current line."""
        if self._at_prompt:
            self._append_output("^C\n")
            self._line_buffer = ""
            self._cursor_pos = 0
            self._show_prompt()
        return True

    def _handle_history_up(self):
        """Navigate up in command history."""
        if not self._history:
            return
        if self._history_index == -1:
            self._saved_line = self._line_buffer
            self._history_index = len(self._history) - 1
        elif self._history_index > 0:
            self._history_index -= 1
        self._line_buffer = self._history[self._history_index]
        self._cursor_pos = len(self._line_buffer)
        self._update_line_display()

    def _handle_history_down(self):
        """Navigate down in command history."""
        if self._history_index >= 0:
            if self._history_index < len(self._history) - 1:
                self._history_index += 1
                self._line_buffer = self._history[self._history_index]
            else:
                self._history_index = -1
                self._line_buffer = self._saved_line
            self._cursor_pos = len(self._line_buffer)
            self._update_line_display()

    def _handle_tab(self):
        """Handle tab key - file path completion."""
        words = self._line_buffer[:self._cursor_pos].split()
        if not words:
            return

        partial = words[-1]
        import glob as glob_mod

        try:
            expanded = os.path.expanduser(partial)
            if expanded != partial:
                matches = glob_mod.glob(expanded + '*')
                home = os.path.expanduser("~")
                matches = [
                    '~' + m[len(home):] if m.startswith(home) else m
                    for m in matches
                ]
            else:
                matches = glob_mod.glob(partial + '*')
        except (OSError, ValueError):
            return

        if len(matches) == 1:
            completion = matches[0][len(partial):]
            full_path = os.path.expanduser(matches[0])
            if os.path.isdir(full_path):
                completion += os.sep
            self._line_buffer = (
                self._line_buffer[:self._cursor_pos] +
                completion +
                self._line_buffer[self._cursor_pos:]
            )
            self._cursor_pos += len(completion)
            self._update_line_display()
        elif len(matches) > 1:
            common = os.path.commonprefix(matches)
            if len(common) > len(partial):
                completion = common[len(partial):]
                self._line_buffer = (
                    self._line_buffer[:self._cursor_pos] +
                    completion +
                    self._line_buffer[self._cursor_pos:]
                )
                self._cursor_pos += len(completion)
                self._update_line_display()
            else:
                self._append_output("\n" + "  ".join(matches) + "\n")
                self._show_prompt()
                self._line_buffer = self._line_buffer
                self._cursor_pos = self._cursor_pos
                self._update_line_display()

    def close(self):
        """Clean up shell process."""
        self._running = False
        self._output_timer.stop()

        if self.process:
            self.process.blockSignals(True)
            if self.process.state() == QProcess.ProcessState.Running:
                self.process.terminate()
                if not self.process.waitForFinished(1000):
                    self.process.kill()
                    self.process.waitForFinished(500)
            self.process = None

    def closeEvent(self, event):
        """Handle widget close."""
        self.close()
        event.accept()

    def focus(self):
        """Focus the terminal."""
        if hasattr(self, 'terminal'):
            self.terminal.setFocus()
