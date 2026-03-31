from PySide6.QtWidgets import QInputDialog, QMessageBox, QApplication
from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool, QMutex, QWaitCondition
from sftp_qt_compat import Qt
from sftp_creds import get_credentials, create_random_integer, sanitize_error_message
from sftp_downloadworkerclass import add_sftp_job
from sftp_preferences import get_preferences
from sftp_connection_pool import get_connection_pool
from sftp_session import get_session_manager
import os
import stat


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
        
        # Try to acquire a discovery channel for faster traversal
        from sftp_connection_pool import get_connection_pool
        from sftp_session import SFTPSession, SFTPCredentials
        from sftp_session_executor import SFTPSessionAPI
        
        pool = get_connection_pool()
        hostname = self.creds.get('hostname', '')
        username = self.creds.get('username', '')
        password = self.creds.get('password', '')
        port = self.creds.get('port', 22)
        key = self.creds.get('key')
        
        discovery_ssh, discovery_sftp = pool.acquire_discovery_channel(
            hostname, port, username, password, key
        )
        
        if discovery_ssh and discovery_sftp:
            # Use discovery channel for operations
            creds = SFTPCredentials(
                hostname=hostname,
                username=username,
                password=password,
                port=port,
                key=key
            )
            self._discovery_session = SFTPSession(create_random_integer(), creds)
            # Store the SSH directly on session for exec_command access
            self._discovery_session._ssh = discovery_ssh
            self._discovery_api = SFTPSessionAPI(
                self._discovery_session, 
                ssh=discovery_ssh, 
                sftp=discovery_sftp
            )
            self._discovery_channel = True
            self.ops = None  # Will use _discovery_api instead
        else:
            # Fall back to regular SFTPOperations
            from sftp_operations import SFTPOperations
            self.ops = SFTPOperations(
                hostname=hostname,
                username=username,
                password=password,
                port=port,
                key=key
            )
            self._discovery_api = None
            self._discovery_session = None
            self._discovery_channel = False
        
        self._cancelled = False
        self._files_found = 0
        self._dirs_scanned = 0

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
        
        # Helper to execute commands - uses discovery API if available, else ops
        def execute_cmd(cmd_type, *args, **kwargs):
            if self._discovery_channel and self._discovery_session:
                if cmd_type == 'exec_command':
                    # Use discovery SSH directly for find command
                    return self._discovery_session._ssh.exec_command(*args, **kwargs)
                elif cmd_type == 'list':
                    return self._discovery_api.list(*args, **kwargs)
                elif cmd_type == 'list_attr':
                    return self._discovery_api.list_attr(*args, **kwargs)
            return getattr(self.ops, cmd_type)(*args, **kwargs)
        
        self._execute_cmd = execute_cmd
        
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
            # Clean up discovery channel if used
            if self._discovery_channel:
                pool = get_connection_pool()
                pool.release_discovery_channel()
                if self._discovery_session:
                    get_session_manager().remove_session(self._discovery_session.session_id)
            elif self.ops:
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
        
        exit_code, output, error = self._execute_cmd('exec_command', find_cmd, timeout=300)
        
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
                raw_files = self._execute_cmd('list_attr', source_dir)
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
            self._collected_files.append((source_path, dest_path, command))
            self._files_found += 1
            _safe_emit(self.signals.discovery_progress, self._files_found, self._dirs_scanned)
