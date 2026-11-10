# SPDX-License-Identifier: MIT
"""UI 通用控件：状态徽标、十六进制视图、分区容器。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QGroupBox, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from ..util.hexfmt import hexdump

__all__ = ["StatusBadge", "HexView", "Section"]


class StatusBadge(QLabel):
    """状态徽标：ok / warn / error / idle 四种配色。"""

    COLORS = {
        "ok": ("#1b5e20", "#e8f5e9"),
        "warn": ("#7a5c00", "#fff8e1"),
        "error": ("#8e1b1b", "#ffebee"),
        "idle": ("#37474f", "#eceff1"),
    }

    def __init__(self, text: str = "未连接", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumWidth(120)
        self.set_state(text, "idle")

    def set_state(self, text: str, level: str = "idle") -> None:
        fg, bg = self.COLORS.get(level, self.COLORS["idle"])
        self.setText(text)
        self.setStyleSheet(
            f"QLabel {{ color: {fg}; background: {bg}; border: 1px solid {fg}40;"
            f" border-radius: 4px; padding: 3px 8px; font-weight: 600; }}"
        )


class HexView(QPlainTextEdit):
    """只读十六进制视图，自动截断，避免大帧把界面拖死。"""

    def __init__(self, *, max_lines: int = 400, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        self._max_lines = max_lines
        self._lines = 0

    def append_hex(self, direction: str, data: bytes, note: str = "") -> None:
        header = f"[{direction}] {len(data)} B" + (f"  {note}" if note else "")
        self.appendPlainText(header)
        self.appendPlainText(hexdump(data, limit=512))
        self._trim()

    def append_text(self, text: str) -> None:
        self.appendPlainText(text)
        self._trim()

    def _trim(self) -> None:
        doc = self.document()
        while doc.blockCount() > self._max_lines:
            cursor = QTextCursor(doc.firstBlock())
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()

    def clear_all(self) -> None:
        self.clear()


class Section(QGroupBox):
    """带标题的分区容器，内部用垂直布局。"""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(10, 8, 10, 10)
        self.body.setSpacing(6)
