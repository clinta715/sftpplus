from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, 
    QPushButton, QToolButton, QLabel, QFrame
)
from sftp_qt_compat import Qt  # Use compatibility layer for Qt enums
from PyQt6.QtCore import pyqtSignal
from icecream import ic

from sftp_filebrowserclass import FileBrowser
from sftp_remotefilebrowserclass import RemoteFileBrowser
from sftp_theme import DARK_THEME, LIGHT_THEME


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
    
    message = pyqtSignal(str)
    transfer_started = pyqtSignal(str)  # Emits transfer_id
    
    def __init__(self, session_id, parent=None, auto_initialize=True):
        super().__init__(parent)
        self.session_id = session_id
        self._local_browser_visible = True
        self._auto_initialize = auto_initialize
        self._initialized = False
        self._init_ui()
        self._setup_browsers()
        self._connect_signals()
        
        # If auto_initialize is False, defer initialization
        # Caller must call initialize() explicitly after connection is ready
        if not auto_initialize:
            ic(f"FileBrowserPanel: Created with deferred initialization for session {session_id}")
        else:
            self._initialized = True
    
    def initialize(self):
        """Initialize the remote browser - must be called after connection is ready"""
        if self._initialized:
            ic(f"FileBrowserPanel.initialize: already initialized, skipping")
            return
        
        ic(f"FileBrowserPanel.initialize: Initializing remote browser for session {self.session_id}")
        self._initialized = True
        
        # Initialize remote browser
        if hasattr(self, 'right_browser') and self.right_browser:
            self.right_browser.initialize()
    
    def _init_ui(self):
        """Initialize the UI layout"""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Toolbar with toggle button
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setContentsMargins(5, 2, 5, 2)
        toolbar_layout.setSpacing(5)
        
        # Toggle button for local browser
        self.toggle_local_btn = QToolButton()
        self.toggle_local_btn.setText("◀")
        self.toggle_local_btn.setToolTip("Toggle Local Files")
        self.toggle_local_btn.setCheckable(True)
        self.toggle_local_btn.setChecked(True)
        self.toggle_local_btn.clicked.connect(self._toggle_local_browser)
        toolbar_layout.addWidget(self.toggle_local_btn)
        
        # Labels
        self.local_label = QLabel("📁 Local Files")
        self.local_label.setStyleSheet(f"font-weight: bold; color: {DARK_THEME['text_secondary']};")
        toolbar_layout.addWidget(self.local_label)
        
        toolbar_layout.addStretch()
        
        self.remote_label = QLabel("🌐 Remote Files")
        self.remote_label.setStyleSheet(f"font-weight: bold; color: {DARK_THEME['text_secondary']};")
        toolbar_layout.addWidget(self.remote_label)
        
        toolbar_layout.addStretch()
        
        main_layout.addLayout(toolbar_layout)
        
        # Separator line
        line = QFrame()
        line.setFrameShape(Qt.Frame_HLine)
        line.setFrameShadow(Qt.Frame_Sunken)
        line.setStyleSheet(f"color: {DARK_THEME['border']};")
        main_layout.addWidget(line)
        
        # Splitter for browsers
        splitter = QSplitter(Qt.Horizontal)
        
        # Local browser container (will be toggleable)
        self.local_container = QWidget()
        local_layout = QVBoxLayout()
        local_layout.setContentsMargins(0, 0, 0, 0)
        local_layout.setSpacing(0)
        self.local_container.setLayout(local_layout)
        
        # Remote browser container
        self.remote_container = QWidget()
        remote_layout = QVBoxLayout()
        remote_layout.setContentsMargins(0, 0, 0, 0)
        remote_layout.setSpacing(0)
        self.remote_container.setLayout(remote_layout)
        
        splitter.addWidget(self.local_container)
        splitter.addWidget(self.remote_container)
        splitter.setSizes([300, 500])  # Default split ratio
        
        main_layout.addWidget(splitter)
        
        # Store reference to layout for adding browsers
        self._local_layout = local_layout
        self._remote_layout = remote_layout
        self._splitter = splitter
        
        self.setLayout(main_layout)
    
    def _setup_browsers(self):
        """Create and add the file browsers"""
        # Create browsers
        self.left_browser = FileBrowser("Local Files", self.session_id)
        self.right_browser = RemoteFileBrowser("Remote Files", self.session_id)
        
        # Add to containers
        self._local_layout.addWidget(self.left_browser)
        self._remote_layout.addWidget(self.right_browser)
        
        # Focus policy
        self.left_browser.table.setFocusPolicy(Qt.StrongFocus)
        self.right_browser.table.setFocusPolicy(Qt.StrongFocus)
    
    def _connect_signals(self):
        """Connect browser signals"""
        # Observer pattern
        self.left_browser.add_observer(self.right_browser)
        self.right_browser.add_observer(self.left_browser)
        
        # Message signals
        self.left_browser.message_signal.connect(self._handle_message)
        self.right_browser.message_signal.connect(self._handle_message)
        
        # Transfer started signal (pass through from both browsers)
        self.left_browser.transfer_started.connect(self.transfer_started)
        self.right_browser.transfer_started.connect(self.transfer_started)
    
    def _toggle_local_browser(self):
        """Toggle local browser visibility"""
        self._local_browser_visible = self.toggle_local_btn.isChecked()
        
        if self._local_browser_visible:
            self.local_container.show()
            self.toggle_local_btn.setText("◀")
        else:
            self.local_container.hide()
            self.toggle_local_btn.setText("▶")
        
        # Update splitter sizes
        self._update_splitter_sizes()
    
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
