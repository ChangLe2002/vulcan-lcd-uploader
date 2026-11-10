# SPDX-License-Identifier: MIT
"""文字投屏面板 —— 当前**唯一**可写硬件的功能（title_display 已验证）。"""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from ...app import AppContext
from ...core.protocol import encode_title
from ...core.transport import TransportError
from ..link import SerialLink
from ..widgets import Section

__all__ = ["TitlePanel"]


class TitlePanel(Section):
    def __init__(self, ctx: AppContext, link: SerialLink, parent: QWidget | None = None) -> None:
        super().__init__("① 文字投屏（已验证功能）", parent)
        self._ctx = ctx
        self._link = link
        self._build()

    def _build(self) -> None:
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入文字，例如 I LOVE YOU（仅 A-Z 0-9 . 空格）")
        self.input.setText("I LOVE YOU")
        self.btn_send = QPushButton("发送到屏幕")
        row.addWidget(self.input, 1)
        row.addWidget(self.btn_send)
        self.body.addLayout(row)

        self.chk_init = QCheckBox("发送前先发初始化序列（首次连接建议勾选）")
        self.chk_init.setChecked(True)
        self.body.addWidget(self.chk_init)

        self.status = QLabel("仅支持大写字母、数字、小数点、空格；其它字符会被忽略。")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #666;")
        self.body.addWidget(self.status)

        self.btn_send.clicked.connect(self.send)
        self.input.returnPressed.connect(self.send)

    def send(self) -> None:
        encoding = encode_title(self.input.text())
        if not encoding.raw:
            self.status.setText("清洗后为空：屏幕只支持 A-Z 0-9 . 空格。")
            return
        if not self._ctx.feature_allowed("title_display"):
            self.status.setText(self._ctx.blocked_reason("title_display") or "功能不可用")
            return
        if not self._link.ensure_open():
            self.status.setText("串口未连接：未检测到智屏或端口被占用。")
            return

        try:
            if self.chk_init.isChecked():
                self._link.send_init_sequence()
            ok = self._link.send_title(encoding)
        except TransportError as exc:
            self.status.setText(f"发送失败：{exc.message}")
            return

        if ok:
            note = encoding.user_note()
            self.status.setText(
                f"已发送：{encoding.text!r}" + (f"（{note}）" if note else "")
            )
        else:
            self.status.setText("发送被拒绝，详见日志。")
