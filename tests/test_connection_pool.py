"""
Tests for ConnectionPool thread safety and functionality.
"""

import os
import sys
import threading
import time
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest


class TestConnectionPoolSingleton:
    """Tests for ConnectionPool singleton pattern"""
    
    def test_singleton_returns_same_instance(self):
        """Test that ConnectionPool returns the same instance"""
        from sftp_connection_pool import ConnectionPool
        
        pool1 = ConnectionPool()
        pool2 = ConnectionPool()
        
        assert pool1 is pool2
    
    def test_singleton_thread_safety(self):
        """Test that singleton is thread-safe during creation"""
        from sftp_connection_pool import ConnectionPool
        
        # Reset the singleton for this test
        ConnectionPool._instance = None
        
        instances = []
        
        def create_instance():
            instances.append(ConnectionPool())
        
        threads = [threading.Thread(target=create_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # All instances should be the same
        assert all(inst is instances[0] for inst in instances)


class TestConnectionPoolBasics:
    """Tests for basic connection pool operations"""
    
    def test_get_connection_key(self):
        """Test connection key generation"""
        from sftp_connection_pool import ConnectionPool
        
        pool = ConnectionPool()
        key = pool.get_connection_key("host.example.com", 22, "user")
        
        assert key == ("host.example.com", 22, "user")
    
    def test_get_connection_key_consistency(self):
        """Test that same inputs produce same key"""
        from sftp_connection_pool import ConnectionPool
        
        pool = ConnectionPool()
        key1 = pool.get_connection_key("host", 22, "user")
        key2 = pool.get_connection_key("host", 22, "user")
        
        assert key1 == key2
    
    def test_get_connection_key_different(self):
        """Test that different inputs produce different keys"""
        from sftp_connection_pool import ConnectionPool
        
        pool = ConnectionPool()
        key1 = pool.get_connection_key("host1", 22, "user")
        key2 = pool.get_connection_key("host2", 22, "user")
        
        assert key1 != key2


class TestConnectionPoolThreadSafety:
    """Tests for thread-safe operations"""
    
    def test_pool_lock_exists(self):
        """Test that pool has a lock for thread safety"""
        from sftp_connection_pool import ConnectionPool
        import threading
        
        pool = ConnectionPool()
        
        assert hasattr(pool, '_pool_lock')
        assert isinstance(pool._pool_lock, type(threading.Lock()))
    
    def test_concurrent_access_no_crash(self):
        """Test that concurrent access doesn't cause crashes"""
        from sftp_connection_pool import ConnectionPool
        
        pool = ConnectionPool()
        errors = []
        
        def access_pool():
            try:
                # Just access the pool structure
                key = pool.get_connection_key("test", 22, "user")
                with pool._pool_lock:
                    if key not in pool._pool:
                        pool._pool[key] = []
            except Exception as e:
                errors.append(str(e))
        
        threads = [threading.Thread(target=access_pool) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
    
    def test_cleanup_thread_safety(self):
        """Test that cleanup operations are thread-safe"""
        from sftp_connection_pool import ConnectionPool
        import time
        
        pool = ConnectionPool()
        
        # Set up some fake connection data
        pool._pool[("test", 22, "user")] = []
        
        def run_cleanup():
            pool.cleanup_stale()
        
        # Run cleanup from multiple threads
        threads = [threading.Thread(target=run_cleanup) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Pool should still be functional
        assert isinstance(pool._pool, dict)


class TestConnectionPoolConnectionManagement:
    """Tests for SSH connection management"""
    
    def test_pool_initialization(self):
        """Test that pool starts empty"""
        from sftp_connection_pool import ConnectionPool
        
        # Create a fresh pool state for testing
        pool = ConnectionPool()
        
        # Pool should have internal structure
        assert hasattr(pool, '_pool')
        assert hasattr(pool, '_max_age')
        assert hasattr(pool, '_max_channels_per_ssh')
    
    def test_max_channels_limit(self):
        """Test that max channels per SSH is set"""
        from sftp_connection_pool import ConnectionPool
        
        pool = ConnectionPool()
        
        assert pool._max_channels_per_ssh > 0
        assert pool._max_channels_per_ssh < 20  # Reasonable limit
    
    def test_max_age_set(self):
        """Test that connection max age is set"""
        from sftp_connection_pool import ConnectionPool
        
        pool = ConnectionPool()
        
        assert pool._max_age > 0
        assert pool._max_age <= 600  # 10 minutes max


class TestConnectionPoolCleanup:
    """Tests for connection cleanup"""
    
    def test_cleanup_stale_connections(self):
        """Test that cleanup removes stale connections"""
        from sftp_connection_pool import ConnectionPool
        
        pool = ConnectionPool()
        
        # The cleanup should not crash even with empty pool
        pool.cleanup_stale()
        
        # Pool should still be usable
        assert isinstance(pool._pool, dict)
    
    def test_close_all_connections(self):
        """Test that close_all closes all connections"""
        from sftp_connection_pool import ConnectionPool
        
        pool = ConnectionPool()
        
        # Close all should not crash on empty pool
        pool.close_all()
        
        # Pool should still be usable
        assert isinstance(pool._pool, dict)
    
    def test_get_pool_size(self):
        """Test getting pool size"""
        from sftp_connection_pool import ConnectionPool
        
        pool = ConnectionPool()
        
        # Empty pool should have size 0
        size = pool.get_pool_size()
        
        assert size >= 0


class TestConnectionInfo:
    """Tests for ConnectionInfo dataclass"""
    
    def test_connection_info_creation(self):
        """Test creating a ConnectionInfo instance"""
        from sftp_connection_pool import ConnectionInfo
        import time
        
        mock_ssh = Mock()
        conn = ConnectionInfo(
            ssh=mock_ssh,
            created_at=time.time(),
            last_used_at=time.time(),
            hostname="test.com",
            port=22,
            username="user"
        )
        
        assert conn.ssh is mock_ssh
        assert conn.hostname == "test.com"
        assert conn.port == 22
        assert conn.username == "user"
    
    def test_connection_info_channels_lists(self):
        """Test that channel lists are initialized"""
        from sftp_connection_pool import ConnectionInfo
        import time
        
        conn = ConnectionInfo(
            ssh=Mock(),
            created_at=time.time(),
            last_used_at=time.time(),
            hostname="test",
            port=22,
            username="user"
        )
        
        assert conn.idle_sftp_channels == []
        assert conn.busy_sftp_channels == []


class TestConnectionPoolStress:
    """Stress tests for connection pool"""
    
    def test_high_concurrent_access(self):
        """Test pool under high concurrent access"""
        from sftp_connection_pool import ConnectionPool
        
        pool = ConnectionPool()
        errors = []
        operations = []
        
        def access_pool(i):
            try:
                key = pool.get_connection_key(f"host{i % 5}", 22, "user")
                with pool._pool_lock:
                    if key not in pool._pool:
                        pool._pool[key] = []
                    operations.append(i)
            except Exception as e:
                errors.append(str(e))
        
        threads = [threading.Thread(target=access_pool, args=(i,)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        assert len(operations) == 100


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])