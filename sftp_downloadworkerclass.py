from PySide6.QtCore import QRunnable, QObject, Signal
import enum
import queue
import paramiko
import base64
import re
import os
import time
import threading
import shlex
import logging

from sftp_connection_pool import ConnectionPool
from sftp_hostdataeditor import cipher_suite

logger = logging.getLogger('sftp.transfer')


def strip_decorative_chars(filename):
    """Strip decorative characters from the filename."""
    # Remove leading emoji characters and spaces
    filename = re.sub(r'^[\U0001F000-\U0001F9FF\s]+', '', filename)
    # Remove any remaining leading or trailing whitespace
    return filename.strip()


class WorkerSignals(QObject):
    progress = Signal(int, int, float, float, int, int)   # transfer_id, percent, speed_bytes_per_sec, eta_seconds, bytes_done, bytes_total
    finished = Signal(int)
    message  = Signal(int, str)

response_queues = {}
sftp_queue = queue.Queue()

# Thread safety locks
response_queues_lock = threading.Lock()

class SIZE_UNIT(enum.Enum):
    BYTES = 1
    KB = 2
    MB = 3
    GB = 4

class Transfer:
    def __init__(self, transfer_id, progress_bar=None, cancel_button=None, download_worker=None, 
                 active=False, speed_label=None, eta_label=None, status_label=None, 
                 pause_button=None, list_item=None, hostname=None):
        self.transfer_id = transfer_id
        self.progress_bar = progress_bar
        self.cancel_button = cancel_button
        self.download_worker = download_worker
        self.active = active
        self.speed_label = speed_label
        self.eta_label = eta_label
        self.status_label = status_label
        self.pause_button = pause_button
        self.list_item = list_item
        self.hostname = hostname
        self.paused = False
        self.layout = None  # Initialize layout attribute
        # Progress tracking
        self.bytes_done = 0
        self.bytes_total = 0
        self.files_done = 0
        self.files_total = 0
        self.speed_bps = 0.0
        self.eta_seconds = 0

class transferSignals(QObject):
    showhide = Signal()

class QueueItem:
    def __init__(self, name, job_id):
        self.name = name
        self.job_id = job_id

class SFTPJob:
    def __init__(self, source_path, is_source_remote, destination_path, is_destination_remote, hostname, username, password, port, command, job_id, key ):
        self.source_path = source_path
        self.is_source_remote = is_source_remote
        self.destination_path = destination_path
        self.is_destination_remote = is_destination_remote
        self.hostname = hostname
        self.username = username
        self.password = password
        self.port = port
        self.command = command
        self.job_id = job_id
        self.key = key

    def to_dict(self):
        """Convert job to dictionary with encrypted password for secure serialization."""
        encrypted_password = ''
        if self.password and cipher_suite:
            try:
                encrypted_password = cipher_suite.encrypt(self.password.encode()).decode()
            except Exception:
                pass
        return {
            "source_path": self.source_path,
            "is_source_remote": self.is_source_remote,
            "destination_path": self.destination_path,
            "is_destination_remote": self.is_destination_remote,
            "hostname": self.hostname,
            "username": self.username,
            "password": encrypted_password,
            "port": self.port,
            "command": self.command,
            "job_id": self.job_id,
            "key": self.key
        }

    @staticmethod
    def from_dict(data):
        """Create job from dictionary with decrypted password."""
        encrypted_password = data.get("password", "")
        if encrypted_password and cipher_suite:
            try:
                data["password"] = cipher_suite.decrypt(encrypted_password.encode()).decode()
            except Exception:
                data["password"] = ""
        else:
            data["password"] = ""
        return SFTPJob(**data)

def clear_sftp_queue():
    while True:
        try: 
            sftp_queue.get_nowait()
        except queue.Empty:
            break

def add_sftp_job(source_path, is_source_remote, destination_path, is_destination_remote, hostname, username, password, port, command, job_id, key ):
    job = SFTPJob(
        source_path, is_source_remote, destination_path, is_destination_remote,
        hostname, username, password, port, command, job_id, key )
    sftp_queue_put(job)

def sftp_queue_get():
    return(sftp_queue.get_nowait())

def sftp_queue_put(job):
    sftp_queue.put(job)

def sftp_queue_isempty():
    return sftp_queue.empty()

def delete_response_queue(job_id):
    with response_queues_lock:
        if job_id in response_queues:
            del response_queues[job_id]

def create_response_queue(job_id):
    # Create a new queue
    new_queue = queue.Queue()
    # Assign the new queue to the specified job_id in response_queues
    with response_queues_lock:
        response_queues[job_id] = new_queue
    # Return the newly created queue
    return new_queue

class ResponseQueueContext:
    """Context manager to ensure response queues are always cleaned up"""
    def __init__(self, job_id):
        self.job_id = job_id
        self.queue = None
    
    def __enter__(self):
        self.queue = create_response_queue(self.job_id)
        return self.queue
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Always clean up the queue, even if an exception occurred
        try:
            delete_response_queue(self.job_id)
        except (KeyError, RuntimeError) as e:
            pass
        # Don't suppress exceptions
        return False

def check_response_queue(job_id):
    """Check response queue for job_id. Thread-safe with minimal lock time."""
    # Get queue reference under lock, then get from queue outside lock
    with response_queues_lock:
        if job_id not in response_queues:
            return None
        q = response_queues[job_id]
    
    # Get from queue OUTSIDE the lock to avoid contention
    try:
        return q.get_nowait()
    except queue.Empty:
        return None

def wait_for_response(job_id, timeout=30.0):
    """
    Wait for response from queue with blocking (efficient, no busy-polling).
    Returns (success, response) tuple.
    Thread-safe.
    """
    with response_queues_lock:
        if job_id not in response_queues:
            return (False, None)
        q = response_queues[job_id]
    
    try:
        response = q.get(timeout=timeout)
        return (True, response)
    except queue.Empty:
        return (False, None)

def put_response(transfer_id, *items):
    """Thread-safe function to put items into response queue"""
    with response_queues_lock:
        if transfer_id in response_queues:
            for item in items:
                response_queues[transfer_id].put(item)

class DownloadWorker(QRunnable):
    def __init__(self, transfer_id, job_source, job_destination, is_source_remote, is_destination_remote, hostname, port, username, password, command=None, key=None):
        super(DownloadWorker, self).__init__()
        self.transfer_id = transfer_id
        self._stop_flag = False
        self.signals = WorkerSignals()
        
        self.is_source_remote = is_source_remote
        self.job_source = job_source
        self.job_destination = job_destination
        self.is_destination_remote = is_destination_remote
        self.hostname = hostname
        self.port = port
        self.username = username
        self.password = password
        self.command = command
        
        # Progress tracking with rate limiting
        self._last_emit_time = 0
        self._emit_interval = 0.2  # Increased to 200ms for better performance
        self._last_bytes = 0
        self._last_time = None
        self._progress_count = 0  # Track number of progress calls
        
        # Connection objects
        self.ssh = None
        self.sftp = None
        self.temp_key = key

    def _get_local_file_size(self, filepath):
        """Get the size of a local file, returns 0 if file doesn't exist."""
        try:
            return os.path.getsize(filepath)
        except (OSError, FileNotFoundError):
            return 0

    def _get_remote_file_size(self, filepath):
        """Get the size of a remote file, returns 0 if file doesn't exist."""
        try:
            return self.sftp.stat(filepath).st_size
        except (IOError, OSError):
            return 0

    def _resume_download(self, remote_path, local_path, callback=None):
        """Download with resume capability, compatible with _transfer_with_timeout."""
        # Get existing local file size
        existing_size = self._get_local_file_size(local_path)
        
        # Get remote file size
        remote_size = self._get_remote_file_size(remote_path)
        
        if existing_size == 0:
            # No existing file, do normal download
            self.sftp.get(remote_path, local_path, callback=callback)
            return
        elif existing_size >= remote_size:
            # Local file is same size or larger, nothing to download
            self.signals.message.emit(
                self.transfer_id,
                f"File already complete: {local_path}"
            )
            # Still call callback with 100% to maintain consistency
            if callback:
                callback(remote_size, remote_size)
            return
        
        # Resume download from existing position
        self.signals.message.emit(
            self.transfer_id,
            f"Resuming download from {existing_size} bytes"
        )
        
        # Open local file in append mode and remote file with offset
        with open(local_path, 'ab') as local_file:
            with self.sftp.open(remote_path, 'rb') as remote_file:
                remote_file.seek(existing_size)
                
                # Download remaining bytes
                chunk_size = 32768  # 32KB chunks
                bytes_downloaded = 0
                remaining_size = remote_size - existing_size
                
                while bytes_downloaded < remaining_size:
                    if self._stop_flag:
                        raise Exception("Transfer interrupted")
                        
                    chunk = remote_file.read(min(chunk_size, remaining_size - bytes_downloaded))
                    if not chunk:
                        break
                        
                    local_file.write(chunk)
                    bytes_downloaded += len(chunk)
                    
                    # Call progress callback with adjusted values
                    if callback:
                        total_downloaded = existing_size + bytes_downloaded
                        callback(total_downloaded, remote_size)

    def _resume_upload(self, local_path, remote_path, callback=None):
        """Upload with resume capability, compatible with _transfer_with_timeout."""
        # Get local file size
        local_size = self._get_local_file_size(local_path)
        
        if local_size == 0:
            raise ValueError("Local file is empty or doesn't exist")
        
        # Get existing remote file size
        existing_size = self._get_remote_file_size(remote_path)
        
        if existing_size == 0:
            # No existing remote file, do normal upload
            self.sftp.put(local_path, remote_path, callback=callback)
            return
        elif existing_size >= local_size:
            # Remote file is same size or larger, nothing to upload
            self.signals.message.emit(
                self.transfer_id,
                f"File already complete: {remote_path}"
            )
            # Still call callback with 100% to maintain consistency
            if callback:
                callback(local_size, local_size)
            return
        
        # Resume upload from existing position
        self.signals.message.emit(
            self.transfer_id,
            f"Resuming upload from {existing_size} bytes"
        )
        
        # Open local file with offset and remote file in append mode
        with open(local_path, 'rb') as local_file:
            local_file.seek(existing_size)
            
            with self.sftp.open(remote_path, 'ab') as remote_file:
                # Upload remaining bytes
                chunk_size = 32768  # 32KB chunks
                bytes_uploaded = 0
                remaining_size = local_size - existing_size
                
                while bytes_uploaded < remaining_size:
                    if self._stop_flag:
                        raise Exception("Transfer interrupted")
                        
                    chunk = local_file.read(min(chunk_size, remaining_size - bytes_uploaded))
                    if not chunk:
                        break
                        
                    remote_file.write(chunk)
                    bytes_uploaded += len(chunk)
                    
                    # Call progress callback with adjusted values
                    if callback:
                        total_uploaded = existing_size + bytes_uploaded
                        callback(total_uploaded, local_size)

    def _load_private_key(self, key_data, passphrase=None):
        """Load private key from string data with comprehensive format support"""
        if not key_data:
            return None
    
        key_types = [
            paramiko.RSAKey,
            paramiko.DSSKey,
            paramiko.ECDSAKey,
            paramiko.Ed25519Key
        ]
        
        for key_type in key_types:
            try:
                if key_data.startswith('-----BEGIN'):
                    key_obj = key_type.from_private_key_file(key_data, password=passphrase)
                else:
                    expanded_path = os.path.expanduser(key_data)
                    key_obj = key_type.from_private_key_file(expanded_path, password=passphrase)
                
                self.signals.message.emit(
                    self.transfer_id, 
                    f"Loaded {key_type.__name__} key successfully"
                )
                return key_obj
            except paramiko.PasswordRequiredException:
                self.signals.message.emit(
                    self.transfer_id, 
                    "Private key is encrypted but no passphrase provided"
                )
                return None
            except (paramiko.SSHException, ValueError, TypeError, FileNotFoundError):
                continue
            except (OSError, IOError) as e:
                continue
                
        # All attempts failed
        self.signals.message.emit(
            self.transfer_id, 
            "Failed to load private key: unsupported format or invalid key data"
        )
        return None

    def _connect(self):
        """Establish SSH connection with connection pooling using ConnectionPool singleton."""
        try:
            # Use ConnectionPool singleton for connection management
            pool = ConnectionPool()
            
            # Get or create connection - pool handles all the logic
            self.ssh, self.sftp = pool.get_connection(
                hostname=self.hostname,
                port=self.port,
                username=self.username,
                password=self.password,
                key=self.temp_key
            )
            
            self.transport = self.ssh.get_transport()
            return True
            
        except paramiko.AuthenticationException as e:
            self.signals.message.emit(
                self.transfer_id, 
                f"Authentication failed for {self.hostname}: {e}"
            )
            return False
        except paramiko.SSHException as e:
            self.signals.message.emit(
                self.transfer_id, 
                f"SSH connection error to {self.hostname}: {e}"
            )
            return False
        except (OSError, IOError) as e:
            self.signals.message.emit(
                self.transfer_id, 
                f"Connection to {self.hostname} failed: {e}"
            )
            return False

    def convert_unit(self, size_in_bytes: int, unit: SIZE_UNIT):
        """Convert the size from bytes to other units like KB, MB or GB"""
        if unit == SIZE_UNIT.KB:
            return size_in_bytes/1024
        elif unit == SIZE_UNIT.MB:
            return size_in_bytes/(1024*1024)
        elif unit == SIZE_UNIT.GB:
            return size_in_bytes/(1024*1024*1024)
        else:
            return size_in_bytes

    def progress(self, transferred: int, total: int):
        """Progress callback with aggressive rate limiting to prevent timer leaks"""
        if self._stop_flag:
            raise Exception("Transfer interrupted")

        # Count progress calls for debugging
        self._progress_count += 1

        # ---- compute speed & eta ----
        now = time.time()
        if self._last_time is None:
            speed_bps = 0.0
            eta_sec = 0.0
        else:
            delta_t = now - self._last_time
            delta_b = transferred - self._last_bytes
            speed_bps = delta_b / max(delta_t, 1e-6)
            # Additional protection for ETA calculation
            if speed_bps <= 0 or total <= transferred:
                eta_sec = 0.0
            else:
                eta_sec = (total - transferred) / speed_bps

        self._last_bytes = transferred
        self._last_time = now

        # More aggressive rate limiting - emit only if enough time has passed
        # AND we haven't hit 100% (always emit the final progress)
        percent = int(transferred * 100 / max(total, 1))
        
        if (now - self._last_emit_time >= self._emit_interval) or (percent >= 100):
            try:
                # Use Qt's QueuedConnection to prevent signal buildup
                self.signals.progress.emit(self.transfer_id, percent, speed_bps, eta_sec, transferred, total)
                self._last_emit_time = now
            except RuntimeError as e:
                # If signal emission fails, don't crash the transfer
                print(f"Progress signal emission failed: {e}")

    def _transfer_with_timeout(self, transfer_func, *args, resume=False):
        """Helper used by both get and put with proper cleanup"""
        watchdog_lock = threading.Lock()
        watchdog_time = [time.time()]
        watchdog_running = [True]

        def watchdog():
            while watchdog_running[0]:
                time.sleep(5)
                with watchdog_lock:
                    if time.time() - watchdog_time[0] > 60:
                        # Timeout occurred
                        break

        # watchdog thread
        wd_thread = threading.Thread(target=watchdog, daemon=True)
        wd_thread.start()

        # progress callback that re-uses the same function object
        def progress_wrapper(transferred, total):
            if watchdog_running[0]:  # Only update if watchdog is still running
                with watchdog_lock:
                    watchdog_time[0] = time.time()
                self.progress(transferred, total)

        try:
            # Perform the actual transfer
            if len(args) >= 2:
                transfer_func(args[0], args[1], callback=progress_wrapper)
            else:
                transfer_func(*args, callback=progress_wrapper)
                
        except (OSError, IOError, Exception) as exc:
            # Handle cancellation gracefully - don't show scary error messages
            if self._stop_flag:
                self.signals.message.emit(
                    self.transfer_id,
                    f"Transfer cancelled"
                )
                put_response(self.transfer_id, "cancelled", "Transfer cancelled by user")
            else:
                self.signals.message.emit(
                    self.transfer_id,
                    f"Transfer interrupted"
                )
                put_response(self.transfer_id, "error", str(exc))
            return
        finally:
            # Stop watchdog
            watchdog_running[0] = False
            
            # Clear the callback to prevent further progress updates
            try:
                if hasattr(transfer_func, '__self__') and hasattr(transfer_func.__self__, 'set_callback'):
                    transfer_func.__self__.set_callback(None)
            except (AttributeError, RuntimeError) as e:
                pass

    def _cleanup_connections(self, error=False):
        """Release connection references or invalidate pooled connection."""
        if self.sftp:
            try:
                pool = ConnectionPool()
                if error:
                    pool.close_connection(self.hostname, self.port, self.username)
                else:
                    pool.release_connection(self.hostname, self.port, self.username, self.sftp)
            except Exception as e:
                pass
        
        # Clear references
        self.sftp = None
        self.ssh = None
        self.transport = None

    def run(self):
        resume = False
        error_occurred = False

        try:
            # Establish connection (includes SFTP channel from pool)
            if not self._connect():
                logger.error(f"Transfer {self.transfer_id}: Connection failed")
                put_response(self.transfer_id, "error", "Connection failed")
                return

            # Strip decorative characters from source and destination paths
            clean_source = strip_decorative_chars(self.job_source)
            clean_destination = strip_decorative_chars(self.job_destination)

            if self.command == "resume":
                resume = True

            logger.debug(f"Transfer {self.transfer_id}: {self.command} {clean_source} → {clean_destination}")

            # Handle different transfer types
            if self.is_source_remote and not self.is_destination_remote:
                # Download
                self.signals.message.emit(
                    self.transfer_id,
                    f"Downloading {clean_source} → {clean_destination}"
                )
                
                if resume:
                    self._transfer_with_timeout(self._resume_download, clean_source, clean_destination)
                else:
                    self._transfer_with_timeout(self.sftp.get, clean_source, clean_destination)
                
                # Only signal success if not already handled (e.g., cancelled)
                if not self._stop_flag:
                    # Signal successful download
                    logger.info(f"Transfer {self.transfer_id}: Download complete {clean_source} → {clean_destination}")
                    put_response(self.transfer_id, "success", clean_destination)

            elif self.is_destination_remote and not self.is_source_remote:
                # Upload
                self.signals.message.emit(
                    self.transfer_id,
                    f"Uploading {clean_source} → {clean_destination}"
                )
                if resume:
                    self._transfer_with_timeout(self._resume_upload, clean_source, clean_destination)
                else:
                    self._transfer_with_timeout(self.sftp.put, clean_source, clean_destination)
                
                # Only signal success if not already handled (e.g., cancelled)
                if not self._stop_flag:
                    # Signal successful upload
                    logger.info(f"Transfer {self.transfer_id}: Upload complete {clean_source} → {clean_destination}")
                    put_response(self.transfer_id, "success", clean_destination)

            elif self.is_source_remote and self.is_destination_remote:
                # Remote command execution
                self._handle_remote_command()

        except Exception as e:
            error_occurred = True
            logger.error(f"Transfer {self.transfer_id} failed: {e}")
            self.signals.message.emit(self.transfer_id, f"Transfer failed: {e}")
            put_response(self.transfer_id, "error", str(e))
        finally:
            # Always cleanup and emit finished signal
            self._cleanup_connections(error=error_occurred)
            self.signals.finished.emit(self.transfer_id)

    def _handle_remote_command(self):
        """Handle remote SFTP commands"""
        try:
            if self.command == "mkdir":
                self.sftp.mkdir(self.job_destination)
                put_response(self.transfer_id, "success", self.job_destination)

            elif self.command == "listdir_attr":
                try:
                    response = self.sftp.listdir_attr(self.job_source)
                    put_response(self.transfer_id, "success", response)
                except (OSError, IOError, paramiko.SSHException) as listdir_err:
                    put_response(self.transfer_id, "error", str(listdir_err))

            elif self.command == "listdir":
                response = self.sftp.listdir(self.job_source)
                put_response(self.transfer_id, "success", response)

            elif self.command == "chdir":
                try:
                    self.sftp.listdir(self.job_source)
                    put_response(self.transfer_id, "success", self.job_source)
                except (OSError, IOError, paramiko.SSHException) as e:
                    error_msg = f"Cannot access directory {self.job_source}: {e}"
                    put_response(self.transfer_id, "error", error_msg)

            elif self.command == "rmdir":
                self.sftp.rmdir(self.job_source)
                put_response(self.transfer_id, "success", self.job_source)

            elif self.command == "stat":
                try:
                    attr = self.sftp.stat(self.job_source)
                    put_response(self.transfer_id, "success", attr)
                except (OSError, IOError, paramiko.SSHException) as e:
                    error_msg = f"Stat failed for {self.job_source}: {e}"
                    put_response(self.transfer_id, "error", error_msg)

            elif self.command == "remove":
                self.sftp.remove(self.job_source)
                put_response(self.transfer_id, "success", self.job_source)

            elif self.command == "getcwd":
                try:
                    stdin, stdout, stderr = self.ssh.exec_command('pwd')
                    error_output = stderr.read()
                    if error_output:
                        error_msg = error_output.decode()
                        self.signals.message.emit(self.transfer_id, f"{self.command} operation failed: {error_msg}")
                        put_response(self.transfer_id, "error", error_msg)
                    else:
                        getcwd_path = stdout.read().strip().decode()
                        put_response(self.transfer_id, "success", getcwd_path)
                except (OSError, IOError, paramiko.SSHException) as e:
                    error_msg = f"getcwd failed: {e}"
                    put_response(self.transfer_id, "error", error_msg)

        except (OSError, IOError, paramiko.SSHException) as e:
            self.signals.message.emit(self.transfer_id, f"{self.command} operation failed: {e}")
            put_response(self.transfer_id, "error", str(e))

    def stop_transfer(self):
        """Stop the transfer by closing the connection to abort ongoing transfer"""
        self._stop_flag = True
        self.signals.message.emit(self.transfer_id, f"Transfer {self.transfer_id} stopping...")
        self.signals.finished.emit(self.transfer_id)
        self._cleanup_connections(error=True)
