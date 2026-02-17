"""
SFTP Session Executor

Executes SFTP commands using session-based credentials and connection pooling.
Provides a cleaner API that wraps the legacy add_sftp_job interface.
"""
from typing import Optional, Any, List, Dict
from dataclasses import dataclass
from threading import Lock
import queue
import time
import os
from icecream import ic

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


class CommandExecutor:
    """
    Executes SFTP commands using sessions and connection pooling.
    
    This provides a cleaner API that wraps the legacy add_sftp_job interface.
    Each command is executed in a background thread with progress tracking.
    """
    
    def __init__(self, session: SFTPSession):
        self.session = session
        self.credentials = session.credentials
        self._pool = get_connection_pool()
        self._lock = Lock()
    
    def execute(self, command: SFTPCommand, timeout: float = 60.0) -> Any:
        """
        Execute a command synchronously and return the result.
        
        Args:
            command: The command to execute
            timeout: Maximum time to wait for result
            
        Returns:
            Command result data or raises exception
            
        Raises:
            TimeoutError: If command times out
            Exception: For command execution errors
        """
        command.validate()
        
        with self._lock:
            # Get or create connection
            ssh, sftp = self._pool.get_connection(
                hostname=self.credentials.hostname,
                port=self.credentials.port,
                username=self.credentials.username,
                password=self.credentials.password,
                key=self.credentials.key
            )
        
        job_id = self.session.get_next_job_id()
        
        with ResponseQueueContext(job_id) as response_queue:
            # Execute based on command type
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
                
                # Wait for result
                return self._wait_for_result(response_queue, timeout)
                
            except Exception as e:
                put_response(job_id, "error", str(e))
                raise
    
    def _execute_download(self, ssh, sftp, command: DownloadCommand, job_id: str):
        """Execute download command"""
        ic(f"Executor: Downloading {command.remote_path} to {command.local_path}")
        
        # Ensure local directory exists
        local_dir = os.path.dirname(command.local_path)
        if local_dir:
            os.makedirs(local_dir, exist_ok=True)
        
        if command.resume:
            self._resume_download(ssh, sftp, command.remote_path, command.local_path, job_id)
        else:
            sftp.get(command.remote_path, command.local_path)
        
        put_response(job_id, "success", command.local_path)
    
    def _execute_upload(self, ssh, sftp, command: UploadCommand, job_id: str):
        """Execute upload command"""
        ic(f"Executor: Uploading {command.local_path} to {command.remote_path}")
        
        if command.resume:
            self._resume_upload(ssh, sftp, command.local_path, command.remote_path, job_id)
        else:
            sftp.put(command.local_path, command.remote_path)
        
        put_response(job_id, "success", command.remote_path)
    
    def _execute_list(self, ssh, sftp, command: ListCommand, job_id: str):
        """Execute list directory command"""
        ic(f"Executor: Listing {command.remote_path}")
        result = sftp.listdir(command.remote_path)
        put_response(job_id, "success", result)
    
    def _execute_list_attr(self, ssh, sftp, command: ListCommand, job_id: str):
        """Execute list directory with attributes command"""
        ic(f"Executor: Listing {command.remote_path} with attributes")
        result = sftp.listdir_attr(command.remote_path)
        put_response(job_id, "success", result)
    
    def _execute_stat(self, ssh, sftp, command: StatCommand, job_id: str):
        """Execute stat command"""
        ic(f"Executor: Stat {command.path}")
        result = sftp.stat(command.path)
        put_response(job_id, "success", result)
    
    def _execute_mkdir(self, ssh, sftp, command: MkDirCommand, job_id: str):
        """Execute mkdir command"""
        ic(f"Executor: MkDir {command.remote_path}")
        try:
            sftp.mkdir(command.remote_path)
            put_response(job_id, "success", command.remote_path)
        except PermissionError as e:
            error_msg = f"Permission denied: Cannot create directory '{os.path.basename(command.remote_path)}'"
            ic(f"Executor: mkdir permission denied: {e}")
            put_response(job_id, "error", error_msg)
            raise
        except IOError as e:
            error_msg = f"IO error creating directory: {e}"
            ic(f"Executor: mkdir IO error: {e}")
            put_response(job_id, "error", error_msg)
            raise
    
    def _execute_rmdir(self, ssh, sftp, command: RmDirCommand, job_id: str):
        """Execute rmdir command"""
        ic(f"Executor: RmDir {command.remote_path}")
        try:
            sftp.rmdir(command.remote_path)
            put_response(job_id, "success", command.remote_path)
        except PermissionError as e:
            error_msg = f"Permission denied: Cannot remove directory '{os.path.basename(command.remote_path)}'"
            ic(f"Executor: rmdir permission denied: {e}")
            put_response(job_id, "error", error_msg)
            raise
        except IOError as e:
            error_msg = f"IO error removing directory: {e}"
            ic(f"Executor: rmdir IO error: {e}")
            put_response(job_id, "error", error_msg)
            raise
    
    def _execute_remove(self, ssh, sftp, command: RemoveCommand, job_id: str):
        """Execute remove command"""
        ic(f"Executor: Remove {command.remote_path}")
        try:
            sftp.remove(command.remote_path)
            put_response(job_id, "success", command.remote_path)
        except PermissionError as e:
            error_msg = f"Permission denied: Cannot remove '{os.path.basename(command.remote_path)}'"
            ic(f"Executor: remove permission denied: {e}")
            put_response(job_id, "error", error_msg)
            raise
        except IOError as e:
            error_msg = f"IO error removing file: {e}"
            ic(f"Executor: remove IO error: {e}")
            put_response(job_id, "error", error_msg)
            raise
    
    def _execute_rmdir(self, ssh, sftp, command: RmDirCommand, job_id: str):
        """Execute rmdir command"""
        ic(f"Executor: RmDir {command.remote_path}")
        sftp.rmdir(command.remote_path)
        put_response(job_id, "success", command.remote_path)
    
    def _execute_remove(self, ssh, sftp, command: RemoveCommand, job_id: str):
        """Execute remove command"""
        ic(f"Executor: Remove {command.remote_path}")
        sftp.remove(command.remote_path)
        put_response(job_id, "success", command.remote_path)
    
    def _execute_rename(self, ssh, sftp, command, job_id: str):
        """Execute rename command"""
        ic(f"Executor: Rename {command.remote_path} to {command.new_name}")
        new_path = os.path.join(os.path.dirname(command.remote_path), command.new_name)
        try:
            sftp.rename(command.remote_path, new_path)
            put_response(job_id, "success", new_path)
        except PermissionError as e:
            error_msg = f"Permission denied: Cannot rename '{os.path.basename(command.remote_path)}'"
            ic(f"Executor: rename permission denied: {e}")
            put_response(job_id, "error", error_msg)
            raise
        except IOError as e:
            ic(f"Executor: SFTP rename failed: {e}, trying SSH mv command")
            import shlex
            safe_old = shlex.quote(command.remote_path)
            safe_new = shlex.quote(new_path)
            stdin, stdout, stderr = ssh.exec_command(f'mv {safe_old} {safe_new}')
            exit_code = stdout.channel.recv_exit_status()
            if exit_code == 0:
                ic(f"Executor: SSH mv succeeded")
                put_response(job_id, "success", new_path)
            else:
                error_output = stderr.read().decode('utf-8', errors='replace')
                error_msg = f"IO error renaming file: {error_output or e}"
                ic(f"Executor: rename IO error: {error_msg}")
                put_response(job_id, "error", error_msg)
                raise IOError(error_msg)
    
    def _execute_chdir(self, ssh, sftp, command: ChDirCommand, job_id: str):
        """Execute chdir command"""
        ic(f"Executor: ChDir {command.remote_path}")
        sftp.listdir(command.remote_path)
        put_response(job_id, "success", command.remote_path)

    def _execute_getcwd(self, ssh, sftp, command: GetCwdCommand, job_id: str):
        """Execute getcwd command - get the actual CWD from server"""
        ic(f"Executor: GetCWD")
        stdin, stdout, stderr = ssh.exec_command('pwd')
        error_output = stderr.read()
        if error_output:
            error_msg = error_output.decode()
            ic(f"Executor: getcwd error: {error_msg}")
            put_response(job_id, "error", error_msg)
        else:
            cwd_path = stdout.read().decode().strip()
            ic(f"Executor: getcwd returned: {cwd_path}")
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
        
        ic(f"Executor: Resuming download from {existing_size} bytes")
        
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
        
        ic(f"Executor: Resuming upload from {existing_size} bytes")
        
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
            
            # Get the actual data
            data = response_queue.get_nowait()
            return data
            
        except queue.Empty:
            raise TimeoutError(f"Command timed out after {timeout} seconds")


class SFTPSessionAPI:
    """
    High-level API for SFTP operations using sessions.
    
    This provides a cleaner interface than the legacy add_sftp_job calls.
    Example usage:
    
    ```python
    # Create credentials
    creds = SFTPCredentials(
        hostname='example.com',
        username='user',
        password='password'
    )
    
    # Create session
    session = get_session_manager().create_session(creds)
    
    # Use API
    api = SFTPSessionAPI(session)
    
    # Download file
    api.download('/remote/file.txt', '/local/file.txt')
    
    # Upload file
    api.upload('/local/file.txt', '/remote/file.txt')
    
    # List directory
    files = api.list('/remote/directory')
    ```
    """
    
    def __init__(self, session: SFTPSession):
        self.session = session
        self.executor = CommandExecutor(session)
    
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
        return self.executor.execute(command)
    
    def remove(self, remote_path: str,
               job_id: Optional[str] = None) -> Any:
        """Remove remote file"""
        if job_id is None:
            job_id = self.session.get_next_job_id()
        
        command = RemoveCommand(job_id=job_id, remote_path=remote_path)
        return self.executor.execute(command)
    
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

        # Update session's remote directory
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
        except Exception:
            return False
    
    def is_directory(self, path: str) -> bool:
        """Check if path is a directory"""
        try:
            from stat import S_ISDIR
            attr = self.stat(path)
            return S_ISDIR(attr.st_mode)
        except Exception:
            return False
    
    def is_file(self, path: str) -> bool:
        """Check if path is a file"""
        try:
            from stat import S_ISDIR
            attr = self.stat(path)
            return not S_ISDIR(attr.st_mode)
        except Exception:
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
