from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QTabWidget, QWidget, QAbstractItemView
)
from PySide6.QtGui import QColor
from sftp_qt_compat import Qt
from sftp_theme import BUTTON_STYLE_DARK
from sftp_preferences import DEFAULT_PREFERENCES

_DARK_GRAY = QColor(169, 169, 169)


class _MenuListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setAlternatingRowColors(True)
        self.itemDoubleClicked.connect(self._toggle_item_visibility)
        self.setStyleSheet("""
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

    def _toggle_item_visibility(self, item):
        config = item.data(Qt.UserRole)
        if config:
            config['visible'] = not config.get('visible', True)
            self._refresh_item(item)

    def _refresh_item(self, item):
        config = item.data(Qt.UserRole)
        if not config:
            return
        visible = config.get('visible', True)
        text = config.get('text', '')
        check = "\u2713" if visible else "\u25cb"
        item.setText(f"{check}  {text}")
        if not visible:
            item.setForeground(_DARK_GRAY)

    def populate(self, items):
        self.clear()
        for item_config in items:
            visible = item_config.get('visible', True)
            text = item_config.get('text', '')
            check = "\u2713" if visible else "\u25cb"
            list_item = QListWidgetItem(f"{check}  {text}")
            list_item.setData(Qt.UserRole, item_config)
            if not visible:
                list_item.setForeground(_DARK_GRAY)
            self.addItem(list_item)

    def get_config(self):
        result = []
        for i in range(self.count()):
            item = self.item(i)
            config = item.data(Qt.UserRole)
            text = item.text()
            config['visible'] = text.startswith("\u2713")
            result.append(config)
        return result


class ContextMenuCustomizerDialog(QDialog):
    def __init__(self, configs, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Customize Context Menus")
        self.setMinimumWidth(500)
        self.setMinimumHeight(450)
        self._configs = {key: [item.copy() for item in items] for key, items in configs.items()}
        self._result = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        self.setStyleSheet("background-color: #2a2a2a;")

        title = QLabel("Customize Context Menus")
        title.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        hint = QLabel("Drag to reorder \u2022 Double-click to show/hide \u2022 \u2713 = visible, \u25cb = hidden")
        hint.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(hint)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #555555; background-color: #2a2a2a; }
            QTabBar::tab { background-color: #333333; color: #dddddd; padding: 8px 16px; margin-right: 2px; }
            QTabBar::tab:selected { background-color: #4a6fa5; color: #ffffff; }
        """)

        self._lists = {}
        tab_labels = {
            'file_table': 'File Table',
            'remote_tree': 'Remote Tree',
            'local_tree': 'Local Tree',
            'transfer_queue': 'Transfers',
            'tab_bar': 'Tab Bar',
        }

        for key, label in tab_labels.items():
            if key not in self._configs:
                continue
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(5, 5, 5, 5)
            list_widget = _MenuListWidget()
            list_widget.populate(self._configs[key])
            tab_layout.addWidget(list_widget)
            self.tabs.addTab(tab, label)
            self._lists[key] = list_widget

        layout.addWidget(self.tabs)

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

    def _reset_to_default(self):
        defaults = DEFAULT_PREFERENCES.get('context_menu_items', {})
        for key, list_widget in self._lists.items():
            if key in defaults:
                self._configs[key] = [item.copy() for item in defaults[key]]
                list_widget.populate(self._configs[key])

    def _accept(self):
        self._result = {}
        for key, list_widget in self._lists.items():
            self._result[key] = list_widget.get_config()
        self.accept()

    def get_config(self):
        return self._result


def customize_context_menus(parent, configs):
    dialog = ContextMenuCustomizerDialog(configs, parent)
    if dialog.exec():
        return dialog.get_config()
    return None


def get_visible_ids(items):
    return [item['id'] for item in items if item.get('visible', True)]


def is_visible(items, action_id):
    for item in items:
        if item['id'] == action_id:
            return item.get('visible', True)
    return True
