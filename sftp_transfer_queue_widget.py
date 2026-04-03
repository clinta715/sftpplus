from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                            QListWidget, QTextEdit, QProgressBar, QSizePolicy,
                            QLabel, QListWidgetItem, QScrollArea, QFrame, QCheckBox,
                            QMessageBox, QMenu, QSpinBox)
from sftp_qt_compat import Qt  # Use compatibility layer for Qt enums
from PySide6.QtCore import QThreadPool, QTimer, QMutex, QMutexLocker, Signal, Slot
import inspect
import os
import json
import queue
import time
import logging
import sys

from sftp_downloadworkerclass import Transfer, DownloadWorker, SFTPJob, sftp_queue, clear_sftp_queue, response_queues, response_queues_lock
from sftp_theme import (BUTTON_STYLE_DARK, LIST_WIDGET_STYLE_DARK, PROGRESS_BAR_STYLE_DARK,
                        TEXT_EDIT_STYLE_DARK, DARK_THEME)
from sftp_preferences import get_preferences
import sftp_hostdataeditor
from sftp_transfer_history import log_transfer
from sftp_platform import get_transfer_queue_path, create_secure_directory, secure_file_permissions, is_windows

logger = logging.getLogger('sftp.transfer_queue')


QUEUE_FILE_PATH = get_transfer_queue_path()


class TransferPanelHeader(QWidget):
    """
    Collapsible header for the transfer panel.
    Shows transfer count and allows collapsing the panel.
    """
    toggle_panel = Signal()  # Emitted when header is clicked to toggle collapse
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_collapsed = False
        self._active_count = 0
        self._init_ui()
        
    def _init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        
        # Collapse toggle button
        self.toggle_btn = QPushButton("▼")
        self.toggle_btn.setFixedWidth(24)
        self.toggle_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #aaaaaa;
                font-size: 12px;
                padding: 0;
            }
            QPushButton:hover {
                color: #ffffff;
            }
        """)
        self.toggle_btn.clicked.connect(self._on_toggle)
        layout.addWidget(self.toggle_btn)
        
        # Title label with count
        self.title_label = QLabel("Transfers")
        self.title_label.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {DARK_THEME['text_primary']};")
        layout.addWidget(self.title_label)
        
        # Status label
        self.status_label = QLabel("Idle")
        self.status_label.setStyleSheet(f"font-size: 11px; color: {DARK_THEME['text_secondary']};")
        layout.addWidget(self.status_label)
        
        # Spacing
        layout.addStretch()
        
        self.setLayout(layout)
        self.setStyleSheet("""
            TransferPanelHeader {
                background-color: #2a2a2a;
                border-bottom: 1px solid #444444;
            }
        """)
        self.setCursor(Qt.PointingHandCursor)
        
    def _on_toggle(self):
        self.toggle_panel.emit()
        
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle_panel.emit()
        super().mousePressEvent(event)
        
    def set_collapsed(self, collapsed: bool):
        self._is_collapsed = collapsed
        self.toggle_btn.setText("▶" if collapsed else "▼")
        
    def set_active_count(self, count: int):
        self._active_count = count
        self._update_title()
        
    def set_status_text(self, text: str):
        """Set the status text (e.g., '3 queued, 2 active')"""
        self.status_label.setText(text)
    
    def _update_title(self):
        if self._active_count > 0:
            self.title_label.setText(f"Transfers ({self._active_count} active)")
        else:
            self.title_label.setText("Transfers")


class TransferQueueWidget(QWidget):
    """
    Transfer queue widget for integration into main window as a bottom panel.
    
    This is a QWidget version of BackgroundThreadWindow that can be embedded
    as a collapsible panel in the main application window.
    
    Features:
    - Collapsible header with active transfer count
    - Collapsible console within the panel
    - Persistent transfer history (doesn't disappear on completion)
    - Scrollable list to view all transfers
    - Hostname indicator for each transfer
    - Full-width progress bars
    """
    print("DEBUG: TransferQueueWidget class defined", file=sys.stderr)
    
    # Signals for transfer events
    signal_transfer_started = Signal(int, str)  # (count, message)
    signal_transfer_completed = Signal(int, str)  # (count, message)
    signal_transfer_error = Signal(int, str)  # (count, message)
    signal_transfer_progress = Signal(int, int, float, float, int, int)  # (transfer_id, percent, speed_bps, eta_sec, bytes_done, bytes_total)
    signal_discovery_progress = Signal(int, int)  # (files_found, dirs_scanned)
    
    # Signal for adding transfer display from background threads (single tuple param)
    signal_add_transfer_display = Signal(object)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.queue_items = []
        self.active_transfers = 0
        self.transfers = []
        
        # New display-only transfer tracking (for DirectTransferWorker)
        self._transfer_displays = {}  # transfer_id -> {widget, progress_bar, status_label, speed_label, eta_label, source, dest}
        self._active_workers = {}  # transfer_id -> worker (for cancellation)
        
        self._observees = []
        self._observees_lock = QMutex()  # THREAD SAFETY: Lock for observee list
        self.total_queue_items = 0
        
        # Directory transfer discovery tracking
        self._discovery_active = False  # True when a traversal is discovering files
        self._discovery_files_found = 0  # Files found during discovery
        self._discovery_dirs_scanned = 0  # Directories scanned during discovery
        self._discovery_total_files = None  # Will be set when discovery completes
        
        # Per-group conflict resolution flags
        self._group_overwrite_all = set()  # group_ids with overwrite_all set
        self._group_skip_all = set()       # group_ids with skip_all set
        self._group_resume_all = set()     # group_ids with resume_all set
        self._group_cancel_all = set()     # group_ids with cancel_all set
        
        # Serialize conflict dialogs so only one shows at a time
        self._conflict_queue = []          # Pending (transfer_id, dest_path, dest_type)
        self._conflict_dialog_active = False
        
        # Transfer groups - track batch progress for directory transfers
        self._transfer_groups = {}  # group_id -> {"total_files": int, "completed_files": int, "total_bytes": int, "completed_bytes": int}
        self._current_group_id = None  # Group being actively transferred
        
        # Thread safety locks
        self._transfer_lock = QMutex()
        self._released_transfers = set()
        self._active_transfers_lock = QMutex()
        
        # Keep strong references to running workers to prevent GC of signal objects
        self._running_workers = set()
        
        # Debounce timer for refresh - prevents excessive refreshing during bulk transfers
        self._refresh_debounce_timer = None
        
        # Collapse state
        self._panel_collapsed = False
        self._console_collapsed = False
        
        # Concurrent queue system
        self._pending_display_transfers = []  # List of transfer_info dicts waiting to start
        self._max_concurrent_transfers = 8   # From preferences
        self._paused = False                  # Pause state
        self._paused_by_user = False         # User-initiated pause (vs system)
        self._session_waiters = {}            # transfer_id -> hostname waiting for session
        self._queue_save_timer = None         # Debounce timer for saves
        
        # Status colors for UI
        self._status_colors = {
            'waiting_session': '#FFA500',     # Orange
            'queued': '#888888',              # Gray
            'transferring': '#4CAF50',        # Green
            'complete': '#2196F3',            # Blue
            'failed': '#F44336',              # Red
            'paused': '#666666',              # Dark gray
        }
        
        # Connect signal for thread-safe transfer display addition
        self.signal_add_transfer_display.connect(
            self._add_transfer_display_slot,
            type=Qt.QueuedConnection
        )
        
        # Load persisted queue
        self._load_pending_queue()
        
        self.init_ui()

    def _insert_pending_by_priority(self, transfer_info):
        """Insert transfer into queue based on priority (higher = sooner)"""
        priority = transfer_info['priority']
        added_time = transfer_info['added_time']
        
        insert_pos = len(self._pending_display_transfers)
        for i, existing in enumerate(self._pending_display_transfers):
            if existing['priority'] < priority:
                insert_pos = i
                break
            elif existing['priority'] == priority and existing['added_time'] > added_time:
                insert_pos = i
                break
        
        self._pending_display_transfers.insert(insert_pos, transfer_info)
    
    def _check_and_start_queued(self):
        """Start transfers if under limit and not paused"""
        if self._paused:
            return
        
        active = len([t for t in self._transfer_displays.values() 
                      if t.get('status') == 'transferring'])
        
        started = 0
        while (self._pending_display_transfers and 
               active < self._max_concurrent_transfers):
            
            transfer_info = None
            for t in self._pending_display_transfers:
                if t['status'] in ('queued',):
                    transfer_info = t
                    break
            
            if not transfer_info:
                break
            
            self._pending_display_transfers.remove(transfer_info)
            self._start_queued_transfer(transfer_info)
            active += 1
            started += 1
        
        if started > 0:
            self._schedule_queue_save()
        
        self._update_queue_status_label()
    
    def _start_queued_transfer(self, transfer_info):
        """Create worker from stored transfer info and start it"""
        transfer_id = transfer_info['transfer_id']
        
        self._update_transfer_display_status(transfer_id, 'transferring')
        
        try:
            from sftp_transfer_handler import DirectTransferWorker
            worker = DirectTransferWorker(
                transfer_info['session_id'],
                transfer_info['source_path'],
                transfer_info['dest_path'],
                transfer_info['is_source_remote'],
                transfer_info['is_destination_remote'],
                transfer_info['command']
            )
            worker.transfer_id = transfer_id
            
            self.register_worker(transfer_id, worker)
            
            worker.signals.progress.connect(
                lambda bd, bt, sp, et, tid=transfer_id:
                    self.update_transfer_progress(tid, bd, bt, sp),
                type=Qt.QueuedConnection
            )
            worker.signals.finished.connect(
                lambda s, f, tid=transfer_id: self.mark_transfer_complete(tid),
                type=Qt.QueuedConnection
            )
            worker.signals.error.connect(
                lambda err, tid=transfer_id: self.mark_transfer_failed(tid, err),
                type=Qt.QueuedConnection
            )
            worker.signals.conflict.connect(
                lambda tid, dest, dtype: self._handle_conflict(tid, dest, dtype),
                type=Qt.QueuedConnection
            )
            
            QThreadPool.globalInstance().start(worker)
            
        except Exception as e:
            logger.error(f"Error starting queued transfer {transfer_id}: {e}")
            self.mark_transfer_failed(transfer_id, str(e))
    
    def _update_transfer_display_status(self, transfer_id, status):
        """Update the status display for a transfer"""
        if transfer_id not in self._transfer_displays:
            return
        
        display = self._transfer_displays[transfer_id]
        display['status'] = status
        display['is_active'] = (status == 'transferring')
        
        color = self._status_colors.get(status, DARK_THEME['text_primary'])
        display['status_label'].setText(status.replace('_', ' ').title())
        display['status_label'].setStyleSheet(f"font-size: 10px; color: {color}; font-weight: 500;")
        
        chunk_color = self._status_colors.get(status, '#666666')
        display['progress_bar'].setStyleSheet(f"""
            QProgressBar {{
                border: none;
                border-radius: 3px;
                background-color: {DARK_THEME['bg_secondary']};
                text-align: center;
                color: white;
                font-size: 10px;
            }}
            QProgressBar::chunk {{
                background-color: {chunk_color};
                border-radius: 3px;
            }}
        """)
        
        if status == 'transferring':
            display['progress_bar'].setFormat("Transferring...")
        elif status == 'queued':
            display['progress_bar'].setFormat("Queued")
        elif status == 'waiting_session':
            display['progress_bar'].setFormat("Waiting...")
        elif status == 'complete':
            display['progress_bar'].setFormat("100% - Complete")
        elif status == 'failed':
            display['progress_bar'].setFormat("Failed")
    
    def _update_queue_status_label(self):
        """Update the queue status label in header"""
        queued = len([t for t in self._pending_display_transfers 
                      if t['status'] == 'queued'])
        waiting = len([t for t in self._pending_display_transfers 
                       if t['status'] == 'waiting_session'])
        active = len([t for t in self._transfer_displays.values() 
                      if t.get('status') == 'transferring'])
        
        parts = []
        if queued > 0:
            parts.append(f"{queued} queued")
        if waiting > 0:
            parts.append(f"{waiting} waiting")
        if active > 0:
            parts.append(f"{active} active")
        
        text = ", ".join(parts) if parts else "Idle"
        if hasattr(self, 'header'):
            self.header.set_status_text(text)
    
    def _encrypt_for_queue(self, password):
        """Encrypt password for queue storage using existing cipher"""
        if not password:
            return ''
        if sftp_hostdataeditor.cipher_suite:
            try:
                return sftp_hostdataeditor.cipher_suite.encrypt(password.encode()).decode()
            except Exception:
                pass
        return password
    
    def _decrypt_for_queue(self, encrypted_password):
        """Decrypt password from queue storage"""
        if not encrypted_password:
            return ''
        if sftp_hostdataeditor.cipher_suite:
            try:
                return sftp_hostdataeditor.cipher_suite.decrypt(encrypted_password.encode()).decode()
            except Exception:
                pass
        return encrypted_password
    
    def _save_pending_queue(self):
        """Save pending transfers to disk for restoration"""
        if not self._pending_display_transfers:
            if os.path.exists(QUEUE_FILE_PATH):
                try:
                    os.remove(QUEUE_FILE_PATH)
                except Exception:
                    pass
            return
        
        data = []
        for t in self._pending_display_transfers:
            if t['status'] in ('queued', 'waiting_session'):
                data.append({
                    'transfer_id': t['transfer_id'],
                    'hostname': t['hostname'],
                    'port': t['port'],
                    'username': t['username'],
                    'password': self._encrypt_for_queue(t.get('password', '')),
                    'key': self._encrypt_for_queue(t.get('key', '')),
                    'source_path': t['source_path'],
                    'dest_path': t['dest_path'],
                    'is_source_remote': t['is_source_remote'],
                    'is_destination_remote': t['is_destination_remote'],
                    'command': t['command'],
                    'group_id': t.get('group_id'),
                    'priority': t['priority'],
                    'status': t['status'],
                    'added_time': t['added_time'],
                })
        
        try:
            json_str = json.dumps(data)
            with open(QUEUE_FILE_PATH, 'w') as f:
                f.write(json_str)
            secure_file_permissions(QUEUE_FILE_PATH)
        except Exception as e:
            logger.error(f"Error saving queue: {e}")
    
    def _schedule_queue_save(self):
        """Debounced save - wait 1 second after last change"""
        if self._queue_save_timer:
            self._queue_save_timer.stop()
        self._queue_save_timer = QTimer()
        self._queue_save_timer.setSingleShot(True)
        self._queue_save_timer.timeout.connect(self._save_pending_queue)
        self._queue_save_timer.start(1000)
    
    def _load_pending_queue(self):
        """Load pending transfers on startup"""
        if not os.path.exists(QUEUE_FILE_PATH):
            return 0
        
        try:
            with open(QUEUE_FILE_PATH, 'r') as f:
                data = json.loads(f.read())
            
            restored = 0
            for item in data:
                item['password'] = self._decrypt_for_queue(item.get('password', ''))
                item['key'] = self._decrypt_for_queue(item.get('key', ''))
                item['status'] = 'waiting_session'  # Start in waiting state
                item['added_time'] = item.get('added_time', time.time())
                item['session_id'] = None
                
                self._pending_display_transfers.append(item)
                
                # Track waiters
                self._session_waiters[item['transfer_id']] = item['hostname']
                restored += 1
            
            if restored > 0:
                self.text_console.append(f"Restored {restored} transfers to queue")
            
            return restored
        except Exception as e:
            logger.error(f"Error loading queue: {e}")
            return 0
    
    def register_active_session(self, hostname, session_id):
        """Called when user connects to a host - check for waiting transfers"""
        if hostname in self._session_waiters.values():
            waiting = [t for t in self._pending_display_transfers 
                       if t.get('hostname') == hostname and t.get('status') == 'waiting_session']
            
            for t in waiting:
                t['session_id'] = session_id
                t['status'] = 'queued'
                del self._session_waiters[t['transfer_id']]
            
            # Try to start
            self._check_and_start_queued()

    def init_ui(self):
        """Initialize the UI layout"""
        print("DEBUG: init_ui() called", file=sys.stderr)
        
        # Main layout
        self.main_layout = QVBoxLayout()
        self.main_layout.setSpacing(0)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Collapsible header
        self.header = TransferPanelHeader(self)
        self.header.toggle_panel.connect(self.toggle_panel)
        self.main_layout.addWidget(self.header)
        
        # Content widget (transfer list + controls + console)
        self.content_widget = QWidget()
        content_layout = QVBoxLayout()
        content_layout.setSpacing(4)
        content_layout.setContentsMargins(8, 8, 8, 8)
        
        # Overall progress section (at top)
        self.overall_progress_widget = QWidget()
        overall_layout = QVBoxLayout()
        overall_layout.setContentsMargins(0, 0, 0, 4)
        overall_layout.setSpacing(2)
        
        # Overall progress label
        self.overall_progress_label = QLabel("Overall: No transfers")
        self.overall_progress_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_THEME['text_primary']};
                font-size: 11px;
                font-weight: 600;
            }}
        """)
        overall_layout.addWidget(self.overall_progress_label)
        
        # Overall progress bar
        self.overall_progress_bar = QProgressBar()
        self.overall_progress_bar.setRange(0, 100)
        self.overall_progress_bar.setValue(0)
        self.overall_progress_bar.setFixedHeight(12)
        self.overall_progress_bar.setTextVisible(True)
        self.overall_progress_bar.setFormat("%p%")
        self.overall_progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: #2a2a2a;
                border: 1px solid #444444;
                border-radius: 4px;
                text-align: center;
                font-size: 10px;
                color: #ffffff;
            }}
            QProgressBar::chunk {{
                background-color: {DARK_THEME['accent_green']};
                border-radius: 3px;
            }}
        """)
        overall_layout.addWidget(self.overall_progress_bar)
        
        self.overall_progress_widget.setLayout(overall_layout)
        content_layout.addWidget(self.overall_progress_widget)
        
        # Transfer list widget (container for transfer items)
        self.transfer_list = QListWidget()
        self.transfer_list.setStyleSheet(LIST_WIDGET_STYLE_DARK)
        self.transfer_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.transfer_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.transfer_list.setMinimumHeight(100)
        self.transfer_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.transfer_list.customContextMenuRequested.connect(self._show_transfer_context_menu)
        
        # Debug label to show item count
        self._debug_count_label = QLabel("List: 0 | Dict: 0")
        self._debug_count_label.setStyleSheet("color: #666; font-size: 10px;")
        content_layout.addWidget(self._debug_count_label)
        
        # Set the list as the scroll area widget
        content_layout.addWidget(self.transfer_list, stretch=1)

        # Add control buttons and preferences
        self.control_layout = QHBoxLayout()
        self.control_layout.setSpacing(8)
        
        # Transfer control buttons
        self.pause_button = QPushButton("⏸ Pause")
        self.pause_button.setStyleSheet(BUTTON_STYLE_DARK)
        self.pause_button.setToolTip("Pause all transfers")
        self.pause_button.clicked.connect(self.pause_all_transfers)
        self.pause_button.setCheckable(True)
        
        self.stop_button = QPushButton("⏹ Stop")
        self.stop_button.setStyleSheet(BUTTON_STYLE_DARK)
        self.stop_button.setToolTip("Cancel all transfers")
        self.stop_button.clicked.connect(self.stop_all_transfers)
        
        self.clear_button = QPushButton("Clear Completed")
        self.clear_button.setStyleSheet(BUTTON_STYLE_DARK)
        self.clear_button.clicked.connect(self.clear_completed)
        
        # Concurrent transfers spinner
        concurrent_label = QLabel("Concurrent:")
        concurrent_label.setStyleSheet(f"color: {DARK_THEME['text_secondary']}; font-size: 11px;")
        self.concurrent_spinner = QSpinBox()
        self.concurrent_spinner.setRange(1, 20)
        self.concurrent_spinner.setValue(self._max_concurrent_transfers)
        self.concurrent_spinner.setToolTip("Maximum concurrent transfers")
        self.concurrent_spinner.setFixedWidth(50)
        self.concurrent_spinner.valueChanged.connect(self._on_concurrent_changed)
        
        # Preferences checkboxes
        prefs = get_preferences()
        
        self.clear_on_complete_checkbox = QCheckBox("Auto-clear completed")
        self.clear_on_complete_checkbox.setToolTip("Automatically clear completed transfers")
        self.clear_on_complete_checkbox.setStyleSheet(f"""
            QCheckBox {{
                color: {DARK_THEME['text_secondary']};
                font-size: 11px;
            }}
        """)
        self.clear_on_complete_checkbox.setChecked(prefs.get_bool("clear_completed_on_complete", False))
        self.clear_on_complete_checkbox.stateChanged.connect(self._on_clear_on_complete_changed)
        
        self.overwrite_checkbox = QCheckBox("Overwrite")
        self.overwrite_checkbox.setToolTip("When enabled, existing files will be overwritten during transfers")
        self.overwrite_checkbox.setChecked(prefs.get_bool("overwrite_on_transfer", False))
        self.overwrite_checkbox.stateChanged.connect(self._on_overwrite_changed)
        
        self.follow_symlinks_checkbox = QCheckBox("Follow symlinks")
        self.follow_symlinks_checkbox.setToolTip(
            "When checked, symbolic links in directory transfers will be followed (resolved).\n"
            "When unchecked (default), symlinks are skipped during transfers.\n"
            "This sets a persistent preference — directory transfers will use this setting automatically."
        )
        self.follow_symlinks_checkbox.setChecked(prefs.get_bool("follow_symlinks", False))
        self.follow_symlinks_checkbox.stateChanged.connect(self._on_follow_symlinks_changed)
        self.console_toggle = QPushButton("▼ Console")
        self.console_toggle.setCheckable(True)
        self.console_toggle.setChecked(False)
        self.console_toggle.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px solid #555555;
                border-radius: 3px;
                padding: 2px 8px;
                color: #aaaaaa;
                font-size: 11px;
            }
            QPushButton:hover {
                border-color: #777777;
                color: #ffffff;
            }
            QPushButton:checked {
                border-color: #5555ff;
                color: #5555ff;
            }
        """)
        self.console_toggle.clicked.connect(self.toggle_console)
        
        self.control_layout.addWidget(self.pause_button)
        self.control_layout.addWidget(self.stop_button)
        self.control_layout.addWidget(concurrent_label)
        self.control_layout.addWidget(self.concurrent_spinner)
        self.control_layout.addWidget(self.clear_on_complete_checkbox)
        self.control_layout.addWidget(self.overwrite_checkbox)
        self.control_layout.addWidget(self.follow_symlinks_checkbox)
        self.control_layout.addStretch(1)
        self.control_layout.addWidget(self.console_toggle)
        self.control_layout.addWidget(self.clear_button)
        
        content_layout.addLayout(self.control_layout)

        # Console (collapsible)
        self.console_widget = QWidget()
        console_layout = QVBoxLayout()
        console_layout.setContentsMargins(0, 0, 0, 0)
        console_layout.setSpacing(0)
        
        self.text_console = QTextEdit()
        self.text_console.setReadOnly(True)
        self.text_console.setMaximumHeight(80)
        self.text_console.setStyleSheet(TEXT_EDIT_STYLE_DARK)
        self.text_console.setMinimumWidth(300)
        self.text_console.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        console_layout.addWidget(self.text_console)
        self.console_widget.setLayout(console_layout)
        
        # Set initial console visibility based on preferences
        console_collapsed = prefs.get_bool("transfer_console_collapsed", False)
        self._console_collapsed = console_collapsed
        self.console_widget.setVisible(not console_collapsed)
        self.console_toggle.setChecked(not console_collapsed)
        self.console_toggle.setText("▼ Console" if not console_collapsed else "▶ Console")
        
        content_layout.addWidget(self.console_widget)
        
        self.content_widget.setLayout(content_layout)
        self.main_layout.addWidget(self.content_widget)

        # Set the main layout
        self.setLayout(self.main_layout)
        
        print(f"DEBUG: init_ui completed, main_layout count: {self.main_layout.count()}", file=sys.stderr)
        
        # Set initial panel collapse state from preferences
        panel_collapsed = prefs.get_bool("transfer_panel_collapsed", False)
        self._panel_collapsed = panel_collapsed
        self.content_widget.setVisible(not panel_collapsed)
        self.header.set_collapsed(panel_collapsed)

        # Initialize thread pool
        self.thread_pool = QThreadPool.globalInstance()
        # Ensure thread pool can handle the maximum number of concurrent transfers
        # We set it slightly higher than MAX_TRANSFERS to allow for overhead
        if self.thread_pool.maxThreadCount() < 20:
            self.thread_pool.setMaxThreadCount(20)

        # Setup timers
        self._setup_timers()
        
    def _add_transfer_display_slot(self, args_tuple):
        """Slot for thread-safe transfer display addition (called via signal from background threads)"""
        transfer_id, source_path, dest_path, is_source_remote, is_destination_remote, hostname, port, username, password, command, key, session_id, group_id = args_tuple
        print(f"DEBUG: _add_transfer_display_slot called for {transfer_id}", file=sys.stderr)
        self.add_transfer_display(
            transfer_id=transfer_id,
            source_path=source_path,
            dest_path=dest_path,
            is_source_remote=is_source_remote,
            is_destination_remote=is_destination_remote,
            hostname=hostname,
            port=port,
            username=username,
            password=password,
            command=command,
            key=key,
            session_id=session_id,
            group_id=group_id
        )

    def toggle_panel(self):
        """Toggle the entire panel visibility (collapse/expand)"""
        self._panel_collapsed = not self._panel_collapsed
        self.content_widget.setVisible(not self._panel_collapsed)
        self.header.set_collapsed(self._panel_collapsed)
        
        # Save preference
        prefs = get_preferences()
        prefs.set_bool("transfer_panel_collapsed", self._panel_collapsed)
        
    def _on_concurrent_changed(self, value):
        """Handle concurrent transfers spinner change"""
        self._max_concurrent_transfers = value
        prefs = get_preferences()
        prefs.set_int("max_concurrent_transfers", value)
        # Try to start more transfers if under limit
        self._check_and_start_queued()
        
    def toggle_console(self):
        """Toggle the console visibility within the panel"""
        self._console_collapsed = not self._console_collapsed
        self.console_widget.setVisible(not self._console_collapsed)
        
        if self._console_collapsed:
            self.console_toggle.setText("▶ Console")
        else:
            self.console_toggle.setText("▼ Console")
            self.console_toggle.setChecked(True)
        
        # Save preference
        prefs = get_preferences()
        prefs.set_bool("transfer_console_collapsed", self._console_collapsed)
        
    def is_collapsed(self):
        """Return whether the panel is collapsed"""
        return self._panel_collapsed
        
    def set_collapsed(self, collapsed: bool):
        """Set the panel collapse state"""
        if self._panel_collapsed != collapsed:
            self._panel_collapsed = collapsed
            self.content_widget.setVisible(not collapsed)
            self.header.set_collapsed(collapsed)
        
    def set_panel_height(self, height: int):
        """Set the panel height (used by splitter)"""
        # This is handled by the splitter in the parent widget
        pass
        
    def update_active_count(self, count: int):
        """Update the active transfer count in the header"""
        self.header.set_active_count(count)

    def _on_clear_on_complete_changed(self, state):
        """Handle clear on complete checkbox change"""
        prefs = get_preferences()
        prefs.set_bool("clear_completed_on_complete", bool(state))

    def _on_overwrite_changed(self, state):
        """Handle overwrite checkbox change"""
        prefs = get_preferences()
        prefs.set_bool("overwrite_on_transfer", bool(state))

    def _on_follow_symlinks_changed(self, state):
        """Handle follow symlinks checkbox change"""
        prefs = get_preferences()
        prefs.set_bool("follow_symlinks", bool(state))

    def _setup_timers(self):
        """Setup timers for queue processing"""
        # Timer to periodically check the queue
        self.check_queue_timer = QTimer(self)
        self.check_queue_timer.timeout.connect(self.check_and_start_transfers)
        self.check_queue_timer.start(100)  # Check every 100 ms
        self._timer_tick_count = 0

    def add_queue_item(self, item, transfer_id):
        """Add item to queue with transfer_id as unique identifier"""
        queue_item = {'path': item, 'transfer_id': transfer_id}
        self.queue_items.append(queue_item)
        self.total_queue_items = len(self.queue_items)
        self.update_overall_progress()

    def remove_queue_item(self, transfer_id):
        """Remove item by transfer_id"""
        self.queue_items = [item for item in self.queue_items 
                           if item['transfer_id'] != transfer_id]
        self.total_queue_items = len(self.queue_items)
        self.update_overall_progress()

    def on_discovery_progress(self, files_found, dirs_scanned):
        """Handle discovery progress from TraversalWorker"""
        self._discovery_files_found = files_found
        self._discovery_dirs_scanned = dirs_scanned
        self._discovery_active = True
        self.update_overall_progress()

    def on_discovery_finished(self):
        """Handle discovery completion - now we know total files"""
        self._discovery_active = False
        self._discovery_total_files = self._discovery_files_found
        self._discovery_files_found = 0
        self._discovery_dirs_scanned = 0
        self.update_overall_progress()

    def start_transfer_group(self, group_id, total_files):
        """Start tracking a new transfer group (batch of files from directory transfer)"""
        self._current_group_id = group_id
        self._transfer_groups[group_id] = {
            "total_files": total_files,
            "completed_files": 0,
            "total_bytes": 0,
            "completed_bytes": 0
        }
        self.update_overall_progress()

    def add_to_group(self, transfer_id, group_id, file_size=0):
        """Add a transfer to a group"""
        if group_id in self._transfer_groups:
            self._transfer_groups[group_id]["total_bytes"] += file_size
        # Store group_id on the transfer for tracking
        with QMutexLocker(self._transfer_lock):
            for t in self.transfers:
                if t.transfer_id == transfer_id:
                    t.group_id = group_id
                    return
        # Transfer not created yet - queue it for assignment when start_transfer runs
        if not hasattr(self, '_pending_group_assignments'):
            self._pending_group_assignments = {}
        self._pending_group_assignments[transfer_id] = group_id

    def set_group_conflict_action(self, group_id, action):
        if action == "overwrite_all":
            self._group_overwrite_all.add(group_id)
        elif action == "skip_all":
            self._group_skip_all.add(group_id)
        elif action == "resume_all":
            self._group_resume_all.add(group_id)
        elif action == "cancel":
            self._group_cancel_all.add(group_id)

    def update_group_progress(self, transfer_id, bytes_done):
        """Update progress for a transfer that's part of a group"""
        with QMutexLocker(self._transfer_lock):
            for t in self.transfers:
                if t.transfer_id == transfer_id and hasattr(t, 'group_id') and t.group_id:
                    group_id = t.group_id
                    if group_id in self._transfer_groups:
                        old_bytes = getattr(t, '_last_bytes_done', 0)
                        delta = bytes_done - old_bytes
                        self._transfer_groups[group_id]["completed_bytes"] += delta
                        t._last_bytes_done = bytes_done
                    break

    def add_observee(self, observee):
        """Add an observer to be notified when transfers complete. Thread-safe."""
        with QMutexLocker(self._observees_lock):
            if observee not in self._observees:
                self._observees.append(observee)

    def remove_observee(self, observee):
        """Remove an observer. Thread-safe."""
        with QMutexLocker(self._observees_lock):
            if observee in self._observees:
                self._observees.remove(observee)

    def notify_observees(self):
        """Notify all observers that transfers completed. Thread-safe.
        Uses debouncing to prevent excessive refreshing during bulk transfers."""
        # Cancel any pending refresh
        if self._refresh_debounce_timer is not None:
            self._refresh_debounce_timer.stop()
        
        # Schedule a refresh after a short delay to batch multiple rapid updates
        from PySide6.QtCore import QTimer
        self._refresh_debounce_timer = QTimer()
        self._refresh_debounce_timer.setSingleShot(True)
        self._refresh_debounce_timer.timeout.connect(self._do_notify_observees)
        self._refresh_debounce_timer.start(500)  # 500ms debounce
    
    def _do_notify_observees(self):
        """Actually notify observers - called after debounce delay"""
        self._refresh_debounce_timer = None
        
        # Copy list under lock to avoid holding lock during callbacks
        with QMutexLocker(self._observees_lock):
            observees_copy = list(self._observees)
        
        for observee in observees_copy:
            try:
                # Use Qt QueuedConnection to ensure refresh happens on main thread
                QTimer.singleShot(0, lambda o=observee: self._do_refresh(o))
            except (AttributeError, RuntimeError):
                pass

    def _do_refresh(self, observee):
        """Actually perform the refresh - called on main thread"""
        try:
            if hasattr(observee, 'model') and hasattr(observee.model, 'get_files'):
                import inspect
                sig = inspect.signature(observee.model.get_files)
                if 'force_refresh' in sig.parameters:
                    observee.model.get_files(force_refresh=True)
                else:
                    observee.model.get_files()
            else:
                observee.get_files()
            
            # Force the table view to update
            if hasattr(observee, 'table'):
                observee.table.viewport().update()
                observee.table.repaint()
                
        except AttributeError as ae:
            pass
        except (AttributeError, RuntimeError) as e:
            pass
    def get_active_transfer_count(self):
        """Get total number of active transfers (both legacy and display-only)"""
        count = 0
        
        # Count legacy transfers
        with QMutexLocker(self._transfer_lock):
            count += len([t for t in self.transfers if t.active])
        
        # Count display-only transfers
        for tid, display in self._transfer_displays.items():
            if display.get('is_active', False):
                count += 1
                
        return count

    def update_overall_progress(self):
        """Update the overall progress bar based on all active transfers"""
        try:
            # Handle discovery phase - show scanning status instead of percentage
            if self._discovery_active:
                self.overall_progress_widget.setVisible(True)
                self.overall_progress_bar.setRange(0, 0)  # Indeterminate
                self.overall_progress_bar.setValue(0)
                
                # Format discovery status
                files_str = f"{self._discovery_files_found:,} files"
                dirs_str = f"{self._discovery_dirs_scanned:,} dirs"
                label_text = f"Scanning: {files_str} found in {dirs_str}..."
                self.overall_progress_label.setText(label_text)
                self.header.set_active_count(0)
                return
            
            # Transfer phase - show actual progress
            active_transfers = [t for t in self.transfers if t.active]
            
            if not active_transfers:
                self.overall_progress_bar.setRange(0, 100)
                self.overall_progress_bar.setValue(0)
                self.overall_progress_label.setText("No active transfers")
                self.overall_progress_widget.setVisible(False)
                self.header.set_active_count(0)
                self._discovery_total_files = None  # Reset discovery state
                return
            
            # Show overall progress widget when there are active transfers
            self.overall_progress_widget.setVisible(True)
            self.overall_progress_bar.setRange(0, 100)
            self.header.set_active_count(len(active_transfers))
            
            # Check if we have an active group to track
            group = None
            if self._current_group_id and self._current_group_id in self._transfer_groups:
                group = self._transfer_groups[self._current_group_id]
            
            # If we have a group with known total files, show file count progress
            if group and group["total_files"] > 0:
                # Calculate file-based progress for the group
                completed = group["completed_files"]
                total = group["total_files"]
                overall_percent = int((completed / total) * 100)
                self.overall_progress_bar.setValue(overall_percent)
                
                # Sum speed from active transfers
                total_speed = 0.0
                for transfer in active_transfers:
                    total_speed += getattr(transfer, 'speed_bps', 0.0) or 0.0
                
                # Show file count progress
                label_text = f"Transferring: {completed}/{total} files ({overall_percent}%)"
                if total_speed > 0:
                    if total_speed >= 1024 * 1024:
                        speed_str = f"{total_speed / (1024 * 1024):.1f} MB/s"
                    elif total_speed >= 1024:
                        speed_str = f"{total_speed / 1024:.1f} KB/s"
                    else:
                        speed_str = f"{total_speed:.0f} B/s"
                    label_text += f" • {speed_str}"
                
                self.overall_progress_label.setText(label_text)
                return
            
            # No group - show traditional bytes-based progress
            
            # Calculate total progress
            total_bytes_done = 0
            total_bytes = 0
            total_speed = 0.0
            
            for transfer in active_transfers:
                # Get bytes from transfer object
                done = getattr(transfer, 'bytes_done', 0) or 0
                total = getattr(transfer, 'bytes_total', 0) or 0
                speed = getattr(transfer, 'speed_bps', 0.0) or 0.0
                
                total_bytes_done += done
                total_bytes += total
                total_speed += speed
            
            # Calculate overall percentage
            if total_bytes > 0:
                overall_percent = int((total_bytes_done / total_bytes) * 100)
            else:
                overall_percent = 0
            
            # Update progress bar
            self.overall_progress_bar.setValue(overall_percent)
            
            # Format speed
            if total_speed > 0:
                if total_speed >= 1024 * 1024:
                    speed_str = f"{total_speed / (1024 * 1024):.1f} MB/s"
                elif total_speed >= 1024:
                    speed_str = f"{total_speed / 1024:.1f} KB/s"
                else:
                    speed_str = f"{total_speed:.0f} B/s"
            else:
                speed_str = ""
            
            # Format bytes
            def humanize_bytes(b):
                if b >= 1024**3:
                    return f"{b / 1024**3:.1f} GB"
                elif b >= 1024**2:
                    return f"{b / 1024**2:.1f} MB"
                elif b >= 1024:
                    return f"{b / 1024:.1f} KB"
                else:
                    return f"{b} B"
            
            if total_bytes > 0:
                bytes_str = f"{humanize_bytes(total_bytes_done)}/{humanize_bytes(total_bytes)}"
            else:
                bytes_str = ""
            
            # Update label
            count_str = f"{len(active_transfers)} active"
            if speed_str:
                label_text = f"Overall: {count_str} • {bytes_str} • {speed_str}"
            elif bytes_str:
                label_text = f"Overall: {count_str} • {bytes_str}"
            else:
                label_text = f"Overall: {count_str}"
            
            self.overall_progress_label.setText(label_text)
            
        except (OSError, IOError, RuntimeError):
            pass

    def check_and_start_transfers(self):
        """Check for new transfers in queue and start them"""
        try:
            self._timer_tick_count = getattr(self, '_timer_tick_count', 0) + 1
            
            # Fix active transfers counter
            with QMutexLocker(self._transfer_lock):
                actual_active = len([t for t in self.transfers if t.active])
                if self.active_transfers != actual_active:
                    self.active_transfers = actual_active
            
            # Check if queue has items
            queue_size = sftp_queue.qsize()
            if queue_size == 0:
                return
            # Get job from queue with timeout (thread-safe, avoids race condition)
            try:
                job = sftp_queue.get_nowait()
            except Exception as e:
                return  # Queue is empty or error
            
            if not job:
                return
            
            # Debug: log job details
            # Validate job
            if not hasattr(job, "job_id"):
                self.text_console.append(f"Invalid job structure: {job}")
                return

            # Handle end command
            if hasattr(job, "command") and job.command == "end":
                self.text_console.append("Received end command")
                with QMutexLocker(self._active_transfers_lock):
                    self.active_transfers = 0
                return

            # Validate required attributes
            required_attrs = ["job_id", "source_path", "destination_path", 
                            "is_source_remote", "is_destination_remote", 
                            "hostname", "port", "username", "password", "command"]
            
            missing_attrs = [attr for attr in required_attrs if not hasattr(job, attr)]
            if missing_attrs:
                self.text_console.append(f"Error: Job missing attributes: {missing_attrs}")
                return

            # Start the transfer
            self.start_transfer(
                job.job_id, job.source_path, job.destination_path,
                job.is_source_remote, job.is_destination_remote,
                job.hostname, job.port, job.username, job.password, 
                job.command, getattr(job, 'key', None)
            )

        except (OSError, IOError, RuntimeError) as e:
            self.text_console.append(f"Error starting transfer: {e}")

    def start_transfer(self, transfer_id, job_source, job_destination, 
                       is_source_remote, is_destination_remote, hostname, 
                       port, username, password, command, key):
        """Start a new transfer"""
        import logging
        logger = logging.getLogger('sftp.queue')
        
        logger.debug(f"start_transfer called: {transfer_id}, {job_source}")
        
        try:
            if not transfer_id:
                logger.debug("start_transfer: empty transfer_id, returning")
                return
            
            # Check if transfer already exists
            if not hasattr(self, 'transfers'):
                logger.debug("start_transfer: self.transfers doesn't exist!")
                self.transfers = []
            
            existing = next((t for t in self.transfers if t.transfer_id == transfer_id), None)
            if existing:
                return
            
            # Create list item
            item = QListWidgetItem()
            item.setData(Qt.UserRole, transfer_id)
            
            # Create widget for the item - COMPACT DESIGN
            widget = QWidget()
            widget.setFixedHeight(60)  # Slightly taller for details
            layout = QVBoxLayout()
            layout.setContentsMargins(8, 4, 8, 4)
            layout.setSpacing(2)
            
            # Top row: Filename and action buttons
            top_row = QHBoxLayout()
            top_row.setSpacing(8)
            
            # Direction arrow + filename
            file_name = os.path.basename(job_source)
            direction = "⬆️" if is_source_remote and not is_destination_remote else "⬇️" if not is_source_remote and is_destination_remote else "🔄"
            file_label = QLabel(f"{direction} {file_name}")
            file_label.setStyleSheet(f"font-weight: 600; font-size: 12px; color: {DARK_THEME['text_primary']};")
            file_label.setSizePolicy(Qt.SizePolicy_Expanding, Qt.SizePolicy_Fixed)
            file_label.setToolTip(f"Source: {job_source}\nDestination: {job_destination}")  # Full paths on hover
            top_row.addWidget(file_label, stretch=3)
            
            # Status label
            status_label = QLabel("Queued")
            status_label.setStyleSheet(f"font-size: 10px; color: {DARK_THEME['text_secondary']}; font-weight: 500;")
            status_label.setAlignment(Qt.AlignRight)
            top_row.addWidget(status_label)
            
            # Cancel button
            cancel_button = QPushButton("✕")
            cancel_button.setFixedWidth(24)
            cancel_button.setFixedHeight(24)
            cancel_button.setToolTip("Cancel")
            cancel_button.setStyleSheet(f"""
                QPushButton {{
                    border: none;
                    border-radius: 4px;
                    background-color: transparent;
                    color: {DARK_THEME['text_secondary']};
                    font-size: 12px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {DARK_THEME['error']};
                    color: white;
                }}
            """)
            cancel_button.clicked.connect(lambda checked, tid=transfer_id: self.cancel_transfer(tid))
            top_row.addWidget(cancel_button)
            
            layout.addLayout(top_row)
            
            # Middle row: Source -> Destination paths
            path_row = QHBoxLayout()
            path_row.setSpacing(4)
            
            source_display = job_source if len(job_source) < 40 else "..." + job_source[-37:]
            dest_display = job_destination if len(job_destination) < 40 else "..." + job_destination[-37:]
            
            path_label = QLabel(f"<span style='color: {DARK_THEME['text_secondary']};'>{source_display}</span> → <span style='color: {DARK_THEME['text_secondary']};'>{dest_display}</span>")
            path_label.setStyleSheet(f"font-size: 9px;")
            path_label.setSizePolicy(Qt.SizePolicy_Expanding, Qt.SizePolicy_Fixed)
            path_row.addWidget(path_label, stretch=1)
            
            layout.addLayout(path_row)
            
            # Bottom row: Slim progress bar + speed/eta
            bottom_row = QHBoxLayout()
            bottom_row.setSpacing(8)
            
            # Progress bar - much thinner
            progress_bar = QProgressBar()
            progress_bar.setRange(0, 100)
            progress_bar.setValue(0)
            progress_bar.setFixedHeight(6)  # Much thinner
            progress_bar.setSizePolicy(Qt.SizePolicy_Expanding, Qt.SizePolicy_Fixed)
            progress_bar.setTextVisible(False)  # Hide text, just show bar
            progress_bar.setStyleSheet(f"""
                QProgressBar {{
                    border: none;
                    border-radius: 3px;
                    background-color: {DARK_THEME['border']};
                }}
                QProgressBar::chunk {{
                    background-color: {DARK_THEME['accent_green']};
                    border-radius: 3px;
                }}
            """)
            bottom_row.addWidget(progress_bar, stretch=4)  # Takes most space
            
            # Speed/ETA labels
            speed_label = QLabel("-")
            speed_label.setStyleSheet(f"font-size: 10px; color: {DARK_THEME['text_primary']}; font-weight: 500;")
            speed_label.setAlignment(Qt.AlignRight)
            speed_label.setFixedWidth(70)
            bottom_row.addWidget(speed_label)
            
            eta_label = QLabel("-")
            eta_label.setStyleSheet(f"font-size: 9px; color: {DARK_THEME['text_secondary']};")
            eta_label.setAlignment(Qt.AlignRight)
            eta_label.setFixedWidth(50)
            bottom_row.addWidget(eta_label)
            
            layout.addLayout(bottom_row)
            
            widget.setLayout(layout)
            
            # Set size hint for consistent row height
            item.setSizeHint(widget.sizeHint())
            
            # Add to list (top)
            self.transfer_list.addItem(item)
            self.transfer_list.setItemWidget(item, widget)
            
            # Create download worker
            download_worker = DownloadWorker(
                transfer_id, job_source, job_destination, 
                is_source_remote, is_destination_remote,
                hostname, port, username, password, command, key
            )
            
            pause_button = None  # Placeholder for pause functionality
            
            # Store transfer details
            new_transfer = Transfer(
                transfer_id=transfer_id,
                download_worker=download_worker,
                active=True,
                progress_bar=progress_bar,
                cancel_button=cancel_button,
                speed_label=speed_label,
                eta_label=eta_label,
                status_label=status_label,
                pause_button=None,
                list_item=item,
                hostname=hostname
            )

            # Connect signals
            if hasattr(download_worker, 'signals'):
                download_worker.signals.progress.connect(
                    lambda tid, val, speed, eta, bdone, btotal: self.update_progress(tid, val, speed, eta, bdone, btotal),
                    Qt.QueuedConnection
                )
                download_worker.signals.finished.connect(
                    lambda tid: self.transfer_finished(tid),
                    Qt.QueuedConnection
                )
                download_worker.signals.message.connect(
                    lambda tid, msg: self._handle_worker_message(tid, msg),
                    Qt.QueuedConnection
                )
                download_worker.signals.conflict.connect(
                    lambda tid, dest, dtype: self._handle_conflict(tid, dest, dtype),
                    Qt.QueuedConnection
                )
            
            # Add to transfers list
            with QMutexLocker(self._transfer_lock):
                self.transfers.append(new_transfer)
            
            # Apply pending group assignment if any
            if hasattr(self, '_pending_group_assignments') and transfer_id in self._pending_group_assignments:
                new_transfer.group_id = self._pending_group_assignments.pop(transfer_id)
            
            # Start the worker
            self._running_workers.add(new_transfer.download_worker)
            self.thread_pool.start(new_transfer.download_worker)
            
            # Emit transfer started signal
            self.signal_transfer_started.emit(1, f"Transfer started: {job_source}")
            
            with QMutexLocker(self._active_transfers_lock):
                self.active_transfers += 1
            self.update_overall_progress()
            
        except (OSError, IOError, RuntimeError) as e:
            self.text_console.append(f"Failed to start transfer: {e}")
    
    # ===== Display-only methods for DirectTransferWorker =====
    
    def add_transfer_display(self, transfer_id, source_path, dest_path, 
                             is_source_remote, is_destination_remote, hostname,
                             port, username, password, command, key,
                             session_id=None, group_id=None, priority=0):
        """
        Add a transfer to the queue (not started immediately if at limit).
        """
        import logging
        logger = logging.getLogger('sftp')
        
        try:
            print(f"DEBUG: add_transfer_display called: {transfer_id}", file=sys.stderr)
            logger.debug(f"add_transfer_display called: {transfer_id} {source_path} -> {dest_path}")
            
            if not transfer_id:
                logger.debug("add_transfer_display: no transfer_id, returning")
                return
            
            # Check if already exists
            if transfer_id in self._transfer_displays:
                logger.debug(f"add_transfer_display: {transfer_id} already exists")
                return
            
            # Determine status based on session availability
            if session_id:
                status = 'queued'
            else:
                status = 'waiting_session'
                self._session_waiters[transfer_id] = hostname
            
            # Create transfer info for queue
            transfer_info = {
                'transfer_id': transfer_id,
                'hostname': hostname,
                'port': port,
                'username': username,
                'password': password,
                'key': key,
                'source_path': source_path,
                'dest_path': dest_path,
                'is_source_remote': is_source_remote,
                'is_destination_remote': is_destination_remote,
                'command': command,
                'group_id': group_id or self._current_group_id,
                'priority': priority,
                'status': status,
                'session_id': session_id,
                'added_time': time.time(),
            }
            
            # Insert by priority
            self._insert_pending_by_priority(transfer_info)
            
            # Create UI with appropriate status
            self._create_transfer_display(transfer_info, status)
            
            # Save to disk
            self._schedule_queue_save()
            
            # Try to start
            if not self._paused:
                self._check_and_start_queued()
            
        except Exception as e:
            import traceback
            print(f"DEBUG: Error in add_transfer_display: {e}", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
            self.text_console.append(f"Error adding transfer display: {e}")
    
    def _create_transfer_display(self, transfer_info, status):
        """Create transfer display UI"""
        transfer_id = transfer_info['transfer_id']
        source_path = transfer_info['source_path']
        dest_path = transfer_info['dest_path']
        hostname = transfer_info['hostname']
        
        is_upload = transfer_info['is_source_remote'] and not transfer_info['is_destination_remote']
        
        # Create list item
        item = QListWidgetItem()
        item.setData(Qt.UserRole, transfer_id)
        
        # Create widget
        widget = QWidget()
        widget.setFixedHeight(60)
        layout = QVBoxLayout()
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(2)
        
        # Top row: filename and status
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        
        file_name = os.path.basename(source_path)
        direction = "⬆️" if is_upload else "⬇️"
        file_label = QLabel(f"{direction} {file_name}")
        file_label.setStyleSheet(f"font-weight: 600; font-size: 12px; color: {DARK_THEME['text_primary']};")
        file_label.setSizePolicy(Qt.SizePolicy_Expanding, Qt.SizePolicy_Fixed)
        file_label.setToolTip(f"Source: {source_path}\nDestination: {dest_path}")
        top_row.addWidget(file_label, stretch=3)
        
        # Status label based on status
        status_text = status.replace('_', ' ').title()
        status_color = self._status_colors.get(status, DARK_THEME['text_secondary'])
        status_label = QLabel(status_text)
        status_label.setStyleSheet(f"font-size: 10px; color: {status_color}; font-weight: 500;")
        status_label.setAlignment(Qt.AlignRight)
        top_row.addWidget(status_label)
        
        # Cancel button
        cancel_btn = QPushButton("✕")
        cancel_btn.setFixedWidth(24)
        cancel_btn.setFixedHeight(24)
        cancel_btn.setStyleSheet("""
            QPushButton {
                border: none;
                border-radius: 4px;
                background-color: transparent;
                color: #aaaaaa;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #ff4444;
                color: white;
            }
        """)
        cancel_btn.clicked.connect(lambda: self._cancel_display_transfer(transfer_id))
        top_row.addWidget(cancel_btn)
        
        layout.addLayout(top_row)
        
        # Middle row: paths
        path_row = QHBoxLayout()
        path_label = QLabel(f"<span style='color: {DARK_THEME['text_secondary']}; font-size: 9px;'>{source_path[:40]}... → {dest_path[:40]}...</span>")
        path_label.setSizePolicy(Qt.SizePolicy_Expanding, Qt.SizePolicy_Fixed)
        path_row.addWidget(path_label)
        layout.addLayout(path_row)
        
        # Bottom row: progress bar + speed/eta
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        
        progress_bar = QProgressBar()
        chunk_color = self._status_colors.get(status, '#666666')
        progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: none;
                border-radius: 3px;
                background-color: {DARK_THEME['bg_secondary']};
                text-align: center;
                color: white;
                font-size: 10px;
            }}
            QProgressBar::chunk {{
                background-color: {chunk_color};
                border-radius: 3px;
            }}
        """)
        progress_bar.setFixedHeight(16)
        
        # Set format based on status
        if status == 'waiting_session':
            progress_bar.setFormat(f"Waiting for {hostname}...")
        elif status == 'queued':
            progress_bar.setFormat("Queued")
        else:
            progress_bar.setFormat("Transferring...")
        
        bottom_row.addWidget(progress_bar, stretch=3)
        
        speed_label = QLabel("-")
        speed_label.setStyleSheet(f"font-size: 10px; color: {DARK_THEME['text_primary']}; font-weight: 500;")
        speed_label.setAlignment(Qt.AlignRight)
        speed_label.setFixedWidth(80)
        bottom_row.addWidget(speed_label)
        
        eta_label = QLabel("-")
        eta_label.setStyleSheet(f"font-size: 9px; color: {DARK_THEME['text_secondary']};")
        eta_label.setAlignment(Qt.AlignRight)
        eta_label.setFixedWidth(50)
        bottom_row.addWidget(eta_label)
        
        layout.addLayout(bottom_row)
        
        widget.setLayout(layout)
        item.setSizeHint(widget.sizeHint())
        
        # Add to list
        self.transfer_list.addItem(item)
        self.transfer_list.setItemWidget(item, widget)
        
        # Store reference
        self._transfer_displays[transfer_id] = {
            'widget': widget,
            'item': item,
            'progress_bar': progress_bar,
            'status_label': status_label,
            'speed_label': speed_label,
            'eta_label': eta_label,
            'source': source_path,
            'dest': dest_path,
            'is_active': (status == 'transferring'),
            'status': status,
            'hostname': hostname,
            'group_id': transfer_info.get('group_id')
        }
    
    def _cancel_display_transfer(self, transfer_id):
        """Cancel a display-based transfer"""
        # Check if in pending queue first
        for i, t in enumerate(self._pending_display_transfers):
            if t['transfer_id'] == transfer_id:
                self._pending_display_transfers.pop(i)
                # Remove from session waiters if present
                if transfer_id in self._session_waiters:
                    del self._session_waiters[transfer_id]
                # Remove display
                if transfer_id in self._transfer_displays:
                    display = self._transfer_displays[transfer_id]
                    display['is_active'] = False
                    display['status'] = 'cancelled'
                    display['status_label'].setText("Cancelled")
                    display['progress_bar'].setValue(0)
                self._schedule_queue_save()
                self._update_queue_status_label()
                return
        
        # Cancel if running
        if transfer_id in self._transfer_displays:
            display = self._transfer_displays[transfer_id]
            display['is_active'] = False
            display['status'] = 'cancelled'
            display['status_label'].setText("Cancelled")
            display['progress_bar'].setValue(0)
            
            # Cancel the worker if running
            if transfer_id in self._active_workers:
                worker = self._active_workers[transfer_id]
                if hasattr(worker, 'cancel'):
                    worker.cancel()
        
        # Check for more queued transfers
        self._check_and_start_queued()
    
    def _show_transfer_context_menu(self, pos):
        """Show context menu for transfer at position"""
        item = self.transfer_list.itemAt(pos)
        if not item:
            return
        
        transfer_id = item.data(Qt.UserRole)
        if not transfer_id:
            return
        
        menu = QMenu(self)
        
        # Priority submenu
        priority_menu = menu.addMenu("Priority")
        top_action = priority_menu.addAction("Move to Top")
        up_action = priority_menu.addAction("Move Up")
        down_action = priority_menu.addAction("Move Down")
        bottom_action = priority_menu.addAction("Move to Bottom")
        
        # Connect
        top_action.triggered.connect(lambda: self._move_transfer(transfer_id, 'top'))
        up_action.triggered.connect(lambda: self._move_transfer(transfer_id, 'up'))
        down_action.triggered.connect(lambda: self._move_transfer(transfer_id, 'down'))
        bottom_action.triggered.connect(lambda: self._move_transfer(transfer_id, 'bottom'))
        
        # Cancel action
        menu.addSeparator()
        cancel_action = menu.addAction("Cancel")
        cancel_action.triggered.connect(lambda: self._cancel_display_transfer(transfer_id))
        
        menu.exec(self.transfer_list.mapToGlobal(pos))
    
    def _move_transfer(self, transfer_id, direction):
        """Move transfer in queue"""
        idx = next((i for i, t in enumerate(self._pending_display_transfers) 
                    if t['transfer_id'] == transfer_id), None)
        if idx is None:
            return
        
        item = self._pending_display_transfers.pop(idx)
        
        if direction == 'top':
            new_idx = 0
        elif direction == 'bottom':
            new_idx = len(self._pending_display_transfers)
        elif direction == 'up':
            new_idx = max(0, idx - 1)
        elif direction == 'down':
            new_idx = min(len(self._pending_display_transfers), idx + 1)
        
        self._pending_display_transfers.insert(new_idx, item)
        
        self._schedule_queue_save()
        self._check_and_start_queued()
        
    def humanize_bytes(self, b):
        """Convert bytes to human readable format"""
        if b >= 1024**3:
            return f"{b / 1024**3:.1f} GB"
        elif b >= 1024**2:
            return f"{b / 1024**2:.1f} MB"
        elif b >= 1024:
            return f"{b / 1024:.1f} KB"
        else:
            return f"{b} B"

    def update_transfer_progress(self, transfer_id, bytes_done, bytes_total, speed_bps=0):
        """Update progress for a display transfer"""
        if transfer_id not in self._transfer_displays:
            return
        
        display = self._transfer_displays[transfer_id]
        if not display.get('is_active', False):
            return
        
        # Calculate percentage
        if bytes_total > 0:
            value = int((bytes_done / bytes_total) * 100)
        else:
            value = 0
        
        # Update progress bar
        display['progress_bar'].setValue(value)
        
        # Format progress text: "45% • 2.3 MB / 5.1 MB • 1.2 MB/s"
        done_str = self.humanize_bytes(bytes_done)
        total_str = self.humanize_bytes(bytes_total)
        speed_str = self.humanize_bytes(int(speed_bps)) + "/s" if speed_bps > 0 else "-"
        
        progress_text = f"{value}% • {done_str} / {total_str} • {speed_str}"
        display['progress_bar'].setFormat(progress_text)
        
        # Update status
        display['status_label'].setText("Transferring")
        
        # Update speed label
        display['speed_label'].setText(speed_str)
        
        # Update ETA
        if speed_bps > 0 and bytes_total > bytes_done:
            eta_seconds = (bytes_total - bytes_done) / speed_bps
            if eta_seconds < 60:
                eta_str = f"{int(eta_seconds)}s"
            elif eta_seconds < 3600:
                eta_str = f"{int(eta_seconds/60)}m"
            else:
                eta_str = f"{int(eta_seconds/3600)}h"
            display['eta_label'].setText(eta_str)
    
    def mark_transfer_complete(self, transfer_id):
        """Mark a display transfer as complete"""
        if transfer_id not in self._transfer_displays:
            return

        display = self._transfer_displays[transfer_id]
        display['is_active'] = False
        display['status'] = 'complete'
        display['status_label'].setText("Done")
        display['progress_bar'].setValue(100)
        display['progress_bar'].setFormat("100% • Complete")
        display['eta_label'].setText("-")

        file_name = os.path.basename(display['source'])
        self.text_console.append(f"Transfer complete: {file_name}")

        self.signal_transfer_completed.emit(1, f"Transfer complete: {file_name}")

        with QMutexLocker(self._active_transfers_lock):
            self.active_transfers = max(0, self.active_transfers - 1)
        self.update_overall_progress()

        # Auto-clear if preference is enabled
        from sftp_preferences import get_preferences
        prefs = get_preferences()
        if prefs.get_bool("clear_completed_on_complete", False):
            QTimer.singleShot(500, self.clear_completed)
        
        # Check for more queued transfers
        self._check_and_start_queued()

    def mark_transfer_failed(self, transfer_id, error_message):
        """Mark a display transfer as failed"""
        if transfer_id not in self._transfer_displays:
            return

        display = self._transfer_displays[transfer_id]
        display['is_active'] = False
        display['status'] = 'failed'
        display['status_label'].setText("Failed")
        display['status_label'].setStyleSheet(f"font-size: 10px; color: {DARK_THEME['error']}; font-weight: 500;")

        file_name = os.path.basename(display['source'])
        self.text_console.append(f"Transfer failed: {file_name} - {error_message}")

        self.signal_transfer_error.emit(transfer_id, error_message)

        with QMutexLocker(self._active_transfers_lock):
            self.active_transfers = max(0, self.active_transfers - 1)
        self.update_overall_progress()

        # Auto-clear if preference is enabled
        from sftp_preferences import get_preferences
        prefs = get_preferences()
        if prefs.get_bool("clear_completed_on_complete", False):
            QTimer.singleShot(500, self.clear_completed)
        
        # Check for more queued transfers
        self._check_and_start_queued()
    def remove_transfer_display(self, transfer_id):
        """Remove a transfer display"""
        if transfer_id in self._transfer_displays:
            display = self._transfer_displays[transfer_id]
            item = display['item']
            row = self.transfer_list.row(item)
            if row >= 0:
                self.transfer_list.takeItem(row)
            del self._transfer_displays[transfer_id]
            
            if transfer_id in self._active_workers:
                del self._active_workers[transfer_id]
    
    def register_worker(self, transfer_id, worker):
        """Register a worker for a display transfer (for cancellation)"""
        self._active_workers[transfer_id] = worker
    
    def stop_all_display_transfers(self):
        """Stop all display-based transfers"""
        for transfer_id, display in self._transfer_displays.items():
            if display.get('is_active', False):
                display['is_active'] = False
                display['status_label'].setText("Stopped")
                
                # Cancel worker if running
                if transfer_id in self._active_workers:
                    worker = self._active_workers[transfer_id]
                    if hasattr(worker, 'cancel'):
                        worker.cancel()
        
        self.text_console.append("All transfers stopped")

    def cancel_transfer(self, transfer_id):
        """Cancel a transfer"""
        try:
            if not transfer_id:
                return
                
            transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)
            if not transfer:
                return
            
            # Stop the worker
            if transfer.download_worker:
                try:
                    transfer.download_worker.stop_transfer()
                except (AttributeError, RuntimeError):
                    pass
            
            # Disconnect signals
            if hasattr(transfer.download_worker, 'signals'):
                try:
                    transfer.download_worker.signals.progress.disconnect()
                    transfer.download_worker.signals.finished.disconnect()
                    transfer.download_worker.signals.message.disconnect()
                except (RuntimeError, TypeError):
                    pass
            
            # Mark as inactive
            transfer.active = False
            
            # Update UI
            try:
                if transfer.status_label:
                    transfer.status_label.setText("Cancelled")
                if transfer.progress_bar:
                    transfer.progress_bar.setStyleSheet(f"""
                        QProgressBar::chunk {{
                            background-color: {DARK_THEME['error']};
                        }}
                    """)
            except RuntimeError:
                pass

            # Release resources
            self._release_transfer(transfer_id)
            
            # Try to start another transfer
            QTimer.singleShot(100, self.check_and_start_transfers)
            
        except (OSError, IOError, RuntimeError) as e:
            self.text_console.append(f"Error cancelling transfer: {e}")

    def cleanup_transfer(self, transfer_id):
        """Clean up transfer UI elements"""
        try:
            if not transfer_id:
                return
                
            transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)
            if not transfer:
                return
                
            # Remove from UI
            try:
                if transfer.list_item:
                    row = self.transfer_list.row(transfer.list_item)
                    if row >= 0:
                        self.transfer_list.takeItem(row)
            except (RuntimeError, ValueError):
                pass

            # Clean up references
            if hasattr(transfer, 'download_worker'):
                self._running_workers.discard(transfer.download_worker)
            self.transfers = [t for t in self.transfers if t.transfer_id != transfer_id]
            
        except (OSError, IOError, RuntimeError):
            pass

    def _release_transfer(self, transfer_id):
        """Release transfer resources"""
        try:
            with QMutexLocker(self._transfer_lock):
                if transfer_id in self._released_transfers:
                    return
                self._released_transfers.add(transfer_id)

            with QMutexLocker(self._active_transfers_lock):
                old_count = self.active_transfers
                self.active_transfers = max(self.active_transfers - 1, 0)
            self.remove_queue_item(transfer_id)
            self.update_overall_progress()
            
        except (OSError, IOError, RuntimeError) as e:
            logger.debug(f"Error releasing transfer {transfer_id}: {e}")

    def transfer_finished(self, transfer_id):
        """Handle transfer completion"""
        try:
            if not transfer_id:
                return
                
            transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)
            if not transfer:
                return

            transfer.active = False
            
            # Update group progress if this transfer is part of a group
            if hasattr(transfer, 'group_id') and transfer.group_id:
                group_id = transfer.group_id
                if group_id in self._transfer_groups:
                    self._transfer_groups[group_id]["completed_files"] += 1
            
            # Check if cancelled or errored
            is_cancelled = False
            is_error = False
            
            with response_queues_lock:
                if transfer_id in response_queues:
                    try:
                        while True:
                            msg = response_queues[transfer_id].get_nowait()
                            if msg == "cancelled":
                                is_cancelled = True
                            elif msg == "error":
                                is_error = True
                    except queue.Empty:
                        pass
            
            try:
                if is_cancelled:
                    if transfer.status_label:
                        transfer.status_label.setText("✗ Cancelled")
                        transfer.status_label.setStyleSheet("font-size: 10px; color: #FFA500; font-weight: bold;")
                    if transfer.progress_bar:
                        transfer.progress_bar.setValue(0)
                elif is_error:
                    if transfer.status_label:
                        transfer.status_label.setText("✗ Error")
                        transfer.status_label.setStyleSheet(f"font-size: 10px; color: {DARK_THEME['error']}; font-weight: bold;")
                    if transfer.progress_bar:
                        transfer.progress_bar.setStyleSheet(f"""
                            QProgressBar {{
                                border: none;
                                border-radius: 3px;
                                background-color: {DARK_THEME['border']};
                            }}
                            QProgressBar::chunk {{
                                background-color: {DARK_THEME['error']};
                                border-radius: 3px;
                            }}
                        """)
                else:
                    if transfer.status_label:
                        transfer.status_label.setText("✓ Done")
                        transfer.status_label.setStyleSheet(f"font-size: 10px; color: {DARK_THEME['success']}; font-weight: bold;")
                    if transfer.progress_bar:
                        transfer.progress_bar.setValue(100)
                        transfer.progress_bar.setStyleSheet(f"""
                            QProgressBar {{
                                border: none;
                                border-radius: 3px;
                                background-color: {DARK_THEME['border']};
                            }}
                            QProgressBar::chunk {{
                                background-color: {DARK_THEME['success']};
                                border-radius: 3px;
                            }}
                        """)
            except RuntimeError:
                pass

            # Notify observers
            try:
                if hasattr(transfer.download_worker, 'command') and \
                   transfer.download_worker.command in ["upload", "download", "resume"]:
                    self.notify_observees()
            except (OSError, IOError, RuntimeError):
                pass

            # Log to transfer history
            try:
                if hasattr(transfer.download_worker, 'command') and \
                   transfer.download_worker.command in ["upload", "download", "resume"]:
                    worker = transfer.download_worker
                    direction = 'upload' if worker.command == 'upload' else 'download'
                    if worker.command == 'resume':
                        direction = 'download' if worker.is_source_remote else 'upload'
                    
                    status = 'success'
                    error_msg = None
                    if is_cancelled:
                        status = 'failed'
                        error_msg = 'Cancelled by user'
                    elif is_error:
                        status = 'failed'
                        error_msg = 'Transfer error'
                    
                    log_transfer(
                        source_path=getattr(worker, 'job_source', ''),
                        destination_path=getattr(worker, 'job_destination', ''),
                        direction=direction,
                        hostname=getattr(worker, 'hostname', None),
                        username=getattr(worker, 'username', None),
                        file_size=getattr(worker, 'file_size', None),
                        status=status,
                        error_message=error_msg
                    )
            except Exception:
                pass  # Don't fail transfer if logging fails

            # Release resources but DON'T cleanup - keep visible
            self._release_transfer(transfer_id)
            
            # Emit transfer completed signal
            self.signal_transfer_completed.emit(1, "Transfer completed")
            
            # Auto-clear if preference is enabled
            prefs = get_preferences()
            if prefs.get_bool("clear_completed_on_complete", False):
                QTimer.singleShot(200, self.clear_completed)
            
            # Try to start another transfer
            QTimer.singleShot(100, self.check_and_start_transfers)
            
        except (OSError, IOError, RuntimeError):
            pass

    def transfer_error(self, transfer_id, message):
        """Handle transfer errors"""
        try:
            if not transfer_id:
                return
            
            transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)
            if not transfer:
                return
            
            transfer.active = False
            
            try:
                if transfer.status_label:
                    transfer.status_label.setText("✗ Failed")
                    transfer.status_label.setStyleSheet(f"font-size: 10px; color: {DARK_THEME['error']}; font-weight: bold;")
                if transfer.progress_bar:
                    transfer.progress_bar.setStyleSheet(f"""
                        QProgressBar {{
                            border: none;
                            border-radius: 3px;
                            background-color: {DARK_THEME['border']};
                        }}
                        QProgressBar::chunk {{
                            background-color: {DARK_THEME['error']};
                            border-radius: 3px;
                        }}
                    """)
            except RuntimeError:
                pass
            
            if hasattr(self, 'text_console'):
                self.text_console.append(f"ERROR Transfer {transfer_id}: {message}")
            
            # Log to transfer history
            try:
                if hasattr(transfer, 'download_worker') and transfer.download_worker:
                    worker = transfer.download_worker
                    direction = 'upload' if getattr(worker, 'command', '') == 'upload' else 'download'
                    
                    log_transfer(
                        source_path=getattr(worker, 'job_source', ''),
                        destination_path=getattr(worker, 'job_destination', ''),
                        direction=direction,
                        hostname=getattr(worker, 'hostname', None),
                        username=getattr(worker, 'username', None),
                        file_size=getattr(worker, 'file_size', None),
                        status='failed',
                        error_message=str(message)[:500] if message else 'Unknown error'
                    )
            except Exception:
                pass  # Don't fail if logging fails
            
            # Notify observers to refresh browsers (local file may have been created before error)
            try:
                if hasattr(transfer, 'download_worker') and transfer.download_worker and \
                   hasattr(transfer.download_worker, 'command') and \
                   transfer.download_worker.command in ["upload", "download", "resume"]:
                    self.notify_observees()
            except (OSError, IOError, RuntimeError):
                pass
            
            # Emit transfer error signal
            self.signal_transfer_error.emit(1, f"Transfer failed: {message}")
            
            self._release_transfer(transfer_id)
            
        except (OSError, IOError, RuntimeError) as e:
            logger.debug(f"Error in transfer_error handler: {e}")

    def _handle_worker_message(self, transfer_id, message):
        """Handle messages from worker threads"""
        try:
            if any(keyword in message.lower() for keyword in ['error', 'failed', 'exception', 'timeout']):
                self.transfer_error(transfer_id, message)
            else:
                if hasattr(self, 'text_console'):
                    self.text_console.append(f"Transfer {transfer_id}: {message}")
        except (OSError, IOError, RuntimeError) as e:
            logger.debug(f"Error handling worker message: {e}")

    def _handle_conflict(self, transfer_id, dest_path, dest_type):
        """Handle file conflict - queue prompt so only one dialog shows at a time"""
        # Find the worker and group_id
        worker = None
        group_id = None
        
        # Check transfers list (legacy)
        transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)
        if transfer:
            worker = transfer.download_worker
            if hasattr(transfer, 'group_id'):
                group_id = transfer.group_id
        
        # Check active workers (DirectTransferWorker)
        if not worker and transfer_id in self._active_workers:
            worker = self._active_workers[transfer_id]
            # Try to find group_id from display
            if transfer_id in self._transfer_displays:
                group_id = self._transfer_displays[transfer_id].get('group_id')
        
        if not worker:
            return
        
        # Check per-group flags first (no dialog needed)
        if group_id:
            if group_id in self._group_cancel_all:
                worker.set_conflict_result("cancel")
                return
            if group_id in self._group_overwrite_all:
                worker.set_conflict_result("overwrite_all")
                return
            elif group_id in self._group_skip_all:
                worker.set_conflict_result("skip_all")
                return
            elif group_id in self._group_resume_all:
                worker.set_conflict_result("resume_all")
                return
        
        # Queue the conflict and process serially
        self._conflict_queue.append((transfer_id, dest_path, dest_type))
        if not self._conflict_dialog_active:
            self._process_next_conflict()
    
    def _process_next_conflict(self):
        """Show the next conflict dialog in the queue"""
        if not self._conflict_queue:
            self._conflict_dialog_active = False
            return
        
        self._conflict_dialog_active = True
        transfer_id, dest_path, dest_type = self._conflict_queue.pop(0)
        
        try:
            # Find the worker and group_id
            worker = None
            group_id = None
            
            # Check transfers list (legacy)
            transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)
            if transfer:
                worker = transfer.download_worker
                if hasattr(transfer, 'group_id'):
                    group_id = transfer.group_id
            
            # Check active workers (DirectTransferWorker)
            if not worker and transfer_id in self._active_workers:
                worker = self._active_workers[transfer_id]
                # Try to find group_id from display
                if transfer_id in self._transfer_displays:
                    group_id = self._transfer_displays[transfer_id].get('group_id')
            
            if not worker:
                self._process_next_conflict()
                return
            
            # Re-check group flags (may have been set by a previous dialog)
            if group_id:
                if group_id in self._group_cancel_all:
                    worker.set_conflict_result("cancel")
                    self._process_next_conflict()
                    return
                if group_id in self._group_overwrite_all:
                    worker.set_conflict_result("overwrite_all")
                    self._process_next_conflict()
                    return
                elif group_id in self._group_skip_all:
                    worker.set_conflict_result("skip_all")
                    self._process_next_conflict()
                    return
                elif group_id in self._group_resume_all:
                    worker.set_conflict_result("resume_all")
                    self._process_next_conflict()
                    return
            
            filename = os.path.basename(dest_path)
            location = "on remote" if dest_type == "remote" else "locally"
            
            msg_box = QMessageBox()
            msg_box.setIcon(Qt.MsgIcon_Question)
            msg_box.setText(f"'{filename}' already exists {location}.")
            msg_box.setInformativeText("What would you like to do?")
            msg_box.setWindowTitle("File Exists")
            
            # Standardized button order for consistent UI
            cancel_btn = msg_box.addButton("Cancel All", Qt.MsgRole_RejectRole)
            skip_all_btn = msg_box.addButton("Skip All", Qt.MsgRole_NoRole)
            skip_btn = msg_box.addButton("Skip", Qt.MsgRole_NoRole)
            overwrite_all_btn = msg_box.addButton("Overwrite All", Qt.MsgRole_YesRole)
            overwrite_btn = msg_box.addButton("Overwrite", Qt.MsgRole_YesRole)
            resume_all_btn = msg_box.addButton("Resume All", Qt.MsgRole_AcceptRole)
            
            msg_box.exec()
            
            clicked = msg_box.clickedButton()
            if clicked == overwrite_all_btn:
                action = "overwrite_all"
            elif clicked == overwrite_btn:
                action = "overwrite"
            elif clicked == skip_all_btn:
                action = "skip_all"
            elif clicked == skip_btn:
                action = "skip"
            elif clicked == resume_all_btn:
                action = "resume_all"
            else:
                action = "cancel"
            
            # Store per-group flags
            if group_id:
                if action == "overwrite_all":
                    self._group_overwrite_all.add(group_id)
                elif action == "skip_all":
                    self._group_skip_all.add(group_id)
                elif action == "resume_all":
                    self._group_resume_all.add(group_id)
                elif action == "cancel":
                    self._group_cancel_all.add(group_id)
            
            worker.set_conflict_result(action)
            
        except (RuntimeError, AttributeError):
            pass
        
        # Process next queued conflict
        self._process_next_conflict()

    def update_progress(self, transfer_id, value, speed_bps=None, eta_sec=None, bytes_done=0, bytes_total=0):
        """Update transfer progress with bytes tracking"""
        import logging
        logger = logging.getLogger('sftp.queue')
        logger.debug(f"update_progress called: {transfer_id}, {value}%, {bytes_done}/{bytes_total}")
        
        try:
            if not transfer_id:
                return
            
            transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)
            if not transfer or not transfer.active:
                return

            speed = speed_bps if speed_bps is not None else 0.0
            eta = eta_sec if eta_sec is not None else 0.0
            
            # Update transfer object with progress data
            transfer.bytes_done = bytes_done
            transfer.bytes_total = bytes_total
            transfer.speed_bps = speed
            transfer.eta_seconds = eta
            
            self.signal_transfer_progress.emit(transfer_id, value, speed, eta, bytes_done, bytes_total)
            
            try:
                if transfer.progress_bar:
                    transfer.progress_bar.setValue(value)
                    # Update progress bar text format
                    if bytes_total > 0:
                        bytes_str = self.format_bytes(bytes_done, bytes_total)
                        transfer.progress_bar.setFormat(f"{value}% • {bytes_str}")
                    
                if transfer.speed_label and speed_bps is not None:
                    transfer.speed_label.setText(self.format_speed(speed_bps))

                if transfer.eta_label and eta_sec is not None:
                    transfer.eta_label.setText(self.format_time(eta_sec))

                if transfer.status_label:
                    if value == 100:
                        transfer.status_label.setText("✓ Done")
                        transfer.status_label.setStyleSheet(f"font-size: 10px; color: {DARK_THEME['success']}; font-weight: bold;")
                    elif getattr(transfer, 'paused', False):
                        transfer.status_label.setText("⏸ Paused")
                        transfer.status_label.setStyleSheet(f"font-size: 10px; color: {DARK_THEME['warning']}; font-weight: bold;")
                    else:
                        transfer.status_label.setText(f"{value}%")
                        transfer.status_label.setStyleSheet(f"font-size: 10px; color: {DARK_THEME['text_secondary']};")
            except RuntimeError:
                pass
            
            # Update overall progress
            self.update_overall_progress()

        except (OSError, IOError, RuntimeError):
            pass

    def format_bytes(self, bytes_done, bytes_total):
        """Format bytes done / bytes total"""
        def humanize(b):
            if b >= 1024**3:
                return f"{b / 1024**3:.1f} GB"
            elif b >= 1024**2:
                return f"{b / 1024**2:.1f} MB"
            elif b >= 1024:
                return f"{b / 1024:.1f} KB"
            else:
                return f"{b} B"
        
        return f"{humanize(bytes_done)}/{humanize(bytes_total)}"

    def format_speed(self, bytes_per_sec):
        """Format transfer speed"""
        try:
            if bytes_per_sec >= 1024 * 1024:
                return f"{bytes_per_sec / (1024 * 1024):.1f} MB/s"
            elif bytes_per_sec >= 1024:
                return f"{bytes_per_sec / 1024:.1f} KB/s"
            return f"{bytes_per_sec} B/s"
        except (TypeError, ValueError):
            return "-"

    def format_time(self, seconds):
        """Format time"""
        try:
            if seconds < 60:
                return f"{int(seconds)}s"
            elif seconds < 3600:
                return f"{int(seconds // 60)}m {int(seconds % 60)}s"
            return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m"
        except (TypeError, ValueError):
            return "-"

    def toggle_pause_transfer(self, transfer_id):
        """Toggle pause for a transfer"""
        try:
            transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)
            if transfer and transfer.active:
                transfer.paused = not getattr(transfer, 'paused', False)
                if hasattr(transfer.download_worker, 'paused'):
                    transfer.download_worker.paused = transfer.paused
                if transfer.pause_button:
                    transfer.pause_button.setText("Resume" if transfer.paused else "Pause")
                if transfer.status_label:
                    transfer.status_label.setText("Paused" if transfer.paused else "Resuming...")
        except (OSError, IOError, RuntimeError):
            pass

    def toggle_pause_all(self):
        """Toggle pause for all transfers"""
        try:
            active_transfers = [t for t in self.transfers if t.active]
            if not active_transfers:
                return
                
            any_paused = any(getattr(t, 'paused', False) for t in active_transfers)
            for transfer in active_transfers:
                transfer.paused = not any_paused
                if hasattr(transfer.download_worker, 'paused'):
                    transfer.download_worker.paused = transfer.paused
                if transfer.pause_button:
                    transfer.pause_button.setText("Resume" if transfer.paused else "Pause")
                if transfer.status_label:
                    transfer.status_label.setText("Paused" if transfer.paused else "Resuming...")
            self.pause_button.setText("Resume All" if not any_paused else "Pause All")
        except (OSError, IOError, RuntimeError):
            pass

    def pause_all_transfers(self):
        """Pause or resume all active transfers"""
        try:
            any_paused = any(getattr(t, 'paused', False) for t in self.transfers if t.active)
            
            for transfer in self.transfers:
                if transfer.active:
                    transfer.paused = not any_paused
                    if hasattr(transfer.download_worker, 'set_paused'):
                        transfer.download_worker.set_paused(transfer.paused)
            
            self.pause_button.setText("Resume All" if any_paused else "⏸ Pause")
            
        except (OSError, IOError, RuntimeError) as e:
            self.text_console.append(f"Error pausing transfers: {e}")
    
    def stop_all_transfers(self):
        """Cancel all active transfers"""
        try:
            # Clear the transfer queue to stop new transfers from starting
            clear_sftp_queue()
            
            # Stop all active display-based transfers (DirectTransferWorker)
            self.stop_all_display_transfers()
            
            # Stop legacy download workers
            for transfer in self.transfers:
                if transfer.active:
                    if hasattr(transfer.download_worker, '_stop_flag'):
                        transfer.download_worker._stop_flag = True
                    if hasattr(transfer.download_worker, 'stop_transfer'):
                        transfer.download_worker.stop_transfer()
            
            # Cancel any active traversal or deletion workers in browser observees
            with QMutexLocker(self._observees_lock):
                for observee in self._observees:
                    if hasattr(observee, '_current_traversal_worker') and observee._current_traversal_worker:
                        observee._current_traversal_worker.cancel()
                        observee._current_traversal_worker = None
                    if hasattr(observee, '_deletion_worker') and observee._deletion_worker:
                        observee._deletion_worker.cancel()
            
            # Clear pending group assignments
            if hasattr(self, '_pending_group_assignments'):
                self._pending_group_assignments.clear()
            
            self.text_console.append("All transfers stopped")
            
        except (OSError, IOError, RuntimeError) as e:
            self.text_console.append(f"Error stopping transfers: {e}")
    
    def clear_completed(self):
        """Remove completed/cancelled/error transfers"""
        try:
            transfers_to_remove = []
            
            # Check legacy transfers
            for transfer in self.transfers[:]:
                status_text = transfer.status_label.text() if transfer.status_label else ""
                if (not transfer.active or 
                    status_text in ["✓ Done", "Done", "✗ Cancelled", "✗ Error", "✗ Failed", "Failed"] or
                    "Error:" in status_text):
                    transfers_to_remove.append(transfer.transfer_id)
            
            # Check display-only transfers
            for tid, display in list(self._transfer_displays.items()):
                if not display.get('is_active', False):
                    status_text = display['status_label'].text() if 'status_label' in display else ""
                    if status_text in ["Done", "Failed", "Stopped", "Cancelled"]:
                        transfers_to_remove.append(tid)
            
            # Unique IDs
            transfers_to_remove = list(set(transfers_to_remove))
            
            for transfer_id in transfers_to_remove:
                if transfer_id in self._transfer_displays:
                    self.remove_transfer_display(transfer_id)
                else:
                    self.cleanup_transfer(transfer_id)
                
        except (OSError, IOError, RuntimeError) as e:
            self.text_console.append(f"Error clearing completed transfers: {e}")
    
    def clear_all_transfers(self):
        """Remove all transfers without saving"""
        try:
            for transfer in self.transfers[:]:
                if transfer.active:
                    if hasattr(transfer.download_worker, '_stop_flag'):
                        transfer.download_worker._stop_flag = True
                    if hasattr(transfer.download_worker, 'cancel'):
                        transfer.download_worker.cancel()
                self.cleanup_transfer(transfer.transfer_id)
            self.transfer_list.clear()
        except (OSError, IOError, RuntimeError) as e:
            pass
    def cleanup(self):
        """Cleanup resources when widget is destroyed"""
        try:
            self.save_pending_transfers()
            
            if hasattr(self, 'check_queue_timer'):
                self.check_queue_timer.stop()

            for transfer in self.transfers[:]:
                try:
                    if transfer.active and hasattr(transfer, 'download_worker'):
                        transfer.download_worker._stop_flag = True
                except (OSError, IOError, RuntimeError):
                    pass

            clear_sftp_queue()

            if hasattr(self, 'thread_pool'):
                self.thread_pool.waitForDone(2000)

            self.transfers.clear()
            self.active_transfers = 0

        except (OSError, IOError, RuntimeError) as e:
            logger.debug(f"Error in cleanup: {e}")
    
    def save_pending_transfers(self):
        """Save pending and paused transfers to disk for restoration on next launch"""
        try:
            pending_jobs = []
            
            while not sftp_queue.empty():
                try:
                    job = sftp_queue.get_nowait()
                    if job and hasattr(job, 'job_id'):
                        # Skip jobs with empty paths
                        src = getattr(job, 'source_path', '') or ''
                        dst = getattr(job, 'destination_path', '') or ''
                        if not src or not dst:
                            continue
                        # Encrypt password for secure storage
                        password = getattr(job, 'password', '') or ''
                        if password and sftp_hostdataeditor.cipher_suite:
                            try:
                                encrypted_password = sftp_hostdataeditor.cipher_suite.encrypt(password.encode()).decode()
                            except Exception:
                                encrypted_password = ''
                        else:
                            encrypted_password = ''
                        pending_jobs.append({
                            'source_path': src,
                            'is_source_remote': getattr(job, 'is_source_remote', False),
                            'destination_path': dst,
                            'is_destination_remote': getattr(job, 'is_destination_remote', False),
                            'hostname': getattr(job, 'hostname', ''),
                            'username': getattr(job, 'username', ''),
                            'password': encrypted_password,
                            'port': getattr(job, 'port', 22),
                            'command': getattr(job, 'command', 'download'),
                            'job_id': getattr(job, 'job_id'),
                            'key': getattr(job, 'key'),
                            'status': 'queued'
                        })
                except queue.Empty:
                    break
            
            with QMutexLocker(self._transfer_lock):
                for transfer in self.transfers:
                    if transfer.active or (hasattr(transfer, 'paused') and transfer.paused):
                        if hasattr(transfer, 'download_worker') and transfer.download_worker:
                            worker = transfer.download_worker
                            # Use job_source/job_destination (DownloadWorker attributes)
                            src = getattr(worker, 'job_source', '') or ''
                            dst = getattr(worker, 'job_destination', '') or ''
                            # Skip transfers with empty paths
                            if not src or not dst:
                                continue
                            # Encrypt password for secure storage
                            password = getattr(worker, 'password', '') or ''
                            if password and sftp_hostdataeditor.cipher_suite:
                                try:
                                    encrypted_password = sftp_hostdataeditor.cipher_suite.encrypt(password.encode()).decode()
                                except Exception:
                                    encrypted_password = ''
                            else:
                                encrypted_password = ''
                            pending_jobs.append({
                                'source_path': src,
                                'is_source_remote': getattr(worker, 'is_source_remote', False),
                                'destination_path': dst,
                                'is_destination_remote': getattr(worker, 'is_destination_remote', False),
                                'hostname': getattr(worker, 'hostname', ''),
                                'username': getattr(worker, 'username', ''),
                                'password': encrypted_password,
                                'port': getattr(worker, 'port', 22),
                                'command': getattr(worker, 'command', 'download'),
                                'job_id': transfer.transfer_id,
                                'key': getattr(worker, 'temp_key', None),
                                'status': 'paused' if getattr(transfer, 'paused', False) else 'active'
                            })
            
            if pending_jobs:
                create_secure_directory(os.path.dirname(QUEUE_FILE_PATH))
                if is_windows():
                    with open(QUEUE_FILE_PATH, 'w') as f:
                        json.dump(pending_jobs, f, indent=2)
                else:
                    old_umask = os.umask(0o077)
                    try:
                        with open(QUEUE_FILE_PATH, 'w') as f:
                            json.dump(pending_jobs, f, indent=2)
                        secure_file_permissions(QUEUE_FILE_PATH)
                    finally:
                        os.umask(old_umask)
            else:
                if os.path.exists(QUEUE_FILE_PATH):
                    try:
                        os.unlink(QUEUE_FILE_PATH)
                    except OSError:
                        pass
            
        except (OSError, IOError, json.JSONEncodeError) as e:
            pass
    def load_pending_transfers(self):
        """Load pending transfers from disk and restore them to the queue"""
        try:
            if not os.path.exists(QUEUE_FILE_PATH):
                return 0
            
            with open(QUEUE_FILE_PATH, 'r') as f:
                saved_jobs = json.load(f)
            
            if not saved_jobs:
                return 0
            
            restored_count = 0
            for job_data in saved_jobs:
                try:
                    src = job_data.get('source_path', '')
                    dst = job_data.get('destination_path', '')
                    # Skip jobs with empty paths
                    if not src or not dst:
                        continue
                    
                    # Decrypt password from secure storage
                    encrypted_password = job_data.get('password', '')
                    if encrypted_password and sftp_hostdataeditor.cipher_suite:
                        try:
                            password = sftp_hostdataeditor.cipher_suite.decrypt(encrypted_password.encode()).decode()
                        except Exception:
                            logger.warning("Failed to decrypt saved password")
                            password = ''
                    else:
                        password = ''
                    
                    job = SFTPJob(
                        source_path=src,
                        is_source_remote=job_data.get('is_source_remote', False),
                        destination_path=dst,
                        is_destination_remote=job_data.get('is_destination_remote', False),
                        hostname=job_data.get('hostname', ''),
                        username=job_data.get('username', ''),
                        password=password,
                        port=job_data.get('port', 22),
                        command=job_data.get('command', 'download'),
                        job_id=job_data.get('job_id'),
                        key=job_data.get('key')
                    )
                    
                    sftp_queue.put(job)
                    restored_count += 1
                    
                except (KeyError, TypeError) as e:
                    continue
            
            try:
                os.unlink(QUEUE_FILE_PATH)
            except OSError:
                pass
            
            if restored_count > 0:
                self.text_console.append(f"Restored {restored_count} pending transfer(s) from previous session")
            return restored_count
            
        except (OSError, IOError, json.JSONDecodeError) as e:
            return 0
