"""
Browser Mixins

Modular functionality for the Browser class, split into logical groups:
- TreeViewMixin: Directory tree view operations (stubs for subclass override)
- BookmarkMixin: Directory bookmark management
- FileOpsMixin: SFTP file operations using SFTPOperations API with caching
- DragDropMixin: Drag and drop support for file transfers
"""

from PySide6.QtWidgets import QMenu
from PySide6.QtCore import Qt
import os
import logging
import threading

from sftp_creds import get_credentials, sanitize_error_message
from sftp_operations import SFTPOperations
from sftp_drag_drop import start_drag, can_accept_drop, DragDropInfo

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
    """Mixin for SFTP file operations using SFTPOperations API with caching"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sftp_ops_cache = None
        self._sftp_ops_session_id = None
        self._sftp_ops_lock = threading.Lock()
    
    def get_sftp_operations(self):
        """Get cached SFTPOperations instance (thread-safe)"""
        with self._sftp_ops_lock:
            creds = get_credentials(self.session_id)
            
            if (self._sftp_ops_cache is not None and 
                self._sftp_ops_session_id == self.session_id):
                return self._sftp_ops_cache
            
            self._sftp_ops_cache = SFTPOperations(
                hostname=creds.get('hostname', ''),
                username=creds.get('username', ''),
                password=creds.get('password', ''),
                port=creds.get('port', 22),
                key=creds.get('key')
            )
            self._sftp_ops_session_id = self.session_id
            return self._sftp_ops_cache
    
    def clear_sftp_cache(self):
        """Clear cached SFTPOperations instance (thread-safe)"""
        with self._sftp_ops_lock:
            if self._sftp_ops_cache is not None:
                try:
                    self._sftp_ops_cache.close()
                except (OSError, IOError, RuntimeError):
                    pass
            self._sftp_ops_cache = None
            self._sftp_ops_session_id = None
    
    def sftp_mkdir(self, remote_path):
        """Create remote directory"""
        try:
            ops = self.get_sftp_operations()
            ops.mkdir(remote_path)
            self.message_signal.emit(f"Created directory: {remote_path}")
            return True
        except (OSError, IOError, RuntimeError) as e:
            self.message_signal.emit(f"Error creating directory: {sanitize_error_message(str(e))}")
            return False
    
    def sftp_rmdir(self, remote_path):
        """Remove remote directory"""
        try:
            ops = self.get_sftp_operations()
            ops.rmdir(remote_path)
            self.message_signal.emit(f"Removed directory: {remote_path}")
            return True
        except (OSError, IOError, RuntimeError) as e:
            self.message_signal.emit(f"Error removing directory: {sanitize_error_message(str(e))}")
            return False
    
    def sftp_remove(self, remote_path):
        """Remove remote file"""
        try:
            ops = self.get_sftp_operations()
            ops.remove(remote_path)
            self.message_signal.emit(f"Deleted: {remote_path}")
            return True
        except (OSError, IOError, RuntimeError) as e:
            self.message_signal.emit(f"Error deleting file: {sanitize_error_message(str(e))}")
            return False
    
    def sftp_rename(self, remote_path, new_name):
        """Rename remote file or directory"""
        try:
            ops = self.get_sftp_operations()
            ops.rename(remote_path, new_name)
            
            self.message_signal.emit(f"Renamed to: {new_name}")
            self.refresh_files()
            return True
        except (OSError, IOError, RuntimeError) as e:
            self.message_signal.emit(f"Error renaming: {sanitize_error_message(str(e))}")
            return False
    
    def sftp_exists(self, path):
        """Check if remote path exists"""
        try:
            ops = self.get_sftp_operations()
            return ops.exists(path)
        except (OSError, IOError, RuntimeError):
            return False
    
    def is_remote_directory(self, partial_remote_path):
        """Check if path is a directory"""
        try:
            ops = self.get_sftp_operations()
            return ops.is_directory(partial_remote_path)
        except (OSError, IOError, RuntimeError):
            return False
    
    def is_remote_file(self, partial_remote_path):
        """Check if path is a file"""
        try:
            ops = self.get_sftp_operations()
            return ops.is_file(partial_remote_path)
        except (OSError, IOError, RuntimeError):
            return False
    
    def sftp_listdir(self, remote_path):
        """List directory contents"""
        try:
            ops = self.get_sftp_operations()
            return ops.list(remote_path)
        except (OSError, IOError, RuntimeError) as e:
            return []
    
    def sftp_listdir_attr(self, remote_path):
        """List directory with attributes"""
        try:
            ops = self.get_sftp_operations()
            return ops.list_attr(remote_path)
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


class DragDropMixin:
    """
    Mixin for drag and drop support in file browsers.
    
    Provides:
    - Drag support for selected files/directories
    - Drop support for receiving files from other browsers
    - Transfer initiation when files are dropped
    """
    
    def setup_drag_drop(self):
        """Enable drag and drop on the table view."""
        if hasattr(self, 'table') and self.table:
            self.table.setDragEnabled(True)
            self.table.setAcceptDrops(True)
            self.table.setDropIndicatorShown(True)
            self.table.setDragDropMode(Qt.DragDropMode.DragDrop)
            self.table.setDefaultDropAction(Qt.DropAction.CopyAction)
    
    def start_drag(self):
        """Start a drag operation with selected files."""
        if not hasattr(self, 'table') or not self.table:
            return None
        
        # Determine source type
        source_type = 'remote' if self.is_remote_browser else 'local'
        
        # Get credentials for remote
        session_id = getattr(self, 'session_id', None)
        hostname = None
        username = None
        
        if source_type == 'remote' and session_id:
            creds = get_credentials(session_id)
            hostname = creds.get('hostname')
            username = creds.get('username')
        
        return start_drag(
            self.table,
            source_type,
            session_id=session_id,
            hostname=hostname,
            username=username
        )
    
    def can_accept_drop(self, mime_data):
        """Check if this browser can accept the dropped data."""
        dest_type = 'remote' if self.is_remote_browser else 'local'
        return can_accept_drop(mime_data, dest_type)
    
    def handle_drop(self, mime_data):
        """
        Handle dropped files.
        
        Returns True if drop was handled, False otherwise.
        """
        drag_info = DragDropInfo.from_mime_data(mime_data)
        if not drag_info:
            return False
        
        dest_type = 'remote' if self.is_remote_browser else 'local'
        
        # Check if drop is valid
        if not can_accept_drop(mime_data, dest_type):
            logger.warning(f"Drop rejected: {drag_info.source_type} -> {dest_type}")
            return False
        
        # Get destination directory
        if dest_type == 'remote':
            creds = get_credentials(self.session_id)
            dest_dir = creds.get('current_remote_directory', '.')
        else:
            creds = get_credentials(self.session_id)
            dest_dir = creds.get('current_local_directory', os.path.expanduser('~'))
        
        logger.info(f"Drop accepted: {len(drag_info.source_paths)} files from {drag_info.source_type} to {dest_type}")
        
        # Initiate transfer
        if drag_info.is_local() and dest_type == 'remote':
            # Upload
            self._initiate_upload(drag_info.source_paths, dest_dir)
        elif drag_info.is_remote() and dest_type == 'local':
            # Download
            self._initiate_download(drag_info.source_paths, dest_dir, 
                                    drag_info.hostname, drag_info.username)
        elif drag_info.is_remote() and dest_type == 'remote':
            # Server-to-server (on same host only for now)
            self._initiate_remote_copy(drag_info.source_paths, dest_dir)
        
        return True
    
    def _initiate_upload(self, source_paths, dest_dir):
        """Initiate upload of local files to remote."""
        if not hasattr(self, 'upload_files'):
            logger.warning("Upload not supported on this browser")
            return
        
        for source_path in source_paths:
            dest_path = os.path.join(dest_dir, os.path.basename(source_path))
            logger.info(f"Uploading: {source_path} -> {dest_path}")
            # Call upload method (to be implemented by subclass)
            if hasattr(self, 'upload_download'):
                # Get password/key from credentials
                pass  # Will be handled by existing upload mechanism
    
    def _initiate_download(self, source_paths, dest_dir, hostname, username):
        """Initiate download of remote files to local."""
        if not hasattr(self, 'upload_files'):
            logger.warning("Download not supported on this browser")
            return
        
        for source_path in source_paths:
            dest_path = os.path.join(dest_dir, os.path.basename(source_path))
            logger.info(f"Downloading: {source_path} -> {dest_path}")
    
    def _initiate_remote_copy(self, source_paths, dest_dir):
        """Initiate server-side copy (remote to remote)."""
        logger.warning("Remote-to-remote copy not yet implemented")
    
    def split_path(self, path):
        """Split path into directory and filename"""
        return os.path.split(path)
