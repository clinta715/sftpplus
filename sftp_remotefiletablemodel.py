from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QTimer, QDateTime, QEventLoop, pyqtSignal
from PyQt6.QtWidgets import QApplication
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
    # Signals for status updates and loading state
    status_message = pyqtSignal(str)
    loading_started = pyqtSignal()
    loading_finished = pyqtSignal()

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
            file_data = self.file_list[index.row()]
            name = file_data[0]
            size = file_data[1]
            mode = file_data[2]
            mtime_str = file_data[3]
            # Parent directory doesn't have an attr item (file_data[4])
            is_directory = stat.S_ISDIR(mode) if name != ".." else True
        except (Exception) as e:
            return None

        column = index.column()

        if role == Qt.DisplayRole:
            if column == 0:
                # Safely decode filename
                filename = _safe_decode(name)
                if is_directory and filename != "..":
                    return f"[DIR] {filename}"
                else:
                    return filename
            elif column == 1:
                return str(size)
            elif column == 2:
                return oct(mode)[-4:] if name != ".." else ""
            elif column == 3:
                return _safe_decode(mtime_str)

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

        if role == Qt.UserRole:
            # Return the full attr item if available (file_data[4])
            return file_data[4] if len(file_data) > 4 else None

        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.column_names[section]
        return None

    def sort(self, column, order):
        # Don't sort here - let DirectoryFirstSortProxyModel handle sorting
        pass

    def get_files(self, force_refresh=False, directory=None):
        """
        Get files for the specified directory.
        """
        if directory is not None:
            current_dir = directory
        else:
            creds = get_credentials(self.session_id)
            current_dir = creds.get('current_remote_directory', '.')

        # Validate directory path
        if not current_dir or current_dir == '.':
            current_dir = '/'

        if not force_refresh and current_dir in self.cache and time.time() - self.cache_time.get(current_dir, 0) < self.cache_duration:
            cached = self.cache[current_dir]
            if self.file_list == cached:
                return
            self.beginResetModel()
            self.file_list = list(cached)
            self.endResetModel()
            return

        # Notify that we're starting a fetch
        self.loading_started.emit()
        self.status_message.emit(f"Fetching file list for {current_dir}...")
        QApplication.processEvents()

        try:
            items = self.sftp_listdir_attr(current_dir)

            self.beginResetModel()
            # Format: (name, size, mode, modified_time, attr_item)
            new_file_list = [("..", 0, stat.S_IFDIR | 0o755, "----", None)]

            for item in items:
                try:
                    name = _safe_decode(item.filename)
                    size = item.st_size
                    mode = item.st_mode
                    modified_time = QDateTime.fromSecsSinceEpoch(item.st_mtime).toString(Qt.ISODate)
                    new_file_list.append((name, size, mode, modified_time, item))
                    
                    if len(new_file_list) % 50 == 0:
                        QApplication.processEvents()
                except (Exception):
                    continue

            self.file_list = new_file_list
            self.cache[current_dir] = self.file_list
            self.cache_time[current_dir] = time.time()
            self.endResetModel()
            
            self.status_message.emit(f"Loaded {len(new_file_list)-1} items from {current_dir}")
        finally:
            self.loading_finished.emit()

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

