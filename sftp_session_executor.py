"""
SFTP Session Executor

Executes SFTP commands using session-based credentials and connection pooling.
Provides a cleaner API that wraps the legacy add_sftp_job interface.
"""
from typing import Optional, Any, List, Dict
from dataclasses import dataclass
from threading import Lock
from stat import S_ISDIR
import queue
import time
import os
import errno
import paramiko

from PyQt6.QtCore import pyqtSignal, QObject

from sftp_session import SessionManager, SFTPSession, SFTPCredentials, get_session_manager
from sftp_commands import (
    SFTPCommand, DownloadCommand, UploadCommand, ListCommand,
    StatCommand, MkDirCommand, RmDirCommand, RemoveCommand,
    ChDirCommand, GetCwdCommand, CommandType, RenameCommand
)
from sftp_connection_pool import get_connection_pool
from sftp_downloadworkerclass import (
    create_response_queue, delete_response_queue, 
    ResponseQueueContext, put_response
)


class CommandExecutor(QObject):
    """
    Executes SFTP commands using sessions and connection pooling.
    
    This provides a cleaner API that wraps the legacy add_sftp_job interface.
    Each command is executed in a background thread with progress tracking.
    """
    
    progress = pyqtSignal(str, int, float, float)
    message = pyqtSignal(str, str)
    finished = pyqtSignal(str)
    
    def __init__(self, session: SFTPSession):
        super().__init__()
        self.session = session
        self.credentials = session.credentials
        self._pool = get_connection_pool()
        self._lock = Lock()
        
        self._last_emit_time = 0
        self._emit_interval = 0.2
        self._last_bytes = 0
        self._last_time = None
    
    def execute(self, command: SFTPCommand, timeout: float = 60.0, retry: bool = True) -> Any:
        """
        Execute a command synchronously and return the result.
        
        Args:
            command: The command to execute
            timeout: Maximum time to wait for result
            retry: If True, retry with fresh connection on failure
            
        Returns:
            Command result data or raises exception
            
        Raises:
            TimeoutError: If command times out
            Exception: For command execution errors
        """
        command.validate()
        
        with self._lock:
            ssh, sftp = self._pool.get_connection(
                hostname=self.credentials.hostname,
                port=self.credentials.port,
                username=self.credentials.username,
                password=self.credentials.password,
                key=self.credentials.key
            )
        
        job_id = self.session.get_next_job_id()
        
        with ResponseQueueContext(job_id) as response_queue:
            try:
                if command.command_type == CommandType.DOWNLOAD:
                    self._execute_download(ssh, sftp, command, job_id)
                elif command.command_type == CommandType.UPLOAD:
                    self._execute_upload(ssh, sftp, command, job_id)
                elif command.command_type == CommandType.LIST:
                    self._execute_list(ssh, sftp, command, job_id)
                elif command.command_type == CommandType.LIST_ATTR:
                    self._execute_list_attr(ssh, sftp, command, job_id)
                elif command.command_type == CommandType.STAT:
                    self._execute_stat(ssh, sftp, command, job_id)
                elif command.command_type == CommandType.MKDIR:
                    self._execute_mkdir(ssh, sftp, command, job_id)
                elif command.command_type == CommandType.RMDIR:
                    self._execute_rmdir(ssh, sftp, command, job_id)
                elif command.command_type == CommandType.REMOVE:
                    self._execute_remove(ssh, sftp, command, job_id)
                elif command.command_type == CommandType.RENAME:
                    self._execute_rename(ssh, sftp, command, job_id)
                elif command.command_type == CommandType.CHDIR:
                    self._execute_chdir(ssh, sftp, command, job_id)
                elif command.command_type == CommandType.GETCWD:
                    self._execute_getcwd(ssh, sftp, command, job_id)
                else:
                    raise ValueError(f"Unknown command type: {command.command_type}")
                
                return self._wait_for_result(response_queue, timeout)
                
            except (OSError, IOError, RuntimeError, paramiko.SSHException) as e:
                put_response(job_id, "error", str(e))
                # Don't retry on permission errors - they're not transient
                # Check both PermissionError and OSError with EACCES/EPERM
                is_permission_error = (
                    isinstance(e, PermissionError) or
                    (isinstance(e, OSError) and e.errno in (errno.EACCES, errno.EPERM))
                )
                if is_permission_error:
                    raise
                else:
                    # Invalidate the connection so a fresh one is created next time
                    self._pool.close_connection(
                        self.credentials.hostname,
                        self.credentials.port,
                        self.credentials.username
                    )
                    # Retry once with a fresh connection if this was the first attempt
                    if retry:
                        return self.execute(command, timeout, retry=False)
                    raise
    
    def _progress_callback(self, job_id: str, transferred: int, total: int):
        """Progress callback with rate limiting"""
        now = time.time()
        
        if self._last_time is None:
            speed_bps = 0.0
            eta_sec = 0.0
        else:
            delta_t = now - self._last_time
            delta_b = transferred - self._last_bytes
            speed_bps = delta_b / max(delta_t, 1e-6)
            if speed_bps <= 0 or total <= transferred:
                eta_sec = 0.0
            else:
                eta_sec = (total - transferred) / speed_bps
        
        self._last_bytes = transferred
        self._last_time = now
        
        percent = int(transferred * 100 / max(total, 1))
        
        if (now - self._last_emit_time >= self._emit_interval) or (percent >= 100):
            try:
                self.progress.emit(job_id, percent, speed_bps, eta_sec)
                self._last_emit_time = now
            except RuntimeError:
                pass

    def _reset_progress_tracking(self):
        """Reset progress tracking state for new transfer"""
        self._last_emit_time = 0
        self._last_bytes = 0
        self._last_time = None
    
    def _execute_download(self, ssh, sftp, command: DownloadCommand, job_id: str):
        """Execute download command"""
        self._reset_progress_tracking()
        
        try:
            local_dir = os.path.dirname(command.local_path)
            if local_dir:
                os.makedirs(local_dir, exist_ok=True)
            
            total_size = sftp.stat(command.remote_path).st_size
            
            if command.resume:
                self._resume_download(ssh, sftp, command.remote_path, command.local_path, job_id)
            else:
                sftp.get(command.remote_path, command.local_path, 
                        callback=lambda transferred, total: self._progress_callback(job_id, transferred, total_size))
            
            self.progress.emit(job_id, 100, 0.0, 0.0)
            put_response(job_id, "success", command.local_path)
            self.finished.emit(job_id)
        except (OSError, IOError, paramiko.SSHException) as e:
            put_response(job_id, "error", str(e))
            raise
    
    def _execute_upload(self, ssh, sftp, command: UploadCommand, job_id: str):
        """Execute upload command"""
        self._reset_progress_tracking()
        
        try:
            total_size = os.path.getsize(command.local_path)
            
            if command.resume:
                self._resume_upload(ssh, sftp, command.local_path, command.remote_path, job_id)
            else:
                sftp.put(command.local_path, command.remote_path,
                        callback=lambda transferred, total: self._progress_callback(job_id, transferred, total_size))
            
            self.progress.emit(job_id, 100, 0.0, 0.0)
            put_response(job_id, "success", command.remote_path)
            self.finished.emit(job_id)
        except (OSError, IOError, paramiko.SSHException) as e:
            put_response(job_id, "error", str(e))
            raise
    
    def _execute_list(self, ssh, sftp, command: ListCommand, job_id: str):
        """Execute list directory command"""
        try:
            result = sftp.listdir(command.remote_path)
            put_response(job_id, "success", result)
        except (OSError, IOError, paramiko.SSHException) as e:
            put_response(job_id, "error", str(e))
            raise
    
    def _execute_list_attr(self, ssh, sftp, command: ListCommand, job_id: str):
        """Execute list directory with attributes command"""
        try:
            result = sftp.listdir_attr(command.remote_path)
            put_response(job_id, "success", result)
        except (OSError, IOError, paramiko.SSHException) as e:
            put_response(job_id, "error", str(e))
            raise
    
    def _execute_stat(self, ssh, sftp, command: StatCommand, job_id: str):
        """Execute stat command"""
        try:
            result = sftp.stat(command.path)
            put_response(job_id, "success", result)
        except (OSError, IOError, paramiko.SSHException) as e:
            put_response(job_id, "error", str(e))
            raise
    
    def _execute_mkdir(self, ssh, sftp, command: MkDirCommand, job_id: str):
        """Execute mkdir command"""
        try:
            sftp.mkdir(command.remote_path)
            put_response(job_id, "success", command.remote_path)
        except PermissionError as e:
            error_msg = f"Permission denied: Cannot create directory '{os.path.basename(command.remote_path)}'"
            put_response(job_id, "error", error_msg)
            raise
        except IOError as e:
            error_msg = f"IO error creating directory: {e}"
            put_response(job_id, "error", error_msg)
            raise

    def _execute_rmdir(self, ssh, sftp, command: RmDirCommand, job_id: str):
        """Execute rmdir command"""
        try:
            sftp.rmdir(command.remote_path)
            put_response(job_id, "success", command.remote_path)
        except PermissionError as e:
            error_msg = f"Permission denied: Cannot remove directory '{os.path.basename(command.remote_path)}'"
            put_response(job_id, "error", error_msg)
            raise
        except IOError as e:
            error_msg = f"IO error removing directory: {e}"
            put_response(job_id, "error", error_msg)
            raise

    def _execute_remove(self, ssh, sftp, command: RemoveCommand, job_id: str):
        """Execute remove command"""
        try:
            sftp.remove(command.remote_path)
            put_response(job_id, "success", command.remote_path)
        except PermissionError as e:
            error_msg = f"Permission denied: Cannot remove '{os.path.basename(command.remote_path)}'"
            put_response(job_id, "error", error_msg)
            raise
        except IOError as e:
            error_msg = f"IO error removing file: {e}"
            put_response(job_id, "error", error_msg)
            raise

    def _execute_rename(self, ssh, sftp, command, job_id: str):
        """Execute rename command"""
        new_path = os.path.join(os.path.dirname(command.remote_path), command.new_name)
        try:
            sftp.rename(command.remote_path, new_path)
            put_response(job_id, "success", new_path)
        except PermissionError as e:
            error_msg = f"Permission denied: Cannot rename '{os.path.basename(command.remote_path)}'"
            put_response(job_id, "error", error_msg)
            raise
        except IOError as e:
            import shlex
            safe_old = shlex.quote(command.remote_path)
            safe_new = shlex.quote(new_path)
            stdin, stdout, stderr = ssh.exec_command(f'mv {safe_old} {safe_new}')
            exit_code = stdout.channel.recv_exit_status()
            if exit_code == 0:
                put_response(job_id, "success", new_path)
            else:
                error_output = stderr.read().decode('utf-8', errors='replace')
                error_msg = f"IO error renaming file: {error_output or e}"
                put_response(job_id, "error", error_msg)
                raise IOError(error_msg)
    
    def _execute_chdir(self, ssh, sftp, command: ChDirCommand, job_id: str):
        """Execute chdir command"""
        sftp.listdir(command.remote_path)
        put_response(job_id, "success", command.remote_path)

    def _execute_getcwd(self, ssh, sftp, command: GetCwdCommand, job_id: str):
        """Execute getcwd command - get the actual CWD from server"""
        stdin, stdout, stderr = ssh.exec_command('pwd')
        error_output = stderr.read()
        if error_output:
            error_msg = error_output.decode()
            put_response(job_id, "error", error_msg)
        else:
            cwd_path = stdout.read().decode().strip()
            put_response(job_id, "success", cwd_path)
    
    def _resume_download(self, ssh, sftp, remote_path: str, local_path: str, job_id: str):
        """Resume a download from existing position"""
        existing_size = os.path.getsize(local_path) if os.path.exists(local_path) else 0
        remote_size = sftp.stat(remote_path).st_size
        
        if existing_size >= remote_size:
            put_response(job_id, "success", local_path)
            return
        
        if existing_size == 0:
            sftp.get(remote_path, local_path)
            put_response(job_id, "success", local_path)
            return
        with open(local_path, 'ab') as local_file:
            with sftp.open(remote_path, 'rb') as remote_file:
                remote_file.seek(existing_size)
                chunk_size = 32768
                bytes_downloaded = 0
                remaining_size = remote_size - existing_size
                
                while bytes_downloaded < remaining_size:
                    chunk = remote_file.read(min(chunk_size, remaining_size - bytes_downloaded))
                    if not chunk:
                        break
                    local_file.write(chunk)
                    bytes_downloaded += len(chunk)
        
        put_response(job_id, "success", local_path)
    
    def _resume_upload(self, ssh, sftp, local_path: str, remote_path: str, job_id: str):
        """Resume an upload from existing position"""
        local_size = os.path.getsize(local_path)
        existing_size = sftp.stat(remote_path).st_size if sftp.stat(remote_path) else 0
        
        if existing_size >= local_size:
            put_response(job_id, "success", remote_path)
            return
        
        if existing_size == 0:
            sftp.put(local_path, remote_path)
            put_response(job_id, "success", remote_path)
            return
        with open(local_path, 'rb') as local_file:
            local_file.seek(existing_size)
            with sftp.open(remote_path, 'ab') as remote_file:
                chunk_size = 32768
                bytes_uploaded = 0
                remaining_size = local_size - existing_size
                
                while bytes_uploaded < remaining_size:
                    chunk = local_file.read(min(chunk_size, remaining_size - bytes_uploaded))
                    if not chunk:
                        break
                    remote_file.write(chunk)
                    bytes_uploaded += len(chunk)
        
        put_response(job_id, "success", remote_path)
    
    def _wait_for_result(self, response_queue: queue.Queue, timeout: float) -> Any:
        """Wait for command result with timeout"""
        try:
            result = response_queue.get(timeout=timeout)
            
            if result == "error":
                error = response_queue.get_nowait()
                raise Exception(error)
            
            data = response_queue.get_nowait()
            return data
            
        except queue.Empty:
            raise TimeoutError(f"Command timed out after {timeout} seconds")


class SFTPSessionAPI(QObject):
    """
    High-level API for SFTP operations using sessions.
    
    This provides a cleaner interface than the legacy add_sftp_job calls.
    
    Example:
        creds = SFTPCredentials(hostname='example.com', username='user', password='password')
        session = get_session_manager().create_session(creds)
        api = SFTPSessionAPI(session)
        api.download('/remote/file.txt', '/local/file.txt')
    """
    
    progress = pyqtSignal(str, int, float, float)
    message = pyqtSignal(str, str)
    finished = pyqtSignal(str)
    
    def __init__(self, session: SFTPSession):
        super().__init__()
        self.session = session
        self.executor = CommandExecutor(session)
        
        self.executor.progress.connect(self.progress)
        self.executor.message.connect(self.message)
        self.executor.finished.connect(self.finished)
    
    def download(self, remote_path: str, local_path: str, 
                 job_id: Optional[str] = None, resume: bool = False) -> Any:
        """Download a file from remote to local"""
        if job_id is None:
            job_id = self.session.get_next_job_id()
        
        command = DownloadCommand(
            job_id=job_id,
            remote_path=remote_path,
            local_path=local_path,
            resume=resume
        )
        return self.executor.execute(command)
    
    def upload(self, local_path: str, remote_path: str,
               job_id: Optional[str] = None, resume: bool = False) -> Any:
        """Upload a file from local to remote"""
        if job_id is None:
            job_id = self.session.get_next_job_id()
        
        command = UploadCommand(
            job_id=job_id,
            local_path=local_path,
            remote_path=remote_path,
            resume=resume
        )
        return self.executor.execute(command)
    
    def list(self, remote_path: str, 
             job_id: Optional[str] = None) -> List[str]:
        """List directory contents"""
        if job_id is None:
            job_id = self.session.get_next_job_id()
        
        command = ListCommand(
            job_id=job_id,
            remote_path=remote_path,
            with_attributes=False
        )
        return self.executor.execute(command)
    
    def list_attr(self, remote_path: str,
                  job_id: Optional[str] = None) -> List[Any]:
        """List directory with attributes"""
        if job_id is None:
            job_id = self.session.get_next_job_id()
        
        command = ListCommand(
            job_id=job_id,
            command_type=CommandType.LIST_ATTR,
            remote_path=remote_path,
            with_attributes=True
        )
        return self.executor.execute(command)
    
    def stat(self, path: str, 
             job_id: Optional[str] = None) -> Any:
        """Get file/directory attributes"""
        if job_id is None:
            job_id = self.session.get_next_job_id()
        
        command = StatCommand(job_id=job_id, path=path)
        return self.executor.execute(command)
    
    def mkdir(self, remote_path: str,
              job_id: Optional[str] = None) -> Any:
        """Create remote directory"""
        if job_id is None:
            job_id = self.session.get_next_job_id()
        
        command = MkDirCommand(job_id=job_id, remote_path=remote_path)
        return self.executor.execute(command)
    
    def rmdir(self, remote_path: str,
              job_id: Optional[str] = None) -> Any:
        """Remove remote directory"""
        if job_id is None:
            job_id = self.session.get_next_job_id()
        
        command = RmDirCommand(job_id=job_id, remote_path=remote_path)
        # Don't retry rmdir operations - permission errors are not transient
        return self.executor.execute(command, retry=False)
    
    def remove(self, remote_path: str,
               job_id: Optional[str] = None) -> Any:
        """Remove remote file"""
        if job_id is None:
            job_id = self.session.get_next_job_id()
        
        command = RemoveCommand(job_id=job_id, remote_path=remote_path)
        # Don't retry remove operations - permission errors are not transient
        return self.executor.execute(command, retry=False)
    
    def rename(self, remote_path: str, new_name: str,
               job_id: Optional[str] = None) -> Any:
        """Rename remote file or directory"""
        if job_id is None:
            job_id = self.session.get_next_job_id()
        
        command = RenameCommand(job_id=job_id, remote_path=remote_path, new_name=new_name)
        return self.executor.execute(command)
    
    def chdir(self, remote_path: str,
              job_id: Optional[str] = None) -> Any:
        """Change remote directory (validates path exists)"""
        if job_id is None:
            job_id = self.session.get_next_job_id()

        command = ChDirCommand(job_id=job_id, remote_path=remote_path)
        result = self.executor.execute(command)
        self.session.update_remote_directory(remote_path)
        return result

    def getcwd(self, job_id: Optional[str] = None) -> str:
        """Get the actual current working directory from the server"""
        if job_id is None:
            job_id = self.session.get_next_job_id()

        command = GetCwdCommand(job_id=job_id)
        return self.executor.execute(command)

    def exists(self, path: str) -> bool:
        """Check if path exists"""
        try:
            self.stat(path)
            return True
        except (OSError, IOError, RuntimeError):
            return False
    
    def is_directory(self, path: str) -> bool:
        """Check if path is a directory"""
        try:
            attr = self.stat(path)
            return S_ISDIR(attr.st_mode)
        except (OSError, IOError, RuntimeError):
            return False
    
    def is_file(self, path: str) -> bool:
        """Check if path is a file"""
        try:
            attr = self.stat(path)
            return not S_ISDIR(attr.st_mode)
        except (OSError, IOError, RuntimeError):
            return False


def create_session_api(credentials: SFTPCredentials) -> SFTPSessionAPI:
    """
    Convenience function to create a session and return the API.
    
    Args:
        credentials: SFTP connection credentials
        
    Returns:
        SFTPSessionAPI instance ready for operations
    """
    session_manager = get_session_manager()
    session = session_manager.create_session(credentials)
    return SFTPSessionAPI(session)
