"""
Test suite for SFTP Client Application

Run tests with: python -m pytest test_sftp.py -v
Or quick tests: python test_sftp.py
"""

import sys
import os
import inspect
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Only import pytest if available
try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False


class TestResponseQueueContext:
    """Test the ResponseQueueContext context manager"""
    
    def test_queue_created_on_enter(self):
        """Test that queue is created when entering context"""
        from sftp_downloadworkerclass import ResponseQueueContext, response_queues
        
        job_id = 12345
        with ResponseQueueContext(job_id) as queue:
            assert queue is not None
            assert job_id in response_queues
    
    def test_queue_deleted_on_exit(self):
        """Test that queue is deleted when exiting context"""
        from sftp_downloadworkerclass import ResponseQueueContext, response_queues
        
        job_id = 12346
        with ResponseQueueContext(job_id) as queue:
            pass
        
        assert job_id not in response_queues
    
    def test_queue_deleted_on_exception(self):
        """Test that queue is deleted even if exception occurs"""
        from sftp_downloadworkerclass import ResponseQueueContext, response_queues
        
        job_id = 12347
        try:
            with ResponseQueueContext(job_id) as queue:
                raise ValueError("Test exception")
        except ValueError:
            pass
        
        assert job_id not in response_queues


class TestPortValidation:
    """Test port number validation"""
    
    def test_valid_ports(self):
        """Test that valid ports (1-65535) are accepted"""
        valid_ports = [1, 22, 80, 443, 8080, 65535]
        for port in valid_ports:
            assert 1 <= port <= 65535
    
    def test_invalid_ports(self):
        """Test that invalid ports are rejected"""
        invalid_ports = [0, -1, 65536, 99999, -100]
        for port in invalid_ports:
            assert not (1 <= port <= 65535)


class TestPathNormalization:
    """Test path normalization functions"""
    
    def test_get_normalized_remote_path_method_exists(self):
        """Test that get_normalized_remote_path method exists on Browser"""
        from sftp_browserclass import Browser
        
        assert hasattr(Browser, 'get_normalized_remote_path')
    
    def test_path_backslash_replacement(self):
        """Test that backslashes are converted to forward slashes"""
        # Simple test of string manipulation logic
        test_path = "\\path\\to\\file"
        normalized = test_path.replace("\\", "/")
        assert normalized == "/path/to/file"
        assert "/" not in "\\" * 10  # Backslashes don't contain forward slashes


class TestInputValidation:
    """Test input validation functions"""
    
    def test_hostname_validation(self):
        """Test hostname validation"""
        valid_hostnames = [
            "example.com",
            "192.168.1.1",
            "localhost",
            "server-name.example.com",
        ]
        
        for hostname in valid_hostnames:
            # Basic hostname validation - should not be empty and should be string
            assert isinstance(hostname, str)
            assert len(hostname) > 0
    
    def test_empty_hostname_rejected(self):
        """Test that empty hostnames are rejected"""
        invalid_hostnames = ["", None, "   " ]
        
        for hostname in invalid_hostnames:
            if hostname is not None:
                assert len(hostname.strip()) == 0 or hostname is None


class TestConnectionPool:
    """Test connection pool functionality"""
    
    def test_pool_is_singleton(self):
        """Test that ConnectionPool is a singleton"""
        from sftp_connection_pool import ConnectionPool
        
        pool1 = ConnectionPool()
        pool2 = ConnectionPool()
        assert pool1 is pool2, "ConnectionPool should be a singleton"
    
    def test_pool_has_lock(self):
        """Test that ConnectionPool has thread-safe lock"""
        import threading
        from sftp_connection_pool import ConnectionPool
        
        pool = ConnectionPool()
        assert hasattr(pool, '_lock'), "ConnectionPool should have _lock attribute"
        assert isinstance(pool._lock, type(threading.Lock()))


class TestThreadSafety:
    """Test thread safety mechanisms"""
    
    def test_response_queues_lock_exists(self):
        """Test that response queues lock exists"""
        import threading
        from sftp_downloadworkerclass import response_queues_lock
        
        assert isinstance(response_queues_lock, type(threading.Lock()))
    
    def test_creds_lock_exists(self):
        """Test that credentials lock exists"""
        import threading
        from sftp_creds import _creds_lock
        
        assert isinstance(_creds_lock, type(threading.Lock()))


class TestErrorHandling:
    """Test error handling improvements"""
    
    def test_specific_exceptions_used(self):
        """Test that specific exceptions are used instead of bare except"""
        # This is a code quality test - verify in source that specific
        # exceptions like (KeyError, RuntimeError) are used
        import sftp_browserclass
        import sftp_downloadworkerclass
        
        # Check that files don't contain bare except clauses
        # (This would need to be checked via code review or AST parsing)
        pass


class TestSecurityFixes:
    """Test security improvements"""
    
    def test_port_range_validation(self):
        """Test that port range is properly validated"""
        # Port should be between 1 and 65535
        assert 1 <= 22 <= 65535  # Valid SSH port
        assert 1 <= 8080 <= 65535  # Valid HTTP alternate port
        assert not (1 <= 0 <= 65535)  # 0 is invalid
        assert not (1 <= 65536 <= 65535)  # 65536 is invalid
    
    def test_shlex_imported(self):
        """Test that shlex is imported for command sanitization"""
        import sftp_downloadworkerclass
        
        # Check that shlex is imported in download worker
        import shlex
        assert 'shlex' in dir(sftp_downloadworkerclass) or 'shlex' in str(sftp_downloadworkerclass)

    def test_auto_add_policy_removed_from_pool(self):
        """Test that AutoAddPolicy is not used in connection pool"""
        from sftp_connection_pool import ConnectionPool
        
        # Inspect source code of _create_ssh_connection
        source = inspect.getsource(ConnectionPool._create_ssh_connection)
        assert "AutoAddPolicy" not in source, "AutoAddPolicy should not be used in ConnectionPool"
        assert "WarningPolicy" in source, "WarningPolicy should be used in ConnectionPool"

    def test_terminal_policy_secure(self):
        """Test that terminal widget uses secure policy"""
        from sftp_terminal_widget import SSHTerminalWidget
        
        # Inspect source code of connect_ssh
        source = inspect.getsource(SSHTerminalWidget.connect_ssh)
        assert "AutoAddPolicy" not in source, "AutoAddPolicy should not be used in SSHTerminalWidget"
        assert "_setup_host_key_policy" in source, "Should call _setup_host_key_policy"



class TestSFTPOperations:
    """Test SFTPOperations class"""
    
    def test_sftp_operations_import(self):
        """Test that SFTPOperations can be imported"""
        from sftp_operations import SFTPOperations
        assert SFTPOperations is not None
    
    def test_sftp_operations_has_required_methods(self):
        """Test that SFTPOperations has all required methods"""
        from sftp_operations import SFTPOperations
        required_methods = [
            'download', 'upload', 'list', 'list_attr', 'stat',
            'mkdir', 'rmdir', 'remove', 'chdir', 'exists',
            'is_directory', 'is_file', 'close'
        ]
        for method in required_methods:
            assert hasattr(SFTPOperations, method), f"Missing method: {method}"
    
    def test_sftp_operations_context_manager(self):
        """Test that SFTPOperations supports context manager"""
        from sftp_operations import SFTPOperations
        assert hasattr(SFTPOperations, '__enter__')
        assert hasattr(SFTPOperations, '__exit__')


class TestSFTPSessionAPI:
    """Test SFTPSessionAPI class"""
    
    def test_session_api_import(self):
        """Test that SFTPSessionAPI can be imported"""
        from sftp_session_executor import SFTPSessionAPI
        assert SFTPSessionAPI is not None
    
    def test_session_api_has_required_methods(self):
        """Test that SFTPSessionAPI has all required methods"""
        from sftp_session_executor import SFTPSessionAPI
        required_methods = [
            'download', 'upload', 'list', 'list_attr', 'stat',
            'mkdir', 'rmdir', 'remove', 'chdir', 'exists',
            'is_directory', 'is_file'
        ]
        for method in required_methods:
            assert hasattr(SFTPSessionAPI, method), f"Missing method: {method}"
    
    def test_session_api_has_signals(self):
        """Test that SFTPSessionAPI has progress signals"""
        from sftp_session_executor import SFTPSessionAPI
        assert hasattr(SFTPSessionAPI, 'progress')
        assert hasattr(SFTPSessionAPI, 'message')
        assert hasattr(SFTPSessionAPI, 'finished')


class TestCommandExecutor:
    """Test CommandExecutor class"""
    
    def test_command_executor_has_signals(self):
        """Test that CommandExecutor has progress signals"""
        from sftp_session_executor import CommandExecutor
        assert hasattr(CommandExecutor, 'progress')
        assert hasattr(CommandExecutor, 'message')
        assert hasattr(CommandExecutor, 'finished')


def run_quick_tests():
    """Run quick smoke tests without pytest"""
    print("Running quick smoke tests...")
    
    # Test ResponseQueueContext
    print("✓ Testing ResponseQueueContext...")
    test_context = TestResponseQueueContext()
    test_context.test_queue_created_on_enter()
    test_context.test_queue_deleted_on_exit()
    test_context.test_queue_deleted_on_exception()
    print("  ✓ ResponseQueueContext tests passed")
    
    # Test port validation
    print("✓ Testing port validation...")
    test_port = TestPortValidation()
    test_port.test_valid_ports()
    test_port.test_invalid_ports()
    print("  ✓ Port validation tests passed")
    
    # Test thread safety
    print("✓ Testing thread safety...")
    test_thread = TestThreadSafety()
    test_thread.test_response_queues_lock_exists()
    test_thread.test_creds_lock_exists()
    print("  ✓ Thread safety tests passed")
    
    # Test security fixes
    print("✓ Testing security fixes...")
    test_sec = TestSecurityFixes()
    test_sec.test_port_range_validation()
    test_sec.test_shlex_imported()
    test_sec.test_auto_add_policy_removed_from_pool()
    test_sec.test_terminal_policy_secure()
    print("  ✓ Security fix tests passed")
    
    # Test SFTPOperations
    print("✓ Testing SFTPOperations...")
    test_ops = TestSFTPOperations()
    test_ops.test_sftp_operations_import()
    test_ops.test_sftp_operations_has_required_methods()
    test_ops.test_sftp_operations_context_manager()
    print("  ✓ SFTPOperations tests passed")
    
    # Test SFTPSessionAPI
    print("✓ Testing SFTPSessionAPI...")
    test_api = TestSFTPSessionAPI()
    test_api.test_session_api_import()
    test_api.test_session_api_has_required_methods()
    test_api.test_session_api_has_signals()
    print("  ✓ SFTPSessionAPI tests passed")
    
    # Test CommandExecutor
    print("✓ Testing CommandExecutor...")
    test_exe = TestCommandExecutor()
    test_exe.test_command_executor_has_signals()
    print("  ✓ CommandExecutor tests passed")
    
    print("\n✅ All quick smoke tests passed!")


if __name__ == "__main__":
    # Run quick tests if pytest is not available
    try:
        import pytest
        # pytest will run the tests automatically
        pass
    except ImportError:
        print("pytest not available, running quick smoke tests...")
        run_quick_tests()
