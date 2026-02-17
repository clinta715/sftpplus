from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, 
                            QPushButton, QListWidget, QTextEdit, QProgressBar, QSizePolicy, 
                            QLabel, QGroupBox, QListWidgetItem)
from PyQt5.QtCore import Qt
from PyQt5.QtCore import QThreadPool, QTimer, Qt
from icecream import ic
import os

from sftp_downloadworkerclass import Transfer, DownloadWorker, sftp_queue_get, sftp_queue_isempty

MAX_TRANSFERS = 2

class BackgroundThreadWindow(QMainWindow):
    def __init__(self):
        super(BackgroundThreadWindow, self).__init__()
        self.queue_items = []
        self.active_transfers = 0
        self.transfers = []
        self.observees = []
        self.total_queue_items = 0
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
        self.overall_progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 5px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                width: 10px;
            }
        """)
        
        self.overall_progress_layout.addWidget(self.overall_progress_label)
        self.overall_progress_layout.addWidget(self.overall_progress_bar)
        self.layout.addLayout(self.overall_progress_layout)

        # Add transfer list
        self.transfer_list = QListWidget()
        self.transfer_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #ddd;
                border-radius: 5px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 5px;
                border-bottom: 1px solid #eee;
            }
            QListWidget::item:hover {
                background-color: #f5f5f5;
            }
        """)
        self.transfer_list.setMaximumHeight(250)
        self.transfer_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.layout.addWidget(self.transfer_list)

        # Add control buttons
        self.control_layout = QHBoxLayout()
        self.pause_button = QPushButton("Pause All")
        self.pause_button.setStyleSheet("""
            QPushButton {
                padding: 5px 10px;
                border: 1px solid #ccc;
                border-radius: 3px;
                background-color: #f8f8f8;
            }
            QPushButton:hover {
                background-color: #e8e8e8;
            }
        """)
        self.pause_button.clicked.connect(self.toggle_pause_all)
        self.control_layout.addWidget(self.pause_button)

        self.clear_button = QPushButton("Clear Completed")
        self.clear_button.setStyleSheet(self.pause_button.styleSheet())
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

    def add_queue_item(self, item):
        if item not in self.queue_items:
            self.queue_items.append(item)
            self.total_queue_items += 1
            self.update_overall_progress()
            # Queue items are now handled by the transfer list widgets

    def remove_queue_item(self, item):
        if item in self.queue_items:
            self.queue_items.remove(item)
            self.total_queue_items -= 1
            self.update_overall_progress()
            # Queue items are now handled by the transfer list widgets

    def add_observee(self, observee):
        if observee not in self.observees:
            self.observees.append(observee)
            ic("Observee added:", observee)
        else:
            ic("Observee already exists:", observee)

    def remove_observee(self, observee):
        if observee in self.observees:
            self.observees.remove(observee)
            ic("Observer removed:", observee)

    def notify_observees(self):
        for observee in self.observees:
            try:
                observee.get_files()  # Notify the observer by calling its update method
                ic("Observee notified:", observee)
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
        # Scroll to the bottom of the QTextEdit
        vertical_scroll_bar = self.text_console.verticalScrollBar()
        vertical_scroll_bar.setValue(vertical_scroll_bar.maximum())

    def check_and_start_transfers(self):
        # Check if more transfers can be started
        if sftp_queue_isempty():
            return
        else:
            job = sftp_queue_get()
            if job is None:
                return

        if job.command == "end":
            ic("end command given")
        else:
            hostname = job.hostname
            password = job.password
            port = job.port
            username = job.username
            command = job.command

            self.start_transfer(job.id, job.source_path, job.destination_path, job.is_source_remote, job.is_destination_remote, hostname, port, username, password, command)

    def start_transfer(self, transfer_id, job_source, job_destination, is_source_remote, is_destination_remote, hostname, port, username, password, command):
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
        progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 3px;
                height: 15px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                width: 10px;
            }
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
        pause_button.setStyleSheet("""
            QPushButton {
                padding: 2px 5px;
                border: 1px solid #ccc;
                border-radius: 3px;
                background-color: #f8f8f8;
            }
            QPushButton:hover {
                background-color: #e8e8e8;
            }
        """)
        pause_button.clicked.connect(lambda: self.toggle_pause_transfer(transfer_id))
        
        cancel_button = QPushButton("Cancel")
        cancel_button.setStyleSheet(pause_button.styleSheet())
        cancel_button.clicked.connect(lambda: self.transfer_finished(transfer_id))
        
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
        
        # Store transfer details
        new_transfer = Transfer(
            transfer_id=transfer_id,
            download_worker=DownloadWorker(transfer_id, job_source, job_destination, 
                                         is_source_remote, is_destination_remote,
                                         hostname, port, username, password, command),
            active=True,
            progress_bar=progress_bar,
            cancel_button=cancel_button,
            speed_label=speed_label,
            eta_label=eta_label,
            status_label=status_label,
            pause_button=pause_button,
            list_item=item
        )

        # Create and configure the download worker
        new_transfer.download_worker.signals.progress.connect(lambda tid, val, speed, eta: self.update_progress(tid, val, speed, eta))
        new_transfer.download_worker.signals.finished.connect(lambda tid: self.transfer_finished(tid))
        new_transfer.download_worker.signals.message.connect(lambda tid, msg: self.update_text_console(tid, msg))
        self.transfers.append(new_transfer)

        # Start the download worker in the thread pool
        self.thread_pool.start(new_transfer.download_worker)
        self.add_queue_item(job_source)
        self.active_transfers += 1
        self.update_overall_progress()

    def transfer_finished(self, transfer_id):
        # Find the transfer
        transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)

        if transfer is None:
            self.text_console.append(f"No transfer found with ID {transfer_id}")
            return

        # Deactivate the transfer
        transfer.active = False

        # Stop the download worker
        transfer.download_worker.stop_transfer()

        if transfer.progress_bar:
            transfer.progress_bar.deleteLater()
            transfer.progress_bar = None

        if transfer.cancel_button:
            transfer.cancel_button.deleteLater()
            transfer.cancel_button = None

        # Remove the list item from the transfer list
        if transfer.list_item:
            self.transfer_list.takeItem(self.transfer_list.row(transfer.list_item))

        # Remove the transfer from the list
        self.transfers = [t for t in self.transfers if t.transfer_id != transfer_id]
        self.text_console.append("Transfer removed from the transfers list.")
        
        self.remove_queue_item(transfer.download_worker.job_source)
        self.active_transfers -= 1
        self.update_overall_progress()
        
        if transfer.download_worker.command == "upload" or transfer.download_worker.command == "download":
            self.notify_observees()

        self.check_and_start_transfers()


    def update_text_console(self, transfer_id, message):
        if message:
            self.text_console.append(f"{message}")

    def update_progress(self, transfer_id, value, speed_bps=None, eta_sec=None):
        transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)
        if not transfer:
            return

        if transfer.progress_bar:
            transfer.progress_bar.setValue(value)

        if transfer.speed_label and speed_bps is not None:
            transfer.speed_label.setText(self.format_speed(speed_bps))

        if transfer.eta_label and eta_sec is not None:
            transfer.eta_label.setText(self.format_time(eta_sec))

        if transfer.status_label:
            transfer.status_label.setText(
                "Completed" if value == 100 else
                "Paused"    if transfer.paused else
                "Transferring"
            )

    def format_speed(self, bytes_per_sec):
        """Format transfer speed in human-readable format"""
        if bytes_per_sec >= 1024 * 1024:
            return f"{bytes_per_sec / (1024 * 1024):.1f} MB/s"
        elif bytes_per_sec >= 1024:
            return f"{bytes_per_sec / 1024:.1f} KB/s"
        return f"{bytes_per_sec} B/s"

    def format_time(self, seconds):
        """Format time in human-readable format"""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds // 60)}m {int(seconds % 60)}s"
        return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m"

    def toggle_pause_transfer(self, transfer_id):
        transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)
        if transfer:
            transfer.paused = not transfer.paused
            transfer.download_worker.paused = transfer.paused
            transfer.pause_button.setText("Resume" if transfer.paused else "Pause")
            if transfer.status_label:
                transfer.status_label.setText("Paused" if transfer.paused else "Resuming...")

    def toggle_pause_all(self):
        any_paused = any(t.paused for t in self.transfers)
        for transfer in self.transfers:
            transfer.paused = not any_paused
            transfer.download_worker.paused = transfer.paused
            transfer.pause_button.setText("Resume" if transfer.paused else "Pause")
            if transfer.status_label:
                transfer.status_label.setText("Paused" if transfer.paused else "Resuming...")
        self.pause_button.setText("Resume All" if any_paused else "Pause All")

    def clear_completed(self):
        """Remove completed transfers from the list"""
        for transfer in self.transfers[:]:
            if transfer.progress_bar and transfer.progress_bar.value() == 100:
                self.transfer_finished(transfer.transfer_id)
