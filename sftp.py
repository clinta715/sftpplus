import sys
import os
import argparse
import platform
import time
import logging
from icecream import ic
from sftp_downloadworkerclass import transferSignals, add_sftp_job, clear_sftp_queue
from sftp_transfer_queue_widget import TransferQueueWidget
from sftp_hostdataeditor import save_connection_data, load_connection_data
from sftp_theme import BUTTON_STYLE_DARK
from sftp_connections_widget import ConnectionsWidget
from sftp_file_browser_panel import FileBrowserPanel
from sftp_filebrowserclass import FileBrowser
from sftp_creds import get_credentials, set_credentials, del_credentials, create_random_integer, clear_all_credentials, get_home_directory
from PyQt5.QtWidgets import QInputDialog, QFileDialog, QLabel, QToolButton, QMainWindow, QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QTextEdit, QCompleter, QComboBox, QSpinBox, QTabWidget, QMessageBox
from PyQt5.QtCore import pyqtSignal, QObject, QCoreApplication, Qt, QTimer, QEvent, QMutexLocker
from cryptography.fernet import Fernet
import paramiko

class CustomComboBox(QComboBox):
    editingFinished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.editingFinished.emit()

# Define SIZE_UNIT and WorkerSignals as necessary
MAX_TRANSFERS = 4

class WorkerSignals(QObject):
    error = pyqtSignal(int, str)

class MainWindow(QMainWindow):  # Inherits from QMainWindow
    message_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.transfers_message = transferSignals()
        self.message_signal.connect(self.update_console)

        # Custom data structure to store hostname, username, and password together
        self.create_initial_data()
        self.host_data = {
            "hostnames" : {},
            "usernames" : {},
            "passwords" : {},
            "ports" : {},
            "key" : {} }

        # Previous text to check for changes
        QCoreApplication.instance().aboutToQuit.connect(self.cleanup)
        self.hostnames = []
        self.sessions = []
        self.observers = []
        self._notifying = False  # Flag to track notification status

        # Create and connect to the error signal from WorkerSignals
        self.worker_signals = WorkerSignals()
        self.worker_signals.error.connect(self._display_error)

        # Load saved connection data and encryption key
        self.host_data = load_connection_data()

        # Initialize UI after loading connection data
        self.init_ui()

        # Install event filter for window movement
        self.installEventFilter(self)
        
        # Note: Transfer queue widget will be created after init_ui() sets up the tab widget

    def _display_error(self, transfer_id, message):
        # Display error in a message box
        QMessageBox.critical(self, "Error", f"Transfer {transfer_id}: {message}")
        
        # Display the error in the status bar
        self.status_bar.setText(f"Error in transfer {transfer_id}: {message}")
        self.status_bar.setStyleSheet("""
            QLabel {
                background-color: #5a1a1a;
                color: #ff6b6b;
                padding: 5px 10px;
                border-top: 1px solid #ff6b6b;
                font-size: 12px;
            }
        """)

    def init_ui(self):
        # Initialize input widgets
        self.container_layout = QVBoxLayout()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.port_selector = QLineEdit()

        # Initialize buttons
        self.connect_button = QPushButton("Connect")
        self.edit_button = QPushButton("Edit Host Data")
        self.clear_queue_button = QPushButton("Clear Queue")
        self.transfers = {}  # Dictionary to store active transfers

        # Initialize hostname combo box
        self.hostname_combo = CustomComboBox(self)  # Pass self as parent
        self.hostname_combo.setEditable(True)
        self.populate_hostname_combo()  # New method to populate the combo box

        # Initialize spin box
        self.spinBox = QSpinBox()
        self.spinBox.setMinimum(2)
        self.spinBox.setMaximum(10)
        self.spinBox.setValue(4)
        self.spinBox.valueChanged.connect(self.on_value_changed)  # Ensure this slot is implemented

        # Initialize layouts
        self.init_top_bar_layout()
        self.init_button_layout()

        # Set main layout
        self.top_layout = QVBoxLayout()
        self.top_layout.addLayout(self.top_bar_layout)
        self.top_layout.addLayout(self.button_layout)

        # Set up central widget
        self.central_widget = QWidget()
        self.central_widget.setLayout(self.top_layout)
        self.setCentralWidget(self.central_widget)

        # Initialize tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.closeTab)

        # Additional setup if necessary
        self.setup_hostname_completer()

        # Add the tab widget to the top layout
        # Add the tab widget (takes most of the space)
        self.top_layout.addWidget(self.tab_widget)
        
        # Create status bar (single line at bottom)
        self.status_bar = QLabel("Ready")
        self.status_bar.setStyleSheet("""
            QLabel {
                background-color: #2a2a2a;
                color: #aaaaaa;
                padding: 5px 10px;
                border-top: 1px solid #555555;
                font-size: 12px;
            }
        """)
        self.status_bar.setMaximumHeight(30)
        self.top_layout.addWidget(self.status_bar)
        
        # Create and add the transfer queue widget as a permanent tab
        self.transfer_queue_widget = TransferQueueWidget()
        self.tab_widget.addTab(self.transfer_queue_widget, "📋 Transfers")
        
        # Create and add the connections widget as a tab
        self.connections_widget = ConnectionsWidget()
        self.connections_widget.connect_requested.connect(self.handle_connection_request)
        self.tab_widget.addTab(self.connections_widget, "🔗 Connections")
        
        # Connect the edit button to switch to connections tab
        self.edit_button.clicked.connect(self._switch_to_connections_tab)
        
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
        self.key_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.top_bar_layout.addWidget(self.key_combo, 2)

        self.key_browse_btn = QToolButton()
        self.key_browse_btn.setText("…")
        self.key_browse_btn.setToolTip("Browse for a private key file")
        self.key_browse_btn.clicked.connect(self.browse_ssh_key)
        self.top_bar_layout.addWidget(self.key_browse_btn, 0)
        # ------------------------------------------------------------------

        self.top_bar_layout.addWidget(self.port_selector, 1)
        self.top_bar_layout.addWidget(self.spinBox)

        # keep the existing return-pressed shortcuts
        self.username.returnPressed.connect(self.connect_button_pressed)
        self.password.returnPressed.connect(self.connect_button_pressed)
        self.port_selector.returnPressed.connect(self.connect_button_pressed)

    def init_button_layout(self):
        self.button_layout = QHBoxLayout()
        
        # File operation buttons
        self.refresh_btn = QPushButton("↻ Refresh")
        self.refresh_btn.setToolTip("Refresh current directory")
        self.refresh_btn.setFixedWidth(80)
        
        self.upload_btn = QPushButton("↑ Upload")
        self.upload_btn.setToolTip("Upload selected file(s)")
        self.upload_btn.setFixedWidth(80)
        
        self.download_btn = QPushButton("↓ Download")
        self.download_btn.setToolTip("Download selected file(s)")
        self.download_btn.setFixedWidth(80)
        
        self.new_folder_btn = QPushButton("+ Folder")
        self.new_folder_btn.setToolTip("Create new folder")
        self.new_folder_btn.setFixedWidth(80)
        
        self.delete_btn = QPushButton("✕ Delete")
        self.delete_btn.setToolTip("Delete selected file(s)")
        self.delete_btn.setFixedWidth(80)
        
        self.rename_btn = QPushButton("⇄ Rename")
        self.rename_btn.setToolTip("Rename selected file(s)")
        self.rename_btn.setFixedWidth(80)
        
        for btn in [self.refresh_btn, self.upload_btn, self.download_btn, self.new_folder_btn, self.delete_btn, self.rename_btn]:
            btn.setStyleSheet(BUTTON_STYLE_DARK)
        
        # Connect file operation buttons
        self.refresh_btn.clicked.connect(self._toolbar_refresh)
        self.upload_btn.clicked.connect(self._toolbar_upload)
        self.download_btn.clicked.connect(self._toolbar_download)
        self.new_folder_btn.clicked.connect(self._toolbar_new_folder)
        self.delete_btn.clicked.connect(self._toolbar_delete)
        self.rename_btn.clicked.connect(self._toolbar_rename)
        
        # Add file operation buttons
        self.button_layout.addWidget(self.refresh_btn)
        self.button_layout.addWidget(self.upload_btn)
        self.button_layout.addWidget(self.download_btn)
        self.button_layout.addWidget(self.new_folder_btn)
        self.button_layout.addWidget(self.delete_btn)
        self.button_layout.addWidget(self.rename_btn)
        
        self.button_layout.addStretch()
        
        self.button_layout.addWidget(self.connect_button)
        self.button_layout.addWidget(self.clear_queue_button)
        self.button_layout.addWidget(self.edit_button)

        # Connect the clicked signal to switch to connections tab
        self.edit_button.clicked.connect(self._switch_to_connections_tab)

        # Connect the clicked signal of the connect button to the connect_button_pressed method
        self.connect_button.clicked.connect(self.connect_button_pressed)
        self.clear_queue_button.clicked.connect(clear_sftp_queue)

    def setup_hostname_completer(self):
        # Make sure self.hostnames is initialized and filled with data
        self.hostname_completer = QCompleter(self.hostnames)
        self.hostname_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.hostname_completer.setCompletionMode(QCompleter.PopupCompletion)
        self.hostname_combo.setCompleter(self.hostname_completer)

        # Connect signals for hostname combo box
        self.hostname_combo.currentIndexChanged.connect(self.hostname_changed)  # Ensure this slot is implemented
        self.hostname_combo.activated.connect(self.hostname_changed)
        self.hostname_combo.editingFinished.connect(self.hostname_changed)        

    def populate_hostname_combo(self):
        # Clear existing items
        self.hostname_combo.clear()
        
        # Add hostnames from the host_data
        for hostname in self.host_data['hostnames'].keys():
            self.hostname_combo.addItem(hostname)
        
        # Update the hostnames list for the completer
        self.hostnames = list(self.host_data['hostnames'].keys())

    def browse_ssh_key(self):
        """Let the user pick a private-key file (*.key, *, etc.) and add it to the key combo."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            caption="Select SSH private-key file",
            directory=os.path.expanduser("~"),
            filter="SSH key (*.key *.pem *.ppk *.pub);;All files (*)"
        )
        if path:
            # Verify the file exists and is readable
            if not os.path.exists(path):
                QMessageBox.warning(self, "Key Error", f"Selected key file does not exist: {path}")
                return
                
            # avoid duplicates
            if self.key_combo.findData(path) == -1:
                # self.key_combo.addItem(os.path.basename(path), path)
                self.key_combo.addItem(os.path.basename(path), path)
                self.key_combo.setCurrentIndex(self.key_combo.findData(path))
            else:
                # Key already exists, just select it
                self.key_combo.setCurrentIndex(self.key_combo.findData(path))

    def prepare_container_widget(self):
        """Create a container widget with file browsers"""
        container_widget = QWidget()

        # Create the file browser panel with toggleable local browser
        # Use auto_initialize=False to defer remote browser initialization
        # until after connection is fully established
        ic(f"prepare_container_widget: Creating FileBrowserPanel with session_id={self.session_id}")
        self.file_browser_panel = FileBrowserPanel(self.session_id, auto_initialize=False)
        ic(f"prepare_container_widget: FileBrowserPanel created (deferred init)")
        
        # Connect observers
        self.transfer_queue_widget.add_observee(self.file_browser_panel.left_browser)
        self.transfer_queue_widget.add_observee(self.file_browser_panel.right_browser)

        # Connect message signals
        self.file_browser_panel.message.connect(self.update_console)
        
        # Connect transfer started signal to switch to transfers tab
        self.file_browser_panel.transfer_started.connect(self._switch_to_transfers_tab)

        # Create the main layout (no per-tab output console - using global status bar instead)
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.file_browser_panel)
        
        # Store references in container widget
        container_widget.left_browser = self.file_browser_panel.left_browser
        container_widget.right_browser = self.file_browser_panel.right_browser

        # Set the main layout to the container widget
        container_widget.setLayout(main_layout)
        self.message_signal.emit("Connection successful")

        return container_widget

    def closeTab(self, index):
        # Don't close the permanent tabs (transfers at 0, connections at 1)
        if index <= 1:
            return
            
        # Close the tab at the given index
        widget_to_remove = self.tab_widget.widget(index)
        
        # Remove observers before closing
        if hasattr(widget_to_remove, 'left_browser'):
            self.transfer_queue_widget.remove_observee(widget_to_remove.left_browser)
        if hasattr(widget_to_remove, 'right_browser'):
            self.transfer_queue_widget.remove_observee(widget_to_remove.right_browser)
        
        self.tab_widget.removeTab(index)

        # Close SFTP connection
        if hasattr(widget_to_remove, 'right_browser'):
            widget_to_remove.right_browser.close_sftp_connection()

        # Delete the widget if necessary
        widget_to_remove.deleteLater()

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

    def initialize_session_credentials(self, session_id):
        self.session_id = session_id

        self.title = self.get_session_title(self.session_id)
        self.tab_widget.addTab(self.tab_widget, self.title)
        self.sessions.append(self.tab_widget)

    def get_session_title(self, session_id):
        self.session_id = session_id
        creds = get_credentials(self.session_id)

        try:
            title = creds.get('hostname') if creds else "Unknown Hostname"
        except KeyError:
            title = "Unknown Hostname"
        return title

    def log_connection_success(self):
        self.status_bar.setText("Connected successfully")

    def restore_user_changes(self):
        """Restore user changes if they exist"""
        if hasattr(self, '_user_changes') and self._user_changes:
            if self._user_changes.get('username'):
                self.username.setText(self._user_changes['username'])
            if self._user_changes.get('password'):
                self.password.setText(self._user_changes['password'])
            if self._user_changes.get('port'):
                self.port_selector.setText(self._user_changes['port'])
            if self._user_changes.get('key'):
                # Find and select the key in combo box
                key_index = self.key_combo.findData(self._user_changes['key'])
                if key_index >= 0:
                    self.key_combo.setCurrentIndex(key_index)

    def hostname_changed(self):
        self.current_hostname = self.hostname_combo.currentText().strip()

        # ------------------------------------------------------------------
        # Clear everything first so we never show stale data
        # ------------------------------------------------------------------
        self.username.clear()
        self.password.clear()
        self.port_selector.clear()
        self.key_combo.clear()
        self.key_combo.addItem('<none>', None)          # default "no key" entry

        if self.current_hostname in self.host_data['hostnames']:
            username = self.host_data['usernames'].get(self.current_hostname, '')
            password = self.host_data['passwords'].get(self.current_hostname, '')
            port     = self.host_data['ports'].get(self.current_hostname, '')
            
            # Handle key data - it might be a single string or a list
            key_data = self.host_data['key'].get(self.current_hostname,'')
            
            self.username.setText(username)
            self.password.setText(password)
            self.port_selector.setText(str(port))

            # Populate the key combo
            try:
                self.key_combo.addItem(os.path.basename(key_data), key_data)
            except:
                self.key_combo.addItem("<none>", None)

            # If we actually added any keys, select the first one
            # if key_paths and self.key_combo.count() > 1:  # More than just '<none>'
            #    self.key_combo.setCurrentIndex(1)  # Select first actual key, not '<none>'

    def removeTab(self, session_id):
        creds = get_credentials(self.session_id)
        self.tabWidget.removeTab( self.tabs[session_id] )
        del self.tabs[session_id]  # Remove the reference from the list
        del_credentials(self.session_id)

    def on_value_changed(self, value):
        global MAX_TRANSFERS
        MAX_TRANSFERS = value
        
    def update_console(self, message):
        # Update status bar with latest message
        self.status_bar.setText(message)
        # Reset to normal style (in case it was showing an error)
        self.status_bar.setStyleSheet("""
            QLabel {
                background-color: #2a2a2a;
                color: #aaaaaa;
                padding: 5px 10px;
                border-top: 1px solid #555555;
                font-size: 12px;
            }
        """)

    def update_completer(self):
        # Update the list of hostnames
        self.hostnames = list(self.host_data['hostnames'].keys())  # Adjusted to fetch keys from the 'hostnames' dict within host_data

        # Clear and repopulate the hostname combo box
        self.hostname_combo.clear()
        self.hostname_combo.addItems(self.hostnames)

        # Reinitialize the completer with the updated list
        self.hostname_completer = QCompleter(self.hostnames)
        self.hostname_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.hostname_completer.setCompletionMode(QCompleter.PopupCompletion)
        self.hostname_combo.setCompleter(self.hostname_completer)

    def _switch_to_connections_tab(self):
        """Switch to the Connections tab"""
        self.tab_widget.setCurrentIndex(1)  # Index 1 is Connections tab
    
    def _switch_to_transfers_tab(self):
        """Switch to the Transfers tab"""
        self.tab_widget.setCurrentIndex(0)  # Index 0 is Transfers tab
    
    def _switch_to_connection_tab(self, tab_index):
        """Switch to a specific connection tab"""
        if tab_index < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(tab_index)
    
    def _get_active_browser(self):
        """Get the currently active remote file browser"""
        current_index = self.tab_widget.currentIndex()
        if current_index < 2:  # Transfers or Connections tab
            return None
        try:
            widget = self.tab_widget.widget(current_index)
            # Container widget has right_browser directly, not file_browser_panel
            if hasattr(widget, 'right_browser'):
                return widget.right_browser
        except:
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
        if browser and hasattr(browser, 'is_remote_browser') and browser.is_remote_browser():
            browser.upload_download()
        else:
            QMessageBox.information(self, "Upload", "Please select a remote connection tab first.")
    
    def _toolbar_download(self):
        """Handle Download button click - downloads from remote to local"""
        browser = self._get_active_browser()
        if browser and hasattr(browser, 'is_remote_browser') and browser.is_remote_browser():
            browser.upload_download()
        else:
            QMessageBox.information(self, "Download", "Please select a remote connection tab first.")
    
    def _toolbar_new_folder(self):
        """Handle New Folder button click"""
        browser = self._get_active_browser()
        if browser:
            browser.prompt_and_create_directory()
        else:
            QMessageBox.information(self, "New Folder", "Please open a connection first.")
    
    def _toolbar_delete(self):
        """Handle Delete button click"""
        browser = self._get_active_browser()
        if browser:
            browser.remove_directory_with_prompt()
        else:
            QMessageBox.information(self, "Delete", "Please open a connection first.")

    def _toolbar_rename(self):
        """Handle Rename button click"""
        from PyQt5.QtWidgets import QInputDialog
        browser = self._get_active_browser()
        if browser:
            current_browser = browser.active_table
            if current_browser is not None:
                current_index = current_browser.currentIndex()
                if current_index.isValid():
                    filename_index = current_browser.model().index(current_index.row(), 0)
                    selected_item = current_browser.model().data(filename_index, Qt.DisplayRole)
                    selected_item = selected_item.split(' ', 1)[-1] if ' ' in selected_item else selected_item
                    
                    new_name, ok = QInputDialog.getText(self, "Rename", f"Enter new name for '{selected_item}':")
                    if ok and new_name and new_name != selected_item:
                        creds = get_credentials(browser.session_id)
                        remote_path = os.path.join(creds.get('current_remote_directory'), selected_item)
                        browser.sftp_rename(remote_path, new_name)
                    elif ok and new_name == selected_item:
                        QMessageBox.information(self, "Rename", "New name is the same as current name.")
                else:
                    QMessageBox.information(self, "Rename", "Please select a file or folder to rename.")
            else:
                QMessageBox.information(self, "Rename", "No file browser available.")
        else:
            QMessageBox.information(self, "Rename", "Please open a connection first.")
    
    def handle_connection_request(self, connection_data):
        """Handle connection request from Connections widget"""
        hostname = connection_data.get("hostname")
        username = connection_data.get("username")
        password = connection_data.get("password")
        port = connection_data.get("port", 22)
        key = connection_data.get("key", "None")
        
        # Update UI fields
        self.hostname_combo.setCurrentText(hostname)
        self.username.setText(username)
        self.password.setText(password)
        self.port_selector.setText(str(port))
        
        # Switch to connection form tab
        self.tab_widget.setCurrentIndex(2)  # Index 2 is the first connection tab
        
        # Perform the connection
        self.message_signal.emit(f"Connecting to {hostname} from Connections...")
        self.connect(hostname=hostname, username=username, password=password, port=port, key=key)

    # Alias for backward compatibility
    on_site_manager_connect = handle_connection_request

    def on_host_data_changed(self, updated_data):
        self.host_data = updated_data
        save_connection_data()
        self.update_completer()

    def onEntryDoubleClicked(self, entry):
        hostname = entry.get("hostname", "localhost")
        username = entry.get("username", "guest")
        password = entry.get("password", "guest")
        port = entry.get("port", "22")
        key = entry.get("key", None)

        self.connect(hostname=hostname, username=username, password=password, port=port,key=key)

    # Function to safely clear a queue
    def clear_queue(self, q):
        try:
            while True:  # Continue until an Empty exception is raised
                q.get_nowait()  # Remove an item from the queue
                q.task_done()  # Indicate that a formerly enqueued task is complete
        except Exception as e:
            pass  # Queue is empty, break the loop

    def connect_button_pressed(self):
        try:
            session_id = self.connect()
            if session_id is None:
                # Connection failed, error has already been displayed
                return
            # If needed, add any post-connection logic here
        except Exception as e:
            error_message = f"Connection failed: {str(e)}"
            self.display_error(error_message)
            self.update_console(error_message)

    def display_error(self, transfer_id, message):
        # Display error in a message box
        QMessageBox.critical(self, "Error", f"Transfer {transfer_id}: {message}")
        
        # Display the error in the status bar
        self.status_bar.setText(f"Error in transfer {transfer_id}: {message}")
        self.status_bar.setStyleSheet("""
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
                QLineEdit.Password)
            if ok and passphrase:
                return paramiko.PKey.from_private_key_file(path, password=passphrase)
        except Exception as e:
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

            # Test the connection with actual SFTP operation
            self.message_signal.emit("Testing SFTP connection...")
            try:
                home_dir = self.test_connection()
                if not home_dir:
                    raise ValueError("SFTP connection test failed")
                self.message_signal.emit("Connection test passed!")
            except Exception as e:
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
            except Exception as e:
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
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                
                if reply == QMessageBox.Yes:
                    # Add to known_hosts
                    try:
                        client.save_host_keys(self.known_hosts_path)
                        return
                    except Exception as e:
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
                else:
                    ic(f"Could not get home directory: {error}")
            except Exception as e:
                ic(f"Could not get home directory: {e}")

            return home_dir

        except Exception as e:
            self.message_signal.emit(f"SSH connection failed: {str(e)}")
            raise Exception(f"Failed to connect: {str(e)}")
        finally:
            # Ensure SFTP session is closed
            if sftp:
                try:
                    sftp.close()
                except Exception as e:
                    ic(f"Warning: Error closing SFTP session: {e}")

            # Ensure SSH connection is closed
            try:
                ssh.close()
            except Exception as e:
                ic(f"Warning: Error closing SSH connection: {e}")
        
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
            # Update host data with new connection info
            self.host_data["hostnames"][self.temp_hostname] = self.temp_hostname
            self.host_data["usernames"][self.temp_hostname] = self.temp_username
            self.host_data["passwords"][self.temp_hostname] = self.temp_password
            self.host_data["ports"][self.temp_hostname] = str(self.temp_port)
            self.host_data["key"][self.temp_hostname] = self.temp_key

            # Save to file
            if not save_connection_data(self.host_data):
                self.message_signal.emit("Failed to save connection data")
            else:
                self.message_signal.emit("Connection data saved successfully")
                
            self.update_completer()
        except Exception as e:
            self.message_signal.emit(f"Error saving connection data: {str(e)}")

    def navigate_to_initial_directories(self):
        """Navigate to initial directories if configured for the current hostname"""
        try:
            # Get initial directories from host_data
            initial_remote = self.host_data.get("initial_remote_dir", {}).get(self.temp_hostname, "")
            initial_local = self.host_data.get("initial_local_dir", {}).get(self.temp_hostname, "")
            
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
                except Exception as e:
                    self.message_signal.emit(f"Warning: Could not change to local directory {initial_local}: {e}")
        except Exception as e:
            self.message_signal.emit(f"Warning: Could not navigate to initial directories: {e}")

    def create_initial_data(self):
        """
        Create initial data for the application.
        This includes defining the data to be written to the JSON file.
        """
        # Example data for demonstration purposes
        self.host_data = {
            "localhost": {
                "username": "guest",
                "password": "WjNWbGMzUT0=",  # Note: This should be securely stored/encrypted
                "port": 22,  # Port should be an integer
                "key": "None"
            }
        }
            
    def cleanup(self):
        if hasattr(self, '_cleanup_performed') and self._cleanup_performed:
            return
        self._cleanup_performed = True

        ic("Cleanup method called")
        try:
            # Stop background thread first (prevents new work)
            self.stop_background_thread()

            # Clear the SFTP queue
            from sftp_downloadworkerclass import clear_sftp_queue
            clear_sftp_queue()

            # Close SFTP connections
            self.close_sftp_connections()

            # Save connection data
            try:
                save_connection_data(self.host_data)
            except Exception as e:
                ic(f"Error saving connection data: {e}")
        except Exception as e:
            ic(f"Error during cleanup: {str(e)}")
        ic("All cleanup tasks completed.")

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
            except Exception as e:
                ic(f"Error closing SFTP connection: {e}")

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
                    except Exception:
                        pass

                # Wait for thread pool to finish (up to 2 seconds)
                if hasattr(self.transfer_queue_widget, 'thread_pool'):
                    self.transfer_queue_widget.thread_pool.waitForDone(2000)

                # Force clear the queue
                from sftp_downloadworkerclass import clear_sftp_queue
                clear_sftp_queue()
        except Exception as e:
            print(f"Error stopping background thread: {e}")

    def closeEvent(self, event):
        """Handle application close"""
        try:
            # Check if there are active transfers
            active_count = 0
            if hasattr(self, 'transfer_queue_widget'):
                with QMutexLocker(self.transfer_queue_widget._active_transfers_lock):
                    active_count = self.transfer_queue_widget.active_transfers

            if active_count > 0:
                reply = QMessageBox.question(
                    self, 'Confirm Exit',
                    f'There are {active_count} active file transfers. Are you sure you want to exit?',
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if reply == QMessageBox.No:
                    event.ignore()
                    return

            # Accept the close event first to allow cleanup to happen
            # The actual cleanup will be handled by the aboutToQuit signal
            event.accept()
        except Exception as e:
            print(f"Error during application shutdown: {e}")
            import traceback
            traceback.print_exc()
            event.accept()  # Force exit on error

    def eventFilter(self, source, event):
        """Handle events for child widgets"""
        return super().eventFilter(source, event)

def main():
    ic.enable()
    clear_all_credentials()  # Clear any stale credentials from previous runs
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="FTP/SFTP Client")
    parser.add_argument("-H", "--hostname", help="Initial hostname to connect to")
    parser.add_argument("-u", "--username", help="Username for the connection")
    parser.add_argument("-p", "--password", help="Password for the connection")
    parser.add_argument("-P", "--port", type=int, default=22, help="Port for the connection (default: 22)")
    parser.add_argument("-K", "--key", help="SSH key")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    app = QApplication(sys.argv)

    # Load connection data to check settings before creating main window
    host_data = load_connection_data()
    show_manager_on_startup = host_data.get("show_manager_on_startup", True)
    
    # List to store connection data from startup site manager (mutable)
    startup_connection = [None]
    
    # Show site manager on startup if enabled and no command line hostname provided
    # We'll show the Connections tab in the main window instead of a separate dialog
    # The Connections tab is already integrated in MainWindow
    if show_manager_on_startup and not args.hostname:
        pass  # MainWindow will show Connections tab by default when created
    
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
        except Exception as e:
            ic("Error connecting:", e)

    # Connect the aboutToQuit signal directly to the cleanup method
    app.aboutToQuit.connect(main_window.cleanup)

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
