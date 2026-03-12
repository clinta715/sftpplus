from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                            QListWidget, QTextEdit, QProgressBar, QSizePolicy,
                            QLabel, QListWidgetItem, QScrollArea, QFrame, QCheckBox)
from sftp_qt_compat import Qt  # Use compatibility layer for Qt enums
from PyQt6.QtCore import QThreadPool, QTimer, QMutex, QMutexLocker, pyqtSignal
from icecream import ic
import inspect
import os
import json
import queue
import time
import stat

from sftp_downloadworkerclass import Transfer, DownloadWorker, SFTPJob, sftp_queue, clear_sftp_queue, response_queues, response_queues_lock
from sftp_theme import (BUTTON_STYLE_DARK, LIST_WIDGET_STYLE_DARK, PROGRESS_BAR_STYLE_DARK,
                        TEXT_EDIT_STYLE_DARK, DARK_THEME)
from sftp_preferences import get_preferences
from sftp_transfer_handler import cancel_active_directory_transfer


QUEUE_FILE_PATH = os.path.join(os.path.expanduser('~'), '.sftp_client_transfer_queue.json')


class TransferQueueWidget(QWidget):
    """
    Transfer queue widget for integration into main window.
    
    This is a QWidget version of BackgroundThreadWindow that can be embedded
    as a tab in the main application window instead of being a separate window.
    
    Features:
    - Persistent transfer history (doesn't disappear on completion)
    - Scrollable list to view all transfers
    - Hostname indicator for each transfer
    - Full-width progress bars
    """
    
    # Signals for transfer events
    signal_transfer_started = pyqtSignal(int, str)  # (count, message)
    signal_transfer_completed = pyqtSignal(int, str)  # (count, message)
    signal_transfer_error = pyqtSignal(int, str)  # (count, message)
    signal_transfer_progress = pyqtSignal(int, int, float, float)  # (transfer_id, percent, speed_bps, eta_sec)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.queue_items = []
        self.active_transfers = 0
        self.transfers = []
        self._observees = []
        self._observees_lock = QMutex()  # THREAD SAFETY: Lock for observee list
        self.total_queue_items = 0
        
        # Thread safety locks
        self._transfer_lock = QMutex()
        self._released_transfers = set()
        self._active_transfers_lock = QMutex()
        
        # Debounce timer for refresh - prevents excessive refreshing during bulk transfers
        self._refresh_debounce_timer = None
        
        self.init_ui()

    def init_ui(self):
        """Initialize the UI layout"""
        # Main layout
        self.main_layout = QVBoxLayout()
        self.main_layout.setSpacing(4)
        self.main_layout.setContentsMargins(8, 8, 8, 8)
        
        # Header
        header = QLabel("Transfers")
        header.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {DARK_THEME['text_primary']};")
        self.main_layout.addWidget(header)
        
        # Transfer list widget (container for transfer items)
        self.transfer_list = QListWidget()
        self.transfer_list.setStyleSheet(LIST_WIDGET_STYLE_DARK)
        self.transfer_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.transfer_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.transfer_list.setMinimumHeight(150)
        
        # Set the list as the scroll area widget
        self.main_layout.addWidget(self.transfer_list, stretch=1)

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
        
        # Preferences checkboxes
        prefs = get_preferences()
        
        self.clear_on_complete_checkbox = QCheckBox("Auto-clear completed")
        self.clear_on_complete_checkbox.setToolTip("Automatically clear completed transfers when they finish")
        self.clear_on_complete_checkbox.setChecked(prefs.get_bool("clear_completed_on_complete", False))
        self.clear_on_complete_checkbox.stateChanged.connect(self._on_clear_on_complete_changed)
        
        self.overwrite_checkbox = QCheckBox("Overwrite files")
        self.overwrite_checkbox.setToolTip("Overwrite existing files during transfer without prompting")
        self.overwrite_checkbox.setChecked(prefs.get_bool("overwrite_on_transfer", False))
        self.overwrite_checkbox.stateChanged.connect(self._on_overwrite_changed)
        
        self.focus_transfers_checkbox = QCheckBox("Focus Transfers tab")
        self.focus_transfers_checkbox.setToolTip("Automatically switch to Transfers tab when transfers start")
        self.focus_transfers_checkbox.setChecked(prefs.get_bool("focus_transfers_on_start", True))
        self.focus_transfers_checkbox.stateChanged.connect(self._on_focus_transfers_changed)
        
        self.control_layout.addWidget(self.pause_button)
        self.control_layout.addWidget(self.stop_button)
        self.control_layout.addWidget(self.clear_on_complete_checkbox)
        self.control_layout.addWidget(self.overwrite_checkbox)
        self.control_layout.addWidget(self.focus_transfers_checkbox)
        self.control_layout.addStretch(1)
        self.control_layout.addWidget(self.clear_button)
        
        self.main_layout.addLayout(self.control_layout)

        # Add text console with dynamic width based on window size
        self.text_console = QTextEdit()
        self.text_console.setReadOnly(True)
        self.text_console.setMaximumHeight(80)
        self.text_console.setStyleSheet(TEXT_EDIT_STYLE_DARK)
        self.main_layout.addWidget(self.text_console)
        
        # Ensure console width is reasonable but not constraining
        self.text_console.setMinimumWidth(300)
        self.text_console.setSizePolicy(
            QSizePolicy.Policy.Expanding, 
            QSizePolicy.Policy.Fixed
        )

        # Set the main layout
        self.setLayout(self.main_layout)

        # Initialize thread pool
        self.thread_pool = QThreadPool.globalInstance()
        # Ensure thread pool can handle the maximum number of concurrent transfers
        # We set it slightly higher than MAX_TRANSFERS to allow for overhead
        if self.thread_pool.maxThreadCount() < 20:
            self.thread_pool.setMaxThreadCount(20)

        # Setup timers
        self._setup_timers()

    def _on_clear_on_complete_changed(self, state):
        """Handle clear on complete checkbox change"""
        prefs = get_preferences()
        prefs.set_bool("clear_completed_on_complete", bool(state))

    def _on_overwrite_changed(self, state):
        """Handle overwrite checkbox change"""
        prefs = get_preferences()
        prefs.set_bool("overwrite_on_transfer", bool(state))

    def _on_focus_transfers_changed(self, state):
        """Handle focus transfers checkbox change"""
        prefs = get_preferences()
        prefs.set_bool("focus_transfers_on_start", bool(state))

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
        from PyQt6.QtCore import QTimer
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
            except (AttributeError, RuntimeError) as e:
                ic("Error queuing observer refresh", observee, e)
    
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
            ic("Observee", observee, "does not implement 'get_files' method.", ae)
        except (AttributeError, RuntimeError) as e:
            ic("An error occurred while notifying observee", observee, e)

    def update_overall_progress(self):
        """Update the overall progress - no longer displayed in compact UI"""
        pass

    def check_and_start_transfers(self):
        """Check for new transfers in queue and start them"""
        try:
            self._timer_tick_count = getattr(self, '_timer_tick_count', 0) + 1
            
            # Fix active transfers counter
            with QMutexLocker(self._transfer_lock):
                actual_active = len([t for t in self.transfers if t.active])
                if self.active_transfers != actual_active:
                    ic(f"Fixing active_transfers: {self.active_transfers} -> {actual_active}")
                    self.active_transfers = actual_active
            
            # Check if we've reached max transfers
            prefs = get_preferences()
            max_concurrent = prefs.get("max_concurrent_transfers", 8)
            with QMutexLocker(self._active_transfers_lock):
                if self.active_transfers >= max_concurrent:
                    # Log every 50 ticks (5 seconds) to avoid spam
                    if self._timer_tick_count % 50 == 0:
                        ic(f"Max transfers reached: {self.active_transfers}/{max_concurrent}")
                    return
            
            # Check if queue has items
            queue_size = sftp_queue.qsize()
            if queue_size == 0:
                return
            
            ic(f"Queue has {queue_size} items, active_transfers={self.active_transfers}")

            # Get job from queue with timeout (thread-safe, avoids race condition)
            try:
                job = sftp_queue.get_nowait()
            except Exception as e:
                ic(f"Queue get error: {e}")
                return  # Queue is empty or error
            
            if not job:
                ic("Got null job from queue")
                return
            
            # Debug: log job details
            ic(f"TransferQueueWidget: Processing job {job.job_id}, command={job.command}")
                
            # Validate job
            if not hasattr(job, "job_id"):
                ic("Job missing 'job_id' attribute:", job)
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
            ic(e)
            self.text_console.append(f"Error starting transfer: {e}")

    def start_transfer(self, transfer_id, job_source, job_destination, 
                       is_source_remote, is_destination_remote, hostname, 
                       port, username, password, command, key):
        """Start a new transfer"""
        try:
            if not transfer_id:
                return
                
            # Check if transfer already exists
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
                    lambda tid, val, speed, eta: self.update_progress(tid, val, speed, eta),
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
            
            # Add to transfers list
            with QMutexLocker(self._transfer_lock):
                self.transfers.append(new_transfer)
            
            # Start the worker
            self.thread_pool.start(new_transfer.download_worker)
            
            # Emit transfer started signal
            self.signal_transfer_started.emit(1, f"Transfer started: {job_source}")
            
            with QMutexLocker(self._active_transfers_lock):
                self.active_transfers += 1
            self.update_overall_progress()
            
        except (OSError, IOError, RuntimeError) as e:
            self.text_console.append(f"Failed to start transfer: {e}")

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
            self.transfers = [t for t in self.transfers if t.transfer_id != transfer_id]
            
        except (OSError, IOError, RuntimeError):
            pass

    def _release_transfer(self, transfer_id):
        """Release transfer resources"""
        ic(f"_release_transfer called for {transfer_id}")
        try:
            with QMutexLocker(self._transfer_lock):
                if transfer_id in self._released_transfers:
                    ic(f"_release_transfer: {transfer_id} already released")
                    return
                self._released_transfers.add(transfer_id)

            with QMutexLocker(self._active_transfers_lock):
                old_count = self.active_transfers
                self.active_transfers = max(self.active_transfers - 1, 0)
                ic(f"_release_transfer: active_transfers {old_count} -> {self.active_transfers}")

            self.remove_queue_item(transfer_id)
            self.update_overall_progress()
            
        except (OSError, IOError, RuntimeError) as e:
            print(f"Error releasing transfer {transfer_id}: {e}")

    def transfer_finished(self, transfer_id):
        """Handle transfer completion"""
        ic(f"transfer_finished called for {transfer_id}")
        try:
            if not transfer_id:
                return
                
            transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)
            if not transfer:
                ic(f"transfer_finished: transfer {transfer_id} not found")
                return

            transfer.active = False
            
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
            print(f"Error in transfer_error handler: {e}")

    def _handle_worker_message(self, transfer_id, message):
        """Handle messages from worker threads"""
        try:
            if any(keyword in message.lower() for keyword in ['error', 'failed', 'exception', 'timeout']):
                self.transfer_error(transfer_id, message)
            else:
                if hasattr(self, 'text_console'):
                    self.text_console.append(f"Transfer {transfer_id}: {message}")
        except (OSError, IOError, RuntimeError) as e:
            print(f"Error handling worker message: {e}")

    def update_progress(self, transfer_id, value, speed_bps=None, eta_sec=None):
        """Update transfer progress"""
        try:
            if not transfer_id:
                return
            
            transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)
            if not transfer or not transfer.active:
                return

            speed = speed_bps if speed_bps is not None else 0.0
            eta = eta_sec if eta_sec is not None else 0.0
            self.signal_transfer_progress.emit(transfer_id, value, speed, eta)
            
            try:
                if transfer.progress_bar:
                    transfer.progress_bar.setValue(value)

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

        except (OSError, IOError, RuntimeError):
            pass

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
            # Cancel any active directory traversal
            cancel_active_directory_transfer()
            
            # Clear the transfer queue to stop new transfers from starting
            clear_sftp_queue()
            
            # Stop all active transfers
            for transfer in self.transfers:
                if transfer.active:
                    if hasattr(transfer.download_worker, '_stop_flag'):
                        transfer.download_worker._stop_flag = True
                    if hasattr(transfer.download_worker, 'stop_transfer'):
                        transfer.download_worker.stop_transfer()
            
            self.text_console.append("Cancelling all transfers and clearing queue...")
            
        except (OSError, IOError, RuntimeError) as e:
            self.text_console.append(f"Error stopping transfers: {e}")
    
    def clear_completed(self):
        """Remove completed/cancelled/error transfers"""
        try:
            transfers_to_remove = []
            
            for transfer in self.transfers[:]:
                status_text = transfer.status_label.text() if transfer.status_label else ""
                if (not transfer.active or 
                    status_text in ["✓ Done", "✗ Cancelled", "✗ Error", "✗ Failed"] or
                    "Error:" in status_text):
                    transfers_to_remove.append(transfer.transfer_id)
            
            for transfer_id in transfers_to_remove:
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
            ic(f"Error clearing all transfers: {e}")

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
            print(f"Error in cleanup: {e}")
    
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
                            ic(f"Skipping queued job with empty path: src={src!r}, dst={dst!r}")
                            continue
                        pending_jobs.append({
                            'source_path': src,
                            'is_source_remote': getattr(job, 'is_source_remote', False),
                            'destination_path': dst,
                            'is_destination_remote': getattr(job, 'is_destination_remote', False),
                            'hostname': getattr(job, 'hostname', ''),
                            'username': getattr(job, 'username', ''),
                            'password': getattr(job, 'password', ''),
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
                            pending_jobs.append({
                                'source_path': src,
                                'is_source_remote': getattr(worker, 'is_source_remote', False),
                                'destination_path': dst,
                                'is_destination_remote': getattr(worker, 'is_destination_remote', False),
                                'hostname': getattr(worker, 'hostname', ''),
                                'username': getattr(worker, 'username', ''),
                                'password': getattr(worker, 'password', ''),
                                'port': getattr(worker, 'port', 22),
                                'command': getattr(worker, 'command', 'download'),
                                'job_id': transfer.transfer_id,
                                'key': getattr(worker, 'temp_key', None),
                                'status': 'paused' if getattr(transfer, 'paused', False) else 'active'
                            })
            
            if pending_jobs:
                old_umask = os.umask(0o077)
                try:
                    with open(QUEUE_FILE_PATH, 'w') as f:
                        json.dump(pending_jobs, f, indent=2)
                    os.chmod(QUEUE_FILE_PATH, stat.S_IRUSR | stat.S_IWUSR)
                    ic(f"Saved {len(pending_jobs)} pending transfers to {QUEUE_FILE_PATH}")
                finally:
                    os.umask(old_umask)
            else:
                if os.path.exists(QUEUE_FILE_PATH):
                    try:
                        os.unlink(QUEUE_FILE_PATH)
                    except OSError:
                        pass
            
        except (OSError, IOError, json.JSONEncodeError) as e:
            ic(f"Error saving pending transfers: {e}")
    
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
                        ic(f"Skipping job with empty path: src={src!r}, dst={dst!r}")
                        continue
                    
                    job = SFTPJob(
                        source_path=src,
                        is_source_remote=job_data.get('is_source_remote', False),
                        destination_path=dst,
                        is_destination_remote=job_data.get('is_destination_remote', False),
                        hostname=job_data.get('hostname', ''),
                        username=job_data.get('username', ''),
                        password=job_data.get('password', ''),
                        port=job_data.get('port', 22),
                        command=job_data.get('command', 'download'),
                        job_id=job_data.get('job_id'),
                        key=job_data.get('key')
                    )
                    
                    sftp_queue.put(job)
                    restored_count += 1
                    
                except (KeyError, TypeError) as e:
                    ic(f"Error restoring job: {e}")
                    continue
            
            try:
                os.unlink(QUEUE_FILE_PATH)
            except OSError:
                pass
            
            if restored_count > 0:
                self.text_console.append(f"Restored {restored_count} pending transfer(s) from previous session")
                ic(f"Restored {restored_count} pending transfers")
            
            return restored_count
            
        except (OSError, IOError, json.JSONDecodeError) as e:
            ic(f"Error loading pending transfers: {e}")
            return 0
