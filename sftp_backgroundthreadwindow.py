from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, 
                            QPushButton, QListWidget, QTextEdit, QProgressBar, QSizePolicy, 
                            QLabel, QGroupBox, QListWidgetItem)
from PyQt5.QtCore import Qt, QThreadPool, QTimer, QMutex, QMutexLocker
from icecream import ic
import os
import time

from sftp_downloadworkerclass import Transfer, DownloadWorker, sftp_queue_get, sftp_queue_isempty
from sftp_theme import (BUTTON_STYLE_DARK, LIST_WIDGET_STYLE_DARK, 
                        PROGRESS_BAR_STYLE_DARK, DARK_THEME)

MAX_TRANSFERS = 2

class BackgroundThreadWindow(QMainWindow):
    def __init__(self):
        super(BackgroundThreadWindow, self).__init__()
        self.queue_items = []
        self.active_transfers = 0
        self.transfers = []
        self.observees = []
        self.total_queue_items = 0
        self.transfer_finish_times = {}
        
        # Thread safety locks
        self._transfer_lock = QMutex()
        self._released_transfers = set()
        self._active_transfers_lock = QMutex()
        self._released_transfers = set()  # Initialize this early
        self.transfer_finish_times = {}  # Track when transfers completed

        self.init_ui()
        
        # Set a fixed size for the window
        self.setFixedSize(400, 500)  # Adjust width and height as needed

    def init_ui(self):
        size_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        size_policy.setHorizontalStretch(1)
        size_policy.setVerticalStretch(1)

        self.layout = QVBoxLayout()
        self.layout.setSpacing(10)
        self.layout.setContentsMargins(10, 10, 10, 10)

        # Add overall queue progress bar
        self.overall_progress_layout = QHBoxLayout()
        self.overall_progress_label = QLabel("Overall Progress:")
        self.overall_progress_label.setStyleSheet("font-weight: bold;")
        
        self.overall_progress_bar = QProgressBar()
        self.overall_progress_bar.setRange(0, 100)
        self.overall_progress_bar.setValue(0)
        self.overall_progress_bar.setStyleSheet(PROGRESS_BAR_STYLE_DARK)
        
        self.overall_progress_layout.addWidget(self.overall_progress_label)
        self.overall_progress_layout.addWidget(self.overall_progress_bar)
        self.layout.addLayout(self.overall_progress_layout)

        # Add transfer list
        self.transfer_list = QListWidget()
        self.transfer_list.setStyleSheet(LIST_WIDGET_STYLE_DARK)
        self.transfer_list.setMaximumHeight(250)
        self.transfer_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.layout.addWidget(self.transfer_list)

        # Add control buttons
        self.control_layout = QHBoxLayout()
        self.pause_button = QPushButton("Pause All")
        self.pause_button.setStyleSheet(BUTTON_STYLE_DARK)
        self.pause_button.clicked.connect(self.toggle_pause_all)
        self.control_layout.addWidget(self.pause_button)

        self.clear_button = QPushButton("Clear Completed")
        self.clear_button.setStyleSheet(BUTTON_STYLE_DARK)
        self.clear_button.clicked.connect(self.clear_completed)
        self.control_layout.addWidget(self.clear_button)
        self.layout.addLayout(self.control_layout)

        # Add text console
        self.text_console = QTextEdit()
        self.text_console.setReadOnly(True)
        self.text_console.setMaximumHeight(100)
        self.layout.addWidget(self.text_console)

        central_widget = QWidget()
        central_widget.setLayout(self.layout)
        self.setCentralWidget(central_widget)

        self.thread_pool = QThreadPool.globalInstance()

        # Setup a QTimer to periodically check the queue
        self.check_queue_timer = QTimer(self)
        self.check_queue_timer.timeout.connect(self.check_and_start_transfers)
        self.check_queue_timer.start(100)  # Check every 100 ms
        
        # Add cleanup timer for old completed transfers
        self.cleanup_timer = QTimer(self)
        self.cleanup_timer.timeout.connect(self.cleanup_old_transfers)
        self.cleanup_timer.start(2000)  # Clean up every 2 seconds

    def cleanup_old_transfers(self):
        """Automatically remove completed/cancelled transfers that are at least 2 seconds old"""
        current_time = time.time()
        transfers_to_cleanup = []
        
        # Thread-safe access to transfers list
        with QMutexLocker(self._transfer_lock):
            for transfer in self.transfers[:]:
                if not transfer.active:
                    # Record finish time if not already recorded
                    if transfer.transfer_id not in self.transfer_finish_times:
                        self.transfer_finish_times[transfer.transfer_id] = current_time
                    else:
                        # Check if it's been at least 2 seconds since inactive
                        finish_time = self.transfer_finish_times[transfer.transfer_id]
                        if current_time - finish_time >= 2.0:
                            transfers_to_cleanup.append(transfer.transfer_id)
        
        # Clean up the transfers
        for transfer_id in transfers_to_cleanup:
            self.cleanup_transfer(transfer_id)
            # Thread-safe removal from finish times dictionary
            with QMutexLocker(self._transfer_lock):
                if transfer_id in self.transfer_finish_times:
                    del self.transfer_finish_times[transfer_id]
                
    def closeEvent(self, event):
        """Handle window close event - properly cleanup all transfers"""
        try:
            # Stop timers first
            if hasattr(self, 'check_queue_timer'):
                self.check_queue_timer.stop()
            if hasattr(self, 'cleanup_timer'):
                self.cleanup_timer.stop()
            
            # Force reset of all transfer state
            with QMutexLocker(self._transfer_lock):
                self.transfers = []
            with QMutexLocker(self._active_transfers_lock):
                self.active_transfers = 0
            self._released_transfers.clear()
            self.transfer_finish_times.clear()
            
            # Cancel all active transfers
            for transfer in self.transfers[:]:
                self.cancel_transfer(transfer.transfer_id)
            
            # Wait for threads to finish
            if hasattr(self, 'thread_pool'):
                self.thread_pool.waitForDone(3000)
            event.accept()
        except Exception as e:
            print(f"Error in BackgroundThreadWindow close: {e}")
            event.accept()
        
    def add_queue_item(self, item, transfer_id):
        """Add item to queue with transfer_id as unique identifier"""
        queue_item = {'path': item, 'transfer_id': transfer_id}
        self.queue_items.append(queue_item)
        self.total_queue_items = len(self.queue_items)
        self.update_overall_progress()

    def remove_queue_item(self, transfer_id):
        """Remove item by transfer_id instead of path"""
        self.queue_items = [item for item in self.queue_items 
                        if item['transfer_id'] != transfer_id]
        self.total_queue_items = len(self.queue_items)
        self.update_overall_progress()

    def add_observee(self, observee):
        if observee not in self.observees:
            self.observees.append(observee)
        else:
            ic("Observee already exists:", observee)

    def remove_observee(self, observee):
        if observee in self.observees:
            self.observees.remove(observee)

    def notify_observees(self):
        for observee in self.observees:
            try:
                observee.get_files()
            except AttributeError as ae:
                ic("Observee", observee, "does not implement 'get_files' method.", ae)
            except Exception as e:
                ic("An error occurred while notifying observee", observee, e)

    def update_overall_progress(self):
        if self.total_queue_items > 0:
            progress = int((self.active_transfers / self.total_queue_items) * 100)
        else:
            progress = 0
        self.overall_progress_bar.setValue(progress)

    def scroll_to_bottom(self):
        vertical_scroll_bar = self.text_console.verticalScrollBar()
        vertical_scroll_bar.setValue(vertical_scroll_bar.maximum())

    def check_and_start_transfers(self):
        """Check for new transfers in queue and start them"""
        try:
            # Debug: Check current state
            with QMutexLocker(self._transfer_lock):
                actual_active = len([t for t in self.transfers if t.active])
                if self.active_transfers != actual_active:
                    # Fix the counter
                    self.active_transfers = actual_active
            
            # Thread-safe check of active transfers count
            with QMutexLocker(self._active_transfers_lock):
                if self.active_transfers >= MAX_TRANSFERS:
                    return

            # Check if queue is empty
            if sftp_queue_isempty():
                return

            # Get job from queue with error handling
            try:
                job = sftp_queue_get()
                if not job:
                    return
            except Exception as e:
                self.text_console.append(f"Error getting job from queue: {e}")
                return
                
            # Validate job has required attributes
            if not hasattr(job, "job_id"):
                ic("Job missing 'jobid' attribute:", job)
                self.text_console.append(f"Invalid job structure: {job}")
                return

            # Handle end command
            if hasattr(job, "command") and job.command == "end":
                self.text_console.append("Received end command, stopping queue processing")
                # Reset all counters on end command
                with QMutexLocker(self._active_transfers_lock):
                    self.active_transfers = 0
                return

            # Validate all required job attributes before starting transfer
            required_attrs = ["job_id", "source_path", "destination_path", "is_source_remote", 
                            "is_destination_remote", "hostname", "port", "username", 
                            "password", "command"]
            
            missing_attrs = [attr for attr in required_attrs if not hasattr(job, attr)]
            if missing_attrs:
                self.text_console.append(f"Error: Job missing attributes: {missing_attrs}")
                return

            # Start the transfer with validated job
            self.start_transfer(
                job.job_id, job.source_path, job.destination_path,
                job.is_source_remote, job.is_destination_remote,
                job.hostname, job.port, job.username, job.password, job.command, job.key
            )

        except Exception as e:
            ic(e)
            self.text_console.append(f"Error starting transfer: {e}")
            # Debug: Print job details
            if 'job' in locals():
                self.text_console.append(f"DEBUG: Job details - ID:{getattr(job, 'job_id', 'N/A')}, Command:{getattr(job, 'command', 'N/A')}, Source:{getattr(job, 'source_path', 'N/A')}")

    def start_transfer(self, transfer_id, job_source, job_destination, is_source_remote, is_destination_remote, hostname, port, username, password, command, key):
        """Start a new transfer with proper error handling"""
        try:
            # Validate transfer_id
            if not transfer_id:
                return
                
            # Check if transfer already exists
            existing_transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)
            if existing_transfer:
                return
            
            # Create list item
            item = QListWidgetItem()
            item.setData(Qt.UserRole, transfer_id)
            
            # Create widget for the item
            widget = QWidget()
            layout = QVBoxLayout()
            layout.setContentsMargins(5, 5, 5, 5)
            
            # File name
            file_label = QLabel(os.path.basename(job_source))
            file_label.setStyleSheet("font-weight: bold;")
            
            # Progress bar
            progress_bar = QProgressBar()
            progress_bar.setRange(0, 100)
            progress_bar.setValue(0)
            progress_bar.setStyleSheet(f"""
                QProgressBar {{
                    border: 1px solid {DARK_THEME['border']};
                    border-radius: 3px;
                    height: 15px;
                }}
                QProgressBar::chunk {{
                    background-color: {DARK_THEME['accent_green']};
                    width: 10px;
                }}
            """)
            
            # Status info
            info_layout = QHBoxLayout()
            speed_label = QLabel("Speed: -")
            eta_label = QLabel("ETA: -")
            status_label = QLabel("Queued")
            
            info_layout.addWidget(speed_label)
            info_layout.addWidget(eta_label)
            info_layout.addWidget(status_label)
            
            # Control buttons
            button_layout = QHBoxLayout()
            pause_button = QPushButton("Pause")
            pause_button.setStyleSheet(BUTTON_STYLE_DARK)
            pause_button.clicked.connect(lambda checked, tid=transfer_id: self.toggle_pause_transfer(tid))        
            cancel_button = QPushButton("Cancel")
            cancel_button.setStyleSheet(BUTTON_STYLE_DARK)
            cancel_button.clicked.connect(lambda checked, tid=transfer_id: self.cancel_transfer(tid))        
            button_layout.addWidget(pause_button)
            button_layout.addWidget(cancel_button)
            
            # Add widgets to layout
            layout.addWidget(file_label)
            layout.addWidget(progress_bar)
            layout.addLayout(info_layout)
            layout.addLayout(button_layout)
            
            widget.setLayout(layout)
            item.setSizeHint(widget.sizeHint())
            
            # Add to list
            self.transfer_list.addItem(item)
            self.transfer_list.setItemWidget(item, widget)
            
            # Create download worker
            download_worker = DownloadWorker(transfer_id, job_source, job_destination, 
                                           is_source_remote, is_destination_remote,
                                           hostname, port, username, password, command,key)
            
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
                pause_button=pause_button,
                list_item=item
            )

            # Connect signals with proper error handling
            if hasattr(download_worker, 'signals'):
                download_worker.signals.progress.connect(
                    lambda tid, val, speed, eta: self.update_progress(tid, val, speed, eta),
                    Qt.QueuedConnection
                )
                download_worker.signals.finished.connect(
                    lambda tid: self.transfer_finished(tid),
                    Qt.QueuedConnection
                )
                # Connect message signal instead of error signal for error handling
                download_worker.signals.message.connect(
                    lambda tid, msg: self._handle_worker_message(tid, msg),
                    Qt.QueuedConnection
                )
            
            # Thread-safe addition to transfers list and counter update
            with QMutexLocker(self._transfer_lock):
                self.transfers.append(new_transfer)
            
            # Start the download worker in the thread pool
            self.thread_pool.start(new_transfer.download_worker)
            
            with QMutexLocker(self._active_transfers_lock):
                self.active_transfers += 1
            self.update_overall_progress()
            
        except Exception as e:
            self.text_console.append(f"Failed to start transfer: {e}")

    def cancel_transfer(self, transfer_id):
        """Properly cancel a transfer with comprehensive error handling"""
        try:
            if not transfer_id:
                return
                
            transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)
            if not transfer:
                return
            
            # Stop the worker first
            if transfer.download_worker:
                try:
                    transfer.download_worker.stop_transfer()
                except Exception as e:
                    pass            
            # Disconnect all signals to prevent further emissions
            if hasattr(transfer.download_worker, 'signals'):
                try:
                    transfer.download_worker.signals.progress.disconnect()
                    transfer.download_worker.signals.finished.disconnect()
                    transfer.download_worker.signals.message.disconnect()
                except (RuntimeError, TypeError) as e:
                    # Signals may already be disconnected
                    pass

            # Mark as inactive
            transfer.active = False
            
            # Update UI safely
            try:
                if transfer.status_label:
                    transfer.status_label.setText("Cancelled")
                if transfer.progress_bar:
                    transfer.progress_bar.setStyleSheet(f"""
                        QProgressBar {{
                            border: 1px solid {DARK_THEME['border']};
                            border-radius: 3px;
                            height: 15px;
                        }}
                        QProgressBar::chunk {{
                            background-color: {DARK_THEME['error']};
                            width: 10px;
                        }}
                    """)
            except RuntimeError as e:
                pass

            # Release transfer resources
            self._release_transfer(transfer_id)
            
            # Schedule cleanup after a short delay to ensure worker has stopped
            QTimer.singleShot(5000, lambda: self.cleanup_transfer(transfer_id))
            
            # Check for more transfers to start
            QTimer.singleShot(500, self.check_and_start_transfers)
            
        except Exception as e:
            self.text_console.append(f"Error cancelling transfer: {e}")

    def cleanup_transfer(self, transfer_id):
        """Clean up transfer UI elements and data with error handling"""
        try:
            if not transfer_id:
                return
                
            transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)
            if not transfer:
                return
                
            # Remove from UI - handle potential race conditions
            try:
                if transfer.list_item:
                    row = self.transfer_list.row(transfer.list_item)
                    if row >= 0:
                        self.transfer_list.takeItem(row)
            except (RuntimeError, ValueError) as e:
                # Item may have already been removed
                pass

            # Clean up references
            self.transfers = [t for t in self.transfers if t.transfer_id != transfer_id]
            
        except Exception as e:
            pass

    def _release_transfer(self, transfer_id):
        """Release transfer resources and update counters"""
        try:
            # Thread-safe check and add to released transfers
            with QMutexLocker(self._transfer_lock):
                if transfer_id in self._released_transfers:
                    return
                self._released_transfers.add(transfer_id)

            # Thread-safe counter update
            with QMutexLocker(self._active_transfers_lock):
                self.active_transfers = max(self.active_transfers - 1, 0)

            self.remove_queue_item(transfer_id)
            self.update_overall_progress()
            
        except Exception as e:
            # Log error instead of silent pass
            print(f"Error releasing transfer {transfer_id}: {e}")

    def transfer_finished(self, transfer_id):
        """Handle natural completion of transfer with error handling"""
        try:
            if not transfer_id:
                return
                
            transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)
            if not transfer:
                return

            # Mark as inactive
            transfer.active = False
            
            # Update status safely
            try:
                if transfer.status_label:
                    transfer.status_label.setText("Completed")
                if transfer.progress_bar:
                    transfer.progress_bar.setValue(100)
            except RuntimeError as e:
                pass

            # Notify observers if needed
            try:
                if hasattr(transfer.download_worker, 'command') and transfer.download_worker.command in ["upload", "download"]:
                    self.notify_observees()
            except Exception as e:
                pass

            # Release transfer resources
            self._release_transfer(transfer_id)
            
            # Schedule cleanup after delay for visibility
            QTimer.singleShot(500, lambda: self.cleanup_transfer(transfer_id))
            
            # Check for more transfers
            QTimer.singleShot(100, self.check_and_start_transfers)
            
        except Exception as e:
            pass

    def transfer_error(self, transfer_id, message):
        """Handle transfer errors"""
        try:
            if not transfer_id:
                return
            
            transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)
            if not transfer:
                return
            
            # Mark as inactive
            transfer.active = False
            
            # Update status to show error
            try:
                if transfer.status_label:
                    transfer.status_label.setText(f"Error: {message}")
                if transfer.progress_bar:
                    transfer.progress_bar.setStyleSheet(f"""
                        QProgressBar::chunk {{
                            background-color: {DARK_THEME['error']};
                        }}
                    """)
            except RuntimeError:
                pass
            
            # Log error to console
            if hasattr(self, 'text_console'):
                self.text_console.append(f"ERROR Transfer {transfer_id}: {message}")
            
            # Release transfer resources
            self._release_transfer(transfer_id)
            
            # Schedule cleanup after delay
            QTimer.singleShot(2000, lambda: self.cleanup_transfer(transfer_id))
            
            # Check for more transfers
            QTimer.singleShot(100, self.check_and_start_transfers)
            
        except Exception as e:
            print(f"Error in transfer_error handler: {e}")

    def update_text_console(self, transfer_id, message):
        """Update console with transfer messages"""
        try:
            # Check if the transfer still exists before updating console
            if transfer_id:
                transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)
                if transfer and message:
                    self.text_console.append(f"[{transfer_id}] {message}")
            elif message:
                # Generic message without transfer_id
                self.text_console.append(f"{message}")
        except Exception as e:
            pass

    def _handle_worker_message(self, transfer_id, message):
        """Handle messages from worker threads, detect error messages"""
        try:
            # If message contains error indicators, treat as error
            if any(keyword in message.lower() for keyword in ['error', 'failed', 'exception', 'timeout']):
                self.transfer_error(transfer_id, message)
            else:
                # Regular message, log to console
                if hasattr(self, 'text_console'):
                    self.text_console.append(f"Transfer {transfer_id}: {message}")
        except Exception as e:
            print(f"Error handling worker message: {e}")

    def update_progress(self, transfer_id, value, speed_bps=None, eta_sec=None):
        """Update progress with error handling"""
        try:
            if not transfer_id:
                return
                
            transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)
            if not transfer or not transfer.active:
                return

            try:
                if transfer.progress_bar:
                    transfer.progress_bar.setValue(value)

                if transfer.speed_label and speed_bps is not None:
                    transfer.speed_label.setText(self.format_speed(speed_bps))

                if transfer.eta_label and eta_sec is not None:
                    transfer.eta_label.setText(self.format_time(eta_sec))

                if transfer.status_label:
                    transfer.status_label.setText(
                        "Completed" if value == 100 else
                        "Paused" if getattr(transfer, 'paused', False) else
                        "Transferring"
                    )
            except RuntimeError:
                # Widget may have been deleted
                pass

        except Exception as e:
            pass

    def format_speed(self, bytes_per_sec):
        """Format transfer speed in human-readable format"""
        try:
            if bytes_per_sec >= 1024 * 1024:
                return f"Speed: {bytes_per_sec / (1024 * 1024):.1f} MB/s"
            elif bytes_per_sec >= 1024:
                return f"Speed: {bytes_per_sec / 1024:.1f} KB/s"
            return f"Speed: {bytes_per_sec} B/s"
        except (TypeError, ValueError) as e:
            ic(f"Speed format error: {e}")
            return "Speed: -"

    def format_time(self, seconds):
        """Format time in human-readable format"""
        try:
            if seconds < 60:
                return f"ETA: {int(seconds)}s"
            elif seconds < 3600:
                return f"ETA: {int(seconds // 60)}m {int(seconds % 60)}s"
            return f"ETA: {int(seconds // 3600)}h {int((seconds % 3600) // 60)}m"
        except (TypeError, ValueError) as e:
            ic(f"Time format error: {e}")
            return "ETA: -"

    def toggle_pause_transfer(self, transfer_id):
        """Toggle pause state for a specific transfer"""
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
        except Exception as e:
            pass

    def toggle_pause_all(self):
        """Toggle pause state for all active transfers"""
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
        except Exception as e:
            pass

    def clear_completed(self):
        """Remove completed transfers from the list"""
        try:
            transfers_to_remove = []
            
            for transfer in self.transfers[:]:
                if (not transfer.active or 
                    (transfer.progress_bar and transfer.progress_bar.value() == 100) or
                    (transfer.status_label and transfer.status_label.text() in ["Completed", "Cancelled"])):
                    transfers_to_remove.append(transfer.transfer_id)
            
            for transfer_id in transfers_to_remove:
                self.cleanup_transfer(transfer_id)
                
        except Exception as e:
            self.text_console.append(f"Error clearing completed transfers: {e}")