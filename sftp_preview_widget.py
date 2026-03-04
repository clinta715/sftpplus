from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextBrowser,
    QToolButton, QScrollArea, QSizePolicy
)
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QPixmap
from sftp_qt_compat import Qt
from icecream import ic
import os
import tempfile
import atexit
import stat

_temp_files_registry = []
_registry_lock = None

def _get_registry_lock():
    global _registry_lock
    if _registry_lock is None:
        import threading
        _registry_lock = threading.Lock()
    return _registry_lock

def _cleanup_all_temp_files():
    global _temp_files_registry
    lock = _get_registry_lock()
    if lock:
        with lock:
            for temp_path in _temp_files_registry[:]:
                try:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
                except OSError:
                    pass
            _temp_files_registry.clear()

atexit.register(_cleanup_all_temp_files)

def _register_temp_file(temp_path):
    lock = _get_registry_lock()
    if lock:
        with lock:
            _temp_files_registry.append(temp_path)

def _unregister_temp_file(temp_path):
    lock = _get_registry_lock()
    if lock:
        with lock:
            if temp_path in _temp_files_registry:
                _temp_files_registry.remove(temp_path)

try:
    import humanize
    HAS_HUMANIZE = True
except ImportError:
    HAS_HUMANIZE = False

def format_size(size):
    if HAS_HUMANIZE:
        return humanize.naturalsize(size)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class FilePreviewWidget(QWidget):
    preview_style = """
        QWidget {
            background-color: #2a2a2a;
            color: #dddddd;
            border-left: 1px solid #555555;
        }
        QLabel {
            color: #aaaaaa;
            font-size: 11px;
        }
        QTextBrowser {
            background-color: #1a1a1a;
            color: #dddddd;
            border: 1px solid #444444;
            font-family: 'Menlo', 'Monaco', 'Consolas', monospace;
            font-size: 11px;
        }
        QToolButton {
            padding: 4px 8px;
            border: 1px solid #555555;
            border-radius: 3px;
            background-color: #444444;
            color: #dddddd;
            font-size: 11px;
        }
        QToolButton:hover {
            background-color: #555555;
        }
    """

    TEXT_EXTENSIONS = {
        '.txt', '.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.htm',
        '.css', '.scss', '.sass', '.less', '.json', '.xml', '.yaml', '.yml',
        '.md', '.rst', '.ini', '.cfg', '.conf', '.log', '.sh', '.bash',
        '.zsh', '.fish', '.c', '.cpp', '.h', '.hpp', '.java', '.kt', '.rs',
        '.go', '.rb', '.php', '.pl', '.lua', '.vim', '.sql', '.tf', '.hcl',
        '.env', '.gitignore', '.dockerignore', '.editorconfig', '.toml'
    }
    
    IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg', '.ico', '.webp'}
    MAX_TEXT_SIZE = 100 * 1024
    MAX_IMAGE_SIZE = 5 * 1024 * 1024

    def __init__(self, parent=None):
        super().__init__(parent)
        self._temp_file = None
        self._current_path = None
        self._init_ui()
        self.setMinimumWidth(250)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

    def _init_ui(self):
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(5, 5, 5, 5)
        self.layout().setSpacing(5)
        self.setStyleSheet(self.preview_style)

        header_layout = QHBoxLayout()
        self.title_label = QLabel("📄 Preview")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 12px; color: #7eb8ff;")
        header_layout.addWidget(self.title_label)
        
        header_layout.addStretch()
        
        self.close_btn = QToolButton()
        self.close_btn.setText("×")
        self.close_btn.setToolTip("Close preview (Ctrl+P)")
        self.close_btn.clicked.connect(self._on_close)
        header_layout.addWidget(self.close_btn)
        
        self.layout().addLayout(header_layout)

        self.file_info_label = QLabel("Select a file to preview")
        self.file_info_label.setWordWrap(True)
        self.layout().addWidget(self.file_info_label)

        self.content_area = QScrollArea()
        self.content_area.setWidgetResizable(True)
        self.content_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.content_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.content_area.setStyleSheet("QScrollArea { border: none; background-color: #1a1a1a; }")

        self.text_preview = QTextBrowser()
        self.text_preview.setLineWrapMode(Qt.NoWrap)
        self.text_preview.setOpenExternalLinks(False)
        self.text_preview.setVisible(False)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setScaledContents(False)
        self.image_label.setVisible(False)

        self.content_area.setWidget(self.text_preview)
        self.layout().addWidget(self.content_area, stretch=1)

        self._show_placeholder()

    def _show_placeholder(self):
        self.text_preview.setVisible(False)
        self.image_label.setVisible(False)
        self.content_area.setWidget(self.text_preview)
        self.text_preview.setPlainText("Select a file to preview")
        self.text_preview.setVisible(True)

    def _on_close(self):
        from PyQt6.QtWidgets import QWidget
        parent = self.parent()
        while parent:
            if hasattr(parent, 'toggle_preview'):
                parent.toggle_preview()
                return
            parent = parent.parent()

    def clear_preview(self):
        self._cleanup_temp_file()
        self._current_path = None
        self._show_placeholder()
        self.file_info_label.setText("Select a file to preview")
        self.title_label.setText("📄 Preview")

    def _cleanup_temp_file(self):
        if self._temp_file:
            try:
                if os.path.exists(self._temp_file):
                    os.unlink(self._temp_file)
            except OSError:
                pass
            _unregister_temp_file(self._temp_file)
            self._temp_file = None

    def preview_file(self, file_path, file_size, modified, permissions, sftp_api=None):
        if file_path == self._current_path:
            return
        
        self._current_path = file_path
        self._cleanup_temp_file()
        
        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1].lower()
        
        size_str = format_size(file_size) if file_size else "Unknown"
        info_text = f"📁 {filename}\n📏 {size_str}"
        if modified:
            info_text += f" | 🕐 {modified}"
        if permissions:
            info_text += f"\n🔒 {permissions}"
        self.file_info_label.setText(info_text)

        if file_size > self.MAX_TEXT_SIZE and ext in self.TEXT_EXTENSIONS:
            self._show_too_large(file_path, "text", self.MAX_TEXT_SIZE)
            return

        if ext in self.IMAGE_EXTENSIONS:
            if file_size > self.MAX_IMAGE_SIZE:
                self._show_too_large(file_path, "image", self.MAX_IMAGE_SIZE)
                return
            self._preview_image(file_path, sftp_api)
        elif ext in self.TEXT_EXTENSIONS or not ext:
            self._preview_text(file_path, sftp_api)
        else:
            self._show_binary_info(file_path, ext)

    def _show_too_large(self, file_path, file_type, max_size):
        filename = os.path.basename(file_path)
        max_str = format_size(max_size)
        self.title_label.setText(f"📄 {filename}")
        self.text_preview.setVisible(True)
        self.image_label.setVisible(False)
        self.content_area.setWidget(self.text_preview)
        self.text_preview.setPlainText(f"File too large to preview.\n\nMaximum {file_type} size: {max_str}")

    def _show_binary_info(self, file_path, ext):
        filename = os.path.basename(file_path)
        self.title_label.setText(f"📄 {filename}")
        self.text_preview.setVisible(True)
        self.image_label.setVisible(False)
        self.content_area.setWidget(self.text_preview)
        self.text_preview.setPlainText(
            f"Binary file preview not available.\n\n"
            f"Extension: {ext or 'none'}\n\n"
            f"Supported previews:\n"
            f"• Text files (max 100KB)\n"
            f"• Images: PNG, JPG, GIF, BMP, SVG (max 5MB)"
        )

    def _preview_text(self, file_path, sftp_api):
        if not sftp_api:
            self.text_preview.setPlainText("Preview not available - no SFTP connection")
            return
        
        filename = os.path.basename(file_path)
        self.title_label.setText(f"📄 {filename}")
        
        try:
            fd, temp_path = tempfile.mkstemp(suffix='.txt', prefix='.sftp_preview_')
            os.close(fd)
            os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
            _register_temp_file(temp_path)
            
            sftp_api.download(file_path, temp_path)
            self._cleanup_temp_file()
            self._temp_file = temp_path
            
            with open(temp_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read(self.MAX_TEXT_SIZE + 1)
            
            if len(content) > self.MAX_TEXT_SIZE:
                content = content[:self.MAX_TEXT_SIZE] + "\n\n... [truncated - file too large]"
            
            self.text_preview.setVisible(True)
            self.image_label.setVisible(False)
            self.content_area.setWidget(self.text_preview)
            self.text_preview.setPlainText(content)
            
        except Exception as e:
            ic(f"Preview error: {e}")
            self.text_preview.setPlainText(f"Error previewing file:\n{str(e)}")

    def _preview_image(self, file_path, sftp_api):
        if not sftp_api:
            self.text_preview.setPlainText("Preview not available - no SFTP connection")
            self.text_preview.setVisible(True)
            self.image_label.setVisible(False)
            self.content_area.setWidget(self.text_preview)
            return
        
        filename = os.path.basename(file_path)
        self.title_label.setText(f"🖼️ {filename}")
        
        try:
            fd, temp_path = tempfile.mkstemp(suffix=os.path.splitext(file_path)[1], prefix='.sftp_preview_')
            os.close(fd)
            os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
            _register_temp_file(temp_path)
            
            sftp_api.download(file_path, temp_path)
            self._cleanup_temp_file()
            self._temp_file = temp_path
            
            pixmap = QPixmap(temp_path)
            if pixmap.isNull():
                raise ValueError("Failed to load image")
            
            max_width = self.content_area.width() - 20
            max_height = self.content_area.height() - 20
            
            if pixmap.width() > max_width or pixmap.height() > max_height:
                pixmap = pixmap.scaled(
                    max_width, max_height,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
            
            self.image_label.setPixmap(pixmap)
            self.text_preview.setVisible(False)
            self.image_label.setVisible(True)
            self.content_area.setWidget(self.image_label)
            
        except Exception as e:
            ic(f"Image preview error: {e}")
            self.text_preview.setPlainText(f"Error previewing image:\n{str(e)}")
            self.text_preview.setVisible(True)
            self.image_label.setVisible(False)
            self.content_area.setWidget(self.text_preview)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.image_label.pixmap() and not self.image_label.pixmap().isNull():
            if self._temp_file and os.path.exists(self._temp_file):
                pixmap = QPixmap(self._temp_file)
                max_width = self.content_area.width() - 20
                max_height = self.content_area.height() - 20
                
                if pixmap.width() > max_width or pixmap.height() > max_height:
                    pixmap = pixmap.scaled(
                        max_width, max_height,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation
                    )
                self.image_label.setPixmap(pixmap)
