from PyQt6.QtWidgets import QInputDialog, QMessageBox, QApplication
from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, QThreadPool, QMutex, QWaitCondition
from sftp_qt_compat import Qt
from sftp_creds import get_credentials, create_random_integer
from sftp_downloadworkerclass import add_sftp_job
from sftp_preferences import get_preferences
import os
import stat
import threading
from icecream import ic


class TraversalSignals(QObject):
    """Signals for the directory traversal worker"""
    status = pyqtSignal(str)
    job_added = pyqtSignal(str)
    prompt_overwrite = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)


class TraversalWorker(QRunnable):
    """Worker that recursively traverses directories in the background"""
    
    def __init__(self, session_id, source_dir, dest_dir, is_source_remote, is_dest_remote,
                 skip_all=False, overwrite_all=False, resume_all=False):
        super().__init__()
        self.session_id = session_id
        self.source_dir = source_dir
        self.dest_dir = dest_dir
        self.is_source_remote = is_source_remote
        self.is_dest_remote = is_dest_remote
        self.skip_all = skip_all
        self.overwrite_all = overwrite_all
        self.resume_all = resume_all
        self.signals = TraversalSignals()
        
        # For cross-thread prompting
        self.prompt_mutex = QMutex()
        self.prompt_cond = QWaitCondition()
        self.prompt_result = None
        
        # Credentials for jobs
        self.creds = get_credentials(session_id)
        
        # SFTPOperations for listing
        from sftp_operations import SFTPOperations
        self.ops = SFTPOperations(
            hostname=self.creds.get('hostname', ''),
            username=self.creds.get('username', ''),
            password=self.creds.get('password', ''),
            port=self.creds.get('port', 22),
            key=self.creds.get('key')
        )

    def set_prompt_result(self, result):
        """Called by UI thread to provide result of overwrite prompt"""
        self.prompt_mutex.lock()
        self.prompt_result = result
        self.prompt_cond.wakeAll()
        self.prompt_mutex.unlock()

    def run(self):
        try:
            self.signals.status.emit(f"Starting traversal of {self.source_dir}...")
            self._traverse(self.source_dir, self.dest_dir)
            self.signals.finished.emit()
        except Exception as e:
            ic(f"TraversalWorker error: {e}")
            self.signals.error.emit(str(e))
        finally:
            if self.ops:
                self.ops.close()

    def _ensure_directory_exists(self, directory_path, is_remote=False):
        if is_remote:
            if not self.ops.exists(directory_path):
                parts = directory_path.strip('/').split('/')
                current = ""
                for part in parts:
                    current += '/' + part
                    if not self.ops.exists(current):
                        self.ops.mkdir(current)
        else:
            os.makedirs(directory_path, exist_ok=True)

    def _traverse(self, source_dir, dest_dir):
        # Ensure destination exists
        self._ensure_directory_exists(dest_dir, is_remote=self.is_dest_remote)
        
        self.signals.status.emit(f"Scanning: {source_dir}")
        
        if self.is_source_remote:
            try:
                files = self.ops.list_attr(source_dir)
            except Exception as e:
                ic(f"Error listing remote dir {source_dir}: {e}")
                return
        else:
            try:
                files = os.listdir(source_dir)
            except Exception as e:
                ic(f"Error listing local dir {source_dir}: {e}")
                return
            
        for entry in files:
            if self.is_source_remote:
                filename = entry.filename
                if filename in ['.', '..']: continue
                is_dir = stat.S_ISDIR(entry.st_mode)
            else:
                filename = entry
                if filename in ['.', '..']: continue
                is_dir = os.path.isdir(os.path.join(source_dir, filename))
                
            source_path = os.path.join(source_dir, filename)
            dest_path = os.path.join(dest_dir, filename)
            
            if is_dir:
                self._traverse(source_path, dest_path)
                continue
                
            # Handle file conflict
            exists = self.ops.exists(dest_path) if self.is_dest_remote else os.path.exists(dest_path)
            command = "upload" if self.is_dest_remote else "download"
            
            if exists and not self.skip_all and not self.overwrite_all and not self.resume_all:
                # Request prompt from UI thread
                self.prompt_mutex.lock()
                self.prompt_result = None
                self.signals.prompt_overwrite.emit(dest_path)
                # Wait for UI thread to respond
                while self.prompt_result is None:
                    self.prompt_cond.wait(self.prompt_mutex)
                
                action = self.prompt_result
                self.prompt_mutex.unlock()
                
                if action == "cancel":
                    return
                elif action == "skip":
                    continue
                elif action == "skip_all":
                    self.skip_all = True
                    continue
                elif action == "overwrite_all":
                    self.overwrite_all = True
                elif action == "resume_all":
                    self.resume_all = True
                elif action == "resume":
                    command = "resume"
                    
            if self.skip_all:
                continue
            
            if self.resume_all:
                command = "resume"
                
            job_id = create_random_integer()
            add_sftp_job(source_path, self.is_source_remote, dest_path, self.is_dest_remote,
                        self.creds.get('hostname', ''),
                        self.creds.get('username', ''),
                        self.creds.get('password', ''),
                        self.creds.get('port', 22),
                        command, job_id, self.creds.get('key'))
            
            self.signals.job_added.emit(str(job_id))


class TransferHandlerMixin:
    """Mixin class providing file transfer functionality."""

    transfer_started = None

    def download_directory(self, source_directory, destination_directory, 
                         skip_all=False, overwrite_all=False, resume_all=False):
        """Start a background worker to traverse and download a directory."""
        worker = TraversalWorker(
            self.session_id, source_directory, destination_directory,
            is_source_remote=True, is_dest_remote=False,
            skip_all=skip_all, overwrite_all=overwrite_all, resume_all=resume_all
        )
        
        # Connect signals
        worker.signals.status.connect(lambda msg: self.message_signal.emit(msg))
        worker.signals.job_added.connect(lambda jid: self.transfer_started.emit(jid) if self.transfer_started else None)
        worker.signals.prompt_overwrite.connect(lambda path: self._handle_worker_prompt(worker, path))
        worker.signals.error.connect(lambda err: self.message_signal.emit(f"Traversal error: {err}"))
        
        # Run in thread pool
        QThreadPool.globalInstance().start(worker)
        self.message_signal.emit(f"Started background scan of {source_directory}")

    def upload_directory(self, source_directory, destination_directory, 
                         skip_all=False, overwrite_all=False, resume_all=False):
        """Start a background worker to traverse and upload a directory."""
        worker = TraversalWorker(
            self.session_id, source_directory, destination_directory,
            is_source_remote=False, is_dest_remote=True,
            skip_all=skip_all, overwrite_all=overwrite_all, resume_all=resume_all
        )
        
        worker.signals.status.connect(lambda msg: self.message_signal.emit(msg))
        worker.signals.job_added.connect(lambda jid: self.transfer_started.emit(jid) if self.transfer_started else None)
        worker.signals.prompt_overwrite.connect(lambda path: self._handle_worker_prompt(worker, path))
        worker.signals.error.connect(lambda err: self.message_signal.emit(f"Traversal error: {err}"))
        
        QThreadPool.globalInstance().start(worker)
        self.message_signal.emit(f"Started background scan of {source_directory}")

    def _handle_worker_prompt(self, worker, path):
        """Handle overwrite prompt request from background worker"""
        action = self.prompt_overwrite(path)
        worker.set_prompt_result(action)

    def prompt_overwrite(self, item_path):
        """Prompt user for overwrite action."""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon_Question)
        msg.setText(f"File already exists:\n{item_path}")
        msg.setWindowTitle("File Exists")
        
        overwrite_btn = msg.addButton("Overwrite", QMessageBox.ButtonRole.ActionRole)
        skip_btn = msg.addButton("Skip", QMessageBox.ButtonRole.ActionRole)
        cancel_btn = msg.addButton(QMessageBox.StandardButton.Cancel)
        resume_btn = msg.addButton("Resume", QMessageBox.ButtonRole.ActionRole)
        
        overwrite_all_btn = msg.addButton("Overwrite All", QMessageBox.ButtonRole.ActionRole)
        skip_all_btn = msg.addButton("Skip All", QMessageBox.ButtonRole.ActionRole)
        resume_all_btn = msg.addButton("Resume All", QMessageBox.ButtonRole.ActionRole)
        
        msg.exec()
        
        clicked = msg.clickedButton()
        
        if clicked == overwrite_btn:
            return "overwrite"
        elif clicked == skip_btn:
            return "skip"
        elif clicked == cancel_btn:
            return "cancel"
        elif clicked == resume_btn:
            return "resume"
        elif clicked == overwrite_all_btn:
            return "overwrite_all"
        elif clicked == skip_all_btn:
            return "skip_all"
        elif clicked == resume_all_btn:
            return "resume_all"
        else:
            return "cancel"
