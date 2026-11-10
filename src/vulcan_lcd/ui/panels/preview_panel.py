# SPDX-License-Identifier: MIT
"""预览面板：横屏（实际上传）+ 竖屏（立装模拟）双视图。

排版说明
--------
* 两张画布放在同一个"预览区"卡片里，视觉上是一组而不是两个孤立方块；
* 卡片用浅色（与整体界面一致），不用深色块——深色在浅色界面里太突兀；
* 横屏画布随宽度自适应，竖屏画布保持真实比例（216:800），**点击可放大**；
* 竖装方向下拉放在竖屏画布正下方——它只影响竖屏，放中间会让人以为也影响上传；
* 上传内容始终是 1024×240（实测值），旋转只发生在本机预览，不进入发送链路。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QThread, Signal
from PIL import Image, ImageOps

from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...app import AppContext
from ...core.port_scanner import find_lcd_port
from ...core.transport import SerialSettings, Transport
from ...features.screen_session import run_cache_clean, run_screen_session
from ...features.device_state import DeviceState, remember
from ...features.history import History as UploadHistory
from ...features.device_settings import read_settings
from ...features.gif_upload import query_free_space
from ...features.upload_ledger import UploadLedger
from ...media.encode import EncodeError, encode_media_to_pak

from ...media.preprocess import (
    FIT_NATIVE,
    PreprocessError,
    fit_to_screen,
    flatten_alpha,
    prepare_image,
    rotate_image,
)
from ...system.service_control import ServiceController
from ...media.probe import MediaError, probe_media
from ..widgets import Section

__all__ = ["PreviewPanel"]

_PORTRAIT_SIZE = (86, 214)
_LANDSCAPE_MIN_H = 132
_LANDSCAPE_MAX_H = 150

_CARD_BG = "#ffffff"
_CARD_BORDER = "#dfe5ec"
_CANVAS_BG = "#f4f7fa"
_CANVAS_BORDER = "#e3e9ef"
_MUTED = "#6b7a88"

#: 单包容量上限（实测 8.5 MB 仍可正常播放，留出余量取 10 MB）
SAFE_PAK_BYTES = 4_000_000
#: 每帧的保守估算值（1024x240 JPEG 通常 8–32 KB）
EST_FRAME_BYTES = 16_000
#: 设备固定播放帧率——时长由帧数决定，编码时按此重采样
DEVICE_FPS = 30


class _Canvas(QLabel):
    """等比自适应画布：随控件尺寸缩放、居中显示、浅色卡片底。"""

    clicked = Signal()

    def __init__(self, placeholder: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._placeholder = placeholder
        self._source: QPixmap | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText(placeholder)
        self.setWordWrap(True)
        self.setStyleSheet(
            f"QLabel {{ background:{_CANVAS_BG}; color:{_MUTED};"
            f" border:1px solid {_CANVAS_BORDER}; border-radius:8px;"
            " padding:6px; font-size:12px; }"
        )

    def set_image(self, pixmap: QPixmap | None) -> None:
        self._source = pixmap
        if pixmap is None:
            self.setPixmap(QPixmap())
            self.setText(self._placeholder)
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setText("")
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self._rescale()

    def _rescale(self) -> None:
        if self._source is None or self._source.isNull():
            return
        area = self.contentsRect().adjusted(8, 8, -8, -8).size()
        if area.width() <= 0 or area.height() <= 0:
            return
        self.setPixmap(
            self._source.scaled(
                area,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event: object) -> None:  # noqa: N802 - Qt 约定
        super().resizeEvent(event)  # type: ignore[arg-type]
        self._rescale()

    def mousePressEvent(self, event: object) -> None:  # noqa: N802 - Qt 约定
        if self._source is not None:
            self.clicked.emit()
        super().mousePressEvent(event)  # type: ignore[arg-type]


class _PortraitDialog(QDialog):
    """竖屏放大浮层：只用于观察，不提供任何发送操作。"""

    def __init__(self, pixmap: QPixmap, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("竖装预览（放大）")
        self.setModal(True)
        self.resize(280, 760)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._canvas = _Canvas("无预览")
        self._canvas.setMinimumSize(240, 690)
        layout.addWidget(self._canvas, 1)

        note = QLabel(f"{caption}\n仅预览，不影响上传内容（800×216）")
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        note.setStyleSheet(f"color:{_MUTED}; font-size:11px;")
        layout.addWidget(note)

        close_btn = QPushButton("关闭")
        close_btn.setFixedWidth(96)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        self.set_image(pixmap)

    def set_image(self, pixmap: QPixmap) -> None:
        self._canvas.set_image(pixmap)


class _ProbeWorker(QThread):
    """后台完成"校验 + 首帧预处理"。"""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path

    def run(self) -> None:  # noqa: D102 - QThread 约定
        try:
            info = probe_media(self._path)
            from PIL import Image  # noqa: PLC0415

            with Image.open(self._path) as im:
                im.seek(0)
                raw = flatten_alpha(im.copy())
                frame = prepare_image(im.copy())
            self.done.emit({"info": info, "image": frame, "source": raw})
        except (MediaError, PreprocessError) as exc:
            message = exc.user_message() if hasattr(exc, "user_message") else str(exc)
            self.failed.emit(f"{exc.error_code}: {message}")
        except Exception as exc:  # noqa: BLE001 - 后台线程不能把异常抛到无人接管的地方
            self.failed.emit(f"UNKNOWN: {exc}")


def _to_pixmap(image: object) -> QPixmap:
    rgb = image.convert("RGB")  # type: ignore[attr-defined]
    data = rgb.tobytes("raw", "RGB")
    qimg = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


def _caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"color:{_MUTED}; font-size:11px; letter-spacing:0.5px;")
    return label


class _CleanWorker(QThread):
    """后台执行「清理设备缓存」：停服务 → 开串口 → 逐个删除 → 恢复服务。"""

    finished_report = Signal(str)      # 人类可读结果
    failed = Signal(str)

    def __init__(
        self, ctx: AppContext, port: str, parent: object = None, *, deep: bool = False
    ) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._ctx = ctx
        self._port = port
        self._deep = deep

    def run(self) -> None:  # noqa: D102 - QThread 约定
        from ...features.screen_session import run_cache_clean

        try:
            ledger = UploadLedger(Path(self._ctx.root) / "uploaded_files.json")
            report = run_cache_clean(
                controller=ServiceController(self._ctx.service_name),
                transport=Transport(self._port, SerialSettings()),
                ledger=ledger,
                deep=self._deep,
            )
            if report.error:
                self.failed.emit(report.error)
            else:
                self.finished_report.emit(report.describe())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class _UploadWorker(QThread):
    """后台完成"编码 → 接管 → 上传 → 持续显示"。

    生命周期：``start()`` 后先编码（可能几秒），再接管屏幕并循环发送显示指令，
    直到 :meth:`stop` 被调用或发生错误。线程内不碰任何 Qt 控件。
    """

    progress = Signal(int, int)      # (已处理, 总数)：编码阶段为帧，上传阶段为块
    status = Signal(str)             # 阶段性文字（含上传剩余时间预估）
    encoded = Signal(int, int, int)  # (帧数, pak 字节, 平均质量)
    uploading = Signal(str)          # 目标文件名，表示文件已上传、屏幕已切换
    failed = Signal(str)
    done = Signal(str)               # 结束时的人话描述

    def __init__(
        self,
        ctx: AppContext,
        path: Path,
        port: str,
        *,
        rotation: str = "none",
        size: tuple[int, int] = (800, 216),
        parent: object = None,
    ) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._ctx = ctx
        self._path = path
        self._port = port
        self._rotation = rotation
        self._size = size
        self._stop = threading.Event()

    def _capture_state(self, transport: object) -> None:
        """上传会话还没关串口时，顺手把可用空间/固件读回来。"""
        free = query_free_space(transport)
        info = read_settings(transport)
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

    def stop(self) -> None:
        """请求结束显示并恢复官方服务。"""
        self._stop.set()

    def run(self) -> None:  # noqa: D102 - QThread 约定
        try:
            encoded = encode_media_to_pak(
                self._path,
                rotation=self._rotation,
                target_fps=30,         # 官方固定 fps=30（反编译证实）
                size=self._size,
                on_progress=lambda done, total: self.progress.emit(done, total),
            )
            self.encoded.emit(encoded.frames, encoded.size, encoded.quality)
            self._ctx.logger.info(
                "encode_ready",
                feature_id="gif_upload",
                frames=encoded.frames,
                bytes=encoded.size,
                quality=encoded.quality,
            )
            controller = ServiceController(self._ctx.service_name)
            transport = Transport(self._port, SerialSettings())
            ledger = UploadLedger(Path(self._ctx.root) / "uploaded_files.json")

            upload_started = time.monotonic()

            def on_block(done: int, total: int) -> None:
                self.progress.emit(done, total)
                if done <= 0 or total <= 0:
                    return
                elapsed = time.monotonic() - upload_started
                if done >= total:
                    self.status.emit(f"上传完成：共 {total} 块，用时 {elapsed:.0f} 秒")
                    return
                rate = elapsed / done
                eta = rate * (total - done)
                self.status.emit(
                    f"上传中 {done}/{total} 块（{done * 100 // total}%）"
                    f" · 剩余约 {eta:.0f} 秒"
                )

            report = run_screen_session(
                encoded.pak,
                controller=controller,
                transport=transport,
                stop_event=self._stop,
                on_progress=on_block,
                ledger=ledger,
                on_state=self._capture_state,
                on_uploaded=self.uploading.emit,
            )
            if report.error:
                self.failed.emit(report.error)
                self.done.emit("已恢复官方显示。")
            else:
                self.done.emit(report.describe())
        except EncodeError as exc:
            self.failed.emit(f"{exc.message} {exc.hint}".strip())
            self.done.emit("未发送任何数据。")
        except Exception as exc:  # noqa: BLE001 - 线程里任何异常都要报给用户
            self.failed.emit(str(exc))
            self.done.emit("已恢复官方显示。")


class PreviewPanel(Section):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__("② 图像预览与上传", parent)
        self._ctx = ctx
        self._worker: _ProbeWorker | None = None
        self._path: Path | None = None
        self._image: object | None = None
        self._portrait: QPixmap | None = None
        self._dialog: _PortraitDialog | None = None
        self._build()

    # -- 构建 ------------------------------------------------------------- #
    def _build(self) -> None:
        # 素材库单独一行，避免和按钮挤在一起被裁切
        recent_row = QHBoxLayout()
        recent_label = QLabel("素材库")
        recent_label.setStyleSheet(f"color:{_MUTED}; font-size:12px;")
        self.recent = QComboBox()
        self.recent.setToolTip("最近上传过的素材，选一个即可直接载入")
        self.recent.currentIndexChanged.connect(self._on_recent_selected)
        recent_row.addWidget(recent_label)
        recent_row.addWidget(self.recent, 1)
        self.body.addLayout(recent_row)
        self.refresh_history()

        actions = QHBoxLayout()
        self.btn_pick = QPushButton("选择 GIF / 图片…")
        self.btn_send = QPushButton("上传到屏幕")
        self.btn_clean = QPushButton("清理设备缓存")
        self.btn_clean.setToolTip(
            "清理设备上的无效缓存。可选：只删本工具上传过的（安全），"
            "或彻底清理（与官方垃圾桶一致，删除 img2 及以后全部文件）"
        )
        actions.addWidget(self.btn_pick)
        actions.addWidget(self.btn_send)
        actions.addWidget(self.btn_clean)
        actions.addStretch(1)
        self.body.addLayout(actions)

        fit_row = QHBoxLayout()
        fit_label = QLabel("屏幕适配")
        fit_label.setStyleSheet(f"color:{_MUTED}; font-size:12px;")
        self.fit_label = QLabel("原始尺寸")
        self.fit_label.setToolTip(
            "按素材原始像素打包；屏幕显示时会自动裁掉黑边并铺满整个屏（与官方一致）"
        )
        fit_row.addWidget(fit_label)
        fit_row.addWidget(self.fit_label, 1)
        fit_row.addSpacing(8)
        fit_row.addSpacing(10)
        flip_label = QLabel("画面旋转")
        flip_label.setStyleSheet(f"color:{_MUTED}; font-size:12px;")
        self.flip180 = QComboBox()
        self.flip180.addItem("不旋转", False)
        self.flip180.addItem("旋转 180°", True)
        self.flip180.setToolTip("把上传的动画内容整体转 180°，屏幕安装方向不受影响")
        fit_row.addWidget(flip_label)
        fit_row.addWidget(self.flip180)
        fit_row.addSpacing(10)
        fit_row.addStretch(1)
        self.body.addLayout(fit_row)

        self.info = QLabel("尚未选择文件。")
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color:#3f4b57; font-size:12px;")
        self.body.addWidget(self.info)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(4)
        self.body.addWidget(self.progress)

        self.body.addWidget(self._build_stage(), 0, Qt.AlignmentFlag.AlignTop)

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.body.addWidget(self.note)

        self._source: object | None = None
        self._target_size: tuple[int, int] = self._read_target_size()
        self._flip180: bool = False
        self._upload: _UploadWorker | None = None
        self._cleaner: _CleanWorker | None = None
        #: 上传前回调：由主窗口注入，用于先断开连接面板占用的串口
        self.before_upload: Callable[[], None] | None = None
        self.rotation.currentIndexChanged.connect(self._refresh_previews)
        self.flip180.currentIndexChanged.connect(self._on_flip_changed)
        self.btn_pick.clicked.connect(self.pick_file)
        self.btn_send.clicked.connect(self.send_upload)
        self.btn_clean.clicked.connect(self.clean_cache)
        self.rotation.currentIndexChanged.connect(self._refresh_previews)
        self._apply_gate()

    def _build_stage(self) -> QWidget:
        """预览区：浅色卡片，内含横屏 + 竖屏两张画布。

        样式表必须用 ``#objectName`` 精确命中：``QLabel`` 继承自 ``QFrame``，
        写 ``QFrame { border: ... }`` 会把标题、提示、按钮一起套上边框。
        """
        stage = QFrame()
        stage.setObjectName("previewStage")
        stage.setStyleSheet(
            f"#previewStage {{ background:{_CARD_BG}; border:1px solid {_CARD_BORDER};"
            " border-radius:10px; }"
        )
        outer = QVBoxLayout(stage)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        caps = QHBoxLayout()
        caps.addWidget(_caption("横屏 800×216 · 实际发送"), 4)
        caps.addSpacing(16)
        caps.addWidget(_caption("竖屏 216×800 · 立装观感"), 1)
        outer.addLayout(caps)

        row = QHBoxLayout()
        row.setSpacing(16)

        self.canvas_landscape = _Canvas("选择文件后显示\n横屏预览")
        self.canvas_landscape.setMinimumSize(320, _LANDSCAPE_MIN_H)
        self.canvas_landscape.setMaximumHeight(_LANDSCAPE_MAX_H)
        self.canvas_landscape.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        row.addWidget(self.canvas_landscape, 4)

        right = QVBoxLayout()
        right.setSpacing(4)
        self.canvas_portrait = _Canvas("竖装预览")
        self.canvas_portrait.setFixedSize(*_PORTRAIT_SIZE)
        self.canvas_portrait.setToolTip("点击放大查看")
        self.canvas_portrait.clicked.connect(self.open_portrait_dialog)
        right.addWidget(self.canvas_portrait, 0, Qt.AlignmentFlag.AlignHCenter)

        hint = QLabel("点击放大")
        hint.setStyleSheet(f"color:{_MUTED}; font-size:10px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        right.addWidget(hint, 0, Qt.AlignmentFlag.AlignHCenter)

        self.rotation = QComboBox()
        self.rotation.addItem("顺时针 90°", "cw")
        self.rotation.addItem("逆时针 90°", "ccw")
        self.rotation.setToolTip("仅改变右侧竖屏预览的观看方向，不影响上传内容")
        self.rotation.setFixedWidth(_PORTRAIT_SIZE[0] + 26)
        right.addWidget(self.rotation, 0, Qt.AlignmentFlag.AlignHCenter)
        right.addStretch(1)
        row.addLayout(right, 1)

        outer.addLayout(row)
        return stage

    # -- 权限 ------------------------------------------------------------- #
    def _apply_gate(self) -> None:
        allowed = self._ctx.feature_allowed("gif_upload")
        busy = self._upload is not None and self._upload.isRunning()
        self.btn_send.setEnabled(allowed or busy)
        self.btn_send.setText("停止显示（恢复官方）" if busy else "上传到屏幕")
        if busy:
            return
        if allowed:
            self.note.setText("")
            self.btn_send.setToolTip("")
            self.note.setStyleSheet(f"color:{_MUTED};")
        else:
            reason = self._ctx.blocked_reason("gif_upload")
            self.btn_send.setToolTip(reason)
            record = self._ctx.registry.get("gif_upload")
            short = f"{record.name}尚未验证" if record is not None else "协议未验证"
            self.note.setText(f"⚠️ 上传暂不可用：{short}，当前只能预览与校验（悬停按钮看详情）。")
            self.note.setStyleSheet("color:#8a6d00; font-size:12px;")

    # -- 目标分辨率 ------------------------------------------------------- #
    def _read_target_size(self) -> tuple[int, int]:
        """从配置读目标分辨率；设备原生尺寸可能不是 1024x240。"""
        media = self._ctx.config.get("media", {})
        width = int(media.get("target_width", 800))
        height = int(media.get("target_height", 216))
        if width <= 0 or height <= 0:
            return (800, 216)
        return (width, height)

    # -- 适配控件 --------------------------------------------------------- #
    def _rotation_value(self) -> str:
        return str(self.rotation.currentData() or "none")

    def _on_flip_changed(self) -> None:
        self._flip180 = bool(self.flip180.currentData())
        self._refresh_previews()

    # -- 预览渲染 --------------------------------------------------------- #
    def _refresh_previews(self) -> None:
        if self._image is None:
            self.canvas_landscape.set_image(None)
            self.canvas_portrait.set_image(None)
            self._portrait = None
            return

        source = self._source if self._source is not None else self._image

        # 横屏预览展示「设备最终看到的画面」。
        # 实测（2026-11-06 真机）：设备会把帧翻转 180°、裁掉黑边并铺满面板——
        # 官方帧同样带黑边，但屏幕上完全看不到黑边。所以这里直接显示填充效果，
        # 而不是照搬打包帧（照搬会误导成"有黑边、还是反的"）。
        shown = source.convert("RGB")
        if self._flip180:
            shown = shown.transpose(Image.ROTATE_180)
        mapped = shown.resize(self._target_size, Image.Resampling.LANCZOS)
        self.canvas_landscape.set_image(_to_pixmap(mapped))

        # 竖屏预览：把"实际发送的缓冲"旋转 90° 后再左右镜像，
        # 这样与立装后肉眼看到的方向一致。**不参与上传**。
        upright = rotate_image(mapped, clockwise=(self._rotation_value() == "cw"))
        mirrored = ImageOps.mirror(upright)
        self._portrait = _to_pixmap(mirrored)
        self.canvas_portrait.set_image(self._portrait)

        if self._dialog is not None and self._dialog.isVisible():
            self._dialog.set_image(self._portrait)

    def open_portrait_dialog(self) -> None:
        """点击竖屏画布放大查看。"""
        if self._portrait is None:
            return
        caption = self.rotation.currentText()
        if self._dialog is None:
            self._dialog = _PortraitDialog(self._portrait, caption, self)
        else:
            self._dialog.set_image(self._portrait)
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()

    # -- 选择文件 --------------------------------------------------------- #
    def pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择素材", "", "图像 (*.gif *.png *.jpg *.jpeg);;所有文件 (*.*)"
        )
        if not path:
            return
        self.load_path(Path(path))

    def load_path(self, path: Path) -> None:
        """载入指定素材（文件对话框与素材库共用）。"""
        if not path.is_file():
            self.info.setText(f"文件不存在：{path}")
            return
        self._path = path
        self.info.setText(f"正在分析 {path.name} …")
        self.progress.setRange(0, 0)

        self._worker = _ProbeWorker(self._path)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    # -- 素材库 ----------------------------------------------------------- #
    def refresh_history(self) -> None:
        """刷新「最近使用」下拉（顺手清掉已删除的文件）。"""
        combo = getattr(self, "recent", None)
        if combo is None:
            return
        ledger = UploadHistory(Path(self._ctx.root) / "recent_files.json")
        items = ledger.prune_missing()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("最近使用…", "")
        for item in items:
            label = f"{item.name}  ·  {item.used_at}" if item.used_at else item.name
            combo.addItem(label, item.path)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _on_recent_selected(self) -> None:
        combo = self.recent
        path = str(combo.currentData() or "")
        if not path:
            return
        self.load_path(Path(path))
        combo.blockSignals(True)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _on_worker_finished(self) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(1)

    def _on_done(self, payload: dict) -> None:
        info = payload["info"]
        self._image = payload["image"]
        self._source = payload.get("source")
        self.info.setText(info.describe())
        self._refresh_previews()

        expected_frames = max(
            info.frames_after_decimation,
            int(round(info.duration_ms / 1000 * 30)),
        )
        estimate = expected_frames * EST_FRAME_BYTES
        if estimate > SAFE_PAK_BYTES:
            advice = (
                f"\n⚠️ 体积预估约 {estimate / 1024 / 1024:.1f} MB（{expected_frames} 帧），"
                f"超过单包上限（{SAFE_PAK_BYTES / 1024 / 1024:.0f} MB）——会自动降质压缩，"
                f"画质可能下降。"
            )
            self.info.setText(info.describe() + advice)

        payload_mb = info.estimated_payload_bytes / 1024 / 1024
        self._ctx.logger.info(
            "preview_ready",
            feature_id="static_image" if not info.is_animated else "gif_upload",
            frames=info.n_frames,
            size_mb=round(info.size_mb, 2),
            estimated_mb=round(payload_mb, 2),
        )
        if info.extension_mismatch:
            self.note.setText("提示：扩展名与实际格式不一致，已按文件内容识别。")
            self.note.setStyleSheet(f"color:{_MUTED}; font-size:12px;")
        else:
            self._apply_gate()

    def _on_failed(self, message: str) -> None:
        self._image = None
        self._portrait = None
        self.info.setText(f"无法处理：{message}")
        self.canvas_landscape.set_image(None)
        self.canvas_portrait.set_image(None)
        self._ctx.logger.error(
            "preview_failed", feature_id="gif_upload", result="fail",
            error_code="PREPROCESS_FAILED", detail=message,
        )

    # -- 发送 ------------------------------------------------------------- #
    def send_upload(self) -> None:
        """上传到屏幕 / 停止显示（同一个按钮切换）。"""
        if self._upload is not None and self._upload.isRunning():
            self._upload.stop()
            self.btn_send.setEnabled(False)
            self.note.setText("正在停止并恢复官方显示 …")
            return

        if not self._ctx.feature_allowed("gif_upload"):
            self.note.setText(f"⚠️ 上传暂不可用：{self._ctx.blocked_reason('gif_upload')}")
            self.note.setStyleSheet("color:#8a6d00; font-size:12px;")
            return

        if self._path is None or not self._path.exists():
            self.pick_file()
            if self._path is None:
                return

        if self.before_upload is not None:
            self.before_upload()

        port = find_lcd_port() or str(
            self._ctx.config.get("port_scan", {}).get("preferred_port") or "COM5"
        )
        self.progress.setRange(0, 0)
        self.note.setText(f"正在编码并接管屏幕（{port}）…")
        self.note.setStyleSheet(f"color:{_MUTED}; font-size:12px;")
        self.btn_send.setText("停止显示（恢复官方）")

        try:
            self._upload = _UploadWorker(
                self._ctx,
                self._path,
                port,
                rotation=("none" if self._flip180 else "180"),
                size=self._target_size,
                parent=self,
            )
            self._upload.encoded.connect(self._on_encoded)
            self._upload.progress.connect(self._on_upload_progress)
            self._upload.status.connect(self._on_upload_status)
            self._upload.uploading.connect(self._on_uploaded)
            self._upload.failed.connect(self._on_upload_failed)
            self._upload.done.connect(self._on_upload_done)
        except Exception as exc:  # noqa: BLE001 - 启动失败要让界面恢复
            self._upload = None
            self.btn_send.setText("上传到屏幕")
            self.btn_send.setEnabled(True)
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
            self.note.setText(f"⚠️ 无法开始上传：{exc}")
            self.note.setStyleSheet("color:#b3261e; font-size:12px;")
            self._ctx.logger.error(
                "upload_start_failed", feature_id="gif_upload",
                result="fail", error_code="UPLOAD_START_FAILED", detail=str(exc),
            )
            return
        self._upload.start()

    def clean_cache(self) -> None:
        """清理设备无效缓存（可选安全模式 / 彻底模式）。"""
        if self._cleaner is not None and self._cleaner.isRunning():
            return

        box = QMessageBox(self)
        box.setWindowTitle("清理设备缓存")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("要如何清理设备上的缓存？")
        box.setInformativeText(
            "只删本工具上传过的：安全，不会动官方素材。\n"
            "彻底清理：与官方垃圾桶一致，删除 img2 及以后的全部文件，"
            "能回收被无效缓存占用的空间。"
        )
        safe_btn = box.addButton("只删本工具上传的", QMessageBox.ButtonRole.AcceptRole)
        deep_btn = box.addButton("彻底清理（删 img2 及以后）", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is safe_btn:
            deep = False
        elif box.clickedButton() is deep_btn:
            deep = True
        else:
            return
        port = find_lcd_port() or str(
            self._ctx.config.get("port_scan", {}).get("preferred_port") or "COM5"
        )
        self.note.setText("正在清理设备缓存（会短暂停止官方服务）…")
        self.note.setStyleSheet(f"color:{_MUTED}; font-size:12px;")
        self.btn_clean.setEnabled(False)

        self._cleaner = _CleanWorker(self._ctx, port, self, deep=deep)
        self._cleaner.finished_report.connect(self._on_clean_done)
        self._cleaner.failed.connect(self._on_clean_failed)
        self._cleaner.finished.connect(lambda: self.btn_clean.setEnabled(True))
        self._cleaner.start()

    def _on_clean_done(self, text: str) -> None:
        self.note.setText(f"✅ {text}")
        self.note.setStyleSheet("color:#1a7f37; font-size:12px;")

    def _on_clean_failed(self, message: str) -> None:
        self.note.setText(f"⚠️ 清理失败：{message}")
        self.note.setStyleSheet("color:#b3261e; font-size:12px;")

    # -- 上传回调 --------------------------------------------------------- #
    def _on_encoded(self, frames: int, size: int, quality: int) -> None:
        """编码完成：显示实测体积，超安全线就警告。"""
        kb = size / 1024
        text = f"编码完成：{frames} 帧 · {kb:.0f} KB · 平均质量 q{quality}"
        if size > SAFE_PAK_BYTES:
            text += "  ⚠️ 超过设备安全容量（约 800 KB），可能无法完整播放"
            self.note.setStyleSheet("color:#b3261e; font-size:12px;")
        else:
            self.note.setStyleSheet("color:#1a7f37; font-size:12px;")
        self.note.setText(text)

    def _on_upload_status(self, text: str) -> None:
        """显示上传阶段文字（含剩余时间）。"""
        self.note.setText(text)
        self.note.setStyleSheet(f"color:{_MUTED}; font-size:12px;")

    def _on_upload_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(done)

    def _on_uploaded(self, name: str) -> None:
        self.note.setText(f"✅ {name} 已上传，屏幕已切换（关闭窗口会自动恢复官方显示）")
        self.note.setStyleSheet("color:#1a7f37; font-size:12px;")
        self._ctx.logger.info("upload_displayed", feature_id="gif_upload", name=name)

    def _on_upload_failed(self, message: str) -> None:
        self.note.setText(f"⚠️ 上传失败：{message}")
        self.note.setStyleSheet("color:#b3261e; font-size:12px;")
        self._ctx.logger.error(
            "upload_failed", feature_id="gif_upload", result="fail",
            error_code="UPLOAD_FAILED", detail=message,
        )

    def _on_upload_done(self, description: str) -> None:
        self.btn_send.setText("上传到屏幕")
        self.btn_send.setEnabled(self._ctx.feature_allowed("gif_upload"))
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        if "✅" not in self.note.text():
            self.note.setText(description)

