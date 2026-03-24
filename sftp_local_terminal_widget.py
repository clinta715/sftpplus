"""
Local Terminal Widget

A terminal widget for local shell using pty module.
Filters terminal control sequences for cleaner display.

Note: Local terminal is only supported on Unix systems (macOS/Linux).
On Windows, a placeholder message is shown instead.
"""

import os
import sys
import platform
import re
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPlainTextEdit, QLabel
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from sftp_platform import is_windows, supports_local_terminal, get_default_shell


def _check_unix_modules():
    """Check if Unix-only modules are available."""
    if is_windows():
        return None
    try:
        import pty
        import fcntl
        import struct
        import termios
        return {'pty': pty, 'fcntl': fcntl, 'struct': struct, 'termios': termios}
    except ImportError:
        return None


UNIX_MODULES = _check_unix_modules()

TERMINAL_CONTROL_PATTERN = re.compile(
    r'\x1b\[[0-9;?]*[a-zA-Z]|'
    r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\|$)|'
    r'\x1b[()][A-Za-z0-9]|'
    r'\x1b[=>]|'
    r'\x1b[78]|'
    r'\x1b[DE]|'
    r'\x1b[HM]|'
    r'\x1b[cl]|'
    r'\x1b[NO]|'
    r'\x1bP[^\\]*(?:\\|$)|'
    r'\x1b\[[\x3e0-9;]*q[0-9;]*~?'
)

DA_RESPONSE = b'\x1b[?1;0c'


def clean_terminal_output(text):
    """Remove terminal control sequences and clean up output"""
    text = TERMINAL_CONTROL_PATTERN.sub('', text)
    text = text.replace('\r\n', '\n').replace('\r', '')
    return text


class LocalTerminalWidget(QWidget):
    """
    Local terminal using pty module for proper terminal emulation.
    
    On Unix systems (macOS/Linux):
    - Spawns $SHELL (fallback: /bin/bash)
    - Real PTY for proper terminal behavior
    - Filters control sequences for cleaner display
    
    On Windows:
    - Shows a placeholder message explaining the limitation
    - Returns early from all operations
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.master_fd = None
        self.pid = None
        self._running = False
        self._notifier = None
        
        if not supports_local_terminal():
            self._init_windows_placeholder()
            return
            
        if UNIX_MODULES is None:
            self._init_windows_placeholder()
            return
            
        self._init_ui()
        self._start_shell()
        
    def _init_windows_placeholder(self):
        """Initialize placeholder for Windows systems."""
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        
        placeholder = QLabel()
        placeholder.setText(
            "Local Terminal is not available on Windows.\n\n"
            "This feature requires Unix PTY support.\n\n"
            "Please use the SSH Terminal tab for remote\n"
            "shell access, or use Windows Terminal/CMD/PowerShell\n"
            "for local commands."
        )
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("""
            QLabel {
                background-color: #1e1e1e;
                color: #888888;
                font-family: 'Menlo', 'Courier New', 'Monaco', monospace;
                font-size: 14px;
                border: 1px solid #444444;
                border-radius: 5px;
                padding: 20px;
            }
        """)
        placeholder.setWordWrap(True)
        
        layout.addWidget(placeholder)
        self.setLayout(layout)
        self._running = False
        
    def _init_ui(self):
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
        self.terminal.setReadOnly(True)
        self.terminal.installEventFilter(self)
        self.terminal.setPlaceholderText("Starting local shell...")
        
        layout.addWidget(self.terminal)
        self.setLayout(layout)
        
    def _start_shell(self):
        """Start the local shell process with proper PTY (Unix only)."""
        if not supports_local_terminal() or UNIX_MODULES is None:
            return
            
        pty = UNIX_MODULES['pty']
        fcntl = UNIX_MODULES['fcntl']
        struct = UNIX_MODULES['struct']
        termios = UNIX_MODULES['termios']
        
        shell = get_default_shell()
        
        self.pid, self.master_fd = pty.fork()
        
        if self.pid == 0:
            os.environ['TERM'] = 'xterm-256color'
            os.environ['COLORTERM'] = 'truecolor'
            os.environ['TERM_PROGRAM'] = 'sftp-client'
            os.execvpe(shell, [shell, '-i', '-l'], os.environ)
        else:
            self._running = True
            self.terminal.setPlaceholderText("")
            
            from PyQt6.QtCore import QSocketNotifier
            self._notifier = QSocketNotifier(self.master_fd, QSocketNotifier.Type.Read)
            self._notifier.activated.connect(self._on_output)
            
            self._set_pty_size()
            
    def _set_pty_size(self):
        """Set the PTY window size (Unix only)."""
        if not supports_local_terminal() or UNIX_MODULES is None:
            return
            
        fcntl = UNIX_MODULES['fcntl']
        struct = UNIX_MODULES['struct']
        termios = UNIX_MODULES['termios']
        
        try:
            font_metrics = self.terminal.fontMetrics()
            char_width = font_metrics.horizontalAdvance('M')
            char_height = font_metrics.height()
            
            width = max(80, self.terminal.width() // char_width)
            height = max(24, self.terminal.height() // char_height)
            
            winsize = struct.pack('HHHH', height, width, 0, 0)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
        except Exception:
            pass
            
    def _on_output(self, fd):
        """Handle output from shell (Unix only)."""
        if not self._running or self.master_fd is None:
            return
            
        try:
            data = os.read(fd, 65536)
            if data:
                if b'\x1b[c' in data or b'\x1b[?c' in data or b'\x1b[>c' in data:
                    try:
                        os.write(self.master_fd, DA_RESPONSE)
                    except OSError:
                        pass
                
                if b'\x1b[6n' in data or b'\x1b[?6n' in data:
                    try:
                        os.write(self.master_fd, b'\x1b[1;1R')
                    except OSError:
                        pass
                
                if b'\x1b[5n' in data:
                    try:
                        os.write(self.master_fd, b'\x1b[0n')
                    except OSError:
                        pass
                
                if b'\x1b[?2004h' in data or b'\x1b[>0q' in data:
                    pass
                
                text = data.decode('utf-8', errors='replace')
                text = clean_terminal_output(text)
                
                if text:
                    from PyQt6.QtGui import QTextCursor
                    cursor = self.terminal.textCursor()
                    cursor.movePosition(QTextCursor.MoveOperation.End)
                    cursor.insertText(text)
                    self.terminal.ensureCursorVisible()
        except OSError:
            self._running = False
            
    def eventFilter(self, obj, event):
        """Capture keyboard input (Unix only)."""
        if not supports_local_terminal() or UNIX_MODULES is None:
            return super().eventFilter(obj, event)
            
        from PyQt6.QtCore import QEvent
        if obj == self.terminal and event.type() == QEvent.Type.KeyPress:
            return self._handle_key_press(event)
        return super().eventFilter(obj, event)
        
    def _handle_key_press(self, event):
        """Handle key press and send to PTY (Unix only)."""
        if not self._running or self.master_fd is None:
            return False
            
        key = event.key()
        text = event.text()
        modifiers = event.modifiers()
        
        try:
            if modifiers & Qt.KeyboardModifier.ControlModifier:
                if key == Qt.Key.Key_C:
                    os.write(self.master_fd, b'\x03')
                    return True
                elif key == Qt.Key.Key_D:
                    os.write(self.master_fd, b'\x04')
                    return True
                elif key == Qt.Key.Key_L:
                    self.terminal.clear()
                    os.write(self.master_fd, b'\x0c')
                    return True
                elif key == Qt.Key.Key_A:
                    os.write(self.master_fd, b'\x01')
                    return True
                elif key == Qt.Key.Key_E:
                    os.write(self.master_fd, b'\x05')
                    return True
                elif key == Qt.Key.Key_U:
                    os.write(self.master_fd, b'\x15')
                    return True
                elif key == Qt.Key.Key_K:
                    os.write(self.master_fd, b'\x0b')
                    return True
                elif key == Qt.Key.Key_W:
                    os.write(self.master_fd, b'\x17')
                    return True
                elif key == Qt.Key.Key_R:
                    os.write(self.master_fd, b'\x12')
                    return True
                    
            if key == Qt.Key.Key_Enter or key == Qt.Key.Key_Return:
                os.write(self.master_fd, b'\r')
                return True
            elif key == Qt.Key.Key_Backspace:
                os.write(self.master_fd, b'\x7f')
                return True
            elif key == Qt.Key.Key_Delete:
                os.write(self.master_fd, b'\x1b[3~')
                return True
            elif key == Qt.Key.Key_Tab:
                os.write(self.master_fd, b'\t')
                return True
            elif key == Qt.Key.Key_Up:
                os.write(self.master_fd, b'\x1b[A')
                return True
            elif key == Qt.Key.Key_Down:
                os.write(self.master_fd, b'\x1b[B')
                return True
            elif key == Qt.Key.Key_Left:
                os.write(self.master_fd, b'\x1b[D')
                return True
            elif key == Qt.Key.Key_Right:
                os.write(self.master_fd, b'\x1b[C')
                return True
            elif key == Qt.Key.Key_Home:
                os.write(self.master_fd, b'\x1b[H')
                return True
            elif key == Qt.Key.Key_End:
                os.write(self.master_fd, b'\x1b[F')
                return True
            elif key == Qt.Key.Key_Escape:
                os.write(self.master_fd, b'\x1b')
                return True
            elif text:
                os.write(self.master_fd, text.encode('utf-8'))
                return True
                
        except OSError:
            self._running = False
            
        return False
        
    def closeEvent(self, event):
        """Clean up shell on close."""
        self._running = False
        
        if self._notifier:
            self._notifier.setEnabled(False)
            
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
                
        if self.pid is not None:
            try:
                os.kill(self.pid, 15)
                os.waitpid(self.pid, os.WNOHANG)
            except OSError:
                pass
                
        event.accept()
        
    def focus(self):
        """Focus the terminal."""
        if hasattr(self, 'terminal'):
            self.terminal.setFocus()
        
    def resizeEvent(self, event):
        """Handle resize to update PTY size."""
        super().resizeEvent(event)
        if self._running and self.master_fd is not None:
            self._set_pty_size()