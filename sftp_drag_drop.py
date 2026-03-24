"""
SFTP Drag and Drop Support

Provides drag and drop functionality for file transfers between
local and remote file browsers.
"""
import os
from PyQt6.QtCore import Qt, QMimeData, QByteArray, QUrl
from PyQt6.QtGui import QDrag
from PyQt6.QtWidgets import QTableView
import logging

logger = logging.getLogger('sftp.dragdrop')

# MIME type for SFTP drag/drop operations
SFTP_MIME_TYPE = 'application/x-sftp-files'
LOCAL_MIME_TYPE = 'application/x-local-files'


class DragDropInfo:
    """Information about files being dragged."""
    
    def __init__(self, source_paths, source_type, session_id=None, 
                 hostname=None, username=None):
        """
        Args:
            source_paths: List of file/directory paths being dragged
            source_type: 'local' or 'remote'
            session_id: Session ID for remote files
            hostname: Hostname for remote files
            username: Username for remote files
        """
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
        """Convert to QMimeData for drag operation."""
        mime_data = QMimeData()
        
        # Store paths as text (one per line)
        paths_text = '\n'.join(self.source_paths)
        mime_data.setText(paths_text)
        
        # Store metadata as custom MIME type
        metadata = f"{self.source_type}|{self.session_id or ''}|{self.hostname or ''}|{self.username or ''}"
        mime_data.setData(SFTP_MIME_TYPE, QByteArray(metadata.encode()))
        
        # Also set URLs for compatibility with file managers
        urls = [QUrl.fromLocalFile(p) if self.is_local() else QUrl(p) for p in self.source_paths]
        mime_data.setUrls(urls)
        
        return mime_data
    
    @staticmethod
    def from_mime_data(mime_data):
        """Extract DragDropInfo from QMimeData."""
        if not mime_data:
            return None
        
        # Try custom MIME type first
        if mime_data.hasFormat(SFTP_MIME_TYPE):
            data = bytes(mime_data.data(SFTP_MIME_TYPE)).decode()
            parts = data.split('|')
            if len(parts) >= 4:
                source_type = parts[0]
                session_id = parts[1] if parts[1] else None
                hostname = parts[2] if parts[2] else None
                username = parts[3] if parts[3] else None
                
                # Get paths from text
                paths_text = mime_data.text()
                source_paths = [p for p in paths_text.split('\n') if p]
                
                return DragDropInfo(
                    source_paths=source_paths,
                    source_type=source_type,
                    session_id=session_id,
                    hostname=hostname,
                    username=username
                )
        
        # Try URLs (from local file manager)
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
        
        # Try text
        if mime_data.hasText():
            paths_text = mime_data.text()
            source_paths = [p for p in paths_text.split('\n') if p]
            # Assume local for text
            return DragDropInfo(
                source_paths=source_paths,
                source_type='local'
            )
        
        return None


def start_drag(table_view, source_type, session_id=None, hostname=None, username=None):
    """
    Start a drag operation from a table view.
    
    Args:
        table_view: QTableView to get selected paths from
        source_type: 'local' or 'remote'
        session_id: Session ID for remote files
        hostname: Hostname for remote files
        username: Username for remote files
    
    Returns:
        QDrag object or None if no selection
    """
    selected_rows = _get_selected_rows(table_view)
    if not selected_rows:
        return None
    
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
        full_path = os.path.join(current_dir, filename) if current_dir else filename
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
    """
    Check if drop is acceptable.
    
    Args:
        mime_data: QMimeData from drop event
        dest_type: 'local' or 'remote' destination
    
    Returns:
        bool: True if drop is acceptable
    """
    if not mime_data:
        return False
    
    drag_info = DragDropInfo.from_mime_data(mime_data)
    if not drag_info:
        return False
    
    # Allow local -> remote (upload) and remote -> local (download)
    # Also allow remote -> remote for server-side operations
    if drag_info.is_local() and dest_type == 'remote':
        return True  # Upload
    if drag_info.is_remote() and dest_type == 'local':
        return True  # Download
    if drag_info.is_remote() and dest_type == 'remote':
        return True  # Server-to-server (same host only for now)
    
    return False


def _get_selected_rows(table_view):
    """Get unique selected row indices."""
    selected = table_view.selectedIndexes()
    rows = set()
    for index in selected:
        rows.add(index.row())
    return sorted(rows)


def _get_current_directory(table_view, source_type):
    """Get current directory from table view's parent browser."""
    # Walk up the widget hierarchy to find the browser
    parent = table_view.parent()
    while parent:
        if hasattr(parent, 'session_id'):
            # Found a browser
            if source_type == 'remote':
                from sftp_creds import get_credentials
                creds = get_credentials(parent.session_id)
                return creds.get('current_remote_directory', '.')
            else:
                from sftp_creds import get_credentials
                creds = get_credentials(parent.session_id)
                return creds.get('current_local_directory', os.path.expanduser('~'))
        parent = parent.parent()
    return '.'


def _strip_prefix(filename):
    """Remove emoji/file type prefixes from filename."""
    prefixes = ['[DIR]', '[FILE]', '[LINK]', '📁', '📄', '🔗', '📂', ' ']
    for prefix in prefixes:
        if filename.startswith(prefix):
            filename = filename[len(prefix):].lstrip()
    return filename.strip()