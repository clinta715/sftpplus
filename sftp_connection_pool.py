"""
SFTP Connection Pool

Provides thread-safe SSH/SFTP connection pooling for reuse across operations.
Works with both the legacy add_sftp_job API and the new session-based API.
"""
from threading import Lock
import time
import os
import paramiko
from typing import Optional, Tuple, Dict, List, Any
from dataclasses import dataclass, field
from icecream import ic


@dataclass
class ConnectionInfo:
    """Information about a pooled SSH connection and its SFTP channels"""
    ssh: paramiko.SSHClient
    created_at: float
    last_used_at: float
    hostname: str
    port: int
    username: str
    # List of available (idle) SFTP channels
    idle_sftp_channels: List[Any] = field(default_factory=list)
    # List of all SFTP channels currently in use
    busy_sftp_channels: List[Any] = field(default_factory=list)


class ConnectionPool:
    """
    Thread-safe connection pool for SSH/SFTP connections.
    
    Connections are keyed by (hostname, port, username).
    Multiple SFTP channels can be opened over a single SSH connection
    to support concurrent transfers efficiently.
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
                    cls._instance._max_age = 300  # Keep SSH connections for 5 minutes
                    cls._instance._cleanup_interval = 60
                    cls._instance._last_cleanup = 0
        return cls._instance
    
    def get_connection_key(self, hostname: str, port: int, username: str) -> Tuple:
        """Create a hashable key for connection pooling"""
        return (hostname, port, username)
    
    def get_connection(self, hostname: str, port: int, username: str, 
                       password: Optional[str] = None, 
                       key: Optional[str] = None) -> Tuple[paramiko.SSHClient, Any]:
        """
        Get or create an SSH connection and an SFTP channel.
        
        Returns:
            Tuple of (ssh_client, sftp_client)
        """
        conn_key = self.get_connection_key(hostname, port, username)
        
        with self._pool_lock:
            # Check for existing valid connection
            if conn_key in self._pool:
                conn_info = self._pool[conn_key]
                age = time.time() - conn_info.created_at
                
                # Check if SSH connection is still valid
                if (age < self._max_age and 
                    conn_info.ssh.get_transport() and 
                    conn_info.ssh.get_transport().is_active()):
                    
                    conn_info.last_used_at = time.time()
                    
                    # Try to reuse an idle SFTP channel
                    while conn_info.idle_sftp_channels:
                        sftp = conn_info.idle_sftp_channels.pop()
                        # Check if channel is still healthy
                        try:
                            sftp.stat('.')
                            conn_info.busy_sftp_channels.append(sftp)
                            ic(f"ConnectionPool: Reusing idle SFTP channel for {hostname}:{port}")
                            return conn_info.ssh, sftp
                        except Exception:
                            ic("ConnectionPool: Idle SFTP channel was stale, closing it")
                            try:
                                sftp.close()
                            except:
                                pass
                            continue
                    
                    # No idle channels, open a new one over existing SSH
                    ic(f"ConnectionPool: Opening new SFTP channel over existing SSH for {hostname}:{port}")
                    try:
                        sftp = conn_info.ssh.open_sftp()
                        conn_info.busy_sftp_channels.append(sftp)
                        return conn_info.ssh, sftp
                    except Exception as e:
                        ic(f"ConnectionPool: Failed to open new SFTP channel: {e}")
                        # Fall through to create new connection if this fails
                
                # If we're here, the pooled connection is stale or failed
                self._close_conn_info(conn_info)
                del self._pool[conn_key]
            
            # Create new SSH connection
            ic(f"ConnectionPool: Creating new SSH connection for {hostname}:{port}")
            ssh = self._create_ssh_connection(hostname, port, username, password, key)
            
            try:
                sftp = ssh.open_sftp()
            except Exception as e:
                ic(f"ConnectionPool: Failed to open initial SFTP channel: {e}")
                ssh.close()
                raise
            
            conn_info = ConnectionInfo(
                ssh=ssh,
                created_at=time.time(),
                last_used_at=time.time(),
                hostname=hostname,
                port=port,
                username=username,
                busy_sftp_channels=[sftp]
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
        
        # Use RejectPolicy for security
        ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
        
        connect_kwargs = {
            'hostname': hostname,
            'port': port,
            'username': username,
            'timeout': 60,
            'allow_agent': True,
            'look_for_keys': True
        }
        
        if key:
            key_obj = self._load_private_key(key)
            if key_obj:
                connect_kwargs['pkey'] = key_obj
            else:
                # If key is a path, paramiko might handle it, but we already tried loading it
                pass
        
        if password:
            connect_kwargs['password'] = password
            
        ssh.connect(**connect_kwargs)
        
        transport = ssh.get_transport()
        if transport:
            transport.set_keepalive(20)
        
        return ssh
    
    def _load_private_key(self, key_data: str) -> Optional[paramiko.PKey]:
        """Load private key from string data or file path"""
        if not key_data:
            return None
        
        key_types = [
            paramiko.RSAKey,
            paramiko.DSSKey,
            paramiko.ECDSAKey,
            paramiko.Ed25519Key,
            paramiko.PKey # Generic fallback
        ]
        
        # Try as raw data first if it looks like a PEM file
        if key_data.startswith('-----BEGIN'):
            import io
            key_file = io.StringIO(key_data)
            for key_type in key_types:
                try:
                    key_file.seek(0)
                    return key_type.from_private_key(key_file)
                except:
                    continue
        
        # Try as file path
        expanded_path = os.path.expanduser(key_data)
        if os.path.exists(expanded_path):
            for key_type in key_types:
                try:
                    return key_type.from_private_key_file(expanded_path)
                except:
                    continue
        
        return None
    
    def release_connection(self, hostname: str, port: int, username: str, sftp: Any):
        """
        Release an SFTP channel back to the pool for reuse.
        """
        conn_key = self.get_connection_key(hostname, port, username)
        
        with self._pool_lock:
            if conn_key in self._pool:
                conn_info = self._pool[conn_key]
                if sftp in conn_info.busy_sftp_channels:
                    conn_info.busy_sftp_channels.remove(sftp)
                    conn_info.idle_sftp_channels.append(sftp)
                    conn_info.last_used_at = time.time()
                    ic(f"ConnectionPool: Released SFTP channel for {hostname}:{port} to idle pool")
                else:
                    # If it wasn't in busy, maybe it was already closed or from old connection
                    try:
                        sftp.close()
                    except:
                        pass
            else:
                # Connection no longer in pool, close the channel
                try:
                    sftp.close()
                except:
                    pass
    
    def close_connection(self, hostname: str, port: int, username: str):
        """Close and remove all connections for this host from the pool"""
        conn_key = self.get_connection_key(hostname, port, username)
        
        with self._pool_lock:
            if conn_key in self._pool:
                conn_info = self._pool[conn_key]
                self._close_conn_info(conn_info)
                del self._pool[conn_key]
                ic(f"ConnectionPool: Closed all channels and SSH for {hostname}:{port}")
    
    def _close_conn_info(self, conn_info: ConnectionInfo):
        """Helper to close all channels in a ConnectionInfo"""
        for sftp in conn_info.idle_sftp_channels + conn_info.busy_sftp_channels:
            try:
                sftp.close()
            except:
                pass
        try:
            conn_info.ssh.close()
        except:
            pass
        conn_info.idle_sftp_channels.clear()
        conn_info.busy_sftp_channels.clear()

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
                idle_time = current_time - conn_info.last_used_at
                is_active = (conn_info.ssh.get_transport() and 
                           conn_info.ssh.get_transport().is_active())
                
                # Cleanup if: SSH connection stale, inactive, OR idle for too long with no busy channels
                if age > self._max_age or not is_active or (idle_time > 120 and not conn_info.busy_sftp_channels):
                    stale_keys.append(conn_key)
            
            for conn_key in stale_keys:
                conn_info = self._pool[conn_key]
                ic(f"ConnectionPool: Cleaning up stale connection for {conn_info.hostname}:{conn_info.port}")
                self._close_conn_info(conn_info)
                del self._pool[conn_key]

    def close_all(self):
        """Close all connections in the pool"""
        with self._pool_lock:
            for conn_key in list(self._pool.keys()):
                conn_info = self._pool[conn_key]
                self._close_conn_info(conn_info)
            self._pool.clear()
            ic("ConnectionPool: All connections closed")
    
    def get_pool_size(self) -> int:
        """Get the number of pooled SSH connections"""
        with self._pool_lock:
            return len(self._pool)


# Global connection pool instance
def get_connection_pool() -> ConnectionPool:
    """Get the global connection pool instance"""
    return ConnectionPool()
