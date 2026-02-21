from PyQt6.QtCore import pyqtSignal
from sftp_qt_compat import Qt  # Use compatibility layer for Qt enums
from sftp_creds import get_credentials
import os


class NavigationMixin:
    """Mixin class providing navigation and bookmark functionality for file browsers.
    
    This class handles:
    - Directory navigation (up, into, bookmarks)
    - Path normalization and validation
    - Tree view navigation for remote browsers
    """

    navigate_signal = pyqtSignal(str)

    def navigate_to_parent(self):
        """Navigate to the parent directory of the current directory."""
        creds = get_credentials(self.session_id)
        current_remote_directory = creds.get('current_remote_directory', '/')
        
        if current_remote_directory == '/':
            return
        
        parent = os.path.dirname(current_remote_directory)
        if not parent:
            parent = '/'
        
        self.change_directory(parent)

    def change_directory(self, path):
        """Change to the specified directory and refresh the file list."""
        if not path:
            return
            
        creds = get_credentials(self.session_id)
        creds['current_remote_directory'] = path
        from sftp_creds import set_credentials
        set_credentials(self.session_id, 'current_remote_directory', path)
        
        self.get_files(force_refresh=True)
        self.navigate_signal.emit(path)

    def get_current_directory(self):
        """Get the current working directory from credentials."""
        creds = get_credentials(self.session_id)
        return creds.get('current_remote_directory', '/')

    def get_normalized_remote_path(self, current_remote_directory, partial_remote_path=None):
        """Normalize a partial remote path to a full path.
        
        Args:
            current_remote_directory: The current working directory
            partial_remote_path: The partial path to normalize
            
        Returns:
            The normalized full path
        """
        if not partial_remote_path:
            return current_remote_directory
            
        if self.is_complete_path(partial_remote_path):
            return partial_remote_path
            
        if current_remote_directory == '/':
            normalized = '/' + partial_remote_path
        else:
            normalized = current_remote_directory + '/' + partial_remote_path
            
        return normalized.replace('//', '/').rstrip('/') or '/'

    def is_complete_path(self, path):
        """Check if the given path is a complete (absolute) path.
        
        Args:
            path: The path to check
            
        Returns:
            True if path starts with '/' (absolute path)
        """
        return path.startswith('/')

    def split_path(self, path):
        """Split a path into directory and filename.
        
        Args:
            path: The path to split
            
        Returns:
            Tuple of (directory, filename)
        """
        path = path.rstrip('/')
        if not path or path == '/':
            return ('/', '')
        
        if '/' in path:
            directory = path.rsplit('/', 1)[0]
            if not directory:
                directory = '/'
            filename = path.rsplit('/', 1)[1]
            return (directory, filename)
        else:
            return ('/', path)

    def normalize_path(self, path):
        """Normalize a path by removing double slashes and trailing slashes.
        
        Args:
            path: The path to normalize
            
        Returns:
            The normalized path
        """
        if not path:
            return '/'
        path = path.replace('//', '/')
        if path != '/' and path.endswith('/'):
            path = path.rstrip('/')
        return path or '/'

    def tree_go_up(self):
        """Navigate up one level in tree view."""
        self.navigate_to_parent()

    def tree_path_navigate(self, path):
        """Navigate to a specific path in tree view.
        
        Args:
            path: The path to navigate to
        """
        self.change_directory(path)

    def navigate_to_bookmark(self, path):
        """Navigate to a bookmarked path.
        
        Args:
            path: The bookmarked path to navigate to
        """
        self.change_directory(path)

    def add_bookmark(self, name=None):
        """Add current directory as a bookmark.
        
        Args:
            name: Optional name for the bookmark. If None, uses directory name.
            
        Returns:
            True if bookmark was added successfully
        """
        try:
            from sftp_hostdataeditor import load_connection_data, save_connection_data
            
            host_data = load_connection_data()
            creds = get_credentials(self.session_id)
            hostname = creds.get('hostname', 'localhost')
            current_dir = creds.get('current_remote_directory', '/')
            
            if hostname not in host_data:
                host_data['bookmarks'] = {}
            
            if hostname not in host_data['bookmarks']:
                host_data['bookmarks'][hostname] = []
            
            bookmark_name = name or os.path.basename(current_dir.rstrip('/')) or '/'
            
            bookmark = {
                'name': bookmark_name,
                'path': current_dir
            }
            
            for bm in host_data['bookmarks'][hostname]:
                if isinstance(bm, dict) and bm.get('path') == current_dir:
                    self.message_signal.emit("Bookmark already exists for this path")
                    return False
            
            host_data['bookmarks'][hostname].append(bookmark)
            
            if save_connection_data(host_data):
                self.message_signal.emit(f"Bookmark added: {bookmark_name}")
                return True
            
            return False
            
        except (OSError, IOError, RuntimeError) as e:
            self.message_signal.emit(f"Error adding bookmark: {e}")
            return False

    def get_bookmarks(self):
        """Get bookmarks for the current hostname.
        
        Returns:
            List of bookmark dictionaries
        """
        try:
            from sftp_hostdataeditor import load_connection_data
            
            host_data = load_connection_data()
            creds = get_credentials(self.session_id)
            hostname = creds.get('hostname', 'localhost')
            
            return host_data.get('bookmarks', {}).get(hostname, [])
            
        except (OSError, IOError, RuntimeError) as e:
            self.message_signal.emit(f"Error loading bookmarks: {e}")
            return []
