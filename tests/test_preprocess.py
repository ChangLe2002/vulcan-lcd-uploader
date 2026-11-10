# SPDX-License-Identifier: MIT
"""图像预处理测试：尺寸、裁切、透明、EXIF、抽帧与时长。

最核心的三条断言：
1. 输出尺寸**永远**是 1024x240；
2. 抽帧后总时长不变（否则动画会变快）；
3. 透明像素必须变成确定的底色，不能留 alpha 到下游。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from vulcan_lcd.media.preprocess import (
    PreprocessError,
    apply_exif_orientation,
    flatten_alpha,
    iter_prepared_frames,
    prepare_image,
    prepare_media,
    rotate_image,
    summarize,
)
from vulcan_lcd.media.probe import probe_media

TARGET = (1024, 240)


def make_gif(path: Path, *, frames: int = 6, duration: int = 20, size: tuple[int, int] = (320, 180)) -> Path:
    images = []
    for i in range(frames):
        color = ((i * 40) % 256, (i * 70) % 256, (i * 110) % 256)
        images.append(Image.new("RGB", size, color).convert("P"))
    images[0].save(
        path, format="GIF", save_all=True, append_images=images[1:], duration=duration, loop=0
    )
    return path


# --------------------------------------------------------------------------- #
# 尺寸与裁切
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "size",
    [(4000, 100), (100, 4000), (1024, 240), (10, 10), (1920, 1080), (240, 1024)],
)
def test_output_is_always_exact_target(size: tuple[int, int]) -> None:
    out = prepare_image(Image.new("RGB", size, (120, 30, 200)))
    assert out.size == TARGET
    assert out.mode == "RGB"


def test_transparent_area_becomes_black() -> None:
    img = Image.new("RGBA", (10, 10), (255, 0, 0, 0))
    out = flatten_alpha(img)
    assert out.mode == "RGB"
    assert out.getpixel((0, 0)) == (0, 0, 0)


def test_semi_transparent_blends_toward_background() -> None:
    img = Image.new("RGBA", (1, 1), (255, 0, 0, 128))
    out = flatten_alpha(img)
    r, g, b = out.getpixel((0, 0))
    assert 120 <= r <= 135
    assert g == 0 and b == 0


def test_background_is_configurable() -> None:
    img = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
    out = flatten_alpha(img, background=(255, 255, 255))
    assert out.getpixel((0, 0)) == (255, 255, 255)


def test_palette_transparency_is_flattened() -> None:
    img = Image.new("P", (4, 4), 0)
    img.info["transparency"] = 0
    out = flatten_alpha(img)
    assert out.mode == "RGB"


def test_opaque_rgb_passes_through() -> None:
    out = flatten_alpha(Image.new("RGB", (2, 2), (9, 9, 9)))
    assert out.getpixel((0, 0)) == (9, 9, 9)


# --------------------------------------------------------------------------- #
# EXIF 方向
# --------------------------------------------------------------------------- #
def test_exif_orientation_is_applied(tmp_path: Path) -> None:
    """Orientation=6 表示顺时针转 90°，处理后宽高应互换。"""
    path = tmp_path / "rotated.jpg"
    img = Image.new("RGB", (100, 50), (200, 10, 10))
    exif = img.getexif()
    exif[0x0112] = 6
    img.save(path, exif=exif)

    with Image.open(path) as loaded:
        assert loaded.size == (100, 50)
        oriented = apply_exif_orientation(loaded)
        assert oriented.size == (50, 100)


def test_missing_exif_is_ignored() -> None:
    img = Image.new("RGB", (30, 20), (0, 0, 0))
    assert apply_exif_orientation(img).size == (30, 20)


# --------------------------------------------------------------------------- #
# 序列：抽帧与时长
# --------------------------------------------------------------------------- #
def test_high_fps_gif_is_decimated_and_keeps_total_duration(tmp_path: Path) -> None:
    """6 帧 × 20ms = 120ms；stride=2 → 3 帧，每帧 40ms，总时长仍 120ms。"""
    path = make_gif(tmp_path / "fast.gif", frames=6, duration=20)
    info = probe_media(path)
    assert info.frame_stride == 2

    frames = prepare_media(path, info)
    assert len(frames) == 3
    assert all(f.size == TARGET for f in frames)
    assert [f.duration_ms for f in frames] == [40, 40, 40]
    assert sum(f.duration_ms for f in frames) == info.duration_ms


def test_slow_gif_keeps_all_frames(tmp_path: Path) -> None:
    path = make_gif(tmp_path / "slow.gif", frames=3, duration=200)
    info = probe_media(path)
    frames = prepare_media(path, info)
    assert len(frames) == 3
    assert [f.duration_ms for f in frames] == [200, 200, 200]


def test_tail_group_is_not_dropped(tmp_path: Path) -> None:
    """5 帧 stride=2 → 3 组（2+2+1），最后一组只有 1 帧也必须保留。"""
    path = make_gif(tmp_path / "odd.gif", frames=5, duration=20)
    info = probe_media(path)
    frames = prepare_media(path, info)
    assert len(frames) == 3
    assert [len(f.source_indices) for f in frames] == [2, 2, 1]
    assert sum(f.duration_ms for f in frames) == 5 * 20


def test_progress_callback_counts(tmp_path: Path) -> None:
    path = make_gif(tmp_path / "p.gif", frames=4, duration=100)
    info = probe_media(path)
    seen: list[tuple[int, int]] = []
    list(iter_prepared_frames(path, info, on_progress=lambda d, t: seen.append((d, t))))
    assert seen == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_max_frames_guard(tmp_path: Path) -> None:
    path = make_gif(tmp_path / "big.gif", frames=6, duration=100)
    info = probe_media(path)
    with pytest.raises(PreprocessError, match="超过上限"):
        prepare_media(path, info, max_frames=3)


def test_summary_reports_dropped_frames(tmp_path: Path) -> None:
    path = make_gif(tmp_path / "fast.gif", frames=6, duration=20)
    info = probe_media(path)
    frames = prepare_media(path, info)
    summary = summarize(frames, info)
    assert summary.frame_count == 3
    assert summary.dropped_frames == 3
    assert summary.bytes_per_frame == 1024 * 240 * 2
    assert summary.total_bytes == 3 * 1024 * 240 * 2
    assert "3 帧" in summary.describe()


def test_static_image_produces_one_frame(tmp_path: Path) -> None:
    path = tmp_path / "still.png"
    Image.new("RGB", (1920, 1080), (5, 6, 7)).save(path)
    info = probe_media(path)
    frames = prepare_media(path, info)
    assert len(frames) == 1
    assert frames[0].duration_ms == 0
    assert frames[0].size == TARGET


def test_broken_file_raises_preprocess_error(tmp_path: Path) -> None:
    valid = tmp_path / "still.png"
    Image.new("RGB", (10, 10)).save(valid)
    info = probe_media(valid)

    broken = tmp_path / "broken.gif"
    broken.write_bytes(b"GIF89a" + bytes(64))
    with pytest.raises(PreprocessError, match="无法解码"):
        list(iter_prepared_frames(broken, info))


# --------------------------------------------------------------------------- #
# 竖装预览用的旋转（只影响预览，不进入发送链路）
# --------------------------------------------------------------------------- #
def test_rotate_clockwise_swaps_dimensions() -> None:
    src = Image.new("RGB", (1024, 240), (10, 20, 30))
    out = rotate_image(src, clockwise=True)
    assert out.size == (240, 1024)


def test_rotate_counter_clockwise_swaps_dimensions() -> None:
    src = Image.new("RGB", (1024, 240), (10, 20, 30))
    out = rotate_image(src, clockwise=False)
    assert out.size == (240, 1024)


def test_rotate_clockwise_maps_corner_exactly() -> None:
    """2×1 的 [A B] 顺时针转 90° 后应是竖着的 A 在上、B 在下，且无插值失真。"""
    src = Image.new("RGB", (2, 1))
    src.putpixel((0, 0), (255, 0, 0))   # A
    src.putpixel((1, 0), (0, 255, 0))   # B

    out = rotate_image(src, clockwise=True)
    assert out.size == (1, 2)
    assert out.getpixel((0, 0)) == (255, 0, 0)
    assert out.getpixel((0, 1)) == (0, 255, 0)


def test_rotate_counter_clockwise_maps_corner_exactly() -> None:
    src = Image.new("RGB", (2, 1))
    src.putpixel((0, 0), (255, 0, 0))
    src.putpixel((1, 0), (0, 255, 0))

    out = rotate_image(src, clockwise=False)
    assert out.size == (1, 2)
    assert out.getpixel((0, 0)) == (0, 255, 0)
    assert out.getpixel((0, 1)) == (255, 0, 0)


def test_rotate_is_lossless_for_flat_colors() -> None:
    """纯色图旋转后必须仍是同一个颜色（插值会引入偏差）。"""
    src = Image.new("RGB", (1024, 240), (37, 113, 199))
    out = rotate_image(src, clockwise=True)
    assert out.getpixel((0, 0)) == (37, 113, 199)
    assert out.getpixel((215, 799)) == (37, 113, 199)


# --------------------------------------------------------------------------- #
# 原始尺寸贴图（官方行为，2026-11-06 实测确认）
# --------------------------------------------------------------------------- #
def test_native_mode_keeps_source_size() -> None:
    """native 模式不缩放：内容贴左上，右侧/下方补黑。"""
    from PIL import Image

    from vulcan_lcd.media.preprocess import fit_to_screen

    img = Image.new("RGB", (800, 216), (200, 30, 30))
    out = fit_to_screen(img, (1024, 240), mode="native")

    assert out.size == (1024, 240)
    assert out.getpixel((0, 0)) == (200, 30, 30)          # 左上角是原图
    assert out.getpixel((799, 215)) == (200, 30, 30)      # 原始右下角仍在
    assert out.getpixel((900, 120)) == (0, 0, 0)          # 右侧补黑
    assert out.getpixel((500, 230)) == (0, 0, 0)          # 下方补黑


def test_native_mode_with_rotation_180() -> None:
    """先旋转再贴图：内容仍贴左上，只是方向转了。"""
    from PIL import Image

    from vulcan_lcd.media.preprocess import fit_to_screen

    img = Image.new("RGB", (800, 216), (10, 20, 30))
    img.putpixel((0, 0), (255, 0, 0))
    rotated = img.transpose(Image.ROTATE_180)
    out = fit_to_screen(rotated, (1024, 240), mode="native")
    # 原左上角的红点旋转后应在原图的右下角位置（799,215）
    assert out.getpixel((799, 215)) == (255, 0, 0)
    assert out.getpixel((900, 120)) == (0, 0, 0)
