DARK_THEME = {
    "bg_primary": "#333333",
    "bg_secondary": "#444444",
    "bg_hover": "#555555",
    "bg_pressed": "#333333",
    "border": "#555555",
    "text_primary": "#dddddd",
    "text_secondary": "#888888",
    "accent_green": "#4CAF50",
    "accent_green_hover": "#45a049",
    "accent_blue": "#4a6fa5",
    "error": "#f44336",
    "success": "#4CAF50",
    "warning": "#ff9800",
}

LIGHT_THEME = {
    "bg_primary": "#ffffff",
    "bg_secondary": "#f8f8f8",
    "bg_hover": "#e8e8e8",
    "bg_pressed": "#d0d0d0",
    "border": "#cccccc",
    "text_primary": "#333333",
    "text_secondary": "#666666",
    "accent_green": "#4CAF50",
    "accent_green_hover": "#45a049",
    "accent_blue": "#2196F3",
    "error": "#f44336",
    "success": "#4CAF50",
    "warning": "#ff9800",
}

BUTTON_STYLE_DARK = """
    QPushButton {{
        padding: 4px 8px;
        border: 1px solid {border};
        border-radius: 3px;
        background-color: {bg_secondary};
        color: {text_primary};
        font-size: 11px;
    }}
    QPushButton:hover {{
        background-color: {bg_hover};
    }}
    QPushButton:pressed {{
        background-color: {bg_pressed};
    }}
    QPushButton:disabled {{
        background-color: {bg_secondary};
        color: {text_secondary};
    }}
""".format(**DARK_THEME)

BUTTON_STYLE_LIGHT = """
    QPushButton {{
        padding: 5px 10px;
        border: 1px solid {border};
        border-radius: 3px;
        background-color: {bg_secondary};
        color: {text_primary};
    }}
    QPushButton:hover {{
        background-color: {bg_hover};
    }}
    QPushButton:pressed {{
        background-color: {bg_pressed};
    }}
    QPushButton:disabled {{
        background-color: {bg_secondary};
        color: {text_secondary};
    }}
""".format(**LIGHT_THEME)

CONNECT_BUTTON_STYLE = """
    QPushButton {{
        background-color: {accent_green};
        color: white;
        font-weight: bold;
        border-radius: 5px;
        padding: 6px 16px;
    }}
    QPushButton:hover {{
        background-color: {accent_green_hover};
    }}
    QPushButton:disabled {{
        background-color: #cccccc;
        color: #666666;
    }}
""".format(**DARK_THEME)

LIST_WIDGET_STYLE_DARK = """
    QListWidget {{
        border: 1px solid {border};
        border-radius: 4px;
        background-color: {bg_primary};
        color: {text_primary};
    }}
    QListWidget::item {{
        padding: 0px;
        border-bottom: 1px solid {border};
        color: {text_primary};
    }}
    QListWidget::item:selected {{
        background-color: {accent_blue};
        color: white;
    }}
    QListWidget::item:hover {{
        background-color: {bg_hover};
    }}
""".format(**DARK_THEME)

LIST_WIDGET_STYLE_LIGHT = """
    QListWidget {{
        border: 1px solid {border};
        border-radius: 5px;
        background-color: {bg_primary};
        color: {text_primary};
        padding: 5px;
    }}
    QListWidget::item {{
        padding: 5px;
        border-bottom: 1px solid {border};
    }}
    QListWidget::item:hover {{
        background-color: {bg_hover};
    }}
""".format(**LIGHT_THEME)

PROGRESS_BAR_STYLE_DARK = """
    QProgressBar {{
        border: 1px solid {border};
        border-radius: 4px;
        text-align: center;
        background-color: {bg_primary};
    }}
    QProgressBar::chunk {{
        background-color: {accent_green};
        border-radius: 3px;
    }}
""".format(**DARK_THEME)

PROGRESS_BAR_STYLE_LIGHT = """
    QProgressBar {{
        border: 1px solid {border};
        border-radius: 5px;
        text-align: center;
        background-color: {bg_primary};
    }}
    QProgressBar::chunk {{
        background-color: {accent_green};
        width: 10px;
    }}
""".format(**LIGHT_THEME)

TEXT_EDIT_STYLE_DARK = """
    QTextEdit {{
        border: 1px solid {border};
        border-radius: 4px;
        background-color: {bg_primary};
        color: {text_primary};
        font-size: 11px;
    }}
""".format(**DARK_THEME)

TEXT_EDIT_STYLE_LIGHT = """
    QTextEdit {{
        border: 1px solid {border};
        border-radius: 4px;
        background-color: {bg_primary};
        color: {text_primary};
    }}
""".format(**LIGHT_THEME)

LABEL_STYLE_DARK = "color: {text_primary};".format(**DARK_THEME)
LABEL_STYLE_LIGHT = "color: {text_primary};".format(**LIGHT_THEME)

CANCEL_BUTTON_STYLE = """
    QPushButton {{
        padding: 4px 8px;
        border: 1px solid #777;
        border-radius: 3px;
        background-color: #555;
        color: #ddd;
        font-size: 10px;
    }}
    QPushButton:hover {{
        background-color: #666;
    }}
"""
