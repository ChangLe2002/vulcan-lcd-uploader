# SPDX-License-Identifier: MIT
"""图像预处理：把任意输入变成"严格 800×216 的 RGB 帧序列"。

硬性保证
--------
1. **输出尺寸严格等于 800×216**，无论输入是 100×100 还是 8000×1000；
2. 采用 **cover** 策略（等比放大到铺满 → 居中裁剪），不拉伸变形、不留黑边；
3. 重采样固定 **LANCZOS**；
4. 先做 **EXIF 方向校正**，否则手机竖拍照片会躺倒 90°；
5. 带透明通道的图**先合成到底色**（默认黑），因为设备端没有 alpha；
6. 帧率按 10ms 量化后的延时抽帧，并把被抽掉帧的延时应有的**时长累加**到保留帧上，
   这样播放总时长不变（否则抽帧会让动画变快）。

内存策略：帧是**流式**产出的（生成器），不会把整段 GIF 解成几十张位图常驻内存。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Sequence

from ..constants import MAX_FPS, SCREEN_HEIGHT, SCREEN_WIDTH
from .probe import MediaInfo

__all__ = [
    "fit_to_screen",
    "FIT_NATIVE",
    "FIT_MODES",
    "PreprocessError",
    "PreparedFrame",
    "PrepareSummary",
    "apply_exif_orientation",
    "flatten_alpha",
    "prepare_image",
    "rotate_image",
    "iter_prepared_frames",
    "prepare_media",
    "summarize",
]

# 与 probe 的兜底约定保持一致：GIF 未写延时时按 100ms/帧 处理
_FALLBACK_FRAME_MS = 100

DEFAULT_BACKGROUND: tuple[int, int, int] = (0, 0, 0)


class PreprocessError(Exception):
    """预处理失败。"""

    error_code = "PREPROCESS_FAILED"

    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


@dataclass(frozen=True)
class PreparedFrame:
    """一帧已就绪的图像。"""

    index: int                      # 输出序号（从 0 开始）
    source_indices: tuple[int, ...]  # 对应原文件的哪些帧（抽帧后可能多个）
    duration_ms: int                # 该输出帧应停留的时长（已含被抽掉帧的时长）
    image: object                   # PIL.Image，模式 RGB，尺寸 800x216

    @property
    def size(self) -> tuple[int, int]:
        return self.image.size  # type: ignore[attr-defined]


@dataclass(frozen=True)
class PrepareSummary:
    """整段素材的处理结果摘要，供 UI 展示与日志记录。"""

    frame_count: int
    total_duration_ms: int
    width: int
    height: int
    bytes_per_frame: int
    dropped_frames: int

    @property
    def total_bytes(self) -> int:
        return self.bytes_per_frame * self.frame_count

    @property
    def fps(self) -> float | None:
        if self.total_duration_ms <= 0 or self.frame_count <= 1:
            return None
        return self.frame_count / (self.total_duration_ms / 1000.0)

    def describe(self) -> str:
        seconds = self.total_duration_ms / 1000.0
        return (
            f"{self.frame_count} 帧 · {self.width}x{self.height} · "
            f"{seconds:.1f}s · 约 {self.total_bytes / 1024 / 1024:.2f} MB 载荷"
            f"（已抽掉 {self.dropped_frames} 帧）"
        )


# --------------------------------------------------------------------------- #
# 单帧处理
# --------------------------------------------------------------------------- #
def apply_exif_orientation(image: object) -> object:
    """按 EXIF Orientation 旋转/镜像。GIF 无 EXIF，调用无副作用。"""
    from PIL import ImageOps  # noqa: PLC0415

    try:
        return ImageOps.exif_transpose(image)
    except Exception:  # noqa: BLE001 - 畸形 EXIF 不应让整个流程失败
        return image


def flatten_alpha(image: object, *, background: tuple[int, int, int] = DEFAULT_BACKGROUND) -> object:
    """把带透明通道的图合成到纯色底，返回 RGB 图。

    设备端没有 alpha，任何"半透明"都必须在这里变成确定颜色。
    选黑底是因为它最接近屏幕默认表现，也不会让浅色元素在暗背景上突然变亮。
    """
    from PIL import Image  # noqa: PLC0415

    mode = getattr(image, "mode", "RGB")
    has_alpha = mode in {"RGBA", "LA", "PA"} or "transparency" in getattr(image, "info", {})
    if not has_alpha:
        return image if mode == "RGB" else image.convert("RGB")  # type: ignore[attr-defined]

    rgba = image.convert("RGBA")  # type: ignore[attr-defined]
    canvas = Image.new("RGB", rgba.size, background)
    canvas.paste(rgba, mask=rgba.split()[-1])
    return canvas


def rotate_image(image: object, *, clockwise: bool = True) -> object:
    """旋转 90°，**只用于预览**，不改变上传内容。

    用 ``transpose`` 而不是 ``rotate``：后者会走插值，800×216 的文字被旋转后
    会发虚，而这里只是让用户判断"立装后好不好看"，必须像素级精确。

    立装显卡时屏幕物理上是竖的，用户想看到 216×800 的模拟效果，
    但**实际发送的仍是 800×216**——旋转只发生在本机预览里。
    """
    from PIL import Image  # noqa: PLC0415

    method = Image.Transpose.ROTATE_270 if clockwise else Image.Transpose.ROTATE_90
    return image.transpose(method)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# 屏幕适配：官方做法 —— 不缩放，原始尺寸贴左上角，其余留黑
# --------------------------------------------------------------------------- #
FIT_NATIVE = "native"    # 唯一模式（2026-11-06 实测确认的官方行为）
FIT_MODES = (FIT_NATIVE,)


def fit_to_screen(
    image: object,
    size: tuple[int, int],
    *,
    mode: str = FIT_NATIVE,
    zoom: float = 1.0,          # 保留形参以兼容旧调用；native 模式下不生效
    background: tuple[int, int, int] = (0, 0, 0),
) -> object:
    """把图像贴到 ``size`` 画布：不缩放，左上对齐，其余补黑的官方做法。

    实测官方 pak 的帧就是「左侧 800 列有内容 + 右侧 224 列全黑」，
    说明官方从不缩放；早期我们改用拉伸/裁切反而导致画面偏移。
    """
    from PIL import Image  # noqa: PLC0415

    if mode != FIT_NATIVE:
        raise ValueError(f"只支持 native 适配（官方效果），收到 {mode!r}")

    target_w, target_h = size
    canvas = Image.new("RGB", (target_w, target_h), background)
    canvas.paste(image, (0, 0))
    return canvas


def prepare_image(
    image: object,
    *,
    size: tuple[int, int] = (SCREEN_WIDTH, SCREEN_HEIGHT),
    background: tuple[int, int, int] = DEFAULT_BACKGROUND,
    fit_mode: str = "native",
    zoom: float = 1.0,
    rotation: str = "none",
) -> object:
    """单帧完整流水线：EXIF → 去 alpha → cover 缩放 → 严格尺寸校验。"""
    from PIL import Image  # noqa: PLC0415 - ROTATE_180 常量

    frame = apply_exif_orientation(image)
    frame = flatten_alpha(frame, background=background)
    # 官方样本 pak 证实：先旋转源图，再贴到画布左上角
    # （若先贴后转，内容会跑到画布右半边，与官方样本不符）
    if rotation == "cw":
        frame = rotate_image(frame, clockwise=True)
    elif rotation == "ccw":
        frame = rotate_image(frame, clockwise=False)
    elif rotation in ("180", "flip180"):
        frame = frame.transpose(Image.Transpose.ROTATE_180)

    frame = fit_to_screen(frame, size=size, mode=fit_mode, zoom=zoom, background=background)

    if tuple(frame.size) != tuple(size):  # type: ignore[attr-defined]
        raise PreprocessError(
            f"缩放后尺寸仍不符：期望 {size}，实际 {frame.size}"  # type: ignore[attr-defined]
        )
    if frame.mode != "RGB":  # type: ignore[attr-defined]
        frame = frame.convert("RGB")  # type: ignore[attr-defined]
    return frame


# --------------------------------------------------------------------------- #
# 序列处理
# --------------------------------------------------------------------------- #
class _Group:
    """把连续的原帧按 stride 聚成一组。"""

    def __init__(self) -> None:
        self.indices: list[int] = []
        self.duration_ms = 0

    def add(self, index: int, duration_ms: int) -> None:
        self.indices.append(index)
        self.duration_ms += duration_ms

    def clear(self) -> None:
        self.indices.clear()
        self.duration_ms = 0


def iter_prepared_frames(
    path: str | Path,
    info: MediaInfo,
    *,
    size: tuple[int, int] = (SCREEN_WIDTH, SCREEN_HEIGHT),
    background: tuple[int, int, int] = DEFAULT_BACKGROUND,
    on_progress: Callable[[int, int], None] | None = None,
    max_frames: int = 0,
    fit_mode: str = FIT_NATIVE,
    zoom: float = 1.0,
    rotation: str = "none",
) -> Iterator[PreparedFrame]:
    """流式产出处理好的帧。

    Args:
        path: 源文件。
        info: :func:`vulcan_lcd.media.probe.probe_media` 的结果（复用其帧率/抽帧结论）。
        size: 目标尺寸。
        background: 透明合成底色。
        on_progress: ``(已产出, 预计总数)`` 回调，供 UI 进度条。
        max_frames: >0 时作为硬上限，超出抛 :class:`PreprocessError`。
    fit_mode: 仅支持 native（官方效果）。
    zoom: 已废弃（native 不缩放），保留形参兼容。
    """
    from PIL import Image, UnidentifiedImageError  # noqa: PLC0415

    stride = max(1, info.frame_stride)
    expected = info.frames_after_decimation
    if max_frames and expected > max_frames:
        raise PreprocessError(
            f"预计输出 {expected} 帧，超过上限 {max_frames}",
            hint="请减少帧数或缩短时长。",
        )

    group = _Group()
    emitted = 0

    try:
        with Image.open(path) as im:
            total = int(getattr(im, "n_frames", 1) or 1)
            for index in range(total):
                im.seek(index)
                frame_duration = int(getattr(im, "info", {}).get("duration", 0) or 0)
                if frame_duration <= 0 and total > 1:
                    # 只有多帧动画才需要"延时缺失"的兜底；静态图没有播放时长概念
                    frame_duration = _FALLBACK_FRAME_MS

                group.add(index, frame_duration)
                if len(group.indices) < stride:
                    continue

                prepared = prepare_image(
                    im.copy(), size=size, background=background,
                    fit_mode=fit_mode, zoom=zoom, rotation=rotation,
                )
                emitted += 1
                if max_frames and emitted > max_frames:
                    raise PreprocessError(f"输出帧数超过上限 {max_frames}")
                if on_progress is not None:
                    on_progress(emitted, expected)
                yield PreparedFrame(
                    index=emitted - 1,
                    source_indices=tuple(group.indices),
                    duration_ms=group.duration_ms,
                    image=prepared,
                )
                group.clear()

            # 尾部不足一组也要产出，否则最后几帧会被吞掉
            if group.indices:
                prepared = prepare_image(
                    im.copy(), size=size, background=background,
                    fit_mode=fit_mode, zoom=zoom, rotation=rotation,
                )
                emitted += 1
                if on_progress is not None:
                    on_progress(emitted, expected)
                yield PreparedFrame(
                    index=emitted - 1,
                    source_indices=tuple(group.indices),
                    duration_ms=group.duration_ms,
                    image=prepared,
                )
    except UnidentifiedImageError as exc:
        raise PreprocessError(f"无法解码图片: {Path(path).name}") from exc
    except OSError as exc:
        raise PreprocessError(f"读取图像失败: {Path(path).name} -> {exc}") from exc


def prepare_media(
    path: str | Path,
    info: MediaInfo,
    *,
    size: tuple[int, int] = (SCREEN_WIDTH, SCREEN_HEIGHT),
    background: tuple[int, int, int] = DEFAULT_BACKGROUND,
    on_progress: Callable[[int, int], None] | None = None,
    max_frames: int = 0,
) -> list[PreparedFrame]:
    """一次性取回全部帧（小素材用；大 GIF 请用生成器版本以控制内存）。"""
    return list(
        iter_prepared_frames(
            path,
            info,
            size=size,
            background=background,
            on_progress=on_progress,
            max_frames=max_frames,
        )
    )


def summarize(frames: Sequence[PreparedFrame], info: MediaInfo) -> PrepareSummary:
    """汇总结果，供 UI 与日志展示。"""
    if not frames:
        raise PreprocessError("没有任何可用帧")
    width, height = frames[0].size
    return PrepareSummary(
        frame_count=len(frames),
        total_duration_ms=sum(f.duration_ms for f in frames),
        width=width,
        height=height,
        bytes_per_frame=width * height * 2,
        dropped_frames=max(0, info.n_frames - len(frames)),
    )


def clamp_fps(frame_count: int, total_duration_ms: int) -> float | None:
    """辅助：计算实际输出帧率，用于校验是否真的压到了 30fps 以内。"""
    if total_duration_ms <= 0 or frame_count <= 1:
        return None
    fps = frame_count / (total_duration_ms / 1000.0)
    return fps if fps <= MAX_FPS else fps
