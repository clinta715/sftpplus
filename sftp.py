import sys
import os
import argparse
import platform
import time
import logging
from sftp_downloadworkerclass import transferSignals, add_sftp_job, clear_sftp_queue
from sftp_transfer_queue_widget import TransferQueueWidget
from sftp_hostdataeditor import (
    save_connection_data, load_connection_data,
    update_connection_data, get_site_names, get_site_data, get_setting
)
from sftp_theme import BUTTON_STYLE_DARK
from sftp_connections_widget import ConnectionsWidget
from sftp_file_browser_panel import FileBrowserPanel
from sftp_terminal_widget import SSHTerminalWidget
from sftp_local_terminal_widget import LocalTerminalWidget
from sftp_filebrowserclass import FileBrowser
from sftp_creds import get_credentials, set_credentials, del_credentials, create_random_integer, clear_all_credentials, get_home_directory
from sftp_session import get_session_manager
from sftp_qt_compat import Qt  # Use compatibility layer for Qt enums
from PySide6.QtWidgets import QInputDialog, QFileDialog, QLabel, QToolButton, QMainWindow, QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QTextEdit, QCompleter, QComboBox, QSpinBox, QTabWidget, QMessageBox, QCheckBox, QMenu, QSizePolicy
from PySide6.QtCore import Signal, QObject, QCoreApplication, QTimer, QEvent, QMutexLocker
from PySide6.QtGui import QKeySequence, QShortcut
import paramiko

from sftp_preferences import get_preferences
from sftp_toolbar_customizer import customize_toolbar
from sftp_about import show_about
from sftp_logging import setup_logging, get_logger

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

class MainWindow(QMainWindow):  # Inherits from QMainWindow
    message_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self.transfers_message = transferSignals()
        self.message_signal.connect(self.update_console)

        QCoreApplication.instance().aboutToQuit.connect(self.cleanup)
        self.hostnames = []
        self.sessions = []
        self.observers = []
        self._notifying = False

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
        from PySide6.QtWidgets import QApplication
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

    def _show_tab_context_menu(self, pos):
        index = self.tab_widget.tabBar().tabAt(pos)
        if index <= 1:
            return
        
        menu = QMenu(self)
        rename_action = menu.addAction("Rename Tab")
        close_action = menu.addAction("Close Tab")
        close_others_action = menu.addAction("Close Other Tabs")
        
        action = menu.exec(self.tab_widget.tabBar().mapToGlobal(pos))
        
        if action == rename_action:
            self._rename_tab_by_index(index)
        elif action == close_action:
            self.closeTab(index)
        elif action == close_others_action:
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
        self.clear_queue_button = QPushButton("Clear Queue")
        self.clear_queue_button.setStyleSheet(BUTTON_STYLE_DARK)
        self.about_button = QPushButton("ℹ About")
        self.about_button.setToolTip("About SFTP Client")
        self.about_button.setStyleSheet(BUTTON_STYLE_DARK)
        
        prefs = get_preferences()
        self.confirm_exit_checkbox = QCheckBox("Confirm exit")
        self.confirm_exit_checkbox.setToolTip("Confirm before closing application with active transfers")
        self.confirm_exit_checkbox.setChecked(prefs.get_bool("confirm_exit", True))
        self.confirm_exit_checkbox.stateChanged.connect(self._on_confirm_exit_changed)
        
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
        
        QTimer.singleShot(500, self.transfer_queue_widget.load_pending_transfers)
        
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
        self.button_layout.addWidget(self.clear_queue_button)
        self.button_layout.addWidget(self.confirm_exit_checkbox)
        self.button_layout.addWidget(self.edit_button)
        self.button_layout.addStretch()
        self.button_layout.addWidget(self.about_button)
        
        self._toolbar_container.setLayout(self.button_layout)
        self._toolbar_container.setContextMenuPolicy(Qt.CustomContextMenu)
        self._toolbar_container.customContextMenuRequested.connect(self._show_toolbar_context_menu)

        self.edit_button.clicked.connect(self._switch_to_connections_tab)
        self.connect_button.clicked.connect(self.connect_button_pressed)
        self.terminal_button.clicked.connect(self.terminal_button_pressed)
        self.clear_queue_button.clicked.connect(clear_sftp_queue)
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

    def create_cancel_button(self, transfer_id):
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(lambda: self.cancel_transfer(transfer_id))
        return cancel_button

    def cancel_transfer(self, transfer_id):
        if transfer_id in self.transfers:
            self.transfers[transfer_id].download_worker._stop_flag = True
            self.message_signal.emit(f"Cancelling transfer {transfer_id}")

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
                            remote_path = os.path.join(creds.get('current_remote_directory', '.'), selected_item)
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

    # Alias for backward compatibility
    on_site_manager_connect = handle_connection_request

    def connect_button_pressed(self):
        try:
            session_id = self.connect()
            if session_id is None:
                # Connection failed, error has already been displayed
                return
            # If needed, add any post-connection logic here
        except (ConnectionError, OSError, ValueError) as e:
            error_message = f"Connection failed: {str(e)}"
            self.display_error(error_message)
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
        self.temp_hostname = self.hostname_combo.currentText() if hostname == "localhost" and self.hostname_combo.currentText() else hostname
        
        # Print to the global output console
        self.message_signal.emit(f"Attempting to connect to {self.temp_hostname}...")
        
        try:
            self.session_id = create_random_integer()
            self.message_signal.emit(f"Created session ID: {self.session_id}")

            # Hostname, username, password, and port handling
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
            max_conns = prefs.get("max_ssh_connections_per_host", 8)
            pool.set_max_connections(self.temp_hostname, self.temp_port, self.temp_username, max_conns)

            # Test the connection with actual SFTP operation
            self.message_signal.emit("Testing SFTP connection...")
            try:
                home_dir = self.test_connection()
                if not home_dir:
                    raise ValueError("SFTP connection test failed")
                self.message_signal.emit("Connection test passed!")
            except (OSError, IOError, RuntimeError) as e:
                self.message_signal.emit(f"Connection test failed: {e}")
                raise  # Re-raise to trigger main exception handling

            self.message_signal.emit(f"Successfully connected to {self.temp_hostname}")

            # Set the home directory from test_connection to avoid another SSH connection
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
            
            # Notify transfer queue of new session
            if hasattr(self, 'transfer_queue_widget') and self.transfer_queue_widget:
                self.transfer_queue_widget.register_active_session(self.temp_hostname, self.session_id)

            # Save connection data synchronously
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
        return None

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
                self.message_signal.emit("Loaded known hosts from ~/.ssh/known_hosts")
            except (OSError, IOError, RuntimeError) as e:
                self.message_signal.emit(f"Warning: Could not load known_hosts: {e}")
        
        # Set up policy to warn about unknown hosts
        class InteractivePolicy(paramiko.MissingHostKeyPolicy):
            def __init__(self, parent):
                self.parent = parent
                self.known_hosts_path = known_hosts_path
                
            def missing_host_key(self, client, hostname, key):
                # Check if this is a new host
                key_type = key.get_name()
                fingerprint = key.get_fingerprint().hex()
                
                msg = f"""Unknown host: {hostname}

Key type: {key_type}
Fingerprint: {fingerprint}

Do you want to trust this host and add it to known_hosts?"""
                
                reply = QMessageBox.question(
                    self.parent,
                    "Unknown Host Key",
                    msg,
                    Qt.MsgBtn_Yes | Qt.MsgBtn_No,
                    Qt.MsgBtn_No
                )
                
                if reply == Qt.MsgBtn_Yes:
                    try:
                        client.get_host_keys().add(hostname, key.get_name(), key)
                        client.save_host_keys(self.known_hosts_path)
                        return
                    except (OSError, IOError, RuntimeError) as e:
                        self.parent.message_signal.emit(f"Warning: Could not save host key: {e}")
                        return
                else:
                    raise paramiko.SSHException(f"Host key verification failed for {hostname}")
        
        ssh.set_missing_host_key_policy(InteractivePolicy(self))
    
    def test_connection(self):
        """Test SSH/SFTP connection with guaranteed cleanup. Returns home directory path."""
        import paramiko
        ssh = paramiko.SSHClient()
        sftp = None
        home_dir = '/'

        # Setup proper host key verification
        self._setup_host_key_policy(ssh)

        try:
            self.message_signal.emit(f"Attempting SSH connection to {self.temp_hostname}:{self.temp_port}...")

            # Attempt connection with appropriate authentication method
            connect_kwargs = {
                'hostname': self.temp_hostname,
                'port': self.temp_port,
                'username': self.temp_username,
                'timeout': 60
            }

            # Handle SSH key authentication
            if self.temp_key:
                self.message_signal.emit(f"Using SSH key authentication with: {os.path.basename(self.temp_key)}")
                ssh.connect(**connect_kwargs, pkey=self._load_private_key(self.temp_key))
            else:
                # Password-based authentication
                if not self.temp_password:
                    raise ValueError("Password is required when not using SSH key authentication")
                connect_kwargs['password'] = self.temp_password
                self.message_signal.emit("Using password authentication")
                ssh.connect(**connect_kwargs)

            self.message_signal.emit("SSH connection successful")

            # Test SFTP functionality by opening SFTP session and listing current directory
            sftp = ssh.open_sftp()
            sftp.listdir('.')  # Test with simple directory listing
            self.message_signal.emit("SFTP connection test successful")

            # Get the actual home directory to avoid relative path issues
            try:
                stdin, stdout, stderr = ssh.exec_command('pwd')
                output = stdout.read().decode().strip()
                error = stderr.read().decode().strip()
                if output and not error:
                    home_dir = output
                    self.message_signal.emit(f"Remote home directory: {home_dir}")
            except (OSError, IOError, RuntimeError) as e:
                pass

            return home_dir

        except paramiko.BadHostKeyException as e:
            # Host key changed - ask user what to do
            msg = f"""Host key mismatch for {e.hostname}

The server's host key has changed. This could indicate:
- The server was rebuilt or updated
- A man-in-the-middle attack
- The known_hosts file was corrupted

Old key: {e.key.get_fingerprint().hex() if e.key else 'unknown'}

Do you want to update the host key and continue connecting?"""
            
            reply = QMessageBox.question(
                self,
                "Host Key Changed",
                msg,
                Qt.MsgBtn_Yes | Qt.MsgBtn_No,
                Qt.MsgBtn_No
            )
            
            if reply == Qt.MsgBtn_Yes:
                # Remove old key and retry
                known_hosts_path = os.path.expanduser('~/.ssh/known_hosts')
                if os.path.exists(known_hosts_path):
                    try:
                        ssh.load_host_keys(known_hosts_path)
                        # Remove the old key
                        ssh.get_host_keys().remove(e.hostname)
                        ssh.save_host_keys(known_hosts_path)
                    except Exception:
                        pass
                
                # Retry connection
                return self.test_connection()
            else:
                self.message_signal.emit("Connection aborted due to host key mismatch")
                raise RuntimeError(f"Host key verification failed for {e.hostname}")
        
        except Exception as e:
            self.message_signal.emit(f"SSH connection failed: {str(e)}")
            raise RuntimeError(f"Failed to connect: {str(e)}")
        finally:
            # Ensure SFTP session is closed
            if sftp:
                try:
                    sftp.close()
                except (OSError, IOError, RuntimeError) as e:
                    pass

            # Ensure SSH connection is closed
            try:
                ssh.close()
            except (OSError, IOError, RuntimeError) as e:
                pass
        
    def set_credentials_async(self):
            set_credentials(self.session_id, 'hostname', self.temp_hostname)
            set_credentials(self.session_id, 'username', self.temp_username)
            set_credentials(self.session_id, 'password', self.temp_password)
            set_credentials(self.session_id, 'port', str(self.temp_port))
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
            site = get_site_data(self.temp_hostname)
            if not site:
                return
            initial_remote = site.get("initial_remote_dir", "")
            initial_local = site.get("initial_local_dir", "")
            
            if initial_remote:
                self.message_signal.emit(f"Navigating to initial remote directory: {initial_remote}")
                # Use set_credentials for thread-safe update (don't modify dict directly)
                set_credentials(self.session_id, 'current_remote_directory', initial_remote)
            
            if initial_local:
                self.message_signal.emit(f"Navigating to initial local directory: {initial_local}")
                # Use set_credentials for thread-safe update
                set_credentials(self.session_id, 'current_local_directory', initial_local)
                # Also change the actual working directory
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

            self.stop_background_thread()

            from sftp_downloadworkerclass import clear_sftp_queue
            clear_sftp_queue()

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

    def stop_background_thread(self):
        """Stop the transfer queue processing"""
        try:
            if hasattr(self, 'transfer_queue_widget'):
                # Stop the timer first to prevent new transfers from starting
                if hasattr(self.transfer_queue_widget, 'check_queue_timer'):
                    self.transfer_queue_widget.check_queue_timer.stop()

                # Cancel all active transfers
                for transfer in self.transfer_queue_widget.transfers[:]:
                    try:
                        if transfer.active and hasattr(transfer, 'download_worker'):
                            transfer.download_worker._stop_flag = True
                    except (OSError, IOError, RuntimeError):
                        pass

                # Wait for thread pool to finish (up to 2 seconds)
                if hasattr(self.transfer_queue_widget, 'thread_pool'):
                    self.transfer_queue_widget.thread_pool.waitForDone(2000)

                # Force clear the queue
                from sftp_downloadworkerclass import clear_sftp_queue
                clear_sftp_queue()
        except (OSError, IOError, RuntimeError) as e:
            logger.debug(f"Error stopping background thread: {e}")

    def _on_confirm_exit_changed(self, state):
        """Handle confirm exit checkbox change"""
        prefs = get_preferences()
        prefs.set_bool("confirm_exit", bool(state))

    def closeEvent(self, event):
        """Handle application close"""
        try:
            prefs = get_preferences()
            if not prefs.get_bool("confirm_exit", True):
                event.accept()
                return

            active_count = 0
            queued_count = 0
            if hasattr(self, 'transfer_queue_widget'):
                tw = self.transfer_queue_widget
                active_count = tw.get_active_transfer_count()
                tw.active_transfers = active_count
                from sftp_downloadworkerclass import sftp_queue
                queued_count = sftp_queue.qsize()

            if active_count > 0 or queued_count > 0:
                total = active_count + queued_count
                msg = f'There are {total} pending file transfers ({active_count} active, {queued_count} queued).\n\n'
                msg += 'Unfinished transfers will be saved and resumed on next launch.\n\n'
                msg += 'What would you like to do?'
                reply = QMessageBox(self)
                reply.setWindowTitle("Confirm Exit")
                reply.setText(msg)
                save_button = reply.addButton("Exit and Save Transfers", QMessageBox.ButtonRole.ActionRole)
                discard_button = reply.addButton("Exit and Discard Transfers", QMessageBox.ButtonRole.DestructiveRole)
                cancel_button = reply.addButton(QMessageBox.StandardButton.Cancel)
                reply.setDefaultButton(save_button)
                reply.exec()
                
                if reply.clickedButton() == cancel_button or reply.clickedButton() == cancel_button:
                    event.ignore()
                    return
                elif reply.clickedButton() == discard_button:
                    self.transfer_queue_widget.clear_all_transfers()
                    from sftp_downloadworkerclass import clear_sftp_queue
                    clear_sftp_queue()
                    self.message_signal.emit("Transfers discarded")

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

    show_manager_on_startup = get_setting("show_manager_on_startup", True)

    startup_connection = [None]

    if show_manager_on_startup and not args.hostname:
        pass
    
    # create the main window of the application
    main_window = MainWindow()
    
    # Handle startup connection from site manager
    if startup_connection[0] and not args.hostname:
        main_window.message_signal.emit(f"Connecting to {startup_connection[0]['hostname']} from Site Manager...")
        # Use QTimer to ensure UI is ready before connecting
        QTimer.singleShot(100, lambda: main_window.on_site_manager_connect(startup_connection[0]))
    main_window.setWindowTitle("FTP/SFTP Client")
    main_window.resize(800, 600)
    main_window.show()

    # No longer needed - transfers are now in a tab
    # main_window.transfers_message.showhide.connect(hide_transfers_window)

    # No longer needed - no separate background window
    # main_window.position_background_window()

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
