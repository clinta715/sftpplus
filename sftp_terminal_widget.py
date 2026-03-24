"""
SSH Terminal Widget

A simple terminal widget for SSH connections using QPlainTextEdit and paramiko.
No additional dependencies beyond PyQt6 and paramiko.
"""
import threading
import os
import re
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPlainTextEdit, QMessageBox
from sftp_qt_compat import Qt
from PyQt6.QtCore import pyqtSignal, QObject, QEvent
from PyQt6.QtGui import QTextCursor
import paramiko

from sftp_creds import sanitize_error_message


# Comprehensive ANSI escape code regex pattern
# Matches:
# - CSI sequences: \x1b[... (colors, bold, cursor movement, etc.)
# - Private CSI: \x1b[?... (bracketed paste mode, alternate screen, etc.)
# - OSC sequences: \x1b]... (terminal titles, etc.)
# - Character set: \x1b( and \x1b)
ANSI_ESCAPE_PATTERN = re.compile(
    r'\x1b\[[0-9;?]*[a-zA-Z]|'     # CSI sequences
    r'\x1b\][^\x07]*(?:\x07|$)|'    # OSC sequences (titles, etc.)
    r'\x1b[()][A-Za-z]'              # Character set switches
)


def strip_ansi_codes(text):
    """Remove ANSI escape codes from text (for colors, bold, etc.)"""
    return ANSI_ESCAPE_PATTERN.sub('', text)


class _TerminalOutputEvent(QEvent):
    """Custom event for thread-safe terminal output"""
    def __init__(self, callback):
        super().__init__(Qt.User)
        self.callback = callback


class TerminalSignals(QObject):
    """Signals for terminal events"""
    disconnected = pyqtSignal()
    connected = pyqtSignal()
    error = pyqtSignal(str)


class SSHTerminalWidget(QWidget):
    """
    Simple SSH terminal widget using QPlainTextEdit.
    
    Provides basic terminal functionality:
    - Display SSH shell output
    - Send keyboard input to SSH shell
    - Auto-scroll to bottom
    """
    
    def __init__(self, session_id, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.ssh = None
        self.channel = None
        self._read_thread = None
        self._running = False
        self.signals = TerminalSignals()
        
        self._init_ui()
    
    def _init_ui(self):
        """Initialize the UI"""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.terminal = QPlainTextEdit()
        self.terminal.setReadOnly(False)
        self.terminal.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #cccccc;
                font-family: 'Menlo', 'Courier New', monospace;
                font-size: 12px;
                border: none;
            }
        """)
        self.terminal.setMaximumBlockCount(10000)
        self.terminal.installEventFilter(self)
        
        layout.addWidget(self.terminal)
        self.setLayout(layout)
        
        self.terminal.setPlaceholderText("Connecting to SSH...")
    
    def eventFilter(self, obj, event):
        """Capture keyboard input"""
        if obj == self.terminal and event.type() == Qt.KeyPress:
            key = event.text()
            if key:
                self._send_input(key)
            else:
                key_int = event.key()
                if key_int == Qt.Key_Return or key_int == Qt.Key_Enter:
                    self._send_input('\r')
                elif key_int == Qt.Key_Backspace:
                    self._send_input('\x7f')
                elif key_int == Qt.Key_Up:
                    self._send_input('\x1b[A')
                elif key_int == Qt.Key_Down:
                    self._send_input('\x1b[B')
                elif key_int == Qt.Key_Right:
                    self._send_input('\x1b[C')
                elif key_int == Qt.Key_Left:
                    self._send_input('\x1b[D')
                elif key_int == Qt.Key_Tab:
                    self._send_input('\t')
                else:
                    return super().eventFilter(obj, event)
            return True
        return super().eventFilter(obj, event)
    
    def customEvent(self, event):
        """Handle custom events for thread-safe UI updates"""
        if isinstance(event, _TerminalOutputEvent):
            try:
                event.callback()
            except (RuntimeError, AttributeError) as e:
                pass

    def _setup_host_key_policy(self, ssh):
        """
        Setup SSH host key verification policy.
        Loads known_hosts and prompts user for unknown hosts.
        """
        known_hosts_path = os.path.expanduser('~/.ssh/known_hosts')
        
        # Try to load existing known_hosts
        if os.path.exists(known_hosts_path):
            try:
                ssh.load_host_keys(known_hosts_path)
            except (OSError, IOError, paramiko.SSHException) as e:
                self.terminal.appendPlainText(f"Warning: Could not load known_hosts: {sanitize_error_message(str(e))}\n")
        
        # Set up policy to warn about unknown hosts
        class InteractivePolicy(paramiko.MissingHostKeyPolicy):
            def __init__(self, parent):
                self.parent = parent
                self.known_hosts_path = known_hosts_path
                
            def missing_host_key(self, client, hostname, key):
                # Check if this is a new host
                key_type = key.get_name()
                fingerprint = key.get_fingerprint().hex()
                
                msg = f"Unknown host: {hostname}\n\nKey type: {key_type}\nFingerprint: {fingerprint}\n\nDo you want to trust this host and add it to known_hosts?"
                
                reply = QMessageBox.question(
                    self.parent,
                    "Unknown Host Key",
                    msg,
                    Qt.MsgBtn_Yes | Qt.MsgBtn_No,
                    Qt.MsgBtn_No
                )
                
                if reply == Qt.MsgBtn_Yes:
                    # Add to known_hosts
                    try:
                        client.save_host_keys(self.known_hosts_path)
                        return
                    except (OSError, IOError) as e:
                        self.parent.terminal.appendPlainText(f"Warning: Could not save host key: {sanitize_error_message(str(e))}\n")
                        return
                else:
                    raise paramiko.SSHException(f"Host key verification failed for {hostname}")
        
        ssh.set_missing_host_key_policy(InteractivePolicy(self))
    
    def connect_ssh(self, hostname, username, password=None, port=22, key=None, ssh_commands=""):
        """Connect to SSH server and start interactive shell"""
        try:
            self.ssh = paramiko.SSHClient()
            self._setup_host_key_policy(self.ssh)
            
            connect_kwargs = {
                'hostname': hostname,
                'username': username,
                'port': port,
            }
            
            if key:
                try:
                    connect_kwargs['key_filename'] = key
                except (OSError, IOError) as e:
                    pass
            
            if password:
                connect_kwargs['password'] = password
            
            self.ssh.connect(**connect_kwargs)
            
            self.channel = self.ssh.invoke_shell(
                term='xterm-256color',
                width=80,
                height=24
            )
            
            self._running = True
            self._start_read_thread()
            
            self.signals.connected.emit()
            self.terminal.setPlaceholderText(f"Connected to {username}@{hostname}")
            self.terminal.appendPlainText(f"Connected to {username}@{hostname}\n")
            
            
            if ssh_commands:
                import time
                time.sleep(0.5)
                for command in ssh_commands.split('\n'):
                    command = command.strip()
                    if command:
                        self.terminal.appendPlainText(f"$ {command}\n")
                        self.send_command(command)
                        time.sleep(0.3)
            
        except (paramiko.SSHException, OSError, IOError) as e:
            error_msg = f"Connection failed: {sanitize_error_message(str(e))}"
            self.terminal.setPlaceholderText(error_msg)
            self.signals.error.emit(error_msg)
    
    def _start_read_thread(self):
        """Start background thread to read from SSH channel"""
        self._read_thread = threading.Thread(target=self._read_from_shell, daemon=True)
        self._read_thread.start()
    
    def _read_from_shell(self):
        """Background thread: read from SSH channel and display"""
        while self._running and self.channel:
            try:
                if self.channel.recv_ready():
                    data = self.channel.recv(4096).decode('utf-8', errors='ignore')
                    if data:
                        # Strip ANSI escape codes for clean display
                        clean_data = strip_ansi_codes(data)
                        self._append_output(clean_data)
                else:
                    import time
                    time.sleep(0.05)
            except (paramiko.SSHException, OSError, IOError) as e:
                if self._running:
                    pass
                break
        
        if self._running:
            self._append_output("\n*** Disconnected ***\n")
            try:
                self.signals.disconnected.emit()
            except RuntimeError:
                pass
    
    def _append_output(self, text):
        """Thread-safe append of output to terminal"""
        def append_text():
            try:
                if self.terminal is None:
                    return
                cursor = self.terminal.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                cursor.insertText(text)
                self.terminal.setTextCursor(cursor)
                self.terminal.ensureCursorVisible()
            except (RuntimeError, AttributeError) as e:
                pass
        
        try:
            from PyQt6.QtWidgets import QApplication
            QApplication.instance().postEvent(self, _TerminalOutputEvent(append_text))
        except (RuntimeError, AttributeError) as e:
            pass
    
    def _send_input(self, text):
        """Send keyboard input to SSH channel"""
        if self.channel and self.channel.send_ready():
            try:
                self.channel.send(text)
            except (paramiko.SSHException, OSError, IOError) as e:
                pass
    
    def send_command(self, command):
        """Send a command string to the shell"""
        if self.channel and self.channel.send_ready():
            try:
                self.channel.send(command + '\n')
            except (paramiko.SSHException, OSError, IOError) as e:
                pass
    
    def disconnect_ssh(self):
        """Disconnect from SSH"""
        self._running = False
        
        if self.channel:
            try:
                self.channel.close()
            except (paramiko.SSHException, OSError, IOError):
                pass
        
        if self.ssh:
            try:
                self.ssh.close()
            except (paramiko.SSHException, OSError, IOError):
                pass
        
        self.channel = None
        self.ssh = None
        
        try:
            self.signals.disconnected.emit()
        except RuntimeError:
            pass
    
    def close(self):
        """Clean up resources"""
        self.disconnect_ssh()
    
    def __del__(self):
        """Destructor"""
        self.close()
