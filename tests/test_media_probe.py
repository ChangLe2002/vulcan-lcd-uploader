# SPDX-License-Identifier: MIT
"""文件校验测试。

测试样本全部在运行时用 Pillow 生成（``tmp_path``），仓库里不放二进制夹具，
避免"夹具本身损坏"与"仓库体积"两个问题。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from vulcan_lcd.media.probe import (
    CorruptMediaError,
    FileMissingError,
    FileTooLargeError,
    MediaKind,
    UnsupportedFormatError,
    probe_media,
    sniff_kind,
)


# --------------------------------------------------------------------------- #
# 夹具生成
# --------------------------------------------------------------------------- #
def make_gif(path: Path, *, frames: int = 3, duration: int | list[int] = 100, size: tuple[int, int] = (40, 20)) -> Path:
    """生成多帧 GIF。

    两个必须注意的真实行为：
    1. 每帧颜色必须**不同**，否则 Pillow 会把重复帧优化掉，帧数变 1；
    2. 必须显式 ``format="GIF"``，否则 Pillow 按扩展名选编码器（存成 .png 就成了 PNG）；
    3. GIF 的延时就绪单位是 **10ms**，传入 16ms 实际落盘为 10ms，所以测试里
       只用 10ms 的整数倍，避免与量化误差纠缠。
    """
    images = []
    for i in range(frames):
        color = ((i * 50) % 256, (i * 30) % 256, (i * 70) % 256)
        images.append(Image.new("RGB", size, color=color).convert("P"))
    images[0].save(
        path,
        format="GIF",
        save_all=True,
        append_images=images[1:],
        duration=duration,
        loop=0,
    )
    return path


def make_png(path: Path, *, size: tuple[int, int] = (40, 20), mode: str = "RGB") -> Path:
    color = (255, 0, 0, 128) if mode == "RGBA" else (255, 0, 0)
    Image.new(mode, size, color=color).save(path)
    return path


def make_jpeg(path: Path, *, size: tuple[int, int] = (40, 20)) -> Path:
    Image.new("RGB", size, color=(0, 128, 255)).save(path, format="JPEG")
    return path


# --------------------------------------------------------------------------- #
# 魔数嗅探（不看扩展名）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (b"GIF89a....", MediaKind.GIF),
        (b"GIF87a....", MediaKind.GIF),
        (b"\x89PNG\r\n\x1a\n....", MediaKind.PNG),
        (b"\xff\xd8\xff\xe0....", MediaKind.JPEG),
        (b"%PDF-1.7", MediaKind.UNKNOWN),
        (b"", MediaKind.UNKNOWN),
    ],
)
def test_sniff_kind(head: bytes, expected: MediaKind) -> None:
    assert sniff_kind(head) is expected


# --------------------------------------------------------------------------- #
# 正常路径
# --------------------------------------------------------------------------- #
def test_probe_animated_gif(tmp_path: Path) -> None:
    path = make_gif(tmp_path / "anim.gif", frames=3, duration=100)
    info = probe_media(path)

    assert info.kind is MediaKind.GIF
    assert (info.width, info.height) == (40, 20)
    assert info.n_frames == 3
    assert info.duration_ms == 300
    assert info.fps == pytest.approx(10.0)
    assert info.is_animated is True
    assert info.needs_decimation is False
    assert info.frame_stride == 1
    assert info.needs_resize is True
    assert info.extension_mismatch is False


def test_probe_static_png(tmp_path: Path) -> None:
    info = probe_media(make_png(tmp_path / "still.png"))
    assert info.kind is MediaKind.PNG
    assert info.n_frames == 1
    assert info.duration_ms == 0
    assert info.fps is None
    assert info.is_animated is False
    assert info.estimated_payload_bytes == 1024 * 240 * 2


def test_probe_jpeg_accepts_jpg_suffix(tmp_path: Path) -> None:
    info = probe_media(make_jpeg(tmp_path / "photo.jpg"))
    assert info.kind is MediaKind.JPEG
    assert info.extension_mismatch is False


def test_probe_jpeg_accepts_jpeg_suffix(tmp_path: Path) -> None:
    info = probe_media(make_jpeg(tmp_path / "photo.jpeg"))
    assert info.kind is MediaKind.JPEG
    assert info.extension_mismatch is False


def test_probe_detects_rgba_transparency(tmp_path: Path) -> None:
    info = probe_media(make_png(tmp_path / "alpha.png", mode="RGBA"))
    assert info.has_transparency is True


def test_probe_uses_actual_magic_not_extension(tmp_path: Path) -> None:
    """GIF 内容存成 .png：必须识别为 GIF，并标记扩展名不符。"""
    path = tmp_path / "fake.png"
    make_gif(path, frames=2)
    info = probe_media(path)
    assert info.kind is MediaKind.GIF
    assert info.extension_mismatch is True


# --------------------------------------------------------------------------- #
# 帧率与抽帧估算
# --------------------------------------------------------------------------- #
def test_high_fps_gif_needs_decimation(tmp_path: Path) -> None:
    """6 帧 × 20ms（GIF 的 10ms 量化单位下精确）→ 50fps，超过 30fps，stride=2。"""
    info = probe_media(make_gif(tmp_path / "fast.gif", frames=6, duration=20))
    assert info.fps == pytest.approx(50.0)
    assert info.needs_decimation is True
    assert info.frame_stride == 2
    assert info.frames_after_decimation == 3


def test_variable_frame_durations_are_summed(tmp_path: Path) -> None:
    """GIF 允许每帧单独延时，必须逐帧累加而不是首帧×帧数。"""
    info = probe_media(make_gif(tmp_path / "var.gif", frames=2, duration=[50, 150]))
    assert info.duration_ms == 200
    assert info.fps == pytest.approx(10.0)


def test_25fps_is_not_decimated(tmp_path: Path) -> None:
    """3 帧 × 40ms = 120ms → 25fps，低于 30，不抽帧。"""
    info = probe_media(make_gif(tmp_path / "ok.gif", frames=3, duration=40))
    assert info.fps == pytest.approx(25.0)
    assert info.needs_decimation is False
    assert info.frame_stride == 1


def test_payload_estimate_uses_target_resolution(tmp_path: Path) -> None:
    info = probe_media(make_gif(tmp_path / "anim.gif", frames=4, duration=100))
    assert info.estimated_payload_bytes == 1024 * 240 * 2 * 4


# --------------------------------------------------------------------------- #
# 拒绝路径
# --------------------------------------------------------------------------- #
def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileMissingError, match="不存在"):
        probe_media(tmp_path / "nope.gif")


def test_directory_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FileMissingError, match="不是一个文件"):
        probe_media(tmp_path)


def test_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.gif"
    path.write_bytes(b"")
    with pytest.raises(CorruptMediaError, match="为空"):
        probe_media(path)


def test_size_limit_rejected_before_decoding(tmp_path: Path) -> None:
    path = make_png(tmp_path / "big.png")
    with pytest.raises(FileTooLargeError, match="上限"):
        probe_media(path, max_bytes=10)


def test_size_limit_message_mentions_shrinking(tmp_path: Path) -> None:
    path = make_png(tmp_path / "big.png")
    with pytest.raises(FileTooLargeError) as excinfo:
        probe_media(path, max_bytes=10)
    assert "缩小" in excinfo.value.user_message()


def test_unsupported_format(tmp_path: Path) -> None:
    path = tmp_path / "notes.gif"
    path.write_text("这不是图片，只是文本。", encoding="utf-8")
    with pytest.raises(UnsupportedFormatError, match="无法识别的文件格式"):
        probe_media(path)


def test_disallowed_kind(tmp_path: Path) -> None:
    path = make_gif(tmp_path / "anim.gif")
    with pytest.raises(UnsupportedFormatError, match="不接受"):
        probe_media(path, allowed=(MediaKind.PNG,))


def test_corrupt_gif_with_valid_magic(tmp_path: Path) -> None:
    path = tmp_path / "broken.gif"
    path.write_bytes(b"GIF89a" + b"\x00" * 32)
    with pytest.raises(CorruptMediaError, match="无法解码"):
        probe_media(path)


def test_apng_is_rejected_explicitly(tmp_path: Path) -> None:
    """多帧 PNG 必须明确拒绝：否则 UI 显示"3 帧"而实际只上传第一帧。"""
    path = tmp_path / "anim.png"
    frames = [Image.new("RGB", (64, 64), (i * 80, 0, 0)) for i in range(3)]
    frames[0].save(path, format="PNG", save_all=True, append_images=frames[1:], duration=100, loop=0)

    with pytest.raises(UnsupportedFormatError, match="APNG"):
        probe_media(path)


def test_gif_without_frame_delay_is_marked_estimated(tmp_path: Path) -> None:
    """GIF 允许不写帧延时（等价"尽可能快"）：按 100ms/帧兜底，但必须标记为估算。"""
    info = probe_media(make_gif(tmp_path / "nodelay.gif", frames=3, duration=0))

    assert info.duration_estimated is True
    assert info.duration_ms == 300
    assert info.fps == pytest.approx(10.0)
    assert "估算" in info.describe()


def test_normal_gif_is_not_marked_estimated(tmp_path: Path) -> None:
    info = probe_media(make_gif(tmp_path / "normal.gif", frames=3, duration=100))
    assert info.duration_estimated is False


# --------------------------------------------------------------------------- #
# 序列化与文案
# --------------------------------------------------------------------------- #
def test_as_dict_is_json_safe(tmp_path: Path) -> None:
    info = probe_media(make_gif(tmp_path / "anim.gif", frames=3, duration=100))
    data = info.as_dict()
    assert data["kind"] == "gif"
    assert data["n_frames"] == 3
    assert data["fps"] == 10.0
    assert isinstance(data["size_mb"], float)
    assert data["needs_resize"] is True


def test_describe_mentions_key_facts(tmp_path: Path) -> None:
    info = probe_media(make_gif(tmp_path / "anim.gif", frames=3, duration=100))
    text = info.describe()
    assert "GIF" in text
    assert "3 帧" in text
    assert "10.0 fps" in text
    assert "1024x240" in text


def test_error_codes_are_stable() -> None:
    assert FileMissingError.error_code == "MEDIA_MISSING"
    assert FileTooLargeError.error_code == "MEDIA_TOO_LARGE"
    assert UnsupportedFormatError.error_code == "MEDIA_UNSUPPORTED"
    assert CorruptMediaError.error_code == "MEDIA_CORRUPT"
