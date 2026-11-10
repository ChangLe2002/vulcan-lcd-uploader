# SPDX-License-Identifier: MIT
"""新界面主窗口（按设计图重排，功能沿用既有 features 层）。

布局对应设计图：
    顶栏：品牌 / 导航 / 串口状态 / 时钟
    左栏：01 设备链接、02 硬件监控、03 播放列表、会话栏
    中间：机箱视图（显卡小屏位置叠加竖屏预览）
    右栏：04 投屏内容、05 设备设置、06 调试
    底栏：提示与版本
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QRect, Qt, QThread, QTimer, Signal
from PySide6.QtCore import QUrl
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..app import AppContext
from ..meta import APP_VERSION
from ..core.port_scanner import find_lcd_port
from ..features.autostart import disable as autostart_disable
from ..features.autostart import enable as autostart_enable
from ..features.autostart import is_enabled as autostart_enabled
from ..features.device_state import cached, describe_free, load as load_state
from ..features.history import History
from ..features.monitor_stream import LAYOUTS
from ..features.sensors import read_cpu, read_gpu
from ..core.protocol import encode_title
from ..features.ui_prefs import CLOSE_TO_TRAY, STANDALONE, load_prefs, save_prefs
from ..system.service_control import ServiceController, is_standalone, set_standalone
from ..ui.link import SerialLink
from ..ui.panels.playlist_panel import _PlaylistWorker
from ..ui.panels.preview_panel import _ProbeWorker, _UploadWorker
from ..ui.panels.settings_panel import _DeviceWorker
from . import theme
from .widgets import AccentButton, CaseView, Dot, MetricBar, Panel

__all__ = ["NewMainWindow"]

def _assets_dir() -> Path:
    """定位机箱底图：打包后走 _internal/ui2_assets，源码运行用包内 assets。"""
    from ..app import resource_root

    bundled = Path(resource_root()) / "ui2_assets"
    if bundled.is_dir():
        return bundled
    return Path(__file__).resolve().parent / "assets"


ASSETS = _assets_dir()
LCD_RECT = QRect(926, 575, 150, 400)    # 显卡小屏放大后的位置（锚在 GPU 上）


class PreviewCanvas(QWidget):
    """按比例居中绘制一张图（横屏预览用）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._caption = "选择文件后显示"
        self.setMinimumHeight(120)

    def set_image(self, pixmap: QPixmap | None) -> None:
        self._pixmap = pixmap
        self.update()

    def paintEvent(self, event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        rect = self.rect()
        painter.fillRect(rect, QColor("#0b0e13"))
        painter.setPen(QColor(theme.BORDER))
        painter.drawRect(rect.adjusted(0, 0, -1, -1))
        if self._pixmap is None or self._pixmap.isNull():
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._caption)
        else:
            scaled = self._pixmap.scaled(
                rect.size() - QRect(0, 0, 2, 2).size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(
                rect.x() + (rect.width() - scaled.width()) // 2,
                rect.y() + (rect.height() - scaled.height()) // 2,
                scaled,
            )
        painter.end()


def _trim_working_set() -> None:
    """把工作集还给系统（最小化到托盘时 RSS 骤降，唤回时按需换页回来）。"""
    import os  # noqa: PLC0415

    if os.name != "nt":
        return
    try:
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.SetProcessWorkingSetSize.argtypes = [
            wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t,
        ]
        handle = kernel32.GetCurrentProcess()
        kernel32.SetProcessWorkingSetSize(handle, ctypes.c_size_t(-1), ctypes.c_size_t(-1))
    except Exception:  # noqa: BLE001 - 纯优化，失败无所谓
        pass


class _TextWorker(QThread):
    """发送文字投屏：自动停官方服务 → 打开串口 → 发送 → 恢复服务。"""

    ok = Signal(str)
    failed = Signal(str)

    def __init__(self, ctx: AppContext, text: str) -> None:
        super().__init__()
        self._ctx = ctx
        self._text = text

    def run(self) -> None:  # noqa: D102 - QThread 约定
        from ..core.handshake import send_init_sequence  # noqa: PLC0415
        from ..core.protocol import build_time_frame, encode_title  # noqa: PLC0415
        from ..core.transport import SerialSettings, Transport  # noqa: PLC0415

        encoding = encode_title(self._text)
        if not encoding.raw:
            self.failed.emit("清洗后为空：只支持 A-Z 0-9 . 空格")
            return

        controller = ServiceController(self._ctx.service_name)
        port = find_lcd_port() or "COM5"
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
                    time.sleep(1)
            if last is not None:
                self.failed.emit(f"打不开串口：{last}")
                return
            if not self._ctx.session.dry_run:
                send_init_sequence(transport)
            transport.write(build_time_frame(encoding))
            transport.flush()
            self.ok.emit(f"文字已发送：{encoding.text}")
        except Exception as exc:  # noqa: BLE001
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


class LinkCard(Panel):
    """01 设备连接：只显示（自动检测），不提供手动启停/连接。"""

    def __init__(self, ctx: AppContext, link: SerialLink, parent: QWidget | None = None) -> None:
        super().__init__("01", "设备连接", "DEVICE LINK", parent)
        self._ctx = ctx
        self._link = link

        port_row = QHBoxLayout()
        self.dot = Dot(theme.WARN)
        port_row.addWidget(self.dot)
        self.port_label = QLabel("检测中…")
        self.port_label.setStyleSheet(f"color:{theme.TEXT}; font-size:12px;")
        port_row.addWidget(self.port_label, 1)
        self.baud = QLabel("115200")
        self.baud.setStyleSheet(f"color:{theme.MUTED}; font-size:10px;")
        port_row.addWidget(self.baud)
        self.body.addLayout(port_row)

        state_row = QHBoxLayout()
        self.service_label = QLabel("iGameCenterService")
        self.service_label.setStyleSheet(f"color:{theme.MUTED}; font-size:10px;")
        state_row.addWidget(self.service_label)
        self.service_state = QLabel("—")
        self.service_state.setStyleSheet(f"color:{theme.MUTED}; font-size:10px;")
        state_row.addWidget(self.service_state)
        state_row.addStretch(1)
        self.body.addLayout(state_row)

        memory_row = QHBoxLayout()
        self.memory = QLabel("可用内存 —")
        self.memory.setStyleSheet(f"color:{theme.MUTED}; font-size:10px;")
        memory_row.addWidget(self.memory, 1)
        self.btn_scan = AccentButton("扫描", variant="ghost")
        self.btn_scan.setFixedWidth(64)
        self.btn_scan.setToolTip("重新检测串口（软件平时会自动检测）")
        self.btn_scan.clicked.connect(lambda: self.refresh(force=True))
        memory_row.addWidget(self.btn_scan)
        self.body.addLayout(memory_row)

        self.refresh()

    # -- 刷新 ------------------------------------------------------------- #
    def refresh(self, *, force: bool = False) -> None:
        """刷新串口 / 服务 / 可用内存（全部只读）。"""
        port = find_lcd_port()
        if port:
            self.dot.set_color(theme.OK)
            self.port_label.setText(f"{port} · USB-SERIAL")
        else:
            self.dot.set_color(theme.BAD)
            self.port_label.setText("未检测到智屏")

        if is_standalone():
            self.service_label.setText("独立模式")
            self.service_state.setText("不管理官方服务")
            self.service_state.setStyleSheet(f"color:{theme.CYAN}; font-size:10px;")
            self._refresh_memory()
            return

        status = _service_status(self._ctx.service_name, force=force)
        if status == "NOT_FOUND":
            # 没装/没启动官方软件也能用：我们把这种状态叫「独立模式」
            self.service_label.setText("独立模式")
            self.service_state.setText("未安装官方服务")
            self.service_state.setStyleSheet(f"color:{theme.CYAN}; font-size:10px;")
        else:
            self.service_label.setText("iGameCenterService")
            self.service_state.setText(status)
            self.service_state.setStyleSheet(
                f"color:{theme.OK if status == 'RUNNING' else theme.WARN}; font-size:10px;"
            )

        self._refresh_memory()

    def _refresh_memory(self) -> None:
        state = cached()
        if state is not None and state.free_bytes is not None:
            text = f"可用内存 {describe_free(state.free_bytes)}"
            if state.updated_at:
                text += f"（{state.updated_at} 读取）"
            self.memory.setText(text)
        else:
            self.memory.setText("可用内存 —")


_SERVICE_CACHE: dict[str, tuple[float, str]] = {}
_SERVICE_TTL_S = 5.0


def _service_status(name: str, *, force: bool = False) -> str:
    """查询官方服务状态：RUNNING / STOPPED / NOT_FOUND（只读，带 5 秒缓存）。

    缓存的意义：状态栏每秒刷新一次，若每次都 ``sc query`` 会不断创建子进程。
    """
    import subprocess  # noqa: PLC0415

    from ..system.proc import run as run_hidden  # noqa: PLC0415

    now = time.monotonic()
    cached_value = _SERVICE_CACHE.get(name)
    if not force and cached_value is not None and now - cached_value[0] < _SERVICE_TTL_S:
        return cached_value[1]

    try:
        result = run_hidden(
            ["sc", "query", name], capture_output=True, text=True, timeout=5
        )
    except Exception:  # noqa: BLE001
        return "NOT_FOUND"
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0 or "1060" in output:
        status = "NOT_FOUND"
    else:
        status = "RUNNING" if "RUNNING" in output.upper() else "STOPPED"
    _SERVICE_CACHE[name] = (now, status)
    return status


class TelemetryCard(Panel):
    """02 硬件监控（本地采集）。"""

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__("02", "硬件监控", "TELEMETRY", parent)
        self._ctx = ctx
        onscreen_row = QHBoxLayout()
        onscreen_row.addWidget(self._muted("上屏内容"))
        self.layout_combo = QComboBox()
        for key, label in LAYOUTS.items():
            self.layout_combo.addItem(label, key)
        index = self.layout_combo.findData("gpu_core")
        if index >= 0:
            self.layout_combo.setCurrentIndex(index)
        onscreen_row.addWidget(self.layout_combo, 1)
        self.btn_onscreen = AccentButton("上屏", variant="ghost")
        self.btn_onscreen.setToolTip("把监控数值交给屏幕自己渲染")
        self.btn_onscreen.setFixedWidth(64)
        self.btn_onscreen.clicked.connect(self._toggle_onscreen)
        onscreen_row.addWidget(self.btn_onscreen)
        self.body.addLayout(onscreen_row)

        self.cpu_bar = MetricBar("CPU", theme.CYAN)
        self.gpu_bar = MetricBar("GPU", theme.ACCENT)
        self.mem_bar = MetricBar("MEM", theme.MAGENTA)
        for bar in (self.cpu_bar, self.gpu_bar, self.mem_bar):
            self.body.addWidget(bar)

        footer = QHBoxLayout()
        self.footer = QLabel("CLK — · FAN — · VOLT —")
        self.footer.setStyleSheet(f"color:{theme.MUTED}; font-size:10px;")
        footer.addWidget(self.footer)
        footer.addStretch(1)
        self.body.addLayout(footer)

        self._worker = None
        self._paused = False
        self.timer = QTimer(self)
        self.timer.setInterval(2000)     # 2 秒足够：温度/负载不会瞬间跳变
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.poll()

    def set_active(self, active: bool) -> None:
        """窗口不可见时停表，避免无意义地读 NVML/psutil。"""
        if active:
            if not self.timer.isActive():
                self.timer.start()
                self.poll()
        else:
            self.timer.stop()

    @staticmethod
    def _muted(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        return label

    def poll(self) -> None:
        if self._paused:
            return
        gpu = read_gpu()
        cpu = read_cpu()
        try:
            import psutil  # noqa: PLC0415

            mem_percent = int(psutil.virtual_memory().percent)
        except Exception:  # noqa: BLE001
            mem_percent = 0
        self.cpu_bar.update_metric(
            badge=f"{cpu.temp:.0f}°C" if cpu.temp else "—",
            value=cpu.load or 0,
            text=f"{cpu.load or 0}%",
        )
        self.gpu_bar.update_metric(
            badge=f"{gpu.temp:.0f}°C" if gpu.temp else "—",
            value=gpu.load or 0,
            text=f"{gpu.load or 0}%",
        )
        self.mem_bar.update_metric(badge=f"{mem_percent}%", value=mem_percent, text=f"{mem_percent}%")
        self.footer.setText(
            f"CLK {cpu.freq or '—'} MHz · FAN {gpu.fan if gpu.fan is not None else '—'}% · "
            f"VRAM {gpu.vram or 0}%"
        )

    def _toggle_onscreen(self) -> None:
        from ..ui.panels.monitor_panel import _MonitorWorker  # noqa: PLC0415

        if self._worker is not None and self._worker.isRunning():
            self._worker.stop()
            self.btn_onscreen.setText("上屏")
            self._paused = False
            self.timer.start()
            return
        port = find_lcd_port() or "COM5"
        layout = str(self.layout_combo.currentData() or "gpu_core")
        self._worker = _MonitorWorker(self._ctx, layout, 1.0, port)
        self._worker.failed.connect(lambda text: self.btn_onscreen.setText("上屏失败"))
        self._worker.start()
        self.btn_onscreen.setText("停止上屏")
        self._paused = True
        self.timer.stop()


class PlaylistCard(Panel):
    """03 播放列表。"""

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__("03", "播放列表", "PLAYLIST", parent)
        self._ctx = ctx
        self._worker: _PlaylistWorker | None = None

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["文件", "停留"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().resizeSection(0, 170)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.setCornerButtonEnabled(False)
        self.table.setStyleSheet("QTableWidget { border: none; background: transparent; }")
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(120)
        self.body.addWidget(self.table)

        row = QHBoxLayout()
        self.btn_add = AccentButton("添加", variant="ghost")
        self.btn_remove = AccentButton("移除", variant="ghost")
        self.btn_clear = AccentButton("清空", variant="ghost")
        row.addWidget(self.btn_add)
        row.addWidget(self.btn_remove)
        row.addWidget(self.btn_clear)
        row.addStretch(1)
        self.body.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(self._muted("停留"))
        self.seconds = QSpinBox()
        self.seconds.setRange(1, 3600)
        self.seconds.setValue(5)
        self.seconds.setMaximumWidth(70)
        row2.addWidget(self.seconds)
        row2.addWidget(self._muted("秒"))
        row2.addStretch(1)
        self.btn_run = AccentButton("轮播", variant="primary")
        self.btn_stop = AccentButton("停止")
        self.btn_stop.setEnabled(False)
        row2.addWidget(self.btn_run)
        row2.addWidget(self.btn_stop)
        self.body.addLayout(row2)

        self.note = QLabel("双击「停留」可单独修改每一项")
        self.note.setStyleSheet(f"color:{theme.MUTED}; font-size:10px;")
        self.body.addWidget(self.note)

        self.btn_add.clicked.connect(self.add_files)
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear.clicked.connect(lambda: self.table.setRowCount(0))
        self.btn_run.clicked.connect(self.start)
        self.btn_stop.clicked.connect(self.stop)

    @staticmethod
    def _muted(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        return label

    def add_files(self) -> None:
        from PySide6.QtWidgets import QFileDialog  # noqa: PLC0415

        paths, _ = QFileDialog.getOpenFileNames(
            self, "添加到播放列表", "", "图像 (*.gif *.png *.jpg *.jpeg)"
        )
        for path in paths:
            row = self.table.rowCount()
            self.table.insertRow(row)
            item = QTableWidgetItem(Path(path).name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, item)
            self.table.setItem(row, 1, QTableWidgetItem(str(self.seconds.value())))

    def remove_selected(self) -> None:
        for index in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(index)

    def _items(self) -> list[tuple[Path, float]]:
        out: list[tuple[Path, float]] = []
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            sec_item = self.table.item(row, 1)
            if name_item is None:
                continue
            raw = name_item.data(Qt.ItemDataRole.UserRole)
            if not raw:
                continue
            try:
                seconds = float(sec_item.text()) if sec_item else 5.0
            except ValueError:
                seconds = 5.0
            out.append((Path(str(raw)), max(1.0, seconds)))
        return out

    def start(self) -> None:
        items = self._items()
        if not items:
            self.note.setText("列表为空")
            return
        port = find_lcd_port() or "COM5"
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._worker = _PlaylistWorker(self._ctx, items, port)
        self._worker.status.connect(lambda text: self.note.setText(text))
        self._worker.failed.connect(lambda text: self.note.setText(f"⚠️ {text}"))
        self._worker.finished_ok.connect(lambda text: self.note.setText(f"✅ {text}"))
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def stop(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self.note.setText("正在停止…")
            self._worker.stop()

    def _on_finished(self) -> None:
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)


class SettingsCard(Panel):
    """05 设备设置（亮度 / 开机图 / 开机动画）。"""

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__("05", "设备设置", "DEVICE CONFIG", parent)
        self._ctx = ctx
        self._worker = None

        row = QHBoxLayout()
        row.addWidget(self._muted("亮度"))
        self.brightness = QSlider(Qt.Orientation.Horizontal)
        self.brightness.setRange(0, 10)
        self.brightness.setValue(10)
        row.addWidget(self.brightness, 1)
        self.bright_value = QLabel("10")
        self.bright_value.setFixedWidth(22)
        self.bright_value.setStyleSheet(f"color:{theme.ACCENT}; font-size:11px;")
        row.addWidget(self.bright_value)
        self.btn_bright = AccentButton("应用")
        self.btn_bright.clicked.connect(
            lambda: self._run("brightness", self.brightness.value())
        )
        row.addWidget(self.btn_bright)
        self.brightness.valueChanged.connect(lambda v: self.bright_value.setText(str(v)))
        self.body.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(self._muted("开机图"))
        self.start_image = QComboBox()
        self.start_image.addItem("（先读取设备信息）", "")
        row2.addWidget(self.start_image, 1)
        self.btn_start_image = AccentButton("设置")
        self.btn_start_image.clicked.connect(
            lambda: self._run("start_image", self.start_image.currentData() or "")
        )
        row2.addWidget(self.btn_start_image)
        self.body.addLayout(row2)

        row3 = QHBoxLayout()
        self.btn_read = AccentButton("读取设备")
        self.btn_op = AccentButton("切换 Vulcan")
        self.btn_play_op = AccentButton("播放动画")
        row3.addWidget(self.btn_read)
        row3.addWidget(self.btn_op)
        row3.addWidget(self.btn_play_op)
        row3.addStretch(1)
        self.body.addLayout(row3)

        self.info = QLabel("尚未读取")
        self.info.setStyleSheet(f"color:{theme.MUTED}; font-size:10px;")
        self.info.setWordWrap(True)
        self.body.addWidget(self.info)

        self.btn_read.clicked.connect(lambda: self._run("read"))
        self.btn_op.clicked.connect(lambda: self._run("op", 1))
        self.btn_play_op.clicked.connect(lambda: self._run("play_op", 1))

    @staticmethod
    def _muted(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        return label

    def _run(self, action: str, arg: object = None) -> None:
        if self._worker is not None and self._worker.isRunning():
            self.info.setText("上一个操作还没完成…")
            return
        self.info.setText("正在接管串口…")
        self._worker = _DeviceWorker(self._ctx, action, arg)
        self._worker.finished_ok.connect(lambda text: self.info.setText(f"✅ {text}"))
        self._worker.failed.connect(lambda text: self.info.setText(f"⚠️ {text}"))
        self._worker.snapshot.connect(self._on_snapshot)
        self._worker.finished.connect(lambda: setattr(self, "_worker", None))
        self._worker.start()

    def _on_snapshot(self, text: str, files: list) -> None:
        self.info.setText(text)
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


class DebugCard(Panel):
    """06 调试控制台。"""

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__("06", "调试", "DEBUG CONSOLE", parent)
        self._ctx = ctx
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        self.body.addWidget(self.log)
        self.body.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_export = AccentButton("导出日志")
        row.addWidget(self.btn_export)
        self.btn_export.clicked.connect(self.export)
        self.body.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.tail)
        self.timer.start()
        self._log_stamp: tuple[str, int] | None = None
        self.tail()

    def set_active(self, active: bool) -> None:
        """窗口不可见时停表。"""
        if active:
            if not self.timer.isActive():
                self.timer.start()
                self.tail()
        else:
            self.timer.stop()

    def note(self, text: str) -> None:
        """在调试卡片里追加一行提示。"""
        self.log.appendPlainText(text)

    def export(self) -> None:
        """导出调试报告（复用旧面板的实现）。"""
        from ..ui.panels.debug_panel import DebugPanel  # noqa: PLC0415

        panel = DebugPanel(self._ctx, None)  # type: ignore[arg-type]
        try:
            panel.export_report()
            self.note("已导出调试报告")
        finally:
            panel.deleteLater()

    def tail(self) -> None:
        try:
            logs = sorted(self._ctx.log_dir.glob("*.log"))
            if not logs:
                return
            newest = logs[-1]
            stat = newest.stat()
            stamp = (str(newest), int(stat.st_mtime_ns))
            if stamp == self._log_stamp:      # 日志没变就不重新解析
                return
            self._log_stamp = stamp
            lines = newest.read_text(encoding="utf-8", errors="replace").splitlines()[-12:]
        except OSError:
            return
        self.log.setPlainText("\n".join(lines[-12:]))
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())


class FeedCard(Panel):
    """04 投屏内容：横屏预览 + 上传 + 文字投屏。"""

    def __init__(self, ctx: AppContext, link: SerialLink, parent: QWidget | None = None) -> None:
        super().__init__("04", "投屏内容", "SCREEN FEED", parent)
        self._ctx = ctx
        self._link = link
        self._path: Path | None = None
        self._probe = None
        self._upload = None
        self._rotation_deg = 180
        self._image = None          # 原始帧（用于旋转后重绘）
        self._portrait: QPixmap | None = None
        self.portrait_changed = lambda pixmap: None   # 由主窗口接管（机箱屏）

        tabs = QHBoxLayout()
        self.btn_image_tab = AccentButton("图像", variant="ghost")
        self.btn_text_tab = AccentButton("文字", variant="ghost")
        tabs.addWidget(self.btn_image_tab)
        tabs.addWidget(self.btn_text_tab)
        tabs.addStretch(1)
        self.size_label = QLabel("1024 × 240")
        self.size_label.setStyleSheet(f"color:{theme.MUTED}; font-size:10px;")
        tabs.addWidget(self.size_label)
        self.body.addLayout(tabs)

        self.canvas = PreviewCanvas()
        self.body.addWidget(self.canvas, 3)

        self.info = QLabel("尚未选择文件")
        self.info.setStyleSheet(f"color:{theme.MUTED}; font-size:10px;")
        self.body.addWidget(self.info)

        row1 = QHBoxLayout()
        self.btn_pick = AccentButton("选择文件")
        self.btn_upload = AccentButton("上传到屏幕", variant="primary")
        row1.addWidget(self.btn_pick)
        row1.addWidget(self.btn_upload)
        self.body.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(self._muted("适配"))
        fit = QLabel("原始尺寸")
        fit.setStyleSheet(f"color:{theme.TEXT}; font-size:11px;")
        row2.addWidget(fit)
        row2.addSpacing(10)
        row2.addWidget(self._muted("旋转"))
        self.rotation = QComboBox()
        self.rotation.addItem("不旋转", False)
        self.rotation.addItem("旋转180°", True)
        self.rotation.setMaximumWidth(96)
        row2.addWidget(self.rotation)
        row2.addStretch(1)
        self.body.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(self._muted("素材库"))
        self.recent = QComboBox()
        row3.addWidget(self.recent, 1)
        self.body.addLayout(row3)

        text_row = QHBoxLayout()
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("文字投屏：仅 A-Z 0-9 . 空格")
        self.btn_text = AccentButton("发送")
        text_row.addWidget(self.text_input, 1)
        text_row.addWidget(self.btn_text)
        self.body.addLayout(text_row)

        self.note = QLabel("")
        self.note.setStyleSheet(f"color:{theme.MUTED}; font-size:10px;")
        self.note.setWordWrap(True)
        self.body.addWidget(self.note)

        self.btn_pick.clicked.connect(self.pick_file)
        self.btn_upload.clicked.connect(self.toggle_upload)
        self.btn_text.clicked.connect(self.send_text)
        self.recent.currentIndexChanged.connect(self._on_recent)
        self.rotation.currentIndexChanged.connect(lambda _i: self._render())
        self.refresh_recent()

    @staticmethod
    def _muted(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        return label

    # -- 素材库 ----------------------------------------------------------- #
    def refresh_recent(self) -> None:
        ledger = History(Path(self._ctx.root) / "recent_files.json")
        self.recent.blockSignals(True)
        self.recent.clear()
        self.recent.addItem("最近使用…", "")
        for item in ledger.prune_missing():
            self.recent.addItem(f"{item.name} · {item.used_at}", item.path)
        self.recent.setCurrentIndex(0)
        self.recent.blockSignals(False)

    def _on_recent(self) -> None:
        path = str(self.recent.currentData() or "")
        if not path:
            return
        self.load_path(Path(path))
        self.recent.blockSignals(True)
        self.recent.setCurrentIndex(0)
        self.recent.blockSignals(False)

    # -- 文件 ------------------------------------------------------------- #
    def pick_file(self) -> None:
        from PySide6.QtWidgets import QFileDialog  # noqa: PLC0415

        path, _ = QFileDialog.getOpenFileName(
            self, "选择素材", "", "图像 (*.gif *.png *.jpg *.jpeg);;所有文件 (*.*)"
        )
        if path:
            self.load_path(Path(path))

    def load_path(self, path: Path) -> None:
        if not path.is_file():
            self.info.setText(f"文件不存在：{path}")
            return
        self._path = path
        self.info.setText(f"正在分析 {path.name} …")
        self._probe = _ProbeWorker(path)
        self._probe.done.connect(self._on_probe_done)
        self._probe.failed.connect(lambda text: self.info.setText(f"无法处理：{text}"))
        self._probe.start()

    def _on_probe_done(self, payload: dict) -> None:
        info = payload["info"]
        image = payload.get("source") or payload.get("image")
        self.info.setText(info.describe())
        if image is not None:
            self._image = image
            self._render()

    def _render(self) -> None:
        """按当前「旋转」选项重绘预览（横屏画布 + 机箱小屏）。"""
        if self._image is None:
            return
        from ..ui.panels.preview_panel import _to_pixmap  # noqa: PLC0415

        image = self._image
        if self.rotation.currentData():          # 选中「旋转180°」
            image = image.transpose(0) if False else image.rotate(180)
        self.canvas.set_image(_to_pixmap(image))
        self._update_portrait(image)

    def _update_portrait(self, image: object) -> None:
        """机箱小屏里显示竖装观感：把画面旋转 90°。"""
        from PySide6.QtGui import QTransform  # noqa: PLC0415

        from ..ui.panels.preview_panel import _to_pixmap  # noqa: PLC0415

        pixmap = _to_pixmap(image)
        if not pixmap.isNull():
            # 与旧界面竖屏预览一致：顺时针 90° 再水平镜像 == 逆时针 90°
            pixmap = pixmap.transformed(QTransform().rotate(-90))
        self._portrait = pixmap
        self.portrait_changed(self._portrait)

    # -- 上传 ------------------------------------------------------------- #
    def toggle_upload(self) -> None:
        if self._upload is not None and self._upload.isRunning():
            self._upload.stop()
            self.btn_upload.setText("上传到屏幕")
            return
        if self._path is None:
            self.pick_file()
            if self._path is None:
                return
        port = find_lcd_port() or "COM5"
        rotation = "none" if self.rotation.currentData() else "180"
        try:
            self._upload = _UploadWorker(
                self._ctx, self._path, port, rotation=rotation, size=(1024, 240)
            )
        except Exception as exc:  # noqa: BLE001
            self.note.setText(f"⚠️ 无法开始上传：{exc}")
            return
        self._upload.encoded.connect(
            lambda frames, size, quality: self.note.setText(
                f"编码完成：{frames} 帧 · {size // 1024} KB · q{quality}"
            )
        )
        self._upload.progress.connect(self._on_progress)
        self._upload.status.connect(lambda text: self.note.setText(text))
        self._upload.uploading.connect(self._on_uploaded)
        self._upload.failed.connect(lambda text: self.note.setText(f"⚠️ {text}"))
        self._upload.done.connect(lambda text: self.btn_upload.setText("上传到屏幕"))
        self._upload.start()
        self.btn_upload.setText("停止显示")

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.note.setText(f"进度 {done}/{total}")

    def _on_uploaded(self, name: str) -> None:
        self.note.setText(f"✅ {name} 已上传，屏幕已切换")
        if self._path is not None:
            History(Path(self._ctx.root) / "recent_files.json").add(self._path)
            self.refresh_recent()

    # -- 文字 ------------------------------------------------------------- #
    def send_text(self) -> None:
        encoding = encode_title(self.text_input.text())
        if not encoding.raw:
            self.note.setText("清洗后为空：只支持 A-Z 0-9 . 空格")
            return
        self.note.setText("正在接管串口并发送…")
        self._text_worker = _TextWorker(self._ctx, encoding.text)
        self._text_worker.ok.connect(lambda text: self.note.setText(f"✅ {text}"))
        self._text_worker.failed.connect(lambda text: self.note.setText(f"⚠️ {text}"))
        self._text_worker.start()


class SessionBar(QWidget):
    """左栏底部：会话信息。"""

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._start = time.monotonic()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)
        self.line1 = QLabel("")
        self.line1.setStyleSheet(f"color:{theme.MUTED}; font-size:10px;")
        self.line2 = QLabel("")
        self.line2.setStyleSheet(f"color:{theme.MUTED}; font-size:10px;")
        layout.addWidget(self.line1)
        layout.addWidget(self.line2)
        self.setStyleSheet(f"background:{theme.PANEL}; border:1px solid {theme.BORDER};")
        self._last: tuple[str, str] = ("", "")
        self.timer = QTimer(self)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def refresh(self) -> None:
        import os  # noqa: PLC0415

        admin = "管理员" if os.name == "nt" and _is_admin() else "普通用户"
        mode = "调试" if self._ctx.session.debug else "生产"
        features = len(self._ctx.registry.verified_ids()) if hasattr(self._ctx, "registry") else 0
        state = cached()
        free = f" · 可用 {describe_free(state.free_bytes)}" if state and state.free_bytes else ""
        uptime = int(time.monotonic() - self._start)
        first = f"{mode} · {admin} · 已验证功能 {features}{free}"
        second = f"运行 {uptime // 60:02d}:{uptime % 60:02d}"
        if first != self._last[0]:           # 只在内容变化时重绘
            self.line1.setText(first)
        if second != self._last[1]:
            self.line2.setText(second)
        self._last = (first, second)


def _is_admin() -> bool:
    try:
        import ctypes  # noqa: PLC0415

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


class NewMainWindow(QMainWindow):
    """新界面主窗口。"""

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self._prefs = load_prefs(ctx.root)
        self._force_quit = False
        self._tray: QSystemTrayIcon | None = None
        self._debug_dialog: QDialog | None = None
        self._portrait_dialog: QDialog | None = None
        self._portrait_label = None
        self._tray_hint = False

        self.link = SerialLink(ctx, self)
        self.setWindowTitle("火神智屏 · VULCAN SCREEN")
        self.resize(1480, 900)
        self.setStyleSheet(theme.STYLE_SHEET)

        self._build_ui()
        self._build_menu()
        self._setup_tray()

        self._active = True
        self._last_refresh_at = 0.0
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._tick)
        self._clock.start()
        self._tick()
        load_state(Path(ctx.root) / "device_state.json")

    # -- 构建 ------------------------------------------------------------- #
    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_topbar())

        body = QHBoxLayout()
        body.setContentsMargins(14, 12, 14, 10)
        body.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(12)
        self.link_card = LinkCard(self._ctx, self.link)
        self.telemetry = TelemetryCard(self._ctx)
        self.playlist = PlaylistCard(self._ctx)
        left.addWidget(self.link_card)
        left.addWidget(self.telemetry)
        left.addWidget(self.playlist, 1)
        left.addWidget(SessionBar(self._ctx))
        left_wrap = QWidget()
        left_wrap.setLayout(left)
        left_wrap.setFixedWidth(330)
        body.addWidget(left_wrap)

        self.case = CaseView(ASSETS / "case_bg.png", LCD_RECT)
        self.case.setToolTip("点击放大竖屏预览")
        self.case.clicked.connect(self._show_portrait)
        body.addWidget(self.case, 1)

        right = QVBoxLayout()
        right.setSpacing(12)
        self.feed = FeedCard(self._ctx, self.link)
        self.feed.portrait_changed = self.case.set_preview
        self.settings = SettingsCard(self._ctx)
        self.debug = DebugCard(self._ctx)
        right.addWidget(self.feed, 3)
        right.addWidget(self.settings)
        right.addWidget(self.debug, 2)
        right_wrap = QWidget()
        right_wrap.setLayout(right)
        right_wrap.setFixedWidth(420)
        body.addWidget(right_wrap)

        body_wrap = QWidget()
        body_wrap.setLayout(body)
        outer.addWidget(body_wrap, 1)
        outer.addWidget(self._build_bottombar())
        self.setCentralWidget(central)

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setProperty("role", "topbar")
        bar.setStyleSheet(
            f"QFrame[role='topbar'] {{ background:{theme.BG};"
            f" border-bottom:1px solid {theme.BORDER}; }}"
        )
        bar.setFixedHeight(64)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 6, 18, 6)
        layout.setSpacing(18)

        logo = QLabel("◆")
        logo.setStyleSheet(f"color:{theme.ACCENT}; font-size:22px;")
        layout.addWidget(logo)

        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)
        brand = QLabel("火神智屏")
        brand.setProperty("role", "brand")
        brand_box.addWidget(brand)
        sub = QLabel("VULCAN SCREEN / CASE 05")
        sub.setStyleSheet(f"color:{theme.MUTED}; font-size:9px; letter-spacing:2px;")
        brand_box.addWidget(sub)
        layout.addLayout(brand_box)
        layout.addSpacing(20)

        self.nav_buttons: list[AccentButton] = []
        for name in ("控制台", "播放列表", "硬件监控", "调试"):
            btn = AccentButton(name, variant="nav")
            btn.setProperty("active", name == "控制台")
            btn.setMinimumWidth(76)
            btn.setFixedHeight(40)
            btn.clicked.connect(lambda _=False, n=name: self._focus_card(n))
            layout.addWidget(btn)
            self.nav_buttons.append(btn)

        layout.addStretch(1)

        self.port_dot = Dot(theme.WARN)
        layout.addWidget(self.port_dot)
        self.port_label = QLabel("检测中…")
        self.port_label.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        layout.addWidget(self.port_label)
        layout.addSpacing(16)
        self.clock = QLabel("--:--:--")
        self.clock.setStyleSheet(f"color:{theme.TEXT}; font-size:13px;")
        layout.addWidget(self.clock)
        return bar

    def _build_bottombar(self) -> QWidget:
        bar = QFrame()
        bar.setProperty("role", "bottombar")
        bar.setFixedHeight(30)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 16, 0)
        self.hint = QLabel("CASE BUS · 拖动/点击部件进入对应功能")
        self.hint.setStyleSheet(f"color:{theme.MUTED}; font-size:10px;")
        layout.addWidget(self.hint)
        layout.addStretch(1)
        version = QLabel(f"VULCAN SCREEN · BUILD {APP_VERSION}")
        version.setStyleSheet(f"color:{theme.MUTED}; font-size:10px;")
        layout.addWidget(version)
        return bar

    # -- 菜单 ------------------------------------------------------------- #
    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("文件(&F)")

        act_clean = QAction("清理设备缓存…", self)
        act_clean.triggered.connect(self._clean_cache)
        file_menu.addAction(act_clean)

        act_export = QAction("导出调试报告…", self)
        act_export.triggered.connect(self._export_report)
        file_menu.addAction(act_export)
        file_menu.addSeparator()

        self.act_close_to_tray = QAction("关闭窗口时最小化到托盘", self)
        self.act_close_to_tray.setCheckable(True)
        self.act_close_to_tray.setChecked(bool(self._prefs.get(CLOSE_TO_TRAY, True)))
        self.act_close_to_tray.toggled.connect(self._on_close_to_tray)
        file_menu.addAction(self.act_close_to_tray)

        self.act_standalone = QAction("独立模式（不管理官方服务）", self)
        self.act_standalone.setCheckable(True)
        self.act_standalone.setChecked(bool(self._prefs.get(STANDALONE, False)))
        self.act_standalone.setToolTip(
            "适合没装或不用 iGame Center 的机器：勾选后本工具不查、不停、不启官方服务"
        )
        self.act_standalone.toggled.connect(self._on_standalone)
        file_menu.addAction(self.act_standalone)
        file_menu.addSeparator()

        self.act_autostart = QAction("开机自启动", self)
        self.act_autostart.setCheckable(True)
        self.act_autostart.setChecked(autostart_enabled())
        self.act_autostart.toggled.connect(self._on_autostart)
        file_menu.addAction(self.act_autostart)
        file_menu.addSeparator()

        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self.quit_app)
        file_menu.addAction(act_quit)

        help_menu = self.menuBar().addMenu("帮助(&H)")
        act_disclaimer = QAction("免责声明与使用说明…", self)
        act_disclaimer.triggered.connect(self._show_disclaimer)
        help_menu.addAction(act_disclaimer)
        help_menu.addSeparator()
        from ..meta import PROJECT_URL  # noqa: PLC0415

        act_home = QAction("项目主页（GitHub）", self)
        act_home.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(PROJECT_URL))
        )
        help_menu.addAction(act_home)
        help_menu.addSeparator()

        act_about = QAction("关于", self)
        act_about.triggered.connect(self._about)
        help_menu.addAction(act_about)

    # -- 顶部/底部刷新 ---------------------------------------------------- #
    # -- 可见性：隐藏到托盘就休眠 ----------------------------------------- #
    def _set_active(self, active: bool) -> None:
        """窗口可见性变化时启停各面板轮询（隐藏后几乎不耗 CPU）。"""
        if active == self._active:
            return
        self._active = active
        for panel in (self.telemetry, self.debug):
            try:
                panel.set_active(active)
            except Exception:  # noqa: BLE001
                pass
        if active:
            self._tick()
        else:
            # 隐藏后只剩托盘：连时钟都不用刷
            self._clock.stop()

    def showEvent(self, event: object) -> None:  # noqa: N802
        if not self._clock.isActive():
            self._clock.start()
        self._set_active(True)
        super().showEvent(event)  # type: ignore[arg-type]

    def hideEvent(self, event: object) -> None:  # noqa: N802
        self._set_active(False)
        _trim_working_set()
        super().hideEvent(event)  # type: ignore[arg-type]

    def changeEvent(self, event: object) -> None:  # noqa: N802
        try:
            from PySide6.QtCore import QEvent  # noqa: PLC0415

            if event.type() == QEvent.Type.WindowStateChange:  # type: ignore[attr-defined]
                self._set_active(not self.isMinimized() and self.isVisible())
        except Exception:  # noqa: BLE001
            pass
        super().changeEvent(event)  # type: ignore[arg-type]

    def _tick(self) -> None:
        now = time.monotonic()
        # 串口枚举有开销，10 秒扫一次足够（点「扫描」可强制刷新）
        if now - getattr(self, "_port_at", 0.0) > 10.0:
            self._port_at = now
            self._port_cached = find_lcd_port()
        port = getattr(self, "_port_cached", None)
        if port:
            self.port_dot.set_color(theme.OK)
            self.port_label.setText(f"{port} 已连接" if self.link.is_open else f"{port} 就绪")
        else:
            self.port_dot.set_color(theme.BAD)
            self.port_label.setText("未检测到设备")
        self.clock.setText(time.strftime("%H:%M:%S"))
        if now - self._last_refresh_at > 5.0:     # 卡片信息 5 秒刷一次
            self._last_refresh_at = now
            try:
                self.link_card.refresh()
            except Exception:  # noqa: BLE001
                pass

    def _show_portrait(self) -> None:
        """放大显示机箱小屏里的竖屏预览。"""
        pixmap = self.feed._portrait
        if pixmap is None or pixmap.isNull():
            return
        if self._portrait_dialog is None:
            dialog = QDialog(self)
            dialog.setWindowTitle("竖屏预览")
            dialog.setStyleSheet(theme.STYLE_SHEET)
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(10, 10, 10, 10)
            label = QLabel()
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
            dialog.resize(320, 720)
            self._portrait_dialog = dialog
            self._portrait_label = label
        self._portrait_label.setPixmap(
            pixmap.scaled(
                280,
                660,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self._portrait_dialog.show()
        self._portrait_dialog.raise_()
        self._portrait_dialog.activateWindow()

    def _focus_card(self, name: str) -> None:
        cards = {
            "控制台": self.feed,
            "播放列表": self.playlist,
            "硬件监控": self.telemetry,
            "调试": self.debug,
        }
        card = cards.get(name)
        if card is None:
            return
        for other in {self.feed, self.playlist, self.telemetry, self.debug}:
            other.setStyleSheet("")
        card.setStyleSheet(f"QFrame[role='panel'] {{ border: 1px solid {theme.ACCENT}; }}")
        self.hint.setText(f"已定位：{name}")
        for btn in self.nav_buttons:
            btn.setProperty("active", btn.text() == name)
            btn.update()

    # -- 菜单动作 --------------------------------------------------------- #
    def _clean_cache(self) -> None:
        from ..ui.panels.preview_panel import _CleanWorker  # noqa: PLC0415

        box = QMessageBox(self)
        box.setWindowTitle("清理设备缓存")
        box.setText("要如何清理？")
        box.setInformativeText(
            "只删本工具上传的：安全。\n彻底清理：与官方垃圾桶一致，删 img2 及以后，回收空间。"
        )
        safe = box.addButton("只删本工具上传的", QMessageBox.ButtonRole.AcceptRole)
        deep = box.addButton("彻底清理", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is safe:
            mode = False
        elif box.clickedButton() is deep:
            mode = True
        else:
            return
        port = find_lcd_port() or "COM5"
        self._cleaner = _CleanWorker(self._ctx, port, self, deep=mode)
        self._cleaner.finished_report.connect(lambda text: self.debug.note(text))
        self._cleaner.failed.connect(lambda text: self.debug.note(f"⚠️ {text}"))
        self._cleaner.start()

    def _export_report(self) -> None:
        from ..ui.panels.debug_panel import DebugPanel  # noqa: PLC0415

        self.debug.note("导出报告请在调试面板中操作")
        try:
            DebugPanel.export_report(self.debug)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001 - 调试面板需要完整上下文
            pass

    def _on_close_to_tray(self, checked: bool) -> None:
        self._prefs[CLOSE_TO_TRAY] = bool(checked)
        save_prefs(self._ctx.root, self._prefs)

    def _on_standalone(self, checked: bool) -> None:
        """独立模式：完全不管官方服务。"""
        self._prefs[STANDALONE] = bool(checked)
        save_prefs(self._ctx.root, self._prefs)
        set_standalone(bool(checked))
        try:
            self.link_card.refresh()
        except Exception:  # noqa: BLE001
            pass
        if checked:
            self.hint.setText("独立模式：不会停止/启动官方服务（请确保串口空闲）")
        else:
            self.hint.setText("已恢复：接管时会自动停止官方服务")

    def _on_autostart(self, checked: bool) -> None:
        ok = autostart_enable() if checked else autostart_disable()
        if not ok:
            self.act_autostart.blockSignals(True)
            self.act_autostart.setChecked(not checked)
            self.act_autostart.blockSignals(False)
            QMessageBox.warning(self, "开机自启动", "写入注册表失败（可能被安全软件拦截）。")

    def _show_disclaimer(self) -> None:
        """重新查看免责声明（不再倒计时）。"""
        from .disclaimer import DisclaimerDialog  # noqa: PLC0415

        dialog = DisclaimerDialog(self, seconds=0, root=self._ctx.root)
        dialog.exec()

    def _about(self) -> None:
        """关于窗口：作者署名、许可证、目录说明。"""
        from .about import AboutDialog  # noqa: PLC0415

        dialog = AboutDialog(self, install_dir=self._ctx.root)
        dialog.exec()

    # -- 托盘 ------------------------------------------------------------- #
    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return
        icon = self._make_icon()
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("火神智屏图传工具")
        menu = self._tray.contextMenu()
        if menu is None:
            from PySide6.QtWidgets import QMenu  # noqa: PLC0415

            menu = QMenu()
            self._tray.setContextMenu(menu)
        act_show = menu.addAction("显示主窗口")
        act_show.triggered.connect(self.show_from_tray)
        menu.addSeparator()
        act_quit = menu.addAction("退出")
        act_quit.triggered.connect(self.quit_app)
        self._tray.activated.connect(
            lambda reason: self.show_from_tray()
            if reason == QSystemTrayIcon.ActivationReason.Trigger
            else None
        )
        self._tray.show()

    @staticmethod
    def _make_icon() -> QIcon:
        pix = QPixmap(64, 64)
        pix.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QColor(theme.ACCENT))
        painter.setPen(QColor(theme.ACCENT))
        painter.drawRoundedRect(4, 4, 56, 56, 12, 12)
        painter.setPen(QColor("#0a0a0a"))
        font = QFont("Microsoft YaHei UI")
        font.setBold(True)
        font.setPixelSize(34)
        painter.setFont(font)
        painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "V")
        painter.end()
        return QIcon(pix)

    def show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        self._force_quit = True
        self.close()

    # -- 关闭 ------------------------------------------------------------- #
    def closeEvent(self, event: object) -> None:  # noqa: N802
        if not self._force_quit and self._prefs.get(CLOSE_TO_TRAY, True) and self._tray:
            event.ignore()  # type: ignore[attr-defined]
            self.hide()
            if not self._tray_hint:
                self._tray_hint = True
                self._tray.showMessage(
                    "火神智屏图传工具",
                    "已最小化到托盘，双击图标可重新打开。",
                    QSystemTrayIcon.MessageIcon.Information,
                    4000,
                )
            return
        if self._tray is not None:
            self._tray.hide()
            self._tray = None
        try:
            if self.link.is_open:
                self.link.close()
            self.telemetry.timer.stop()
            self.debug.timer.stop()
            self._clock.stop()
        except Exception:  # noqa: BLE001
            pass
        self._ctx.logger.info("window_closed", result="ok")
        super().closeEvent(event)  # type: ignore[arg-type]
