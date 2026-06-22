from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                            QListWidget, QTextEdit, QProgressBar, QSizePolicy,
                            QLabel, QListWidgetItem, QScrollArea, QFrame, QCheckBox,
                            QMessageBox, QMenu, QSpinBox)
from sftp_qt_compat import Qt  # Use compatibility layer for Qt enums
from PySide6.QtCore import QThreadPool, QTimer, Signal, Slot
import inspect
import os
import json
DEBUG = os.environ.get('SFTP_DEBUG', '').lower() in ('1', 'true', 'yes')
import time
import logging
import sys
from sftp_theme import (BUTTON_STYLE_DARK, LIST_WIDGET_STYLE_DARK, PROGRESS_BAR_STYLE_DARK,
                        TEXT_EDIT_STYLE_DARK, DARK_THEME)
from sftp_preferences import get_preferences
from sftp_context_menu_customizer import is_visible
import sftp_hostdataeditor
from sftp_transfer_history import log_transfer
from sftp_platform import get_transfer_queue_path, create_secure_directory, secure_file_permissions, is_windows
from sftp_transfer_model import TransferModel
from sftp_transfer_persistence import TransferPersistence

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
    if DEBUG:
        print("DEBUG: TransferQueueWidget class defined", file=sys.stderr)
    
    # Signals for transfer events
    signal_transfer_started = Signal(int, str)  # (count, message)
    signal_transfer_completed = Signal(int, str)  # (count, message)
    signal_transfer_error = Signal(int, str)  # (count, message)
    signal_transfer_progress = Signal(int, int, float, float, int, int)  # (transfer_id, percent, speed_bps, eta_sec, bytes_done, bytes_total)
    signal_discovery_progress = Signal(int, int)  # (files_found, dirs_scanned)
    signal_overall_progress = Signal(int, float, float, int, int)  # (percent, total_speed, eta_seconds, bytes_done, bytes_total)
    
    # Signal for adding transfer display from background threads (single tuple param)
    signal_add_transfer_display = Signal(object)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Model and persistence layer
        self.model = TransferModel(self)
        self.persistence = TransferPersistence()
        
        # New display-only transfer tracking (for DirectTransferWorker)
        self._transfer_displays = {}  # transfer_id -> {widget, progress_bar, status_label, speed_label, eta_label, source, dest}
        
        # Debounce timer for refresh - prevents excessive refreshing during bulk transfers
        self._refresh_debounce_timer = None
        
        # Collapse state
        self._panel_collapsed = False
        self._console_collapsed = False
        
        # Debounce timer for queue saves
        self._queue_save_timer = None

        # ================================================================
        # Alias mutable model state onto self for backward compatibility.
        # Single-value attributes (bool, int, str) use properties to
        # delegate through self.model.
        # ================================================================
        self._pending_display_transfers = self.model._pending_display_transfers
        self._session_waiters = self.model._session_waiters
        self._transfer_groups = self.model._transfer_groups
        self._active_workers = self.model._active_workers
        self._running_workers = self.model._running_workers
        self._group_overwrite_all = self.model._group_overwrite_all
        self._group_skip_all = self.model._group_skip_all
        self._group_resume_all = self.model._group_resume_all
        self._group_cancel_all = self.model._group_cancel_all
        self._conflict_queue = self.model._conflict_queue
        self._observees = self.model._observees
        self._observees_lock = self.model._observees_lock
        self._released_transfers = self.model._released_transfers
        self._pending_group_assignments = self.model._pending_group_assignments
        
        self._batch_add_active = False
        
        # Status colors for UI
        self._status_colors = {
            'waiting_session': '#FFA500',     # Orange
            'queued': '#888888',              # Gray
            'transferring': '#4CAF50',        # Green
            'complete': '#2196F3',            # Blue
            'failed': '#F44336',              # Red
            'paused': '#666666',              # Dark gray
            'retrying': '#FF9800',            # Amber
        }
        
        # Connect signal for thread-safe transfer display addition
        self.signal_add_transfer_display.connect(
            self._add_transfer_display_slot,
            type=Qt.QueuedConnection
        )
        
        self.init_ui()
        
        # Load persisted queue (must be after init_ui, needs text_console)
        self._load_pending_queue()

    @property
    def _paused(self):
        return self.model._paused
    @_paused.setter
    def _paused(self, val):
        self.model._paused = val

    @property
    def _paused_by_user(self):
        return self.model._paused_by_user
    @_paused_by_user.setter
    def _paused_by_user(self, val):
        self.model._paused_by_user = val

    @property
    def _batch_add_active(self):
        return self.model._batch_add_active
    @_batch_add_active.setter
    def _batch_add_active(self, val):
        self.model._batch_add_active = val

    @property
    def _conflict_dialog_active(self):
        return self.model._conflict_dialog_active
    @_conflict_dialog_active.setter
    def _conflict_dialog_active(self, val):
        self.model._conflict_dialog_active = val

    @property
    def _discovery_active(self):
        return self.model._discovery_active
    @_discovery_active.setter
    def _discovery_active(self, val):
        self.model._discovery_active = val

    @property
    def _discovery_files_found(self):
        return self.model._discovery_files_found
    @_discovery_files_found.setter
    def _discovery_files_found(self, val):
        self.model._discovery_files_found = val

    @property
    def _discovery_dirs_scanned(self):
        return self.model._discovery_dirs_scanned
    @_discovery_dirs_scanned.setter
    def _discovery_dirs_scanned(self, val):
        self.model._discovery_dirs_scanned = val

    @property
    def _discovery_total_files(self):
        return self.model._discovery_total_files
    @_discovery_total_files.setter
    def _discovery_total_files(self, val):
        self.model._discovery_total_files = val

    @property
    def _current_group_id(self):
        return self.model._current_group_id
    @_current_group_id.setter
    def _current_group_id(self, val):
        self.model._current_group_id = val

    @property
    def _max_concurrent_transfers(self):
        return self.model._max_concurrent_transfers
    @_max_concurrent_transfers.setter
    def _max_concurrent_transfers(self, val):
        self.model._max_concurrent_transfers = val

    def _insert_pending_by_priority(self, transfer_info):
        """Insert transfer into queue. Delegates to model."""
        self.model.insert_pending_by_priority(transfer_info)

    def begin_batch_add(self):
        """Start batch add mode - defers UI updates and uses O(1) insertion"""
        self.model.set_batch_active(True)
        if hasattr(self, 'transfer_list'):
            self.transfer_list.setUpdatesEnabled(False)

    def end_batch_add(self):
        """End batch add mode - re-enables UI and starts queued transfers"""
        self.model.set_batch_active(False)
        if hasattr(self, 'transfer_list'):
            self.transfer_list.setUpdatesEnabled(True)
        self._schedule_queue_save()
        if not self.model.is_paused():
            self._check_and_start_queued()
    
    @staticmethod
    def _is_transient_error(msg):
        if not msg:
            return False
        msg_lower = msg.lower()
        transient_indicators = [
            'channel', 'open failed', 'connect failed',
            'timed out', 'timeout', 'connection reset',
            'broken pipe', 'eof', 'transport',
            'session', 'not open', 'closed',
        ]
        return any(indicator in msg_lower for indicator in transient_indicators)

    def _auto_retry_failed_transfers(self):
        for tid, display in list(self._transfer_displays.items()):
            if display.get('status') != 'failed':
                continue

            error_msg = display.get('error_message', '')
            if not self._is_transient_error(error_msg):
                continue

            transfer_info = display.get('transfer_info')
            if not transfer_info:
                continue

            retry_count = display.get('_auto_retry_count', 0) + 1
            file_name = os.path.basename(display['source'])
            self.text_console.append(f"Auto-retrying (attempt {retry_count}): {file_name}")

            self.remove_transfer_display(tid)

            transfer_info = dict(transfer_info)
            new_id = f"{tid}_r{retry_count}"
            self.add_transfer_display(
                transfer_id=new_id,
                source_path=transfer_info['source_path'],
                dest_path=transfer_info['dest_path'],
                is_source_remote=transfer_info['is_source_remote'],
                is_destination_remote=transfer_info['is_destination_remote'],
                hostname=transfer_info['hostname'],
                port=transfer_info['port'],
                username=transfer_info['username'],
                password=transfer_info['password'],
                command=transfer_info['command'],
                key=transfer_info.get('key', ''),
                session_id=transfer_info.get('session_id'),
                group_id=transfer_info.get('group_id')
            )

            if new_id in self._transfer_displays:
                self._transfer_displays[new_id]['_auto_retry_count'] = retry_count

            return True

        return False

    def _check_and_start_queued(self):
        """Start transfers one at a time with staggered delays to avoid thundering herd."""
        if self._paused:
            return
        
        active = len([t for t in self._transfer_displays.values() 
                      if t.get('status') == 'transferring'])
        
        if active >= self._max_concurrent_transfers:
            self._update_queue_status_label()
            return
        
        if self._auto_retry_failed_transfers():
            QTimer.singleShot(150, self._check_and_start_queued)
            return
        
        transfer_info = None
        for t in self._pending_display_transfers:
            if t['status'] in ('queued',):
                transfer_info = t
                break
        
        if not transfer_info:
            self._update_queue_status_label()
            return
        
        self._pending_display_transfers.remove(transfer_info)
        self._start_queued_transfer(transfer_info)
        
        self._schedule_queue_save()
        self._update_queue_status_label()
        
        # Stagger: schedule next start after short delay so channel opens
        # don't all hit the server simultaneously
        QTimer.singleShot(150, self._check_and_start_queued)
    
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

            # Update display with discovered file size if it was unknown
            file_size = transfer_info.get('file_size', 0)
            if file_size <= 0 and not transfer_info['is_source_remote']:
                try:
                    file_size = os.path.getsize(transfer_info['source_path'])
                    if file_size > 0:
                        transfer_info['file_size'] = file_size
                        if transfer_id in self._transfer_displays:
                            self._transfer_displays[transfer_id]['bytes_total'] = file_size
                            # If it's in a group, we might need to update the group total now
                            # but it's cleaner if it was already accounted for.
                            # Since we now do it in add_transfer_display, this is mostly a fallback.
                            group_id = transfer_info.get('group_id')
                            if group_id and group_id in self._transfer_groups:
                                # Only add if it wasn't already added (difficult to track without extra state)
                                # For now, we rely on add_transfer_display having done it.
                                pass
                except (OSError, IOError):
                    pass

            worker.signals.progress.connect(                lambda bd, bt, sp, et, tid=transfer_id:
                    self.update_transfer_progress(tid, bd, bt, sp),
                type=Qt.QueuedConnection
            )
            worker.signals.finished.connect(
                lambda s, f, tid=transfer_id: self.mark_transfer_complete(tid) if f == 0 else None,
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
            worker.signals.retrying.connect(
                lambda attempt, max_att, err, tid=transfer_id:
                    self._handle_retrying(tid, attempt, max_att, err),
                type=Qt.QueuedConnection
            )
            worker.signals.disk_full.connect(
                lambda err: self._handle_disk_full(err),
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
            display['progress_bar'].setFormat("Failed - double-click to retry")
        elif status == 'retrying':
            display['progress_bar'].setFormat("Retrying...")
    
    def _handle_retrying(self, transfer_id, attempt, max_attempts, error_msg):
        """Update UI when a transfer is being retried"""
        if transfer_id not in self._transfer_displays:
            return
        
        display = self._transfer_displays[transfer_id]
        display['status'] = 'retrying'
        
        color = self._status_colors['retrying']
        display['status_label'].setText(f"Retry {attempt}/{max_attempts}")
        display['status_label'].setStyleSheet(f"font-size: 10px; color: {color}; font-weight: 500;")
        
        chunk_color = color
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
        display['progress_bar'].setFormat(f"Retry {attempt}/{max_attempts} - waiting...")
        display['speed_label'].setText("-")
        display['eta_label'].setText("-")

    def _handle_disk_full(self, error_message):
        """Handle disk full by stopping all active and pending transfers."""
        self.text_console.append(f"\u26a0 {error_message}")

        stopped = 0
        for transfer_id, display in list(self._transfer_displays.items()):
            if display.get('is_active', False):
                display['is_active'] = False
                display['status'] = 'failed'
                display['error_message'] = error_message
                display['status_label'].setText("Disk Full")
                display['status_label'].setStyleSheet(
                    f"font-size: 10px; color: {DARK_THEME['error']}; font-weight: 500;")
                display['progress_bar'].setFormat("Stopped - disk full")
                if transfer_id in self._active_workers:
                    worker = self._active_workers[transfer_id]
                    if hasattr(worker, 'cancel'):
                        worker.cancel()
                stopped += 1

        self._pending_display_transfers.clear()

        self._current_group_id = None

        if stopped > 0:
            self.text_console.append(
                f"Stopped {stopped} transfer(s). Free up disk space and retry.")

        self.update_overall_progress()
        self._update_queue_status_label()
        self._schedule_queue_save()

        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(
            self, "Disk Full",
            "The destination drive has run out of space.\n\n"
            f"All remaining transfers have been stopped ({stopped} active).\n"
            "Free up disk space and retry your transfers."
        )
    
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
        return self.persistence.encrypt_password(password)

    def _decrypt_for_queue(self, encrypted_password):
        return self.persistence.decrypt_password(encrypted_password)
    
    def _save_pending_queue(self):
        """Save pending transfers to disk for restoration"""
        self.persistence.save_pending_queue(self.model._pending_display_transfers)
    
    def _schedule_queue_save(self):
        """Debounced save - wait 1 second after last change"""
        if self._queue_save_timer is None:
            self._queue_save_timer = QTimer(self)
            self._queue_save_timer.setSingleShot(True)
            self._queue_save_timer.timeout.connect(self._save_pending_queue)
        else:
            self._queue_save_timer.stop()
        self._queue_save_timer.start(1000)
    
    def _load_pending_queue(self):
        """Load pending transfers on startup"""
        data = self.persistence.load_pending_queue()
        if not data:
            return 0

        restored = 0
        for item in data:
            self.model._pending_display_transfers.append(item)
            self.model.add_session_waiter(item['transfer_id'], item['hostname'])
            restored += 1

        if restored > 0:
            self.text_console.append(f"Restored {restored} transfers to queue")

        return restored
    
    def register_active_session(self, hostname, session_id):
        """Called when user connects to a host - check for waiting transfers"""
        if not self.model.has_waiters_for_host(hostname):
            return

        waiting = self.model.get_waiting_transfers(hostname)
        for t in waiting:
            t['session_id'] = session_id
            t['status'] = 'queued'
            self.model.remove_session_waiter(t['transfer_id'])

        self._check_and_start_queued()

    def init_ui(self):
        """Initialize the UI layout"""
        if DEBUG:
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
        self.transfer_list.itemDoubleClicked.connect(self._retry_failed_transfer)
        
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
        self.pause_button.setToolTip("Pause all transfers (disabled)")
        self.pause_button.setEnabled(False)
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
        
        if DEBUG:
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

        # (legacy timer setup removed)
        
    def _add_transfer_display_slot(self, args_tuple):
        """Slot for thread-safe transfer display addition (called via signal from background threads)"""
        transfer_id, source_path, dest_path, is_source_remote, is_destination_remote, hostname, port, username, password, command, key, session_id, group_id = args_tuple[:13]
        file_size = args_tuple[13] if len(args_tuple) > 13 else 0
        if DEBUG:
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
            group_id=group_id,
            file_size=file_size
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

    def add_observee(self, observee):
        """Add an observer to be notified when transfers complete. Thread-safe."""
        with self._observees_lock:
            if observee not in self._observees:
                self._observees.append(observee)

    def remove_observee(self, observee):
        """Remove an observer. Thread-safe."""
        with self._observees_lock:
            if observee in self._observees:
                self._observees.remove(observee)

    def notify_observees(self, is_upload=None):
        """Notify all observers that transfers completed. Thread-safe.
        Uses debouncing to prevent excessive refreshing during bulk transfers.
        
        Args:
            is_upload: True=only refresh remote, False=only refresh local,
                       None=refresh all (backward compat)
        """
        if self._refresh_debounce_timer is not None:
            self._refresh_debounce_timer.stop()
        
        from PySide6.QtCore import QTimer
        self._refresh_debounce_timer = QTimer()
        self._refresh_debounce_timer.setSingleShot(True)
        self._refresh_debounce_timer.timeout.connect(
            lambda: self._do_notify_observees(is_upload))
        self._refresh_debounce_timer.start(500)
    
    def _do_notify_observees(self, is_upload=None):
        """Actually notify observers - called after debounce delay"""
        self._refresh_debounce_timer = None
        
        # Copy list under lock to avoid holding lock during callbacks
        with self._observees_lock:
            observees_copy = list(self._observees)
        
        for observee in observees_copy:
            try:
                QTimer.singleShot(
                    0, lambda o=observee, d=is_upload: self._do_refresh(o, d))
            except (AttributeError, RuntimeError):
                pass

    def _do_refresh(self, observee, is_upload=None):
        """Actually perform the refresh - called on main thread"""
        if is_upload is not None:
            is_remote = (hasattr(observee, 'is_remote_browser')
                         and observee.is_remote_browser())
            if is_upload and not is_remote:
                return
            if not is_upload and is_remote:
                return
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
        """Get total number of active transfers"""
        count = 0
        for tid, display in self._transfer_displays.items():
            if display.get('is_active', False):
                count += 1
        return count

    def update_overall_progress(self):
        """Update the overall progress bar based on all active transfers."""
        if not hasattr(self, 'overall_progress_widget'):
            return

        try:
            if self._discovery_active:
                self.overall_progress_widget.setVisible(True)
                self.overall_progress_bar.setRange(0, 0)
                self.overall_progress_bar.setValue(0)
                files_str = f"{self._discovery_files_found:,} files"
                dirs_str = f"{self._discovery_dirs_scanned:,} dirs"
                self.overall_progress_label.setText(f"Scanning: {files_str} found in {dirs_str}...")
                self.header.set_active_count(0)
                self.signal_overall_progress.emit(0, 0.0, 0.0, 0, 0)
                return

            total_bytes = 0
            completed_bytes = 0
            total_files = 0
            completed_files = 0
            total_speed = 0.0
            active_count = 0

            # 1. Process legacy transfers
            for t in self.transfers:
                total_files += 1
                if t.active:
                    active_count += 1
                    total_speed += getattr(t, 'speed_bps', 0.0) or 0.0
                    total_bytes += getattr(t, 'bytes_total', 0) or 0
                    completed_bytes += getattr(t, 'bytes_done', 0) or 0
                elif getattr(t, 'status', '') == 'complete':
                    completed_files += 1
                    tb = getattr(t, 'bytes_total', 0) or 0
                    total_bytes += tb
                    completed_bytes += tb
                else:
                    # Queued or failed
                    total_bytes += getattr(t, 'bytes_total', 0) or 0
                    completed_bytes += getattr(t, 'bytes_done', 0) or 0

            # 2. Process modern transfer displays
            for display in self._transfer_displays.values():
                status = display.get('status')
                total_files += 1
                
                if status == 'complete':
                    completed_files += 1
                    tb = display.get('bytes_total', 0) or 0
                    total_bytes += tb
                    completed_bytes += tb
                else:
                    total_bytes += display.get('bytes_total', 0) or 0
                    completed_bytes += display.get('bytes_done', 0) or 0
                    
                    if display.get('is_active', False) or status == 'transferring':
                        active_count += 1
                        total_speed += display.get('speed_bps', 0) or 0

            if total_files == 0 and active_count == 0:
                self.overall_progress_bar.setRange(0, 100)
                self.overall_progress_bar.setValue(0)
                self.overall_progress_label.setText("No active transfers")
                self.overall_progress_widget.setVisible(False)
                self.header.set_active_count(0)
                self._discovery_total_files = None
                self.signal_overall_progress.emit(0, 0.0, 0.0, 0, 0)
                return

            self.overall_progress_widget.setVisible(True)
            self.overall_progress_bar.setRange(0, 100)
            self.header.set_active_count(active_count)

            group = None
            if self._current_group_id and self._current_group_id in self._transfer_groups:
                group = self._transfer_groups[self._current_group_id]

            if group and group["total_files"] > 0:
                completed = group["completed_files"]
                total = group["total_files"]
                completed_bytes = group.get("completed_bytes", 0)
                total_bytes = group.get("total_bytes", 0)

                if total_bytes > 0:
                    overall_percent = min(99, int((completed_bytes / total_bytes) * 100))
                else:
                    overall_percent = int((completed / total) * 100)

                self.overall_progress_bar.setValue(overall_percent)
                total_speed = 0.0
                for display in self._transfer_displays.values():
                    if display.get('is_active', False):
                        total_speed += display.get('speed_bps', 0) or 0

                parts = [f"Transferring: {completed}/{total} files"]
                if total_bytes > 0:
                    parts.append(f"{self.humanize_bytes(completed_bytes)}/{self.humanize_bytes(total_bytes)}")
                parts.append(f"{overall_percent}%")
                speed_str = self._format_speed(total_speed)
                if speed_str:
                    parts.append(speed_str)
                self.overall_progress_label.setText(" • ".join(parts))

                remaining = max(0, total_bytes - completed_bytes) if total_bytes > 0 else 0
                eta_seconds = self._calc_eta(total_speed, remaining)
                self.signal_overall_progress.emit(overall_percent, total_speed, eta_seconds, completed_bytes, total_bytes)
                return

            if total_bytes > 0:
                overall_percent = int((completed_bytes / total_bytes) * 100)
            elif total_files > 0:
                overall_percent = int((completed_files / total_files) * 100)
            else:
                overall_percent = 0

            overall_percent = max(0, min(100, overall_percent))
            self.overall_progress_bar.setValue(overall_percent)
            
            speed_str = self._format_speed(total_speed)
            bytes_str = f"{self.humanize_bytes(completed_bytes)}/{self.humanize_bytes(total_bytes)}" if total_bytes > 0 else ""
            
            parts = [f"Transferring: {completed_files}/{total_files} files"]
            if bytes_str:
                parts.append(bytes_str)
            parts.append(f"{overall_percent}%")
            if speed_str:
                parts.append(speed_str)
            
            remaining = max(0, total_bytes - completed_bytes)
            eta_seconds = self._calc_eta(total_speed, remaining)
            eta_str = self._format_eta(eta_seconds)
            if eta_str:
                parts.append(eta_str)
            
            self.overall_progress_label.setText(" • ".join(parts))
            self.signal_overall_progress.emit(overall_percent, total_speed, eta_seconds, completed_bytes, total_bytes)

        except (OSError, IOError, RuntimeError, ZeroDivisionError):
            pass

    def _format_speed(self, speed_bps):
        if speed_bps <= 0:
            return ""
        if speed_bps >= 1024 * 1024:
            return f"{speed_bps / (1024 * 1024):.1f} MB/s"
        elif speed_bps >= 1024:
            return f"{speed_bps / 1024:.1f} KB/s"
        else:
            return f"{speed_bps:.0f} B/s"

    def _calc_eta(self, speed_bps, remaining_bytes):
        if speed_bps > 0 and remaining_bytes > 0:
            return remaining_bytes / speed_bps
        return 0.0

    def _format_eta(self, eta_seconds):
        if eta_seconds <= 0:
            return ""
        if eta_seconds < 60:
            return f"{int(eta_seconds)}s remaining"
        elif eta_seconds < 3600:
            return f"{int(eta_seconds / 60)}m remaining"
        else:
            return f"{int(eta_seconds / 3600)}h remaining"

    # ===== Display-only methods for DirectTransferWorker =====
    
    def add_transfer_display(self, transfer_id, source_path, dest_path, 
                             is_source_remote, is_destination_remote, hostname,
                             port, username, password, command, key,
                             session_id=None, group_id=None, priority=0,
                             file_size=0):
        """
        Add a transfer to the queue (not started immediately if at limit).
        """
        import logging
        logger = logging.getLogger('sftp')
        
        try:
            if DEBUG:
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
            effective_group_id = group_id or self._current_group_id
            
            # Discovery file size for local files if not provided
            if file_size <= 0 and not is_source_remote:
                try:
                    file_size = os.path.getsize(source_path)
                except (OSError, IOError):
                    pass

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
                'group_id': effective_group_id,
                'priority': priority,
                'status': status,
                'session_id': session_id,
                'added_time': time.time(),
                'file_size': file_size,
            }
            
            # Update group total bytes if applicable
            if effective_group_id and effective_group_id in self._transfer_groups:
                if file_size > 0:
                    self._transfer_groups[effective_group_id]["total_bytes"] += file_size

            # Insert by priority
            self._insert_pending_by_priority(transfer_info)
            
            # Create UI with appropriate status
            self._create_transfer_display(transfer_info, status)
            
            # Save to disk and try to start (deferred during batch)
            if not self._batch_add_active:
                self._schedule_queue_save()
                if not self._paused:
                    self._check_and_start_queued()
            
            self.update_overall_progress()

        except Exception as e:
            import traceback
            if DEBUG:
                print(f"DEBUG: Error in add_transfer_display: {e}", file=sys.stderr)
                print(traceback.format_exc(), file=sys.stderr)
            self.text_console.append(f"Error adding transfer display: {e}")
    
    def _create_transfer_display(self, transfer_info, status):
        """Create transfer display UI"""
        transfer_id = transfer_info['transfer_id']
        source_path = transfer_info['source_path']
        dest_path = transfer_info['dest_path']
        hostname = transfer_info['hostname']
        file_size = transfer_info.get('file_size', 0)
        
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
            'group_id': transfer_info.get('group_id'),
            'bytes_done': 0,
            'bytes_total': file_size,
            'speed_bps': 0,
            'transfer_info': dict(transfer_info),
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
    
    def _retry_failed_transfer(self, item):
        """Retry a failed transfer on double-click"""
        transfer_id = item.data(Qt.UserRole)
        if not transfer_id or transfer_id not in self._transfer_displays:
            return
        
        display = self._transfer_displays[transfer_id]
        if display['status'] != 'failed':
            return
        
        transfer_info = display.get('transfer_info')
        if not transfer_info:
            return
        
        self.remove_transfer_display(transfer_id)
        
        self.add_transfer_display(
            transfer_id=transfer_info['transfer_id'],
            source_path=transfer_info['source_path'],
            dest_path=transfer_info['dest_path'],
            is_source_remote=transfer_info['is_source_remote'],
            is_destination_remote=transfer_info['is_destination_remote'],
            hostname=transfer_info['hostname'],
            port=transfer_info['port'],
            username=transfer_info['username'],
            password=transfer_info['password'],
            command=transfer_info['command'],
            key=transfer_info.get('key', ''),
            session_id=transfer_info.get('session_id'),
            group_id=transfer_info.get('group_id')
        )
    
    def _get_transfer_menu_config(self):
        prefs = get_preferences()
        items = prefs.get('context_menu_items', {}).get('transfer_queue')
        if not items:
            from sftp_preferences import DEFAULT_PREFERENCES
            items = DEFAULT_PREFERENCES.get('context_menu_items', {}).get('transfer_queue', [])
        return items

    def _show_transfer_context_menu(self, pos):
        """Show context menu for transfer at position"""
        item = self.transfer_list.itemAt(pos)
        if not item:
            return

        transfer_id = item.data(Qt.UserRole)
        if not transfer_id:
            return

        menu = QMenu(self)
        items = self._get_transfer_menu_config()

        is_failed = False
        if transfer_id in self._transfer_displays:
            display = self._transfer_displays[transfer_id]
            if display['status'] == 'failed':
                is_failed = True

        if is_failed and is_visible(items, 'retry'):
            retry_action = menu.addAction("Retry")
            retry_action.triggered.connect(lambda: self._retry_failed_transfer(item))
            menu.addSeparator()

        if is_visible(items, 'priority'):
            priority_menu = menu.addMenu("Priority")
            top_action = priority_menu.addAction("Move to Top")
            up_action = priority_menu.addAction("Move Up")
            down_action = priority_menu.addAction("Move Down")
            bottom_action = priority_menu.addAction("Move to Bottom")

            top_action.triggered.connect(lambda: self._move_transfer(transfer_id, 'top'))
            up_action.triggered.connect(lambda: self._move_transfer(transfer_id, 'up'))
            down_action.triggered.connect(lambda: self._move_transfer(transfer_id, 'down'))
            bottom_action.triggered.connect(lambda: self._move_transfer(transfer_id, 'bottom'))

        if is_visible(items, 'cancel'):
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
        display['bytes_done'] = bytes_done
        display['bytes_total'] = bytes_total
        display['speed_bps'] = speed_bps

        display['progress_bar'].setValue(value)
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

        # Store metrics for overall progress aggregation
        display['bytes_done'] = bytes_done
        display['bytes_total'] = bytes_total
        display['speed_bps'] = speed_bps

        self.update_overall_progress()
    
    def mark_transfer_complete(self, transfer_id):
        """Mark a display transfer as complete"""
        if transfer_id not in self._transfer_displays:
            return

        display = self._transfer_displays[transfer_id]
        display['is_active'] = False
        display['status'] = 'complete'
        # Ensure progress is 100% on completion
        display['bytes_done'] = display.get('bytes_total', 0)
        display['status_label'].setText("Done")
        display['progress_bar'].setValue(100)
        display['progress_bar'].setFormat("100% • Complete")
        display['eta_label'].setText("-")

        file_name = os.path.basename(display['source'])
        self.text_console.append(f"Transfer complete: {file_name}")

        self.signal_transfer_completed.emit(0, f"Transfer complete: {file_name}")

        group_id = display.get('group_id')
        if group_id and group_id in self._transfer_groups:
            self._transfer_groups[group_id]["completed_files"] += 1
            if self._transfer_groups[group_id]["completed_files"] >= self._transfer_groups[group_id]["total_files"]:
                if self._current_group_id == group_id:
                    self._current_group_id = None
                del self._transfer_groups[group_id]

        self.update_overall_progress()

        from sftp_preferences import get_preferences
        prefs = get_preferences()
        if prefs.get_bool("clear_completed_on_complete", False):
            QTimer.singleShot(500, self.clear_completed)
        
        self.notify_observees(
            is_upload=not display.get('is_source_remote', True))
        self._check_and_start_queued()

    def mark_transfer_failed(self, transfer_id, error_message):
        """Mark a display transfer as failed"""
        if transfer_id not in self._transfer_displays:
            return

        display = self._transfer_displays[transfer_id]
        display['is_active'] = False
        display['status'] = 'failed'
        display['error_message'] = error_message
        display['status_label'].setText("Failed")
        display['status_label'].setStyleSheet(f"font-size: 10px; color: {DARK_THEME['error']}; font-weight: 500;")
        display['progress_bar'].setFormat("Failed")
        display['progress_bar'].setStyleSheet(f"QProgressBar::chunk {{ background-color: {DARK_THEME['error']}; }}")

        file_name = os.path.basename(display['source'])
        self.text_console.append(f"Transfer failed: {file_name} - {error_message}")

        self.signal_transfer_error.emit(0, error_message)

        group_id = display.get('group_id')
        if group_id and group_id in self._transfer_groups:
            self._transfer_groups[group_id]["completed_files"] += 1
            if self._transfer_groups[group_id]["completed_files"] >= self._transfer_groups[group_id]["total_files"]:
                if self._current_group_id == group_id:
                    self._current_group_id = None
                del self._transfer_groups[group_id]

        self.update_overall_progress()

        from sftp_preferences import get_preferences
        prefs = get_preferences()
        if prefs.get_bool("clear_completed_on_complete", False):
            QTimer.singleShot(500, self.clear_completed)
        
        self.notify_observees(
            is_upload=not display.get('is_source_remote', True))
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

    def _handle_conflict(self, transfer_id, dest_path, dest_type):
        """Handle file conflict - queue prompt so only one dialog shows at a time"""
        # Find the worker and group_id
        worker = None
        group_id = None
        
        # Check active workers (DirectTransferWorker)
        if transfer_id in self._active_workers:
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
            
            # Check active workers (DirectTransferWorker)
            if transfer_id in self._active_workers:
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

    def stop_all_transfers(self):
        """Cancel all active transfers"""
        try:
            # Stop all active display-based transfers (DirectTransferWorker)
            self.stop_all_display_transfers()
            
            # Cancel any active traversal or deletion workers in browser observees
            with self._observees_lock:
                for observee in self._observees:
                    if hasattr(observee, '_current_traversal_worker') and observee._current_traversal_worker:
                        observee._current_traversal_worker.cancel()
                        observee._current_traversal_worker = None
                    if hasattr(observee, '_deletion_worker') and observee._deletion_worker:
                        observee._deletion_worker.cancel()
            
            # Clear pending group assignments
            self._pending_group_assignments.clear()
            
            self.text_console.append("All transfers stopped")
            
        except (OSError, IOError, RuntimeError) as e:
            self.text_console.append(f"Error stopping transfers: {e}")
    
    def clear_completed(self):
        """Remove completed/cancelled/error transfers"""
        try:
            transfers_to_remove = []
            
            # Check display-only transfers
            for tid, display in list(self._transfer_displays.items()):
                if not display.get('is_active', False):
                    status_text = display['status_label'].text() if 'status_label' in display else ""
                    if status_text in ["Done", "Failed", "Stopped", "Cancelled"]:
                        transfers_to_remove.append(tid)
            
            for transfer_id in transfers_to_remove:
                if transfer_id in self._transfer_displays:
                    self.remove_transfer_display(transfer_id)
                
        except (OSError, IOError, RuntimeError) as e:
            self.text_console.append(f"Error clearing completed transfers: {e}")
    
    def cleanup(self):
        """Cleanup resources when widget is destroyed"""
        try:
            if hasattr(self, 'thread_pool'):
                self.thread_pool.waitForDone(2000)
        except (OSError, IOError, RuntimeError) as e:
            logger.debug(f"Error in cleanup: {e}")
