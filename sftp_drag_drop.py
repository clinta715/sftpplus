"""
SFTP Drag and Drop Support

Provides drag and drop functionality for file transfers between
local and remote file browsers.
"""
import os
import time
import logging

from PySide6.QtCore import Qt, QMimeData, QByteArray, QUrl
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QTableView, QAbstractItemView

from sftp_qt_compat import _remote_join

logger = logging.getLogger('sftp.dragdrop')

SFTP_MIME_TYPE = 'application/x-sftp-files'

_DROP_HIGHLIGHT_STYLE = """
    QTableView {
        background-color: rgba(76, 175, 80, 40);
        border: 2px dashed #4CAF50;
        border-radius: 4px;
    }
"""


class DragDropInfo:

    def __init__(self, source_paths, source_type, session_id=None,
                 hostname=None, username=None):
        self.source_paths = source_paths
        self.source_type = source_type
        self.session_id = session_id
        self.hostname = hostname
        self.username = username

    def is_remote(self):
        return self.source_type == 'remote'

    def is_local(self):
        return self.source_type == 'local'

    def to_mime_data(self):
        mime_data = QMimeData()
        paths_text = '\n'.join(self.source_paths)
        mime_data.setText(paths_text)
        metadata = f"{self.source_type}|{self.session_id or ''}|{self.hostname or ''}|{self.username or ''}"
        mime_data.setData(SFTP_MIME_TYPE, QByteArray(metadata.encode()))
        urls = [QUrl.fromLocalFile(p) if self.is_local() else QUrl(p) for p in self.source_paths]
        mime_data.setUrls(urls)
        return mime_data

    @staticmethod
    def from_mime_data(mime_data):
        if not mime_data:
            return None

        if mime_data.hasFormat(SFTP_MIME_TYPE):
            data = bytes(mime_data.data(SFTP_MIME_TYPE)).decode()
            parts = data.split('|')
            if len(parts) >= 4:
                source_type = parts[0]
                session_id = parts[1] if parts[1] else None
                hostname = parts[2] if parts[2] else None
                username = parts[3] if parts[3] else None
                paths_text = mime_data.text()
                source_paths = [p for p in paths_text.split('\n') if p]
                return DragDropInfo(
                    source_paths=source_paths,
                    source_type=source_type,
                    session_id=session_id,
                    hostname=hostname,
                    username=username
                )

        if mime_data.hasUrls():
            urls = mime_data.urls()
            source_paths = []
            for url in urls:
                if url.isLocalFile():
                    source_paths.append(url.toLocalFile())
            if source_paths:
                return DragDropInfo(
                    source_paths=source_paths,
                    source_type='local'
                )

        if mime_data.hasText():
            paths_text = mime_data.text()
            source_paths = [p for p in paths_text.split('\n') if p]
            return DragDropInfo(
                source_paths=source_paths,
                source_type='local'
            )

        return None


def start_drag(table_view, source_type, session_id=None, hostname=None, username=None):
    # Get paths from model
    source_paths = []
    model = table_view.model()
    current_dir = _get_current_directory(table_view, source_type)
    
    for row in selected_rows:
        # Get filename from first column
        index = model.index(row, 0)
        filename = model.data(index, Qt.ItemDataRole.DisplayRole)
        
        # Remove prefix (📁, 📄, etc.)
        filename = _strip_prefix(filename)
        
        # Build full path
        full_path = current_dir.rstrip('/') + '/' + filename if current_dir else filename
        source_paths.append(full_path)
    
    if not source_paths:
        return None
    
    # Create drag info
    drag_info = DragDropInfo(
        source_paths=source_paths,
        source_type=source_type,
        session_id=session_id,
        hostname=hostname,
        username=username
    )
    
    # Create drag object
    drag = QDrag(table_view)
    drag.setMimeData(drag_info.to_mime_data())
    
    logger.debug(f"Started drag with {len(source_paths)} files ({source_type})")
    
    return drag


def can_accept_drop(mime_data, dest_type):
    if not mime_data:
        return False
    drag_info = DragDropInfo.from_mime_data(mime_data)
    if not drag_info:
        return False
    if drag_info.is_local() and dest_type == 'remote':
        return True
    if drag_info.is_remote() and dest_type == 'local':
        return True
    return False


class BrowserTableView(QTableView):

    def __init__(self, browser, parent=None):
        super().__init__(parent)
        self._browser = browser
        self._original_style = None

    def startDrag(self, supportedActions):
        browser = self._browser
        creds = None
        try:
            from sftp_creds import get_credentials
            creds = get_credentials(browser.session_id)
        except Exception:
            return

        if creds is None:
            return

        is_remote = browser.is_remote_browser()
        source_type = 'remote' if is_remote else 'local'

        if is_remote:
            current_dir = creds.get('current_remote_directory', '.')
        else:
            current_dir = creds.get('current_local_directory', os.path.expanduser('~'))

        source_paths = []
        processed_rows = set()
        for index in self.selectedIndexes():
            row = index.row()
            if row in processed_rows:
                continue
            processed_rows.add(row)
            name_index = index.sibling(row, 0)
            filename = self.model().data(name_index, Qt.ItemDataRole.DisplayRole)
            if not filename or filename == "..":
                continue
            if is_remote:
                full_path = _remote_join(current_dir, filename)
            else:
                full_path = os.path.join(current_dir, filename)
            source_paths.append(full_path)

        if not source_paths:
            return

        session_id = getattr(browser, 'session_id', None)
        hostname = creds.get('hostname') if creds else None
        username = creds.get('username') if creds else None

        drag_info = DragDropInfo(
            source_paths=source_paths,
            source_type=source_type,
            session_id=session_id,
            hostname=hostname,
            username=username
        )

        drag = QDrag(self)
        drag.setMimeData(drag_info.to_mime_data())
        drag.exec(Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event):
        dest_type = 'remote' if self._browser.is_remote_browser() else 'local'
        if can_accept_drop(event.mimeData(), dest_type):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            if self._original_style is None:
                self._original_style = self.styleSheet()
            self.setStyleSheet(self._original_style + _DROP_HIGHLIGHT_STYLE)
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        dest_type = 'remote' if self._browser.is_remote_browser() else 'local'
        if can_accept_drop(event.mimeData(), dest_type):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        if self._original_style is not None:
            self.setStyleSheet(self._original_style)
            self._original_style = None

    def dropEvent(self, event):
        if self._original_style is not None:
            self.setStyleSheet(self._original_style)
            self._original_style = None

        drag_info = DragDropInfo.from_mime_data(event.mimeData())
        if not drag_info:
            event.ignore()
            return

        dest_type = 'remote' if self._browser.is_remote_browser() else 'local'
        if not can_accept_drop(event.mimeData(), dest_type):
            event.ignore()
            return

        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

        self._browser.handle_drop(drag_info)
