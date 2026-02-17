"""
SFTP Connection Pool

Provides thread-safe SSH/SFTP connection pooling for reuse across operations.
Works with both the legacy add_sftp_job API and the new session-based API.
"""
from threading import Lock
import time
import os
import paramiko
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass
from icecream import ic


@dataclass
class ConnectionInfo:
    """Information about a pooled connection"""
    ssh: paramiko.SSHClient
    sftp: Optional[Any]  # SFTPClient
    created_at: float
    last_used_at: float
    hostname: str
    port: int
    username: str


class ConnectionPool:
    """
    Thread-safe connection pool for SSH/SFTP connections.
    
    Connections are keyed by (hostname, port, username) and can be reused
    across multiple operations. Old connections are cleaned up based on
    max age and activity status.
    """
    
    _instance: Optional['ConnectionPool'] = None
    _lock: Lock = Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._pool: Dict[Tuple, ConnectionInfo] = {}
                    cls._instance._pool_lock = Lock()
                    cls._instance._max_age = 30  # seconds
                    cls._instance._cleanup_interval = 60  # seconds
                    cls._instance._last_cleanup = 0
        return cls._instance
    
    def get_connection_key(self, hostname: str, port: int, username: str) -> Tuple:
        """Create a hashable key for connection pooling"""
        return (hostname, port, username)
    
    def get_connection(self, hostname: str, port: int, username: str, 
                       password: Optional[str] = None, 
                       key: Optional[str] = None) -> Tuple[paramiko.SSHClient, Any]:
        """
        Get or create an SSH/SFTP connection.
        
        Returns:
            Tuple of (ssh_client, sftp_client)
            
        Raises:
            paramiko.AuthenticationException: If authentication fails
            paramiko.SSHException: If connection fails
            Exception: For other connection errors
        """
        conn_key = self.get_connection_key(hostname, port, username)
        
        with self._pool_lock:
            # Check for existing valid connection
            if conn_key in self._pool:
                conn_info = self._pool[conn_key]
                age = time.time() - conn_info.created_at
                
                # Check if connection is still valid
                if (age < self._max_age and 
                    conn_info.ssh.get_transport() and 
                    conn_info.ssh.get_transport().is_active()):
                    conn_info.last_used_at = time.time()
                    ic(f"ConnectionPool: Reusing pooled connection for {hostname}:{port}")
                    return conn_info.ssh, conn_info.sftp
                else:
                    # Remove stale connection
                    ic(f"ConnectionPool: Removing stale connection for {hostname}:{port}")
                    try:
                        if conn_info.sftp:
                            try:
                                conn_info.sftp.close()
                            except:
                                pass
                        conn_info.ssh.close()
                    except:
                        pass
                    del self._pool[conn_key]
            
            # Create new connection
            ic(f"ConnectionPool: Creating new connection for {hostname}:{port}")
            ssh = self._create_ssh_connection(hostname, port, username, password, key)
            
            try:
                sftp = ssh.open_sftp()
            except Exception as e:
                ic(f"ConnectionPool: Failed to open SFTP channel: {e}")
                ssh.close()
                raise
            
            conn_info = ConnectionInfo(
                ssh=ssh,
                sftp=sftp,
                created_at=time.time(),
                last_used_at=time.time(),
                hostname=hostname,
                port=port,
                username=username
            )
            
            self._pool[conn_key] = conn_info
            return ssh, sftp
    
    def _create_ssh_connection(self, hostname: str, port: int, username: str,
                                password: Optional[str] = None,
                                key: Optional[str] = None) -> paramiko.SSHClient:
        """Create a new SSH connection with proper host key handling"""
        ssh = paramiko.SSHClient()
        
        # Load known hosts
        known_hosts_path = os.path.expanduser('~/.ssh/known_hosts')
        if os.path.exists(known_hosts_path):
            try:
                ssh.load_host_keys(known_hosts_path)
            except Exception as e:
                ic(f"ConnectionPool: Warning: Could not load known_hosts: {e}")
        
        # Use WarningPolicy for background transfers
        ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
        
        connect_kwargs = {
            'hostname': hostname,
            'port': port,
            'username': username,
            'timeout': 60
        }
        
        if key:
            key_obj = self._load_private_key(key)
            if key_obj:
                connect_kwargs['pkey'] = key_obj
            else:
                raise ValueError("Failed to load private key")
        else:
            connect_kwargs['password'] = password
        
        ssh.connect(**connect_kwargs)
        
        transport = ssh.get_transport()
        if transport:
            transport.set_keepalive(20)
        
        return ssh
    
    def _load_private_key(self, key_data: str) -> Optional[paramiko.PKey]:
        """Load private key from string data"""
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
                    key_obj = key_type.from_private_key(key_data)
                else:
                    expanded_path = os.path.expanduser(key_data)
                    key_obj = key_type.from_private_key_file(expanded_path)
                return key_obj
            except (paramiko.SSHException, ValueError, TypeError, FileNotFoundError):
                continue
            except Exception as e:
                ic(f"ConnectionPool: Error loading key: {e}")
                continue
        
        return None
    
    def release_connection(self, hostname: str, port: int, username: str):
        """
        Release a connection back to the pool (keep it for reuse).
        Simply updates the last_used timestamp.
        """
        conn_key = self.get_connection_key(hostname, port, username)
        
        with self._pool_lock:
            if conn_key in self._pool:
                self._pool[conn_key].last_used_at = time.time()
    
    def close_connection(self, hostname: str, port: int, username: str):
        """Close and remove a connection from the pool"""
        conn_key = self.get_connection_key(hostname, port, username)
        
        with self._pool_lock:
            if conn_key in self._pool:
                conn_info = self._pool[conn_key]
                try:
                    if conn_info.sftp:
                        try:
                            conn_info.sftp.close()
                        except:
                            pass
                    conn_info.ssh.close()
                except:
                    pass
                del self._pool[conn_key]
                ic(f"ConnectionPool: Closed connection for {hostname}:{port}")
    
    def cleanup_stale(self):
        """Remove connections that are too old or no longer active"""
        current_time = time.time()
        
        if current_time - self._last_cleanup < self._cleanup_interval:
            return
        
        self._last_cleanup = current_time
        
        with self._pool_lock:
            stale_keys = []
            
            for conn_key, conn_info in self._pool.items():
                age = current_time - conn_info.created_at
                is_active = (conn_info.ssh.get_transport() and 
                           conn_info.ssh.get_transport().is_active())
                
                if age > self._max_age or not is_active:
                    stale_keys.append(conn_key)
            
            for conn_key in stale_keys:
                conn_info = self._pool[conn_key]
                ic(f"ConnectionPool: Cleaning up stale connection for {conn_info.hostname}:{conn_info.port}")
                try:
                    if conn_info.sftp:
                        try:
                            conn_info.sftp.close()
                        except:
                            pass
                    conn_info.ssh.close()
                except:
                    pass
                del self._pool[conn_key]
    
    def close_all(self):
        """Close all pooled connections"""
        with self._pool_lock:
            for conn_key, conn_info in list(self._pool.items()):
                try:
                    if conn_info.sftp:
                        try:
                            conn_info.sftp.close()
                        except:
                            pass
                    conn_info.ssh.close()
                except:
                    pass
            self._pool.clear()
            ic("ConnectionPool: Closed all connections")
    
    def get_pool_size(self) -> int:
        """Get the number of pooled connections"""
        with self._pool_lock:
            return len(self._pool)


# Global connection pool instance
def get_connection_pool() -> ConnectionPool:
    """Get the global connection pool instance"""
    return ConnectionPool()
