# SPDX-License-Identifier: MIT
"""文件校验：在把任何东西读进内存之前，先判定"这个文件能不能传"。

设计意图：所有拒绝都发生在**解码之前**（除 GIF 帧数统计外），这样可以
避免一个 500MB 的畸形 GIF 把进程内存打满。

校验顺序（先便宜后昂贵）：
1. 存在性 / 是否文件 → 一次 ``stat``
2. 空文件
3. **40MB 上限** → 只读 ``st_size``，不读内容
4. 魔数嗅探（不信任扩展名）→ 只读前 16 字节
5. 解码与元数据（Pillow）→ 最后才真正解码

错误一律带 ``error_code``，可直接写进 ``feature_registry.json`` 与结构化日志。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ..constants import MAX_FPS, MAX_UPLOAD_BYTES, SCREEN_HEIGHT, SCREEN_WIDTH

__all__ = [
    "MediaKind",
    "MediaError",
    "FileMissingError",
    "FileTooLargeError",
    "UnsupportedFormatError",
    "CorruptMediaError",
    "MediaInfo",
    "sniff_kind",
    "probe_media",
    "SUPPORTED_KINDS",
]


# --------------------------------------------------------------------------- #
# 类型
# --------------------------------------------------------------------------- #
class MediaKind(str, Enum):
    """文件真实类型（由魔数判定，不看扩展名）。"""

    GIF = "gif"
    PNG = "png"
    JPEG = "jpeg"
    UNKNOWN = "unknown"

    @property
    def display(self) -> str:
        return {"gif": "GIF", "png": "PNG", "jpeg": "JPEG", "unknown": "未知"}[self.value]


#: 允许上传的类型（对应 feature_id: gif_upload / static_image）
SUPPORTED_KINDS: tuple[MediaKind, ...] = (MediaKind.GIF, MediaKind.PNG, MediaKind.JPEG)

# 魔数表：只认文件头，不认扩展名
_MAGIC: tuple[tuple[bytes, MediaKind], ...] = (
    (b"GIF87a", MediaKind.GIF),
    (b"GIF89a", MediaKind.GIF),
    (b"\x89PNG\r\n\x1a\n", MediaKind.PNG),
    (b"\xff\xd8\xff", MediaKind.JPEG),
)

_HEAD_BYTES = 16
_MB = 1024 * 1024


# --------------------------------------------------------------------------- #
# 异常
# --------------------------------------------------------------------------- #
class MediaError(Exception):
    """媒体校验异常基类。"""

    error_code: str = "MEDIA_ERROR"
    hint: str = ""

    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint or self.hint

    def user_message(self) -> str:
        return f"{self.message} {self.hint}".strip()


class FileMissingError(MediaError):
    error_code = "MEDIA_MISSING"
    hint = "请确认路径正确，且文件没有被移动或删除。"


class FileTooLargeError(MediaError):
    error_code = "MEDIA_TOO_LARGE"
    hint = "请先用工具缩小文件（降低分辨率/减少帧数/降低颜色数）后重试。"


class UnsupportedFormatError(MediaError):
    error_code = "MEDIA_UNSUPPORTED"
    hint = "仅支持 GIF / PNG / JPEG。"


class CorruptMediaError(MediaError):
    error_code = "MEDIA_CORRUPT"
    hint = "文件可能已损坏，或扩展名与实际内容不符。"


# --------------------------------------------------------------------------- #
# 魔数嗅探
# --------------------------------------------------------------------------- #
def sniff_kind(head: bytes) -> MediaKind:
    """根据文件头判定类型。无法识别返回 :attr:`MediaKind.UNKNOWN`。"""
    for magic, kind in _MAGIC:
        if head.startswith(magic):
            return kind
    return MediaKind.UNKNOWN


# --------------------------------------------------------------------------- #
# 结果
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MediaInfo:
    """校验结果。字段够 UI 直接展示，也够写进调试报告。"""

    path: Path
    kind: MediaKind
    size_bytes: int
    width: int
    height: int
    n_frames: int
    duration_ms: int
    mode: str = ""
    extension_mismatch: bool = False
    has_transparency: bool = False
    duration_estimated: bool = False
    """True 表示 GIF 未写帧延时（延时为 0），``duration_ms`` 是按每帧 100ms 估算的。

    这不是事实，只是与浏览器/多数播放器一致的兜底约定。UI 必须显式标注，
    否则用户会误以为"我看到的时间就是实际播放时间"。
    """

    # -- 派生值 --------------------------------------------------------- #
    @property
    def size_mb(self) -> float:
        return self.size_bytes / _MB

    @property
    def is_animated(self) -> bool:
        return self.kind is MediaKind.GIF and self.n_frames > 1

    @property
    def duration_s(self) -> float:
        return self.duration_ms / 1000.0

    @property
    def fps(self) -> float | None:
        """平均帧率。总时长为 0（例如未写 duration 的单帧 GIF）时返回 None。"""
        if self.duration_ms <= 0 or self.n_frames <= 1:
            return None
        return self.n_frames / self.duration_s

    @property
    def frame_stride(self) -> int:
        """为压到 30fps 以内需要每隔几帧取一帧（1 表示不抽帧）。"""
        fps = self.fps
        if fps is None or fps <= MAX_FPS:
            return 1
        return max(1, math.ceil(fps / MAX_FPS))

    @property
    def needs_decimation(self) -> bool:
        return self.frame_stride > 1

    @property
    def frames_after_decimation(self) -> int:
        stride = self.frame_stride
        return max(1, math.ceil(self.n_frames / stride))

    @property
    def target_size(self) -> tuple[int, int]:
        return (SCREEN_WIDTH, SCREEN_HEIGHT)

    @property
    def needs_resize(self) -> bool:
        return (self.width, self.height) != (SCREEN_WIDTH, SCREEN_HEIGHT)

    @property
    def estimated_payload_bytes(self) -> int:
        """按 800x216 RGB565（2 字节/像素）估算传输字节数。

        注意：这是**载荷**估算，不含协议头与分包开销，也不代表文件大小。
        """
        return SCREEN_WIDTH * SCREEN_HEIGHT * 2 * self.frames_after_decimation

    def as_dict(self) -> dict[str, object]:
        """便于写进 debug_report.json 与 feature_registry.json。"""
        return {
            "path": str(self.path),
            "kind": self.kind.value,
            "size_bytes": self.size_bytes,
            "size_mb": round(self.size_mb, 2),
            "width": self.width,
            "height": self.height,
            "n_frames": self.n_frames,
            "duration_ms": self.duration_ms,
            "fps": round(self.fps, 2) if self.fps is not None else None,
            "frame_stride": self.frame_stride,
            "needs_decimation": self.needs_decimation,
            "needs_resize": self.needs_resize,
            "extension_mismatch": self.extension_mismatch,
            "mode": self.mode,
            "duration_estimated": self.duration_estimated,
            "estimated_payload_bytes": self.estimated_payload_bytes,
        }

    def describe(self) -> str:
        """单行 UI 文案。"""
        parts = [
            f"{self.kind.display} {self.width}x{self.height}",
            f"{self.n_frames} 帧",
            f"{self.size_mb:.2f} MB",
        ]
        if self.fps is not None:
            parts.append(f"{self.fps:.1f} fps")
        if self.needs_decimation:
            parts.append(f"将抽帧 1/{self.frame_stride} → {self.frames_after_decimation} 帧")
        if self.needs_resize:
            parts.append(f"将缩放至 {SCREEN_WIDTH}x{SCREEN_HEIGHT}")
        if self.duration_estimated:
            parts.append("帧延时缺失，按 100ms/帧估算")
        return " · ".join(parts)


# --------------------------------------------------------------------------- #
# 主校验
# --------------------------------------------------------------------------- #
def _read_head(path: Path, size: int = _HEAD_BYTES) -> bytes:
    with path.open("rb") as fh:
        return fh.read(size)


def probe_media(
    path: str | Path,
    *,
    max_bytes: int = MAX_UPLOAD_BYTES,
    allowed: tuple[MediaKind, ...] = SUPPORTED_KINDS,
) -> MediaInfo:
    """校验文件并返回元数据。不合法时抛 :class:`MediaError` 子类。

    Args:
        path: 文件路径。
        max_bytes: 体积上限，默认 40MB。
        allowed: 允许的类型集合。

    Raises:
        FileMissingError: 路径不存在或不是文件。
        FileTooLargeError: 超过 ``max_bytes``。
        UnsupportedFormatError: 魔数不在支持范围内。
        CorruptMediaError: 无法解码 / 空文件 / 帧数据异常。
    """
    file_path = Path(path)

    # 1. 存在性
    try:
        stat = file_path.stat()
    except OSError as exc:
        raise FileMissingError(f"文件不存在或无法访问: {file_path}") from exc
    if not file_path.is_file():
        raise FileMissingError(f"不是一个文件: {file_path}")

    # 2. 空文件
    if stat.st_size == 0:
        raise CorruptMediaError(f"文件为空: {file_path.name}", hint="空文件没有可上传的内容。")

    # 3. 体积上限（不读内容，先拒绝）
    if stat.st_size > max_bytes:
        raise FileTooLargeError(
            f"文件 {stat.st_size / _MB:.2f} MB 超过 {max_bytes / _MB:.0f} MB 上限: {file_path.name}",
            hint=f"请先缩小到 {max_bytes / _MB:.0f} MB 以内再上传。",
        )

    # 4. 魔数
    head = _read_head(file_path)
    kind = sniff_kind(head)
    if kind is MediaKind.UNKNOWN:
        raise UnsupportedFormatError(
            f"无法识别的文件格式: {file_path.name}（文件头 {head[:8].hex()}）",
            hint="仅支持 GIF / PNG / JPEG，且不看扩展名、只看文件内容。",
        )
    if kind not in allowed:
        raise UnsupportedFormatError(f"当前功能不接受 {kind.display} 文件: {file_path.name}")

    suffix = file_path.suffix.lower().lstrip(".")
    accepted_suffixes = {kind.value}
    if kind is MediaKind.JPEG:
        accepted_suffixes |= {"jpg", "jpe"}
    extension_mismatch = suffix not in accepted_suffixes

    # 5. 解码（最贵的一步放最后）
    return _read_metadata(file_path, kind, stat.st_size, extension_mismatch)


def _read_metadata(path: Path, kind: MediaKind, size: int, extension_mismatch: bool) -> MediaInfo:
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:  # pragma: no cover - 环境问题
        raise MediaError("Pillow 未安装，无法解码图片") from exc

    try:
        with Image.open(path) as im:
            width, height = im.size
            mode = im.mode
            n_frames = int(getattr(im, "n_frames", 1) or 1)
            duration_ms, duration_estimated = _total_duration_ms(im, n_frames, kind)
            has_transparency = _detect_transparency(im, kind)
    except UnidentifiedImageError as exc:
        raise CorruptMediaError(f"无法解码图片: {path.name}") from exc
    except Image.DecompressionBombError as exc:  # type: ignore[attr-defined]
        raise CorruptMediaError(
            f"图片像素数量异常（疑似解压炸弹）: {path.name}",
            hint="请确认这不是恶意构造的文件。",
        ) from exc
    except (OSError, ValueError) as exc:
        raise CorruptMediaError(f"读取图片元数据失败: {path.name} -> {exc}") from exc

    if width <= 0 or height <= 0:
        raise CorruptMediaError(f"图片尺寸非法: {width}x{height}")
    if n_frames <= 0:
        raise CorruptMediaError("帧数为 0，文件可能已损坏")

    # APNG 会被 Pillow 报成多帧 PNG，但后续上传路径只认 GIF 的动画语义。
    # 若不在这里拒绝，UI 会显示"3 帧"而实际只上传第一帧 —— 属于欺骗用户。
    if kind is MediaKind.PNG and n_frames > 1:
        raise UnsupportedFormatError(
            f"检测到多帧 PNG（APNG）: {path.name}（{n_frames} 帧）",
            hint="APNG 暂不支持，强行上传只会显示第一帧。请导出为 GIF，或挑单帧存成普通 PNG。",
        )

    return MediaInfo(
        path=path,
        kind=kind,
        size_bytes=size,
        width=width,
        height=height,
        n_frames=n_frames,
        duration_ms=duration_ms,
        mode=mode,
        extension_mismatch=extension_mismatch,
        has_transparency=has_transparency,
        duration_estimated=duration_estimated,
    )


def _total_duration_ms(im: object, n_frames: int, kind: MediaKind) -> tuple[int, bool]:
    """累计所有帧的 duration（毫秒），并标明是否为估算值。

    GIF 允许每帧单独设延时，所以必须逐帧 seek 累加，不能用首帧乘帧数。

    另一个现实问题：GIF 可以**不写延时**（等价于"尽可能快"）。此时若按 0 处理，
    ``fps`` 会变成 None，抽帧逻辑直接失效，一个可能是 100fps 的动画会被原速送出。
    这里采用浏览器/主流播放器一致的兜底约定（每帧 100ms），但必须把
    ``estimated=True`` 传递出去，让 UI 与日志明确这是假设而不是事实。
    """
    if kind is not MediaKind.GIF or n_frames <= 1:
        return (0, False)

    total = 0
    for index in range(n_frames):
        try:
            im.seek(index)  # type: ignore[attr-defined]
        except (EOFError, OSError):
            break
        info = getattr(im, "info", {}) or {}
        frame_duration = info.get("duration", 0) or 0
        try:
            total += int(frame_duration)
        except (TypeError, ValueError):
            continue

    if total <= 0:
        return (100 * n_frames, True)
    return (total, False)


def _detect_transparency(im: object, kind: MediaKind) -> bool:
    if kind is MediaKind.JPEG:
        return False
    mode = getattr(im, "mode", "")
    if mode in {"RGBA", "LA", "P"}:
        info = getattr(im, "info", {}) or {}
        return bool(info.get("transparency") is not None or mode in {"RGBA", "LA"})
    return False
