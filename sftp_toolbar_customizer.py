from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QCheckBox, QWidget, QFrame, QAbstractItemView
)
from sftp_qt_compat import Qt
from sftp_theme import BUTTON_STYLE_DARK
from sftp_preferences import get_preferences


class ToolbarCustomizerDialog(QDialog):
    def __init__(self, current_config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Customize Toolbar")
        self.setMinimumWidth(450)
        self.setMinimumHeight(400)
        self._config = [btn.copy() for btn in current_config]
        self._result = None
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)
        
        self.setStyleSheet("background-color: #2a2a2a;")
        
        title = QLabel("Customize Toolbar Buttons")
        title.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: bold;")
        layout.addWidget(title)
        
        hint = QLabel("Drag to reorder • Double-click to show/hide • ✓ = visible, ○ = hidden")
        hint.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(hint)
        
        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.itemDoubleClicked.connect(self._toggle_item_visibility)
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: #1e1e1e;
                alternate-background-color: #252525;
                color: #ffffff;
                border: 1px solid #555555;
                font-size: 13px;
                padding: 4px;
            }
            QListWidget::item {
                padding: 10px 8px;
                border: none;
                min-height: 20px;
            }
            QListWidget::item:selected {
                background-color: #4a6fa5;
                color: #ffffff;
            }
            QListWidget::item:hover {
                background-color: #3a3a3a;
            }
        """)
        self._populate_list()
        layout.addWidget(self.list_widget)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        reset_btn = QPushButton("Reset to Default")
        reset_btn.setStyleSheet(BUTTON_STYLE_DARK)
        reset_btn.clicked.connect(self._reset_to_default)
        btn_layout.addWidget(reset_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(BUTTON_STYLE_DARK)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        ok_btn = QPushButton("OK")
        ok_btn.setStyleSheet(BUTTON_STYLE_DARK)
        ok_btn.clicked.connect(self._accept)
        btn_layout.addWidget(ok_btn)
        
        layout.addLayout(btn_layout)
        self.setLayout(layout)
    
    def _toggle_item_visibility(self, item):
        btn_config = item.data(Qt.UserRole)
        if btn_config:
            btn_config['visible'] = not btn_config.get('visible', True)
            self._refresh_item(item)
    
    def _refresh_item(self, item):
        btn_config = item.data(Qt.UserRole)
        if not btn_config:
            return
        visible = btn_config.get('visible', True)
        text = btn_config.get('text', 'Button')
        tooltip = btn_config.get('tooltip', '')
        check = "✓" if visible else "○"
        display_text = f"{check}  {text}    —    {tooltip}"
        item.setText(display_text)
        if not visible:
            item.setForeground(Qt.Color_darkGray)
    
    def _populate_list(self):
        self.list_widget.clear()
        for btn in self._config:
            visible = btn.get('visible', True)
            text = btn.get('text', 'Button')
            tooltip = btn.get('tooltip', '')
            check = "✓" if visible else "○"
            display_text = f"{check}  {text}    —    {tooltip}"
            
            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, btn)
            if not visible:
                item.setForeground(Qt.Color_darkGray)
            self.list_widget.addItem(item)
    
    def _update_visibility(self, btn_config, state):
        btn_config['visible'] = state == Qt.Checked
    
    def _reset_to_default(self):
        from sftp_preferences import DEFAULT_PREFERENCES
        self._config = [btn.copy() for btn in DEFAULT_PREFERENCES.get('toolbar_buttons', [])]
        self._populate_list()
    
    def _accept(self):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            text = item.text()
            visible = text.startswith("✓")
            btn_config = item.data(Qt.UserRole)
            btn_config['visible'] = visible
        
        self._result = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            btn_config = item.data(Qt.UserRole)
            self._result.append(btn_config)
        self.accept()
    
    def get_config(self):
        return self._result


def customize_toolbar(parent, current_config):
    dialog = ToolbarCustomizerDialog(current_config, parent)
    if dialog.exec():
        return dialog.get_config()
    return None
