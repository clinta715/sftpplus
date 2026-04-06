import os
from PySide6.QtWidgets import (
    QWidget, QPushButton, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QMessageBox, QHeaderView,
    QLineEdit, QLabel, QFormLayout, QGroupBox, QSplitter, QFrame,
    QCheckBox, QComboBox, QSpinBox, QSpinBox
)
from PySide6.QtGui import QIntValidator
from sftp_qt_compat import Qt  # Use compatibility layer for Qt enums
from PySide6.QtCore import Signal

from sftp_hostdataeditor import (
    save_connection_data, load_connection_data,
    get_site_data, get_site_names, get_setting,
    delete_site, copy_site, rename_site
)
from sftp_theme import CONNECT_BUTTON_STYLE, BUTTON_STYLE_DARK


class ConnectionsWidget(QWidget):
    """
    Connections/ Sites management widget for integration into main window.
    
    This provides the same functionality as HostDataEditor but as an embeddable
    widget that can be added as a tab in the main application window.
    
    Signals:
        connect_requested: Emitted when user wants to connect to a site
        open_local_terminal: Emitted when user wants to open local terminal
    """
    
    connect_requested = Signal(dict)
    open_local_terminal = Signal()
    
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
        
        self.local_terminal_button = QPushButton("💻 Local Terminal")
        self.local_terminal_button.setToolTip("Open local terminal tab")
        self.local_terminal_button.setStyleSheet(BUTTON_STYLE_DARK)
        self.local_terminal_button.clicked.connect(self._open_local_terminal)
        toolbar_layout.addWidget(self.local_terminal_button)
        
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
        
        self.detail_nickname = QLineEdit()
        self.detail_nickname.setPlaceholderText("(optional)")
        self.detail_nickname.textChanged.connect(self.update_selected_row)
        
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
        
        self.detail_follow_symlinks = QCheckBox("Follow symbolic links during directory transfers")
        self.detail_follow_symlinks.setToolTip(
            "When checked, symbolic links in directory transfers will be followed (resolved).\n"
            "When unchecked (default), symlinks are skipped."
        )
        self.detail_follow_symlinks.stateChanged.connect(self.update_selected_row)
        
        self.detail_max_connections = QSpinBox()
        self.detail_max_connections.setRange(0, 20)
        self.detail_max_connections.setSpecialValueText("Global default")
        self.detail_max_connections.setValue(0)
        self.detail_max_connections.setToolTip(
            "Maximum concurrent SSH connections for this site.\n"
            "0 = use global default from toolbar spinner."
        )
        self.detail_max_connections.valueChanged.connect(self.update_selected_row)
        
        details_layout.addRow("Nickname:", self.detail_nickname)
        details_layout.addRow("Hostname:", self.detail_hostname)
        details_layout.addRow("Username:", self.detail_username)
        details_layout.addRow("Password:", self.detail_password)
        details_layout.addRow("Port:", self.detail_port)
        details_layout.addRow("SSH Key:", self.detail_key)
        details_layout.addRow("Connection Type:", self.detail_connection_type)
        details_layout.addRow("Startup Commands:", self.detail_ssh_commands)
        details_layout.addRow("Transfers:", self.detail_follow_symlinks)
        details_layout.addRow("SSH Connections:", self.detail_max_connections)
        
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
                "ssh_commands": {},
                "follow_symlinks": {}
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
            # Get actual hostname from UserRole (not the display name/nickname)
            hostname = hostname_item.data(Qt.UserRole)
            if not hostname:
                hostname = hostname_item.text()
            
            site = get_site_data(hostname)
            if not site:
                self._clear_details()
                self._set_details_enabled(False)
                return
            
            # Block signals temporarily
            for widget in [self.detail_nickname, self.detail_hostname, self.detail_username, self.detail_password,
                          self.detail_port, self.detail_key, self.detail_remote_dir, 
                          self.detail_local_dir, self.detail_ssh_commands]:
                widget.blockSignals(True)
            self.detail_connection_type.blockSignals(True)
            self.detail_follow_symlinks.blockSignals(True)
            
            self.detail_nickname.setText(site.get("nickname", ""))
            self.detail_hostname.setText(site.get("hostname", ""))
            self.detail_username.setText(site.get("username", ""))
            self.detail_password.setText(site.get("password", ""))
            self.detail_port.setText(str(site.get("port", 22)))
            self.detail_key.setText(site.get("key", ""))
            self.detail_remote_dir.setText(site.get("initial_remote_dir", ""))
            self.detail_local_dir.setText(site.get("initial_local_dir", ""))
            self.detail_ssh_commands.setText(site.get("ssh_commands", ""))
            
            self.detail_follow_symlinks.setChecked(site.get("follow_symlinks", False))
            
            self.detail_max_connections.blockSignals(True)
            self.detail_max_connections.setValue(site.get("max_connections", 0))
            self.detail_max_connections.blockSignals(False)
            
            connection_type = site.get("connection_type", "SFTP Browser")
            if connection_type == "SSH Terminal":
                self.detail_connection_type.setCurrentIndex(1)
            else:
                self.detail_connection_type.setCurrentIndex(0)
            
            for widget in [self.detail_hostname, self.detail_username, self.detail_password,
                          self.detail_port, self.detail_key, self.detail_remote_dir, 
                          self.detail_local_dir, self.detail_ssh_commands]:
                widget.blockSignals(False)
            self.detail_connection_type.blockSignals(False)
            self.detail_follow_symlinks.blockSignals(False)
    
    def _clear_details(self):
        """Clear all detail fields"""
        for widget in [self.detail_nickname, self.detail_hostname, self.detail_username, self.detail_password,
                      self.detail_port, self.detail_key, self.detail_remote_dir,
                      self.detail_local_dir, self.detail_ssh_commands]:
            widget.blockSignals(True)
            widget.clear()
            widget.blockSignals(False)
        self.detail_connection_type.blockSignals(True)
        self.detail_connection_type.setCurrentIndex(0)
        self.detail_connection_type.blockSignals(False)
        self.detail_follow_symlinks.blockSignals(True)
        self.detail_follow_symlinks.setChecked(False)
        self.detail_follow_symlinks.blockSignals(False)
        self.detail_max_connections.blockSignals(True)
        self.detail_max_connections.setValue(0)
        self.detail_max_connections.blockSignals(False)
    
    def _set_details_enabled(self, enabled):
        """Enable/disable detail panel"""
        for widget in [self.detail_nickname, self.detail_hostname, self.detail_username, self.detail_password,
                      self.detail_port, self.detail_key, self.detail_remote_dir, 
                      self.detail_local_dir, self.detail_ssh_commands,
                      self.connect_button, self.detail_connection_type,
                      self.detail_follow_symlinks, self.detail_max_connections]:
            widget.setEnabled(enabled)
    
    def _update_selected_row(self):
        """Update table display when form fields change (does not save)"""
        selected_row = self.table.currentRow()
        if selected_row < 0:
            return
        
        hostname = self.detail_hostname.text()
        username = self.detail_username.text()
        port = self.detail_port.text() or "22"
        
        # Update table display only - actual data is saved when Save button is clicked
        if self.table.item(selected_row, 0):
            self.table.item(selected_row, 0).setText(hostname)
        if self.table.item(selected_row, 1):
            self.table.item(selected_row, 1).setText(username)
        if self.table.item(selected_row, 2):
            self.table.item(selected_row, 2).setText(port)
        if self.table.item(selected_row, 3):
            self.table.item(selected_row, 3).setText(self.detail_connection_type.currentText())
    
    def _update_table(self):
        """Update table with current host data.

        Uses a single load_connection_data() call to avoid TOCTOU races
        between get_site_names() and per-host get_site_data() calls.
        """
        host_data = load_connection_data()
        hostnames = list(host_data.get("hostnames", {}).keys())

        self.table.setRowCount(0)
        self.table.setRowCount(len(hostnames))
        for i, hostname in enumerate(hostnames):
            display_name = host_data.get("nicknames", {}).get(hostname, "") or hostname
            item = QTableWidgetItem(display_name)
            item.setData(Qt.UserRole, hostname)
            self.table.setItem(i, 0, item)
            self.table.setItem(i, 1, QTableWidgetItem(
                host_data.get("usernames", {}).get(hostname, "")))
            self.table.setItem(i, 2, QTableWidgetItem(
                str(host_data.get("ports", {}).get(hostname, 22))))
            self.table.setItem(i, 3, QTableWidgetItem(
                host_data.get("connection_type", {}).get(hostname, "SFTP Browser")))

        count = len(hostnames)
        self.status_label.setText(f"{count} site{'s' if count != 1 else ''} configured")

        self.show_on_startup_checkbox.blockSignals(True)
        self.show_on_startup_checkbox.setChecked(
            host_data.get("show_manager_on_startup", True))
        self.show_on_startup_checkbox.blockSignals(False)

        self.table.updateGeometry()
        self.table.viewport().update()
    
    def add_row(self):
        """Add a new empty row"""
        hostnames = get_site_names()
        
        new_hostname = ""
        counter = 1
        while new_hostname in hostnames or new_hostname == "":
            new_hostname = f"new_site_{counter}"
            counter += 1
        
        # Add the new site atomically
        def add_site(host_data):
            for key in ["connection_type", "initial_remote_dir", "initial_local_dir", "ssh_commands", "follow_symlinks", "max_connections"]:
                if key not in host_data:
                    host_data[key] = {}
            host_data["hostnames"][new_hostname] = new_hostname
            host_data["usernames"][new_hostname] = ""
            host_data["passwords"][new_hostname] = ""
            host_data["ports"][new_hostname] = 22
            host_data["key"][new_hostname] = ""
            host_data["connection_type"][new_hostname] = "SFTP Browser"
            host_data["initial_remote_dir"][new_hostname] = ""
            host_data["initial_local_dir"][new_hostname] = ""
            host_data["ssh_commands"][new_hostname] = ""
            host_data["follow_symlinks"][new_hostname] = False
            host_data["max_connections"][new_hostname] = 0
        
        from sftp_hostdataeditor import update_connection_data
        update_connection_data(add_site)
        
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
                # Get actual hostname from UserRole (not display name/nickname)
                hostname = hostname_item.data(Qt.UserRole)
                if not hostname:
                    hostname = hostname_item.text()
                reply = QMessageBox.question(
                    self, "Confirm Delete",
                    f"Delete site '{hostname}'?",
                    Qt.MsgBtn_Yes | Qt.MsgBtn_No,
                    Qt.MsgBtn_No
                )
                if reply == Qt.MsgBtn_Yes:
                    if delete_site(hostname):
                        self.table.setUpdatesEnabled(False)
                        self.table.blockSignals(True)
                        self._update_table()
                        self.table.clearSelection()
                        self.table.blockSignals(False)
                        self.table.setUpdatesEnabled(True)
                        self.table.viewport().update()
                        self._clear_details()
                        self._set_details_enabled(False)
                    else:
                        QMessageBox.critical(self, "Error", "Failed to delete site")
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
        
        # Get actual hostname from UserRole (not display name/nickname)
        original_hostname = hostname_item.data(Qt.UserRole)
        if not original_hostname:
            original_hostname = hostname_item.text()
        
        # Find a unique new hostname
        hostnames = get_site_names()
        new_hostname = original_hostname
        counter = 1
        while new_hostname in hostnames:
            new_hostname = f"{original_hostname} (copy{counter})"
            counter += 1
        
        # Use the API to copy the site
        if copy_site(original_hostname, new_hostname):
            self._update_table()
            
            for i in range(self.table.rowCount()):
                if self.table.item(i, 0) and self.table.item(i, 0).text() == new_hostname:
                    self.table.setCurrentCell(i, 0)
                    break
        else:
            QMessageBox.critical(self, "Error", "Failed to copy site")
        
        self._set_details_enabled(True)
        self.detail_hostname.setFocus()
        self.detail_hostname.selectAll()
    
    def save_data(self):
        """Save all site data"""
        try:
            # Load fresh data from disk to avoid stale overwrites
            host_data = load_connection_data()
            
            # Ensure all required keys exist
            for key in ["connection_type", "initial_remote_dir", "initial_local_dir", "bookmarks", "ssh_commands", "follow_symlinks", "max_connections"]:
                if key not in host_data:
                    host_data[key] = {}
            
            # If a row is selected, update that site with current form values
            selected_row = self.table.currentRow()
            if selected_row >= 0:
                hostname_item = self.table.item(selected_row, 0)
                if hostname_item:
                    old_hostname = hostname_item.data(Qt.UserRole)
                    if not old_hostname:
                        old_hostname = hostname_item.text()
                    new_hostname = self.detail_hostname.text().strip()
                    if not new_hostname:
                        new_hostname = old_hostname
                    port = self.detail_port.text() or "22"
                    
                    # If hostname changed, remove old entry and re-key under new hostname
                    if new_hostname != old_hostname:
                        for key in ["hostnames", "usernames", "passwords", "ports", "key",
                                   "connection_type", "initial_remote_dir", "initial_local_dir",
                                   "bookmarks", "ssh_commands", "follow_symlinks", "nicknames",
                                   "max_connections"]:
                            if key in host_data and old_hostname in host_data[key]:
                                host_data[key][new_hostname] = host_data[key].pop(old_hostname)
                    
                    host_data["hostnames"][new_hostname] = new_hostname
                    host_data["usernames"][new_hostname] = self.detail_username.text()
                    host_data["passwords"][new_hostname] = self.detail_password.text()
                    host_data["ports"][new_hostname] = int(port)
                    host_data["key"][new_hostname] = self.detail_key.text()
                    host_data["connection_type"][new_hostname] = self.detail_connection_type.currentText()
                    host_data["initial_remote_dir"][new_hostname] = self.detail_remote_dir.text()
                    host_data["initial_local_dir"][new_hostname] = self.detail_local_dir.text()
                    host_data["ssh_commands"][new_hostname] = self.detail_ssh_commands.text()
                    host_data["follow_symlinks"][new_hostname] = self.detail_follow_symlinks.isChecked()
                    max_conn = self.detail_max_connections.value()
                    host_data["max_connections"][new_hostname] = max_conn if max_conn > 0 else 0
                    
                    nickname = self.detail_nickname.text().strip()
                    if nickname:
                        host_data["nicknames"][new_hostname] = nickname
                    
                    # Update UserRole so subsequent operations use the new hostname
                    hostname_item.setData(Qt.UserRole, new_hostname)
            
            # Remove orphaned entries (empty hostnames or hostnames that were deleted from table)
            # Don't remove "new_site_*" entries - they are pending new sites user is creating
            orphaned = []
            for hostname in list(host_data["hostnames"].keys()):
                if not hostname:
                    orphaned.append(hostname)
                elif hostname.startswith("new_site_"):
                    # Check if this is actually in the table - if not, remove it
                    in_table = False
                    for row in range(self.table.rowCount()):
                        item = self.table.item(row, 0)
                        if item:
                            # Compare actual hostname (UserRole), not display name
                            actual_hostname = item.data(Qt.UserRole) or item.text()
                            if actual_hostname == hostname:
                                in_table = True
                                break
                    if not in_table:
                        orphaned.append(hostname)
            
            for hostname in orphaned:
                for key in ["hostnames", "usernames", "passwords", "ports", "key", 
                           "connection_type", "initial_remote_dir", "initial_local_dir", "bookmarks",
                           "ssh_commands", "follow_symlinks", "nicknames", "max_connections"]:
                    if key in host_data:
                        host_data[key].pop(hostname, None)
            
            # Check for duplicate hostnames - warn and merge instead of silently corrupting
            seen_hostnames = {}
            duplicate_warnings = []
            for hostname in list(host_data["hostnames"].keys()):
                if hostname.startswith("new_site_"):
                    continue
                if hostname in seen_hostnames:
                    duplicate_warnings.append(hostname)
                else:
                    seen_hostnames[hostname] = True
            
            if duplicate_warnings:
                reply = QMessageBox.question(
                    self, "Duplicate Hostnames",
                    f"These hostnames have duplicate entries which would overwrite each other:\n\n" +
                    "\n".join(f"  - {h}" for h in duplicate_warnings) +
                    "\n\nDo you want to keep ONLY the currently selected entry and delete the others?",
                    Qt.MsgBtn_Yes | Qt.MsgBtn_No,
                    Qt.MsgBtn_Yes
                )
                if reply == Qt.MsgBtn_Yes:
                    # Get the currently selected hostname (use actual hostname, not display name)
                    selected_row = self.table.currentRow()
                    keep_hostname = None
                    if selected_row >= 0:
                        item = self.table.item(selected_row, 0)
                        if item:
                            keep_hostname = item.data(Qt.UserRole)
                            if not keep_hostname:
                                keep_hostname = item.text()
                    
                    # Remove all duplicates except the one we're keeping
                    for hostname in duplicate_warnings:
                        if hostname != keep_hostname:
                            for key in ["hostnames", "usernames", "passwords", "ports", "key",
                                       "connection_type", "initial_remote_dir", "initial_local_dir",
                                       "bookmarks", "ssh_commands", "follow_symlinks", "max_connections"]:
                                if key in host_data:
                                    host_data[key].pop(hostname, None)
                else:
                    # User chose not to fix - reject the save
                    raise ValueError(f"Duplicate hostname(s) detected: {', '.join(duplicate_warnings)}. Please rename or delete duplicates before saving.")
            
            # Validate remaining sites (but skip new_site_* entries that are still being filled in)
            for hostname in host_data["hostnames"]:
                if not hostname:
                    raise ValueError("Hostname cannot be empty")
                # Skip validation for newly created empty sites
                if hostname.startswith("new_site_"):
                    continue
                username = host_data.get("usernames", {}).get(hostname, "")
                if not username:
                    raise ValueError(f"Username required for '{hostname}'")
                password = host_data.get("passwords", {}).get(hostname, "")
                key = host_data.get("key", {}).get(hostname, "")
                if not password and not key:
                    raise ValueError(f"Password or SSH key required for '{hostname}'")
            
            host_data["show_manager_on_startup"] = self.show_on_startup_checkbox.isChecked()
            
            if save_connection_data(host_data):
                QMessageBox.information(self, "Success", "Sites saved successfully!")
                self._update_table()
                # Update internal cache to match what was saved
                self.host_data = host_data
            else:
                QMessageBox.critical(self, "Error", "Failed to save site data")
        except ValueError as e:
            QMessageBox.critical(self, "Validation Error", str(e))
        except (OSError, RuntimeError) as e:
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
        
        # Read from form field - this is what user entered (not UserRole which may be placeholder)
        hostname = self.detail_hostname.text().strip()
        if not hostname or hostname.startswith("new_site_"):
            QMessageBox.warning(self, "Invalid Hostname", "Please enter a valid hostname or IP address before connecting.")
            self.detail_hostname.setFocus()
            return
        
        # Read directly from form fields - this ensures we use exactly what the user sees
        # This is important because duplicate hostnames could exist in the data
        username = self.detail_username.text()
        password = self.detail_password.text()
        port_str = self.detail_port.text() or "22"
        try:
            port = int(port_str)
        except ValueError:
            port = 22
        key = self.detail_key.text() or "None"
        initial_remote_dir = self.detail_remote_dir.text()
        initial_local_dir = self.detail_local_dir.text()
        connection_type = self.detail_connection_type.currentText()
        ssh_commands = self.detail_ssh_commands.text()
        follow_symlinks = self.detail_follow_symlinks.isChecked()
        max_connections = self.detail_max_connections.value()
        
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
            "ssh_commands": ssh_commands,
            "follow_symlinks": follow_symlinks,
            "max_connections": max_connections
        }
        
        self.connect_requested.emit(connection_data)
    
    def _open_local_terminal(self):
        """Emit signal to open local terminal"""
        self.open_local_terminal.emit()
    
    # Alias methods to match expected names from HostDataEditor
    on_selection_changed = _on_selection_changed
    on_cell_double_clicked = _on_cell_double_clicked
    load_details_from_row = _load_details_from_row
    clear_details = _clear_details
    set_details_enabled = _set_details_enabled
    update_selected_row = _update_selected_row
    load_data = _load_data
    update_table = _update_table
