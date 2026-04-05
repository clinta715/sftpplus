from PySide6.QtWidgets import QInputDialog, QMessageBox, QApplication
from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool, QMutex, QWaitCondition
from sftp_qt_compat import Qt
from sftp_creds import get_credentials, create_random_integer, sanitize_error_message
from sftp_downloadworkerclass import add_sftp_job
from sftp_preferences import get_preferences
from sftp_connection_pool import get_connection_pool
from sftp_session import get_session_manager
from sftp_logging import get_logger
import os
import stat
import time

logger = get_logger(__name__)


def _safe_emit(signal, *args):
    """Emit a signal safely, catching RuntimeError if the signal source was deleted."""
    try:
        signal.emit(*args)
    except RuntimeError:
        pass


class DeletionWorker(QRunnable):
    """Worker that deletes files/directories in a background thread.

    Supports both remote (SFTP) and local deletion. For remote deletion,
    creates its own SFTPOperations instance. Emits progress signals for
    UI updates without blocking the main thread.
    """

    class Signals(QObject):
        progress = Signal(int, str)           # (index, current_filename)
        item_deleted = Signal(str)            # (path that was deleted)
        item_failed = Signal(str, str)        # (path, error_message)
        finished = Signal(int, int, list)     # (success_count, failure_count, failures)

    def __init__(self, paths, session_id=None, is_remote=True):
        super().__init__()
        self.setAutoDelete(False)
        self.paths = paths
        self.session_id = session_id
        self.is_remote = is_remote
        self.signals = self.Signals()
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        success_count = 0
        failure_count = 0
        failures = []

        if self.is_remote:
            self._run_remote(success_count, failure_count, failures)
        else:
            self._run_local(success_count, failure_count, failures)

    def _run_local(self, success_count, failure_count, failures):
        import shutil

        for i, path in enumerate(self.paths):
            if self._cancel_requested:
                break

            _safe_emit(self.signals.progress, i, os.path.basename(path))

            try:
                if not os.path.exists(path):
                    failure_count += 1
                    failures.append((path, "Not found"))
                    continue

                if os.path.isfile(path):
                    os.remove(path)
                else:
                    shutil.rmtree(path)

                success_count += 1
                _safe_emit(self.signals.item_deleted, path)
            except (OSError, IOError, RuntimeError) as e:
                failure_count += 1
                failures.append((path, str(e)))
                _safe_emit(self.signals.item_failed, path, str(e))

        _safe_emit(self.signals.finished, success_count, failure_count, failures)

    def _run_remote(self, success_count, failure_count, failures):
        from sftp_operations import SFTPOperations
        from sftp_creds import get_credentials

        creds = get_credentials(self.session_id)
        ops = SFTPOperations(
            hostname=creds.get('hostname', ''),
            username=creds.get('username', ''),
            password=creds.get('password', ''),
            port=creds.get('port', 22),
            key=creds.get('key')
        )

        try:
            for i, remote_path in enumerate(self.paths):
                if self._cancel_requested:
                    break

                _safe_emit(self.signals.progress, i, os.path.basename(remote_path))

                try:
                    if not ops.exists(remote_path):
                        failure_count += 1
                        failures.append((remote_path, "Not found"))
                        continue

                    if ops.is_file(remote_path):
                        ops.remove(remote_path)
                        success_count += 1
                        _safe_emit(self.signals.item_deleted, remote_path)
                    else:
                        self._remove_remote_dir_recursive(ops, remote_path)
                        success_count += 1
                        _safe_emit(self.signals.item_deleted, remote_path)
                except PermissionError as e:
                    failure_count += 1
                    failures.append((remote_path, str(e)))
                    _safe_emit(self.signals.item_failed, remote_path, str(e))
                except (OSError, IOError, RuntimeError) as e:
                    failure_count += 1
                    failures.append((remote_path, str(e)))
                    _safe_emit(self.signals.item_failed, remote_path, str(e))
                except Exception as e:
                    failure_count += 1
                    failures.append((remote_path, str(e)))
                    _safe_emit(self.signals.item_failed, remote_path, str(e))

            _safe_emit(self.signals.finished, success_count, failure_count, failures)
        finally:
            ops.close()

    def _remove_remote_dir_recursive(self, ops, remote_path, _depth=0):
        """Recursively remove a remote directory and its contents"""
        if self._cancel_requested:
            return
        
        if _depth > 100:
            return

        try:
            items = ops.list_attr(remote_path)
        except (OSError, IOError, RuntimeError):
            return
        except Exception:
            return
        
        # Items are dicts with 'filename' and 'st_mode' keys
        files = [item for item in items if stat.S_ISREG(item['st_mode'])]
        dirs = [item for item in items if stat.S_ISDIR(item['st_mode'])]

        for entry in files:
            if self._cancel_requested:
                return
            entry_path = os.path.join(remote_path, entry['filename'])
            try:
                ops.remove(entry_path)
            except (PermissionError, OSError):
                continue
            except Exception:
                continue

        for entry in dirs:
            if self._cancel_requested:
                return
            entry_path = os.path.join(remote_path, entry['filename'])
            try:
                self._remove_remote_dir_recursive(ops, entry_path, _depth + 1)
            except Exception:
                pass

        try:
            ops.rmdir(remote_path)
        except (PermissionError, OSError):
            pass


class TreePopulateWorker(QRunnable):
    """Worker that populates tree children in background"""
    
    class Signals(QObject):
        finished = Signal(object, list)  # (path, directories)
        error = Signal(str, str)  # (path, error_message)
    
    def __init__(self, session_id, path, is_remote=True):
        super().__init__()
        self.session_id = session_id
        self.path = path
        self.is_remote = is_remote
        self.signals = self.Signals()
        
    def run(self):
        try:
            if self.is_remote:
                from sftp_operations import SFTPOperations
                from sftp_creds import get_credentials
                creds = get_credentials(self.session_id)
                ops = SFTPOperations(
                    hostname=creds.get('hostname', ''),
                    username=creds.get('username', ''),
                    password=creds.get('password', ''),
                    port=creds.get('port', 22),
                    key=creds.get('key')
                )
                try:
                    items = ops.list_attr(self.path)
                    dirs = []
                    # Items are now dicts, not SFTPAttribute objects
                    for item in items:
                        if stat.S_ISDIR(item['st_mode']):
                            dirs.append(item)
                    dirs.sort(key=lambda x: x['filename'].lower())
                    _safe_emit(self.signals.finished, self.path, dirs)
                finally:
                    ops.close()
            else:
                items = os.listdir(self.path)
                dirs = []
                for name in items:
                    full_path = os.path.join(self.path, name)
                    if os.path.isdir(full_path):
                        dirs.append(name)
                dirs.sort(key=lambda x: x.lower())
                _safe_emit(self.signals.finished, self.path, dirs)
        except (OSError, IOError, RuntimeError) as e:
            _safe_emit(self.signals.error, self.path, sanitize_error_message(str(e)))


class FileListWorker(QRunnable):
    """Worker that fetches file list with attributes in background"""
    
    class Signals(QObject):
        finished = Signal(str, list)  # (path, items)
        error = Signal(str, str)     # (path, error_message)
    
    def __init__(self, session_id, path, is_remote=True):
        super().__init__()
        self.session_id = session_id
        self.path = path
        self.is_remote = is_remote
        self.signals = self.Signals()
        
    def run(self):
        items = []
        error_msg = None
        try:
            if self.is_remote:
                from sftp_operations import SFTPOperations
                from sftp_creds import get_credentials
                creds = get_credentials(self.session_id)
                ops = SFTPOperations(
                    hostname=creds.get('hostname', ''),
                    username=creds.get('username', ''),
                    password=creds.get('password', ''),
                    port=creds.get('port', 22),
                    key=creds.get('key')
                )
                try:
                    raw_items = ops.list_attr(self.path)
                    for item in raw_items:
                        items.append({
                            'filename': item['filename'],
                            'st_size': item['st_size'],
                            'st_mode': item['st_mode'],
                            'st_mtime': item['st_mtime']
                        })
                finally:
                    ops.close()
            else:
                import os
                import stat
                from dataclasses import dataclass
                
                @dataclass
                class LocalAttr:
                    filename: str
                    st_size: int
                    st_mode: int
                    st_mtime: int
                
                items = []
                for name in os.listdir(self.path):
                    full_path = os.path.join(self.path, name)
                    st = os.stat(full_path)
                    items.append(LocalAttr(name, st.st_size, st.st_mode, int(st.st_mtime)))
        except Exception as e:
            error_msg = sanitize_error_message(str(e))
        
        if error_msg:
            _safe_emit(self.signals.error, self.path, error_msg)
        else:
            _safe_emit(self.signals.finished, self.path, items)


class FilePreviewWorker(QRunnable):
    """Worker that downloads file for preview in background"""
    
    class Signals(QObject):
        finished = Signal(str, str)  # (temp_path, original_path)
        error = Signal(str, str)  # (original_path, error_message)
    
    def __init__(self, session_id, remote_path, local_temp_path, is_remote=True):
        super().__init__()
        self.session_id = session_id
        self.remote_path = remote_path
        self.local_temp_path = local_temp_path
        self.is_remote = is_remote
        self.signals = self.Signals()
        
    def run(self):
        try:
            if self.is_remote:
                from sftp_operations import SFTPOperations
                from sftp_creds import get_credentials
                creds = get_credentials(self.session_id)
                ops = SFTPOperations(
                    hostname=creds.get('hostname', ''),
                    username=creds.get('username', ''),
                    password=creds.get('password', ''),
                    port=creds.get('port', 22),
                    key=creds.get('key')
                )
                try:
                    ops.download(self.remote_path, self.local_temp_path)
                    _safe_emit(self.signals.finished, self.local_temp_path, self.remote_path)
                finally:
                    ops.close()
        except (OSError, IOError, RuntimeError) as e:
            _safe_emit(self.signals.error, self.remote_path, sanitize_error_message(str(e)))


class TraversalSignals(QObject):
    """Signals for the directory traversal worker"""
    status = Signal(str)
    job_added = Signal(str)
    prompt_overwrite = Signal(str)
    finished = Signal()
    finished_with_files = Signal(list)  # Emits list of (source_path, dest_path, command) when done
    error = Signal(str)
    # Discovery progress: (files_found_so_far, directories_scanned_so_far)
    discovery_progress = Signal(int, int)


class TraversalWorker(QRunnable):
    """Worker that recursively traverses directories in the background"""
    
    def __init__(self, session_id, source_dir, dest_dir, is_source_remote, is_dest_remote,
                 skip_all=False, overwrite_all=False, resume_all=False, 
                 follow_symlinks=False, parent_signals=None):
        super().__init__()
        self.session_id = session_id
        self.source_dir = source_dir
        self.dest_dir = dest_dir
        self.is_source_remote = is_source_remote
        self.is_dest_remote = is_dest_remote
        self.skip_all = skip_all
        self.overwrite_all = overwrite_all
        self.resume_all = resume_all
        self.follow_symlinks = follow_symlinks
        # Use parent signals if provided, otherwise create new ones
        if parent_signals:
            self.signals = parent_signals
        else:
            self.signals = TraversalSignals()
        
        # For cross-thread prompting
        self.prompt_mutex = QMutex()
        self.prompt_cond = QWaitCondition()
        self.prompt_result = None
        
        # Credentials for jobs
        self.creds = get_credentials(session_id)
        
        # Collect files for batch transfer (instead of streaming)
        self._collected_files = []  # List of (source_path, dest_path, command)
        
        # SFTPOperations for listing - created lazily when needed (for remote directories)
        self.ops = None
        
        self._discovery_channel = False
        self._cancelled = False
        self._files_found = 0
        self._dirs_scanned = 0
    
    def _get_ops(self):
        """Lazy initialization of SFTPOperations - only needed for remote directories"""
        if self.ops is None:
            from sftp_operations import SFTPOperations
            self.ops = SFTPOperations(
                hostname=self.creds.get('hostname', ''),
                username=self.creds.get('username', ''),
                password=self.creds.get('password', ''),
                port=self.creds.get('port', 22),
                key=self.creds.get('key')
            )
        return self.ops

    def cancel(self):
        """Cancel the traversal"""
        self._cancelled = True
        # Also wake up if waiting for prompt
        self.set_prompt_result("cancel")

    def set_prompt_result(self, result):
        """Called by UI thread to provide result of overwrite prompt"""
        self.prompt_mutex.lock()
        self.prompt_result = result
        self.prompt_cond.wakeAll()
        self.prompt_mutex.unlock()

    def run(self):
        if self._cancelled: 
            return
        
        try:
            _safe_emit(self.signals.status, f"Starting traversal of {self.source_dir}...")
            
            fast_success = False
            if self.is_source_remote:
                try:
                    fast_success = self._traverse_remote_find(self.source_dir, self.dest_dir)
                except Exception:
                    fast_success = False
            
            if not fast_success and not self._cancelled:
                self._traverse(self.source_dir, self.dest_dir)
        except Exception as e:
            _safe_emit(self.signals.error, str(e))
        finally:
            if self.ops:
                self.ops.close()
        
        if not self._cancelled:
            _safe_emit(self.signals.finished_with_files, list(self._collected_files))
            _safe_emit(self.signals.finished)

    def _traverse_remote_find(self, source_dir, dest_dir):
        """
        Fast remote traversal using a single SSH find command.
        Returns True on success, False to fall back to SFTP traversal.
        """
        import shlex
        
        source_norm = source_dir.rstrip('/')
        follow_flag = '-L ' if self.follow_symlinks else ''
        find_cmd = (
            f"find {follow_flag}{shlex.quote(source_norm)}"
            f" -printf '%y\\0%p\\0'"
        )
        
        _safe_emit(self.signals.status, f"Fast scanning: {source_dir}")
        
        exit_code, output, error = self._get_ops().exec_command(find_cmd, timeout=300)
        
        if exit_code != 0:
            return False
        
        if not output or not output.strip('\0'):
            return True
        
        entries = output.split('\0')
        
        for i in range(0, len(entries) - 1, 2):
            if self._cancelled:
                return True
            
            entry_type = entries[i].strip()
            path = entries[i + 1].strip()
            
            if not path or not entry_type:
                continue
            
            if path == source_norm or path == source_norm + '/':
                continue
            
            if not path.startswith(source_norm + '/'):
                continue
            
            relative = path[len(source_norm) + 1:]
            if not relative:
                continue
            
            dest_path = os.path.join(dest_dir, relative)
            
            if entry_type == 'l':
                if not self.follow_symlinks:
                    continue
            elif entry_type == 'd':
                self._dirs_scanned += 1
                _safe_emit(self.signals.discovery_progress, self._files_found, self._dirs_scanned)
                continue
            elif entry_type != 'f':
                continue
            
            command = "upload" if self.is_dest_remote else "download"
            self._collected_files.append((path, dest_path, command))
            self._files_found += 1
            _safe_emit(self.signals.discovery_progress, self._files_found, self._dirs_scanned)
        
        _safe_emit(self.signals.status,
            f"Found {self._files_found} files in {self._dirs_scanned} directories"
        )
        return True

    def _traverse(self, source_dir, dest_dir, _depth=0):
        if self._cancelled:
            return
            
        if _depth > 100:
            _safe_emit(self.signals.error, f"Maximum directory depth exceeded at: {source_dir}")
            return
        
        _safe_emit(self.signals.status, f"Scanning: {source_dir}")
        self._dirs_scanned += 1
        
        if self.is_source_remote:
            try:
                raw_files = self._get_ops().list_attr(source_dir)
                # Filter out '.' and '..' which can cause infinite recursion
                # Items are now dicts, not SFTPAttribute objects
                files = [f for f in raw_files if f['filename'] not in ['.', '..']]
            except Exception as e:
                error_msg = sanitize_error_message(str(e))
                # Check if it's a connection error
                if "connection" in error_msg.lower() or "dropped" in error_msg.lower() or "timeout" in error_msg.lower():
                    _safe_emit(self.signals.error, f"Connection error while scanning {source_dir}: {error_msg}")
                    self._cancelled = True
                return
        else:
            try:
                files = os.listdir(source_dir)
            except (OSError, IOError) as e:
                return
            
        for entry in files:
            if self._cancelled: return
            if self.is_source_remote:
                # Items are now dicts, not SFTPAttribute objects
                filename = entry['filename']
                if filename in ['.', '..']: continue
                # Skip symlinks unless follow_symlinks is enabled
                if not self.follow_symlinks and stat.S_ISLNK(entry['st_mode']):
                    continue
                is_dir = stat.S_ISDIR(entry['st_mode'])
            else:
                filename = entry
                if filename in ['.', '..']: continue
                full_path = os.path.join(source_dir, filename)
                # Skip symlinks unless follow_symlinks is enabled
                if not self.follow_symlinks and os.path.islink(full_path):
                    continue
                is_dir = os.path.isdir(full_path)
                
            source_path = os.path.join(source_dir, filename)
            dest_path = os.path.join(dest_dir, filename)
            
            if is_dir:
                if self._cancelled:
                    return
                self._traverse(source_path, dest_path, _depth + 1)
                continue
            
            # Just collect the file - no conflict checking during discovery
            # Conflict handling happens when transfers actually start
            command = "upload" if self.is_dest_remote else "download"
            
            # Add to collected files (skip prompts during discovery)
            # Conflict handling happens when transfers actually start
            command = "upload" if self.is_dest_remote else "download"
            
            # Add to collected files (skip prompts during discovery)
            self._collected_files.append((source_path, dest_path, command))
            self._files_found += 1
            _safe_emit(self.signals.discovery_progress, self._files_found, self._dirs_scanned)


class DirectTransferWorker(QRunnable):
    """Direct transfer worker using SFTPSessionAPI.execute() directly.
    
    This worker bypasses the legacy queue and uses SFTPSessionAPI directly
    for file transfers. It coexists with the legacy add_sftp_job() queue
    during the transition period.
    
    Signals:
        progress: (bytes_transferred, total_bytes, speed, eta)
        finished: (success_count, failure_count)
        error: (error_message)
        conflict: (transfer_id, dest_path, dest_type)
    """
    
    class Signals(QObject):
        progress = Signal(int, int, float, float)  # (bytes, total, speed, eta)
        finished = Signal(int, int)
        error = Signal(str)
        conflict = Signal(str, str, str)  # (transfer_id, dest_path, dest_type)
        retrying = Signal(int, int, str)  # (attempt, max_attempts, error_msg)
    
    def __init__(self, session_id, source_path, dest_path, 
                 is_source_remote, is_dest_remote, command):
        super().__init__()
        self.setAutoDelete(False)
        self.session_id = session_id
        self.source_path = source_path
        self.dest_path = dest_path
        self.is_source_remote = is_source_remote
        self.is_dest_remote = is_dest_remote
        self.command = command  # "upload" or "download"
        self.signals = self.Signals()
        self._cancel_requested = False
        self.transfer_id = None  # Set by caller
        
        # Conflict resolution
        self._conflict_mutex = QMutex()
        self._conflict_cond = QWaitCondition()
        self._conflict_result = None
    
    def cancel(self):
        self._cancel_requested = True
        # Also wake up if waiting for conflict resolution
        self.set_conflict_result("cancel")
    
    def set_conflict_result(self, result):
        """Called by UI thread to provide result of conflict prompt"""
        self._conflict_mutex.lock()
        self._conflict_result = result
        self._conflict_cond.wakeAll()
        self._conflict_mutex.unlock()

    def _wait_for_conflict_result(self):
        """Wait for UI thread to resolve conflict. Returns action string."""
        self._conflict_mutex.lock()
        # Wait up to 30 seconds for user response
        self._conflict_cond.wait(self._conflict_mutex, 30000)
        result = self._conflict_result
        self._conflict_result = None
        self._conflict_mutex.unlock()
        return result or "skip"

    def _check_destination_exists(self, sftp):
        """Check if destination file exists and resolve conflict if needed.
        Returns: "proceed", "skip", "resume", or "cancel"
        """
        dest_exists = False
        if self.is_dest_remote:
            try:
                sftp.stat(self.dest_path)
                dest_exists = True
            except (IOError, OSError):
                pass
        else:
            dest_exists = os.path.exists(self.dest_path)
        
        if not dest_exists:
            return "proceed"
        
        # Check global overwrite preference
        from sftp_preferences import get_preferences
        prefs = get_preferences()
        if prefs.get_bool("overwrite_on_transfer", False):
            return "proceed"
        
        # Signal conflict to UI and wait for resolution
        dest_type = "remote" if self.is_dest_remote else "local"
        _safe_emit(self.signals.conflict, self.transfer_id, self.dest_path, dest_type)
        action = self._wait_for_conflict_result()
        
        if action == "overwrite" or action == "overwrite_all":
            return "proceed"
        elif action == "resume" or action == "resume_all":
            return "resume"
        elif action in ("skip", "skip_all"):
            return "skip"
        elif action == "cancel":
            return "cancel"
        
        return "skip"

    def run(self):
        logger.debug(f"DirectTransferWorker.run() called for {self.source_path} -> {self.dest_path}")
        
        if self._cancel_requested:
            logger.debug("Worker cancelled before starting")
            return
        
        from sftp_creds import get_credentials
        from sftp_connection_pool import get_connection_pool
        
        logger.debug(f"Starting transfer: source={self.source_path}, dest={self.dest_path}, cmd={self.command}")
        
        max_retries = 5
        for attempt in range(max_retries):
            if self._cancel_requested:
                logger.debug("Worker cancelled before attempt")
                return
            
            try:
                self._do_transfer()
                return
            except Exception as e:
                is_transient = self._is_transient_error(e)
                if is_transient and attempt < max_retries - 1:
                    delay = 2.0 * (2 ** attempt)
                    logger.debug(f"Transient error on attempt {attempt + 1}/{max_retries}, retrying in {delay}s: {e}")
                    _safe_emit(self.signals.retrying, attempt + 2, max_retries, sanitize_error_message(str(e)))
                    time.sleep(delay)
                    continue
                
                logger.exception(f"Transfer exception (attempt {attempt + 1}/{max_retries}): {e}")
                error_msg = sanitize_error_message(str(e))
                _safe_emit(self.signals.error, error_msg)
                _safe_emit(self.signals.finished, 0, 1)
                return
        
        _safe_emit(self.signals.error, "Transfer failed after all retries")
        _safe_emit(self.signals.finished, 0, 1)
    
    def _is_transient_error(self, exc):
        """Check if an exception is likely transient and worth retrying."""
        exc_str = str(exc).lower()
        transient_indicators = [
            'channel', 'open failed', 'connect failed',
            'timed out', 'timeout', 'connection reset',
            'broken pipe', 'eof', 'transport',
            'session', 'not open', 'closed',
        ]
        return any(indicator in exc_str for indicator in transient_indicators)
    
    def _do_transfer(self):
        """Perform the actual transfer. Raises on failure for retry logic."""
        from sftp_creds import get_credentials
        from sftp_connection_pool import get_connection_pool
        
        ssh = None
        sftp = None
        start_time = time.time()
        last_update_time = start_time
        bytes_transferred = 0
        
        def progress_callback(bytes_sent, total_bytes):
            nonlocal bytes_transferred, last_update_time
            bytes_transferred = bytes_sent
            current_time = time.time()
            
            if current_time - last_update_time >= 0.2:
                elapsed = current_time - start_time
                speed = bytes_transferred / elapsed if elapsed > 0 else 0
                eta = (total_bytes - bytes_transferred) / speed if speed > 0 else 0
                logger.debug(f"Progress callback: {bytes_sent}/{total_bytes}, speed={speed:.0f}")
                _safe_emit(self.signals.progress, bytes_transferred, total_bytes, speed, eta)
                last_update_time = current_time
        
        pool = get_connection_pool()
        creds = get_credentials(self.session_id)
        
        try:
            ssh, sftp = pool.get_connection(
                hostname=creds.get('hostname', ''),
                port=creds.get('port', 22),
                username=creds.get('username', ''),
                password=creds.get('password', ''),
                key=creds.get('key')
            )
            
            sftp.get_channel().settimeout(300)
            
            resume = False
            action = self._check_destination_exists(sftp)
            if action == "skip":
                logger.debug(f"Skipping transfer as requested: {self.dest_path}")
                _safe_emit(self.signals.finished, 1, 0)
                return
            elif action == "resume":
                resume = True
            elif action == "cancel":
                logger.debug("Transfer cancelled during conflict resolution")
                return
            
            if self.command == "upload":
                if not os.path.exists(self.source_path):
                    raise FileNotFoundError(f"Local file not found: {self.source_path}")
                
                self._ensure_remote_dir(sftp, os.path.dirname(self.dest_path))
                
                logger.debug(f"Uploading {self.source_path} to {self.dest_path}")
                file_size = os.path.getsize(self.source_path)
                
                if resume:
                    existing_size = sftp.stat(self.dest_path).st_size if sftp.stat(self.dest_path) else 0
                    if existing_size >= file_size:
                        _safe_emit(self.signals.progress, file_size, file_size, 0, 0)
                        _safe_emit(self.signals.finished, 1, 0)
                        return
                    
                    with open(self.source_path, 'rb') as local_file:
                        local_file.seek(existing_size)
                        with sftp.open(self.dest_path, 'ab') as remote_file:
                            chunk_size = 32768
                            bytes_uploaded = existing_size
                            while bytes_uploaded < file_size:
                                if self._cancel_requested:
                                    logger.debug("Upload cancelled by flag")
                                    return
                                chunk = local_file.read(chunk_size)
                                if not chunk: break
                                remote_file.write(chunk)
                                bytes_uploaded += len(chunk)
                                progress_callback(bytes_uploaded, file_size)
                else:
                    sftp.put(self.source_path, self.dest_path, progress_callback)
                
            elif self.command == "download":
                local_parent = os.path.dirname(self.dest_path)
                if local_parent and not os.path.exists(local_parent):
                    os.makedirs(local_parent, exist_ok=True)
                
                logger.debug(f"Downloading {self.source_path} to {self.dest_path}")
                file_size = sftp.stat(self.source_path).st_size
                
                if resume:
                    existing_size = os.path.getsize(self.dest_path) if os.path.exists(self.dest_path) else 0
                    if existing_size >= file_size:
                        _safe_emit(self.signals.progress, file_size, file_size, 0, 0)
                        _safe_emit(self.signals.finished, 1, 0)
                        return
                    
                    with open(self.dest_path, 'ab') as local_file:
                        with sftp.open(self.source_path, 'rb') as remote_file:
                            remote_file.seek(existing_size)
                            chunk_size = 32768
                            bytes_downloaded = existing_size
                            while bytes_downloaded < file_size:
                                if self._cancel_requested:
                                    logger.debug("Download cancelled by flag")
                                    return
                                chunk = remote_file.read(chunk_size)
                                if not chunk: break
                                local_file.write(chunk)
                                bytes_downloaded += len(chunk)
                                progress_callback(bytes_downloaded, file_size)
                else:
                    sftp.get(self.source_path, self.dest_path, progress_callback)
            else:
                _safe_emit(self.signals.error, f"Unknown command: {self.command}")
                _safe_emit(self.signals.finished, 0, 1)
                return
            
            if self._cancel_requested:
                logger.debug("Transfer cancelled during execution")
                return

            logger.debug("Transfer completed successfully")
            elapsed = time.time() - start_time
            speed = file_size / elapsed if elapsed > 0 else 0
            _safe_emit(self.signals.progress, file_size, file_size, speed, 0)
            _safe_emit(self.signals.finished, 1, 0)
            
        finally:
            if sftp:
                pool.release_connection(
                    creds.get('hostname', ''),
                    creds.get('port', 22),
                    creds.get('username', ''),
                    sftp
                )

    def _ensure_remote_dir(self, sftp, remote_dir):
        if not remote_dir or remote_dir == '/':
            return
        parts = remote_dir.strip('/').split('/')
        current = ''
        for part in parts:
            current += '/' + part
            try:
                sftp.stat(current)
            except (OSError, IOError):
                try:
                    sftp.mkdir(current)
                except (OSError, IOError):
                    pass

