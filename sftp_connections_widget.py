import os
from PyQt6.QtWidgets import (
    QWidget, QPushButton, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QMessageBox, QHeaderView,
    QLineEdit, QLabel, QFormLayout, QGroupBox, QSplitter, QFrame,
    QCheckBox, QComboBox
)
from PyQt6.QtGui import QIntValidator
from sftp_qt_compat import Qt  # Use compatibility layer for Qt enums
from PyQt6.QtCore import pyqtSignal
from icecream import ic

from sftp_hostdataeditor import save_connection_data, load_connection_data
from sftp_theme import CONNECT_BUTTON_STYLE, BUTTON_STYLE_DARK


class ConnectionsWidget(QWidget):
    """
    Connections/ Sites management widget for integration into main window.
    
    This provides the same functionality as HostDataEditor but as an embeddable
    widget that can be added as a tab in the main application window.
    
    Signals:
        connect_requested: Emitted when user wants to connect to a site
    """
    
    connect_requested = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.host_data = None
        self._init_ui()
        self._load_data()
    
    def _init_ui(self):
        """Initialize the UI"""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(10)
        
        # Header with toolbar
        toolbar_layout = QHBoxLayout()
        
        self.add_button = QPushButton("+ Add Site")
        self.add_button.setToolTip("Add a new site")
        self.add_button.setStyleSheet(BUTTON_STYLE_DARK)
        self.add_button.clicked.connect(self.add_row)
        toolbar_layout.addWidget(self.add_button)
        
        self.delete_button = QPushButton("- Delete")
        self.delete_button.setToolTip("Delete selected site")
        self.delete_button.setStyleSheet(BUTTON_STYLE_DARK)
        self.delete_button.clicked.connect(self.delete_row)
        toolbar_layout.addWidget(self.delete_button)
        
        self.copy_button = QPushButton("📋 Copy")
        self.copy_button.setToolTip("Copy selected site")
        self.copy_button.setStyleSheet(BUTTON_STYLE_DARK)
        self.copy_button.clicked.connect(self.copy_row)
        toolbar_layout.addWidget(self.copy_button)
        
        toolbar_layout.addStretch()
        
        self.save_button = QPushButton("💾 Save")
        self.save_button.setToolTip("Save all changes")
        self.save_button.setStyleSheet(BUTTON_STYLE_DARK)
        self.save_button.clicked.connect(self.save_data)
        toolbar_layout.addWidget(self.save_button)
        
        main_layout.addLayout(toolbar_layout)
        
        # Main content with splitter
        content_layout = QHBoxLayout()
        content_layout.setSpacing(10)
        
        # Left panel - Site list
        left_panel = QVBoxLayout()
        left_panel.setSpacing(5)
        
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Hostname", "Username", "Port", "Type"])
        self.table.setSelectionBehavior(Qt.TableWidget_SelectRows)
        self.table.setSelectionMode(Qt.TableWidget_SingleSelection)
        self.table.setMinimumHeight(150)
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, Qt.HeaderView_Stretch)
        header.setSectionResizeMode(1, Qt.HeaderView_Stretch)
        header.setSectionResizeMode(2, Qt.HeaderView_ResizeToContents)
        header.setSectionResizeMode(3, Qt.HeaderView_ResizeToContents)
        
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        self.table.cellDoubleClicked.connect(self.on_cell_double_clicked)
        
        left_panel.addWidget(self.table)
        
        self.status_label = QLabel("0 sites configured")
        left_panel.addWidget(self.status_label)
        
        left_widget = QWidget()
        left_widget.setLayout(left_panel)
        left_widget.setMinimumWidth(300)
        
        # Right panel - Connection details
        right_panel = QVBoxLayout()
        right_panel.setSpacing(10)
        
        details_group = QGroupBox("Connection Details")
        details_layout = QFormLayout()
        details_layout.setSpacing(8)
        
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
        port_validator = QIntValidator(1, 65535, self)
        self.detail_port.setValidator(port_validator)
        self.detail_port.textChanged.connect(self.update_selected_row)
        
        self.detail_key = QLineEdit()
        self.detail_key.setPlaceholderText("Path to SSH key (optional)")
        self.detail_key.textChanged.connect(self.update_selected_row)
        
        self.detail_remote_dir = QLineEdit()
        self.detail_remote_dir.setPlaceholderText("/home/user (optional)")
        self.detail_remote_dir.textChanged.connect(self.update_selected_row)
        
        self.detail_local_dir = QLineEdit()
        self.detail_local_dir.setPlaceholderText("/path/to/local (optional)")
        self.detail_local_dir.textChanged.connect(self.update_selected_row)
        
        self.detail_connection_type = QComboBox()
        self.detail_connection_type.addItems(["SFTP Browser", "SSH Terminal"])
        self.detail_connection_type.setCurrentIndex(0)
        self.detail_connection_type.currentIndexChanged.connect(self.update_selected_row)
        
        self.detail_ssh_commands = QLineEdit()
        self.detail_ssh_commands.setPlaceholderText("Commands to run on connect (one per line, SSH Terminal only)")
        self.detail_ssh_commands.textChanged.connect(self.update_selected_row)
        
        details_layout.addRow("Hostname:", self.detail_hostname)
        details_layout.addRow("Username:", self.detail_username)
        details_layout.addRow("Password:", self.detail_password)
        details_layout.addRow("Port:", self.detail_port)
        details_layout.addRow("SSH Key:", self.detail_key)
        details_layout.addRow("Connection Type:", self.detail_connection_type)
        details_layout.addRow("Startup Commands:", self.detail_ssh_commands)
        
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
        self.connect_button.setMinimumHeight(35)
        self.connect_button.setStyleSheet(CONNECT_BUTTON_STYLE)
        self.connect_button.clicked.connect(self.connect_to_selected)
        right_panel.addWidget(self.connect_button)
        
        right_panel.addStretch()
        
        # Checkbox for showing manager on startup
        self.show_on_startup_checkbox = QCheckBox("Show site manager on startup")
        right_panel.addWidget(self.show_on_startup_checkbox)
        
        right_widget = QWidget()
        right_widget.setLayout(right_panel)
        right_widget.setMinimumWidth(280)
        
        # Splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([350, 350])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        
        content_layout.addWidget(splitter)
        main_layout.addLayout(content_layout)
        
        self.setLayout(main_layout)
        
        # Initially disable detail panel
        self._set_details_enabled(False)
    
    def _load_data(self):
        """Load connection data"""
        try:
            self.host_data = load_connection_data()
            for key in ["connection_type", "initial_remote_dir", "initial_local_dir", "bookmarks", "ssh_commands"]:
                if key not in self.host_data:
                    self.host_data[key] = {}
            self._update_table()
        except (OSError, IOError, RuntimeError) as e:
            QMessageBox.critical(self, "Error", f"Failed to load data: {str(e)}")
            self.host_data = {
                "hostnames": {}, 
                "usernames": {}, 
                "passwords": {}, 
                "ports": {}, 
                "key": {},
                "connection_type": {},
                "initial_remote_dir": {},
                "initial_local_dir": {},
                "bookmarks": {},
                "ssh_commands": {}
            }
    
    def _on_selection_changed(self):
        """Handle selection change"""
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            self._load_details_from_row(selected_row)
            self._set_details_enabled(True)
        else:
            self._clear_details()
            self._set_details_enabled(False)
    
    def _on_cell_double_clicked(self, row, column):
        """Handle double-click - connect to site"""
        self.connect_to_selected()
    
    def _load_details_from_row(self, row):
        """Load details from table row"""
        hostname_item = self.table.item(row, 0)
        if hostname_item:
            hostname = hostname_item.text()
            
            # Block signals temporarily
            for widget in [self.detail_hostname, self.detail_username, self.detail_password,
                          self.detail_port, self.detail_key, self.detail_remote_dir, 
                          self.detail_local_dir, self.detail_ssh_commands]:
                widget.blockSignals(True)
            self.detail_connection_type.blockSignals(True)
            
            self.detail_hostname.setText(hostname)
            self.detail_username.setText(self.host_data["usernames"].get(hostname, ""))
            self.detail_password.setText(self.host_data["passwords"].get(hostname, ""))
            self.detail_port.setText(str(self.host_data["ports"].get(hostname, 22)))
            self.detail_key.setText(self.host_data["key"].get(hostname, ""))
            self.detail_remote_dir.setText(self.host_data["initial_remote_dir"].get(hostname, ""))
            self.detail_local_dir.setText(self.host_data["initial_local_dir"].get(hostname, ""))
            self.detail_ssh_commands.setText(self.host_data["ssh_commands"].get(hostname, ""))
            
            connection_type = self.host_data["connection_type"].get(hostname, "SFTP Browser")
            if connection_type == "SSH Terminal":
                self.detail_connection_type.setCurrentIndex(1)
            else:
                self.detail_connection_type.setCurrentIndex(0)
            
            for widget in [self.detail_hostname, self.detail_username, self.detail_password,
                          self.detail_port, self.detail_key, self.detail_remote_dir, 
                          self.detail_local_dir, self.detail_ssh_commands]:
                widget.blockSignals(False)
            self.detail_connection_type.blockSignals(False)
    
    def _clear_details(self):
        """Clear all detail fields"""
        for widget in [self.detail_hostname, self.detail_username, self.detail_password,
                      self.detail_port, self.detail_key, self.detail_remote_dir, 
                      self.detail_local_dir, self.detail_ssh_commands]:
            widget.clear()
        self.detail_connection_type.setCurrentIndex(0)
    
    def _set_details_enabled(self, enabled):
        """Enable/disable detail panel"""
        for widget in [self.detail_hostname, self.detail_username, self.detail_password,
                      self.detail_port, self.detail_key, self.detail_remote_dir, 
                      self.detail_local_dir, self.detail_ssh_commands,
                      self.connect_button, self.detail_connection_type]:
            widget.setEnabled(enabled)
    
    def _update_selected_row(self):
        """Update table when form fields change"""
        selected_row = self.table.currentRow()
        if selected_row < 0:
            return
        
        for key in ["connection_type", "initial_remote_dir", "initial_local_dir", "ssh_commands"]:
            if key not in self.host_data:
                self.host_data[key] = {}
        
        hostname = self.detail_hostname.text()
        username = self.detail_username.text()
        port = self.detail_port.text() or "22"
        
        self.table.item(selected_row, 0).setText(hostname)
        self.table.item(selected_row, 1).setText(username)
        self.table.item(selected_row, 2).setText(port)
        self.table.item(selected_row, 3).setText(self.detail_connection_type.currentText())
        
        old_hostnames = list(self.host_data["hostnames"].keys())
        old_hostname = old_hostnames[selected_row] if selected_row < len(old_hostnames) else None
        
        if old_hostname and old_hostname != hostname:
            self._migrate_host_data(old_hostname, hostname)
        
        self.host_data["hostnames"][hostname] = hostname
        self.host_data["usernames"][hostname] = username
        self.host_data["passwords"][hostname] = self.detail_password.text()
        self.host_data["ports"][hostname] = int(port)
        self.host_data["key"][hostname] = self.detail_key.text()
        self.host_data["connection_type"][hostname] = self.detail_connection_type.currentText()
        self.host_data["initial_remote_dir"][hostname] = self.detail_remote_dir.text()
        self.host_data["initial_local_dir"][hostname] = self.detail_local_dir.text()
        self.host_data["ssh_commands"][hostname] = self.detail_ssh_commands.text()
    
    def _migrate_host_data(self, old_hostname, new_hostname):
        """Migrate data when hostname changes"""
        for key in ["usernames", "passwords", "ports", "key", "connection_type", "initial_remote_dir", "initial_local_dir", "bookmarks", "ssh_commands"]:
            if key in self.host_data and old_hostname in self.host_data[key]:
                self.host_data[key][new_hostname] = self.host_data[key].pop(old_hostname)
    
    def _update_table(self):
        """Update table with current host data"""
        self.table.setRowCount(len(self.host_data["hostnames"]))
        for i, hostname in enumerate(self.host_data["hostnames"]):
            self.table.setItem(i, 0, QTableWidgetItem(hostname))
            self.table.setItem(i, 1, QTableWidgetItem(self.host_data["usernames"].get(hostname, "")))
            self.table.setItem(i, 2, QTableWidgetItem(str(self.host_data["ports"].get(hostname, 22))))
            connection_type = self.host_data["connection_type"].get(hostname, "SFTP Browser")
            self.table.setItem(i, 3, QTableWidgetItem(connection_type))
        
        count = len(self.host_data["hostnames"])
        self.status_label.setText(f"{count} site{'s' if count != 1 else ''} configured")
        
        show_on_startup = self.host_data.get("show_manager_on_startup", True)
        self.show_on_startup_checkbox.setChecked(show_on_startup)
    
    def add_row(self):
        """Add a new empty row"""
        for key in ["connection_type", "initial_remote_dir", "initial_local_dir", "ssh_commands"]:
            if key not in self.host_data:
                self.host_data[key] = {}
        
        new_hostname = ""
        counter = 1
        while new_hostname in self.host_data["hostnames"] or new_hostname == "":
            new_hostname = f"new_site_{counter}"
            counter += 1
        
        self.host_data["hostnames"][new_hostname] = new_hostname
        self.host_data["usernames"][new_hostname] = ""
        self.host_data["passwords"][new_hostname] = ""
        self.host_data["ports"][new_hostname] = 22
        self.host_data["key"][new_hostname] = ""
        self.host_data["connection_type"][new_hostname] = "SFTP Browser"
        self.host_data["initial_remote_dir"][new_hostname] = ""
        self.host_data["initial_local_dir"][new_hostname] = ""
        self.host_data["ssh_commands"][new_hostname] = ""
        
        self._update_table()
        
        for i in range(self.table.rowCount()):
            if self.table.item(i, 0) and self.table.item(i, 0).text() == new_hostname:
                self.table.setCurrentCell(i, 0)
                break
        
        self._set_details_enabled(True)
        self.detail_hostname.setFocus()
        self.detail_hostname.selectAll()
    
    def delete_row(self):
        """Delete selected site"""
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            hostname_item = self.table.item(selected_row, 0)
            if hostname_item:
                hostname = hostname_item.text()
                reply = QMessageBox.question(
                    self, "Confirm Delete",
                    f"Delete site '{hostname}'?",
                    Qt.MsgBtn_Yes | Qt.MsgBtn_No,
                    Qt.MsgBtn_No
                )
                if reply == Qt.MsgBtn_Yes:
                    for key in ["hostnames", "usernames", "passwords", "ports", "key", 
                               "connection_type", "initial_remote_dir", "initial_local_dir", "bookmarks",
                               "ssh_commands"]:
                        if key in self.host_data:
                            self.host_data[key].pop(hostname, None)
                    self.table.removeRow(selected_row)
                    self._clear_details()
                    self._set_details_enabled(False)
                    self._update_table()
        else:
            QMessageBox.warning(self, "No selection", "Please select a site to delete.")
    
    def copy_row(self):
        """Copy selected site to a new entry"""
        selected_row = self.table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "No selection", "Please select a site to copy.")
            return
        
        hostname_item = self.table.item(selected_row, 0)
        if not hostname_item:
            return
        
        original_hostname = hostname_item.text()
        
        new_hostname = original_hostname
        counter = 1
        while new_hostname in self.host_data["hostnames"]:
            new_hostname = f"{original_hostname} (copy{counter})"
            counter += 1
        
        for key in ["usernames", "passwords", "ports", "key", "connection_type", 
                   "initial_remote_dir", "initial_local_dir", "ssh_commands"]:
            if key not in self.host_data:
                self.host_data[key] = {}
            if original_hostname in self.host_data[key]:
                self.host_data[key][new_hostname] = self.host_data[key][original_hostname]
        
        self.host_data["hostnames"][new_hostname] = new_hostname
        self._update_table()
        
        for i in range(self.table.rowCount()):
            if self.table.item(i, 0) and self.table.item(i, 0).text() == new_hostname:
                self.table.setCurrentCell(i, 0)
                break
        
        self._set_details_enabled(True)
        self.detail_hostname.setFocus()
        self.detail_hostname.selectAll()
    
    def save_data(self):
        """Save all site data"""
        try:
            for key in ["connection_type", "initial_remote_dir", "initial_local_dir", "ssh_commands"]:
                if key not in self.host_data:
                    self.host_data[key] = {}
            
            selected_row = self.table.currentRow()
            if selected_row >= 0:
                self._update_selected_row()
            
            orphaned = []
            for hostname in list(self.host_data["hostnames"].keys()):
                if not hostname or hostname not in self.host_data.get("usernames", {}):
                    orphaned.append(hostname)
            
            for hostname in orphaned:
                for key in ["hostnames", "usernames", "passwords", "ports", "key", 
                           "connection_type", "initial_remote_dir", "initial_local_dir", "bookmarks"]:
                    if key in self.host_data:
                        self.host_data[key].pop(hostname, None)
            
            for hostname in self.host_data["hostnames"]:
                if not hostname:
                    raise ValueError("Hostname cannot be empty")
                username = self.host_data.get("usernames", {}).get(hostname, "")
                if not username:
                    raise ValueError(f"Username required for '{hostname}'")
                password = self.host_data.get("passwords", {}).get(hostname, "")
                key = self.host_data.get("key", {}).get(hostname, "")
                if not password and not key:
                    raise ValueError(f"Password or SSH key required for '{hostname}'")
            
            self.host_data["show_manager_on_startup"] = self.show_on_startup_checkbox.isChecked()
            
            if save_connection_data(self.host_data):
                QMessageBox.information(self, "Success", "Sites saved successfully!")
                self._update_table()
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
        
        hostname_item = self.table.item(selected_row, 0)
        if not hostname_item:
            QMessageBox.critical(self, "Error", "Selected site is missing hostname.")
            return
        
        hostname = hostname_item.text()
        username = self.host_data["usernames"].get(hostname, "")
        password = self.host_data["passwords"].get(hostname, "")
        port = self.host_data["ports"].get(hostname, 22)
        key = self.host_data["key"].get(hostname, "None") or "None"
        initial_remote_dir = self.host_data["initial_remote_dir"].get(hostname, "")
        initial_local_dir = self.host_data["initial_local_dir"].get(hostname, "")
        connection_type = self.host_data["connection_type"].get(hostname, "SFTP Browser")
        ssh_commands = self.host_data["ssh_commands"].get(hostname, "")
        
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
            "connection_type": connection_type,
            "initial_remote_dir": initial_remote_dir,
            "initial_local_dir": initial_local_dir,
            "ssh_commands": ssh_commands
        }
        
        self.connect_requested.emit(connection_data)
    
    # Alias methods to match expected names from HostDataEditor
    on_selection_changed = _on_selection_changed
    on_cell_double_clicked = _on_cell_double_clicked
    load_details_from_row = _load_details_from_row
    clear_details = _clear_details
    set_details_enabled = _set_details_enabled
    update_selected_row = _update_selected_row
    migrate_host_data = _migrate_host_data
    load_data = _load_data
    update_table = _update_table
