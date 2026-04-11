"""
About Dialog for SFTP Client

Displays application credits and acknowledgments.
"""

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from sftp_theme import DARK_THEME, BUTTON_STYLE_DARK


def show_about(parent=None):
    """Show the About dialog"""
    dialog = QDialog(parent)
    dialog.setWindowTitle("About SFTP Client")
    dialog.setFixedSize(420, 480)
    dialog.setStyleSheet(f"""
        QDialog {{
            background-color: {DARK_THEME['bg_primary']};
            color: {DARK_THEME['text_primary']};
        }}
        QLabel {{
            color: {DARK_THEME['text_primary']};
        }}
    """)
    
    layout = QVBoxLayout()
    layout.setSpacing(8)
    layout.setContentsMargins(20, 15, 20, 15)
    
    # Title
    title = QLabel("SFTP Client")
    title_font = QFont('Menlo', 18)
    title_font.setBold(True)
    title.setFont(title_font)
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    title.setStyleSheet(f"color: {DARK_THEME['accent_green']};")
    layout.addWidget(title)
    
    # Version
    version = QLabel("Version 2.5.0")
    version.setAlignment(Qt.AlignmentFlag.AlignCenter)
    version.setStyleSheet(f"color: {DARK_THEME['text_secondary']}; font-size: 12px;")
    layout.addWidget(version)
    
    # Spacer
    layout.addWidget(QLabel())
    
    # Author
    author_label = QLabel("Created by")
    author_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    author_label.setStyleSheet(f"color: {DARK_THEME['text_secondary']}; font-size: 11px;")
    layout.addWidget(author_label)
    
    author_name = QLabel("Clint Anderson")
    author_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
    author_name_font = QFont('Menlo', 14)
    author_name_font.setBold(True)
    author_name.setFont(author_name_font)
    layout.addWidget(author_name)
    
    # Started text
    started = QLabel("Started ~3 years ago with ChatGPT 3.5")
    started.setAlignment(Qt.AlignmentFlag.AlignCenter)
    started.setStyleSheet(f"color: {DARK_THEME['text_secondary']}; font-size: 11px; margin-top: 4px;")
    layout.addWidget(started)
    
    # Spacer
    layout.addWidget(QLabel())
    
    # LLM credits
    llm_header = QLabel("AI Assistants Used")
    llm_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
    llm_header.setStyleSheet(f"color: {DARK_THEME['accent_blue']}; font-size: 12px; font-weight: bold;")
    layout.addWidget(llm_header)
    
    llm_label = QLabel(
        "ChatGPT • Claude • Gemini • DeepMind • "
        "Kimi • MiniMax • GLM • Grok • Qwen"
    )
    llm_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    llm_label.setStyleSheet(f"""
        color: {DARK_THEME['text_secondary']};
        font-size: 10px;
        padding: 6px;
        background-color: {DARK_THEME['bg_secondary']};
        border-radius: 4px;
    """)
    llm_label.setWordWrap(True)
    layout.addWidget(llm_label)
    
    # Spacer
    layout.addWidget(QLabel())
    
    # Acknowledgment
    ack = QLabel(
        "This project was developed as a collaboration "
        "between human creativity and AI assistance."
    )
    ack.setAlignment(Qt.AlignmentFlag.AlignCenter)
    ack.setWordWrap(True)
    ack.setStyleSheet(f"color: {DARK_THEME['text_secondary']}; font-size: 10px; font-style: italic;")
    layout.addWidget(ack)
    
    # Spacer
    layout.addWidget(QLabel())
    
    # Close button
    button_layout = QHBoxLayout()
    button_layout.addStretch()
    
    close_btn = QPushButton("Close")
    close_btn.setStyleSheet(BUTTON_STYLE_DARK)
    close_btn.setFixedSize(80, 30)
    close_btn.clicked.connect(dialog.accept)
    button_layout.addWidget(close_btn)
    
    button_layout.addStretch()
    layout.addLayout(button_layout)
    
    dialog.setLayout(layout)
    dialog.exec()