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

from sftp_platform import get_known_hosts_path


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
    Multiple SSH connections can be opened for the same key to avoid 
    SSH channel limits (usually 10 per session).
    """
    
    _instance: Optional['ConnectionPool'] = None
    _lock: Lock = Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    # Key: (hostname, port, username), Value: List of ConnectionInfo
                    cls._instance._pool: Dict[Tuple, List[ConnectionInfo]] = {}
                    cls._instance._pool_lock = Lock()
                    cls._instance._max_age = 300  # Keep SSH connections for 5 minutes
                    cls._instance._max_channels_per_ssh = 8 # Safe limit below standard 10
                    cls._instance._cleanup_interval = 60
                    cls._instance._last_cleanup = 0
                    cls._instance._discovery_channels_used = 0  # Track discovery channel usage
                    cls._instance._max_discovery_channels = 2  # Reserve up to 2 channels for discovery
        return cls._instance
    
    def get_connection_key(self, hostname: str, port: int, username: str) -> Tuple:
        """Create a hashable key for connection pooling"""
        return (hostname, port, username)
    
    def get_effective_max_channels(self, for_discovery=False):
        """Get the maximum channels per SSH connection.
        
        Args:
            for_discovery: If True, allow discovery to use reserved channels
        """
        if for_discovery:
            # Discovery can use all channels including reserved ones
            return self._max_channels_per_ssh
        # Regular transfers leave some channels for discovery
        return max(1, self._max_channels_per_ssh - self._max_discovery_channels)
    
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
            if conn_key not in self._pool:
                self._pool[conn_key] = []
            
            conn_list = self._pool[conn_key]
            
            # 1. Try to find an existing connection with room for a new channel
            valid_connections = []
            for conn_info in conn_list:
                age = time.time() - conn_info.created_at
                total_channels = len(conn_info.busy_sftp_channels) + len(conn_info.idle_sftp_channels)
                
                if not (age < self._max_age and 
                        conn_info.ssh.get_transport() and 
                        conn_info.ssh.get_transport().is_active()):
                    self._close_conn_info(conn_info)
                    continue
                
                if total_channels >= self.get_effective_max_channels(for_discovery=False):
                    valid_connections.append(conn_info)
                    continue
                
                try:
                    sftp = conn_info.ssh.open_sftp()
                    conn_info.busy_sftp_channels.append(sftp)
                    conn_info.last_used_at = time.time()
                    valid_connections.append(conn_info)
                    return conn_info.ssh, sftp
                except Exception as e:
                    valid_connections.append(conn_info)
                    continue
            
            self._pool[conn_key] = valid_connections
            
            # 2. Create new SSH connection
            try:
                ssh = self._create_ssh_connection(hostname, port, username, password, key)
                sftp = ssh.open_sftp()
                
                conn_info = ConnectionInfo(
                    ssh=ssh,
                    created_at=time.time(),
                    last_used_at=time.time(),
                    hostname=hostname,
                    port=port,
                    username=username,
                    busy_sftp_channels=[sftp]
                )
                
                self._pool[conn_key].append(conn_info)
                return ssh, sftp
            except Exception as e:
                raise

    def acquire_discovery_channel(self, hostname: str, port: int, username: str,
                                   password: Optional[str] = None,
                                   key: Optional[str] = None) -> Tuple[paramiko.SSHClient, Any]:
        """
        Acquire a connection channel reserved for discovery/traversal operations.
        Discovery channels are prioritized to ensure directory scans complete quickly.
        
        Returns:
            Tuple of (ssh_client, sftp_client) or (None, None) if no channels available
        """
        conn_key = self.get_connection_key(hostname, port, username)
        
        with self._pool_lock:
            if self._discovery_channels_used >= self._max_discovery_channels:
                return (None, None)
            
            self._discovery_channels_used += 1
        
        try:
            ssh, sftp = self.get_connection(hostname, port, username, password, key)
            return (ssh, sftp)
        except Exception:
            with self._pool_lock:
                self._discovery_channels_used = max(0, self._discovery_channels_used - 1)
            raise

    def release_discovery_channel(self):
        """Release a discovery channel, making it available again"""
        with self._pool_lock:
            self._discovery_channels_used = max(0, self._discovery_channels_used - 1)

    def _create_ssh_connection(self, hostname: str, port: int, username: str,
                                password: Optional[str] = None,
                                key: Optional[str] = None) -> paramiko.SSHClient:
        """Create a new SSH connection with proper host key handling"""
        ssh = paramiko.SSHClient()
        
        # Load known hosts
        known_hosts_path = get_known_hosts_path()
        if os.path.exists(known_hosts_path):
            try:
                ssh.load_host_keys(known_hosts_path)
            except Exception as e:
                pass
        
        # Use WarningPolicy to warn about unknown hosts but allow connection
        # This is appropriate for a file transfer client where user initiates connections
        ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
        
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
            paramiko.PKey
        ]
        
        if key_data.startswith('-----BEGIN'):
            import io
            key_file = io.StringIO(key_data)
            for key_type in key_types:
                try:
                    key_file.seek(0)
                    return key_type.from_private_key(key_file)
                except (OSError, IOError, ValueError):
                    continue
        
        expanded_path = os.path.expanduser(key_data)
        if os.path.exists(expanded_path):
            for key_type in key_types:
                try:
                    return key_type.from_private_key_file(expanded_path)
                except (OSError, IOError, ValueError):
                    continue
        
        return None
    
    def release_connection(self, hostname: str, port: int, username: str, sftp: Any):
        """
        Release an SFTP channel back to the pool for reuse.
        """
        conn_key = self.get_connection_key(hostname, port, username)
        
        with self._pool_lock:
            if conn_key in self._pool:
                for conn_info in self._pool[conn_key]:
                    if sftp in conn_info.busy_sftp_channels:
                        conn_info.busy_sftp_channels.remove(sftp)
                        # Always close the SFTP channel - don't reuse stale channels
                        # to avoid corruption issues
                        try:
                            sftp.close()
                        except (OSError, IOError):
                            pass
                        conn_info.last_used_at = time.time()
                        return
            
            # If not found in any active ConnectionInfo, just close it
            try:
                sftp.close()
            except (OSError, IOError):
                pass
    
    def close_connection(self, hostname: str, port: int, username: str):
        """Close and remove all connections for this host from the pool"""
        conn_key = self.get_connection_key(hostname, port, username)
        
        with self._pool_lock:
            if conn_key in self._pool:
                for conn_info in self._pool[conn_key]:
                    self._close_conn_info(conn_info)
                del self._pool[conn_key]
    
    def _close_conn_info(self, conn_info: ConnectionInfo):
        """Helper to close all channels in a ConnectionInfo"""
        all_channels = conn_info.idle_sftp_channels + conn_info.busy_sftp_channels
        for sftp in all_channels:
            try:
                sftp.close()
            except (OSError, IOError):
                pass
        try:
            conn_info.ssh.close()
        except (OSError, IOError):
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
            for conn_key in list(self._pool.keys()):
                valid_list = []
                for conn_info in self._pool[conn_key]:
                    age = current_time - conn_info.created_at
                    idle_time = current_time - conn_info.last_used_at
                    is_active = (conn_info.ssh.get_transport() and 
                               conn_info.ssh.get_transport().is_active())
                    
                    if age > self._max_age or not is_active or (idle_time > 120 and not conn_info.busy_sftp_channels):
                        self._close_conn_info(conn_info)
                    else:
                        valid_list.append(conn_info)
                
                if valid_list:
                    self._pool[conn_key] = valid_list
                else:
                    del self._pool[conn_key]

    def close_all(self):
        """Close all connections in the pool"""
        with self._pool_lock:
            for conn_key in list(self._pool.keys()):
                for conn_info in self._pool[conn_key]:
                    self._close_conn_info(conn_info)
            self._pool.clear()
    
    def get_pool_size(self) -> int:
        """Get the total number of pooled SSH connections"""
        with self._pool_lock:
            return sum(len(conns) for conns in self._pool.values())


# Global connection pool instance
def get_connection_pool() -> ConnectionPool:
    """Get the global connection pool instance"""
    return ConnectionPool()
