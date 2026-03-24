"""
Pytest configuration and fixtures for SFTP Client tests.
"""

import os
import sys
import pytest
from unittest.mock import Mock, MagicMock
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def qapp():
    """Create QApplication instance for the test session."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication(['-platform', 'offscreen'])
    yield app
    # Don't quit app in session fixture - it's shared


@pytest.fixture
def mock_session_id():
    """Return a mock session ID."""
    return 99999


@pytest.fixture
def mock_remote_browser(mock_session_id):
    """Create a mock RemoteFileBrowser."""
    browser = Mock()
    browser.session_id = mock_session_id
    browser.is_remote_browser.return_value = True
    browser.table = Mock()
    browser.table.selectedIndexes.return_value = []
    browser.table.currentIndex.return_value = Mock(isValid=lambda: False)
    return browser


@pytest.fixture
def mock_local_browser(mock_session_id):
    """Create a mock FileBrowser (local browser)."""
    browser = Mock()
    browser.session_id = mock_session_id
    browser.is_remote_browser.return_value = False
    browser.table = Mock()
    browser.table.selectedIndexes.return_value = []
    browser.table.currentIndex.return_value = Mock(isValid=lambda: False)
    return browser


@pytest.fixture
def mock_file_browser_panel(mock_remote_browser, mock_local_browser):
    """Create a mock FileBrowserPanel with both browsers."""
    panel = Mock()
    panel.left_browser = mock_local_browser
    panel.right_browser = mock_remote_browser
    panel._last_active_browser = mock_remote_browser
    panel.get_active_browser.return_value = mock_remote_browser
    return panel


@pytest.fixture
def mock_credentials():
    """Create mock credentials dict."""
    return {
        'hostname': 'test.example.com',
        'username': 'testuser',
        'password': 'testpass',
        'port': 22,
        'current_remote_directory': '/home/testuser',
        'current_local_directory': '/tmp/test',
        'key': None
    }


@pytest.fixture
def mock_sftp_operations():
    """Create mock SFTPOperations."""
    ops = Mock()
    ops.download.return_value = None
    ops.upload.return_value = None
    ops.list.return_value = []
    ops.list_attr.return_value = []
    ops.stat.return_value = Mock(st_size=100, st_mode=0o100644)
    ops.exists.return_value = True
    ops.is_directory.return_value = False
    ops.is_file.return_value = True
    ops.mkdir.return_value = True
    ops.rmdir.return_value = True
    ops.remove.return_value = True
    ops.chdir.return_value = True
    ops.close.return_value = None
    return ops


@pytest.fixture
def mock_session_api(mock_sftp_operations):
    """Create mock SFTPSessionAPI."""
    api = Mock()
    api.session = Mock()
    api.session.get_next_job_id.return_value = 'test-job-123'
    api.session.session_id = 'session-123'
    api.download.return_value = None
    api.upload.return_value = None
    api.list.return_value = []
    api.list_attr.return_value = []
    api.stat.return_value = Mock(st_size=100, st_mode=0o100644)
    api.exists.return_value = True
    api.is_directory.return_value = False
    api.is_file.return_value = True
    api.mkdir.return_value = True
    api.rmdir.return_value = True
    api.remove.return_value = True
    api.chdir.return_value = True
    api.rename.return_value = True
    return api


@pytest.fixture
def temp_local_dir(tmp_path):
    """Create a temporary local directory for testing."""
    test_dir = tmp_path / "test_files"
    test_dir.mkdir()
    
    # Create some test files
    (test_dir / "file1.txt").write_text("test content 1")
    (test_dir / "file2.txt").write_text("test content 2")
    subdir = test_dir / "subdir"
    subdir.mkdir()
    (subdir / "file3.txt").write_text("test content 3")
    
    return str(test_dir)


@pytest.fixture
def mock_qmessagebox():
    """Mock QMessageBox to avoid actual dialogs."""
    from unittest.mock import patch
    with patch('PySide6.QtWidgets.QMessageBox.question') as mock:
        mock.return_value = Mock()  # Return value will be set in tests
        yield mock


@pytest.fixture
def mock_qinputdialog():
    """Mock QInputDialog to avoid actual dialogs."""
    from unittest.mock import patch
    with patch('PySide6.QtWidgets.QInputDialog.getText') as mock:
        mock.return_value = ('new_name', True)
        yield mock
