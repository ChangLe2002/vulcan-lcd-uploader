# SPDX-License-Identifier: MIT
"""新界面主题：深色 + 黄色强调，取自设计图。"""

from __future__ import annotations

# 取色自设计图
BG = "#08070b"
PANEL = "#0e1117"
PANEL_ALT = "#12161d"
BORDER = "#232a34"
TEXT = "#e8edf5"
MUTED = "#7c8798"
ACCENT = "#fcee0a"      # 主强调色（黄）
CYAN = "#59cfff"
MAGENTA = "#ff2d78"
OK = "#39d98a"
WARN = "#ffb020"
BAD = "#ff5a5f"

FONT_FAMILY = "Microsoft YaHei UI"

__all__ = [
    "BG", "PANEL", "PANEL_ALT", "BORDER", "TEXT", "MUTED",
    "ACCENT", "CYAN", "MAGENTA", "OK", "WARN", "BAD", "STYLE_SHEET",
]


STYLE_SHEET = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: "{FONT_FAMILY}";
    font-size: 12px;
}}
QMainWindow, QDialog {{ background: {BG}; }}

QLabel {{ background: transparent; }}
QLabel[role="muted"] {{ color: {MUTED}; font-size: 11px; }}
QLabel[role="title"] {{ color: {TEXT}; font-size: 13px; font-weight: 600; }}
QLabel[role="accent"] {{ color: {ACCENT}; font-weight: 600; }}
QLabel[role="brand"] {{ color: {TEXT}; font-size: 17px; font-weight: 700; letter-spacing: 2px; }}

QFrame[role="panel"] {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
QFrame[role="topbar"] {{
    background: {BG};
    border-bottom: 1px solid {BORDER};
}}
QFrame[role="bottombar"] {{
    background: {PANEL_ALT};
    border-top: 1px solid {BORDER};
}}

QPushButton {{
    background: {PANEL_ALT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 5px 12px;
}}
QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: #4a5361; border-color: #1a2029; }}

QPushButton[role="primary"] {{
    background: {ACCENT};
    color: #0a0a0a;
    border: 1px solid {ACCENT};
    font-weight: 700;
}}
QPushButton[role="primary"]:hover {{ background: #fff75a; border-color: #fff75a; }}
QPushButton[role="primary"]:pressed {{ background: #d8cc00; }}
QPushButton[role="primary"]:disabled {{ background: #3a3a24; color: #7a7a5a; border-color: #3a3a24; }}

QPushButton[role="ghost"] {{
    background: transparent;
    border: 1px solid {BORDER};
    color: {MUTED};
}}
QPushButton[role="ghost"]:hover {{ color: {ACCENT}; border-color: {ACCENT}; }}

QPushButton[role="nav"] {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    color: {MUTED};
    padding: 8px 16px;
}}
QPushButton[role="nav"]:hover {{ color: {TEXT}; }}
QPushButton[role="nav"]:checked {{
    color: {ACCENT};
    border-bottom: 2px solid {ACCENT};
}}

QComboBox, QSpinBox, QLineEdit {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 4px 6px;
    color: {TEXT};
    selection-background-color: {ACCENT};
    selection-color: #000;
}}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover {{ border-color: #3a4757; }}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    selection-background-color: {BORDER};
    color: {TEXT};
}}

QProgressBar {{
    background: #161b23;
    border: none;
    border-radius: 2px;
    text-align: center;
    color: {MUTED};
}}
QProgressBar::chunk {{ background: {CYAN}; border-radius: 2px; }}

QTableWidget {{
    background: {PANEL};
    border: 1px solid {BORDER};
    gridline-color: #1b222c;
    selection-background-color: #1f2732;
    selection-color: {TEXT};
}}
QHeaderView::section {{
    background: {PANEL_ALT};
    color: {MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 5px;
}}
QScrollBar:vertical {{ background: transparent; width: 8px; }}
QScrollBar::handle:vertical {{ background: #2a3340; border-radius: 4px; }}
QScrollBar::handle:vertical:hover {{ background: #3a4757; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; }}
QScrollBar::handle:horizontal {{ background: #2a3340; border-radius: 4px; }}

QSlider::groove:horizontal {{ background: #1b222c; height: 4px; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {ACCENT};
    width: 12px; margin: -5px 0; border-radius: 6px;
}}
QSlider::sub-page:horizontal {{ background: {CYAN}; border-radius: 2px; }}

QCheckBox {{ color: {TEXT}; }}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {BORDER};
    border-radius: 2px;
    background: {PANEL_ALT};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QTextEdit, QPlainTextEdit {{
    background: #0b0e13;
    border: 1px solid {BORDER};
    color: {MUTED};
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 11px;
}}

QMenuBar {{ background: {BG}; color: {MUTED}; border: none; padding-left: 8px; }}
QMenuBar::item {{ background: transparent; padding: 4px 10px; }}
QMenuBar::item:selected {{ background: {BORDER}; color: {ACCENT}; }}
QMenu {{ background: {PANEL_ALT}; border: 1px solid {BORDER}; }}
QMenu::item:selected {{ background: {BORDER}; color: {ACCENT}; }}
QToolTip {{
    background: {PANEL_ALT}; color: {TEXT};
    border: 1px solid {BORDER}; padding: 4px;
}}
"""
