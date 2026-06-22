import sys
import os
import json
import argparse
import threading
import logging
from sftp_transfer_queue_widget import TransferQueueWidget
from sftp_hostdataeditor import (
    update_connection_data, get_site_names, get_site_data
)
from sftp_theme import BUTTON_STYLE_DARK
from sftp_connections_widget import ConnectionsWidget
from sftp_file_browser_panel import FileBrowserPanel
from sftp_terminal_widget import SSHTerminalWidget
from sftp_local_terminal_widget import LocalTerminalWidget
from sftp_creds import get_credentials, set_credentials, del_credentials, create_random_integer, clear_all_credentials, get_home_directory
from sftp_session import get_session_manager
from sftp_qt_compat import Qt  # Use compatibility layer for Qt enums
from PySide6.QtWidgets import QInputDialog, QFileDialog, QLabel, QToolButton, QMainWindow, QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QTextEdit, QCompleter, QComboBox, QSpinBox, QTabWidget, QMessageBox, QCheckBox, QMenu, QSizePolicy, QProgressDialog, QDialog, QDialogButtonBox, QListWidget, QListWidgetItem, QRadioButton, QGroupBox
from PySide6.QtCore import Signal, QObject, QCoreApplication, QTimer, QEvent, QRunnable, QThreadPool, QEventLoop
from PySide6.QtGui import QKeySequence, QShortcut
import paramiko

from sftp_preferences import get_preferences
from sftp_toolbar_customizer import customize_toolbar
from sftp_context_menu_customizer import is_visible, customize_context_menus
from sftp_about import show_about
from sftp_logging import setup_logging, get_logger
from sftp_platform import get_known_hosts_path, create_secure_directory, get_sessions_path

logger = logging.getLogger('sftp')

class CustomComboBox(QComboBox):
    editingFinished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.editingFinished.emit()

class WorkerSignals(QObject):
    error = Signal(int, str)


class ConnectionTestSignals(QObject):
    step = Signal(str)
    success = Signal(str)
    error = Signal(str)
    prompt_unknown_host = Signal(str, str, str)
    prompt_bad_host_key = Signal(str, str)


class ConnectionTestWorker(QRunnable):
    MAX_RETRIES = 4

    def __init__(self, hostname, port, username, password, pkey,
                 known_hosts_path):
        super().__init__()
        self.hostname = hostname
        self.port = port
        self.username = username
        self.password = password
        self.pkey = pkey
        self.known_hosts_path = known_hosts_path
        self.signals = ConnectionTestSignals()
        self._prompt_event = threading.Event()
        self._prompt_result = None
        self._cancelled = False
        self.setAutoDelete(True)

    def resolve_prompt(self, accepted):
        self._prompt_result = accepted
        self._prompt_event.set()

    def cancel(self):
        self._cancelled = True
        self._prompt_result = False
        self._prompt_event.set()

    def _wait_for_prompt(self, timeout=120):
        self._prompt_event.wait(timeout)
        return self._prompt_result

    @staticmethod
    def _is_transient_error(exc):
        msg = str(exc).lower()
        transient_keywords = [
            'banner', 'timeout', 'timed out', 'eof', 'connection reset',
            'broken pipe', 'refused', 'unreachable', 'no route',
            'network is', 'temporarily unavailable', 'channel',
            'session is not active', 'session active', 'transport',
        ]
        return any(kw in msg for kw in transient_keywords)

    @staticmethod
    def _friendly_error(exc):
        msg = str(exc)
        lower = msg.lower()
        if 'banner' in lower:
            return (
                "Could not establish SSH connection.\n\n"
                "The server did not respond in time. This may be caused by:\n"
                "  \u2022 Network congestion or temporary outage\n"
                "  \u2022 The server is overloaded or restarting\n"
                "  \u2022 A firewall blocking the connection\n\n"
                "Please try again in a moment."
            )
        if 'timeout' in lower or 'timed out' in lower:
            return (
                "Connection timed out.\n\n"
                "The server did not respond within the allowed time.\n"
                "Please check your network connection and try again."
            )
        if 'refused' in lower:
            return (
                "Connection refused.\n\n"
                f"The server refused the connection on port {msg}.\n"
                "The SSH service may not be running."
            )
        if 'unreachable' in lower or 'no route' in lower:
            return (
                "Host unreachable.\n\n"
                "The server could not be reached. Please check:\n"
                "  \u2022 The hostname is correct\n"
                "  \u2022 Your network connection is active"
            )
        if 'authentication' in lower or 'permission denied' in lower:
            return (
                "Authentication failed.\n\n"
                "Please check your username and password or SSH key."
            )
        return f"Connection failed:\n{msg}"

    def run(self):
        for _attempt in range(self.MAX_RETRIES):
            if self._cancelled:
                self.signals.error.emit("Connection cancelled")
                return
            try:
                home_dir = self._do_connect()
                self.signals.success.emit(home_dir)
                return
            except paramiko.BadHostKeyException as e:
                fingerprint = (e.key.get_fingerprint().hex()
                               if e.key else 'unknown')
                self._prompt_event.clear()
                self._prompt_result = None
                self.signals.prompt_bad_host_key.emit(
                    e.hostname, fingerprint)
                if self._wait_for_prompt():
                    self._remove_host_key(e.hostname)
                    continue
                self.signals.error.emit(
                    f"Host key verification failed for {e.hostname}")
                return
            except Exception as e:
                if self._cancelled:
                    self.signals.error.emit("Connection cancelled")
                    return
                if self._is_transient_error(e) and _attempt < self.MAX_RETRIES - 1:
                    import time as _time
                    _time.sleep(1)
                    continue
                msg = self._friendly_error(e)
                self.signals.error.emit(msg)
                return
        self.signals.error.emit("Connection failed after multiple retries")

    def _do_connect(self):
        ssh = paramiko.SSHClient()
        sftp = None
        home_dir = '/'
        try:
            if os.path.exists(self.known_hosts_path):
                try:
                    ssh.load_host_keys(self.known_hosts_path)
                except (OSError, IOError, RuntimeError):
                    pass

            worker_self = self

            class _Policy(paramiko.MissingHostKeyPolicy):
                def missing_host_key(self, client, hostname, key):
                    worker_self._prompt_event.clear()
                    worker_self._prompt_result = None
                    worker_self.signals.prompt_unknown_host.emit(
                        hostname, key.get_name(),
                        key.get_fingerprint().hex())
                    if worker_self._wait_for_prompt():
                        client.get_host_keys().add(
                            hostname, key.get_name(), key)
                        try:
                            # Ensure the directory exists
                            dir_path = os.path.dirname(worker_self.known_hosts_path)
                            if dir_path:
                                create_secure_directory(dir_path)
                            client.save_host_keys(
                                worker_self.known_hosts_path)
                        except (OSError, IOError, RuntimeError):
                            pass
                        return
                    raise paramiko.SSHException(
                        f"Host key verification failed for {hostname}")

            ssh.set_missing_host_key_policy(_Policy())

            self.signals.step.emit(
                f"Connecting to {self.hostname}:{self.port}...")

            kwargs = {
                'hostname': self.hostname,
                'port': self.port,
                'username': self.username,
                'timeout': 60,
            }

            if self.pkey:
                self.signals.step.emit("Authenticating with SSH key...")
                ssh.connect(**kwargs, pkey=self.pkey)
            else:
                self.signals.step.emit("Authenticating...")
                kwargs['password'] = self.password
                ssh.connect(**kwargs)

            self.signals.step.emit("Opening SFTP channel...")
            sftp = ssh.open_sftp()

            self.signals.step.emit("Testing directory access...")
            sftp.listdir('.')

            self.signals.step.emit("Determining home directory...")
            try:
                stdin, stdout, stderr = ssh.exec_command('pwd')
                output = stdout.read().decode().strip()
                err = stderr.read().decode().strip()
                if output and not err:
                    home_dir = output
            except (OSError, IOError, RuntimeError):
                pass

            return home_dir
        finally:
            if sftp:
                try:
                    sftp.close()
                except (OSError, IOError, RuntimeError):
                    pass
            try:
                ssh.close()
            except (OSError, IOError, RuntimeError):
                pass

    def _remove_host_key(self, hostname):
        if os.path.exists(self.known_hosts_path):
            try:
                tmp = paramiko.SSHClient()
                tmp.load_host_keys(self.known_hosts_path)
                host_keys = tmp.get_host_keys()
                # HostKeys is dict-like for some operations, but not always for deletion
                if hostname in host_keys:
                    try:
                        # Try standard dict-like pop
                        if hasattr(host_keys, 'pop'):
                            host_keys.pop(hostname)
                        elif hasattr(host_keys, '_keys'):
                            # Fallback to private dict if necessary
                            host_keys._keys.pop(hostname, None)
                        else:
                            # Final fallback - clear and re-add others (inefficient but safe)
                            del host_keys[hostname]
                    except (TypeError, KeyError, AttributeError):
                        pass
                tmp.save_host_keys(self.known_hosts_path)
            except Exception as e:
                logger.error(f"Error removing host key for {hostname}: {e}")


class MainWindow(QMainWindow):  # Inherits from QMainWindow
    message_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self.message_signal.connect(self.update_console)

        QCoreApplication.instance().aboutToQuit.connect(self.cleanup)
        self.hostnames = []
        self.sessions = []
        self.observers = []
        self._notifying = False
        self._connecting = False

        self.worker_signals = WorkerSignals()
        self.worker_signals.error.connect(self._display_error)

        self.init_ui()

        # Setup keyboard shortcuts
        self.setup_keyboard_shortcuts()

        # Install event filter for window movement
        self.installEventFilter(self)
        
        # Note: Transfer queue widget will be created after init_ui() sets up the tab widget

    def _display_error(self, transfer_id, message):
        # Display error in a message box
        QMessageBox.critical(self, "Error", f"Transfer {transfer_id}: {message}")
        
        # Display the error in the status bar
        self.status_message.setText(f"Error in transfer {transfer_id}: {message}")
        self.status_message.setStyleSheet("""
            QLabel {
                background-color: #5a1a1a;
                color: #ff6b6b;
                padding: 5px 10px;
                border-top: 1px solid #ff6b6b;
                font-size: 12px;
            }
        """)

    def setup_keyboard_shortcuts(self):
        shortcuts = [
            (QKeySequence("Ctrl+R"), self._toolbar_refresh),
            (QKeySequence("F5"), self._toolbar_refresh),
            (QKeySequence("Ctrl+N"), self._new_connection_tab),
            (QKeySequence("Ctrl+W"), self._close_current_tab),
            (QKeySequence("Ctrl+Shift+N"), self._toolbar_new_folder),
            (QKeySequence("F6"), self._toolbar_download),
            (QKeySequence("F7"), self._toolbar_upload),
            (QKeySequence("Ctrl+U"), self._toolbar_upload),
            (QKeySequence("Ctrl+D"), self._toolbar_download),
            (QKeySequence("F2"), self._toolbar_rename),
            (QKeySequence("Delete"), self._toolbar_delete),
            (QKeySequence("Backspace"), self._navigate_parent),
            (QKeySequence("Ctrl+L"), self._focus_address_bar),
            (QKeySequence("Ctrl+B"), self._add_bookmark),
            (QKeySequence("Ctrl+P"), self._toggle_preview),
            (QKeySequence("Ctrl+T"), self._toggle_transfers_tab),
            (QKeySequence("Ctrl+Shift+T"), self._customize_toolbar),
            (QKeySequence("F1"), self._show_shortcuts_help),
            (QKeySequence("Ctrl+Return"), self._toolbar_view),
        ]
        for key_seq, callback in shortcuts:
            shortcut = QShortcut(key_seq, self)
            shortcut.activated.connect(callback)
    
    def _show_shortcuts_help(self):
        """Show keyboard shortcuts help dialog"""
        shortcuts_text = """
<h2>Keyboard Shortcuts</h2>
<table border="1" cellpadding="5">
<tr><th>Action</th><th>Shortcut</th></tr>
<tr><td>Refresh</td><td>Ctrl+R or F5</td></tr>
<tr><td>New Connection</td><td>Ctrl+N</td></tr>
<tr><td>Close Tab</td><td>Ctrl+W</td></tr>
<tr><td>Upload</td><td>Ctrl+U or F7</td></tr>
<tr><td>Download</td><td>Ctrl+D or F6</td></tr>
<tr><td>New Folder</td><td>Ctrl+Shift+N</td></tr>
<tr><td>Delete</td><td>Delete</td></tr>
<tr><td>Rename</td><td>F2</td></tr>
<tr><td>View File</td><td>Enter</td></tr>
<tr><td>Go to Parent</td><td>Backspace</td></tr>
<tr><td>Address Bar</td><td>Ctrl+L</td></tr>
<tr><td>Add Bookmark</td><td>Ctrl+B</td></tr>
<tr><td>Toggle Preview</td><td>Ctrl+P</td></tr>
<tr><td>Transfers Tab</td><td>Ctrl+T</td></tr>
<tr><td>Customize Toolbar</td><td>Ctrl+Shift+T</td></tr>
<tr><td>This Help</td><td>F1</td></tr>
</table>
        """.strip()
        
        msg = QMessageBox(self)
        msg.setWindowTitle("Keyboard Shortcuts")
        msg.setText(shortcuts_text)
        msg.setTextFormat(Qt.TextFormat_RichText)
        msg.exec()

    def _new_connection_tab(self):
        self.tab_widget.setCurrentIndex(1)
        self.hostname_combo.setFocus()

    def _close_current_tab(self):
        current_index = self.tab_widget.currentIndex()
        if current_index > 1:
            self.closeTab(current_index)

    def _navigate_parent(self):
        browser = self._get_active_browser()
        if browser:
            browser.navigate_to_parent()

    def _focus_address_bar(self):
        browser = self._get_active_browser()
        if browser and hasattr(browser, 'tree_path_input'):
            browser.tree_path_input.setFocus()
            browser.tree_path_input.selectAll()

    def _add_bookmark(self):
        browser = self._get_active_browser()
        if browser and hasattr(browser, 'add_bookmark'):
            browser.add_bookmark()

    def _toggle_preview(self):
        current_widget = self.tab_widget.currentWidget()
        if hasattr(current_widget, 'file_browser_panel'):
            panel = current_widget.file_browser_panel
            if hasattr(panel, 'toggle_preview'):
                panel.toggle_preview()
        elif hasattr(current_widget, 'right_browser'):
            browser = current_widget.right_browser
            if hasattr(browser, 'toggle_preview'):
                browser.toggle_preview()

    def _toggle_transfers_tab(self):
        if self.tab_widget.currentIndex() == 0:
            self.tab_widget.setCurrentIndex(1)
        else:
            self.tab_widget.setCurrentIndex(0)

    def _create_separator(self):
        sep = QLabel("│")
        sep.setStyleSheet("QLabel { color: #555555; }")
        return sep

    def _copy_current_path(self, event):
        current_widget = self.tab_widget.currentWidget()
        path = ""
        if hasattr(current_widget, 'right_browser') and current_widget.right_browser:
            creds = get_credentials(current_widget.right_browser.session_id)
            path = creds.get('current_remote_directory', '')
        if path:
            QApplication.clipboard().setText(path)
            self.status_message.setText(f"Copied: {path}")

    def _update_status_path(self):
        current_widget = self.tab_widget.currentWidget()
        if hasattr(current_widget, 'right_browser') and current_widget.right_browser:
            creds = get_credentials(current_widget.right_browser.session_id)
            hostname = creds.get('hostname', '')
            path = creds.get('current_remote_directory', '')
            self.status_path.setText(f"{hostname}:{path}")
            self.status_connection.setText("🟢 Connected")
            self.status_connection.setStyleSheet("QLabel { color: #4a8a4a; font-size: 11px; }")
        elif hasattr(current_widget, 'terminal_widget') and current_widget.terminal_widget:
            creds = get_credentials(current_widget.terminal_widget.session_id)
            hostname = creds.get('hostname', '')
            self.status_path.setText(f"{hostname}")
            self.status_connection.setText("🟢 Connected")
            self.status_connection.setStyleSheet("QLabel { color: #4a8a4a; font-size: 11px; }")
        else:
            self.status_path.setText("No path")
            self.status_connection.setText("⚫ Disconnected")
            self.status_connection.setStyleSheet("QLabel { color: #888888; font-size: 11px; }")

    def _on_tab_changed(self, index):
        """Handle tab change to update status bar"""
        self._update_status_path()

    def _rename_tab_by_index(self, index):
        if index <= 1:
            return
        current_name = self.tab_widget.tabText(index)
        new_name, ok = QInputDialog.getText(
            self, "Rename Tab", "Enter new tab name:", text=current_name
        )
        if ok and new_name:
            self.tab_widget.setTabText(index, new_name)

    def _get_tab_bar_menu_config(self):
        prefs = get_preferences()
        items = prefs.get('context_menu_items', {}).get('tab_bar')
        if not items:
            from sftp_preferences import DEFAULT_PREFERENCES
            items = DEFAULT_PREFERENCES.get('context_menu_items', {}).get('tab_bar', [])
        return items

    def _show_tab_context_menu(self, pos):
        index = self.tab_widget.tabBar().tabAt(pos)
        if index <= 1:
            return

        items = self._get_tab_bar_menu_config()
        menu = QMenu(self)
        action_map = {}

        if is_visible(items, 'rename'):
            rename_action = menu.addAction("Rename Tab")
            action_map['rename'] = rename_action
        if is_visible(items, 'close'):
            close_action = menu.addAction("Close Tab")
            action_map['close'] = close_action
        if is_visible(items, 'close_others'):
            close_others_action = menu.addAction("Close Other Tabs")
            action_map['close_others'] = close_others_action

        action = menu.exec(self.tab_widget.tabBar().mapToGlobal(pos))

        if action == action_map.get('rename'):
            self._rename_tab_by_index(index)
        elif action == action_map.get('close'):
            self.closeTab(index)
        elif action == action_map.get('close_others'):
            for i in range(self.tab_widget.count() - 1, 1, -1):
                if i != index:
                    self.closeTab(i)

    def init_ui(self):
        # Initialize input widgets
        self.container_layout = QVBoxLayout()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(Qt.Password)
        self.port_selector = QLineEdit()

        # Initialize buttons
        self.connect_button = QPushButton("Connect")
        self.connect_button.setStyleSheet(BUTTON_STYLE_DARK)
        self.terminal_button = QPushButton("Terminal")
        self.terminal_button.setToolTip("Open SSH terminal session")
        self.terminal_button.setStyleSheet(BUTTON_STYLE_DARK)
        self.edit_button = QPushButton("Edit Host Data")
        self.edit_button.setStyleSheet(BUTTON_STYLE_DARK)
        self.about_button = QPushButton("ℹ About")
        self.about_button.setToolTip("About SFTP Client")
        self.about_button.setStyleSheet(BUTTON_STYLE_DARK)
        
        prefs = get_preferences()
        self.confirm_exit_checkbox = QCheckBox("Confirm exit")
        self.confirm_exit_checkbox.setToolTip("Confirm before closing application with active transfers")
        self.confirm_exit_checkbox.setChecked(prefs.get_bool("confirm_exit", True))
        self.confirm_exit_checkbox.stateChanged.connect(self._on_confirm_exit_changed)
        
        self.session_restore_combo = QComboBox()
        self.session_restore_combo.setToolTip("Session restore behavior on exit")
        self.session_restore_combo.addItem("Ask on close")
        self.session_restore_combo.addItem("Always restore")
        self.session_restore_combo.addItem("Never restore")
        session_restore_val = prefs.get("session_restore", "ask")
        session_restore_map = {"ask": 0, "always": 1, "never": 2}
        self.session_restore_combo.setCurrentIndex(
            session_restore_map.get(session_restore_val, 0))
        self.session_restore_combo.currentIndexChanged.connect(
            self._on_session_restore_changed)
        
        self.transfers = {}  # Dictionary to store active transfers

        # Initialize hostname combo box
        self.hostname_combo = CustomComboBox(self)  # Pass self as parent
        self.hostname_combo.setEditable(True)
        self.populate_hostname_combo()  # New method to populate the combo box

        # Initialize max SSH connections spin box
        self.ssh_conn_spinbox = QSpinBox()
        self.ssh_conn_spinbox.setMinimum(1)
        self.ssh_conn_spinbox.setMaximum(20)
        self.ssh_conn_spinbox.setValue(prefs.get("max_ssh_connections_per_host", 8))
        self.ssh_conn_spinbox.setToolTip("Maximum concurrent SSH connections per host (servers often limit this)")
        self.ssh_conn_spinbox.valueChanged.connect(self.on_ssh_conn_value_changed)

        # Initialize layouts
        self.init_top_bar_layout()
        self.init_button_layout()

        # Set main layout
        self.top_layout = QVBoxLayout()
        self.top_layout.addLayout(self.top_bar_layout)
        self.top_layout.addWidget(self._toolbar_container)

        # Set up central widget
        self.central_widget = QWidget()
        self.central_widget.setLayout(self.top_layout)
        self.setCentralWidget(self.central_widget)

        # Initialize tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.closeTab)
        self.tab_widget.tabBarDoubleClicked.connect(self._rename_tab_by_index)
        self.tab_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tab_widget.customContextMenuRequested.connect(self._show_tab_context_menu)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        # Additional setup if necessary
        self.setup_hostname_completer()

        # Add the tab widget to the top layout
        # Add the tab widget (takes most of the space)
        self.top_layout.addWidget(self.tab_widget)
        
        # Create enhanced status bar with multiple sections
        status_bar_widget = QWidget()
        status_bar_layout = QHBoxLayout()
        status_bar_layout.setContentsMargins(5, 0, 5, 0)
        status_bar_layout.setSpacing(10)
        
        self.status_connection = QLabel("⚫ Disconnected")
        self.status_connection.setStyleSheet("QLabel { color: #888888; font-size: 11px; }")
        self.status_connection.setToolTip("Connection status")
        status_bar_layout.addWidget(self.status_connection)
        
        status_bar_layout.addWidget(self._create_separator())
        
        self.status_path = QLabel("No path")
        self.status_path.setStyleSheet("QLabel { color: #aaaaaa; font-size: 11px; }")
        self.status_path.setToolTip("Click to copy current path")
        self.status_path.setCursor(Qt.PointingHandCursor)
        self.status_path.mousePressEvent = self._copy_current_path
        self.status_path.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        status_bar_layout.addWidget(self.status_path, stretch=1)
        
        status_bar_layout.addWidget(self._create_separator())
        
        self.status_transfers = QLabel("Transfers: 0")
        self.status_transfers.setStyleSheet("QLabel { color: #aaaaaa; font-size: 11px; }")
        self.status_transfers.setToolTip("Active transfers")
        status_bar_layout.addWidget(self.status_transfers)
        
        status_bar_layout.addWidget(self._create_separator())
        
        self.status_message = QLabel("Ready")
        self.status_message.setStyleSheet("QLabel { color: #7eb8ff; font-size: 11px; }")
        self.status_message.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        status_bar_layout.addWidget(self.status_message, stretch=1)
        
        status_bar_widget.setLayout(status_bar_layout)
        status_bar_widget.setStyleSheet("""
            QWidget {
                background-color: #2a2a2a;
                border-top: 1px solid #555555;
            }
        """)
        status_bar_widget.setMaximumHeight(28)
        self.top_layout.addWidget(status_bar_widget)
        
        self._active_transfers = 0
        
        # Create and add the transfer queue widget as a permanent tab
        self.transfer_queue_widget = TransferQueueWidget()
        self.tab_widget.addTab(self.transfer_queue_widget, "📋 Transfers")
        
        import logging
        logger = logging.getLogger('sftp')
        logger.debug(f"Transfers tab added, index: 0, count: {self.tab_widget.count()}")
        logger.debug(f"TransferQueueWidget created: {self.transfer_queue_widget}")
        logger.debug(f"transfer_list exists: {hasattr(self.transfer_queue_widget, 'transfer_list')}")
        logger.debug(f"text_console exists: {hasattr(self.transfer_queue_widget, 'text_console')}")
        
        # Connect transfer signals for status bar updates and focus
        self.transfer_queue_widget.signal_transfer_started.connect(self._on_transfer_started)
        self.transfer_queue_widget.signal_transfer_completed.connect(self._on_transfer_completed)
        self.transfer_queue_widget.signal_transfer_error.connect(self._on_transfer_error)
        self.transfer_queue_widget.signal_transfer_progress.connect(self._on_transfer_progress)
        self.transfer_queue_widget.signal_overall_progress.connect(self._on_overall_progress)
        
        # Create and add the connections widget as a tab
        self.connections_widget = ConnectionsWidget()
        self.connections_widget.connect_requested.connect(self.handle_connection_request)
        self.connections_widget.open_local_terminal.connect(self.open_local_terminal)
        self.tab_widget.addTab(self.connections_widget, "🔗 Connections")
        
        # Set initial tab to Connections (index 1)
        # Tab structure: 0=Transfers, 1=Connections, 2+=Connection tabs
        self.tab_widget.setCurrentIndex(1)

    def init_top_bar_layout(self):
        self.top_bar_layout = QHBoxLayout()

        self.top_bar_layout.addWidget(self.hostname_combo, 3)
        self.top_bar_layout.addWidget(self.username,       3)
        self.top_bar_layout.addWidget(self.password,       2)

        # --- new widgets for key handling ---------------------------------
        self.top_bar_layout.addWidget(QLabel("Key:"), 0)   # caption
        self.key_combo = QComboBox()
        self.key_combo.setEditable(False)
        self.key_combo.setSizeAdjustPolicy(Qt.ComboBox_AdjustToContents)
        self.top_bar_layout.addWidget(self.key_combo, 2)

        self.key_browse_btn = QToolButton()
        self.key_browse_btn.setText("…")
        self.key_browse_btn.setToolTip("Browse for a private key file")
        self.key_browse_btn.clicked.connect(self.browse_ssh_key)
        self.top_bar_layout.addWidget(self.key_browse_btn, 0)
        # ------------------------------------------------------------------

        self.top_bar_layout.addWidget(self.port_selector, 1)
        self.top_bar_layout.addWidget(QLabel("SSH Conn:"), 0)
        self.top_bar_layout.addWidget(self.ssh_conn_spinbox)

        # keep the existing return-pressed shortcuts
        self.username.returnPressed.connect(self.connect_button_pressed)
        self.password.returnPressed.connect(self.connect_button_pressed)
        self.port_selector.returnPressed.connect(self.connect_button_pressed)

    def init_button_layout(self):
        self._toolbar_container = QWidget()
        self.button_layout = QHBoxLayout()
        self.button_layout.setSpacing(5)
        self.button_layout.setContentsMargins(0, 0, 0, 0)
        self._toolbar_buttons = {}
        
        self._create_toolbar_buttons()
        self._apply_toolbar_config()
        
        self.button_layout.addStretch()
        
        self.customize_btn = QToolButton()
        self.customize_btn.setText("⚙")
        self.customize_btn.setToolTip("Customize toolbar (right-click toolbar for quick toggle)")
        self.customize_btn.setStyleSheet("""
            QToolButton {
                padding: 4px 8px;
                border: 1px solid #555555;
                border-radius: 3px;
                background-color: #444444;
                color: #dddddd;
                font-size: 11px;
            }
            QToolButton:hover {
                background-color: #555555;
            }
        """)
        self.customize_btn.clicked.connect(self._customize_toolbar)
        self.button_layout.addWidget(self.customize_btn)
        
        self.button_layout.addWidget(self.connect_button)
        self.button_layout.addWidget(self.terminal_button)
        self.button_layout.addWidget(self.confirm_exit_checkbox)
        self.button_layout.addWidget(QLabel("Sessions:"))
        self.button_layout.addWidget(self.session_restore_combo)
        self.button_layout.addWidget(self.edit_button)
        self.button_layout.addStretch()
        self.button_layout.addWidget(self.about_button)
        
        self._toolbar_container.setLayout(self.button_layout)
        self._toolbar_container.setContextMenuPolicy(Qt.CustomContextMenu)
        self._toolbar_container.customContextMenuRequested.connect(self._show_toolbar_context_menu)

        self.edit_button.clicked.connect(self._switch_to_connections_tab)
        self.connect_button.clicked.connect(self.connect_button_pressed)
        self.terminal_button.clicked.connect(self.terminal_button_pressed)
        self.about_button.clicked.connect(self.show_about_dialog)
    
    def show_about_dialog(self):
        """Show the About dialog"""
        show_about(self)
    
    def _show_toolbar_context_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2a2a2a;
                color: #dddddd;
                border: 1px solid #555555;
            }
            QMenu::item:selected {
                background-color: #4a6fa5;
            }
        """)
        
        prefs = get_preferences()
        config = prefs.get('toolbar_buttons', [])
        
        if not config:
            from sftp_preferences import DEFAULT_PREFERENCES
            config = DEFAULT_PREFERENCES.get('toolbar_buttons', [])
        
        for btn_config in config:
            btn_id = btn_config.get('id', '')
            text = btn_config.get('text', 'Button')
            visible = btn_config.get('visible', True)
            
            action = menu.addAction(f"{'✓' if visible else '○'} {text}")
            action.setCheckable(True)
            action.setChecked(visible)
            action.triggered.connect(lambda checked, bid=btn_id: self._toggle_button_visibility(bid))
        
        menu.addSeparator()
        customize_action = menu.addAction("⚙ Customize Toolbar...")
        customize_action.triggered.connect(self._customize_toolbar)
        customize_ctx_action = menu.addAction("⚙ Customize Context Menus...")
        customize_ctx_action.triggered.connect(self._customize_context_menus)
        
        menu.exec(self._toolbar_container.mapToGlobal(pos))
    
    def _toggle_button_visibility(self, btn_id):
        prefs = get_preferences()
        config = prefs.get('toolbar_buttons', [])
        
        if not config:
            from sftp_preferences import DEFAULT_PREFERENCES
            config = [b.copy() for b in DEFAULT_PREFERENCES.get('toolbar_buttons', [])]
        else:
            config = [b.copy() for b in config]
        
        for btn_config in config:
            if btn_config.get('id') == btn_id:
                btn_config['visible'] = not btn_config.get('visible', True)
                break
        
        prefs.set('toolbar_buttons', config)
        self._apply_toolbar_config()
    
    def _create_toolbar_buttons(self):
        button_defs = {
            'refresh': ('↻ Refresh', 'Refresh current directory\nShortcut: Ctrl+R', self._toolbar_refresh),
            'upload': ('↑ Upload', 'Upload selected file(s) to remote\nShortcut: Ctrl+U', self._toolbar_upload),
            'download': ('↓ Download', 'Download selected file(s) to local\nShortcut: Ctrl+D', self._toolbar_download),
            'new_folder': ('+ Folder', 'Create new folder\nShortcut: Ctrl+N', self._toolbar_new_folder),
            'delete': ('✕ Delete', 'Delete selected file(s)\nShortcut: Delete', self._toolbar_delete),
            'rename': ('⇄ Rename', 'Rename selected file(s)\nShortcut: F2', self._toolbar_rename),
            'view': ('👁 View', 'View/Edit selected text file\nShortcut: Ctrl+Enter', self._toolbar_view),
        }
        
        for btn_id, (text, tooltip, callback) in button_defs.items():
            btn = QPushButton(text)
            btn.setToolTip(tooltip)
            btn.setFixedWidth(80)
            btn.setStyleSheet(BUTTON_STYLE_DARK)
            btn.clicked.connect(lambda checked, c=callback, b=btn_id: self._handle_toolbar_click(c, b))
            self._toolbar_buttons[btn_id] = btn
    
    def _handle_toolbar_click(self, callback, btn_id):
        try:
            callback()
        except Exception as e:
            pass
    
    def _apply_toolbar_config(self):
        for btn_id, btn in self._toolbar_buttons.items():
            self.button_layout.removeWidget(btn)
            btn.setParent(None)
        
        prefs = get_preferences()
        config = prefs.get('toolbar_buttons', [])
        
        if not config:
            from sftp_preferences import DEFAULT_PREFERENCES
            config = DEFAULT_PREFERENCES.get('toolbar_buttons', [])
        
        insert_index = 0
        for btn_config in config:
            btn_id = btn_config.get('id', '')
            visible = btn_config.get('visible', True)
            
            if btn_id in self._toolbar_buttons:
                btn = self._toolbar_buttons[btn_id]
                btn.setVisible(visible)
                if visible:
                    self.button_layout.insertWidget(insert_index, btn)
                    insert_index += 1
    
    def _customize_toolbar(self):
        prefs = get_preferences()
        current_config = prefs.get('toolbar_buttons', [])
        
        if not current_config:
            from sftp_preferences import DEFAULT_PREFERENCES
            current_config = DEFAULT_PREFERENCES.get('toolbar_buttons', [])
        
        new_config = customize_toolbar(self, current_config)
        
        if new_config is not None:
            prefs.set('toolbar_buttons', new_config)
            self._apply_toolbar_config()

    def _customize_context_menus(self):
        prefs = get_preferences()
        current = prefs.get('context_menu_items')
        if not current:
            from sftp_preferences import DEFAULT_PREFERENCES
            current = DEFAULT_PREFERENCES.get('context_menu_items', {})
        configs = {k: [item.copy() for item in v] for k, v in current.items()}
        result = customize_context_menus(self, configs)
        if result is not None:
            prefs.set('context_menu_items', result)

    def setup_hostname_completer(self):
        # Make sure self.hostnames is initialized and filled with data
        self.hostname_completer = QCompleter(self.hostnames)
        self.hostname_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.hostname_completer.setCompletionMode(Qt.Completer_PopupCompletion)
        self.hostname_combo.setCompleter(self.hostname_completer)

        # Connect signals for hostname combo box
        self.hostname_combo.currentIndexChanged.connect(self.hostname_changed)  # Ensure this slot is implemented
        self.hostname_combo.activated.connect(self.hostname_changed)
        self.hostname_combo.editingFinished.connect(self.hostname_changed)        

    def populate_hostname_combo(self):
        self.hostname_combo.clear()
        self.hostnames = get_site_names()
        for hostname in self.hostnames:
            self.hostname_combo.addItem(hostname)

    def browse_ssh_key(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select SSH private-key file",
            os.path.expanduser("~/.ssh"),
            "SSH key (*.key *.pem *.ppk *.pub);;All files (*)"
        )
        if path:
            if not os.path.exists(path):
                QMessageBox.warning(self, "Key Error", f"Selected key file does not exist: {path}")
                return
            if self.key_combo.findData(path) == -1:
                self.key_combo.addItem(os.path.basename(path), path)
            self.key_combo.setCurrentIndex(self.key_combo.findData(path))
            self.key_combo.addItem(os.path.basename(path), path)
            self.key_combo.setCurrentIndex(self.key_combo.findData(path))

    def prepare_container_widget(self):
        container_widget = QWidget()
        self.file_browser_panel = FileBrowserPanel(self.session_id, auto_initialize=False)
        
        self.transfer_queue_widget.add_observee(self.file_browser_panel.left_browser)
        self.transfer_queue_widget.add_observee(self.file_browser_panel.right_browser)
        
        self.file_browser_panel.left_browser.transfer_queue_widget = self.transfer_queue_widget
        self.file_browser_panel.right_browser.transfer_queue_widget = self.transfer_queue_widget

        self.file_browser_panel.message.connect(self.update_console)
        self.file_browser_panel.transfer_started.connect(self._switch_to_transfers_tab)
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.file_browser_panel)
        container_widget.left_browser = self.file_browser_panel.left_browser
        container_widget.right_browser = self.file_browser_panel.right_browser
        container_widget.file_browser_panel = self.file_browser_panel
        container_widget.session_id = self.session_id
        container_widget.is_terminal = False
        container_widget.get_active_browser = self.file_browser_panel.get_active_browser
        container_widget.setLayout(main_layout)
        self.message_signal.emit("Connection successful")
        return container_widget

    def prepare_terminal_widget(self, hostname, username, password, port, key, ssh_commands=""):
        self.session_id = create_random_integer()
        container_widget = QWidget()
        self.terminal_widget = SSHTerminalWidget(self.session_id)
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.terminal_widget)
        container_widget.setLayout(main_layout)
        container_widget.terminal_widget = self.terminal_widget
        container_widget.is_terminal = True
        container_widget.session_id = self.session_id
        tab_title = f"Terminal: {hostname}"
        new_tab_index = self.tab_widget.addTab(container_widget, tab_title)
        self.tab_widget.setCurrentIndex(new_tab_index)
        self.terminal_widget.connect_ssh(hostname, username, password, port, key, ssh_commands)
        self.message_signal.emit(f"Terminal session opened to {hostname}")

    def closeTab(self, index):
        # Don't close the permanent tabs (transfers at 0, connections at 1)
        if index <= 1:
            return
            
        # Close the tab at the given index
        widget_to_remove = self.tab_widget.widget(index)
        if not widget_to_remove:
            return
        
        # Store session_id for cleanup before removing the widget
        session_id = getattr(widget_to_remove, 'session_id', None)
        
        # Remove observers before closing
        if hasattr(widget_to_remove, 'left_browser'):
            self.transfer_queue_widget.remove_observee(widget_to_remove.left_browser)
        if hasattr(widget_to_remove, 'right_browser'):
            self.transfer_queue_widget.remove_observee(widget_to_remove.right_browser)
        
        # Close terminal session if this is a terminal tab
        if hasattr(widget_to_remove, 'is_terminal') and widget_to_remove.is_terminal:
            # SSH terminal
            if hasattr(widget_to_remove, 'terminal_widget') and widget_to_remove.terminal_widget:
                try:
                    widget_to_remove.terminal_widget.disconnect_ssh()
                except Exception as e:
                    logger.debug(f"Error disconnecting SSH terminal: {e}")
            # Local terminal
            if hasattr(widget_to_remove, 'local_terminal_widget') and widget_to_remove.local_terminal_widget:
                try:
                    widget_to_remove.local_terminal_widget.close()
                except Exception as e:
                    logger.debug(f"Error closing local terminal: {e}")
        
        self.tab_widget.removeTab(index)

        # Close SFTP connection
        if hasattr(widget_to_remove, 'right_browser') and widget_to_remove.right_browser:
            try:
                widget_to_remove.right_browser.close_sftp_connection()
            except Exception as e:
                logger.debug(f"Error closing SFTP connection: {e}")

        # Delete the widget if necessary
        try:
            widget_to_remove.deleteLater()
        except Exception as e:
            logger.debug(f"Error deleting widget: {e}")
        
        # Clean up session and credentials
        if session_id:
            try:
                get_session_manager().remove_session(str(session_id))
            except Exception as e:
                pass
            try:
                del_credentials(session_id)
            except Exception as e:
                pass

    def add_tab(self, session_id, widget):
        self.session_id = session_id

        self.title = self.get_session_title(self.session_id)

        # Use the provided widget instead of creating a new one
        # This prevents duplicate creation and session_id issues
        container_widget = widget

        tab_title = self.get_session_title(session_id)
        new_tab_index = self.tab_widget.addTab(container_widget, tab_title)

        self.tab_widget.setCurrentIndex(new_tab_index)

        self.log_connection_success()

    def get_session_title(self, session_id):
        self.session_id = session_id
        creds = get_credentials(self.session_id)

        try:
            title = creds.get('hostname') if creds else "Unknown Hostname"
        except KeyError:
            title = "Unknown Hostname"
        return title

    def log_connection_success(self):
        self.status_message.setText("Connected successfully")

    def hostname_changed(self):
        self.current_hostname = self.hostname_combo.currentText().strip()

        # ------------------------------------------------------------------
        # Clear everything first so we never show stale data
        # ------------------------------------------------------------------
        self.username.clear()
        self.password.clear()
        self.port_selector.clear()
        self.key_combo.clear()
        self.key_combo.addItem('<none>', None)

        site = get_site_data(self.current_hostname)
        if site:
            username = site.get("username", "")
            password = site.get("password", "")
            port = site.get("port", 22)
            key_data = site.get("key", "")

            self.username.setText(username)
            self.password.setText(password)
            self.port_selector.setText(str(port))

            # Populate the key combo
            if key_data:
                try:
                    self.key_combo.addItem(os.path.basename(key_data), key_data)
                except (TypeError, AttributeError) as e:
                    pass

            # If we actually added any keys, select the first one
            # if key_paths and self.key_combo.count() > 1:  # More than just '<none>'
            #    self.key_combo.setCurrentIndex(1)  # Select first actual key, not '<none>'

    def on_ssh_conn_value_changed(self, value):
        prefs = get_preferences()
        prefs.set("max_ssh_connections_per_host", value)
        self.update_console(f"Max SSH connections per host set to {value}")
        
    def update_console(self, message):
        # Update status bar with latest message
        # Truncate long messages based on window width to prevent resizing
        # Rough estimate: each character ~7px, reserve 200px for other status bar elements
        window_width = self.width() if hasattr(self, 'width') and self.width() > 0 else 800
        max_chars = max(50, min(200, (window_width - 200) // 7))
        if len(message) > max_chars:
            message = message[:max_chars] + "..."
        self.status_message.setText(message)
        # Reset to normal style (in case it was showing an error)
        self.status_message.setStyleSheet("""
            QLabel {
                background-color: #2a2a2a;
                color: #aaaaaa;
                padding: 5px 10px;
                border-top: 1px solid #555555;
                font-size: 12px;
            }
        """)

    def update_completer(self):
        self.hostnames = get_site_names()
        self.hostname_combo.clear()
        self.hostname_combo.addItems(self.hostnames)

        # Reinitialize the completer with the updated list
        self.hostname_completer = QCompleter(self.hostnames)
        self.hostname_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.hostname_completer.setCompletionMode(Qt.Completer_PopupCompletion)
        self.hostname_combo.setCompleter(self.hostname_completer)

    def _switch_to_connections_tab(self):
        """Switch to the Connections tab"""
        self.tab_widget.setCurrentIndex(1)  # Index 1 is Connections tab
    
    def _switch_to_transfers_tab(self):
        """Switch to the Transfers tab if preference is enabled"""
        prefs = get_preferences()
        if prefs.get_bool("focus_transfers_on_start", True):
            self.tab_widget.setCurrentIndex(0)  # Index 0 is Transfers tab
    
    def _on_transfer_started(self, count, message):
        """Handle transfer started event"""
        prefs = get_preferences()
        
        self._active_transfers = count
        self.status_transfers.setText(f"Transfers: {count}")
        self.status_message.setText(f"Transfer started: {message}")
        
        if prefs.get_bool("focus_transfers_on_start", True):
            self.tab_widget.setCurrentIndex(0)
    
    def _on_transfer_completed(self, count, message):
        """Handle transfer completed event"""
        self._active_transfers = count
        self.status_transfers.setText(f"Transfers: {count}")
        self.status_message.setText("Transfer completed")
        self.status_message.setStyleSheet("QLabel { color: #7eb8ff; font-size: 11px; }")
        self._update_status_path()
    
    def _on_transfer_error(self, count, message):
        """Handle transfer error event"""
        prefs = get_preferences()
        
        self._active_transfers = count
        self.status_transfers.setText(f"Transfers: {count}")
        self.status_message.setText(f"Transfer failed: {message}")
        self.status_message.setStyleSheet("QLabel { color: #ff6b6b; font-size: 11px; }")
        
        # Focus on transfers tab so user can see the error
        if prefs.get_bool("focus_transfers_on_start", True):
            self.tab_widget.setCurrentIndex(0)
    
    def _on_transfer_progress(self, transfer_id, percent, speed_bps, eta_sec):
        """Handle transfer progress updates"""
        speed_kbps = speed_bps / 1024 if speed_bps else 0
        if speed_kbps >= 1024:
            speed_str = f"{speed_kbps/1024:.1f} MB/s"
        else:
            speed_str = f"{speed_kbps:.0f} KB/s"
        
        eta_str = ""
        if eta_sec and eta_sec > 0:
            if eta_sec < 60:
                eta_str = f" - {int(eta_sec)}s remaining"
            elif eta_sec < 3600:
                eta_str = f" - {int(eta_sec/60)}m remaining"
            else:
                eta_str = f" - {int(eta_sec/3600)}h remaining"
        
        self.status_message.setText(f"Transfer: {percent}% {speed_str}{eta_str}")
        self.status_message.setStyleSheet("QLabel { color: #a0a0a0; font-size: 11px; }")
    
    def _on_overall_progress(self, percent, total_speed, eta_seconds, bytes_done, bytes_total):
        """Handle overall aggregate progress updates for status bar"""
        if percent <= 0 and total_speed <= 0:
            return

        def humanize(b):
            if b >= 1024**3:
                return f"{b / 1024**3:.1f} GB"
            elif b >= 1024**2:
                return f"{b / 1024**2:.1f} MB"
            elif b >= 1024:
                return f"{b / 1024:.1f} KB"
            else:
                return f"{b} B"

        parts = [f"{percent}%"]
        if bytes_total > 0:
            parts.append(f"{humanize(bytes_done)}/{humanize(bytes_total)}")
        if total_speed > 0:
            speed_kbps = total_speed / 1024
            if speed_kbps >= 1024:
                parts.append(f"{speed_kbps/1024:.1f} MB/s")
            else:
                parts.append(f"{speed_kbps:.0f} KB/s")
        if eta_seconds > 0:
            if eta_seconds < 60:
                parts.append(f"{int(eta_seconds)}s remaining")
            elif eta_seconds < 3600:
                parts.append(f"{int(eta_seconds/60)}m remaining")
            else:
                parts.append(f"{int(eta_seconds/3600)}h remaining")

        self.status_message.setText(" • ".join(parts))
        self.status_message.setStyleSheet("QLabel { color: #a0a0a0; font-size: 11px; }")
    
    def _switch_to_connection_tab(self, tab_index):
        """Switch to a specific connection tab"""
        if tab_index < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(tab_index)
    
    def _get_active_browser(self):
        """Get the currently active file browser (local or remote based on last click)"""
        current_index = self.tab_widget.currentIndex()
        if current_index < 2:  # Transfers or Connections tab
            return None
        try:
            widget = self.tab_widget.widget(current_index)
            # Check if widget has get_active_browser method (FileBrowserPanel)
            if hasattr(widget, 'get_active_browser'):
                return widget.get_active_browser()
            # Fallback for widgets with just right_browser
            if hasattr(widget, 'right_browser'):
                return widget.right_browser
        except (AttributeError, RuntimeError) as e:
            pass
        return None
    
    def _toolbar_refresh(self):
        """Handle Refresh button click"""
        browser = self._get_active_browser()
        if browser:
            browser.refresh_files()
        else:
            QMessageBox.information(self, "Refresh", "Please open a connection first.")
    
    def _toolbar_upload(self):
        """Handle Upload button click - uploads from local to remote"""
        browser = self._get_active_browser()
        if browser:
            is_remote = browser.is_remote_browser() if hasattr(browser, 'is_remote_browser') else False
            if not is_remote:
                # Local browser - call upload_download to upload to remote
                browser.upload_download()
            else:
                QMessageBox.information(self, "Upload", "Please select a file in the local browser first.")
    
    def _toolbar_download(self):
        """Handle Download button click - downloads from remote to local"""
        browser = self._get_active_browser()
        if browser:
            is_remote = browser.is_remote_browser() if hasattr(browser, 'is_remote_browser') else False
            if is_remote:
                # Remote browser - call upload_download to download to local
                browser.upload_download()
            else:
                QMessageBox.information(self, "Download", "Please select a file in the remote browser first.")
    
    def _toolbar_new_folder(self):
        """Handle New Folder button click"""
        browser = self._get_active_browser()
        if browser:
            browser.prompt_and_create_directory()
        else:
            QMessageBox.information(self, "New Folder", "Please open a connection first.")
    
    def _toolbar_delete(self):
        """Handle Delete button click - works for both local and remote browsers"""
        browser = self._get_active_browser()
        if browser:
            try:
                browser.remove_directory_with_prompt()
            except Exception as e:
                pass
                QMessageBox.warning(self, "Delete Error", f"Error deleting: {e}")
        else:
            QMessageBox.information(self, "Delete", "Please open a connection first.")

    def _toolbar_rename(self):
        """Handle Rename button click - works for both local and remote browsers"""
        from PySide6.QtWidgets import QInputDialog
        browser = self._get_active_browser()
        if browser:
            current_browser = browser.table
            if current_browser is not None:
                # Check selected indexes first (right-click selection)
                indexes = current_browser.selectedIndexes()
                if not indexes:
                    # Fall back to current index (keyboard navigation)
                    indexes = [current_browser.currentIndex()]
                
                if indexes and indexes[0].isValid():
                    current_index = indexes[0]
                    filename_index = current_browser.model().index(current_index.row(), 0)
                    selected_item = current_browser.model().data(filename_index, Qt.DisplayRole)
                    
                    # Remove type prefix if present (handles both text and emoji prefixes)
                    prefixes = ['[DIR] ', '[FILE] ', '[LINK] ', '📁 ', '📄 ', '🔗 ']
                    for prefix in prefixes:
                        if selected_item.startswith(prefix):
                            selected_item = selected_item[len(prefix):]
                            break
                    
                    new_name, ok = QInputDialog.getText(
                        self, "Rename", 
                        f"Enter new name for '{selected_item}':",
                        text=selected_item
                    )
                    if ok and new_name and new_name != selected_item:
                        creds = get_credentials(browser.session_id)
                        
                        if browser.is_remote_browser():
                            base = creds.get('current_remote_directory', '.').rstrip('/')
                            remote_path = (base + '/' + selected_item) if base else '/' + selected_item
                            browser.sftp_rename(remote_path, new_name)
                        else:
                            local_path = os.path.join(creds.get('current_local_directory', '.'), selected_item)
                            browser.rename(local_path, new_name)
                    elif ok and new_name == selected_item:
                        QMessageBox.information(self, "Rename", "New name is the same as current name.")
                else:
                    QMessageBox.information(self, "Rename", "Please select a file or folder to rename.")
            else:
                QMessageBox.information(self, "Rename", "No file browser available.")
        else:
            QMessageBox.information(self, "Rename", "Please open a connection first.")
    
    def _toolbar_view(self):
        """Handle View button click - view/edit selected text file"""
        browser = self._get_active_browser()
        if browser:
            browser.view_edit_file()
        else:
            QMessageBox.information(self, "View", "Please open a connection first.")
    
    def handle_connection_request(self, connection_data):
        """Handle connection request from Connections widget"""
        try:
            self._handle_connection_request_impl(connection_data)
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", f"Failed to connect: {str(e)}")
            self.message_signal.emit(f"Connection failed: {str(e)}")

    def _handle_connection_request_impl(self, connection_data):
        hostname = connection_data.get("hostname")
        username = connection_data.get("username")
        password = connection_data.get("password")
        port = connection_data.get("port", 22)
        key = connection_data.get("key", "None")
        connection_type = connection_data.get("connection_type", "SFTP Browser")
        initial_remote_dir = connection_data.get("initial_remote_dir", "")
        initial_local_dir = connection_data.get("initial_local_dir", "")
        ssh_commands = connection_data.get("ssh_commands", "")
        follow_symlinks = connection_data.get("follow_symlinks", False)
        self._pending_max_connections = connection_data.get("max_connections", 0)
        
        from sftp_preferences import get_preferences
        get_preferences().set_bool("follow_symlinks", bool(follow_symlinks))

        def store_initial_dirs(host_data):
            if initial_remote_dir:
                host_data.setdefault("initial_remote_dir", {})[hostname] = initial_remote_dir
            if initial_local_dir:
                host_data.setdefault("initial_local_dir", {})[hostname] = initial_local_dir

        update_connection_data(store_initial_dirs)
        
        # Update UI fields
        self.hostname_combo.setCurrentText(hostname)
        self.username.setText(username)
        self.password.setText(password)
        self.port_selector.setText(str(port))
        if key:
            self.key_combo.setCurrentText(key)
        
        # Switch to connection form tab
        self.tab_widget.setCurrentIndex(2)  # Index 2 is the first connection tab
        
        # Perform the connection based on type
        self.message_signal.emit(f"Connecting to {hostname} from Connections...")
        
        if connection_type == "SSH Terminal":
            self.prepare_terminal_widget(
                hostname, username, password, port, 
                key if key != "None" else None,
                ssh_commands
            )
        else:
            self.connect(hostname=hostname, username=username, password=password, port=port, key=key)

    def connect_button_pressed(self):
        try:
            session_id = self.connect()
            if session_id is None:
                return
        except (ConnectionError, OSError, ValueError) as e:
            error_message = f"Connection failed: {str(e)}"
            QMessageBox.critical(self, "Connection Error", error_message)
            self.update_console(error_message)

    def terminal_button_pressed(self):
        """Handle Terminal button click - opens SSH terminal session"""
        try:
            hostname = self.hostname_combo.currentText().strip()
            username = self.username.text().strip()
            password = self.password.text()
            port_text = self.port_selector.text().strip()
            port = int(port_text) if port_text else 22
            key = self.key_combo.currentText() if self.key_combo.currentText() else None
            if key == "<none>":
                key = None

            if not hostname:
                QMessageBox.warning(self, "Missing Hostname", "Please enter a hostname")
                return

            if not username:
                QMessageBox.warning(self, "Missing Username", "Please enter a username")
                return

            if not password and not key:
                QMessageBox.warning(self, "Missing Credentials", "Please enter a password or select an SSH key")
                return

            self.message_signal.emit(f"Opening terminal session to {hostname}...")

            ssh_commands = ""
            site = get_site_data(hostname)
            if site:
                ssh_commands = site.get("ssh_commands", "")

            self.prepare_terminal_widget(hostname, username, password, port, key, ssh_commands)

        except (ConnectionError, OSError, ValueError) as e:
            error_message = f"Connection failed: {str(e)}"
            self.update_console(error_message)
            QMessageBox.critical(self, "Connection Error", error_message)

    def open_local_terminal(self):
        """Handle Local Terminal button click - opens local shell tab"""
        container_widget = QWidget()
        container_widget.is_terminal = True
        
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        container_widget.setLayout(layout)
        
        self.local_terminal_widget = LocalTerminalWidget()
        layout.addWidget(self.local_terminal_widget)
        
        container_widget.local_terminal_widget = self.local_terminal_widget
        
        tab_title = "💻 Local Terminal"
        new_tab_index = self.tab_widget.addTab(container_widget, tab_title)
        self.tab_widget.setCurrentIndex(new_tab_index)
        
        self.message_signal.emit("Local terminal opened")

    def display_error(self, transfer_id, message):
        # Display error in a message box
        QMessageBox.critical(self, "Error", f"Transfer {transfer_id}: {message}")
        
        # Display the error in the status bar
        self.status_message.setText(f"Error in transfer {transfer_id}: {message}")
        self.status_message.setStyleSheet("""
            QLabel {
                background-color: #5a1a1a;
                color: #ff6b6b;
                padding: 5px 10px;
                border-top: 1px solid #ff6b6b;
                font-size: 12px;
            }
        """)

    def _load_private_key(self, path):
        """
        Return a Paramiko PKey object for the file path currently selected in
        self.key_combo, or None if the combo is '<none>'.
        """
        if not path:                   # covers None, '', or anything falsy
            return None

        try:
            # ic(path)
            # Auto-detect key type (RSA, ECDSA, Ed25519…)
            return paramiko.PKey.from_path(path)
        except paramiko.PasswordRequiredException:
            # Prompt the user if the key is encrypted, or handle differently
            passphrase, ok = QInputDialog.getText(
                self, "Passphrase", f"Passphrase for {os.path.basename(path)}:",
                Qt.Password)
            if ok and passphrase:
                return paramiko.PKey.from_private_key_file(path, password=passphrase)
        except (OSError, IOError, RuntimeError) as e:
            QMessageBox.critical(self, "Key error", str(e))
        return None

    def connect(self, hostname="localhost", username="guest", password="guest", port="22", key=None):
        if self._connecting:
            self.message_signal.emit("A connection is already in progress. Please wait.")
            return None
        self._connecting = True
        try:
            self.temp_hostname = self.hostname_combo.currentText() if hostname == "localhost" and self.hostname_combo.currentText() else hostname

            self.temp_username = self.username.text() if username == "guest" and self.username.text() else username
            self.temp_password = self.password.text() if password == "guest" and self.password.text() else password
            self.temp_port = self.port_selector.text() or port or "22"

            # Handle key selection properly
            current_key_data = self.key_combo.currentData()
            if current_key_data:
                self.temp_key = current_key_data
                # ic(self.temp_key)
            else:
                self.temp_key = None
                # ic("No key selected")

            self.message_signal.emit(f"Using hostname: {self.temp_hostname}, username: {self.temp_username}, port: {self.temp_port}, key: {self.temp_key}")

            if not self.temp_hostname:
                raise ValueError("Hostname is required")
            if not self.temp_username:
                raise ValueError("Username is required")
            if not self.temp_password and not self.temp_key:
                raise ValueError("Either password or SSH key is required")
            try:
                self.temp_port = int(self.temp_port)  # Validate port is a number
                # Validate port range (1-65535)
                if not (1 <= self.temp_port <= 65535):
                    raise ValueError(f"Port must be between 1 and 65535, got {self.temp_port}")
            except ValueError as e:
                if "between 1 and 65535" in str(e):
                    raise
                raise ValueError("Port must be a valid number")

            # Set credentials synchronously
            self.message_signal.emit("Setting credentials...")
            self.set_credentials_async()

            # Configure connection pool limits
            from sftp_connection_pool import get_connection_pool
            from sftp_preferences import get_preferences
            pool = get_connection_pool()
            prefs = get_preferences()
            site_limit = getattr(self, '_pending_max_connections', 0) or 0
            max_conns = site_limit if site_limit > 0 else prefs.get("max_ssh_connections_per_host", 8)
            pool.set_max_connections(self.temp_hostname, self.temp_port, self.temp_username, max_conns)
            self._pending_max_connections = 0

            # Pre-load SSH key on UI thread (may show passphrase dialog)
            pkey = None
            if self.temp_key:
                self.message_signal.emit("Loading SSH key...")
                pkey = self._load_private_key(self.temp_key)
                if pkey is None:
                    raise ValueError("Failed to load SSH key")

            # Test connection in background with progress dialog
            self.message_signal.emit("Testing SFTP connection...")
            known_hosts_path = get_known_hosts_path()
            home_dir = self._test_connection_with_progress(
                self.temp_hostname, self.temp_port,
                self.temp_username, self.temp_password,
                pkey, known_hosts_path
            )
            if home_dir is None:
                return None
            self.message_signal.emit("Connection test passed!")

            self.message_signal.emit(f"Successfully connected to {self.temp_hostname}")

            # Set the home directory from the connection test to avoid another SSH connection
            # This must be done BEFORE prepare_container_widget() calls initialize_model()
            set_credentials(self.session_id, 'current_remote_directory', home_dir)
            self.message_signal.emit(f"Remote home directory: {home_dir}")

            # Check for and navigate to initial directories AFTER setting home directory
            # This ensures the credentials are set correctly before initialize_model() runs
            self.navigate_to_initial_directories()

            # Create a new QWidget as a container for both the file table and the output console
            self.container_widget = self.prepare_container_widget()

            # Add tab synchronously
            self.add_tab(self.session_id, self.container_widget)

            # NOW initialize the remote browser - connection is fully ready
            self.file_browser_panel.initialize()

            if hasattr(self, 'transfer_queue_widget') and self.transfer_queue_widget:
                self.transfer_queue_widget.register_active_session(self.temp_hostname, self.session_id)

            self.message_signal.emit("Saving connection data...")
            self.save_connection_data_async()

            return self.session_id
        except ValueError as ve:
            error_message = str(ve)
            QMessageBox.critical(self, "Connection Error", error_message)
            self.message_signal.emit(f"Connection failed: {error_message}")
        except Exception as e:
            error_message = f"Unexpected error: {str(e)}"
            QMessageBox.critical(self, "Connection Error", error_message)
            self.message_signal.emit(f"Connection failed: {error_message}")
        finally:
            self._connecting = False
        return None

    def _test_connection_with_progress(self, hostname, port, username,
                                       password, pkey, known_hosts_path):
        progress = QProgressDialog(
            f"Connecting to {hostname}:{port}...", "Cancel", 0, 0, self)
        progress.setWindowTitle("Connecting")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setMinimumWidth(380)
        progress.show()
        QApplication.processEvents()

        worker = ConnectionTestWorker(
            hostname, port, username, password, pkey, known_hosts_path)

        result = {'home_dir': None, 'error': None}
        cancelled = [False]
        loop = QEventLoop(self)
        self._connection_event_loop = loop

        def on_step(msg):
            progress.setLabelText(msg)

        def on_success(home_dir):
            result['home_dir'] = home_dir
            loop.quit()

        def on_error(msg):
            result['error'] = msg
            loop.quit()

        def on_prompt_unknown_host(host, key_type, fingerprint):
            msg = (
                f"Unknown host: {host}\n\n"
                f"Key type: {key_type}\n"
                f"Fingerprint: {fingerprint}\n\n"
                "Do you want to trust this host?")
            reply = QMessageBox.question(
                self, "Unknown Host Key", msg,
                Qt.MsgBtn_Yes | Qt.MsgBtn_No, Qt.MsgBtn_No)
            worker.resolve_prompt(reply == Qt.MsgBtn_Yes)

        def on_prompt_bad_host_key(host, fingerprint):
            msg = (
                f"Host key mismatch for {host}\n\n"
                "The server's host key has changed. "
                "This could indicate:\n"
                "  \u2022 The server was rebuilt\n"
                "  \u2022 A man-in-the-middle attack\n\n"
                f"Fingerprint: {fingerprint}\n\n"
                "Update the host key and continue?")
            reply = QMessageBox.question(
                self, "Host Key Changed", msg,
                Qt.MsgBtn_Yes | Qt.MsgBtn_No, Qt.MsgBtn_No)
            worker.resolve_prompt(reply == Qt.MsgBtn_Yes)

        def on_cancel():
            cancelled[0] = True
            worker.cancel()
            loop.quit()

        def on_timeout():
            cancelled[0] = True
            worker.cancel()
            result['error'] = "Connection timed out."
            loop.quit()

        worker.signals.step.connect(on_step)
        worker.signals.success.connect(on_success)
        worker.signals.error.connect(on_error)
        worker.signals.prompt_unknown_host.connect(on_prompt_unknown_host)
        worker.signals.prompt_bad_host_key.connect(on_prompt_bad_host_key)
        progress.canceled.connect(on_cancel)

        timeout_timer = QTimer(self)
        timeout_timer.setSingleShot(True)
        timeout_timer.timeout.connect(on_timeout)
        timeout_timer.start(90000)

        QThreadPool.globalInstance().start(worker)
        loop.exec()

        timeout_timer.stop()
        del self._connection_event_loop

        home_dir = result['home_dir']
        error_msg = result['error']
        was_cancelled = cancelled[0]

        progress.canceled.disconnect(on_cancel)
        progress.close()

        if was_cancelled and home_dir is None:
            self.message_signal.emit("Connection cancelled")
            return None

        if error_msg:
            self.message_signal.emit(
                f"Connection test failed: {error_msg}")
            QMessageBox.critical(
                self, "Connection Error", error_msg)
            return None

        return home_dir

    def set_credentials_async(self):
            set_credentials(self.session_id, 'hostname', self.temp_hostname)
            set_credentials(self.session_id, 'username', self.temp_username)
            set_credentials(self.session_id, 'password', self.temp_password)
            set_credentials(self.session_id, 'port', int(self.temp_port))
            set_credentials(self.session_id, 'current_local_directory', get_home_directory())
            set_credentials(self.session_id, 'current_remote_directory', '.')
            set_credentials(self.session_id, "key", self.temp_key)
            # set_credentials(self.session_id, "keyfile", self.key_combo.currentData())

    def save_connection_data_async(self):
        try:
            def updater(host_data):
                host_data["hostnames"][self.temp_hostname] = self.temp_hostname
                host_data["usernames"][self.temp_hostname] = self.temp_username
                host_data["passwords"][self.temp_hostname] = self.temp_password
                host_data["ports"][self.temp_hostname] = int(self.temp_port)
                host_data["key"][self.temp_hostname] = self.temp_key

            if not update_connection_data(updater):
                self.message_signal.emit("Failed to save connection data")
            else:
                self.message_signal.emit("Connection data saved successfully")

            self.update_completer()
        except (OSError, RuntimeError) as e:
            self.message_signal.emit(f"Error saving connection data: {str(e)}")

    def navigate_to_initial_directories(self):
        """Navigate to initial directories if configured for the current hostname"""
        try:
            restore_remote = getattr(self, '_restore_remote_dir', None)
            restore_local = getattr(self, '_restore_local_dir', None)
            self._restore_remote_dir = None
            self._restore_local_dir = None

            if restore_remote or restore_local:
                if restore_remote:
                    set_credentials(self.session_id, 'current_remote_directory', restore_remote)
                    self.message_signal.emit(f"Restoring remote directory: {restore_remote}")
                if restore_local:
                    set_credentials(self.session_id, 'current_local_directory', restore_local)
                    self.message_signal.emit(f"Restoring local directory: {restore_local}")
                    try:
                        os.chdir(restore_local)
                    except (OSError, IOError, RuntimeError) as e:
                        self.message_signal.emit(f"Warning: Could not change to local directory {restore_local}: {e}")
                return

            site = get_site_data(self.temp_hostname)
            if not site:
                return
            initial_remote = site.get("initial_remote_dir", "")
            initial_local = site.get("initial_local_dir", "")
            
            if initial_remote:
                self.message_signal.emit(f"Navigating to initial remote directory: {initial_remote}")
                set_credentials(self.session_id, 'current_remote_directory', initial_remote)
            
            if initial_local:
                self.message_signal.emit(f"Navigating to initial local directory: {initial_local}")
                set_credentials(self.session_id, 'current_local_directory', initial_local)
                set_credentials(self.session_id, 'current_local_directory', initial_local)
                try:
                    os.chdir(initial_local)
                except (OSError, IOError, RuntimeError) as e:
                    self.message_signal.emit(f"Warning: Could not change to local directory {initial_local}: {e}")
        except (OSError, IOError, RuntimeError) as e:
            self.message_signal.emit(f"Warning: Could not navigate to initial directories: {e}")

    def cleanup(self):
        if hasattr(self, '_cleanup_performed') and self._cleanup_performed:
            return
        self._cleanup_performed = True

        try:
            if hasattr(self, 'transfer_queue_widget'):
                self.transfer_queue_widget.cleanup()
            self.close_sftp_connections()
        except (OSError, RuntimeError) as e:
            pass

    # Remove the perform_next_cleanup_task method as it's no longer needed

    def close_sftp_connections(self):
        """Close all SFTP connections for each tab"""
        if not hasattr(self, 'tab_widget'):
            return
            
        # Collect widgets first to avoid iterator invalidation
        widgets = []
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if widget and hasattr(widget, 'right_browser'):
                widgets.append(widget.right_browser)
        
        # Close each connection
        for browser in widgets:
            try:
                if hasattr(browser, 'close_sftp_connection'):
                    browser.close_sftp_connection()
            except (OSError, IOError, RuntimeError) as e:
                pass

    def _on_confirm_exit_changed(self, state):
        """Handle confirm exit checkbox change"""
        prefs = get_preferences()
        prefs.set_bool("confirm_exit", bool(state))

    def _on_session_restore_changed(self, index):
        prefs = get_preferences()
        values = ["ask", "always", "never"]
        if 0 <= index < len(values):
            prefs.set("session_restore", values[index])

    def _get_open_sftp_sessions(self):
        sessions = []
        for i in range(2, self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if not widget:
                continue
            if getattr(widget, 'is_terminal', False):
                continue
            session_id = getattr(widget, 'session_id', None)
            if not session_id:
                continue
            creds = get_credentials(session_id)
            if not creds or not creds.get('hostname'):
                continue
            tab_title = self.tab_widget.tabText(i)
            sessions.append({
                'hostname': creds.get('hostname', ''),
                'username': creds.get('username', ''),
                'password': creds.get('password', ''),
                'port': creds.get('port', 22),
                'key': creds.get('key', '') or '',
                'current_remote_directory': creds.get('current_remote_directory', ''),
                'current_local_directory': creds.get('current_local_directory', ''),
                'tab_title': tab_title,
            })
        return sessions

    def save_open_sessions(self, sessions):
        if not sessions:
            return
        try:
            from sftp_hostdataeditor import cipher_suite
            from sftp_platform import secure_file_permissions

            sessions_to_save = []
            for s in sessions:
                entry = dict(s)
                if entry.get('password') and cipher_suite:
                    try:
                        entry['password'] = cipher_suite.encrypt(
                            entry['password'].encode()).decode()
                    except Exception:
                        entry['password'] = ''
                sessions_to_save.append(entry)

            filepath = get_sessions_path()
            with open(filepath, 'w') as f:
                json.dump({"sessions": sessions_to_save}, f, indent=2)
            secure_file_permissions(filepath)
            logger.info(f"Saved {len(sessions_to_save)} session(s) to {filepath}")
        except Exception as e:
            logger.error(f"Failed to save sessions: {e}")

    @staticmethod
    def _load_sessions_file():
        try:
            filepath = get_sessions_path()
            if not os.path.exists(filepath):
                return []
            with open(filepath, 'r') as f:
                data = json.load(f)
            from sftp_hostdataeditor import cipher_suite
            sessions = data.get("sessions", [])
            for s in sessions:
                if s.get('password') and cipher_suite:
                    try:
                        s['password'] = cipher_suite.decrypt(
                            s['password'].encode()).decode()
                    except Exception:
                        s['password'] = ''
            return sessions
        except Exception as e:
            logger.warning(f"Failed to load sessions: {e}")
            return []

    def _delete_sessions_file(self):
        try:
            filepath = get_sessions_path()
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            logger.debug(f"Failed to delete sessions file: {e}")

    def restore_sessions(self):
        prefs = get_preferences()
        mode = prefs.get("session_restore", "ask")

        sessions = self._load_sessions_file()
        if not sessions:
            return

        if mode == "never":
            self._delete_sessions_file()
            return

        to_restore = sessions
        if mode == "ask":
            to_restore = self._show_restore_dialog(sessions)
            if not to_restore:
                self._delete_sessions_file()
                return

        self._delete_sessions_file()

        restored = 0
        for session in to_restore:
            try:
                self._restore_single_session(session)
                restored += 1
            except Exception as e:
                logger.warning(
                    f"Failed to restore session to "
                    f"{session.get('hostname')}: {e}")

        if restored > 0:
            self.message_signal.emit(f"Restored {restored} session(s)")

    def _show_restore_dialog(self, sessions):
        dialog = QDialog(self)
        dialog.setWindowTitle("Restore Sessions")
        dialog.setMinimumWidth(450)
        dialog.setStyleSheet("""
            QDialog { background-color: #2a2a2a; color: #dddddd; }
            QLabel { color: #dddddd; }
            QListWidget {
                background-color: #333333; color: #dddddd;
                border: 1px solid #555555;
            }
            QListWidget::item { padding: 6px; }
            QListWidget::item:selected { background-color: #4a6fa5; }
            QPushButton {
                padding: 6px 16px; border: 1px solid #555555;
                border-radius: 3px; background-color: #444444;
                color: #dddddd;
            }
            QPushButton:hover { background-color: #555555; }
        """)

        layout = QVBoxLayout(dialog)

        label = QLabel(
            f"Found {len(sessions)} saved session(s).\n"
            f"Select sessions to restore:")
        layout.addWidget(label)

        list_widget = QListWidget()
        for s in sessions:
            host = s.get('hostname', 'Unknown')
            remote_dir = s.get('current_remote_directory', '')
            item_text = host
            if remote_dir:
                item_text += f"  ({remote_dir})"
            item = QListWidgetItem(item_text)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, s)
            list_widget.addItem(item)
        layout.addWidget(list_widget)

        btn_layout = QHBoxLayout()
        restore_btn = QPushButton("Restore Selected")
        skip_btn = QPushButton("Skip")
        btn_layout.addStretch()
        btn_layout.addWidget(restore_btn)
        btn_layout.addWidget(skip_btn)
        layout.addLayout(btn_layout)

        restore_btn.clicked.connect(dialog.accept)
        skip_btn.clicked.connect(dialog.reject)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return []

        selected = []
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            if item.checkState() == Qt.Checked:
                selected.append(item.data(Qt.UserRole))
        return selected

    def _restore_single_session(self, session):
        hostname = session.get('hostname', '')
        username = session.get('username', '')
        password = session.get('password', '')
        port = session.get('port', 22)
        key = session.get('key', '') or None
        remote_dir = session.get('current_remote_directory', '')
        local_dir = session.get('current_local_directory', '')
        tab_title = session.get('tab_title', '')

        if remote_dir:
            self._restore_remote_dir = remote_dir
        if local_dir:
            self._restore_local_dir = local_dir

        self.hostname_combo.setCurrentText(hostname)
        self.username.setText(username)
        self.password.setText(password)
        self.port_selector.setText(str(port))

        self.key_combo.setCurrentIndex(0)
        if key:
            idx = self.key_combo.findData(key)
            if idx == -1:
                self.key_combo.addItem(os.path.basename(key), key)
                idx = self.key_combo.findData(key)
            if idx >= 0:
                self.key_combo.setCurrentIndex(idx)

        session_id = self.connect(
            hostname=hostname,
            username=username,
            password=password,
            port=str(port),
            key=key if key else None
        )

        if session_id is None:
            return

        if tab_title:
            idx = self.tab_widget.count() - 1
            saved_host = self.get_session_title(session_id)
            if tab_title != saved_host:
                self.tab_widget.setTabText(idx, tab_title)

    def closeEvent(self, event):
        """Handle application close with combined transfer/session dialog"""
        try:
            if hasattr(self, '_connection_event_loop'):
                self._connection_event_loop.quit()

            prefs = get_preferences()
            if not prefs.get_bool("confirm_exit", True):
                event.accept()
                return

            active_count = 0
            if hasattr(self, 'transfer_queue_widget'):
                tw = self.transfer_queue_widget
                active_count = tw.get_active_transfer_count()

            has_transfers = active_count > 0 or queued_count > 0
            open_sessions = self._get_open_sftp_sessions()
            has_sessions = len(open_sessions) > 0
            session_mode = prefs.get("session_restore", "ask")

            if not has_transfers and not has_sessions:
                event.accept()
                return

            if session_mode == "always" and has_sessions:
                self.save_open_sessions(open_sessions)
                has_sessions = False

            if not has_transfers and not has_sessions:
                event.accept()
                return

            if session_mode == "never":
                has_sessions = False

            if not has_transfers and not has_sessions:
                event.accept()
                return

            dialog = QDialog(self)
            dialog.setWindowTitle("Confirm Exit")
            dialog.setStyleSheet("""
                QDialog { background-color: #2a2a2a; color: #dddddd; }
                QLabel { color: #dddddd; }
                QRadioButton { color: #dddddd; }
                QCheckBox { color: #dddddd; }
                QGroupBox {
                    color: #dddddd; border: 1px solid #555555;
                    border-radius: 4px; margin-top: 8px; padding-top: 12px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin; left: 10px; padding: 0 4px;
                }
                QPushButton {
                    padding: 6px 16px; border: 1px solid #555555;
                    border-radius: 3px; background-color: #444444;
                    color: #dddddd; min-width: 80px;
                }
                QPushButton:hover { background-color: #555555; }
                QPushButton[destructive="true"] { border-color: #aa5555; }
                QPushButton[destructive="true"]:hover {
                    background-color: #663333;
                }
            """)
            layout = QVBoxLayout(dialog)

            parts = []
            if has_transfers:
                total = active_count + queued_count
                parts.append(
                    f"{total} pending transfer(s) "
                    f"({active_count} active, {queued_count} queued)")
            if has_sessions:
                parts.append(
                    f"{len(open_sessions)} open SFTP session(s)")
            summary = QLabel(
                f"You have {' and '.join(parts)}.\n\n"
                f"What would you like to do?")
            summary.setWordWrap(True)
            layout.addWidget(summary)

            save_transfers_radio = None
            discard_transfers_radio = None
            restore_sessions_check = None

            if has_transfers:
                transfer_group = QGroupBox("Transfers")
                transfer_layout = QVBoxLayout(transfer_group)
                save_transfers_radio = QRadioButton(
                    "Save transfers for next launch")
                discard_transfers_radio = QRadioButton(
                    "Discard transfers")
                save_transfers_radio.setChecked(True)
                transfer_layout.addWidget(save_transfers_radio)
                transfer_layout.addWidget(discard_transfers_radio)
                layout.addWidget(transfer_group)

            if has_sessions:
                session_group = QGroupBox("Sessions")
                session_layout = QVBoxLayout(session_group)
                restore_sessions_check = QCheckBox(
                    "Restore sessions on next launch")
                restore_sessions_check.setChecked(True)
                session_layout.addWidget(restore_sessions_check)
                layout.addWidget(session_group)

            btn_layout = QHBoxLayout()
            exit_btn = QPushButton("Exit")
            cancel_btn = QPushButton("Cancel")
            btn_layout.addStretch()
            btn_layout.addWidget(exit_btn)
            btn_layout.addWidget(cancel_btn)
            layout.addLayout(btn_layout)

            exit_btn.clicked.connect(dialog.accept)
            cancel_btn.clicked.connect(dialog.reject)
            dialog.setDefaultButton(exit_btn)

            if dialog.exec() != QDialog.DialogCode.Accepted:
                event.ignore()
                return

            if has_transfers:
                if discard_transfers_radio.isChecked():
                    self.transfer_queue_widget.clear_all_transfers()
                    self.message_signal.emit("Transfers discarded")

            if has_sessions and restore_sessions_check.isChecked():
                self.save_open_sessions(open_sessions)

            event.accept()
        except (OSError, IOError, RuntimeError) as e:
            logger.debug(f"Error during application shutdown: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            event.accept()

    def eventFilter(self, source, event):
        """Handle events for child widgets"""
        return super().eventFilter(source, event)

def main():
    # Clear any stale credentials from previous runs
    clear_all_credentials()
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="FTP/SFTP Client")
    parser.add_argument("-H", "--hostname", help="Initial hostname to connect to")
    parser.add_argument("-u", "--username", help="Username for the connection")
    parser.add_argument("-p", "--password", help="Password for the connection")
    parser.add_argument("-P", "--port", type=int, default=22, help="Port for the connection (default: 22)")
    parser.add_argument("-K", "--key", help="SSH key")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--log-file", help="Log file path (default: ~/Library/Logs/sftp_client/sftp.log on macOS)")
    args = parser.parse_args()

    # Set up logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logger = setup_logging(log_level=log_level, log_file=args.log_file)
    logger.info("SFTP Client starting up")

    app = QApplication(sys.argv)

    font = app.font()
    font.setPointSize(10)
    app.setFont(font)

    main_window = MainWindow()
    main_window.setWindowTitle("FTP/SFTP Client")
    main_window.resize(800, 600)
    main_window.show()

    
    # Restore saved sessions (after UI is ready)
    QTimer.singleShot(500, main_window.restore_sessions)
    # If command line arguments are provided, initiate the connection
    if args.hostname:
        try:
            main_window.connect(
                hostname=args.hostname,
                username=args.username or "guest",
                password=args.password or "guest",
                port=args.port or "22",
                key=args.key or "None"
            )
        except (OSError, IOError, RuntimeError) as e:
            pass

    # Connect the aboutToQuit signal directly to the cleanup method
    app.aboutToQuit.connect(main_window.cleanup)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
