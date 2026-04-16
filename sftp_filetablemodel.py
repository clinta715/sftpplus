from PySide6.QtCore import QAbstractTableModel, QModelIndex, Signal, QThreadPool, QObject
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import QApplication
from sftp_qt_compat import Qt
from pathlib import Path
import os
import datetime

from sftp_creds import get_credentials, set_credentials
from sftp_transfer_handler import FileListWorker


class FileTableModel(QAbstractTableModel):
    loading_started = Signal()
    loading_finished = Signal()
    status_message = Signal(str)

    def __init__(self, session_id, parent=None):
        super().__init__(parent)
        self.file_list = []
        self.session_id = session_id
        self._fetch_generation = 0
        self._active_workers = set()

        creds = get_credentials(self.session_id)
        current_dir = creds.get('current_local_directory')

        if not current_dir or not os.path.exists(current_dir):
            current_dir = os.getcwd()

        set_credentials(self.session_id, 'current_local_directory', current_dir)
        self.directory = Path(current_dir)

        self.column_names = ['Name', 'Size', 'Permissions', 'Modified']

    def is_remote_browser(self):
        return False

    def get_files(self):
        creds = get_credentials(self.session_id)
        self.directory = Path(creds.get('current_local_directory'))

        self._fetch_generation += 1
        generation = self._fetch_generation

        self.loading_started.emit()
        self.status_message.emit(f"Loading {self.directory}...")

        worker = FileListWorker(self.session_id, str(self.directory), is_remote=False)
        self._active_workers.add(worker)

        def on_finished(path, items, _gen=generation, _worker=worker):
            self._active_workers.discard(_worker)
            if _gen == self._fetch_generation:
                self._on_files_ready(path, items)

        def on_error(path, error_msg, _gen=generation, _worker=worker):
            self._active_workers.discard(_worker)
            if _gen == self._fetch_generation:
                self._on_files_error(path, error_msg)

        worker.signals.finished.connect(on_finished)
        worker.signals.error.connect(on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_files_ready(self, path, items):
        try:
            self.beginResetModel()
            new_file_list = [("..", 0, "----", "----", True, False)]

            for item in items:
                try:
                    if isinstance(item, dict):
                        name = item.get('filename', '')
                        size = item.get('st_size', 0)
                        st_mode = item.get('st_mode', 0)
                        mtime = item.get('st_mtime', 0)
                    else:
                        name = item.filename
                        size = item.st_size
                        st_mode = item.st_mode
                        mtime = item.st_mtime
                    permissions = oct(st_mode)[-4:]
                    modified_time = datetime.datetime.fromtimestamp(
                        int(mtime)).strftime('%Y-%m-%d %H:%M:%S')
                    import stat as stat_mod
                    is_dir = stat_mod.S_ISDIR(st_mode)
                    is_link = stat_mod.S_ISLNK(st_mode)
                    new_file_list.append(
                        (name, size, permissions, modified_time, is_dir, is_link))
                except (OSError, PermissionError):
                    continue

            self.file_list = new_file_list
            self.endResetModel()
            self.status_message.emit(
                f"Loaded {len(new_file_list) - 1} items from {path}")
        except Exception:
            pass
        finally:
            self.loading_finished.emit()

    def _on_files_error(self, path, error_msg):
        self.status_message.emit(f"Error loading {path}: {error_msg}")
        self.loading_finished.emit()

    def rowCount(self, parent=QModelIndex()):
        return len(self.file_list)

    def columnCount(self, parent=QModelIndex()):
        return len(self.column_names)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.file_list)):
            return None

        file_info = self.file_list[index.row()]
        column = index.column()

        if role == Qt.DisplayRole:
            if column == 0:
                return file_info[0]
            elif column == 1:
                return str(file_info[1])
            elif column == 2:
                return file_info[2]
            elif column == 3:
                return file_info[3]
        elif role == Qt.ForegroundRole:
            name = file_info[0]
            if name == "..":
                return QColor(Qt.Color_blue)
            is_dir = file_info[4] if len(file_info) > 4 else False
            is_link = file_info[5] if len(file_info) > 5 else False
            if is_link:
                return QColor(0, 180, 180)
            elif is_dir:
                return QColor(Qt.Color_blue)
            else:
                return QColor(Qt.Color_darkGray)
        elif role == Qt.FontRole:
            name = file_info[0]
            if name == "..":
                font = QFont()
                font.setBold(True)
                return font
            is_dir = file_info[4] if len(file_info) > 4 else False
            if is_dir:
                font = QFont()
                font.setBold(True)
                return font
        elif role == Qt.TextAlignmentRole:
            if column == 1:
                return Qt.AlignRight
            return Qt.AlignLeft
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            if section < len(self.column_names):
                return self.column_names[section]
        return None

    def sort(self, column, order):
        self.layoutAboutToBeChanged.emit()

        if column == 0:
            try:
                self.file_list.sort(key=lambda x: x[0], reverse=(order == Qt.DescendingOrder))
            except (OSError, IOError, RuntimeError):
                pass
        elif column == 1:
            try:
                self.file_list.sort(key=lambda x: int(x[1]), reverse=(order == Qt.DescendingOrder))
            except (OSError, IOError, RuntimeError):
                pass
        elif column == 2:
            try:
                self.file_list.sort(key=lambda x: x[2], reverse=(order == Qt.DescendingOrder))
            except (OSError, IOError, RuntimeError):
                pass
        elif column == 3:
            try:
                self.file_list.sort(key=lambda x: x[3], reverse=(order == Qt.DescendingOrder))
            except (OSError, IOError, RuntimeError):
                pass

        self.layoutChanged.emit()
