from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                            QListWidget, QTextEdit, QProgressBar, QSizePolicy,
                            QLabel, QListWidgetItem, QScrollArea, QFrame)
from PyQt5.QtCore import Qt, QThreadPool, QTimer, QMutex, QMutexLocker
from icecream import ic
import os
import time

from sftp_downloadworkerclass import Transfer, DownloadWorker, sftp_queue_get, sftp_queue_isempty, clear_sftp_queue
from sftp_theme import (BUTTON_STYLE_DARK, LIST_WIDGET_STYLE_DARK, PROGRESS_BAR_STYLE_DARK,
                        TEXT_EDIT_STYLE_DARK, DARK_THEME)

MAX_TRANSFERS = 2


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
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.queue_items = []
        self.active_transfers = 0
        self.transfers = []
        self.observees = []
        self.total_queue_items = 0
        
        # Thread safety locks
        self._transfer_lock = QMutex()
        self._released_transfers = set()
        self._active_transfers_lock = QMutex()
        
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

        # Add control buttons
        self.control_layout = QHBoxLayout()
        self.control_layout.setSpacing(8)
        
        self.clear_button = QPushButton("Clear Completed")
        self.clear_button.setStyleSheet(BUTTON_STYLE_DARK)
        self.clear_button.clicked.connect(self.clear_completed)
        
        self.control_layout.addStretch(1)
        self.control_layout.addWidget(self.clear_button)
        
        self.main_layout.addLayout(self.control_layout)

        # Add text console
        self.text_console = QTextEdit()
        self.text_console.setReadOnly(True)
        self.text_console.setMaximumHeight(80)
        self.text_console.setStyleSheet(TEXT_EDIT_STYLE_DARK)
        self.main_layout.addWidget(self.text_console)

        # Set the main layout
        self.setLayout(self.main_layout)

        # Initialize thread pool
        self.thread_pool = QThreadPool.globalInstance()

        # Setup timers
        self._setup_timers()

    def _setup_timers(self):
        """Setup timers for queue processing"""
        # Timer to periodically check the queue
        self.check_queue_timer = QTimer(self)
        self.check_queue_timer.timeout.connect(self.check_and_start_transfers)
        self.check_queue_timer.start(100)  # Check every 100 ms

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
        """Add an observer to be notified when transfers complete"""
        if observee not in self.observees:
            self.observees.append(observee)

    def remove_observee(self, observee):
        """Remove an observer"""
        if observee in self.observees:
            self.observees.remove(observee)

    def notify_observees(self):
        """Notify all observers that transfers completed"""
        for observee in self.observees:
            try:
                observee.get_files()
            except AttributeError as ae:
                ic("Observee", observee, "does not implement 'get_files' method.", ae)
            except Exception as e:
                ic("An error occurred while notifying observee", observee, e)

    def update_overall_progress(self):
        """Update the overall progress - no longer displayed in compact UI"""
        pass

    def check_and_start_transfers(self):
        """Check for new transfers in queue and start them"""
        try:
            # Fix active transfers counter
            with QMutexLocker(self._transfer_lock):
                actual_active = len([t for t in self.transfers if t.active])
                if self.active_transfers != actual_active:
                    self.active_transfers = actual_active
            
            # Check if we've reached max transfers
            with QMutexLocker(self._active_transfers_lock):
                if self.active_transfers >= MAX_TRANSFERS:
                    return

            # Check if queue is empty
            if sftp_queue_isempty():
                return

            # Get job from queue
            try:
                job = sftp_queue_get()
                if not job:
                    return
            except Exception as e:
                self.text_console.append(f"Error getting job from queue: {e}")
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

        except Exception as e:
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
            widget.setFixedHeight(44)  # Much more compact
            layout = QHBoxLayout()
            layout.setContentsMargins(8, 4, 8, 4)
            layout.setSpacing(8)
            
            # File icon + name on the left
            file_layout = QVBoxLayout()
            file_layout.setSpacing(0)
            file_layout.setContentsMargins(0, 0, 0, 0)
            
            file_name = os.path.basename(job_source)
            file_label = QLabel(file_name if len(file_name) < 35 else file_name[:32] + "...")
            file_label.setStyleSheet(f"font-weight: 600; font-size: 12px; color: {DARK_THEME['text_primary']};")
            file_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            file_label.setToolTip(job_source)  # Full path on hover
            file_layout.addWidget(file_label)
            
            # Status below filename
            status_label = QLabel("Queued")
            status_label.setStyleSheet(f"font-size: 10px; color: {DARK_THEME['text_secondary']};")
            status_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            file_layout.addWidget(status_label)
            
            layout.addLayout(file_layout, 3)  # Takes 3/5 of space
            
            # Progress bar in middle
            progress_bar = QProgressBar()
            progress_bar.setRange(0, 100)
            progress_bar.setValue(0)
            progress_bar.setFixedHeight(16)
            progress_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            progress_bar.setStyleSheet(f"""
                QProgressBar {{
                    border: none;
                    border-radius: 3px;
                    background-color: {DARK_THEME['border']};
                    text-align: center;
                    font-size: 10px;
                    color: {DARK_THEME['text_primary']};
                }}
                QProgressBar::chunk {{
                    background-color: {DARK_THEME['accent_green']};
                    border-radius: 3px;
                }}
            """)
            layout.addWidget(progress_bar, 2)  # Takes 2/5 of space
            
            # Speed/ETA on the right
            stats_layout = QVBoxLayout()
            stats_layout.setSpacing(0)
            stats_layout.setContentsMargins(0, 0, 0, 0)
            
            speed_label = QLabel("-")
            speed_label.setStyleSheet(f"font-size: 10px; color: {DARK_THEME['text_primary']};")
            speed_label.setAlignment(Qt.AlignRight)
            stats_layout.addWidget(speed_label)
            
            eta_label = QLabel("-")
            eta_label.setStyleSheet(f"font-size: 10px; color: {DARK_THEME['text_secondary']};")
            eta_label.setAlignment(Qt.AlignRight)
            stats_layout.addWidget(eta_label)
            
            layout.addLayout(stats_layout)
            
            # Compact buttons
            cancel_button = QPushButton("✕")
            cancel_button.setFixedWidth(28)
            cancel_button.setFixedHeight(28)
            cancel_button.setToolTip("Cancel")
            cancel_button.setStyleSheet(f"""
                QPushButton {{
                    border: none;
                    border-radius: 4px;
                    background-color: transparent;
                    color: {DARK_THEME['text_secondary']};
                    font-size: 14px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {DARK_THEME['error']};
                    color: white;
                }}
            """)
            cancel_button.clicked.connect(lambda checked, tid=transfer_id: self.cancel_transfer(tid))
            layout.addWidget(cancel_button)
            
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
            
            with QMutexLocker(self._active_transfers_lock):
                self.active_transfers += 1
            self.update_overall_progress()
            
        except Exception as e:
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
                except Exception:
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
            
        except Exception as e:
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
            
        except Exception:
            pass

    def _release_transfer(self, transfer_id):
        """Release transfer resources"""
        try:
            with QMutexLocker(self._transfer_lock):
                if transfer_id in self._released_transfers:
                    return
                self._released_transfers.add(transfer_id)

            with QMutexLocker(self._active_transfers_lock):
                self.active_transfers = max(self.active_transfers - 1, 0)

            self.remove_queue_item(transfer_id)
            self.update_overall_progress()
            
        except Exception as e:
            print(f"Error releasing transfer {transfer_id}: {e}")

    def transfer_finished(self, transfer_id):
        """Handle transfer completion"""
        try:
            if not transfer_id:
                return
                
            transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)
            if not transfer:
                return

            transfer.active = False
            
            try:
                if transfer.status_label:
                    transfer.status_label.setText("Completed")
                    transfer.status_label.setStyleSheet(f"font-size: 12px; color: {DARK_THEME['success']}; font-weight: bold;")
                if transfer.progress_bar:
                    transfer.progress_bar.setValue(100)
                    transfer.progress_bar.setStyleSheet(f"""
                        QProgressBar {{
                            border: 1px solid {DARK_THEME['success']};
                            border-radius: 4px;
                            text-align: center;
                            font-size: 12px;
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
                   transfer.download_worker.command in ["upload", "download"]:
                    self.notify_observees()
            except Exception:
                pass

            # Release resources but DON'T cleanup - keep visible
            self._release_transfer(transfer_id)
            
            # Try to start another transfer
            QTimer.singleShot(100, self.check_and_start_transfers)
            
        except Exception:
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
                    transfer.status_label.setText(f"Error: {message[:30]}...")
                    transfer.status_label.setStyleSheet(f"font-size: 12px; color: {DARK_THEME['error']}; font-weight: bold;")
                if transfer.progress_bar:
                    transfer.progress_bar.setStyleSheet(f"""
                        QProgressBar::chunk {{
                            background-color: {DARK_THEME['error']};
                        }}
                    """)
            except RuntimeError:
                pass
            
            if hasattr(self, 'text_console'):
                self.text_console.append(f"ERROR Transfer {transfer_id}: {message}")
            
            self._release_transfer(transfer_id)
            
        except Exception as e:
            print(f"Error in transfer_error handler: {e}")

    def _handle_worker_message(self, transfer_id, message):
        """Handle messages from worker threads"""
        try:
            if any(keyword in message.lower() for keyword in ['error', 'failed', 'exception', 'timeout']):
                self.transfer_error(transfer_id, message)
            else:
                if hasattr(self, 'text_console'):
                    self.text_console.append(f"Transfer {transfer_id}: {message}")
        except Exception as e:
            print(f"Error handling worker message: {e}")

    def update_progress(self, transfer_id, value, speed_bps=None, eta_sec=None):
        """Update transfer progress"""
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
                    if value == 100:
                        transfer.status_label.setStyleSheet(f"font-size: 12px; color: {DARK_THEME['success']}; font-weight: bold;")
            except RuntimeError:
                pass

        except Exception:
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
        except Exception:
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
        except Exception:
            pass

    def clear_completed(self):
        """Remove completed/cancelled/error transfers"""
        try:
            transfers_to_remove = []
            
            for transfer in self.transfers[:]:
                status_text = transfer.status_label.text() if transfer.status_label else ""
                if (not transfer.active or 
                    status_text in ["Completed", "Cancelled"] or
                    status_text.startswith("Error:")):
                    transfers_to_remove.append(transfer.transfer_id)
            
            for transfer_id in transfers_to_remove:
                self.cleanup_transfer(transfer_id)
                
        except Exception as e:
            self.text_console.append(f"Error clearing completed transfers: {e}")

    def cleanup(self):
        """Cleanup resources when widget is destroyed"""
        try:
            # Stop timers first to prevent new transfers
            if hasattr(self, 'check_queue_timer'):
                self.check_queue_timer.stop()

            # Cancel all transfers
            for transfer in self.transfers[:]:
                try:
                    if transfer.active and hasattr(transfer, 'download_worker'):
                        transfer.download_worker._stop_flag = True
                except Exception:
                    pass

            # Clear the queue
            clear_sftp_queue()

            # Wait for threads with timeout
            if hasattr(self, 'thread_pool'):
                self.thread_pool.waitForDone(2000)

            # Final cleanup of transfers list
            self.transfers.clear()
            self.active_transfers = 0

        except Exception as e:
            print(f"Error in cleanup: {e}")
