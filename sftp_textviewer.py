from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, 
    QPushButton, QLabel, QFileDialog, QMessageBox
)
from sftp_qt_compat import Qt  # Use compatibility layer for Qt enums
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor

from sftp_theme import DARK_THEME, BUTTON_STYLE_DARK

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB max for viewing


def is_text_file(file_path, sample_size=8192):
    """Check if a file appears to be text by reading a sample and checking for null bytes."""
    try:
        with open(file_path, 'rb') as f:
            chunk = f.read(sample_size)
        if b'\x00' in chunk:
            return False
        try:
            chunk.decode('utf-8')
            return True
        except UnicodeDecodeError:
            try:
                chunk.decode('latin-1')
                return True
            except (UnicodeDecodeError, LookupError, ValueError):
                return False
    except (OSError, IOError) as e:
        pass
        return False


class TextViewerWindow(QWidget):
    """A simple text viewer window for viewing/editing text files."""
    
    file_saved = pyqtSignal(str)
    
    def __init__(self, file_path=None, content=None, remote_path=None, session_api=None, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.remote_path = remote_path
        self.session_api = session_api
        self.is_modified = False
        self.original_content = content or ""
        
        self.init_ui()
        
        if content:
            self.text_edit.setPlainText(content)
        elif file_path:
            self.load_file(file_path)
    
    def init_ui(self):
        self.setWindowTitle("Text Viewer")
        self.resize(800, 600)
        
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)
        
        # Header with file info
        header_layout = QHBoxLayout()
        
        self.file_label = QLabel(self.file_path or self.remote_path or "Untitled")
        self.file_label.setStyleSheet(f"font-weight: bold; color: {DARK_THEME['text_primary']};")
        header_layout.addWidget(self.file_label)
        
        self.modified_label = QLabel("")
        self.modified_label.setStyleSheet(f"color: {DARK_THEME['warning']};")
        header_layout.addWidget(self.modified_label)
        
        header_layout.addStretch()
        
        self.size_label = QLabel("")
        self.size_label.setStyleSheet(f"color: {DARK_THEME['text_secondary']}; font-size: 10px;")
        header_layout.addWidget(self.size_label)
        
        layout.addLayout(header_layout)
        
        # Text editor
        self.text_edit = QTextEdit()
        self.text_edit.setFont(QFont("Courier New", 10))
        self.text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_THEME['bg_secondary']};
                color: {DARK_THEME['text_primary']};
                border: 1px solid {DARK_THEME['border']};
                border-radius: 4px;
                padding: 4px;
            }}
        """)
        self.text_edit.textChanged.connect(self.on_text_changed)
        layout.addWidget(self.text_edit)
        
        # Button row
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.save_btn = QPushButton("💾 Save")
        self.save_btn.setToolTip("Save changes to file")
        self.save_btn.setStyleSheet(BUTTON_STYLE_DARK)
        self.save_btn.clicked.connect(self.save_file)
        self.save_btn.setEnabled(False)
        button_layout.addWidget(self.save_btn)
        
        self.save_as_btn = QPushButton("Save As...")
        self.save_as_btn.setToolTip("Save to a different location")
        self.save_as_btn.setStyleSheet(BUTTON_STYLE_DARK)
        self.save_as_btn.clicked.connect(self.save_file_as)
        button_layout.addWidget(self.save_as_btn)
        
        self.close_btn = QPushButton("Close")
        self.close_btn.setToolTip("Close viewer")
        self.close_btn.setStyleSheet(BUTTON_STYLE_DARK)
        self.close_btn.clicked.connect(self.close)
        button_layout.addWidget(self.close_btn)
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def load_file(self, file_path):
        """Load a file into the viewer."""
        try:
            file_size = os.path.getsize(file_path)
            
            if file_size > MAX_FILE_SIZE:
                QMessageBox.warning(
                    self, "Large File",
                    f"File is large ({file_size / (1024*1024):.1f} MB). Loading may be slow."
                )
            
            if not is_text_file(file_path):
                result = QMessageBox.question(
                    self, "Binary File",
                    "This file appears to be binary. View anyway?",
                    Qt.MsgBtn_Yes | Qt.MsgBtn_No,
                    Qt.MsgBtn_No
                )
                if result == Qt.MsgBtn_No:
                    self.close()
                    return
            
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            
            self.text_edit.setPlainText(content)
            self.original_content = content
            self.file_path = file_path
            self.file_label.setText(file_path)
            self.size_label.setText(f"{file_size:,} bytes")
            self.is_modified = False
            self.update_modified_indicator()
            
        except (OSError, IOError) as e:
            QMessageBox.critical(self, "Error", f"Could not load file: {e}")
            self.close()
    
    def on_text_changed(self):
        """Handle text changes."""
        current = self.text_edit.toPlainText()
        self.is_modified = (current != self.original_content)
        self.update_modified_indicator()
        self.save_btn.setEnabled(self.is_modified)
    
    def update_modified_indicator(self):
        """Update the modified indicator."""
        if self.is_modified:
            self.modified_label.setText("● Modified")
        else:
            self.modified_label.setText("")
    
    def save_file(self):
        """Save changes to the file."""
        if self.file_path:
            try:
                with open(self.file_path, 'w', encoding='utf-8') as f:
                    f.write(self.text_edit.toPlainText())
                
                self.original_content = self.text_edit.toPlainText()
                self.is_modified = False
                self.update_modified_indicator()
                self.save_btn.setEnabled(False)
                
                # Update remote file if this was a remote file
                if self.remote_path and self.session_api:
                    try:
                        self.session_api.upload(self.file_path, self.remote_path)
                        QMessageBox.information(self, "Saved", f"File saved to {self.remote_path}")
                    except (OSError, IOError) as e:
                        QMessageBox.warning(self, "Warning", f"Saved locally but failed to upload: {e}")
                else:
                    QMessageBox.information(self, "Saved", f"File saved to {self.file_path}")
                
                self.file_saved.emit(self.file_path)
                
            except (OSError, IOError) as e:
                QMessageBox.critical(self, "Error", f"Could not save file: {e}")
        else:
            self.save_file_as()
    
    def save_file_as(self):
        """Save file to a new location."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save File As", self.file_path or "", 
            "All Files (*);;Text Files (*.txt)"
        )
        
        if file_path:
            self.file_path = file_path
            self.save_file()
    
    def closeEvent(self, event):
        """Handle close event - prompt to save if modified."""
        if self.is_modified:
            result = QMessageBox.question(
                self, "Save Changes?",
                "The file has been modified. Save changes?",
                Qt.MsgBtn_Yes | Qt.MsgBtn_No | Qt.MsgBtn_Cancel,
                Qt.MsgBtn_Yes
            )
            
            if result == Qt.MsgBtn_Yes:
                self.save_file()
                event.accept()
            elif result == Qt.MsgBtn_No:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


import os
