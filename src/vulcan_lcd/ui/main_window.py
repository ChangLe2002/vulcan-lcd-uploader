# SPDX-License-Identifier: MIT
"""主窗口：把各面板拼起来，并统一处理跨面板的关注点（收发显示、状态栏、退出清理）。

布局思路：左侧是"主流程"（连接 → 文字投屏 → 图像预览），右侧是"三个工具"
（播放列表 / 监控 / 调试）。这样用户从上到下就能走完一次完整操作，
而调试用的东西不会挤在主流程里。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QSystemTrayIcon,
    QMenu,

    QMainWindow,
    QDialog,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..app import AppContext
from .link import SerialLink
from .panels.debug_panel import DebugPanel
from .panels.monitor_panel import MonitorPanel
from .panels.playlist_panel import PlaylistPanel
from .panels.settings_panel import SettingsPanel
from ..features.autostart import disable as autostart_disable
from ..features.autostart import enable as autostart_enable
from ..features.autostart import is_enabled as autostart_enabled
from ..features.ui_prefs import CLOSE_TO_TRAY, load_prefs, save_prefs
from .panels.preview_panel import PreviewPanel
from .port_status import PortStatusBar
from .panels.title_panel import TitlePanel

__all__ = ["MainWindow"]


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext, *, admin: bool = False) -> None:
        super().__init__()
        self._ctx = ctx
        self._admin = admin

        self.setWindowTitle("火神智屏图传工具 —— 未连接")
        self.resize(1180, 760)

        self.link = SerialLink(ctx, self)
        self._prefs = load_prefs(ctx.root)
        self._force_quit = False
        self._tray_hint_shown = False
        self._tray: QSystemTrayIcon | None = None
        self._debug_dialog = None
        self._build_ui()
        self._setup_tray()
        self._build_menu()
        self._wire()
        self._update_status()

    # -- 构建 ------------------------------------------------------------- #
    def _build_ui(self) -> None:
        # 注意：不要在样式里写 font-size/font-family。
        # Qt 用样式设置字体时会丢掉字体族，回退到系统默认（本机是衬线体，
        # 数字会渲染成 l/O 这种怪字形）。字号交给 QApplication.setFont()。
        self.setStyleSheet(
            "QSpinBox { min-width: 72px; padding: 2px 4px; }"
            "QDoubleSpinBox { min-width: 72px; padding: 2px 4px; }"
        )
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(8)

        self.title = TitlePanel(self._ctx, self.link)
        self.preview = PreviewPanel(self._ctx)
        # 上传需要独占串口：开始前先断开连接面板的占用
        self.preview.before_upload = self._release_port
        left_layout.addWidget(self.title)
        left_layout.addWidget(self.preview, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(left)

        self.tabs = QTabWidget()
        self.playlist = PlaylistPanel(self._ctx)
        self.monitor = MonitorPanel(self._ctx)
        self.settings = SettingsPanel(self._ctx)
        self.debug = DebugPanel(self._ctx, self.link)
        self.tabs.addTab(self.playlist, "播放列表")
        self.tabs.addTab(self.monitor, "硬件监控")
        self.tabs.addTab(self.settings, "设备设置")

        splitter.addWidget(scroll)
        splitter.addWidget(self.tabs)

        # 状态条放在窗口顶部整行：分栏里会被裁切，放这里永远完整可见
        self.port_status = PortStatusBar(self._ctx, self.link)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        container_layout.addWidget(self.port_status)
        container_layout.addWidget(splitter, 1)
        # 左右均衡：左栏（上传/投屏）内容更宽，右栏（标签页）够用即可
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        # 右栏内容（监控页）最小宽度较大，这里允许压缩，保证左右均衡
        self.tabs.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        for index in range(self.tabs.count()):
            page = self.tabs.widget(index)
            page.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            page.setMinimumWidth(0)
        splitter.setSizes([600, 560])
        scroll.setMinimumWidth(400)
        self.setCentralWidget(container)

        # 调试面板默认不抢焦点，生产模式下也不该成为主视图
        if not self._ctx.session.debug:
            self.tabs.setCurrentWidget(self.playlist)


    def show_debug_panel(self) -> None:
        """在独立窗口里打开调试面板（原「调试」标签页）。"""
        if self._debug_dialog is None:
            dialog = QDialog(self)
            dialog.setWindowTitle("调试面板")
            dialog.resize(640, 720)
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.addWidget(self.debug)
            self._debug_dialog = dialog
        self._debug_dialog.show()
        self._debug_dialog.raise_()
        self._debug_dialog.activateWindow()

    def _release_port(self) -> None:
        """上传前释放串口（连接面板若已打开）。"""
        if self.link.is_open:
            self.link.close()
            self._ctx.logger.info("port_released_for_upload", feature_id="gif_upload")


    # -- 托盘与退出策略 --------------------------------------------------- #
    def _setup_tray(self) -> None:
        """创建托盘图标（系统不支持时静默跳过）。"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return

        icon = self._make_tray_icon()
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("火神智屏图传工具")
        menu = QMenu()
        act_show = menu.addAction("显示主窗口")
        act_show.triggered.connect(self.show_from_tray)
        menu.addSeparator()
        act_quit = menu.addAction("退出")
        act_quit.triggered.connect(self.quit_app)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(
            lambda reason: self.show_from_tray()
            if reason == QSystemTrayIcon.ActivationReason.Trigger
            else None
        )
        self._tray.show()

    @staticmethod
    def _make_tray_icon() -> QIcon:
        """没有图标资源，运行时画一个（深蓝底 + V）。"""
        pix = QPixmap(64, 64)
        pix.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QColor(30, 90, 200))
        painter.setPen(QColor(15, 45, 100))
        painter.drawRoundedRect(2, 2, 60, 60, 14, 14)
        painter.setPen(QColor(255, 255, 255))
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(38)
        painter.setFont(font)
        painter.drawText(pix.rect(), 0x84, "V")  # AlignCenter
        painter.end()
        return QIcon(pix)

    def show_from_tray(self) -> None:
        """从托盘恢复窗口。"""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        """真正退出（托盘菜单/文件菜单用）。"""
        self._force_quit = True
        self.close()

    def _on_autostart_toggled(self, checked: bool) -> None:
        ok = autostart_enable() if checked else autostart_disable()
        if not ok:
            # 写注册表失败：把勾选状态还原，别让界面骗人
            self.act_autostart.blockSignals(True)
            self.act_autostart.setChecked(not checked)
            self.act_autostart.blockSignals(False)
            QMessageBox.warning(self, "开机自启动", "写入注册表失败（可能被安全软件拦截）。")
        else:
            self._ctx.logger.info(
                "autostart", result="ok", detail="enabled" if checked else "disabled"
            )

    def _on_close_to_tray_toggled(self, checked: bool) -> None:
        self._prefs[CLOSE_TO_TRAY] = bool(checked)
        save_prefs(self._ctx.root, self._prefs)

    def _close_to_tray(self) -> bool:
        return bool(self._prefs.get(CLOSE_TO_TRAY, True)) and self._tray is not None

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("文件(&F)")
        act_export = QAction("导出调试报告…", self)
        act_export.triggered.connect(self.debug.export_report)
        self.act_close_to_tray = QAction("关闭窗口时最小化到托盘", self)
        self.act_close_to_tray.setCheckable(True)
        self.act_close_to_tray.setChecked(bool(self._prefs.get(CLOSE_TO_TRAY, True)))
        self.act_close_to_tray.toggled.connect(self._on_close_to_tray_toggled)
        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self.quit_app)
        file_menu.addAction(act_export)
        file_menu.addSeparator()
        file_menu.addAction(self.act_close_to_tray)
        self.act_autostart = QAction("开机自启动", self)
        self.act_autostart.setCheckable(True)
        self.act_autostart.setChecked(autostart_enabled())
        self.act_autostart.toggled.connect(self._on_autostart_toggled)
        self.act_autostart.setToolTip("登录 Windows 后自动启动本工具（当前用户级，不需要管理员）")
        file_menu.addAction(self.act_autostart)
        file_menu.addSeparator()
        file_menu.addAction(act_quit)

        help_menu = self.menuBar().addMenu("帮助(&H)")
        act_debug_panel = QAction("调试面板…", self)
        act_debug_panel.triggered.connect(self.show_debug_panel)
        help_menu.addAction(act_debug_panel)
        help_menu.addSeparator()
        act_about = QAction("关于", self)
        act_about.triggered.connect(self.show_about)
        help_menu.addAction(act_about)

    def _wire(self) -> None:
        self.link.opened.connect(self._on_opened)
        self.link.closed.connect(self._on_closed)
        self.link.failed.connect(self._on_failed)
        self.link.sent.connect(self._on_sent)
        self.link.received.connect(self._on_received)

    # -- 状态 ------------------------------------------------------------- #
    def _teardown_tray(self) -> None:
        if self._tray is not None:
            self._tray.hide()
            self._tray = None

    def _update_status(self) -> None:
        session = self._ctx.session
        mode = "调试" if session.debug else "生产"
        if session.dry_run:
            mode += " · dry-run"
        admin = "管理员" if self._admin else "⚠️ 非管理员"
        venv = "venv" if self._ctx.root else ""
        self.statusBar().showMessage(
            f"{mode} · {admin} · {venv} · 可写功能 {len(self._ctx.gate.writable())}/{len(self._ctx.registry)}"
        )

    def _on_opened(self, port: str) -> None:
        self.setWindowTitle(f"火神智屏图传工具 —— {port}")
        self.statusBar().showMessage(f"已连接 {port}")

    def _on_closed(self) -> None:
        self.setWindowTitle("火神智屏图传工具 —— 未连接")
        self._update_status()

    def _on_failed(self, message: str) -> None:
        self.statusBar().showMessage(f"错误：{message}", 8000)
        self.debug.hex.append_text(f"[error] {message}")

    def _on_sent(self, action: str, payload: bytes) -> None:
        self.debug.hex.append_hex(f"tx:{action}", payload)

    def _on_received(self, payload: bytes) -> None:
        self.debug.hex.append_hex("rx", payload)

    # -- 关于 / 关闭 ------------------------------------------------------ #
    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "关于",
            "火神智屏图传工具（非官方）\n\n"
            "为七彩虹 iGame RTX 50 系火神显卡的 800×216 智屏提供自定义显示。\n"
            "协议事实来自公开分析，未公开部分一律标记为 experimental 且默认只读。\n\n"
            f"日志目录：{self._ctx.log_dir}",
        )

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt 约定
        if not self._force_quit and self._close_to_tray():
            event.ignore()  # type: ignore[attr-defined]
            self.hide()
            if not self._tray_hint_shown and self._tray is not None:
                self._tray_hint_shown = True
                self._tray.showMessage(
                    "火神智屏图传工具",
                    "已最小化到托盘，双击图标可重新打开；退出请右键托盘图标。",
                    QSystemTrayIcon.MessageIcon.Information,
                    4000,
                )
            self._ctx.logger.info("window_hidden_to_tray", result="ok")
            return

        self._teardown_tray()
        try:
            self.monitor.shutdown()
            # 关串口 + 恢复官方服务，顺序不能反
            if self.link.is_open:
                self.link.close()
            self._ctx.logger.info("window_closed", result="ok")
        except Exception as exc:  # noqa: BLE001 - 关闭失败不应阻塞退出
            print(f"cleanup error: {exc}")
        super().closeEvent(event)  # type: ignore[arg-type]
