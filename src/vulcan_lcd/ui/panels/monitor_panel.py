# SPDX-License-Identifier: MIT
"""硬件监控：**完全本地采集，不依赖 iGame Center**。

* GPU 走 NVML（显卡驱动自带），CPU/内存走 psutil，都是本机 API；
* 无论官方服务是否运行、小屏是否插着，都能正常显示；
* **只读**：监控数据上屏所需的指令尚未验证，所以这里只采集与显示，
  绝不向串口发送任何字节（硬性约束）。
"""

from __future__ import annotations

import platform

import threading

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QSizePolicy,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from ...app import AppContext
from ...core.port_scanner import find_lcd_port
from ...core.transport import SerialSettings, Transport
from ...features.monitor_stream import LAYOUTS, run_monitor_stream
from ...system.service_control import ServiceController
from ..widgets import Section

__all__ = ["MonitorPanel"]

_MUTED = "#5f6368"
_OK = "#1a7f37"
_WARN = "#b26a00"

#: (键, 显示名, 分组)
_ROWS = [
    ("gpu_name", "显卡", "GPU"),
    ("gpu_util", "使用率", "GPU"),
    ("gpu_temp", "温度", "GPU"),
    ("gpu_mem", "显存", "GPU"),
    ("gpu_clock", "频率", "GPU"),
    ("gpu_power", "功耗", "GPU"),
    ("gpu_fan", "风扇", "GPU"),
    ("cpu_name", "处理器", "CPU"),
    ("cpu_util", "使用率", "CPU"),
    ("cpu_freq", "频率", "CPU"),
    ("mem", "内存", "CPU"),
]


class _MonitorWorker(QThread):
    """后台持续发送监控帧（设备自己渲染）。"""

    status = Signal(str)
    failed = Signal(str)
    finished_ok = Signal(str)

    def __init__(self, ctx: AppContext, layout: str, interval_s: float, port: str) -> None:
        super().__init__()
        self._ctx = ctx
        self._layout = layout
        self._interval = interval_s
        self._port = port
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:  # noqa: D102 - QThread 约定
        error = run_monitor_stream(
            controller=ServiceController(self._ctx.service_name),
            transport=Transport(self._port, SerialSettings()),
            stop_event=self._stop,
            layout=self._layout,
            interval_s=self._interval,
            on_status=self.status.emit,
        )
        if error:
            self.failed.emit(error)
        else:
            self.finished_ok.emit("已停止上屏，官方显示已恢复")


class MonitorPanel(Section):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__("硬件监控（本地采集）", parent)
        self._ctx = ctx
        self._nvml_ready = False
        self._handle = None
        self._paused = False
        self._cpu_name = ""
        self._monitor_worker: _MonitorWorker | None = None
        self._build()

    # -- 构建 ------------------------------------------------------------- #
    def _build(self) -> None:
        hint = QLabel(
            "本地读取显卡/CPU 传感器，不依赖 iGame Center。"
            "点「显示到屏幕」会把数值交给屏幕自己渲染（不上传图片）。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{_MUTED}; font-size:12px;")
        self.body.addWidget(hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)
        self.values: dict[str, QLabel] = {}

        gpu_row = 0
        grid.addWidget(self._group_label("GPU"), gpu_row, 0, 1, 2)
        gpu_row += 1
        cpu_started = False
        for key, label, group in _ROWS:
            if group == "CPU" and not cpu_started:
                grid.addWidget(self._group_label("CPU"), gpu_row, 0, 1, 2)
                gpu_row += 1
                cpu_started = True
            grid.addWidget(QLabel(label), gpu_row, 0)
            value = QLabel("—")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setStyleSheet("font-size:13px;")
            # 允许被压缩：否则长文本（CPU 型号、显存）会把整页最小宽度顶到 800+
            value.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
            )
            value.setWordWrap(True)
            grid.addWidget(value, gpu_row, 1)
            self.values[key] = value
            gpu_row += 1
        grid.setColumnStretch(1, 1)
        self.body.addLayout(grid)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("刷新"))
        self.interval = QComboBox()
        for text, ms in (("0.5 秒", 500), ("1 秒", 1000), ("2 秒", 2000), ("5 秒", 5000)):
            self.interval.addItem(text, ms)
        self.interval.setCurrentIndex(1)
        self.interval.setMaximumWidth(90)
        self.interval.currentIndexChanged.connect(self._apply_interval)
        controls.addWidget(self.interval)

        controls.addSpacing(8)
        controls.addWidget(QLabel("上屏内容"))
        self.layout_combo = QComboBox()
        for key, label in LAYOUTS.items():
            self.layout_combo.addItem(label, key)
        # 默认「显卡：负载/温度/频率」——这台机器上所有指标都能读到
        default_index = self.layout_combo.findData("gpu_core")
        if default_index >= 0:
            self.layout_combo.setCurrentIndex(default_index)
        controls.addWidget(self.layout_combo, 1)
        self.body.addLayout(controls)

        row = QHBoxLayout()
        self.on_screen = QPushButton("显示到屏幕")
        self.on_screen.setToolTip(
            "把 GPU/CPU 数值交给屏幕自己渲染（不上传图片，也不依赖 iGame Center）"
        )
        self.on_screen.clicked.connect(self.start_screen)
        row.addWidget(self.on_screen)

        self.stop_screen = QPushButton("停止上屏")
        self.stop_screen.setEnabled(False)
        self.stop_screen.clicked.connect(self.stop_screen_stream)
        row.addWidget(self.stop_screen)

        self.btn_pause = QPushButton("暂停")
        self.btn_pause.setCheckable(True)
        self.btn_pause.toggled.connect(self._toggle_pause)
        row.addWidget(self.btn_pause)
        row.addStretch(1)
        self.body.addLayout(row)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{_MUTED}; font-size:12px;")
        self.status.setWordWrap(True)
        self.body.addWidget(self.status)


        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.poll()

    @staticmethod
    def _group_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("color:#37474f; font-weight:600; font-size:12px;")
        return label

    def _apply_interval(self) -> None:
        self.timer.setInterval(int(self.interval.currentData() or 1000))

    def _toggle_pause(self, paused: bool) -> None:
        self._paused = paused
        self.btn_pause.setText("继续" if paused else "暂停")
        if paused:
            self.timer.stop()
            self._set_status("已暂停采集", _WARN)
        else:
            self.timer.start()
            self.poll()

    def _set_status(self, text: str, color: str = _MUTED) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color:{color}; font-size:12px;")

    # -- 采集 ------------------------------------------------------------- #
    def _init_nvml(self) -> bool:
        if self._nvml_ready:
            return True
        try:
            import pynvml  # noqa: PLC0415

            pynvml.nvmlInit()
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            self._pynvml = pynvml
            self._nvml_ready = True
            self._set_status("NVML 已就绪（本地读取）", _OK)
            return True
        except Exception as exc:  # noqa: BLE001 - 无 N 卡/无驱动都可能失败
            self.values["gpu_name"].setText("NVML 不可用（未检测到 NVIDIA 显卡或驱动）")
            self._set_status(f"GPU 采集不可用：{type(exc).__name__}", _WARN)
            return False

    def poll(self) -> None:
        if self._paused:
            return
        self._poll_gpu()
        self._poll_cpu()

    def _poll_gpu(self) -> None:
        if not self._init_nvml():
            return
        nv = self._pynvml
        handle = self._handle
        try:
            name = nv.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode(errors="replace")
            self.values["gpu_name"].setText(str(name))

            self.values["gpu_util"].setText(f"{nv.nvmlDeviceGetUtilizationRates(handle).gpu} %")
            self.values["gpu_temp"].setText(
                f"{nv.nvmlDeviceGetTemperature(handle, nv.NVML_TEMPERATURE_GPU)} °C"
            )

            mem = nv.nvmlDeviceGetMemoryInfo(handle)
            used = mem.used / 1024 / 1024
            total = mem.total / 1024 / 1024
            self.values["gpu_mem"].setText(
                f"{used:,.0f} / {total:,.0f} MB（{used / total * 100:.0f}%）"
            )
            self.values["gpu_clock"].setText(
                f"{nv.nvmlDeviceGetClockInfo(handle, nv.NVML_CLOCK_GRAPHICS)} MHz"
            )
            self.values["gpu_power"].setText(f"{nv.nvmlDeviceGetPowerUsage(handle) / 1000.0:.1f} W")

            try:
                fan = nv.nvmlDeviceGetFanSpeed(handle)
                self.values["gpu_fan"].setText(f"{fan} %")
            except Exception:  # noqa: BLE001 - 水冷/无风扇型号会抛异常
                self.values["gpu_fan"].setText("不可用")
        except Exception as exc:  # noqa: BLE001
            self.values["gpu_name"].setText(f"读取失败：{type(exc).__name__}")

    def _poll_cpu(self) -> None:
        try:
            import psutil  # noqa: PLC0415

            if not self._cpu_name:
                raw = platform.processor() or "CPU"
                short = "AMD" if "AMD" in raw.upper() else ("INTEL" if "INTEL" in raw.upper() else raw[:18])
                try:
                    short += f" · {psutil.cpu_count(logical=True)} 线程"
                except Exception:  # noqa: BLE001
                    pass
                self._cpu_name = short
            self.values["cpu_name"].setText(self._cpu_name)
            self.values["cpu_util"].setText(f"{psutil.cpu_percent(interval=None):.0f} %")

            freq = psutil.cpu_freq()
            self.values["cpu_freq"].setText(f"{freq.current:.0f} MHz" if freq else "不可用")


            mem = psutil.virtual_memory()
            self.values["mem"].setText(
                f"{mem.used / 1024**3:.1f} / {mem.total / 1024**3:.1f} GB（{mem.percent:.0f}%）"
            )
        except Exception as exc:  # noqa: BLE001
            self.values["cpu_util"].setText(f"读取失败：{type(exc).__name__}")


    # -- 上屏（设备自己渲染）---------------------------------------------- #
    def start_screen(self) -> None:
        """开始把监控数据发送给屏幕（设备自己渲染，不上传图片）。"""
        if self._monitor_worker is not None and self._monitor_worker.isRunning():
            return
        port = find_lcd_port() or str(
            self._ctx.config.get("port_scan", {}).get("preferred_port") or "COM5"
        )
        layout = str(self.layout_combo.currentData() or "gpu_core")
        interval_s = max(0.3, int(self.interval.currentData() or 1000) / 1000.0)
        self._set_status(f"正在接管串口并开始上屏（{port}）…", _WARN)
        self.on_screen.setEnabled(False)
        self.stop_screen.setEnabled(True)
        self.timer.stop()      # 本地轮询让位给上屏线程，避免重复读传感器

        self._monitor_worker = _MonitorWorker(self._ctx, layout, interval_s, port)
        self._monitor_worker.status.connect(lambda text: self._set_status(text, _OK))
        self._monitor_worker.failed.connect(self._on_screen_failed)
        self._monitor_worker.finished_ok.connect(
            lambda text: self._set_status(text, _MUTED)
        )
        self._monitor_worker.finished.connect(self._on_screen_finished)
        self._monitor_worker.start()

    def stop_screen_stream(self) -> None:
        """停止上屏并恢复官方显示。"""
        if self._monitor_worker is not None and self._monitor_worker.isRunning():
            self._set_status("正在停止上屏并恢复官方显示…", _MUTED)
            self._monitor_worker.stop()

    def _on_screen_failed(self, message: str) -> None:
        self._set_status(f"上屏失败：{message}", _WARN)

    def _on_screen_finished(self) -> None:
        self._monitor_worker = None
        self.on_screen.setEnabled(True)
        self.stop_screen.setEnabled(False)
        if not self._paused:
            self.timer.start()
            self.poll()

    # -- 生命周期 --------------------------------------------------------- #
    def shutdown(self) -> None:
        if self._monitor_worker is not None and self._monitor_worker.isRunning():
            self._monitor_worker.stop()
            self._monitor_worker.wait(15000)
        self.timer.stop()
        if self._nvml_ready:
            try:
                self._pynvml.nvmlShutdown()
            except Exception:  # noqa: BLE001
                pass
            self._nvml_ready = False
