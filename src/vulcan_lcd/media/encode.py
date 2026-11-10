# SPDX-License-Identifier: MIT
"""把 GIF / 静态图片编码成设备可用的 pak。

链路：``probe_media`` → ``iter_prepared_frames``（缩放/合成/纹理）→ JPEG 编码 → ``build_pak``。

尺寸取 :data:`~vulcan_lcd.constants.SCREEN_WIDTH/HEIGHT`（实测 1024×240）。
JPEG 质量可配：官方 1024×240 帧约 8.7–11.3 KB，可作校准基准。
"""

from __future__ import annotations

from ..system.proc import run as _run_hidden

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..constants import SCREEN_HEIGHT, SCREEN_WIDTH
from .pak import build_pak
from .preprocess import iter_prepared_frames
from .probe import MediaInfo, probe_media

__all__ = [
    "EncodeError",
    "find_ffmpeg",
    "encode_jpeg_ffmpeg",
    "encode_jpeg_best",
    "adjust_frame_count",
    "encode_file_ffmpeg",
    "fit_frames_to_budget",
    "encode_frames_batch_ffmpeg",
    "encode_jpeg_chunk",
    "encode_jpeg_official",
    "EncodedPak",
    "STRATEGY_SMOOTH",
    "STRATEGY_CLEAR",
    "encode_jpeg",
    "encode_jpeg_limited",
    "encode_media_to_pak",
]

#: 默认 JPEG 质量。官方帧约 8.7–11.3 KB / 1024×240，85 大致落在同一区间。
DEFAULT_QUALITY = 85

#: 帧间隔下限/上限（毫秒）。设备按固定间隔播放，取各帧平均停留时长。
MIN_INTERVAL_MS = 20
MAX_INTERVAL_MS = 2000

#: 单帧 JPEG 的默认上限（策略表会再按容量预算收紧）。官方帧约 8.7–16 KB；
#: 超出这个量级时设备解码会跳帧（表现为"只循环播放几帧"），所以这里按上限自适应降质。
DEFAULT_MAX_FRAME_BYTES = 16_384

#: 自适应降质的质量阶梯（从高到低尝试，取第一个满足上限的）。
QUALITY_LADDER = (85, 78, 70, 62, 54, 46, 38, 30, 24, 20, 16, 12, 10)

#: 单个 pak 的目标容量上限。实测 757 KB 的 130 帧可完整播放，2,005 KB 的播不全——
#: 设备闪存/解码缓冲有限，这里保守取 1 MB，超出则抽帧。
DEFAULT_MAX_PAK_BYTES = 4_000_000

#: 两种压缩策略：`smooth` 保帧数（单帧压得更狠）、`clear` 保画质（抽帧）。
STRATEGY_SMOOTH = "smooth"
STRATEGY_CLEAR = "clear"

#: 各策略下单帧的 JPEG 目标上限。
FRAME_CAP_BY_STRATEGY = {STRATEGY_SMOOTH: 32_000, STRATEGY_CLEAR: 48_000}

#: 抽帧下限：再抽也不能少于这么多帧，否则动画会变成幻灯片。
MIN_FRAMES = 8

#: JPEG 编码后端：auto（优先 ffmpeg）/ ffmpeg / pil
JPEG_BACKEND = "auto"

#: 屏幕安装方向补偿。实测本机屏幕为倒装：官方 pak 里的画面是旋转 180° 的，
#: 不旋转会导致画面上下颠倒（表现为“看起来偏移/不居中”）。
DEFAULT_ROTATION = "180"

#: 设备固定播放帧率。实测：官方把 3 帧/1.5s 的 GIF 打成 31 帧（≈20fps），
#: 而 180 帧/9s 的素材（正好 20fps）播放正常——说明 `interval` 被忽略，
#: 播放速度由「帧数 × 50ms」决定，编码时必须重采样到这个帧率。
TARGET_FPS = 30
TARGET_INTERVAL_MS = 1000 // TARGET_FPS


class EncodeError(Exception):
    """编码失败。"""

    error_code = "ENCODE_FAILED"

    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


@dataclass(frozen=True)
class EncodedPak:
    """编码结果。"""

    pak: bytes
    frames: int
    fps: int
    quality: int
    width: int
    height: int

    @property
    def size(self) -> int:
        return len(self.pak)

    def describe(self) -> str:
        return (
            f"{self.frames} 帧 · {self.width}×{self.height} · "
            f"源帧率 {self.fps}fps · JPEG q{self.quality} · {self.size / 1024:.1f} KB"
        )


def encode_jpeg(image: object, *, quality: int = DEFAULT_QUALITY) -> bytes:
    """把 PIL 图像编码成 JPEG 字节。"""
    from PIL import Image  # noqa: PLC0415

    if not isinstance(image, Image.Image):
        raise EncodeError("需要 PIL.Image 对象")
    if not 1 <= quality <= 95:
        raise EncodeError(f"JPEG 质量必须在 1–95: {quality}")

    buffer = io.BytesIO()
    try:
        image.save(buffer, format="JPEG", quality=quality, subsampling=2, optimize=True)
    except OSError as exc:
        raise EncodeError(f"JPEG 编码失败：{exc}") from exc
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# 官方风格 JPEG 编码
# --------------------------------------------------------------------------- #
#: 标准亮度量化表（JPEG Annex K，对应 quality≈50 的基准）。
_BASE_LUMA_Q = (
    16, 11, 10, 16, 24, 40, 51, 61,
    12, 12, 14, 19, 26, 58, 60, 55,
    14, 13, 16, 24, 40, 57, 69, 56,
    14, 17, 22, 29, 51, 87, 80, 62,
    18, 22, 37, 56, 68, 109, 103, 77,
    24, 35, 55, 64, 81, 104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101,
    72, 92, 95, 98, 112, 100, 103, 99,
)


def _scaled_qtable(quality: int) -> list[int]:
    """按 JPEG 标准公式把基准表缩放到指定质量。"""
    quality = max(1, min(95, quality))
    scale = 5000 // quality if quality < 50 else 200 - quality * 2
    table = []
    for value in _BASE_LUMA_Q:
        scaled = (value * scale + 50) // 100
        table.append(max(1, min(255, scaled)))
    return table


def encode_jpeg_official(image: object, *, quality: int = DEFAULT_QUALITY) -> bytes:
    """按官方段结构编码：单张量化表（色度也用 q0）+ 去掉 JFIF APP0。"""
    from PIL import Image  # noqa: PLC0415

    if not isinstance(image, Image.Image):
        raise EncodeError("需要 PIL.Image 对象")
    if not 1 <= quality <= 95:
        raise EncodeError(f"JPEG 质量必须在 1–95: {quality}")

    buffer = io.BytesIO()
    try:
        image.save(
            buffer,
            format="JPEG",
            quality=quality,
            subsampling=2,
            qtables=[_scaled_qtable(quality)],
            optimize=False,
        )
    except OSError as exc:
        raise EncodeError(f"JPEG 编码失败：{exc}") from exc

    data = buffer.getvalue()
    if data[:2] != b"\xff\xd8":
        return data

    # 去掉 APP0(0xE0) 段，其余原样保留
    result = bytearray(data[:2])
    index = 2
    while index < len(data) - 1:
        if data[index] != 0xFF:
            result += data[index:]
            break
        marker = data[index + 1]
        if marker == 0xE0:
            seglen = int.from_bytes(data[index + 2 : index + 4], "big")
            next_index = index + 2 + seglen
            if next_index >= len(data):  # 段长度损坏：放弃裁剪，保留原始数据
                return data
            index = next_index
            continue
        result += data[index:]
        break
    return bytes(result)


# --------------------------------------------------------------------------- #
# ffmpeg 编码（与官方同源：官方 pak 的 JPEG 里 COM 段写着 Lavc57.104.100）
# --------------------------------------------------------------------------- #
#: 已知的 ffmpeg 位置（iGame Center 自带一份）
_FFMPEG_CANDIDATES = (
    r"E:\iGameCenter\SAVIConverter\tools\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    r"C:\ffmpeg\bin\ffmpeg.exe",
)


def find_ffmpeg() -> str | None:
    """返回可用的 ffmpeg 路径，找不到返回 None。"""
    import shutil  # noqa: PLC0415

    for candidate in _FFMPEG_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return shutil.which("ffmpeg")


def encode_jpeg_ffmpeg(image: object, *, quality: int = DEFAULT_QUALITY) -> bytes:
    """用 ffmpeg 的 mjpeg 编码器压缩（与官方产物同源）。

    Args:
        image: PIL.Image（RGB）。
        quality: 1–95，映射到 ffmpeg 的 ``-q:v``（1 最好、31 最差）。

    Raises:
        EncodeError: 找不到 ffmpeg 或编码失败。
    """
    import subprocess  # noqa: PLC0415

    from PIL import Image  # noqa: PLC0415

    if not isinstance(image, Image.Image):
        raise EncodeError("需要 PIL.Image 对象")
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise EncodeError("未找到 ffmpeg")

    rgb = image.convert("RGB")
    width, height = rgb.size
    quality = max(1, min(95, quality))
    # quality 95→q:v 2，quality 30→q:v 20，线性映射
    qv = max(2, min(31, int(round(2 + (95 - quality) * 0.28))))

    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-i", "pipe:0",
        "-frames:v", "1", "-c:v", "mjpeg", "-q:v", str(qv),
        "-pix_fmt", "yuvj420p", "-f", "image2pipe", "pipe:1",
    ]
    try:
        proc = _run_hidden(
            cmd,
            input=rgb.tobytes(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EncodeError(f"ffmpeg 执行失败：{exc}") from exc

    data = proc.stdout
    if proc.returncode != 0 or not data.startswith(b"\xff\xd8"):
        detail = proc.stderr.decode("utf-8", errors="replace")[:200]
        raise EncodeError(f"ffmpeg 编码失败：{detail or proc.returncode}")
    return data


def encode_jpeg_best(image: object, *, quality: int = DEFAULT_QUALITY, backend: str = "auto") -> bytes:
    """按配置选择编码后端。

    Args:
        backend: ``auto`` 优先 ffmpeg、失败回退 PIL；``ffmpeg`` 强制；``pil`` 只用 PIL。
    """
    if backend == "pil":
        return encode_jpeg_official(image, quality=quality)
    if backend == "ffmpeg":
        return encode_jpeg_ffmpeg(image, quality=quality)
    try:
        return encode_jpeg_ffmpeg(image, quality=quality)
    except EncodeError:
        return encode_jpeg_official(image, quality=quality)


def encode_jpeg_limited(
    image: object,
    *,
    max_bytes: int = DEFAULT_MAX_FRAME_BYTES,
    quality: int = DEFAULT_QUALITY,
) -> tuple[bytes, int]:
    """编码 JPEG，并逐级降质直到不超过 `max_bytes`。

    Returns:
        `(jpeg 字节, 实际使用的质量)`。若降到最低档仍超限，返回最低档结果。
    """
    ladder = [quality] + [q for q in QUALITY_LADDER if q < quality]
    best: tuple[bytes, int] | None = None
    for candidate in ladder:
        data = encode_jpeg_best(image, quality=candidate, backend=JPEG_BACKEND)
        best = (data, candidate)
        if len(data) <= max_bytes:
            return best
    return best if best is not None else (encode_jpeg_best(image, quality=quality, backend=JPEG_BACKEND), quality)


def _estimate_total(frames: list[bytes]) -> int:
    """pak 体积估算：头部 8 + 偏移表 4N + 每条记录（4 + JPEG + 对齐）。"""
    total = 8 + 4 * len(frames)
    for frame in frames:
        record = 4 + len(frame)
        total += record + (-record) % 4
    return total


def encode_frames_batch_ffmpeg(
    images: object,
    *,
    quality: int = DEFAULT_QUALITY,
) -> list[bytes]:
    """一次 ffmpeg 进程编码多帧（mjpeg），比逐帧 spawn 快约 10 倍。

    Args:
        images: PIL.Image 的序列（每帧同尺寸）。
        quality: 1–95。

    Raises:
        EncodeError: ffmpeg 不可用或编码失败。
    """
    import subprocess  # noqa: PLC0415

    from PIL import Image  # noqa: PLC0415

    frames = list(images)  # type: ignore[arg-type]
    if not frames:
        return []
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise EncodeError("未找到 ffmpeg")

    width, height = frames[0].size
    payload = bytearray()
    for frame in frames:
        rgb = frame.convert("RGB")
        if rgb.size != (width, height):
            rgb = rgb.resize((width, height), Image.Resampling.LANCZOS)
        payload += rgb.tobytes()

    quality = max(1, min(95, quality))
    qv = max(2, min(31, int(round(2 + (95 - quality) * 0.28))))
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-i", "pipe:0",
        "-c:v", "mjpeg", "-q:v", str(qv), "-pix_fmt", "yuvj420p",
        "-f", "image2pipe", "pipe:1",
    ]
    try:
        proc = _run_hidden(
            cmd, input=bytes(payload), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=180, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EncodeError(f"ffmpeg 批量编码失败：{exc}") from exc

    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace")[:200]
        raise EncodeError(f"ffmpeg 批量编码失败：{detail or proc.returncode}")

    # 按 SOI/EOI 切分
    out: list[bytes] = []
    data = proc.stdout
    pos = 0
    while True:
        start = data.find(b"\xff\xd8", pos)
        if start < 0:
            break
        end = data.find(b"\xff\xd9", start + 2)
        if end < 0:
            break
        out.append(data[start : end + 2])
        pos = end + 2

    if len(out) != len(frames):
        raise EncodeError(f"ffmpeg 返回帧数不符：期望 {len(frames)}，实际 {len(out)}")
    return out


def encode_jpeg_chunk(
    images: object,
    *,
    max_bytes: int,
    quality: int,
    chunk_size: int = 32,
) -> list[tuple[bytes, int]]:
    """分批编码（每批一次 ffmpeg），超预算的帧再单独降质重编。"""
    frames = list(images)  # type: ignore[arg-type]
    results: list[tuple[bytes, int]] = []
    for start in range(0, len(frames), chunk_size):
        chunk = frames[start : start + chunk_size]
        try:
            encoded = encode_frames_batch_ffmpeg(chunk, quality=quality)
        except EncodeError:
            for frame in chunk:
                results.append(
                    encode_jpeg_limited(frame, max_bytes=max_bytes, quality=quality)
                )
            continue
        for frame, data in zip(chunk, encoded):
            if len(data) <= max_bytes:
                results.append((data, quality))
            else:
                results.append(
                    encode_jpeg_limited(frame, max_bytes=max_bytes, quality=quality)
                )
    return results


def encode_file_ffmpeg(
    path: str | Path,
    *,
    size: tuple[int, int] = (SCREEN_WIDTH, SCREEN_HEIGHT),
    fps: int = TARGET_FPS,
    quality: int = DEFAULT_QUALITY,
    rotate180: bool = True,
) -> list[bytes]:
    """用一次 ffmpeg 调用把媒体文件直接转成 JPEG 序列（官方做法）。

    滤镜链与官方一致：``fps=30`` 重采样 → 180° 翻转 → 原始尺寸左上角贴图。

    Args:
        path: GIF / PNG / JPEG。
        size: 设备分辨率。
        fps: 目标帧率（设备固定 30）。
        quality: 1–95。
        rotate180: 是否做 180° 翻转（面板倒装补偿）。

    Raises:
        EncodeError: ffmpeg 不可用或转换失败。
    """
    import subprocess  # noqa: PLC0415

    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise EncodeError("未找到 ffmpeg")

    width, height = size
    quality = max(1, min(95, quality))
    qv = max(2, min(31, int(round(2 + (95 - quality) * 0.28))))

    # 与官方 ffmpeg 参数逐项对齐（反编译 LCDImgPakHelper.ClipImage:243）：
    #   rotate = 180 * PI / 180,
    #   pad = width = 1024:height = 240:x=1.0:y=5.0:color = black,
    #   fps = 30
    # 唯一新增的是前置 scale：官方不兜超大素材，我们兜一下，避免 pad 直接失败。
    filters = [f"scale=w='min(iw,{width})':h='min(ih,{height})'"]
    if rotate180:
        filters.append("rotate=180*PI/180")
    filters.append(f"pad=width={width}:height={height}:x=1:y=5:color=black")
    if fps > 0:
        filters.append(f"fps={fps}")
    vf = ",".join(filters)

    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-i", str(path),
        "-vf", vf,
        "-c:v", "mjpeg", "-q:v", str(qv), "-pix_fmt", "yuvj420p",
        "-vsync", "0",
        "-f", "image2pipe", "pipe:1",
    ]
    try:
        proc = _run_hidden(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=300, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EncodeError(f"ffmpeg 转换失败：{exc}") from exc

    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace")[:300]
        raise EncodeError(f"ffmpeg 转换失败：{detail or proc.returncode}")

    frames: list[bytes] = []
    data = proc.stdout
    pos = 0
    while True:
        start = data.find(b"\xff\xd8", pos)
        if start < 0:
            break
        end = data.find(b"\xff\xd9", start + 2)
        if end < 0:
            break
        frames.append(data[start : end + 2])
        pos = end + 2
    if not frames:
        raise EncodeError("ffmpeg 没有产出任何帧")
    return frames


def fit_frames_to_budget(
    frames: list[bytes],
    *,
    max_frame_bytes: int,
    max_pak_bytes: int,
    path: str | Path,
    size: tuple[int, int],
    fps: int,
    rotate180: bool,
    quality: int,
) -> tuple[list[bytes], int]:
    """按容量预算逐级降质重编（一次 ffmpeg 调用即一轮，很快）。"""
    ladder = [quality] + [q for q in QUALITY_LADDER if q < quality]
    result = frames
    used = quality
    expected = len(frames)   # 降质重编后仍要保证帧数不变（时长不变）
    for candidate in ladder:
        biggest = max(len(f) for f in result)
        total = sum(len(f) for f in result) + 12 + 4 * len(result)
        if biggest <= max_frame_bytes and (max_pak_bytes <= 0 or total <= max_pak_bytes):
            return result, used
        used = candidate
        try:
            result = encode_file_ffmpeg(
                path, size=size, fps=fps, quality=candidate, rotate180=rotate180
            )
            result = adjust_frame_count(result, expected)
        except EncodeError:
            break
    return result, used


def adjust_frame_count(frames: list[bytes], target: int) -> list[bytes]:
    """把帧数对齐到 target：多了均匀抽掉，少了均匀复制。

    ffmpeg 的 fps 滤镜在边界会丢/多帧，导致时长偏短；设备固定 30fps 播放，
    帧数就是时长，所以这里按真实时长效准。
    """
    if target <= 0 or not frames:
        return frames
    count = len(frames)
    if count == target:
        return frames
    if count > target:
        step = count / target
        return [frames[min(count - 1, int(i * step))] for i in range(target)]
    out: list[bytes] = []
    missing = target - count
    for index, frame in enumerate(frames):
        out.append(frame)
        if missing and int((index + 1) * missing / count) > int(index * missing / count):
            out.append(frame)
    return out[:target]


def encode_media_to_pak(
    path: str | Path,
    *,
    quality: int = DEFAULT_QUALITY,
    size: tuple[int, int] = (SCREEN_WIDTH, SCREEN_HEIGHT),
    max_frames: int = 0,
    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES,
    max_pak_bytes: int = DEFAULT_MAX_PAK_BYTES,
    allow_decimation: bool = False,
    strategy: str = STRATEGY_SMOOTH,
    target_fps: int = TARGET_FPS,
    zoom: float = 1.0,
    rotation: str = DEFAULT_ROTATION,
    on_progress: Callable[[int, int], None] | None = None,
    info: MediaInfo | None = None,
) -> EncodedPak:
    """把媒体文件编码成 pak。

    Args:
        path: GIF / PNG / JPEG。
        quality: JPEG 质量 1–95。
        size: 目标尺寸，默认设备实际分辨率 1024×240。
        max_frames: >0 时限制帧数（超出报错）。
        on_progress: ``(已编码, 预计总数)``。
        info: 已有探测结果可复用，省一次解码。

    Raises:
        EncodeError: 没有可用帧、或编码失败。
    """
    media = info or probe_media(Path(path))

    # 官方式快路径：一次 ffmpeg 调用完成解码 + 缩放 + 翻转 + 编码
    if JPEG_BACKEND != "pil" and find_ffmpeg() is not None:
        try:
            raw = encode_file_ffmpeg(
                path,
                size=size,
                fps=target_fps,
                quality=quality,
                rotate180=(rotation in ("180", "flip180")),
            )
            duration_ms = getattr(media, "duration_ms", 0) or 0
            if target_fps > 0 and duration_ms > 0:
                expected = max(1, int(round(duration_ms / (1000 / target_fps))))
                raw = adjust_frame_count(raw, expected)
            if max_frames > 0 and len(raw) > max_frames:
                raise EncodeError(f"帧数 {len(raw)} 超过上限 {max_frames}")
            raw, used = fit_frames_to_budget(
                raw,
                max_frame_bytes=max_frame_bytes,
                max_pak_bytes=max_pak_bytes,
                path=path,
                size=size,
                fps=target_fps,
                rotate180=(rotation in ("180", "flip180")),
                quality=quality,
            )
            if on_progress is not None:
                on_progress(len(raw), len(raw))
            source_fps = 0
            duration_ms = getattr(media, "duration_ms", 0) or 0
            n_frames = getattr(media, "n_frames", 0) or 0
            if duration_ms > 0 and n_frames > 0:
                source_fps = max(0, min(0xFFFF, int(round(n_frames * 1000 / duration_ms))))
            pak = build_pak(raw, fps=source_fps)
            return EncodedPak(
                pak=pak,
                frames=len(raw),
                fps=source_fps,
                quality=used,
                width=size[0],
                height=size[1],
            )
        except EncodeError:
            pass  # 退回纯 Python 路径


    # 按「总容量 ÷ 预计帧数」估算单帧预算。duration_ms 缺失时退回源帧数估算。
    per_frame = FRAME_CAP_BY_STRATEGY.get(strategy, max_frame_bytes)
    if max_pak_bytes > 0:
        media_ms = getattr(media, "duration_ms", 0) or 0
        if target_fps > 0 and media_ms > 0:
            expected_frames = max(1, int(round(media_ms / (1000 / target_fps))))
        else:
            source_frames = max(1, int(getattr(media, "frames_after_decimation", 1) or 1))
            expected_frames = source_frames * max(1, target_fps or 1)
        per_frame = min(per_frame, max(4_000, int(max_pak_bytes / expected_frames)))

    frames: list[bytes] = []
    durations: list[int] = []
    qualities: list[int] = []
    pak = b""
    interval = TARGET_INTERVAL_MS if target_fps > 0 else MIN_INTERVAL_MS

    duration_ms = getattr(media, "duration_ms", 0) or 0
    n_frames = getattr(media, "n_frames", 0) or 0
    source_fps_fallback = (
        max(0, min(0xFFFF, int(round(n_frames * 1000 / duration_ms))))
        if duration_ms > 0 and n_frames > 0 else 0
    )

    # 最多尝试 3 轮：重采样后若仍超预算，逐轮降质重编（绝不抽帧）
    for attempt in range(3):
        frames, durations, qualities = [], [], []
        prepared = list(
            iter_prepared_frames(
                path,
                media,
                size=size,
                max_frames=max_frames,
                zoom=zoom,
                rotation=rotation,
            )
        )
        if on_progress is not None:
            on_progress(0, max(1, len(prepared)))

        pending = [item.image for item in prepared]
        cursor = 0
        chunk = 32
        while cursor < len(pending):
            batch_images = pending[cursor : cursor + chunk]
            for data, used in encode_jpeg_chunk(
                batch_images, max_bytes=per_frame, quality=quality
            ):
                frames.append(data)
                qualities.append(used)
            for item in prepared[cursor : cursor + chunk]:
                durations.append(max(0, item.duration_ms))
            cursor += chunk
            if on_progress is not None:
                on_progress(min(cursor, len(prepared)), max(1, len(prepared)))

        if not frames:
            raise EncodeError("没有可编码的帧", hint="确认文件不是空动画。")

        # 重采样到设备固定帧率：按每帧时长重复/丢弃帧
        if target_fps > 0 and durations:
            step = 1000.0 / target_fps
            resampled: list[bytes] = []
            acc = 0.0
            for frame, duration in zip(frames, durations):
                acc += max(1.0, float(duration))
                repeats = max(1, int(round(acc / step)) - len(resampled))
                resampled.extend([frame] * repeats)
            frames = resampled
            durations = [TARGET_INTERVAL_MS] * len(frames)

        # 仅当显式允许时才抽帧（抽帧会删除剧情）
        if allow_decimation and max_pak_bytes > 0 and frames:
            while _estimate_total(frames) > max_pak_bytes and len(frames) > MIN_FRAMES:
                frames = frames[::2]
                durations = durations[::2]

        if target_fps > 0:
            interval = TARGET_INTERVAL_MS
        else:
            total_ms = sum(durations) or (MIN_INTERVAL_MS * len(frames))
            interval = int(round(total_ms / len(frames)))
            interval = max(MIN_INTERVAL_MS, min(MAX_INTERVAL_MS, interval))

        pak = build_pak(frames, fps=source_fps_fallback, reserved=0)

        # 容量复核：超预算且还有重试机会 → 降质重编
        if max_pak_bytes <= 0 or len(pak) <= max_pak_bytes or attempt == 2:
            break
        per_frame = max(4_000, int(per_frame * 0.7))

    effective = int(round(sum(qualities) / len(qualities))) if qualities else quality
    return EncodedPak(
        pak=pak,
        frames=len(frames),
        fps=source_fps_fallback,
        quality=effective,
        width=size[0],
        height=size[1],
    )
