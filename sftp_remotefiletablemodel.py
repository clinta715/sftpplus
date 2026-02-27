from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QTimer, QDateTime, QEventLoop
from sftp_qt_compat import Qt  # Use compatibility layer for Qt enums
import base64
import queue
import time
from icecream import ic
from PyQt6.QtGui import QFont, QColor
from sftp_creds import get_credentials, create_random_integer
from sftp_downloadworkerclass import create_response_queue, delete_response_queue
from sftp_operations import SFTPOperations
import stat


_sftp_ops_cache = {}


def _get_sftp_operations(session_id):
    """Get cached SFTPOperations instance for session"""
    creds = get_credentials(session_id)
    
    if session_id in _sftp_ops_cache:
        return _sftp_ops_cache[session_id]
    
    ops = SFTPOperations(
        hostname=creds.get('hostname', ''),
        username=creds.get('username', ''),
        password=creds.get('password', ''),
        port=creds.get('port', 22),
        key=creds.get('key')
    )
    _sftp_ops_cache[session_id] = ops
    return ops

def _safe_decode(s, encoding='utf-8', errors='replace'):
    """Safely decode a string or bytes, handling encoding issues"""
    if s is None:
        return ""
    if isinstance(s, str):
        return s
    if isinstance(s, bytes):
        try:
            return s.decode(encoding, errors=errors)
        except (OSError, IOError, RuntimeError):
            try:
                return s.decode('latin-1', errors=errors)
            except (OSError, IOError, RuntimeError):
                return s.decode('utf-8', errors='backslashreplace')
    return str(s)


class RemoteFileTableModel(QAbstractTableModel):
    def __init__(self, session_id, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.file_list = []  # Initialize as an empty list
        self.column_names = ['Name', 'Size', 'Permissions', 'Modified']
        self.cache = {}  # Cache for directory listings
        self.cache_time = {}  # Track when each directory was last updated
        self.cache_duration = 60  # Cache duration in seconds
        self.attr_cache = {}  # Cache for file attributes
        self.attr_cache_time = {}  # Track when each file's attributes were last checked

    def is_remote_browser(self):
        return True

    def rowCount(self, parent=QModelIndex()):
        return len(self.file_list)

    def columnCount(self, parent=QModelIndex()):
        return len(self.column_names)

    def invalidate_cache(self, directory=None):
        if directory:
            self.cache.pop(directory, None)
            self.cache_time.pop(directory, None)
        else:
            self.cache.clear()
            self.cache_time.clear()

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.file_list)):
            return None

        try:
            file = self.file_list[index.row()]
        except (OSError, IOError, RuntimeError) as e:
            return None

        column = index.column()
        is_directory = stat.S_ISDIR(file[2])  # Use stat.S_ISDIR to check if it's a directory

        if role == Qt.DisplayRole:
            if column == 0:
                # Safely decode filename
                filename = _safe_decode(file[0])
                if is_directory:
                    return f"[DIR] {filename}"  # Fast text indicator for directories
                else:
                    return filename  # No indicator needed for files
            elif column == 1:
                return str(file[1])  # size
            elif column == 2:
                return oct(file[2])[-4:]  # permissions as a string
            elif column == 3:
                return _safe_decode(file[3])  # modified_date

        if role == Qt.FontRole:
            font = QFont()
            if is_directory:
                font.setBold(True)
            return font

        if role == Qt.ForegroundRole:
            if is_directory:
                return QColor(Qt.Color_blue)
            else:
                return QColor(Qt.Color_darkGray)

        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.column_names[section]
        return None

    def sort(self, column, order):
        # Skip sorting for very large directories to keep UI responsive
        if len(self.file_list) > 10000:
            return
            
        self.layoutAboutToBeChanged.emit()

        if column == 0:
            try:
                self.file_list.sort(key=lambda x: _safe_decode(x[0]), reverse=(order == Qt.DescendingOrder))
            except (OSError, IOError, RuntimeError) as e:
                pass
        elif column == 1:
            try:
                self.file_list.sort(key=lambda x: x[1], reverse=(order == Qt.DescendingOrder))
            except (OSError, IOError, RuntimeError) as e:
                pass
        elif column == 2:
            try:
                self.file_list.sort(key=lambda x: x[2], reverse=(order == Qt.DescendingOrder))
            except (OSError, IOError, RuntimeError) as e:
                pass
        elif column == 3:
            try:
                self.file_list.sort(key=lambda x: _safe_decode(x[3]), reverse=(order == Qt.DescendingOrder))
            except (OSError, IOError, RuntimeError) as e:
                pass

        self.layoutChanged.emit()

    def get_files(self, force_refresh=False, directory=None):
        """
        Get files for the specified directory.

        Args:
            force_refresh: If True, bypass cache and fetch fresh data
            directory: Optional directory path. If provided, uses this instead of fetching from credentials.
                      This prevents race conditions during directory navigation.
        """
        if directory is not None:
            # Use provided directory (avoids race condition during navigation)
            current_dir = directory
            ic(f"RemoteFileTableModel.get_files: using provided directory={current_dir}, force_refresh={force_refresh}")
        else:
            # Fetch from credentials (may be stale during navigation)
            creds = get_credentials(self.session_id)
            current_dir = creds.get('current_remote_directory', '.')
            ic(f"RemoteFileTableModel.get_files: session_id={self.session_id}, current_dir={current_dir}, force_refresh={force_refresh}")

        # Validate directory path
        if not current_dir or current_dir == '.':
            current_dir = '/'

        if not force_refresh and current_dir in self.cache and time.time() - self.cache_time.get(current_dir, 0) < self.cache_duration:
            if self.file_list == self.cache[current_dir]:
                return
            self.file_list = self.cache[current_dir]
            self.layoutChanged.emit()
            return

        items = self.sftp_listdir_attr(current_dir)

        self.beginResetModel()
        new_file_list = [("..", 0, 0, "----")]  # Parent directory entry

        for item in items:
            try:
                # Safely decode filename
                name = _safe_decode(item.filename)
                size = item.st_size
                permissions = item.st_mode  # Store st_mode as an integer
                modified_time = QDateTime.fromSecsSinceEpoch(item.st_mtime).toString(Qt.ISODate)
                new_file_list.append((name, size, permissions, modified_time))
            except (OSError, IOError, RuntimeError) as e:
                ic(f"Error processing file {item.filename if hasattr(item, 'filename') else 'unknown'}: {str(e)}")

        self.file_list = new_file_list
        self.cache[current_dir] = self.file_list
        self.cache_time[current_dir] = time.time()
        self.endResetModel()

        # Debug: verify what we loaded
        ic(f"RemoteFileTableModel.get_files: loaded {len(new_file_list)-1} items from {current_dir}")

    def non_blocking_sleep(self, ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def sftp_listdir_attr(self, remote_path):
        try:
            ops = _get_sftp_operations(self.session_id)
            result_list = ops.list_attr(remote_path)
            ic(f"sftp_listdir_attr: Success, got {len(result_list)} items")
            return result_list
        except Exception as e:
            ic(f"sftp_listdir_attr: Error: {e}")
            return []

