"""
SFTP Client Package

A PySide6-based SFTP client application with:
- Multi-tabbed interface for multiple SFTP connections
- SSH Terminal support alongside SFTP file transfers
- File preview panel for text and image files
- Customizable toolbar with drag-and-drop reordering
- Per-host directory bookmarks
- Persistent transfer queue between sessions
- Enhanced security with separate key storage
"""

__version__ = "1.0.0"
__author__ = "Developer"

from .sftp import MainWindow
from .sftp_connections_widget import ConnectionsWidget
from .sftp_transfer_queue_widget import TransferQueueWidget
from .sftp_operations import SFTPOperations
from .sftp_preferences import get_preferences

__all__ = [
    'MainWindow',
    'ConnectionsWidget', 
    'TransferQueueWidget',
    'SFTPOperations',
    'get_preferences',
]
