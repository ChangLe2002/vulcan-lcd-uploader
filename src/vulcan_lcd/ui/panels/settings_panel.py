# SPDX-License-Identifier: MIT
"""设备设置面板：亮度 / 设备信息 / 开机图 / 开机动画。

所有操作都会短暂接管串口（停官方服务 → 操作 → 恢复），因此放在后台线程里跑。
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)

from ...app import AppContext
from ...core.port_scanner import find_lcd_port
from ...core.transport import SerialSettings, Transport
from ...features.device_settings import (
    OP_THEMES,
    play_op,
    read_settings,
    set_brightness,
    set_op_type,
    set_start_image,
)
from ...features.device_state import DeviceState, remember
from ...features.gif_upload import query_file_list, query_free_space
from ...system.service_control import ServiceController
from ..widgets import Section

__all__ = ["SettingsPanel"]

_MUTED = "#5f6368"
_OK = "#1a7f37"
_WARN = "#b3261e"


class _DeviceWorker(QThread):
    """在后台执行一次设备操作（停服务 → 打开串口 → 操作 → 恢复）。"""

    finished_ok = Signal(str)
    failed = Signal(str)
    snapshot = Signal(str, list)   # 设备信息文本, 文件清单

    def __init__(self, ctx: AppContext, action: str, arg: object = None) -> None:
        super().__init__()
        self._ctx = ctx
        self._action = action
        self._arg = arg

    def run(self) -> None:  # noqa: D102 - QThread 约定
        controller = ServiceController(self._ctx.service_name)
        port = find_lcd_port() or str(
            self._ctx.config.get("port_scan", {}).get("preferred_port") or "COM5"
        )
        transport = Transport(port, SerialSettings())
        took_over = False
        try:
            controller.takeover()
            took_over = True
            last: Exception | None = None
            for _ in range(20):
                try:
                    transport.open()
                    last = None
                    break
                except Exception as exc:  # noqa: BLE001
                    last = exc
                    time.sleep(1.0)
            if last is not None:
                self.failed.emit(f"打不开串口：{last}")
                return

            if self._action == "read":
                info = read_settings(transport)
                free = query_free_space(transport)
                files = [item.name for item in query_file_list(transport)]
                if info is not None or free is not None:
                    remember(
                        DeviceState(
                            free_bytes=free,
                            firmware=info.firmware if info else "",
                            brightness=info.brightness if info else None,
                            device_id=info.device_id if info else None,
                            op_type=info.op_type if info else None,
                        ),
                        path=Path(self._ctx.root) / "device_state.json",
                    )
                if info is None:
                    self.failed.emit("读取设备设置失败（设备无应答）")
                    return
                self.snapshot.emit(info.describe(), files)
                self.finished_ok.emit(info.describe())
            elif self._action == "brightness":
                level = int(self._arg or 0)  # type: ignore[arg-type]
                ok = set_brightness(transport, level)
                self.finished_ok.emit(f"亮度已设为 {level}/10" if ok else "设置亮度失败")
            elif self._action == "start_image":
                name = str(self._arg or "")
                ok = set_start_image(transport, name)
                self.finished_ok.emit(f"开机图已设为 {name}" if ok else "设置开机图失败")
            elif self._action == "op":
                theme = int(self._arg or 1)  # type: ignore[arg-type]
                ok = set_op_type(transport, theme)
                label = OP_THEMES.get(theme, str(theme))
                self.finished_ok.emit(f"开机动画已切换为 {label}" if ok else "切换动画失败")
            elif self._action == "play_op":
                theme = int(self._arg or 1)  # type: ignore[arg-type]
                ok = play_op(transport, theme)
                label = OP_THEMES.get(theme, str(theme))
                self.finished_ok.emit(f"已播放 {label} 动画" if ok else "播放动画失败")
            else:
                self.failed.emit(f"未知操作：{self._action}")
        except Exception as exc:  # noqa: BLE001 - 设置失败不该炸 UI
            self.failed.emit(str(exc))
        finally:
            try:
                transport.close()
            except Exception:  # noqa: BLE001
                pass
            if took_over:
                try:
                    controller.release()
                except Exception:  # noqa: BLE001
                    pass


class SettingsPanel(Section):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__("设备设置", parent)
        self._ctx = ctx
        self._worker: _DeviceWorker | None = None
        self._build()

    def _build(self) -> None:
        # 设备信息
        row0 = QHBoxLayout()
        self.info = QLabel("尚未读取")
        self.info.setStyleSheet(f"color:{_MUTED}; font-size:12px;")
        self.info.setWordWrap(True)
        self.btn_read = QPushButton("读取设备信息")
        row0.addWidget(self.info, 1)
        row0.addWidget(self.btn_read)
        self.body.addLayout(row0)

        # 亮度
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("亮度"))
        self.brightness = QSlider(Qt.Orientation.Horizontal)
        self.brightness.setRange(0, 10)
        self.brightness.setValue(10)
        self.brightness.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.brightness.setTickInterval(1)
        self.brightness.setMinimumWidth(160)
        self.bright_value = QLabel("10")
        self.bright_value.setMinimumWidth(24)
        self.btn_bright = QPushButton("应用")
        row1.addWidget(self.brightness, 1)
        row1.addWidget(self.bright_value)
        row1.addWidget(self.btn_bright)
        self.body.addLayout(row1)

        # 开机图
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("开机图"))
        self.start_image = QComboBox()
        self.start_image.setMinimumWidth(160)
        self.start_image.addItem("（先读取设备信息）", "")
        self.btn_start_image = QPushButton("设为开机图")
        row2.addWidget(self.start_image, 1)
        row2.addWidget(self.btn_start_image)
        self.body.addLayout(row2)

        # 开机动画
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("开机动画"))
        self.btn_op_vulcan = QPushButton("切换 Vulcan")
        self.btn_play_vulcan = QPushButton("播放 Vulcan")
        for btn in (self.btn_op_vulcan, self.btn_play_vulcan):
            row3.addWidget(btn)
        row3.addStretch(1)
        self.body.addLayout(row3)

        self.note = QLabel("这些设置会短暂停止官方服务，读取/写入完成后自动恢复。")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color:{_MUTED}; font-size:12px;")
        self.body.addWidget(self.note)

        self.btn_read.clicked.connect(lambda: self._run("read"))
        self.btn_bright.clicked.connect(
            lambda: self._run("brightness", self.brightness.value())
        )
        self.brightness.valueChanged.connect(lambda v: self.bright_value.setText(str(v)))
        self.btn_start_image.clicked.connect(
            lambda: self._run("start_image", self.start_image.currentData() or "")
        )
        self.btn_op_vulcan.clicked.connect(lambda: self._run("op", 1))
        self.btn_play_vulcan.clicked.connect(lambda: self._run("play_op", 1))

    # -- 执行 ------------------------------------------------------------- #
    def _run(self, action: str, arg: object = None) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._set_note("上一个操作还没完成，请稍候…", _MUTED)
            return
        self._set_note("正在接管串口…", _MUTED)
        self._worker = _DeviceWorker(self._ctx, action, arg)
        self._worker.finished_ok.connect(lambda text: self._set_note(f"✅ {text}", _OK))
        self._worker.failed.connect(lambda text: self._set_note(f"⚠️ {text}", _WARN))
        self._worker.snapshot.connect(self._on_snapshot)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_snapshot(self, text: str, files: list) -> None:
        self.info.setText(text)
        self.info.setStyleSheet(f"color:{_OK}; font-size:12px;")
        current = self.start_image.currentData()
        self.start_image.clear()
        if not files:
            self.start_image.addItem("（设备上没有文件）", "")
        for name in files:
            self.start_image.addItem(str(name), str(name))
        if current:
            index = self.start_image.findData(current)
            if index >= 0:
                self.start_image.setCurrentIndex(index)

    def _on_finished(self) -> None:
        self._worker = None

    def _set_note(self, text: str, color: str) -> None:
        self.note.setText(text)
        self.note.setStyleSheet(f"color:{color}; font-size:12px;")
