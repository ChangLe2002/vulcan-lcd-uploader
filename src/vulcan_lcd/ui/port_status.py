# SPDX-License-Identifier: MIT
"""智屏串口状态条：串口状态 + 上次读到的可用内存。

串口是独占的，"可用内存"只能在我们接管设备时读到，因此显示的是
**上次读取的值**（悬停提示里有说明）。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..app import AppContext
from ..core.port_scanner import find_lcd_port
from ..features.device_state import cached, describe_free, load
from .link import SerialLink

__all__ = ["PortStatusBar"]

_OK = "#1a7f37"
_WARN = "#b26a00"
_BAD = "#b3261e"
_MUTED = "#5f6368"


class PortStatusBar(QWidget):
    """两行状态条：①串口状态；②可用内存 + 扫描按钮。"""

    def __init__(self, ctx: AppContext, link: SerialLink, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._link = link

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 2, 4, 2)
        outer.setSpacing(2)

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        self.dot = QLabel("●")
        self.text = QLabel()
        self.text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row1.addWidget(self.dot)
        row1.addWidget(self.text, 1)
        outer.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        self.memory = QLabel("可用内存 —")
        self.memory.setStyleSheet(f"color:{_MUTED}; font-size:12px;")
        self.memory.setToolTip("串口独占，只有我们接管设备时才能读取；这里显示上次读到的值")
        row2.addWidget(self.memory, 1)

        self.btn_scan = QPushButton("扫描")
        self.btn_scan.setToolTip("重新扫描串口/设备（平时会自动检测）")
        self.btn_scan.setMaximumWidth(64)
        self.btn_scan.clicked.connect(self.scan)
        row2.addWidget(self.btn_scan)
        outer.addLayout(row2)

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self.refresh)
        load(Path(self._ctx.root) / "device_state.json")
        self._timer.start()
        self.refresh()

    def scan(self) -> None:
        """手动触发一次扫描，并给出明确的即时结果。"""
        port = find_lcd_port()
        self.refresh()
        if port:
            self._paint(_OK if self._link.is_open else _WARN, f"已扫描到智屏：{port}")
        else:
            self._paint(_BAD, "未扫描到智屏（检查 USB）")

    def refresh(self) -> None:
        """刷新显示：已连接 > 检测到但未打开 > 未检测到；并显示缓存的可用内存。"""
        state = cached()
        if state is not None and state.free_bytes is not None:
            text = f"可用内存 {describe_free(state.free_bytes)}"
            if state.updated_at:
                text += f"（{state.updated_at} 读取）"
            self.memory.setText(text)
        else:
            self.memory.setText("可用内存 —")

        if self._link.is_open:
            self._paint(_OK, f"智屏 已连接 · {self._link.port}")
            return
        port = find_lcd_port()
        if port:
            self._paint(_WARN, f"智屏 未连接 · {port}")
            self.text.setToolTip("发送时会自动连接；点「扫描设备」可重新检测")
        else:
            self._paint(_BAD, "智屏 未检测到设备（检查 USB）")

    def _paint(self, color: str, text: str) -> None:
        self.dot.setStyleSheet(f"color:{color}; font-size:14px;")
        self.text.setText(text)
        self.text.setStyleSheet(f"color:{color}; font-size:13px; font-weight:600;")
