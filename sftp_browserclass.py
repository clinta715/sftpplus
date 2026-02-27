from PyQt6.QtWidgets import QTableView, QApplication, QWidget, QVBoxLayout, QLabel, QFileDialog, QMessageBox, QInputDialog, QMenu, QHeaderView, QProgressBar, QSizePolicy, QTreeWidget, QTreeWidgetItem, QPushButton, QHBoxLayout, QProgressDialog, QLineEdit, QToolButton
from PyQt6.QtCore import pyqtSignal, QTimer, QEventLoop, QModelIndex
from sftp_qt_compat import Qt
import stat
import os
import sys
import tempfile
import subprocess
import time
from icecream import ic
from pathlib import Path

import paramiko
import threading

from sftp_creds import get_credentials, create_random_integer, set_credentials
from sftp_downloadworkerclass import (create_response_queue, delete_response_queue,
                                       check_response_queue, QueueItem, ResponseQueueContext)
from sftp_session_executor import SFTPSessionAPI, create_session_api
from sftp_session import SFTPCredentials, get_session_manager
from sftp_browser_mixins import TreeViewMixin, BookmarkMixin, FileOpsMixin


class Browser(TreeViewMixin, BookmarkMixin, FileOpsMixin, QWidget):
    def __init__(self, title, session_id, parent=None):
        super().__init__(parent)
        self._observers = []
        self._observers_lock = threading.Lock()
        self.title = title
        self.model = None
        self.session_id = session_id
        self._notifying = False
        
        # THREAD SAFETY: Cancel flag with lock
        self._cancel_lock = threading.Lock()
        self._user_canceled = False
        
        creds = get_credentials(session_id)
        self.init_hostname = creds.get('hostname')
        self.init_username = creds.get('username')
        self.init_password = creds.get('password')
        port = creds.get('port')
        self.init_port = int(port) if port else 22
        self.init_key = creds.get('key')

        self._session_api = None
        # THREAD SAFETY: Lock for session API initialization
        self._session_api_lock = threading.Lock()

    def _init_session_api(self):
        """Initialize the session-based API for SFTP operations.
        Only creates a session if credentials are valid and no session exists yet.
        The session_id passed to this browser is used consistently.
        Thread-safe: Uses double-checked locking pattern."""
        # THREAD SAFETY: Double-checked locking pattern
        if self._session_api is not None:
            return

        with self._session_api_lock:
            # Check again inside the lock
            if self._session_api is not None:
                return

            if not all([self.init_hostname, self.init_username]):
                ic("Browser: Missing credentials, session API not initialized")
                return

            try:
                credentials = SFTPCredentials(
                    hostname=self.init_hostname,
                    username=self.init_username,
                    password=self.init_password,
                    port=self.init_port or 22,
                    key=self.init_key
                )

                session_manager = get_session_manager()
                session = session_manager.create_session(credentials)
                self._session_api = SFTPSessionAPI(session)
                ic(f"Browser: Session API initialized for {self.init_hostname}")
            except (paramiko.SSHException, OSError, ValueError) as e:
                ic(f"Browser: Failed to initialize session API: {e}")
                self._session_api = None

    @property
    def session_api(self):
        """Get the session API, initializing if needed.
        Uses the existing session_id that was passed to the browser.
        The FileBrowser (local) will always return None since it doesn't need SFTP.
        Thread-safe: Uses locking to prevent race conditions during initialization."""
        if self._session_api is None:
            self._init_session_api()
        return self._session_api

    # Define a signal for sending messages to the console
    message_signal = pyqtSignal(str)
    
    # Signal to indicate a transfer has started
    transfer_started = pyqtSignal(str)  # Emits transfer_id when transfer starts

    def init_ui(self):
        self.layout = QVBoxLayout()
        
        header_layout = QHBoxLayout()
        self.label = QLabel(self.title)
        header_layout.addWidget(self.label)
        header_layout.addStretch()
        
        self.tree_toggle_btn = QPushButton("🌲 Tree")
        self.tree_toggle_btn.setToolTip("Toggle tree view panel")
        self.tree_toggle_btn.setCheckable(True)
        self.tree_toggle_btn.setStyleSheet("""
            QPushButton {
                padding: 4px 8px;
                border: 1px solid #555555;
                border-radius: 3px;
                background-color: #444444;
                color: #dddddd;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #555555;
            }
            QPushButton:checked {
                background-color: #4a6fa5;
            }
        """)
        self.tree_toggle_btn.clicked.connect(self.toggle_tree_view)
        header_layout.addWidget(self.tree_toggle_btn)
        
        self.tree_position_btn = QPushButton("↕")
        self.tree_position_btn.setToolTip("Toggle tree view position (above/below list)")
        self.tree_position_btn.setVisible(False)
        self.tree_position_btn.setStyleSheet("""
            QPushButton {
                padding: 4px 8px;
                border: 1px solid #555555;
                border-radius: 3px;
                background-color: #444444;
                color: #dddddd;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #555555;
            }
        """)
        self.tree_position_btn.clicked.connect(self.toggle_tree_position)
        header_layout.addWidget(self.tree_position_btn)
        
        self.bookmarks_btn = QToolButton()
        self.bookmarks_btn.setText("⭐")
        self.bookmarks_btn.setToolTip("Bookmarks (Ctrl+D to add)")
        self.bookmarks_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.bookmarks_btn.setStyleSheet("""
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
            QToolButton::menu-indicator {
                subcontrol-position: right center;
                subcontrol-origin: padding;
                left: -2px;
                width: 8px;
            }
        """)
        self.bookmarks_btn.clicked.connect(self._show_bookmarks_menu)
        header_layout.addWidget(self.bookmarks_btn)
        
        self.layout.addLayout(header_layout)
        
        self._create_tree_container()
        
        self.table = QTableView()
        self.active_table = self.table

        self.table.setSizePolicy(Qt.SizePolicy_Expanding, Qt.SizePolicy_Expanding)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.verticalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(Qt.HeaderView_Stretch)
        self.table.horizontalHeader().setSectionResizeMode(Qt.HeaderView_Interactive)
        self.table.setSortingEnabled(True)

        self.table.doubleClicked.connect(self.double_click_handler)
        self.table.customContextMenuRequested.connect(self.context_menu_handler)
        self.table.setFocusPolicy(Qt.StrongFocus)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.sortByColumn(0, Qt.AscendingOrder)

        self._tree_position = "above"
        self._apply_tree_layout()
        
        self._tree_root_path = None
        self._tree_current_path = None
        
        self.progressBar = QProgressBar()
        self.layout.addWidget(self.progressBar)

        self.setLayout(self.layout)
    
    def _create_tree_container(self):
        self.tree_container = QWidget()
        self.tree_container.setVisible(False)
        tree_container_layout = QVBoxLayout()
        tree_container_layout.setContentsMargins(0, 0, 0, 0)
        tree_container_layout.setSpacing(5)
        
        tree_controls_layout = QHBoxLayout()
        
        self.tree_up_btn = QPushButton("⬆️ Up")
        self.tree_up_btn.setToolTip("Go to parent directory")
        self.tree_up_btn.setStyleSheet("""
            QPushButton {
                padding: 4px 8px;
                border: 1px solid #555555;
                border-radius: 3px;
                background-color: #444444;
                color: #dddddd;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #555555;
            }
            QPushButton:disabled {
                background-color: #333333;
                color: #666666;
            }
        """)
        self.tree_up_btn.clicked.connect(self.tree_go_up)
        tree_controls_layout.addWidget(self.tree_up_btn)
        
        self.tree_path_input = QLineEdit("/")
        self.tree_path_input.setStyleSheet("""
            QLineEdit {
                color: #dddddd;
                font-size: 11px;
                padding: 4px 8px;
                background-color: #2a2a2a;
                border: 1px solid #555555;
                border-radius: 3px;
            }
            QLineEdit:focus {
                border: 1px solid #7eb8ff;
                background-color: #333333;
            }
        """)
        self.tree_path_input.setToolTip("Type a path and press Enter to navigate")
        self.tree_path_input.returnPressed.connect(self.tree_path_navigate)
        tree_controls_layout.addWidget(self.tree_path_input, stretch=1)
        
        self.tree_download_btn = QPushButton("⬇️ Download")
        self.tree_download_btn.setToolTip("Download selected directory")
        self.tree_download_btn.setStyleSheet("""
            QPushButton {
                padding: 4px 8px;
                border: 1px solid #555555;
                border-radius: 3px;
                background-color: #2a5a3a;
                color: #dddddd;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #3a7a4a;
            }
            QPushButton:disabled {
                background-color: #333333;
                color: #666666;
            }
        """)
        self.tree_download_btn.clicked.connect(self.tree_download_selected)
        tree_controls_layout.addWidget(self.tree_download_btn)
        
        self.tree_download_all_btn = QPushButton("⬇️⬇️ Download All")
        self.tree_download_all_btn.setToolTip("Download all visible directories")
        self.tree_download_all_btn.setStyleSheet("""
            QPushButton {
                padding: 4px 8px;
                border: 1px solid #555555;
                border-radius: 3px;
                background-color: #3a5a8a;
                color: #dddddd;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #4a7aaa;
            }
            QPushButton:disabled {
                background-color: #333333;
                color: #666666;
            }
        """)
        self.tree_download_all_btn.clicked.connect(self.tree_download_all)
        tree_controls_layout.addWidget(self.tree_download_all_btn)
        
        self.tree_delete_btn = QPushButton("🗑️ Delete")
        self.tree_delete_btn.setToolTip("Delete selected directory")
        self.tree_delete_btn.setStyleSheet("""
            QPushButton {
                padding: 4px 8px;
                border: 1px solid #555555;
                border-radius: 3px;
                background-color: #8a3a3a;
                color: #dddddd;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #aa4a4a;
            }
            QPushButton:disabled {
                background-color: #333333;
                color: #666666;
            }
        """)
        self.tree_delete_btn.clicked.connect(self.tree_delete_selected)
        tree_controls_layout.addWidget(self.tree_delete_btn)
        
        tree_container_layout.addLayout(tree_controls_layout)
        
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(["Directories"])
        self.tree_widget.setHeaderHidden(False)
        self.tree_widget.setColumnWidth(0, 400)
        self.tree_widget.setSizePolicy(Qt.SizePolicy_Expanding, Qt.SizePolicy_Expanding)
        self.tree_widget.setIndentation(20)
        self.tree_widget.setItemsExpandable(True)
        self.tree_widget.setExpandsOnDoubleClick(True)
        self.tree_widget.itemDoubleClicked.connect(self.tree_double_click_handler)
        self.tree_widget.itemExpanded.connect(self.tree_item_expanded_handler)
        self.tree_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_widget.customContextMenuRequested.connect(self.tree_context_menu_handler)
        self.tree_widget.setStyleSheet("""
            QTreeWidget {
                background-color: #333333;
                color: #dddddd;
                border: 1px solid #555555;
            }
            QTreeWidget::item:selected {
                background-color: #4a6fa5;
            }
            QTreeWidget::item[current="true"] {
                font-weight: bold;
                color: #7eb8ff;
            }
            QTreeWidget::branch:has-children:!has-siblings:closed,
            QTreeWidget::branch:closed:has-children:has-siblings {
                border-image: none;
                image: url(:/qt-project.org/styles/commonstyle/images/branch-closed.png);
            }
            QTreeWidget::branch:open:has-children:!has-siblings,
            QTreeWidget::branch:open:has-children:has-siblings {
                border-image: none;
                image: url(:/qt-project.org/styles/commonstyle/images/branch-open.png);
            }
        """)
        tree_container_layout.addWidget(self.tree_widget)
        
        self.tree_status_label = QLabel("")
        self.tree_status_label.setStyleSheet("""
            color: #ffffff;
            font-size: 11px;
            padding: 4px;
            background-color: #2a5a8a;
            border-radius: 3px;
        """)
        self.tree_status_label.setAlignment(Qt.AlignCenter)
        tree_container_layout.addWidget(self.tree_status_label)
        
        self.tree_container.setLayout(tree_container_layout)
    
    def _apply_tree_layout(self):
        self.tree_container.setParent(None)
        self.table.setParent(None)
        
        from sftp_preferences import get_preferences
        position = get_preferences().get('tree_view_position', 'above')
        self._tree_position = position
        
        if position == 'above':
            self.layout.addWidget(self.tree_container)
            self.layout.addWidget(self.table)
        else:
            self.layout.addWidget(self.table)
            self.layout.addWidget(self.tree_container)
        
        self.tree_position_btn.setToolTip(f"Tree position: {position} list (click to toggle)")
    
    def toggle_tree_position(self):
        from sftp_preferences import get_preferences
        prefs = get_preferences()
        
        current = prefs.get('tree_view_position', 'above')
        new_position = 'below' if current == 'above' else 'above'
        
        prefs.set('tree_view_position', new_position)
        self._tree_position = new_position
        self._apply_tree_layout()
    
    def toggle_tree_view(self):
        show_tree = self.tree_toggle_btn.isChecked()
        ic(f"Tree toggle: show_tree={show_tree}")
        self.tree_container.setVisible(show_tree)
        self.tree_position_btn.setVisible(show_tree)
        
        if show_tree:
            self.populate_tree_view()
    
    def keyPressEvent(self, event):
        """Handle keyboard shortcuts"""
        key = event.key()
        modifiers = event.modifiers()
        
        if key == Qt.Key_F5:
            self.refresh_files()
        elif key == Qt.Key_Delete:
            self.remove_directory_with_prompt()
        elif key == Qt.Key_A and modifiers == Qt.ControlModifier:
            self.table.selectAll()
        elif key == Qt.Key_Return or key == Qt.Key_Enter:
            self.change_directory_handler()
        elif key == Qt.Key_Backspace and modifiers == Qt.NoModifier:
            self.navigate_to_parent()
        elif key == Qt.Key_B and modifiers == Qt.ControlModifier:
            self.add_bookmark()
        elif key == Qt.Key_D and modifiers == Qt.ControlModifier:
            self.add_bookmark()
        elif key == Qt.Key_F2:
            self.rename_selected()
        elif key == Qt.Key_F6:
            if hasattr(self, 'upload_download'):
                self.upload_download()
        elif key == Qt.Key_F7:
            if hasattr(self, 'upload_download'):
                self.upload_download()
        elif key == Qt.Key_L and modifiers == Qt.ControlModifier:
            if hasattr(self, 'tree_path_input'):
                self.tree_path_input.setFocus()
                self.tree_path_input.selectAll()
        elif key == Qt.Key_P and modifiers == Qt.ControlModifier:
            self.toggle_preview()
        else:
            super().keyPressEvent(event)
    
    def populate_tree_view(self):
        """Populate the tree view with directory structure. Override in subclasses."""
        pass
    
    def tree_double_click_handler(self, item, column):
        """Handle double-click on tree item. Override in subclasses."""
        pass
    
    def tree_context_menu_handler(self, pos):
        """Handle context menu on tree widget. Override in subclasses."""
        pass
    
    def tree_item_expanded_handler(self, item):
        """Handle item expansion - lazy load subdirectories. Override in subclasses."""
        pass
    
    def tree_go_up(self):
        """Navigate to parent directory and make it the new tree root. Override in subclasses."""
        pass
    
    def tree_path_navigate(self):
        """Navigate to path entered in tree path input. Override in subclasses."""
        pass
    
    def tree_download_selected(self):
        """Download selected directory from tree. Override in subclasses."""
        pass
    
    def tree_download_all(self):
        """Download all directories in current tree view. Override in subclasses."""
        pass
    
    def tree_delete_selected(self):
        """Delete selected directory from tree. Override in subclasses."""
        pass

    def navigate_to_parent(self):
        """Navigate to parent directory"""
        self.change_directory("..")

    def rename_selected(self):
        """Rename the currently selected file or directory"""
        from PyQt6.QtWidgets import QInputDialog
        
        current_index = self.table.currentIndex()
        if not current_index.isValid():
            self.message_signal.emit("Please select a file or folder to rename.")
            return
        
        filename_index = self.table.model().index(current_index.row(), 0)
        selected_item = self.table.model().data(filename_index, Qt.DisplayRole)
        if ' ' in selected_item:
            selected_item = selected_item.split(' ', 1)[-1]
        
        new_name, ok = QInputDialog.getText(self, "Rename", f"Enter new name for '{selected_item}':")
        if ok and new_name and new_name != selected_item:
            creds = get_credentials(self.session_id)
            current_dir = creds.get('current_remote_directory' if hasattr(self, 'is_remote_browser') and self.is_remote_browser() else 'current_local_directory', '.')
            remote_path = os.path.join(current_dir, selected_item)
            if hasattr(self, 'sftp_rename'):
                self.sftp_rename(remote_path, new_name)
            else:
                self.message_signal.emit("Rename not available for this browser type")
        elif ok and new_name == selected_item:
            self.message_signal.emit("New name is the same as current name.")

    def toggle_preview(self):
        parent = self.parent()
        while parent:
            if hasattr(parent, 'toggle_preview') and hasattr(parent, 'preview_widget'):
                parent.toggle_preview()
                return
            parent = parent.parent()
        self.message_signal.emit("Preview panel: Open a connection tab first")

    def get_files(self):
        self.model.get_files()

    def add_observer(self, observer):
        """Add an observer with thread-safe lock protection."""
        with self._observers_lock:
            if observer not in self._observers:
                self._observers.append(observer)
            else:
                ic("Observer already exists:", observer)

    def remove_observer(self, observer):
        """Remove an observer with thread-safe lock protection."""
        with self._observers_lock:
            if observer in self._observers:
                self._observers.remove(observer)

    def notify_observers(self):
        """Notify all observers to refresh files. Thread-safe."""
        # Copy list under lock to avoid holding lock during callbacks
        with self._observers_lock:
            observers_copy = list(self._observers)
        
        for observer in observers_copy:
            try:
                observer.get_files()  # Notify the observer by calling its update method
            except AttributeError as ae:
                ic("Observer", observer, "does not implement 'get_files' method.", ae)
            except (AttributeError, RuntimeError) as e:
                ic("An error occurred while notifying observer", observer, e)

    def get_normalized_remote_path(self, current_remote_directory, partial_remote_path=None):
        """
        Get a normalized remote path by joining the current remote directory with a partial path.
        If no partial path is provided, return the normalized current remote directory.
        
        Args:
            current_remote_directory (str): The base directory on the remote server.
            partial_remote_path (str, optional): The partial path to be appended.
            
        Returns:
            str: The normalized remote path with forward slashes and no trailing slash.
            
        Raises:
            ValueError: If the path attempts to traverse outside the base directory.
        """
        # Replace backslashes with forward slashes in the base directory
        current_remote_directory = current_remote_directory.replace("\\", "/")

        if partial_remote_path is not None:
            # Replace backslashes with forward slashes in the partial path
            partial_remote_path = partial_remote_path.replace("\\", "/")
            
            # Join paths and normalize
            remote_path = os.path.join(current_remote_directory, partial_remote_path)
            normalized_path = os.path.normpath(remote_path)
        else:
            # Normalize the current remote directory
            normalized_path = os.path.normpath(current_remote_directory)
        
        # Convert backslashes to forward slashes in the final path
        normalized_path = normalized_path.replace("\\", "/")
        
        # SECURITY: Path traversal protection
        # Ensure the normalized path doesn't escape the base directory
        # Handle both absolute paths and paths relative to root
        base = current_remote_directory.rstrip('/')
        if not normalized_path.startswith('/') and base:
            # Relative path - check if it would go above base when resolved
            # Normalize the base as well for comparison
            test_path = os.path.normpath(os.path.join(base, normalized_path)).replace("\\", "/")
        else:
            test_path = normalized_path
            
        # For absolute paths, ensure they don't traverse above root
        # For relative paths resolved against base, ensure they stay within base
        if base and not test_path.startswith(base) and test_path != base:
            if not test_path.startswith('/'):
                # Try with leading slash
                if not ('/' + test_path).startswith(base):
                    raise ValueError(f"Path traversal attempt detected: {partial_remote_path}")
            else:
                raise ValueError(f"Path traversal attempt detected: {partial_remote_path}")
        
        # Remove the trailing slash if it's not the root '/'
        if normalized_path != '/':
            normalized_path = normalized_path.rstrip('/')
        
        return normalized_path

    def is_complete_path(self, path):
        """
        Determine if a path is a complete path or just a filename/directory name.
        A complete path starts with '/' (absolute) indicating it's already fully qualified.
        
        Args:
            path (str): The filesystem path to check.
            
        Returns:
            bool: True if the path is a complete path, False if it's just a filename/directory name.
        """
        # Strip whitespace for checking
        path = path.strip()
        
        # Empty path is not complete
        if not path:
            return False
        
        # ONLY check if it starts with '/' (Unix-like absolute path)
        # This is the only reliable indicator for remote SFTP paths
        if path.startswith('/'):
            return True
        
        # Single component names (including hidden files like .mozilla) are NOT complete paths
        # Even if they contain dots, slashes, or backslashes
        return False        

    def split_path(self, path):
        """Split path into head and tail, ensuring head is never empty for absolute paths."""
        # try to deal with windows backslashes
        if "\\" in path:
            # Use "\\" as the separator
            head, tail = path.rsplit("\\", 1)
        elif "/" in path:
            # Use "/" as the separator
            head, tail = path.rsplit("/", 1)
            # Handle edge case: if head is empty but path started with /, head should be /
            if not head and path.startswith("/"):
                head = "/"
        else:
            # No "\\" or "/" found, assume the entire string is the head
            head, tail = path, ""

        return head, tail

    def _wait_for_response(self, queue, timeout=30):
        """
        Wait for a response using blocking queue with timeout.
        More efficient than busy-polling.
        
        Args:
            queue: The response queue to wait on
            timeout: Maximum time to wait in seconds
            
        Returns:
            Response item or None if timeout
        """
        try:
            # Use blocking get with timeout - much more efficient than polling
            return queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def sftp_mkdir(self, remote_path):
        """Create a remote directory with guaranteed resource cleanup"""
        if self.session_api is None:
            self.message_signal.emit("sftp_mkdir() - Session API not initialized")
            return False

        # If path is not absolute, prepend current remote directory
        if not remote_path.startswith('/'):
            creds = get_credentials(self.session_id)
            current_dir = creds.get('current_remote_directory', '.')
            remote_path = self.get_normalized_remote_path(current_dir, remote_path)

        job_id = create_random_integer()

        try:
            self.session_api.mkdir(remote_path, job_id=str(job_id))
            result = True
        except (OSError, IOError) as e:
            self.message_signal.emit(f"FileBrowser sftp_mkdir() {e}")
            result = False

        self.model.get_files(force_refresh=True)
        self.notify_observers()
        return result

    def sftp_rmdir(self, remote_path):
        ic(f"sftp_rmdir: Starting for {remote_path}")
        if self.session_api is None:
            ic("sftp_rmdir: Session API is None!")
            self.message_signal.emit("sftp_rmdir() - Session API not initialized")
            return False

        job_id = create_random_integer()

        try:
            ic(f"sftp_rmdir: Calling session_api.rmdir({remote_path}, job_id={job_id})")
            self.session_api.rmdir(remote_path, job_id=str(job_id))
            ic(f"sftp_rmdir: session_api.rmdir returned successfully")
            result = True
        except (OSError, IOError, PermissionError, paramiko.SSHException) as e:
            ic(f"sftp_rmdir: Exception: {e}")
            import traceback
            traceback.print_exc()
            self.message_signal.emit(f"FileBrowser sftp_rmdir() {e}")
            result = False

        self.get_files()
        self.notify_observers()
        return result

    def sftp_remove(self, remote_path):
        ic(f"sftp_remove: Starting for {remote_path}")
        if self.session_api is None:
            ic("sftp_remove: Session API is None!")
            self.message_signal.emit("sftp_remove() - Session API not initialized")
            return False

        job_id = create_random_integer()

        try:
            ic(f"sftp_remove: Calling session_api.remove({remote_path}, job_id={job_id})")
            self.session_api.remove(remote_path, job_id=str(job_id))
            ic(f"sftp_remove: session_api.remove returned successfully")
            result = True
        except (OSError, IOError, PermissionError, paramiko.SSHException) as e:
            ic(f"sftp_remove: Exception: {e}")
            import traceback
            traceback.print_exc()
            self.message_signal.emit(f"FileBrowser sftp_remove() {e}")
            result = False

        self.get_files()
        self.notify_observers()
        return result

    def sftp_rename(self, remote_path, new_name):
        ic(f"sftp_rename: Starting for {remote_path} to {new_name}")
        if self.session_api is None:
            ic("sftp_rename: Session API is None!")
            self.message_signal.emit("sftp_rename() - Session API not initialized")
            return False

        job_id = create_random_integer()

        try:
            ic(f"sftp_rename: Calling session_api.rename({remote_path}, {new_name}, job_id={job_id})")
            self.session_api.rename(remote_path, new_name, job_id=str(job_id))
            ic(f"sftp_rename: session_api.rename returned successfully")
            self.message_signal.emit(f"Renamed '{os.path.basename(remote_path)}' to '{new_name}'")
            result = True
        except PermissionError as e:
            ic(f"sftp_rename: Permission denied: {e}")
            error_msg = f"Permission denied: Cannot rename file. You may not have permission to modify this file."
            QMessageBox.warning(None, "Permission Denied", error_msg)
            self.message_signal.emit(f"Rename failed: {error_msg}")
            result = False
        except (OSError, IOError, paramiko.SSHException) as e:
            ic(f"sftp_rename: Exception: {e}")
            import traceback
            traceback.print_exc()
            error_msg = str(e)
            QMessageBox.critical(None, "Rename Error", f"Error renaming file: {error_msg}")
            self.message_signal.emit(f"FileBrowser sftp_rename() {e}")
            result = False

        self.get_files()
        self.notify_observers()
        return result
    
    def sftp_listdir(self, remote_path):
        if self.session_api is None:
            self.message_signal.emit("sftp_listdir() - Session API not initialized")
            return False

        self.progressBar.setRange(0, 0)

        try:
            result = self.session_api.list(remote_path)
            self.progressBar.setRange(0, 100)
            return result
        except (OSError, IOError, paramiko.SSHException) as e:
            self.message_signal.emit(f"FileBrowser sftp_listdir() {e}")
            self.progressBar.setRange(0, 100)
            return False

    def non_blocking_sleep(self, ms):
        # special sleep function that can be used by a background/foreground thread, without causing a hang

        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def sftp_listdir_attr(self, remote_path):
        if self.session_api is None:
            self.message_signal.emit("sftp_listdir_attr() - Session API not initialized")
            return False

        self.progressBar.setRange(0, 0)

        try:
            result = self.session_api.list_attr(remote_path)
            self.progressBar.setRange(0, 100)
            return result
        except (OSError, IOError, paramiko.SSHException) as e:
            self.message_signal.emit(f"FileBrowser sftp_listdir_attr() {e}")
            self.progressBar.setRange(0, 100)
            return False

    def normalize_path(self, path):
        """
        Normalize the given path by collapsing redundant slashes and up-level references.
        
        Args:
            path (str): The filesystem path to normalize.
            
        Returns:
            str: The normalized path.
        """
        return os.path.normpath(path)

    def on_header_clicked(self, logicalIndex):
        # Check the current sort order and toggle it
        # not the best, should really be revised 
        order = Qt.DescendingOrder if self.table.horizontalHeader().sortIndicatorOrder() == Qt.AscendingOrder else Qt.AscendingOrder
        self.table.sortByColumn(logicalIndex, order)

    def is_remote_directory(self, partial_remote_path):
        """Check if a path is a remote directory with comprehensive debugging"""
        ic(f"is_remote_directory: START - partial_remote_path={partial_remote_path}, session_id={self.session_id}")

        try:
            current_dir = get_credentials(self.session_id).get('current_remote_directory', '.')
            ic(f"is_remote_directory: current_remote_directory={current_dir}")

            if not self.is_complete_path(partial_remote_path):
                remote_path = self.get_normalized_remote_path(current_dir, partial_remote_path)
                ic(f"is_remote_directory: incomplete path - joined {current_dir} + {partial_remote_path} = {remote_path}")
            else:
                remote_path = partial_remote_path.replace("\\", "/")
                if remote_path != '/':
                    remote_path = remote_path.rstrip('/')
                ic(f"is_remote_directory: complete path - normalized to {remote_path}")

            if hasattr(self.model, 'attr_cache'):
                cached_attr = self.model.attr_cache.get(remote_path)
                if cached_attr and time.time() - self.model.attr_cache_time.get(remote_path, 0) < self.model.cache_duration:
                    is_dir = stat.S_ISDIR(cached_attr.st_mode)
                    ic(f"is_remote_directory: CACHE HIT - {remote_path} is_dir={is_dir}")
                    return is_dir

            # Use session_api property to ensure initialization
            if self.session_api is None:
                ic("is_remote_directory: Session API not initialized")
                return False

            ic(f"is_remote_directory: submitting stat for {remote_path}")
            attr = self.session_api.stat(remote_path)
            is_dir = stat.S_ISDIR(attr.st_mode)
            ic(f"is_remote_directory: SUCCESS - {remote_path} is_dir={is_dir}, st_mode={attr.st_mode}")

            if hasattr(self.model, 'attr_cache'):
                self.model.attr_cache[remote_path] = attr
                self.model.attr_cache_time[remote_path] = time.time()

            return is_dir

        except (OSError, IOError, paramiko.SSHException) as e:
            ic(f"is_remote_directory: EXCEPTION - {e} for {partial_remote_path}")
            import traceback
            traceback.print_exc()
            return False

    def is_remote_file(self, partial_remote_path):
        """Check if a path is a remote file"""
        try:
            creds = get_credentials(self.session_id)
            current_dir = creds.get('current_remote_directory', '.')
            ic(f"is_remote_file: START - partial_remote_path={partial_remote_path}, current_dir={current_dir}")

            if not self.is_complete_path(partial_remote_path):
                remote_path = self.get_normalized_remote_path(current_dir, partial_remote_path)
                ic(f"is_remote_file: incomplete path - joined {current_dir} + {partial_remote_path} = {remote_path}")
            else:
                remote_path = partial_remote_path.replace("\\", "/")
                if remote_path != '/':
                    remote_path = remote_path.rstrip('/')
                ic(f"is_remote_file: complete path - normalized to {remote_path}")

        except (KeyError, ValueError) as e:
            self.message_signal.emit(f"Error in getting credentials or forming remote path: {e}")
            ic(e)
            return False

        try:
            if self.session_api is None:
                ic("is_remote_file: Session API not initialized")
                return False

            attr = self.session_api.stat(remote_path)
            is_directory = stat.S_ISDIR(attr.st_mode)
            is_file = not is_directory
            ic(f"is_remote_file: {remote_path} is_file={is_file}")
            return is_file

        except (OSError, IOError, paramiko.SSHException) as e:
            ic(f"is_remote_file: Exception - {e}")
            return False

    def waitjob(self, job_id, timeout=30):
        # Reset cancel flag at start of each job
        self.reset_cancel_flag()
        self.progressBar.setRange(0, 100)
        self.progressBar.setValue(0)
        progress_value = 0
        start_time = time.time()
        
        try:
            while not check_response_queue(job_id):
                if time.time() - start_time > timeout:
                    raise TimeoutError("Job timed out")
                
                # Check for user cancellation (thread-safe)
                if self.is_canceled():
                    raise KeyboardInterrupt("User canceled the transfer")
                    
                progress_value = min(progress_value + 10, 100)
                self.progressBar.setValue(progress_value)
                self.non_blocking_sleep(100)
                QApplication.processEvents()

        except (TimeoutError, KeyboardInterrupt) as e:
            self.message_signal.emit(f"Job interrupted: {str(e)}")
            # Ensure we clean up the job even when canceled
            delete_response_queue(job_id)
            return False
        finally:
            self.progressBar.setValue(100)
            self.progressBar.setRange(0, 100)

        return True

    def cancel_current_operation(self):
        """Set the user_canceled flag to True to cancel current operation"""
        with self._cancel_lock:
            self._user_canceled = True
        self.message_signal.emit("Operation canceled by user")

    def reset_cancel_flag(self):
        """Reset the user_canceled flag to False"""
        with self._cancel_lock:
            self._user_canceled = False

    def is_canceled(self):
        """Check if operation was canceled (thread-safe)"""
        with self._cancel_lock:
            return self._user_canceled

    def focusInEvent(self, event):
        self.setStyleSheet("""
            QTableWidget {
            background-color: #ffffff; /* Set background color */
            color: white;  /* Text color */
            border: 1px solid #cccccc; /* Add a thin border */
            selection-background-color: #e0e0e0; /* Set background color for selected items */
            }
        """)
        self.label.repaint()  # Force a repaint

    def focusOutEvent(self, event):
        self.setStyleSheet("""
            QTableWidget {
            background-color: #777777; /* Set background color */
            color: gray;  /* Text color */
            border: 1px solid #999999; /* Add a thin border */
            selection-background-color: #909090; /* Set background color for selected items */
            }
        """)
        self.label.repaint()  # Force a repaint

    def prompt_and_rename(self):
        """Prompt user for new name and rename the selected file"""
        current_browser = self.active_table
        if current_browser is not None:
            indexes = current_browser.selectedIndexes()
            if indexes:
                row = indexes[0].row()
                filename_index = current_browser.model().index(row, 0)
                selected_item = current_browser.model().data(filename_index, Qt.DisplayRole)
                selected_item = selected_item.split(' ', 1)[-1] if ' ' in selected_item else selected_item
                
                new_name, ok = QInputDialog.getText(
                    None,
                    "Rename",
                    f"Enter new name for '{selected_item}':",
                    text=selected_item
                )
                if ok and new_name and new_name != selected_item:
                    creds = get_credentials(self.session_id)
                    remote_path = os.path.join(creds.get('current_remote_directory'), selected_item)
                    self.sftp_rename(remote_path, new_name)
                elif ok and new_name == selected_item:
                    QMessageBox.information(None, "Rename", "New name is the same as current name.")
            else:
                QMessageBox.information(None, "Rename", "Please select a file or folder to rename.")

    def prompt_and_create_directory(self):
        creds = get_credentials(self.session_id)

        # Prompt the user for a new directory name
        directory_name, ok = QInputDialog.getText(
            None,
            'Create New Directory',
            'Enter the name of the new directory:'
        )

        if ok and directory_name:
            directory_path = os.path.join(creds.get('current_local_directory'), directory_name)

            try:
                # Attempt to create the directory locally
                os.makedirs(directory_path)
                self.message_signal.emit(f"Directory '{directory_path}' created successfully.")

            except (OSError, IOError) as e:
                QMessageBox.critical(None, 'Error', f"Error creating directory: {e}")
                self.message_signal.emit(f"Error creating directory: {e}")

            finally:
                self.model.get_files()
                self.notify_observers()

    def change_directory_handler(self):
        selected_path, ok = QInputDialog.getText(self, 'Input Dialog', 'Enter directory name:')

        if not ok:
            return

        try:
            is_directory = os.path.isdir(selected_path)

            if is_directory:
                # Call the method to change the directory
                self.change_directory(selected_path)

        except (OSError, TypeError) as e:
            # Append error message to the output_console
            self.message_signal.emit(f"change_directory_handler() {e}")

        finally:
            self.model.get_files()
            self.notify_observers()

    def change_directory(self, path ):
        # this is a function to change the current LOCAL working directory, it also uses this moment to refresh the local file list

        try:
            # Local file browser
            os.chdir(path)
            set_credentials(self.session_id, 'current_local_directory', os.getcwd() )
            self.model.get_files()
            self.notify_observers()
        except OSError as e:
            # Append error message to the output_console
            self.message_signal.emit(f"change_directory() {e}")

    def double_click_handler(self, index):
        creds = get_credentials(self.session_id)
        if index.isValid():
            # Always get the data from the first column (filename)
            filename_index = self.model.index(index.row(), 0)
            filename = self.model.data(filename_index, Qt.DisplayRole)

            # Remove type prefix if present ([DIR], [FILE], 📁, 📄, etc.)
            prefixes = ['[DIR]', '[FILE]', '[LINK]', '📁', '📄', '🔗']
            for prefix in prefixes:
                if filename.startswith(prefix):
                    filename = filename[len(prefix):].lstrip()
                    break

        try:
            if filename == "..":
                head, _ = self.split_path(creds.get('current_local_directory'))
                new_path = head
            else:
                new_path = os.path.join(creds.get('current_local_directory'), filename)

            # Check if the item is a directory
            is_directory = os.path.isdir(new_path)

            if is_directory:
                # Change the current working directory
                self.change_directory(new_path)
            else:
                # Handle file upload/download
                if self.is_local_view:
                    # Upload the file to the remote server
                    remote_path, _ = QFileDialog.getSaveFileName(self, "Select Remote Location", filename)
                    if remote_path:
                        self.upload_download(new_path)
                else:
                    # Download the file from the remote server
                    local_path, _ = QFileDialog.getSaveFileName(self, "Select Local Location", filename)
                    if local_path:
                        self.upload_download(new_path)

        except (OSError, IOError, RuntimeError) as e:
            self.message_signal.emit(f"double_click_handler() error: {e}")

    def context_menu_handler(self, point):
        ic(f"context_menu_handler: called on {self.__class__.__name__}, title={self.title}")
        
        # If point is not provided, use the center of the list widget
        if not point:
            point = self.table.rect().center()
            ic("context_menu_handler: using center of widget")

        # Get the currently focused widget
        # current_browser = self.focusWidget()
        current_browser = self.active_table
        ic(f"context_menu_handler: current_browser={current_browser}")
        
        if current_browser is not None:
            # Debug: check what's selected
            indexes = current_browser.selectedIndexes()
            ic(f"context_menu_handler: selected rows = {[i.row() for i in indexes]}")
            
            if not indexes:
                ic("context_menu_handler: WARNING - no rows selected!")
                # Don't show menu if nothing selected
                return
            
            menu = QMenu(self)
            # Add actions to the menu
            rename_action = menu.addAction("Rename")
            remove_dir_action = menu.addAction("Remove Directory")
            change_dir_action = menu.addAction("Change Directory")
            upload_download_action = menu.addAction("Upload/Download")
            prompt_and_create_directory = menu.addAction("Create Directory")
            view_edit_action = menu.addAction("View/Edit")
            
            # Add the new Refresh action
            refresh_action = menu.addAction("Refresh")
            
            menu.addSeparator()  # Visual separator
            
            # Add bookmark actions
            add_bookmark_action = menu.addAction("Add Bookmark")
            bookmarks_menu = menu.addMenu("Go to Bookmark")
            
            # Populate bookmarks submenu
            bookmarks = self.get_bookmarks()
            if bookmarks:
                for bookmark in bookmarks:
                    name = bookmark.get('name', 'Unnamed')
                    path = bookmark.get('path', '')
                    action = bookmarks_menu.addAction(name)
                    action.triggered.connect(lambda checked, p=path: self.navigate_to_bookmark(p))
            else:
                no_bookmarks_action = bookmarks_menu.addAction("No bookmarks")
                no_bookmarks_action.setEnabled(False)

            # Connect the actions to corresponding methods
            rename_action.triggered.connect(self.prompt_and_rename)
            remove_dir_action.triggered.connect(self.remove_directory_with_prompt)
            change_dir_action.triggered.connect(self.change_directory_handler)
            upload_download_action.triggered.connect(self.upload_download)
            prompt_and_create_directory.triggered.connect(self.prompt_and_create_directory)
            view_edit_action.triggered.connect(self.view_edit_file)
            
            # Connect the new Refresh action
            refresh_action.triggered.connect(self.refresh_files)
            
            # Connect bookmark action
            add_bookmark_action.triggered.connect(lambda: self.add_bookmark())

            # Show the menu at the cursor position
            menu.exec(current_browser.mapToGlobal(point))

    def upload_download(self):
        creds = get_credentials(self.session_id)
        # current_browser = self.focusWidget()
        current_browser = self.active_table
        if current_browser is not None and isinstance(current_browser, QTableView):
            # Get unique rows from selected indexes to avoid processing the same item multiple times
            indexes = current_browser.selectedIndexes()
            processed_rows = set()
            has_valid_item = False
            action = None

            # Global flags for user choices - initialize outside the loop
            skip_all = False
            overwrite_all = False
            resume_all = False
            
            job_id = None

            try:
                for index in indexes:
                    row = index.row()
                    if row in processed_rows:
                        continue
                    processed_rows.add(row)

                    filename = ""
                    if isinstance(index, QModelIndex):
                        if index.isValid():
                            filename_index = current_browser.model().index(row, 0)
                            filename = current_browser.model().data(filename_index, Qt.DisplayRole)
                            # Remove type prefix if present ([DIR], [FILE], 📁, 📄, etc.)
                            prefixes = ['[DIR]', '[FILE]', '[LINK]', '📁', '📄', '🔗']
                            for prefix in prefixes:
                                if filename.startswith(prefix):
                                    filename = filename[len(prefix):].lstrip()
                                    break
                    elif isinstance(index, str):
                        # Remove type prefix if present
                        prefixes = ['[DIR]', '[FILE]', '[LINK]', '📁', '📄', '🔗']
                        for prefix in prefixes:
                            if index.startswith(prefix):
                                filename = index[len(prefix):].lstrip()
                                break
                        else:
                            filename = index

                    if filename and filename != "..":  # Skip parent directory entry
                        if not self.is_complete_path(filename):
                            selected_path = os.path.join(creds.get('current_local_directory'), filename)
                        else:
                            selected_path = self.normalize_path(filename)

                        remote_entry_path = self.get_normalized_remote_path(creds.get('current_remote_directory'), filename)
                        job_id = None  # Initialize job_id to avoid UnboundLocalError

                        if os.path.isdir(selected_path):
                            self.message_signal.emit(f"Uploading directory: {selected_path}")
                            # Pass the global flags to directory upload
                            skip_all, overwrite_all, resume_all = self.upload_directory(
                                selected_path, remote_entry_path, 
                                skip_all=skip_all, overwrite_all=overwrite_all, resume_all=resume_all)
                        else:
                            # Handle individual file upload with resume support
                            
                            # Check if file exists remotely
                            file_exists = self.sftp_exists(remote_entry_path)
                            
                            # If no global flags are set and file exists, prompt user
                            if file_exists and not skip_all and not overwrite_all and not resume_all:
                                action = self.prompt_overwrite(remote_entry_path)
                                if action == "cancel":
                                    return
                                elif action == "skip":
                                    continue
                                elif action == "skip_all":
                                    skip_all = True
                                    continue
                                elif action == "overwrite_all":
                                    overwrite_all = True
                                elif action == "resume_all":
                                    resume_all = True
                            elif not file_exists:
                                action = "upload"
                            
                            # Apply global flags to determine final action
                            if skip_all:
                                continue
                            elif overwrite_all and file_exists:
                                action = "overwrite"
                            elif resume_all and file_exists:
                                action = "resume"

                            # Execute the upload if not skipping
                            if not skip_all:
                                self.message_signal.emit(f"Uploading file: {selected_path}")
                                job_id = create_random_integer()
                                queue_item = QueueItem(os.path.basename(selected_path), job_id)
                                
                                resume = (action == "resume")
                                
                                try:
                                    ops = self.get_sftp_operations()
                                    ops.upload(selected_path, remote_entry_path, job_id=str(job_id), resume=resume)
                                    self.transfer_started.emit(str(job_id))
                                except Exception as e:
                                    self.message_signal.emit(f"Upload failed: {e}")
                                    ic(e)
                        has_valid_item = True
            
            except (OSError, IOError, RuntimeError) as e:
                self.message_signal.emit(f"upload_download() error: {e}")
                ic(e)
                # Print the full traceback to help debug
                import traceback
                ic(traceback.format_exc())
            finally:
                # Clean up any remaining job resources
                if job_id is not None:
                    delete_response_queue(job_id)
        else:
            self.message_signal.emit("Invalid item or empty path.")

        if not has_valid_item:
            self.message_signal.emit("No valid items selected.")
        else:
            self.message_signal.emit("Current browser is not a valid QTableView.")

    def _get_transfer_action(self, target_path, skip_all, overwrite_all, resume_all, 
                            is_remote_target=False):
        """
        Determine action for file transfer based on existing file and user preferences.
        
        Args:
            target_path: Path to check (local or remote)
            skip_all: Whether to skip all existing files
            overwrite_all: Whether to overwrite all existing files  
            resume_all: Whether to resume all existing files
            is_remote_target: True if target is remote, False if local
            
        Returns:
            tuple: (action, skip_all, overwrite_all, resume_all)
                   action can be: 'skip', 'overwrite', 'resume', 'cancel', None
        """
        # Check global flags first
        if skip_all:
            return "skip", skip_all, overwrite_all, resume_all
        if overwrite_all:
            return "overwrite", skip_all, overwrite_all, resume_all
        if resume_all:
            return "resume", skip_all, overwrite_all, resume_all
        
        # Check if target exists
        if is_remote_target:
            exists = self.sftp_exists(target_path)
        else:
            exists = os.path.exists(target_path)
        
        if not exists:
            return None, skip_all, overwrite_all, resume_all
        
        # Prompt user for action
        action = self.prompt_overwrite(target_path)
        
        if action == "skip_all":
            return "skip", True, overwrite_all, resume_all
        elif action == "overwrite_all":
            return "overwrite", skip_all, True, resume_all
        elif action == "resume_all":
            return "resume", skip_all, overwrite_all, True
        elif action in {"skip", "overwrite", "resume", "cancel"}:
            return action, skip_all, overwrite_all, resume_all
        
        return None, skip_all, overwrite_all, resume_all

    def _ensure_directory_exists(self, directory_path, is_remote=False):
        """
        Ensure a directory exists, creating it if necessary.
        
        Args:
            directory_path: Path to directory
            is_remote: True if remote directory, False if local
            
        Returns:
            bool: True if directory exists or was created successfully
        """
        try:
            if is_remote:
                if not self.sftp_exists(directory_path):
                    return self.sftp_mkdir(directory_path)
                return True
            else:
                os.makedirs(directory_path, exist_ok=True)
                return True
        except (OSError, IOError, RuntimeError) as e:
            self.message_signal.emit(f"Directory creation error for {directory_path}: {e}")
            return False

    def traverse_and_transfer(self, source_dir, dest_dir, is_source_remote, is_dest_remote,
                             skip_all=False, overwrite_all=False, resume_all=False,
                             always=0, is_top_level=True):
        """
        Unified directory traversal and transfer method.
        
        Args:
            source_dir: Source directory path
            dest_dir: Destination directory path
            is_source_remote: True if source is remote
            is_dest_remote: True if destination is remote
            skip_all: Skip all existing files flag
            overwrite_all: Overwrite all existing files flag
            resume_all: Resume all existing files flag
            always: Flag for directory overwrite confirmation (0=ask, 1=always)
            is_top_level: True if this is the initial call
            
        Returns:
            tuple: (skip_all, overwrite_all, resume_all) - updated flags
        """
        creds = get_credentials(self.session_id)
        action = None
        
        try:
            # Check destination directory at top level
            if is_top_level and is_dest_remote:
                target_exists = self.sftp_exists(dest_dir)
                if target_exists and self.is_remote_directory(dest_dir) and not always:
                    response = self.show_prompt_dialog(
                        f"The folder {dest_dir} already exists. Do you want to continue?",
                        "Transfer Confirmation"
                    )
                    if response == Qt.MsgBtn_No:
                        return skip_all, overwrite_all, resume_all
                    elif response == Qt.MsgBtn_YesToAll:
                        always = 1
                    elif response != Qt.MsgBtn_Yes:
                        return skip_all, overwrite_all, resume_all
            
            # Ensure destination directory exists
            if not self._ensure_directory_exists(dest_dir, is_dest_remote):
                return skip_all, overwrite_all, resume_all
            
            # Get directory contents
            if is_source_remote:
                entries = self.sftp_listdir(source_dir)
            else:
                entries = os.listdir(source_dir)
            
            # Process each entry
            for name in entries:
                if is_source_remote:
                    source_path = self.get_normalized_remote_path(source_dir, name)
                    dest_path = os.path.join(dest_dir, name)
                    is_dir = self.is_remote_directory(source_path)
                else:
                    source_path = os.path.join(source_dir, name)
                    # For remote destination, use forward slashes
                    if is_dest_remote:
                        dest_path = self.get_normalized_remote_path(dest_dir, name)
                    else:
                        dest_path = os.path.join(dest_dir, name)
                    is_dir = os.path.isdir(source_path)
                
                if is_dir:
                    # Recursively process subdirectories
                    action_result = self._get_transfer_action(
                        dest_path, skip_all, overwrite_all, resume_all, is_dest_remote
                    )
                    action, skip_all, overwrite_all, resume_all = action_result
                    
                    if action == "cancel":
                        return skip_all, overwrite_all, resume_all
                    if action == "skip":
                        continue
                    
                    self.message_signal.emit(f"Processing directory: {source_path}")
                    skip_all, overwrite_all, resume_all = self.traverse_and_transfer(
                        source_path, dest_path, is_source_remote, is_dest_remote,
                        skip_all, overwrite_all, resume_all, always, is_top_level=False
                    )
                else:
                    # Handle files
                    action_result = self._get_transfer_action(
                        dest_path, skip_all, overwrite_all, resume_all, is_dest_remote
                    )
                    action, skip_all, overwrite_all, resume_all = action_result
                    
                    if action == "cancel":
                        return skip_all, overwrite_all, resume_all
                    if action == "skip":
                        continue
                    
                    resume = (action == "resume" or resume_all)
                    
                    self.message_signal.emit(f"Transferring: {source_path} to {dest_path}")
                    
                    job_id = create_random_integer()
                    
                    try:
                        ops = self.get_sftp_operations()
                        if is_source_remote:
                            ops.download(source_path, dest_path, job_id=str(job_id), resume=resume)
                        else:
                            ops.upload(source_path, dest_path, job_id=str(job_id), resume=resume)
                        self.transfer_started.emit(str(job_id))
                    except Exception as e:
                        self.message_signal.emit(f"Transfer failed: {e}")
                        ic(e)
        
        except (OSError, IOError, RuntimeError) as e:
            operation = "upload" if not is_source_remote else "download"
            self.message_signal.emit(f"traverse_and_transfer ({operation}) error: {e}")
            ic(e)
        finally:
            self.notify_observers()
        
        return skip_all, overwrite_all, resume_all

    def upload_directory(self, source_directory, destination_directory, 
                        skip_all=False, overwrite_all=False, resume_all=False, always=0):
        """
        Upload a directory and its contents to the remote server.
        Uses unified traverse_and_transfer method.
        """
        return self.traverse_and_transfer(
            source_directory, destination_directory,
            is_source_remote=False, is_dest_remote=True,
            skip_all=skip_all, overwrite_all=overwrite_all, resume_all=resume_all,
            always=always, is_top_level=True
        )

    def prompt_overwrite(self, item_path):
        """Prompt user for overwrite action - should be implemented in base class"""
        msg_box = QMessageBox()
        msg_box.setIcon(Qt.MsgIcon_Question)
        msg_box.setText(f"The item '{item_path}' already exists.")
        msg_box.setInformativeText("What would you like to do?")
        msg_box.setWindowTitle("Overwrite Confirmation")

        cancel_btn = msg_box.addButton("Cancel All", Qt.MsgRole_RejectRole)
        skip_btn = msg_box.addButton("Skip", Qt.MsgRole_NoRole)
        skip_all_btn = msg_box.addButton("Skip All", Qt.MsgRole_NoRole)
        overwrite_btn = msg_box.addButton("Overwrite", Qt.MsgRole_YesRole)
        overwrite_all_btn = msg_box.addButton("Overwrite All", Qt.MsgRole_YesRole)
        resume_btn = msg_box.addButton("Resume", Qt.MsgRole_AcceptRole)
        resume_all_btn = msg_box.addButton("Resume All", Qt.MsgRole_AcceptRole)

        msg_box.exec()

        if msg_box.clickedButton() == cancel_btn:
            return "cancel"
        elif msg_box.clickedButton() == skip_btn:
            return "skip"
        elif msg_box.clickedButton() == skip_all_btn:
            return "skip_all"
        elif msg_box.clickedButton() == overwrite_btn:
            return "overwrite"
        elif msg_box.clickedButton() == overwrite_all_btn:
            return "overwrite_all"
        elif msg_box.clickedButton() == resume_btn:
            return "resume"
        elif msg_box.clickedButton() == resume_all_btn:
            return "resume_all"
            
    def show_prompt_dialog(self, text, title):
        dialog = QMessageBox(self.parent())
        dialog.setWindowTitle(title)
        dialog.setText(text)
        dialog.setStandardButtons(Qt.MsgBtn_Yes | Qt.MsgBtn_No | Qt.MsgBtn_YesToAll)
        dialog.setDefaultButton(Qt.MsgBtn_Yes)

        return dialog.exec()

    def view_edit_file(self):
        """View/Edit a text file - works for both local and remote files."""
        from sftp_textviewer import TextViewerWindow, is_text_file, MAX_FILE_SIZE
        
        creds = get_credentials(self.session_id)
        current_browser = self.active_table
        if current_browser is not None and isinstance(current_browser, QTableView):
            indexes = current_browser.selectedIndexes()
            if indexes:
                index = indexes[0]
                selected_item_text = current_browser.model().data(index, Qt.DisplayRole)
                # Remove emoji prefixes
                prefixes = ['📁', '📄', '🔗']
                for prefix in prefixes:
                    if selected_item_text.startswith(prefix):
                        selected_item_text = selected_item_text[len(prefix):].lstrip()
                        break
                
                # Check if it's a directory
                if self.is_remote_directory(selected_item_text) or self.is_remote_file(selected_item_text):
                    is_remote = True
                    is_dir = self.is_remote_directory(selected_item_text)
                else:
                    # Check local
                    local_path = os.path.join(creds.get('current_local_directory', '.'), selected_item_text)
                    is_remote = False
                    is_dir = os.path.isdir(local_path)
                
                if is_dir:
                    QMessageBox.information(None, "View", "Cannot view directories. Select a file.")
                    return
                
                if is_remote:
                    # Remote file
                    remote_path = self.get_normalized_remote_path(creds.get('current_remote_directory'), selected_item_text)
                    
                    # Get file size first
                    try:
                        file_stat = self.session_api.stat(remote_path)
                        file_size = file_stat.st_size if hasattr(file_stat, 'st_size') else 0
                    except (OSError, IOError, paramiko.SSHException) as e:
                        self.message_signal.emit(f"Could not get file info: {e}")
                        return
                    
                    if file_size > MAX_FILE_SIZE:
                        result = QMessageBox.question(
                            None, "Large File",
                            f"File is large ({file_size / (1024*1024):.1f} MB). Continue?",
                            Qt.MsgBtn_Yes | Qt.MsgBtn_No,
                            Qt.MsgBtn_No
                        )
                        if result == Qt.MsgBtn_No:
                            return
                    
                    # Download to temp file
                    import tempfile
                    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(selected_item_text)[1]) as temp_file:
                        temp_path = temp_file.name
                    
                    job_id = create_random_integer()
                    
                    try:
                        ops = self.get_sftp_operations()
                        ops.download(remote_path, temp_path, job_id=str(job_id))
                    except Exception as e:
                        ic(f"view_edit_file: download failed: {e}")
                        self.message_signal.emit(f"File download failed: {e}")
                        return
                    
                    ic(f"view_edit_file: download complete, checking text file: {temp_path}")
                    # Check if it's a text file
                    if not is_text_file(temp_path):
                        result = QMessageBox.question(
                            None, "Binary File",
                            "This file appears to be binary. View anyway?",
                            Qt.MsgBtn_Yes | Qt.MsgBtn_No,
                            Qt.MsgBtn_No
                        )
                        if result == Qt.MsgBtn_No:
                            os.unlink(temp_path)
                            return
                    
                    ic(f"view_edit_file: opening viewer for {temp_path}")
                    # Open viewer
                    self.viewer = TextViewerWindow(
                        file_path=temp_path,
                        remote_path=remote_path,
                        session_api=self.session_api
                    )
                    self.viewer.setWindowTitle(f"View: {remote_path}")
                    self.viewer.show()
                    ic(f"view_edit_file: viewer shown, visible={self.viewer.isVisible()}")
                    self.message_signal.emit(f"Opened: {selected_item_text}")
                    
                else:
                    # Local file
                    local_path = os.path.join(creds.get('current_local_directory', '.'), selected_item_text)
                    
                    if not os.path.exists(local_path):
                        self.message_signal.emit(f"File not found: {local_path}")
                        return
                    
                    file_size = os.path.getsize(local_path)
                    if file_size > MAX_FILE_SIZE:
                        result = QMessageBox.question(
                            None, "Large File",
                            f"File is large ({file_size / (1024*1024):.1f} MB). Continue?",
                            Qt.MsgBtn_Yes | Qt.MsgBtn_No,
                            Qt.MsgBtn_No
                        )
                        if result == Qt.MsgBtn_No:
                            return
                    
                    if not is_text_file(local_path):
                        result = QMessageBox.question(
                            None, "Binary File",
                            "This file appears to be binary. View anyway?",
                            Qt.MsgBtn_Yes | Qt.MsgBtn_No,
                            Qt.MsgBtn_No
                        )
                        if result == Qt.MsgBtn_No:
                            return
                    
                    # Open viewer
                    self.viewer = TextViewerWindow(file_path=local_path)
                    self.viewer.setWindowTitle(f"View: {local_path}")
                    self.viewer.show()
                    self.message_signal.emit(f"Opened: {selected_item_text}")
            else:
                self.message_signal.emit("No item selected.")
        else:
            self.message_signal.emit("Current browser is not a valid QTableView.")

    def sftp_exists(self, path):
        try:
            ops = self.get_sftp_operations()
            exist = ops.exists(path)
            return exist
        except Exception as e:
            self.message_signal.emit(f"sftp_exists() {e}")
            return False
        
    def refresh_files(self):
        if hasattr(self.model, 'invalidate_cache'):
            self.model.invalidate_cache()
        self.get_files()
        self.notify_observers()

    def get_current_directory(self):
        """Get the current directory path - to be overridden by subclasses"""
        creds = get_credentials(self.session_id)
        return creds.get('current_local_directory', '.')

    def add_bookmark(self, name=None):
        """Add current directory to bookmarks"""
        try:
            from sftp_hostdataeditor import load_connection_data, save_connection_data
            
            host_data = load_connection_data()
            creds = get_credentials(self.session_id)
            hostname = creds.get('hostname', 'localhost')
            current_dir = self.get_current_directory()
            
            if not name:
                name = os.path.basename(current_dir) or current_dir
            
            if hostname not in host_data.get('bookmarks', {}):
                host_data['bookmarks'][hostname] = []
            
            # Check if already bookmarked
            for bookmark in host_data['bookmarks'][hostname]:
                if isinstance(bookmark, dict):
                    if bookmark.get('path') == current_dir:
                        self.message_signal.emit(f"Directory already bookmarked: {name}")
                        return False
                elif bookmark == current_dir:
                    # Convert old format to new format
                    self.message_signal.emit(f"Directory already bookmarked: {name}")
                    return False
            
            # Add new bookmark with metadata
            host_data['bookmarks'][hostname].append({
                'name': name,
                'path': current_dir,
                'is_remote': self.is_remote_browser()
            })
            
            if save_connection_data(host_data):
                self.message_signal.emit(f"Bookmark added: {name} ({current_dir})")
                return True
            else:
                self.message_signal.emit("Failed to save bookmark")
                return False
                
        except (OSError, IOError, RuntimeError) as e:
            self.message_signal.emit(f"Error adding bookmark: {e}")
            return False

    def get_bookmarks(self):
        """Get bookmarks for current hostname"""
        try:
            from sftp_hostdataeditor import load_connection_data
            
            host_data = load_connection_data()
            creds = get_credentials(self.session_id)
            hostname = creds.get('hostname', 'localhost')
            
            bookmarks = host_data.get('bookmarks', {}).get(hostname, [])
            # Normalize old format (strings) to new format (dicts)
            normalized = []
            for b in bookmarks:
                if isinstance(b, str):
                    normalized.append({
                        'name': os.path.basename(b) or b,
                        'path': b,
                        'is_remote': self.is_remote_browser()
                    })
                else:
                    normalized.append(b)
            return normalized
            
        except (OSError, IOError, RuntimeError) as e:
            self.message_signal.emit(f"Error loading bookmarks: {e}")
            return []

    def navigate_to_bookmark(self, path):
        """Navigate to a bookmarked directory - to be overridden by subclasses"""
        self.message_signal.emit(f"Navigating to: {path}")
        return False  # Subclasses should implement actual navigation

    def _show_bookmarks_menu(self):
        bookmarks = self.get_bookmarks()
        menu = QMenu(self)
        
        add_action = menu.addAction("⭐ Add Current Directory")
        add_action.triggered.connect(lambda: self.add_bookmark())
        
        if bookmarks:
            menu.addSeparator()
            for bm in bookmarks:
                if isinstance(bm, dict):
                    name = bm.get('name', bm.get('path', 'Unknown'))
                    path = bm.get('path', '')
                    action = menu.addAction(f"📁 {name}")
                    action.triggered.connect(lambda checked, p=path: self.navigate_to_bookmark(p))
        
        menu.addSeparator()
        manage_action = menu.addAction("⚙️ Manage Bookmarks...")
        manage_action.triggered.connect(self._manage_bookmarks)
        
        menu.exec(self.bookmarks_btn.mapToGlobal(self.bookmarks_btn.rect().bottomLeft()))

    def _manage_bookmarks(self):
        bookmarks = self.get_bookmarks()
        if not bookmarks:
            QMessageBox.information(self, "Manage Bookmarks", "No bookmarks to manage.")
            return
        
        items = []
        for bm in bookmarks:
            if isinstance(bm, dict):
                items.append(f"{bm.get('name', 'Unknown')} - {bm.get('path', '')}")
        
        item, ok = QInputDialog.getItem(
            self, "Manage Bookmarks", 
            "Select bookmark to delete:", 
            items, 0, False
        )
        
        if ok and item:
            from sftp_hostdataeditor import load_connection_data, save_connection_data
            host_data = load_connection_data()
            creds = get_credentials(self.session_id)
            hostname = creds.get('hostname', 'localhost')
            
            name = item.split(' - ')[0]
            host_data['bookmarks'][hostname] = [
                bm for bm in host_data.get('bookmarks', {}).get(hostname, [])
                if isinstance(bm, dict) and bm.get('name') != name
            ]
            
            if save_connection_data(host_data):
                self.message_signal.emit(f"Bookmark '{name}' deleted")
