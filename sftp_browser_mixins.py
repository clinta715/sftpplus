"""
Browser Mixins

Modular functionality for the Browser class, split into logical groups:
- TreeViewMixin: Directory tree view operations (stubs for subclass override)
- BookmarkMixin: Directory bookmark management
- FileOpsMixin: SFTP file operations using SFTPOperations API (dead code - overridden by Browser)
"""

from PySide6.QtWidgets import QMenu
from PySide6.QtCore import Qt
import os
import logging

from sftp_creds import get_credentials, sanitize_error_message
from sftp_operations import SFTPOperations

logger = logging.getLogger('sftp.browser')


class TreeViewMixin:
    """Mixin for directory tree view functionality - stubs for subclass override"""
    
    def populate_tree_view(self):
        """Populate tree view - override in subclasses"""
        pass
    
    def tree_double_click_handler(self, item, column):
        """Handle tree double-click - override in subclasses"""
        pass
    
    def tree_context_menu_handler(self, pos):
        """Handle tree context menu - override in subclasses"""
        pass
    
    def tree_item_expanded_handler(self, item):
        """Handle tree item expansion - override in subclasses"""
        pass
    
    def tree_go_up(self):
        """Navigate tree to parent - override in subclasses"""
        pass
    
    def tree_path_navigate(self):
        """Navigate to path in tree input - override in subclasses"""
        pass
    
    def tree_download_selected(self):
        """Download selected tree item - override in subclasses"""
        pass
    
    def tree_download_all(self):
        """Download all visible tree items - override in subclasses"""
        pass
    
    def tree_delete_selected(self):
        """Delete selected tree item - override in subclasses"""
        pass


class BookmarkMixin:
    """Mixin stub for directory bookmark management.

    All bookmark methods are defined directly on Browser in sftp_browserclass.py.
    This mixin is kept only for MRO compatibility.
    """
    pass


class FileOpsMixin:
    """Mixin for SFTP file operations using SFTPOperations API.
    
    Note: The Browser class overrides all methods in this mixin via MRO.
    This mixin is kept for documentation of the intended SFTPOperations-based
    interface pattern. See sftp_browserclass.py for the active implementations
    which use session_api instead.
    """

    def get_sftp_operations(self):
        """Create a new SFTPOperations instance from session credentials"""
        return self._create_ops()

    def _create_ops(self):
        """Create a new SFTPOperations instance from session credentials"""
        creds = get_credentials(self.session_id)
        return SFTPOperations(
            hostname=creds.get('hostname', ''),
            username=creds.get('username', ''),
            password=creds.get('password', ''),
            port=creds.get('port', 22),
            key=creds.get('key')
        )

    def sftp_mkdir(self, remote_path):
        """Create remote directory"""
        try:
            ops = self._create_ops()
            try:
                ops.mkdir(remote_path)
                self.message_signal.emit(f"Created directory: {remote_path}")
                return True
            finally:
                ops.close()
        except (OSError, IOError, RuntimeError) as e:
            self.message_signal.emit(f"Error creating directory: {sanitize_error_message(str(e))}")
            return False
    
    def sftp_rmdir(self, remote_path):
        """Remove remote directory"""
        try:
            ops = self._create_ops()
            try:
                ops.rmdir(remote_path)
                self.message_signal.emit(f"Removed directory: {remote_path}")
                return True
            finally:
                ops.close()
        except (OSError, IOError, RuntimeError) as e:
            self.message_signal.emit(f"Error removing directory: {sanitize_error_message(str(e))}")
            return False
    
    def sftp_remove(self, remote_path):
        """Remove remote file"""
        try:
            ops = self._create_ops()
            try:
                ops.remove(remote_path)
                self.message_signal.emit(f"Deleted: {remote_path}")
                return True
            finally:
                ops.close()
        except (OSError, IOError, RuntimeError) as e:
            self.message_signal.emit(f"Error deleting file: {sanitize_error_message(str(e))}")
            return False
    
    def sftp_rename(self, remote_path, new_name):
        """Rename remote file or directory"""
        try:
            ops = self._create_ops()
            try:
                ops.rename(remote_path, new_name)
                self.message_signal.emit(f"Renamed to: {new_name}")
                self.refresh_files()
                return True
            finally:
                ops.close()
        except (OSError, IOError, RuntimeError) as e:
            self.message_signal.emit(f"Error renaming: {sanitize_error_message(str(e))}")
            return False
    
    def sftp_exists(self, path):
        """Check if remote path exists"""
        try:
            ops = self._create_ops()
            try:
                return ops.exists(path)
            finally:
                ops.close()
        except (OSError, IOError, RuntimeError):
            return False
    
    def is_remote_directory(self, partial_remote_path):
        """Check if path is a directory"""
        try:
            ops = self._create_ops()
            try:
                return ops.is_directory(partial_remote_path)
            finally:
                ops.close()
        except (OSError, IOError, RuntimeError):
            return False
    
    def is_remote_file(self, partial_remote_path):
        """Check if path is a file"""
        try:
            ops = self._create_ops()
            try:
                return ops.is_file(partial_remote_path)
            finally:
                ops.close()
        except (OSError, IOError, RuntimeError):
            return False
    
    def sftp_listdir(self, remote_path):
        """List directory contents"""
        try:
            ops = self._create_ops()
            try:
                return ops.list(remote_path)
            finally:
                ops.close()
        except (OSError, IOError, RuntimeError) as e:
            return []
    
    def sftp_listdir_attr(self, remote_path):
        """List directory with attributes"""
        try:
            ops = self._create_ops()
            try:
                return ops.list_attr(remote_path)
            finally:
                ops.close()
        except (OSError, IOError, RuntimeError) as e:
            return []
    
    def get_normalized_remote_path(self, current_remote_directory, partial_remote_path=None):
        """Normalize and join remote paths"""
        if partial_remote_path is None:
            return current_remote_directory
        
        if self.is_complete_path(partial_remote_path):
            return partial_remote_path
        
        return os.path.normpath(os.path.join(current_remote_directory, partial_remote_path))
    
    def normalize_path(self, path):
        """Normalize path for current OS"""
        return os.path.normpath(path)
    
    def is_complete_path(self, path):
        """Check if path is absolute (complete)"""
        return path.startswith('/')
