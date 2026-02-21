import sys
import os
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QMessageBox, QHeaderView,
    QLineEdit, QLabel, QFormLayout, QGroupBox, QTextEdit,
    QComboBox, QSpinBox, QCheckBox, QSplitter, QFileDialog,
    QCompleter, QFrame
)
from PyQt6.QtGui import QIntValidator
from sftp_qt_compat import Qt  # Use compatibility layer for Qt enums
from PyQt6.QtCore import pyqtSignal
import json
from cryptography.fernet import Fernet
from icecream import ic
from sftp_theme import CONNECT_BUTTON_STYLE, BUTTON_STYLE_DARK

encryption_key = []
cipher_suite = []

def save_connection_data(host_data):
    global encryption_key, cipher_suite
    try:
        # Ensure the data structure is complete
        if not all(key in host_data for key in ["hostnames", "usernames", "passwords", "ports", "key"]):
            raise ValueError("Incomplete host data structure")

        # Encrypt passwords
        encrypted_passwords = {k: cipher_suite.encrypt(v.encode()).decode() 
                             for k, v in host_data["passwords"].items()}

        data = {
            "hostnames": host_data["hostnames"],
            "usernames": host_data["usernames"],
            "passwords": encrypted_passwords,
            "ports": host_data["ports"],
            "key" : host_data["key"],
            "connection_type": host_data.get("connection_type", {}),
            "initial_remote_dir": host_data.get("initial_remote_dir", {}),
            "initial_local_dir": host_data.get("initial_local_dir", {}),
            "show_manager_on_startup": host_data.get("show_manager_on_startup", True),
            "bookmarks": host_data.get("bookmarks", {}),
            "encryption_key": encryption_key.decode() if isinstance(encryption_key, bytes) else encryption_key
        }

        # Save to file with proper error handling
        filepath = os.path.join(os.path.expanduser('~'), '.sftp_client_connection_data.json')
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=4)  # Add indentation for better readability
        return True
    except PermissionError as e:
        ic(f"Permission denied saving connection data: {e}")
        return False
    except OSError as e:
        ic(f"OS error saving connection data: {e}")
        return False
    except (OSError, IOError, RuntimeError) as e:
        ic(f"Error saving connection data: {e}")
        return False

def load_connection_data():
    global encryption_key, cipher_suite
    host_data = {
        "hostnames": {}, "usernames": {}, "passwords": {}, "ports": {}, "key": {},
        "connection_type": {}, "initial_remote_dir": {}, "initial_local_dir": {}, "show_manager_on_startup": True,
        "bookmarks": {}
    }

    try:
        # Check if file exists and is readable
        filepath = os.path.join(os.path.expanduser('~'), '.sftp_client_connection_data.json')
        
        # Try new location first, then old location for backwards compatibility
        if not os.path.exists(filepath):
            old_filepath = 'connection_data.json'
            if os.path.exists(old_filepath):
                filepath = old_filepath
            else:
                raise FileNotFoundError("Connection data file not found")

        with open(filepath, 'r') as f:
            data = json.load(f)

        # Validate encryption key
        encryption_key = data.get("encryption_key", Fernet.generate_key())
        if not isinstance(encryption_key, (str, bytes)):
            raise ValueError("Invalid encryption key format")
            
        cipher_suite = Fernet(encryption_key)

        # Load and validate data
        host_data["hostnames"] = data.get("hostnames", {})
        host_data["usernames"] = data.get("usernames", {})
        
        # Decrypt passwords with error handling
        encrypted_passwords = data.get("passwords", {})
        host_data["passwords"] = {}
        for k, v in encrypted_passwords.items():
            try:
                host_data["passwords"][k] = cipher_suite.decrypt(v.encode()).decode()
            except (OSError, IOError, RuntimeError) as e:
                print(f"Error decrypting password for {k}: {str(e)}")
                host_data["passwords"][k] = ""  # Set empty password if decryption fails
                
        host_data["ports"] = data.get("ports", {})
        host_data["key"] = data.get("key", {})
        
        # Load new fields (with defaults for backwards compatibility)
        host_data["connection_type"] = data.get("connection_type", {})
        host_data["initial_remote_dir"] = data.get("initial_remote_dir", {})
        host_data["initial_local_dir"] = data.get("initial_local_dir", {})
        host_data["show_manager_on_startup"] = data.get("show_manager_on_startup", True)
        host_data["bookmarks"] = data.get("bookmarks", {})

        return host_data

    except FileNotFoundError:
        # If the file doesn't exist, generate a new encryption key
        encryption_key = Fernet.generate_key()
        cipher_suite = Fernet(encryption_key)
        return host_data
        
    except json.JSONDecodeError:
        print("Error: Invalid JSON format in connection data file")
        encryption_key = Fernet.generate_key()
        cipher_suite = Fernet(encryption_key)
        return host_data
        
    except (OSError, IOError, RuntimeError) as e:
        print(f"Error loading connection data: {str(e)}")
        encryption_key = Fernet.generate_key()
        cipher_suite = Fernet(encryption_key)
        return host_data

class HostDataEditor(QDialog):  # Change QWidget to QDialog
    # Signal emitted when user wants to connect to a site
    connect_requested = pyqtSignal(dict)
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Site Manager")
        self.resize(900, 600)  # Wider to accommodate split panel
        
        # Main horizontal layout with splitter
        main_layout = QHBoxLayout()
        
        # Left panel - Site list
        left_panel = QVBoxLayout()
        
        # Toolbar with action buttons
        toolbar_layout = QHBoxLayout()
        
        self.add_button = QPushButton("+ Add Site")
        self.add_button.setToolTip("Add a new site")
        self.add_button.setStyleSheet(BUTTON_STYLE_DARK)
        self.add_button.clicked.connect(self.add_row)
        
        self.delete_button = QPushButton("- Delete")
        self.delete_button.setToolTip("Delete selected site")
        self.delete_button.setStyleSheet(BUTTON_STYLE_DARK)
        self.delete_button.clicked.connect(self.delete_row)
        
        self.save_button = QPushButton("💾 Save")
        self.save_button.setToolTip("Save all changes")
        self.save_button.setStyleSheet(BUTTON_STYLE_DARK)
        self.save_button.clicked.connect(self.save_data)
        
        toolbar_layout.addWidget(self.add_button)
        toolbar_layout.addWidget(self.delete_button)
        toolbar_layout.addStretch()
        toolbar_layout.addWidget(self.save_button)
        
        left_panel.addLayout(toolbar_layout)
        
        # Site list table - simplified columns
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Hostname", "Username", "Port"])
        self.table.setSelectionBehavior(Qt.TableWidget_SelectRows)
        self.table.setSelectionMode(Qt.TableWidget_SingleSelection)
        
        # Set column resize modes
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, Qt.HeaderView_Stretch)
        header.setSectionResizeMode(1, Qt.HeaderView_Stretch)
        header.setSectionResizeMode(2, Qt.HeaderView_ResizeToContents)
        
        # Connect signals
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        self.table.cellDoubleClicked.connect(self.on_cell_double_clicked)
        
        left_panel.addWidget(self.table)
        
        # Status label
        self.status_label = QLabel("0 sites configured")
        left_panel.addWidget(self.status_label)
        
        # Right panel - Connection details
        right_panel = QVBoxLayout()
        
        # Details group
        details_group = QGroupBox("Connection Details")
        details_layout = QFormLayout()
        
        # Connection fields
        self.detail_hostname = QLineEdit()
        self.detail_hostname.setPlaceholderText("example.com")
        self.detail_hostname.textChanged.connect(self.update_selected_row)
        
        self.detail_username = QLineEdit()
        self.detail_username.setPlaceholderText("username")
        self.detail_username.textChanged.connect(self.update_selected_row)
        
        self.detail_password = QLineEdit()
        self.detail_password.setPlaceholderText("password")
        self.detail_password.setEchoMode(Qt.Password)
        self.detail_password.textChanged.connect(self.update_selected_row)
        
        self.detail_port = QLineEdit()
        self.detail_port.setPlaceholderText("22")
        self.detail_port.setMaximumWidth(80)
        # Add validator to ensure only valid port numbers (1-65535)
        port_validator = QIntValidator(1, 65535, self)
        self.detail_port.setValidator(port_validator)
        self.detail_port.textChanged.connect(self.update_selected_row)
        
        self.detail_key = QLineEdit()
        self.detail_key.setPlaceholderText("Path to SSH key (optional)")
        self.detail_key.textChanged.connect(self.update_selected_row)
        
        # Advanced section
        self.detail_remote_dir = QLineEdit()
        self.detail_remote_dir.setPlaceholderText("/home/user (optional)")
        self.detail_remote_dir.textChanged.connect(self.update_selected_row)
        
        self.detail_local_dir = QLineEdit()
        self.detail_local_dir.setPlaceholderText("/path/to/local (optional)")
        self.detail_local_dir.textChanged.connect(self.update_selected_row)
        
        # Add fields to form
        details_layout.addRow("Hostname:", self.detail_hostname)
        details_layout.addRow("Username:", self.detail_username)
        details_layout.addRow("Password:", self.detail_password)
        details_layout.addRow("Port:", self.detail_port)
        details_layout.addRow("SSH Key:", self.detail_key)
        
        # Add separator
        line = QFrame()
        line.setFrameShape(Qt.Frame_HLine)
        line.setFrameShadow(Qt.Frame_Sunken)
        details_layout.addRow(line)
        
        details_layout.addRow("Initial Remote Dir:", self.detail_remote_dir)
        details_layout.addRow("Initial Local Dir:", self.detail_local_dir)
        
        details_group.setLayout(details_layout)
        right_panel.addWidget(details_group)
        
        # Connect button
        self.connect_button = QPushButton("🚀 Connect")
        self.connect_button.setToolTip("Connect to selected site")
        self.connect_button.setMinimumHeight(40)
        self.connect_button.setStyleSheet(CONNECT_BUTTON_STYLE)
        self.connect_button.clicked.connect(self.connect_to_selected)
        right_panel.addWidget(self.connect_button)
        
        right_panel.addStretch()
        
        # Checkbox for showing manager on startup
        self.show_on_startup_checkbox = QCheckBox("Show site manager on startup")
        self.show_on_startup_checkbox.setChecked(True)
        right_panel.addWidget(self.show_on_startup_checkbox)
        
        # Add panels to main layout with splitter
        left_widget = QWidget()
        left_widget.setLayout(left_panel)
        left_widget.setMinimumWidth(350)
        
        right_widget = QWidget()
        right_widget.setLayout(right_panel)
        right_widget.setMinimumWidth(300)
        
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([400, 400])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        
        main_layout.addWidget(splitter)
        self.setLayout(main_layout)

        # Initialize host_data before loading data
        self.host_data = {
            "hostnames": {}, 
            "usernames": {}, 
            "passwords": {}, 
            "ports": {}, 
            "key": {},
            "initial_remote_dir": {},
            "initial_local_dir": {},
            "bookmarks": {}
        }
        
        # Load the data
        self.host_data = self.load_data()
        self.update_table()
        
        # Initially disable detail panel
        self.set_details_enabled(False)

    def on_selection_changed(self):
        """Update detail panel when table selection changes"""
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            self.load_details_from_row(selected_row)
            self.set_details_enabled(True)
        else:
            self.clear_details()
            self.set_details_enabled(False)

    def on_cell_double_clicked(self, row, column):
        """Handle double-click on table cell - connect to site"""
        self.connect_to_selected()

    def load_details_from_row(self, row):
        """Load site details from table row into form fields"""
        hostname_item = self.table.item(row, 0)
        if hostname_item:
            hostname = hostname_item.text()
            
            # Block signals temporarily to prevent recursion
            self.detail_hostname.blockSignals(True)
            self.detail_username.blockSignals(True)
            self.detail_password.blockSignals(True)
            self.detail_port.blockSignals(True)
            self.detail_key.blockSignals(True)
            self.detail_remote_dir.blockSignals(True)
            self.detail_local_dir.blockSignals(True)
            
            self.detail_hostname.setText(hostname)
            self.detail_username.setText(self.host_data["usernames"].get(hostname, ""))
            self.detail_password.setText(self.host_data["passwords"].get(hostname, ""))
            self.detail_port.setText(str(self.host_data["ports"].get(hostname, 22)))
            self.detail_key.setText(self.host_data["key"].get(hostname, ""))
            self.detail_remote_dir.setText(self.host_data["initial_remote_dir"].get(hostname, ""))
            self.detail_local_dir.setText(self.host_data["initial_local_dir"].get(hostname, ""))
            
            # Re-enable signals
            self.detail_hostname.blockSignals(False)
            self.detail_username.blockSignals(False)
            self.detail_password.blockSignals(False)
            self.detail_port.blockSignals(False)
            self.detail_key.blockSignals(False)
            self.detail_remote_dir.blockSignals(False)
            self.detail_local_dir.blockSignals(False)

    def clear_details(self):
        """Clear all detail form fields"""
        self.detail_hostname.clear()
        self.detail_username.clear()
        self.detail_password.clear()
        self.detail_port.clear()
        self.detail_key.clear()
        self.detail_remote_dir.clear()
        self.detail_local_dir.clear()

    def set_details_enabled(self, enabled):
        """Enable or disable detail panel"""
        self.detail_hostname.setEnabled(enabled)
        self.detail_username.setEnabled(enabled)
        self.detail_password.setEnabled(enabled)
        self.detail_port.setEnabled(enabled)
        self.detail_key.setEnabled(enabled)
        self.detail_remote_dir.setEnabled(enabled)
        self.detail_local_dir.setEnabled(enabled)
        self.connect_button.setEnabled(enabled)

    def update_selected_row(self):
        """Update table row when form fields change"""
        selected_row = self.table.currentRow()
        if selected_row < 0:
            return
        
        hostname = self.detail_hostname.text()
        username = self.detail_username.text()
        port = self.detail_port.text() or "22"
        
        # Update table display
        self.table.item(selected_row, 0).setText(hostname)
        self.table.item(selected_row, 1).setText(username)
        self.table.item(selected_row, 2).setText(port)
        
        # Update host_data
        old_hostname = list(self.host_data["hostnames"].keys())[selected_row] if selected_row < len(self.host_data["hostnames"]) else None
        
        if old_hostname and old_hostname != hostname:
            # Hostname changed - migrate data
            self.migrate_host_data(old_hostname, hostname)
        
        self.host_data["hostnames"][hostname] = hostname
        self.host_data["usernames"][hostname] = username
        self.host_data["passwords"][hostname] = self.detail_password.text()
        self.host_data["ports"][hostname] = int(port)
        self.host_data["key"][hostname] = self.detail_key.text()
        self.host_data["initial_remote_dir"][hostname] = self.detail_remote_dir.text()
        self.host_data["initial_local_dir"][hostname] = self.detail_local_dir.text()

    def migrate_host_data(self, old_hostname, new_hostname):
        """Migrate data when hostname changes"""
        for key in ["usernames", "passwords", "ports", "key", "initial_remote_dir", "initial_local_dir", "bookmarks"]:
            if old_hostname in self.host_data[key]:
                self.host_data[key][new_hostname] = self.host_data[key].pop(old_hostname)

    def load_data(self):
        try:
            data = load_connection_data()
            self.update_table()
            return data
        except (OSError, IOError, RuntimeError) as e:
            QMessageBox.critical(self, "Error", f"Failed to load data: {str(e)}")

    def add_row(self):
        row_count = self.table.rowCount()
        self.table.insertRow(row_count)

    def delete_row(self):
        """Delete the selected site"""
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            hostname_item = self.table.item(selected_row, 0)
            if hostname_item:
                hostname = hostname_item.text()
                # Confirm deletion
                reply = QMessageBox.question(self, "Confirm Delete",
                                            f"Delete site '{hostname}'?",
                                            Qt.MsgBtn_Yes | Qt.MsgBtn_No,
                                            Qt.MsgBtn_No)
                if reply == Qt.MsgBtn_Yes:
                    # Remove the corresponding data from host_data
                    self.host_data["hostnames"].pop(hostname, None)
                    self.host_data["usernames"].pop(hostname, None)
                    self.host_data["passwords"].pop(hostname, None)
                    self.host_data["ports"].pop(hostname, None)
                    self.host_data["key"].pop(hostname, None)
                    self.host_data["initial_remote_dir"].pop(hostname, None)
                    self.host_data["initial_local_dir"].pop(hostname, None)
                    self.host_data["bookmarks"].pop(hostname, None)
                    self.table.removeRow(selected_row)
                    self.clear_details()
                    self.set_details_enabled(False)
                    self.update_table()
        else:
            QMessageBox.warning(self, "No selection", "Please select a site to delete.")

    def save_data(self):
        """Save all site data"""
        try:
            # Ensure current form data is saved to host_data
            selected_row = self.table.currentRow()
            if selected_row >= 0:
                self.update_selected_row()
            
            # Validate data
            for hostname in self.host_data["hostnames"]:
                if not hostname:
                    raise ValueError("Hostname cannot be empty")
                if not self.host_data["usernames"].get(hostname):
                    raise ValueError(f"Username required for {hostname}")
                if not self.host_data["passwords"].get(hostname) and not self.host_data["key"].get(hostname):
                    raise ValueError(f"Password or SSH key required for {hostname}")
            
            # Save the show_on_startup setting
            self.host_data["show_manager_on_startup"] = self.show_on_startup_checkbox.isChecked()

            # Save the data using the parent's save function
            if save_connection_data(self.host_data):
                QMessageBox.information(self, "Success", "Sites saved successfully!")
            else:
                QMessageBox.critical(self, "Error", "Failed to save site data")
        except ValueError as e:
            QMessageBox.critical(self, "Validation Error", str(e))
        except (OSError, IOError, RuntimeError) as e:
            QMessageBox.critical(self, "Unknown Error", f"An error occurred: {str(e)}")

    def connect_to_selected(self):
        """Connect to the selected site"""
        selected_row = self.table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "No Selection", "Please select a site to connect to.")
            return
        
        # Get hostname from table
        hostname_item = self.table.item(selected_row, 0)
        if not hostname_item:
            QMessageBox.critical(self, "Error", "Selected site is missing hostname.")
            return
        
        hostname = hostname_item.text()
        
        # Get full data from host_data dictionary
        username = self.host_data["usernames"].get(hostname, "")
        password = self.host_data["passwords"].get(hostname, "")
        port = self.host_data["ports"].get(hostname, 22)
        key = self.host_data["key"].get(hostname, "None") or "None"
        initial_remote_dir = self.host_data["initial_remote_dir"].get(hostname, "")
        initial_local_dir = self.host_data["initial_local_dir"].get(hostname, "")
        
        # Validate required fields
        if not username:
            QMessageBox.critical(self, "Error", f"Username required for {hostname}")
            return
        if not password and key == "None":
            QMessageBox.critical(self, "Error", f"Password or SSH key required for {hostname}")
            return
        
        # Emit signal with connection data
        connection_data = {
            "hostname": hostname,
            "username": username,
            "password": password,
            "port": port,
            "key": key,
            "initial_remote_dir": initial_remote_dir,
            "initial_local_dir": initial_local_dir
        }
        
        self.connect_requested.emit(connection_data)
        self.accept()  # Close the dialog

    def update_table(self):
        """Update table with current host data"""
        self.table.setRowCount(len(self.host_data["hostnames"]))
        for i, hostname in enumerate(self.host_data["hostnames"]):
            self.table.setItem(i, 0, QTableWidgetItem(hostname))
            self.table.setItem(i, 1, QTableWidgetItem(self.host_data["usernames"].get(hostname, "")))
            self.table.setItem(i, 2, QTableWidgetItem(str(self.host_data["ports"].get(hostname, 22))))
        
        # Update status label
        count = len(self.host_data["hostnames"])
        self.status_label.setText(f"{count} site{'s' if count != 1 else ''} configured")
        
        # Set the checkbox state based on saved setting
        show_on_startup = self.host_data.get("show_manager_on_startup", True)
        self.show_on_startup_checkbox.setChecked(show_on_startup)

    def closeEvent(self, event):
        # Save data when the window is closed
        try:
            self.save_data()  # Call save_data() to collect and save the data
        except (OSError, IOError, RuntimeError) as e:
            QMessageBox.critical(self, "Error", f"Failed to save data on close: {str(e)}")
        event.accept()  # Accept the close event
