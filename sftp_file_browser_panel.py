from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, 
    QPushButton, QToolButton, QLabel, QFrame
)
from sftp_qt_compat import Qt  # Use compatibility layer for Qt enums
from PySide6.QtCore import Signal

from sftp_filebrowserclass import FileBrowser
from sftp_remotefilebrowserclass import RemoteFileBrowser
from sftp_theme import DARK_THEME, LIGHT_THEME
from sftp_preview_widget import FilePreviewWidget


class FileBrowserPanel(QWidget):
    """
    File browser panel with collapsible local browser and responsive layout.
    
    Features:
    - Side-by-side local and remote file browsers
    - Collapsible local browser panel (can be hidden with toggle button)
    - Resizable panels using QSplitter
    - Observer pattern for cross-browser synchronization
    - Clean, integrated UI
    
    Signals:
        message: Emitted for status messages
        transfer_started: Emitted when a transfer is initiated
    """
    
    message = Signal(str)
    transfer_started = Signal(str)  # Emits transfer_id
    
    def __init__(self, session_id, parent=None, auto_initialize=True):
        super().__init__(parent)
        self.session_id = session_id
        self._local_browser_visible = True
        self._preview_visible = False
        self._auto_initialize = auto_initialize
        self._initialized = False
        self._init_ui()
        self._setup_browsers()
        self._connect_signals()
        
        if not auto_initialize:
            pass
        else:
            self._initialized = True
    
    def initialize(self):
        """Initialize the remote browser - must be called after connection is ready"""
        if self._initialized:
            pass
            return
        
        self._initialized = True
        
        # Initialize remote browser
        if hasattr(self, 'right_browser') and self.right_browser:
            self.right_browser.initialize()
    
    def _init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setContentsMargins(5, 2, 5, 2)
        toolbar_layout.setSpacing(5)
        
        self.toggle_local_btn = QToolButton()
        self.toggle_local_btn.setText("◀")
        self.toggle_local_btn.setToolTip("Toggle Local Files")
        self.toggle_local_btn.setCheckable(True)
        self.toggle_local_btn.setChecked(True)
        self.toggle_local_btn.clicked.connect(self._toggle_local_browser)
        toolbar_layout.addWidget(self.toggle_local_btn)
        
        self.local_label = QLabel("📁 Local Files")
        self.local_label.setStyleSheet(f"font-weight: bold; color: {DARK_THEME['text_secondary']};")
        toolbar_layout.addWidget(self.local_label)
        
        toolbar_layout.addStretch()
        
        self.remote_label = QLabel("🌐 Remote Files")
        self.remote_label.setStyleSheet(f"font-weight: bold; color: {DARK_THEME['text_secondary']};")
        toolbar_layout.addWidget(self.remote_label)
        
        toolbar_layout.addStretch()
        
        self.toggle_preview_btn = QToolButton()
        self.toggle_preview_btn.setText("👁")
        self.toggle_preview_btn.setToolTip("Toggle Preview (Ctrl+P)")
        self.toggle_preview_btn.setCheckable(True)
        self.toggle_preview_btn.setChecked(False)
        self.toggle_preview_btn.clicked.connect(self.toggle_preview)
        toolbar_layout.addWidget(self.toggle_preview_btn)
        
        main_layout.addLayout(toolbar_layout)
        
        line = QFrame()
        line.setFrameShape(Qt.Frame_HLine)
        line.setFrameShadow(Qt.Frame_Sunken)
        line.setStyleSheet(f"color: {DARK_THEME['border']};")
        main_layout.addWidget(line)
        
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        
        self.browser_splitter = QSplitter(Qt.Horizontal)
        
        self.local_container = QWidget()
        local_layout = QVBoxLayout()
        local_layout.setContentsMargins(0, 0, 0, 0)
        local_layout.setSpacing(0)
        self.local_container.setLayout(local_layout)
        
        self.remote_container = QWidget()
        remote_layout = QVBoxLayout()
        remote_layout.setContentsMargins(0, 0, 0, 0)
        remote_layout.setSpacing(0)
        self.remote_container.setLayout(remote_layout)
        
        self.browser_splitter.addWidget(self.local_container)
        self.browser_splitter.addWidget(self.remote_container)
        self.browser_splitter.setSizes([300, 500])
        
        content_layout.addWidget(self.browser_splitter)
        
        self.preview_widget = FilePreviewWidget(self)
        self.preview_widget.setVisible(False)
        content_layout.addWidget(self.preview_widget)
        
        main_layout.addLayout(content_layout, stretch=1)
        
        self._local_layout = local_layout
        self._remote_layout = remote_layout
        self._splitter = self.browser_splitter
        
        self.setLayout(main_layout)
    
    def _setup_browsers(self):
        """Create and add the file browsers"""
        # Create browsers
        self.left_browser = FileBrowser("Local Files", self.session_id)
        self.right_browser = RemoteFileBrowser("Remote Files", self.session_id)
        
        # Track last active browser
        self._last_active_browser = self.right_browser  # Default to remote
        
        # Add to containers
        self._local_layout.addWidget(self.left_browser)
        self._remote_layout.addWidget(self.right_browser)
        
        # Focus policy
        self.left_browser.table.setFocusPolicy(Qt.StrongFocus)
        self.right_browser.table.setFocusPolicy(Qt.StrongFocus)
        
        # Install event filters on viewports to track clicks
        self.left_browser.table.viewport().installEventFilter(self)
        self.right_browser.table.viewport().installEventFilter(self)
        
        # Also track focus events on the tables
        self.left_browser.table.focusInEvent = lambda e: self._on_browser_focused(self.left_browser)
        self.right_browser.table.focusInEvent = lambda e: self._on_browser_focused(self.right_browser)
    
    def _on_browser_focused(self, browser):
        """Called when a browser table gains focus"""
        self._last_active_browser = browser
    
    def eventFilter(self, obj, event):
        """Track which browser table viewport was last clicked"""
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.MouseButtonPress:
            if obj == self.left_browser.table.viewport():
                self._last_active_browser = self.left_browser
            elif obj == self.right_browser.table.viewport():
                self._last_active_browser = self.right_browser
        return super().eventFilter(obj, event)
    
    def get_active_browser(self):
        """Return the last active browser (local or remote)"""
        return self._last_active_browser
    
    def _connect_signals(self):
        self.left_browser.add_observer(self.right_browser)
        self.right_browser.add_observer(self.left_browser)
        
        self.left_browser.message_signal.connect(self._handle_message)
        self.right_browser.message_signal.connect(self._handle_message)
        
        self.left_browser.transfer_started.connect(self.transfer_started)
        self.right_browser.transfer_started.connect(self.transfer_started)
        
        self.right_browser.table.selectionModel().selectionChanged.connect(
            self._on_remote_selection_changed
        )
    
    def _on_remote_selection_changed(self, selected, deselected):
        if not self._preview_visible:
            return
        
        indexes = self.right_browser.table.selectionModel().selectedRows()
        if not indexes:
            self.preview_widget.clear_preview()
            return
        
        index = indexes[0]
        proxy_model = self.right_browser.table.model()
        source_index = proxy_model.mapToSource(index)
        row = source_index.row()
        
        if row < 0 or row >= len(self.right_browser.model.file_list):
            return
        
        file_info = self.right_browser.model.file_list[row]
        
        if not isinstance(file_info, (list, tuple)) or len(file_info) < 4:
            return
        
        filename = file_info[0]
        file_size = file_info[1]
        mode = file_info[2]
        
        import stat as stat_mod
        is_dir = stat_mod.S_ISDIR(mode) if filename != ".." else True
        
        if is_dir:
            self.preview_widget.clear_preview()
            return
        
        creds = self._get_credentials(self.right_browser.session_id)
        current_dir = creds.get('current_remote_directory', '.')
        file_path = f"{current_dir}/{filename}".replace('//', '/')
        
        modified = file_info[3]
        permissions = oct(mode)[-4:] if filename != ".." else ""
        
        self.preview_widget.preview_file(
            file_path, file_size, modified, permissions,
            sftp_api=self.right_browser.session_api
        )
    
    def _get_credentials(self, session_id):
        from sftp_creds import get_credentials
        return get_credentials(session_id)
    
    def _toggle_local_browser(self):
        self._local_browser_visible = self.toggle_local_btn.isChecked()
        
        if self._local_browser_visible:
            self.local_container.show()
            self.toggle_local_btn.setText("◀")
        else:
            self.local_container.hide()
            self.toggle_local_btn.setText("▶")
        
        self._update_splitter_sizes()
    
    def toggle_preview(self):
        self._preview_visible = not self._preview_visible
        self.toggle_preview_btn.setChecked(self._preview_visible)
        
        if self._preview_visible:
            self.preview_widget.show()
            self._on_remote_selection_changed(None, None)
        else:
            self.preview_widget.hide()
            self.preview_widget.clear_preview()
    
    def _update_splitter_sizes(self):
        """Update splitter sizes based on visibility"""
        if self._local_browser_visible:
            self._splitter.setSizes([300, 500])
        else:
            self._splitter.setSizes([0, 800])
    
    def _handle_message(self, message):
        """Forward message signals"""
        self.message.emit(message)
    
    def add_observer(self, observer):
        """Add an observer to be notified"""
        if hasattr(self, 'left_browser'):
            self.left_browser.add_observer(observer)
        if hasattr(self, 'right_browser'):
            self.right_browser.add_observer(observer)
    
    def remove_observer(self, observer):
        """Remove an observer"""
        if hasattr(self, 'left_browser'):
            self.left_browser.remove_observer(observer)
        if hasattr(self, 'right_browser'):
            self.right_browser.remove_observer(observer)
    
    @property
    def left_browser(self):
        """Access to local file browser"""
        return getattr(self, '_left_browser', None)
    
    @left_browser.setter
    def left_browser(self, value):
        self._left_browser = value
    
    @property
    def right_browser(self):
        """Access to remote file browser"""
        return getattr(self, '_right_browser', None)
    
    @right_browser.setter
    def right_browser(self, value):
        self._right_browser = value
    
    def cleanup(self):
        """Cleanup resources"""
        try:
            if hasattr(self, 'right_browser') and self.right_browser:
                self.right_browser.close_sftp_connection()
        except (OSError, IOError, RuntimeError) as e:
            pass
