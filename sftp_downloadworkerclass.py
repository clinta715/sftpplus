from PyQt6.QtCore import QRunnable, QObject, pyqtSignal
import enum
import queue
from icecream import ic
import paramiko
import base64
import re
import os
import time
import threading
import shlex

from sftp_config import MAX_TRANSFERS
from sftp_connection_pool import ConnectionPool


def strip_decorative_chars(filename):
    """Strip decorative characters from the filename."""
    # Remove leading emoji characters and spaces
    filename = re.sub(r'^[\U0001F000-\U0001F9FF\s]+', '', filename)
    # Remove any remaining leading or trailing whitespace
    return filename.strip()


class WorkerSignals(QObject):
    progress = pyqtSignal(int, int, float, float)   # transfer_id, percent, speed_bytes_per_sec, eta_seconds
    finished = pyqtSignal(int)
    message  = pyqtSignal(int, str)

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

class transferSignals(QObject):
    showhide = pyqtSignal()

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
        # SECURITY WARNING: Base64 encoding provides NO SECURITY - it is NOT encryption!
        # This is merely obfuscation. Do NOT serialize jobs to disk or logs.
        # Passwords should be passed through secure memory channels only.
        # TODO: Implement proper encryption or avoid serializing credentials entirely
        return {
            "source_path": self.source_path,
            "is_source_remote": self.is_source_remote,
            "destination_path": self.destination_path,
            "is_destination_remote": self.is_destination_remote,
            "hostname": self.hostname,
            "username": self.username,
            "password": base64.b64encode(self.password.encode()).decode(),  # NOT secure - only obfuscation!
            "port": self.port,
            "command": self.command,
            "job_id": self.job_id,
            "key" : self.key
        }

    @staticmethod
    def from_dict(data):
        # SECURITY WARNING: Base64 decoding provides NO SECURITY
        data["password"] = base64.b64decode(data["password"]).decode()
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
            ic(f"Queue cleanup warning for job {self.job_id}: {e}")
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
        ic("load_private_key: attempting to load key")
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
                ic(e)
                continue
                
        # All attempts failed
        self.signals.message.emit(
            self.transfer_id, 
            "Failed to load private key: unsupported format or invalid key data"
        )
        return None

    def _connect(self):
        """Establish SSH connection with connection pooling using ConnectionPool singleton."""
        ic(f"_connect: Starting for {self.hostname}:{self.port} user={self.username}")
        
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
            ic(f"_connect: Successfully connected using connection pool")
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
                self.signals.progress.emit(self.transfer_id, percent, speed_bps, eta_sec)
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
                ic(f"Transfer {self.transfer_id}: Performing transfer - func={transfer_func.__name__}")
                ic(f"Transfer {self.transfer_id}: args[0]={args[0]}")
                ic(f"Transfer {self.transfer_id}: args[1]={args[1]}")
                transfer_func(args[0], args[1], callback=progress_wrapper)
            else:
                transfer_func(*args, callback=progress_wrapper)
                
        except (OSError, IOError, paramiko.SSHException) as exc:
            ic(f"Transfer {self.transfer_id}: Exception during transfer - {type(exc).__name__}: {exc}")
            ic(f"Transfer {self.transfer_id}: Full exception traceback:")
            import traceback
            traceback.print_exc()
            self.signals.message.emit(
                self.transfer_id,
                f"Transfer {self.transfer_id} was interrupted: {exc}"
            )
            raise
        finally:
            # Stop watchdog
            watchdog_running[0] = False
            
            # Clear the callback to prevent further progress updates
            try:
                if hasattr(transfer_func, '__self__') and hasattr(transfer_func.__self__, 'set_callback'):
                    transfer_func.__self__.set_callback(None)
            except (AttributeError, RuntimeError) as e:
                ic(f"_perform_transfer: Error clearing callback: {e}")

    def _cleanup_connections(self):
        """Release connection references and invalidate the pooled connection after file transfers."""
        # After file transfers, invalidate the connection so subsequent commands get fresh one
        # File transfers can leave the SFTP channel in a blocked state
        if self.is_source_remote != self.is_destination_remote:  # File transfer, not just command
            try:
                pool = ConnectionPool()
                pool.close_connection(self.hostname, self.port, self.username)
                ic(f"Invalidated connection after file transfer for {self.hostname}:{self.port}")
            except Exception as e:
                ic(f"Error invalidating connection: {e}")
        
        # Clear references
        self.sftp = None
        self.ssh = None
        self.transport = None

    def run(self):
        resume = False
        resume_all = False

        try:
            # Debug: Log worker start
            ic(f"DownloadWorker started: transfer_id={self.transfer_id}, command={self.command}, source={self.job_source}")
            ic(f"DownloadWorker: hostname={self.hostname}, port={self.port}, username={self.username}")
            
            # Establish connection (includes SFTP channel from pool)
            ic(f"DownloadWorker: Calling _connect()")
            if not self._connect():
                ic(f"Connection failed for transfer {self.transfer_id}")
                put_response(self.transfer_id, "error", "Connection failed")
                return
            ic(f"DownloadWorker: _connect() returned True, sftp ready")

            # Strip decorative characters from source and destination paths
            clean_source = strip_decorative_chars(self.job_source)
            clean_destination = strip_decorative_chars(self.job_destination)
            
            ic(f"Transfer {self.transfer_id}: clean_source={clean_source}")
            ic(f"Transfer {self.transfer_id}: clean_destination={clean_destination}")
            ic(f"Processing: source_remote={self.is_source_remote}, dest_remote={self.is_destination_remote}, command={self.command}")

            if self.command == "resume":
                resume = True

            # Handle different transfer types
            if self.is_source_remote and not self.is_destination_remote:
                # Download
                self.signals.message.emit(
                    self.transfer_id,
                    f"Downloading {clean_source} → {clean_destination}"
                )
                ic(f"Transfer {self.transfer_id}: Opening SFTP channel for download")
                ic(f"Transfer {self.transfer_id}: Full paths - source={clean_source}, dest={clean_destination}")
                
                # Debug: List the remote directory to verify file exists
                remote_dir = os.path.dirname(clean_source)
                remote_file = os.path.basename(clean_source)
                ic(f"Transfer {self.transfer_id}: Checking remote_dir={remote_dir}, remote_file={remote_file}")
                
                if resume:
                    self._transfer_with_timeout(self._resume_download, clean_source, clean_destination)
                else:
                    ic(f"Transfer {self.transfer_id}: Calling sftp.get({clean_source}, {clean_destination})")
                    self._transfer_with_timeout(self.sftp.get, clean_source, clean_destination)
                
                # Signal successful download
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
                
                # Signal successful upload
                put_response(self.transfer_id, "success", clean_destination)

            elif self.is_source_remote and self.is_destination_remote:
                # Remote command execution
                ic(f"Handling remote command: {self.command}")
                ic(f"Remote command - about to call _handle_remote_command")
                self._handle_remote_command()
                ic(f"Remote command - _handle_remote_command returned")
            else:
                ic(f"No matching transfer type: src_remote={self.is_source_remote}, dst_remote={self.is_destination_remote}")

        except (OSError, IOError, paramiko.SSHException) as e:
            self.signals.message.emit(self.transfer_id, f"Transfer failed: {e}")
            put_response(self.transfer_id, "error", str(e))
        finally:
            # Always cleanup and emit finished signal
            self._cleanup_connections()
            self.signals.finished.emit(self.transfer_id)

    def _handle_remote_command(self):
        """Handle remote SFTP commands"""
        ic(f"_handle_remote_command: Starting - command={self.command}, source={self.job_source}")
        ic(f"_handle_remote_command: sftp object = {self.sftp}")
        ic(f"_handle_remote_command: ssh object = {self.ssh}")
        
        try:
            ic(f"Executing command: {self.command}, source: {self.job_source}, dest: {self.job_destination}")
            
            if self.command == "mkdir":
                ic(f"Creating directory: {self.job_destination}")
                self.sftp.mkdir(self.job_destination)
                put_response(self.transfer_id, "success", self.job_destination)

            elif self.command == "listdir_attr":
                ic(f"Listing directory attributes: {self.job_source}")
                ic(f"About to call sftp.listdir_attr({self.job_source})")
                try:
                    response = self.sftp.listdir_attr(self.job_source)
                    ic(f"listdir_attr returned {len(response)} items")
                    put_response(self.transfer_id, "success", response)
                except (OSError, IOError, paramiko.SSHException) as listdir_err:
                    ic(f"listdir_attr FAILED: {listdir_err}")
                    put_response(self.transfer_id, "error", str(listdir_err))

            elif self.command == "listdir":
                ic(f"Listing directory: {self.job_source}")
                response = self.sftp.listdir(self.job_source)
                put_response(self.transfer_id, "success", response)

            elif self.command == "chdir":
                ic(f"Changing directory to: {self.job_source}")
                # Note: chdir doesn't actually change the server's working directory permanently
                # It just validates that the path exists and is accessible
                # The actual path tracking is done in the client
                try:
                    # Test if directory exists by trying to list it
                    self.sftp.listdir(self.job_source)
                    ic(f"Directory exists and is accessible: {self.job_source}")
                    put_response(self.transfer_id, "success", self.job_source)
                except (OSError, IOError, paramiko.SSHException) as e:
                    error_msg = f"Cannot access directory {self.job_source}: {e}"
                    ic(error_msg)
                    put_response(self.transfer_id, "error", error_msg)

            elif self.command == "rmdir":
                ic(f"Removing directory: {self.job_source}")
                self.sftp.rmdir(self.job_source)
                put_response(self.transfer_id, "success", self.job_source)

            elif self.command == "stat":
                ic(f"Getting stat for: {self.job_source}")
                try:
                    attr = self.sftp.stat(self.job_source)
                    put_response(self.transfer_id, "success", attr)
                except (OSError, IOError, paramiko.SSHException) as e:
                    error_msg = f"Stat failed for {self.job_source}: {e}"
                    ic(error_msg)
                    put_response(self.transfer_id, "error", error_msg)

            elif self.command == "remove":
                ic(f"Removing file: {self.job_source}")
                self.sftp.remove(self.job_source)
                put_response(self.transfer_id, "success", self.job_source)

            elif self.command == "getcwd":
                # Get current working directory
                # Note: This creates a new SSH session which always starts in the home directory
                # So it will return the home directory, not the SFTP session's current directory
                try:
                    stdin, stdout, stderr = self.ssh.exec_command('pwd')
                    error_output = stderr.read()
                    if error_output:
                        error_msg = error_output.decode()
                        ic("Error:", error_msg)
                        self.signals.message.emit(self.transfer_id, f"{self.command} operation failed: {error_msg}")
                        put_response(self.transfer_id, "error", error_msg)
                    else:
                        getcwd_path = stdout.read().strip().decode()
                        ic(f"getcwd: returning home directory: {getcwd_path}")
                        put_response(self.transfer_id, "success", getcwd_path)
                except (OSError, IOError, paramiko.SSHException) as e:
                    error_msg = f"getcwd failed: {e}"
                    ic(error_msg)
                    put_response(self.transfer_id, "error", error_msg)

        except (OSError, IOError, paramiko.SSHException) as e:
            self.signals.message.emit(self.transfer_id, f"{self.command} operation failed: {e}")
            put_response(self.transfer_id, "error", str(e))

    def stop_transfer(self):
        """Stop the transfer gracefully"""
        self._stop_flag = True
        self.signals.message.emit(self.transfer_id, f"Transfer {self.transfer_id} stopping...")
        self.signals.finished.emit(self.transfer_id)
        self._cleanup_connections()