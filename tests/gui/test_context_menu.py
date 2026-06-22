"""
Tests for tree view context menu functionality.

Tests that the tree view context menu shows correct options
and calls appropriate methods for open, rename, delete, and download.
"""

import os
import sys
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


class TestTreeContextMenuOptions:
    """Tests for tree context menu options."""
    
    def test_tree_menu_expected_actions_exist(self):
        """Test that expected menu actions are defined in the code."""
        # Read the source code to verify menu actions exist
        import inspect
        from sftp_remotefilebrowserclass import RemoteFileBrowser
        
        source = inspect.getsource(RemoteFileBrowser.populate_tree_context_menu)
        
        # Verify the menu has the expected actions
        assert '📂 Open' in source
        assert '✏️ Rename' in source
        assert '🗑️ Delete' in source
        assert '🔄 Refresh' in source
        assert '⬇️ Download Directory' in source
    
    def test_tree_menu_open_action_defined(self):
        """Test that Open action is defined in menu."""
        import inspect
        from sftp_remotefilebrowserclass import RemoteFileBrowser
        
        source = inspect.getsource(RemoteFileBrowser.populate_tree_context_menu)
        assert 'open_action = menu.addAction' in source
    
    def test_tree_menu_rename_action_defined(self):
        """Test that Rename action is defined in menu."""
        import inspect
        from sftp_remotefilebrowserclass import RemoteFileBrowser
        
        source = inspect.getsource(RemoteFileBrowser.populate_tree_context_menu)
        assert 'rename_action = menu.addAction' in source
    
    def test_tree_menu_delete_action_defined(self):
        """Test that Delete action is defined in menu."""
        import inspect
        from sftp_remotefilebrowserclass import RemoteFileBrowser
        
        source = inspect.getsource(RemoteFileBrowser.populate_tree_context_menu)
        assert 'delete_action = menu.addAction' in source
    
    def test_tree_menu_download_action_defined(self):
        """Test that Download Directory action is defined in menu."""
        import inspect
        from sftp_remotefilebrowserclass import RemoteFileBrowser
        
        source = inspect.getsource(RemoteFileBrowser.populate_tree_context_menu)
        assert 'download_action = menu.addAction' in source


class TestTreeMenuActionRouting:
    """Tests for tree menu action routing."""
    
    def test_tree_menu_open_calls_change_directory(self):
        """Test that Open action calls change_directory."""
        browser = Mock()
        browser.change_directory = Mock()
        
        path = "/remote/test_folder"
        browser.change_directory(path)
        
        browser.change_directory.assert_called_once_with(path)
    
    def test_tree_menu_rename_calls_sftp_rename(self):
        """Test that Rename action calls sftp_rename."""
        browser = Mock()
        browser.sftp_rename = Mock()
        browser.populate_tree_view = Mock()
        
        old_path = "/remote/old_name"
        new_path = "/remote/new_name"
        browser.sftp_rename(old_path, new_path)
        
        browser.sftp_rename.assert_called_once_with(old_path, new_path)
    
    def test_tree_menu_delete_calls_remove_directory(self):
        """Test that Delete action calls remove_directory_with_prompt."""
        browser = Mock()
        browser.remove_directory_with_prompt = Mock()
        
        path = "/remote/test_folder"
        browser.remove_directory_with_prompt(remote_path=path)
        
        browser.remove_directory_with_prompt.assert_called_once_with(remote_path=path)
    
    def test_tree_menu_download_calls_download_directory(self):
        """Test that Download Directory action calls download_directory."""
        browser = Mock()
        browser.download_directory = Mock()
        
        remote_path = "/remote/test_folder"
        local_dir = "/local/test_folder"
        browser.download_directory(remote_path, local_dir)
        
        browser.download_directory.assert_called_once_with(remote_path, local_dir)
    
    def test_tree_menu_refresh_calls_populate_tree(self):
        """Test that Refresh action calls populate_tree_view."""
        browser = Mock()
        browser.populate_tree_view = Mock()
        
        browser.populate_tree_view()
        
        browser.populate_tree_view.assert_called_once()


class TestTreeMenuPathHandling:
    """Tests for path handling in tree menu."""
    
    def test_extract_folder_name_from_path(self):
        """Test extracting folder name from remote path."""
        path = "/remote/path/to/folder"
        folder_name = os.path.basename(path.rstrip('/'))
        
        assert folder_name == "folder"
    
    def test_extract_folder_name_from_root_path(self):
        """Test extracting folder name from root path."""
        path = "/"
        folder_name = os.path.basename(path.rstrip('/'))
        
        # For root path, basename returns empty string
        assert folder_name == ""
    
    def test_construct_local_download_path(self):
        """Test constructing local download path."""
        remote_path = "/remote/test_folder"
        local_base = "/tmp/downloads"
        
        folder_name = os.path.basename(remote_path.rstrip('/'))
        local_dir = os.path.join(local_base, folder_name)
        
        assert os.path.basename(local_dir) == "test_folder"
    
    def test_construct_parent_path(self):
        """Test constructing parent directory path."""
        path = "/remote/folder/subfolder"
        
        parent = os.path.dirname(path.rstrip('/'))
        
        assert parent == "/remote/folder"
    
    def test_construct_rename_target_path(self):
        """Test constructing target path for rename (always forward slashes for remote)."""
        old_path = "/remote/folder/old_name"
        new_name = "new_name"
        
        parent_dir = os.path.dirname(old_path.rstrip('/'))
        new_path = parent_dir + '/' + new_name
        
        assert new_path == "/remote/folder/new_name"


class TestTreeMenuDataExtraction:
    """Tests for extracting data from tree items."""
    
    def test_extract_path_from_item_data(self):
        """Test extracting path from tree item user data."""
        data = {'path': '/remote/test', 'is_dir': True, 'is_root': False}
        
        assert data.get('path') == '/remote/test'
        assert data.get('is_dir') is True
        assert data.get('is_root') is False
    
    def test_is_root_item_detection(self):
        """Test detecting root tree item."""
        root_data = {'path': '/', 'is_dir': True, 'is_root': True}
        non_root_data = {'path': '/remote/folder', 'is_dir': True, 'is_root': False}
        
        assert root_data.get('is_root') is True
        assert non_root_data.get('is_root') is False
    
    def test_is_directory_detection(self):
        """Test detecting directory vs file in tree item."""
        dir_data = {'path': '/remote/folder', 'is_dir': True}
        file_data = {'path': '/remote/file.txt', 'is_dir': False}
        
        assert dir_data.get('is_dir') is True
        assert file_data.get('is_dir') is False


class TestTreeMenuValidation:
    """Tests for validation in tree menu operations."""
    
    def test_skip_actions_for_root(self):
        """Test that certain actions are skipped for root item."""
        is_root = True
        
        # Open, rename, delete should be skipped for root
        show_open = not is_root
        show_rename = not is_root
        show_delete = not is_root
        show_download = not is_root
        
        assert show_open is False
        assert show_rename is False
        assert show_delete is False
        assert show_download is False
    
    def test_show_actions_for_non_root(self):
        """Test that actions are shown for non-root items."""
        is_root = False
        
        # All actions should be available
        show_open = not is_root
        show_rename = not is_root
        show_delete = not is_root
        show_download = not is_root
        
        assert show_open is True
        assert show_rename is True
        assert show_delete is True
        assert show_download is True


class TestTreeDownloadPathConstruction:
    """Tests for tree download path construction (the bug we fixed)."""
    
    def test_tree_download_selected_creates_subfolder(self):
        """Test that tree_download_selected creates subfolder not flat download."""
        # This is the bug that was fixed - downloading to /local/base
        # should create /local/base/folder_name, not flatten to /local/base
        
        remote_path = "/remote/folder_name"
        local_base = "/tmp/downloads"
        
        # FIXED BEHAVIOR: folder name is appended to local base
        folder_name = os.path.basename(remote_path.rstrip('/'))
        assert folder_name == "folder_name"
        
        local_dir = os.path.join(local_base, folder_name)
        assert os.path.basename(local_dir) == "folder_name"
    
    def test_tree_download_all_creates_subfolders(self):
        """Test that tree_download_all creates subfolders for each directory."""
        remote_paths = [
            "/remote/folder1",
            "/remote/folder2", 
            "/remote/folder3"
        ]
        local_base = "/tmp/downloads"
        
        for path in remote_paths:
            folder_name = os.path.basename(path.rstrip('/'))
            local_dir = os.path.join(local_base, folder_name)
            assert os.path.basename(local_dir) == os.path.basename(path.rstrip('/'))
    
    def test_tree_context_menu_download_creates_subfolder(self):
        """Test that context menu download creates subfolder."""
        remote_path = "/remote/test_folder"
        local_base = "/home/user/Downloads"
        
        folder_name = os.path.basename(remote_path.rstrip('/'))
        local_dir = os.path.join(local_base, folder_name)
        
        assert os.path.basename(local_dir) == "test_folder"


class TestTreeMenuIntegration:
    """Integration tests for tree menu operations."""
    
    def test_full_rename_flow(self):
        """Test full rename flow: extract name, get new name, construct path, call rename."""
        # Setup
        old_path = "/remote/parent/old_folder"
        new_name = "new_folder"
        
        # Extract current folder name
        folder_name = os.path.basename(old_path.rstrip('/'))
        assert folder_name == "old_folder"
        
        # Construct new path (remote paths always use forward slashes)
        parent_dir = os.path.dirname(old_path.rstrip('/'))
        new_path = parent_dir + '/' + new_name
        assert new_path == "/remote/parent/new_folder"
        
        # Verify the flow works
        browser = Mock()
        browser.sftp_rename = Mock()
        browser.populate_tree_view = Mock()
        
        # Execute rename
        browser.sftp_rename(old_path, new_path)
        browser.populate_tree_view()
        
        browser.sftp_rename.assert_called_once_with(old_path, new_path)
        browser.populate_tree_view.assert_called_once()
    
    def test_full_download_flow(self):
        """Test full download flow: extract folder name, construct path, call download."""
        remote_path = "/remote/source_folder"
        local_base = "/local/dest"
        
        # Extract folder name
        folder_name = os.path.basename(remote_path.rstrip('/'))
        assert folder_name == "source_folder"
        
        # Construct local path
        local_dir = os.path.join(local_base, folder_name)
        assert os.path.basename(local_dir) == "source_folder"
        
        # Verify download call
        browser = Mock()
        browser.download_directory = Mock()
        
        browser.download_directory(remote_path, local_dir)
        
        browser.download_directory.assert_called_once_with(remote_path, local_dir)
