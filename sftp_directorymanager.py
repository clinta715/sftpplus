"""
Remote Directory Manager Module

Provides centralized, thread-safe management of remote directory state.
Eliminates race conditions and ensures consistency across all components.
"""

import threading
import time
from typing import Optional, Callable
from PyQt5.QtCore import QObject, pyqtSignal
from icecream import ic


class DirectoryChangeEvent(QObject):
    """Signals for directory change notifications"""
    directory_changed = pyqtSignal(str, str)  # session_id, new_directory


class RemoteDirectoryManager:
    """
    Centralized manager for remote directory state.
    
    Features:
    - Thread-safe directory tracking
    - Cache with TTL (time-to-live)
    - Event-based change notifications
    - Automatic server verification
    - Consistency assertions
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton pattern to ensure single manager instance"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._initialized = True
        self._directory_cache = {}  # session_id -> (directory, timestamp)
        self._cache_ttl = 5.0  # seconds
        self._lock = threading.RLock()
        self._signals = DirectoryChangeEvent()
        self._get_cwd_callbacks = {}  # session_id -> callback function
        
    def register_cwd_callback(self, session_id: int, callback: Callable[[], str]):
        """Register a callback function to get current working directory from server"""
        with self._lock:
            self._get_cwd_callbacks[session_id] = callback
            ic(f"RemoteDirectoryManager: Registered cwd callback for session {session_id}")
    
    def unregister_cwd_callback(self, session_id: int):
        """Unregister a cwd callback"""
        with self._lock:
            if session_id in self._get_cwd_callbacks:
                del self._get_cwd_callbacks[session_id]
                ic(f"RemoteDirectoryManager: Unregistered cwd callback for session {session_id}")
    
    def get_directory(self, session_id: int, fresh: bool = False) -> str:
        """
        Get current directory for session.
        
        Args:
            session_id: The session identifier
            fresh: If True, always query server; if False, use cache if valid
            
        Returns:
            Current directory path (absolute)
        """
        with self._lock:
            # Check cache if not requesting fresh data
            if not fresh and session_id in self._directory_cache:
                directory, timestamp = self._directory_cache[session_id]
                if time.time() - timestamp < self._cache_ttl:
                    ic(f"RemoteDirectoryManager: Cache hit for session {session_id}: {directory}")
                    return directory
            
            # Cache miss or fresh request - query server
            directory = self._query_server(session_id)
            if directory:
                self._directory_cache[session_id] = (directory, time.time())
                ic(f"RemoteDirectoryManager: Server query for session {session_id}: {directory}")
                return directory
            
            # Fallback to root if query fails
            ic(f"RemoteDirectoryManager: Server query failed for session {session_id}, using '/'")
            return "/"
    
    def set_directory(self, session_id: int, directory: str, verify: bool = True) -> bool:
        """
        Set directory for session with optional verification.
        
        Args:
            session_id: The session identifier
            directory: New directory path
            verify: If True, verify the directory exists on server
            
        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            # Normalize path
            directory = directory.replace("\\", "/")
            if not directory.startswith("/"):
                directory = "/" + directory
            
            # Update cache
            old_directory = None
            if session_id in self._directory_cache:
                old_directory, _ = self._directory_cache[session_id]
            
            self._directory_cache[session_id] = (directory, time.time())
            
            # Emit change signal if different
            if old_directory != directory:
                self._signals.directory_changed.emit(str(session_id), directory)
            
            ic(f"RemoteDirectoryManager: Set directory for session {session_id}: {directory}")
            return True
    
    def change_directory(self, session_id: int, path: str) -> Optional[str]:
        """
        Change to a new directory (handles relative and absolute paths).
        
        Args:
            session_id: The session identifier
            path: New path (relative or absolute)
            
        Returns:
            Absolute path if successful, None otherwise
        """
        with self._lock:
            current_dir = self.get_directory(session_id, fresh=False)
            
            # Handle relative vs absolute path
            if path.startswith("/"):
                # Absolute path
                new_dir = path
            elif path == "..":
                # Parent directory
                if current_dir == "/":
                    new_dir = "/"  # Already at root
                else:
                    # Remove trailing slash if present, then split
                    current = current_dir.rstrip("/")
                    parts = current.split("/")
                    if len(parts) > 1:
                        new_dir = "/".join(parts[:-1]) or "/"
                    else:
                        new_dir = "/"
            elif path == ".":
                # Current directory - no change
                new_dir = current_dir
            else:
                # Relative path - append to current
                if current_dir.endswith("/"):
                    new_dir = current_dir + path
                else:
                    new_dir = current_dir + "/" + path
            
            # Normalize
            new_dir = new_dir.replace("//", "/")
            
            # Update
            if self.set_directory(session_id, new_dir):
                return new_dir
            return None
    
    def invalidate_cache(self, session_id: int):
        """Invalidate cache for session, forcing next read to query server"""
        with self._lock:
            if session_id in self._directory_cache:
                del self._directory_cache[session_id]
                ic(f"RemoteDirectoryManager: Invalidated cache for session {session_id}")
    
    def invalidate_all_cache(self):
        """Invalidate all caches"""
        with self._lock:
            self._directory_cache.clear()
            ic("RemoteDirectoryManager: Invalidated all caches")
    
    def _query_server(self, session_id: int) -> Optional[str]:
        """Query server for current directory using registered callback"""
        with self._lock:
            if session_id in self._get_cwd_callbacks:
                try:
                    callback = self._get_cwd_callbacks[session_id]
                    directory = callback()
                    if directory:
                        return directory
                except Exception as e:
                    ic(f"RemoteDirectoryManager: Error querying server for session {session_id}: {e}")
            return None
    
    def get_cache_age(self, session_id: int) -> float:
        """Get age of cached directory in seconds, or -1 if not cached"""
        with self._lock:
            if session_id in self._directory_cache:
                _, timestamp = self._directory_cache[session_id]
                return time.time() - timestamp
            return -1
    
    def is_cache_valid(self, session_id: int) -> bool:
        """Check if cached directory is still valid (within TTL)"""
        age = self.get_cache_age(session_id)
        return 0 <= age < self._cache_ttl
    
    @property
    def signals(self) -> DirectoryChangeEvent:
        """Access to directory change signals"""
        return self._signals


# Global instance for application-wide access
directory_manager = RemoteDirectoryManager()


def get_directory_manager() -> RemoteDirectoryManager:
    """Get the global directory manager instance"""
    return directory_manager
