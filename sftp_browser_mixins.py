"""
Browser Mixins

Modular functionality for the Browser class, split into logical groups:
- TreeViewMixin: Directory tree view operations (stubs for subclass override)
- BookmarkMixin: Directory bookmark management
- FileOpsMixin: SFTP file operations using SFTPOperations API with caching
"""

from PyQt6.QtWidgets import QMenu, QInputDialog, QMessageBox
from sftp_qt_compat import Qt
from icecream import ic
import os
import threading

from sftp_creds import get_credentials, sanitize_error_message
from sftp_hostdataeditor import load_connection_data, save_connection_data
from sftp_operations import SFTPOperations


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
    """Mixin for directory bookmark management"""
    
    def add_bookmark(self):
        """Add current directory to bookmarks"""
        try:
            creds = get_credentials(self.session_id)
            hostname = creds.get('hostname', '')
            is_remote = self.is_remote_browser() if hasattr(self, 'is_remote_browser') else False
            current_dir = creds.get('current_remote_directory' if is_remote else 'current_local_directory', '.')
            
            if not hostname:
                self.message_signal.emit("Cannot add bookmark: no hostname")
                return False
            
            name, ok = QInputDialog.getText(
                self, "Add Bookmark",
                f"Enter name for bookmark:\n{current_dir}",
                text=os.path.basename(current_dir) or "Root"
            )
            
            if not ok or not name:
                return False
            
            host_data = load_connection_data()
            
            if 'bookmarks' not in host_data:
                host_data['bookmarks'] = {}
            
            if hostname not in host_data['bookmarks']:
                host_data['bookmarks'][hostname] = []
            
            for existing in host_data['bookmarks'][hostname]:
                if isinstance(existing, dict) and existing.get('path') == current_dir:
                    self.message_signal.emit("Bookmark already exists for this directory")
                    return False
            
            host_data['bookmarks'][hostname].append({
                'name': name,
                'path': current_dir,
                'is_remote': is_remote
            })
            
            if save_connection_data(host_data):
                self.message_signal.emit(f"Bookmark added: {name}")
                return True
            else:
                self.message_signal.emit("Failed to save bookmark")
                return False
                
        except (OSError, IOError, RuntimeError) as e:
            self.message_signal.emit(f"Error adding bookmark: {sanitize_error_message(str(e))}")
            return False
    
    def get_bookmarks(self):
        """Get bookmarks for current hostname"""
        try:
            host_data = load_connection_data()
            creds = get_credentials(self.session_id)
            hostname = creds.get('hostname', 'localhost')
            
            bookmarks = host_data.get('bookmarks', {}).get(hostname, [])
            normalized = []
            for b in bookmarks:
                if isinstance(b, str):
                    normalized.append({'name': b, 'path': b})
                else:
                    normalized.append(b)
            return normalized
        except (OSError, IOError, RuntimeError):
            return []
    
    def navigate_to_bookmark(self, path):
        """Navigate to bookmarked path"""
        self.change_directory(path)
        return True
    
    def _show_bookmarks_menu(self):
        """Show bookmarks dropdown menu"""
        bookmarks = self.get_bookmarks()
        menu = QMenu(self)
        
        add_action = menu.addAction("⭐ Add Current Directory")
        add_action.triggered.connect(lambda: self.add_bookmark())
        
        if bookmarks:
            menu.addSeparator()
            for bm in bookmarks:
                if isinstance(bm, dict):
                    name = bm.get('name', bm.get('path', 'Unknown'))
                    path = bm.get('path', '')
                    action = menu.addAction(f"📁 {name}")
                    action.triggered.connect(lambda checked, p=path: self.navigate_to_bookmark(p))
        
        menu.addSeparator()
        manage_action = menu.addAction("⚙️ Manage Bookmarks...")
        manage_action.triggered.connect(self._manage_bookmarks)
        
        menu.exec(self.bookmarks_btn.mapToGlobal(self.bookmarks_btn.rect().bottomLeft()))
    
    def _manage_bookmarks(self):
        """Manage existing bookmarks"""
        bookmarks = self.get_bookmarks()
        if not bookmarks:
            QMessageBox.information(self, "Manage Bookmarks", "No bookmarks to manage.")
            return
        
        items = []
        for bm in bookmarks:
            if isinstance(bm, dict):
                items.append(f"{bm.get('name', 'Unknown')} - {bm.get('path', '')}")
        
        item, ok = QInputDialog.getItem(
            self, "Manage Bookmarks", 
            "Select bookmark to delete:", 
            items, 0, False
        )
        
        if ok and item:
            host_data = load_connection_data()
            creds = get_credentials(self.session_id)
            hostname = creds.get('hostname', 'localhost')
            
            name = item.split(' - ')[0]
            host_data['bookmarks'][hostname] = [
                bm for bm in host_data.get('bookmarks', {}).get(hostname, [])
                if isinstance(bm, dict) and bm.get('name') != name
            ]
            
            if save_connection_data(host_data):
                self.message_signal.emit(f"Bookmark '{name}' deleted")


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
            parent = os.path.dirname(remote_path)
            new_path = os.path.join(parent, new_name)
            
            ssh = ops._api._get_ssh()
            ssh.exec_command(f'mv "{remote_path}" "{new_path}"')
            
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
            ic(f"Error listing directory: {sanitize_error_message(str(e))}")
            return []
    
    def sftp_listdir_attr(self, remote_path):
        """List directory with attributes"""
        try:
            ops = self.get_sftp_operations()
            return ops.list_attr(remote_path)
        except (OSError, IOError, RuntimeError) as e:
            ic(f"Error listing directory attrs: {sanitize_error_message(str(e))}")
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
    
    def split_path(self, path):
        """Split path into directory and filename"""
        return os.path.split(path)
