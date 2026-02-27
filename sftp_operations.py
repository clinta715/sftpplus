"""
SFTP Operations Module

High-level convenience functions for SFTP operations.
Provides a simple API that can replace add_sftp_job calls.
"""
from typing import Optional, List, Any
from icecream import ic

from sftp_session import (
    SessionManager, SFTPSession, SFTPCredentials, 
    get_session_manager
)
from sftp_commands import (
    DownloadCommand, UploadCommand, ListCommand, StatCommand,
    MkDirCommand, RmDirCommand, RemoveCommand, ChDirCommand
)
from sftp_session_executor import SFTPSessionAPI, CommandExecutor, create_session_api
from sftp_connection_pool import get_connection_pool


class SFTPOperations:
    """
    Class-based interface for SFTP operations.
    
    Maintains a persistent session for multiple operations.
    
    Example:
        ops = SFTPOperations('example.com', 'user', 'password')
        ops.download('/remote/file.txt', '/local/file.txt')
        ops.upload('/local/other.txt', '/remote/other.txt')
        files = ops.list('/remote/directory')
        ops.close()
    """
    
    def __init__(self, hostname: str, username: str,
                 password: Optional[str] = None,
                 port: int = 22,
                 key: Optional[str] = None):
        """
        Initialize SFTP operations.
        
        Args:
            hostname: SFTP hostname
            username: SSH username
            password: SSH password (or None if using key)
            port: SSH port (default 22)
            key: Path to SSH private key (or None if using password)
        """
        creds = SFTPCredentials(
            hostname=hostname,
            username=username,
            password=password,
            port=port,
            key=key
        )
        
        self._session = get_session_manager().create_session(creds)
        self._api = SFTPSessionAPI(self._session)
    
    @property
    def session_id(self) -> str:
        """Get the session ID"""
        return self._session.session_id
    
    @property
    def remote_directory(self) -> str:
        """Get the current remote directory"""
        return self._session.credentials.remote_directory
    
    @remote_directory.setter
    def remote_directory(self, path: str):
        """Set the current remote directory"""
        self._session.update_remote_directory(path)
    
    @property
    def local_directory(self) -> str:
        """Get the current local directory"""
        return self._session.credentials.local_directory
    
    @local_directory.setter
    def local_directory(self, path: str):
        """Set the current local directory"""
        self._session.update_local_directory(path)
    
    def download(self, remote_path: str, local_path: str,
                 job_id: Optional[str] = None) -> Any:
        """
        Download a file.
        
        Args:
            remote_path: Remote file path
            local_path: Local destination path
            job_id: Optional job ID for tracking
            
        Returns:
            Downloaded file path
        """
        return self._api.download(remote_path, local_path, job_id)
    
    def upload(self, local_path: str, remote_path: str,
               job_id: Optional[str] = None) -> Any:
        """
        Upload a file.
        
        Args:
            local_path: Local file path
            remote_path: Remote destination path
            job_id: Optional job ID for tracking
            
        Returns:
            Uploaded file path
        """
        return self._api.upload(local_path, remote_path, job_id)
    
    def list(self, remote_path: Optional[str] = None,
             job_id: Optional[str] = None) -> List[str]:
        """
        List directory contents.
        
        Args:
            remote_path: Remote directory path (uses current if None)
            job_id: Optional job ID for tracking
            
        Returns:
            List of filenames
        """
        path = remote_path or self.remote_directory
        return self._api.list(path, job_id)
    
    def list_attr(self, remote_path: Optional[str] = None,
                  job_id: Optional[str] = None) -> List[Any]:
        """
        List directory with attributes.
        
        Args:
            remote_path: Remote directory path (uses current if None)
            job_id: Optional job ID for tracking
            
        Returns:
            List of entries with attributes
        """
        path = remote_path or self.remote_directory
        return self._api.list_attr(path, job_id)
    
    def stat(self, path: str,
             job_id: Optional[str] = None) -> Any:
        """
        Get file/directory attributes.
        
        Args:
            path: Remote path
            job_id: Optional job ID for tracking
            
        Returns:
            File attributes
        """
        return self._api.stat(path, job_id)
    
    def mkdir(self, remote_path: str,
              job_id: Optional[str] = None) -> Any:
        """
        Create remote directory.
        
        Args:
            remote_path: Directory path to create
            job_id: Optional job ID for tracking
        """
        return self._api.mkdir(remote_path, job_id)
    
    def rmdir(self, remote_path: str,
              job_id: Optional[str] = None) -> Any:
        """
        Remove remote directory.
        
        Args:
            remote_path: Directory path to remove
            job_id: Optional job ID for tracking
        """
        return self._api.rmdir(remote_path, job_id)
    
    def remove(self, remote_path: str,
               job_id: Optional[str] = None) -> Any:
        """
        Remove remote file.
        
        Args:
            remote_path: File path to remove
            job_id: Optional job ID for tracking
        """
        return self._api.remove(remote_path, job_id)
    
    def chdir(self, remote_path: str,
              job_id: Optional[str] = None) -> Any:
        """
        Change remote directory.
        
        Args:
            remote_path: Directory path to change to
            job_id: Optional job ID for tracking
        """
        result = self._api.chdir(remote_path, job_id)
        self.remote_directory = remote_path
        return result
    
    def exists(self, path: str) -> bool:
        """Check if path exists"""
        return self._api.exists(path)
    
    def is_directory(self, path: str) -> bool:
        """Check if path is a directory"""
        return self._api.is_directory(path)
    
    def is_file(self, path: str) -> bool:
        """Check if path is a file"""
        return self._api.is_file(path)
    
    def close(self):
        """Close the session and cleanup"""
        get_session_manager().remove_session(self._session.session_id)
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup"""
        self.close()
        return False
    
    def __del__(self):
        """Destructor - cleanup"""
        try:
            get_session_manager().remove_session(self._session.session_id)
        except (OSError, IOError, RuntimeError):
            pass
