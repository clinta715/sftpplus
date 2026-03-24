"""
SFTP Session Management

Provides session-based credential storage and management.
Replaces the global sftp_current_creds dictionary.
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from threading import Lock
import time
import os


@dataclass
class SFTPCredentials:
    """Credentials for an SFTP connection"""
    hostname: str
    username: str
    password: Optional[str] = None
    port: int = 22
    key: Optional[str] = None
    
    # Working directories
    remote_directory: str = "."
    local_directory: str = field(default_factory=lambda: os.path.expanduser("~"))
    
    def validate(self) -> bool:
        """Validate credentials have required fields"""
        if not self.hostname:
            raise ValueError("hostname is required")
        if not self.username:
            raise ValueError("username is required")
        if not self.password and not self.key:
            raise ValueError("Either password or SSH key is required")
        return True


@dataclass
class CommandResult:
    """Result of a command execution"""
    success: bool = False
    job_id: str = ""
    data: Any = None
    error: Optional[str] = None
    
    @classmethod
    def success(cls, job_id: str, data: Any = None) -> 'CommandResult':
        return cls(success=True, job_id=job_id, data=data)
    
    @classmethod
    def error(cls, job_id: str, error: str) -> 'CommandResult':
        return cls(success=False, job_id=job_id, error=error)


class SessionManager:
    """
    Manages SFTP sessions.
    
    Sessions provide isolated credential storage and operation tracking.
    """
    
    _instance: Optional['SessionManager'] = None
    _lock: Lock = Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._sessions: Dict[str, SFTPSession] = {}
                    cls._instance._lock = Lock()
        return cls._instance
    
    def create_session(self, credentials):
        """Create a new session with the given credentials"""
        credentials.validate()

        session_id = self._generate_session_id()
        session = SFTPSession(session_id, credentials)

        with self._lock:
            self._sessions[session_id] = session

        return session
    
    def get_session(self, session_id: str) -> Optional['SFTPSession']:
        """Get an existing session by ID"""
        with self._lock:
            return self._sessions.get(session_id)
    
    def remove_session(self, session_id: str) -> bool:
        """Remove and cleanup a session"""
        with self._lock:
            if session_id in self._sessions:
                session = self._sessions[session_id]
                session.cleanup()
                del self._sessions[session_id]
                return True
        return False
    
    def cleanup_all(self):
        """Cleanup all sessions"""
        with self._lock:
            for session_id in list(self._sessions.keys()):
                self.remove_session(session_id)
    
    def _generate_session_id(self) -> str:
        """Generate a unique session ID"""
        import random
        return str(int(time.time() * 1000) + random.randint(1000, 9999))


class SFTPSession:
    """
    An isolated SFTP session with its own credentials and state.
    
    This replaces passing credentials with every operation.
    """
    
    def __init__(self, session_id: str, credentials: SFTPCredentials):
        self.session_id = session_id
        self.credentials = credentials
        self._lock = Lock()
        self._job_counter = 0
        self._active = True
    
    @property
    def is_active(self) -> bool:
        """Check if session is still active"""
        return self._active
    
    def get_next_job_id(self) -> str:
        """Generate a unique job ID"""
        with self._lock:
            self._job_counter += 1
            return f"{self.session_id}_{self._job_counter}"
    
    def update_remote_directory(self, path: str):
        """Update the current remote directory"""
        self.credentials.remote_directory = path
    
    def update_local_directory(self, path: str):
        """Update the current local directory"""
        self.credentials.local_directory = path
    
    def cleanup(self):
        """Cleanup session resources"""
        self._active = False
    
    def __repr__(self) -> str:
        return (f"SFTPSession(id={self.session_id}, "
                f"host={self.credentials.hostname}, "
                f"remote_dir={self.credentials.remote_directory})")


# Global session manager instance
def get_session_manager() -> SessionManager:
    """Get the global session manager instance"""
    return SessionManager()
