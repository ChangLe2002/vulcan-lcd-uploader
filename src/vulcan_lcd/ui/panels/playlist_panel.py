# SPDX-License-Identifier: MIT
"""播放列表面板：多素材轮播，**每项可单独设置停留时间**。

实测要点（2026-11-06）
----------------------
* 设备能即时在已上传文件之间切换显示；
* 刚上传完时设备还在注册文件，立刻切换会闪官方图/显示"上传中"，
  所以 ``carousel.run_playlist`` 会先校验清单、再静置几秒才开播；
* 槽位必须连续（max+1），跳号会被静默丢弃。
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from ...app import AppContext
from ...core.port_scanner import find_lcd_port
from ...core.transport import SerialSettings, Transport
from ...features.carousel import build_entries, run_playlist
from ...system.service_control import ServiceController
from ..widgets import Section

__all__ = ["PlaylistPanel"]

_MUTED = "#5f6368"
_OK = "#1a7f37"
_WARN = "#b3261e"
_COL_NAME = 0
_COL_SECONDS = 1


class _PlaylistWorker(QThread):
    """后台：编码全部素材 → 接管串口 → 逐个上传 → 循环显示。"""

    status = Signal(str)
    failed = Signal(str)
    finished_ok = Signal(str)

    def __init__(self, ctx: AppContext, items: list[tuple[Path, float]], port: str) -> None:
        super().__init__()
        self._ctx = ctx
        self._items = items
        self._port = port
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:  # noqa: D102 - QThread 约定
        try:
            def on_encode(done: int, total: int, name: str) -> None:
                self.status.emit(f"编码 {done}/{total}：{name}")

            entries = build_entries(self._items, on_progress=on_encode)
            report = run_playlist(
                entries,
                controller=ServiceController(self._ctx.service_name),
                transport=Transport(self._port, SerialSettings()),
                stop_event=self._stop,
                on_status=self.status.emit,
            )
            if report.error:
                self.failed.emit(report.error)
            else:
                self.finished_ok.emit(report.describe())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class PlaylistPanel(Section):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__("播放列表（轮播）", parent)
        self._ctx = ctx
        self._worker: _PlaylistWorker | None = None
        self._build()

    def _build(self) -> None:
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["文件", "停留（秒）"])
        self.table.horizontalHeader().setSectionResizeMode(
            _COL_NAME, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            _COL_SECONDS, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.table.setMinimumHeight(150)
        self.body.addWidget(self.table)

        row = QHBoxLayout()
        self.btn_add = QPushButton("添加…")
        self.btn_remove = QPushButton("移除")
        self.btn_clear = QPushButton("清空")
        row.addWidget(self.btn_add)
        row.addWidget(self.btn_remove)
        row.addWidget(self.btn_clear)
        row.addStretch(1)
        self.body.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("新增默认停留"))
        self.seconds = QSpinBox()
        self.seconds.setRange(1, 3600)
        self.seconds.setValue(5)
        self.seconds.setSingleStep(1)
        self.seconds.setMinimumWidth(80)
        self.seconds.setKeyboardTracking(False)
        self.seconds.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row2.addWidget(self.seconds)
        unit = QLabel("秒")
        unit.setStyleSheet(f"color:{_MUTED}; font-size:12px;")
        row2.addWidget(unit)
        row2.addSpacing(10)
        self.btn_start = QPushButton("开始轮播")
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setEnabled(False)
        row2.addWidget(self.btn_start)
        row2.addWidget(self.btn_stop)
        row2.addStretch(1)
        self.body.addLayout(row2)

        self.note = QLabel(
            "添加多个 GIF/图片 → 开始轮播。双击「停留（秒）」单元格可单独修改每项时间。"
        )
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color:{_MUTED}; font-size:12px;")
        self.body.addWidget(self.note)

        self.btn_add.clicked.connect(self.add_files)
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear.clicked.connect(lambda: self.table.setRowCount(0))
        self.btn_start.clicked.connect(self.start_rotation)
        self.btn_stop.clicked.connect(self.stop_rotation)
        self.table.itemChanged.connect(self._on_item_changed)

    # -- 编辑 ------------------------------------------------------------- #
    def add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "添加到播放列表", "", "图像 (*.gif *.png *.jpg *.jpeg)"
        )
        for path in paths:
            row = self.table.rowCount()
            self.table.insertRow(row)
            name_item = QTableWidgetItem(Path(path).name)
            name_item.setData(Qt.ItemDataRole.UserRole, str(path))
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, _COL_NAME, name_item)
            sec_item = QTableWidgetItem(str(self.seconds.value()))
            sec_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, _COL_SECONDS, sec_item)

    def remove_selected(self) -> None:
        for index in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(index)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != _COL_SECONDS:
            return
        text = item.text().strip()
        try:
            value = max(1, min(3600, int(float(text))))
        except ValueError:
            value = 1
        if text != str(value):
            self.table.blockSignals(True)
            item.setText(str(value))
            self.table.blockSignals(False)

    def _items(self) -> list[tuple[Path, float]]:
        out: list[tuple[Path, float]] = []
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, _COL_NAME)
            sec_item = self.table.item(row, _COL_SECONDS)
            if name_item is None:
                continue
            raw = name_item.data(Qt.ItemDataRole.UserRole)
            if not raw:
                continue
            try:
                seconds = float(sec_item.text()) if sec_item is not None else 5.0
            except ValueError:
                seconds = 5.0
            out.append((Path(str(raw)), max(1.0, seconds)))
        return out

    # -- 轮播 ------------------------------------------------------------- #
    def start_rotation(self) -> None:
        items = self._items()
        if not items:
            self._set_note("播放列表为空。", _WARN)
            return
        port = find_lcd_port() or str(
            self._ctx.config.get("port_scan", {}).get("preferred_port") or "COM5"
        )
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        total = sum(sec for _, sec in items)
        self._set_note(f"准备轮播 {len(items)} 项（一轮 {total:.0f} 秒，{port}）…", _MUTED)

        self._worker = _PlaylistWorker(self._ctx, items, port)
        self._worker.status.connect(lambda text: self._set_note(text, _MUTED))
        self._worker.failed.connect(self._on_failed)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.finished.connect(self._on_thread_finished)
        self._worker.start()

    def stop_rotation(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._set_note("正在停止轮播（恢复官方服务）…", _MUTED)
            self._worker.stop()
        else:
            self._set_note("已停止轮播。", _MUTED)

    # -- 回调 ------------------------------------------------------------- #
    def _on_done(self, text: str) -> None:
        self._set_note(f"✅ {text}", _OK)

    def _on_failed(self, message: str) -> None:
        self._set_note(f"⚠️ {message}", _WARN)

    def _on_thread_finished(self) -> None:
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def _set_note(self, text: str, color: str) -> None:
        self.note.setText(text)
        self.note.setStyleSheet(f"color:{color}; font-size:12px;")
