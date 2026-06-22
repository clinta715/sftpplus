"""
SFTP Session Executor

Executes SFTP commands using session-based credentials and connection pooling.
Provides a cleaner API that wraps the legacy add_sftp_job interface.
"""
from typing import Optional, Any, List
from threading import Lock
from stat import S_ISDIR
import time
import os
import errno
import logging
import paramiko

from PySide6.QtCore import Signal, QObject

from sftp_session import SFTPSession, SFTPCredentials, get_session_manager
from sftp_commands import (
    SFTPCommand, DownloadCommand, UploadCommand, ListCommand,
    StatCommand, MkDirCommand, RmDirCommand, RemoveCommand,
    ChDirCommand, GetCwdCommand, CommandType, RenameCommand
)
from sftp_connection_pool import get_connection_pool


class CommandExecutor(QObject):
    """
    Executes SFTP commands using sessions and connection pooling.
    
    This provides a cleaner API that wraps the legacy add_sftp_job interface.
    Each command is executed in a background thread with progress tracking.
    """
    
    progress = Signal(str, int, float, float)
    message = Signal(str, str)
    finished = Signal(str)
    
    def __init__(self, session: SFTPSession, ssh=None, sftp=None):
        super().__init__()
        self.session = session
        self.credentials = session.credentials
        self._pool = get_connection_pool()
        self._lock = Lock()
        
        # Allow passing pre-established connections for specialized use cases
        self._provided_ssh = ssh
        self._provided_sftp = sftp
        
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
        
        # Use provided connections if available, otherwise get from pool
        if self._provided_ssh and self._provided_sftp:
            ssh, sftp = self._provided_ssh, self._provided_sftp
        else:
            with self._lock:
                ssh, sftp = self._pool.get_connection(
                    hostname=self.credentials.hostname,
                    port=self.credentials.port,
                    username=self.credentials.username,
                    password=self.credentials.password,
                    key=self.credentials.key
                )
        
        try:
            result = self._execute_dispatch(ssh, sftp, command)
            return result
                
        except (OSError, IOError, RuntimeError, paramiko.SSHException) as e:
            # Invalidate the connection so a fresh one is created next time
            self._pool.close_connection(
                self.credentials.hostname,
                self.credentials.port,
                self.credentials.username
            )
            
            # Don't retry on permission errors - they're not transient
            is_permission_error = (
                isinstance(e, PermissionError) or
                (isinstance(e, OSError) and e.errno in (errno.EACCES, errno.EPERM))
            )
            if is_permission_error:
                raise
            
            # Retry once with a fresh connection if this was the first attempt
            if retry:
                logger = logging.getLogger('sftp.executor')
                logger.debug(f"Retrying command after error: {e}")
                return self.execute(command, timeout, retry=False)
            
            raise
        finally:
            # Always release connection back to pool
            self._pool.release_connection(
                self.credentials.hostname,
                self.credentials.port,
                self.credentials.username,
                sftp
            )
    
    def _execute_dispatch(self, ssh, sftp, command):
        if command.command_type == CommandType.DOWNLOAD:
            return self._execute_download(ssh, sftp, command)
        elif command.command_type == CommandType.UPLOAD:
            return self._execute_upload(ssh, sftp, command)
        elif command.command_type == CommandType.LIST:
            return self._execute_list(ssh, sftp, command)
        elif command.command_type == CommandType.LIST_ATTR:
            return self._execute_list_attr(ssh, sftp, command)
        elif command.command_type == CommandType.STAT:
            return self._execute_stat(ssh, sftp, command)
        elif command.command_type == CommandType.MKDIR:
            return self._execute_mkdir(ssh, sftp, command)
        elif command.command_type == CommandType.RMDIR:
            return self._execute_rmdir(ssh, sftp, command)
        elif command.command_type == CommandType.REMOVE:
            return self._execute_remove(ssh, sftp, command)
        elif command.command_type == CommandType.RENAME:
            return self._execute_rename(ssh, sftp, command)
        elif command.command_type == CommandType.CHDIR:
            return self._execute_chdir(ssh, sftp, command)
        elif command.command_type == CommandType.GETCWD:
            return self._execute_getcwd(ssh, sftp, command)
        else:
            raise ValueError(f"Unknown command type: {command.command_type}")
    
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
    
    def _ensure_remote_dir(self, ssh, sftp, remote_path):
        """Ensure a remote directory exists, creating parents as needed"""
        try:
            sftp.stat(remote_path)
            return
        except FileNotFoundError:
            pass
        except IOError:
            pass
        
        import shlex
        parent = os.path.dirname(remote_path)
        if parent and parent != remote_path:
            self._ensure_remote_dir(ssh, sftp, parent)
        
        try:
            sftp.mkdir(remote_path)
        except IOError:
            stdin, stdout, stderr = ssh.exec_command(f'mkdir -p {shlex.quote(remote_path)}')
            stdout.channel.recv_exit_status()
    
    def _execute_download(self, ssh, sftp, command: DownloadCommand):
        """Execute download command"""
        self._reset_progress_tracking()
        
        job_id = command.job_id
        local_dir = os.path.dirname(command.local_path)
        if local_dir:
            os.makedirs(local_dir, exist_ok=True)
        
        total_size = sftp.stat(command.remote_path).st_size
        
        if command.resume:
            self._resume_download(ssh, sftp, command.remote_path, command.local_path)
        else:
            sftp.get(command.remote_path, command.local_path, 
                    callback=lambda transferred, total: self._progress_callback(job_id, transferred, total_size))
        
        self.progress.emit(job_id, 100, 0.0, 0.0)
        self.finished.emit(job_id)
        return command.local_path
    
    def _execute_upload(self, ssh, sftp, command: UploadCommand):
        """Execute upload command"""
        self._reset_progress_tracking()
        
        job_id = command.job_id
        remote_dir = os.path.dirname(command.remote_path)
        if remote_dir:
            self._ensure_remote_dir(ssh, sftp, remote_dir)
        
        total_size = os.path.getsize(command.local_path)
        
        if command.resume:
            self._resume_upload(ssh, sftp, command.local_path, command.remote_path)
        else:
            sftp.put(command.local_path, command.remote_path,
                    callback=lambda transferred, total: self._progress_callback(job_id, transferred, total_size))
        
        self.progress.emit(job_id, 100, 0.0, 0.0)
        self.finished.emit(job_id)
        return command.remote_path
    
    def _execute_list(self, ssh, sftp, command: ListCommand):
        """Execute list directory command"""
        return sftp.listdir(command.remote_path)
    
    def _execute_list_attr(self, ssh, sftp, command: ListCommand):
        """Execute list directory with attributes command"""
        raw_items = sftp.listdir_attr(command.remote_path)
        # CRITICAL: Convert to plain Python dicts BEFORE connection is released
        # Paramiko SFTPAttribute objects become invalid after SFTP channel is closed
        result = []
        for item in raw_items:
            result.append({
                'filename': item.filename,
                'st_size': item.st_size,
                'st_mode': item.st_mode,
                'st_mtime': item.st_mtime
            })
        return result
    
    def _execute_stat(self, ssh, sftp, command: StatCommand):
        """Execute stat command"""
        stat_result = sftp.stat(command.path)
        # Convert to plain Python dict before connection is released
        result = {
            'filename': os.path.basename(command.path),
            'st_size': stat_result.st_size,
            'st_mode': stat_result.st_mode,
            'st_mtime': stat_result.st_mtime
        }
        return result
    
    def _execute_mkdir(self, ssh, sftp, command: MkDirCommand):
        """Execute mkdir command"""
        sftp.mkdir(command.remote_path)
        return command.remote_path

    def _execute_rmdir(self, ssh, sftp, command: RmDirCommand):
        """Execute rmdir command"""
        sftp.rmdir(command.remote_path)
        return command.remote_path

    def _execute_remove(self, ssh, sftp, command: RemoveCommand):
        """Execute remove command"""
        sftp.remove(command.remote_path)
        return command.remote_path

    def _execute_rename(self, ssh, sftp, command):
        """Execute rename command"""
        new_path = os.path.dirname(command.remote_path).rstrip('/') + '/' + command.new_name
        try:
            sftp.rename(command.remote_path, new_path)
            return new_path
        except IOError:
            import shlex
            safe_old = shlex.quote(command.remote_path)
            safe_new = shlex.quote(new_path)
            stdin, stdout, stderr = ssh.exec_command(f'mv {safe_old} {safe_new}')
            exit_code = stdout.channel.recv_exit_status()
            if exit_code == 0:
                return new_path
            else:
                error_output = stderr.read().decode('utf-8', errors='replace')
                raise IOError(error_output or f"Rename failed for {command.remote_path}")
    
    def _execute_chdir(self, ssh, sftp, command: ChDirCommand):
        """Execute chdir command"""
        sftp.listdir(command.remote_path)
        return command.remote_path

    def _execute_getcwd(self, ssh, sftp, command: GetCwdCommand):
        """Execute getcwd command - get the actual CWD from server"""
        stdin, stdout, stderr = ssh.exec_command('pwd')
        error_output = stderr.read()
        if error_output:
            raise IOError(error_output.decode())
        return stdout.read().decode().strip()
    
    def _resume_download(self, ssh, sftp, remote_path: str, local_path: str):
        """Resume a download from existing position"""
        existing_size = os.path.getsize(local_path) if os.path.exists(local_path) else 0
        remote_size = sftp.stat(remote_path).st_size
        
        if existing_size >= remote_size:
            return local_path
        
        if existing_size == 0:
            sftp.get(remote_path, local_path)
            return local_path
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
        
        return local_path
    
    def _resume_upload(self, ssh, sftp, local_path: str, remote_path: str):
        """Resume an upload from existing position"""
        local_size = os.path.getsize(local_path)
        try:
            existing_size = sftp.stat(remote_path).st_size
        except (IOError, OSError):
            existing_size = 0
        
        if existing_size >= local_size:
            return remote_path
        
        if existing_size == 0:
            sftp.put(local_path, remote_path)
            return remote_path
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
        
        return remote_path


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
    
    progress = Signal(str, int, float, float)
    message = Signal(str, str)
    finished = Signal(str)
    
    def __init__(self, session: SFTPSession):
        super().__init__()
        self.session = session
        self.executor = CommandExecutor(session)
        
        self.executor.progress.connect(self.progress)
        self.executor.message.connect(self.message)
        self.executor.finished.connect(self.finished)
    
    def execute(self, command: SFTPCommand, timeout: float = 60.0) -> Any:
        """Execute a command and return the result."""
        return self.executor.execute(command, timeout=timeout)
    
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
        except (OSError, IOError, RuntimeError, paramiko.SSHException):
            return False
    
    def is_directory(self, path: str) -> bool:
        """Check if path is a directory"""
        try:
            attr = self.stat(path)
            # Attr is now a dict, not SFTPAttribute object
            return S_ISDIR(attr['st_mode'])
        except (OSError, IOError, RuntimeError):
            return False
    
    def is_file(self, path: str) -> bool:
        """Check if path is a file"""
        try:
            attr = self.stat(path)
            # Attr is now a dict, not SFTPAttribute object
            return not S_ISDIR(attr['st_mode'])
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
