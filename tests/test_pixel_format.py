# SPDX-License-Identifier: MIT
"""RGB565 转换测试。

已知像素值（按 RGB 顺序解释）::

    红 255,0,0    -> 0xF800
    绿 0,255,0    -> 0x07E0
    蓝 0,0,255    -> 0x001F
    白            -> 0xFFFF
    黑            -> 0x0000
    灰 128,128,128 -> 0x8410   (0x8000 | 0x0400 | 0x0010)
"""

from __future__ import annotations

import pytest
from PIL import Image

from vulcan_lcd.media.pixel_format import (
    ByteOrder,
    ChannelOrder,
    PixelFormatError,
    frame_byte_length,
    to_rgb565,
    to_rgb888,
)


def solid(color: tuple[int, int, int], size: tuple[int, int] = (1, 1)) -> Image.Image:
    return Image.new("RGB", size, color)


def value_of(raw: bytes, byte_order: ByteOrder = ByteOrder.LITTLE) -> int:
    return int.from_bytes(raw[:2], byte_order.value)


# --------------------------------------------------------------------------- #
# 已知像素值
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("color", "expected"),
    [
        ((255, 0, 0), 0xF800),
        ((0, 255, 0), 0x07E0),
        ((0, 0, 255), 0x001F),
        ((255, 255, 255), 0xFFFF),
        ((0, 0, 0), 0x0000),
        ((128, 128, 128), 0x8410),
    ],
)
def test_rgb565_known_values(color: tuple[int, int, int], expected: int) -> None:
    raw = to_rgb565(solid(color))
    assert len(raw) == 2
    assert value_of(raw) == expected


def test_rgb565_little_endian_layout() -> None:
    assert to_rgb565(solid((255, 0, 0)), byte_order=ByteOrder.LITTLE) == b"\x00\xf8"


def test_rgb565_big_endian_layout() -> None:
    assert to_rgb565(solid((255, 0, 0)), byte_order=ByteOrder.BIG) == b"\xf8\x00"


def test_bgr_order_swaps_channels() -> None:
    """BGR 顺序下纯红的高位来自 B=0，低位来自 R=255。"""
    raw = to_rgb565(solid((255, 0, 0)), order=ChannelOrder.BGR)
    assert value_of(raw) == 0x001F


def test_bgr_green_unchanged() -> None:
    assert value_of(to_rgb565(solid((0, 255, 0)), order=ChannelOrder.BGR)) == 0x07E0


# --------------------------------------------------------------------------- #
# 长度与形状
# --------------------------------------------------------------------------- #
def test_length_is_two_bytes_per_pixel() -> None:
    img = Image.new("RGB", (4, 3), (10, 20, 30))
    assert len(to_rgb565(img)) == 4 * 3 * 2


def test_frame_byte_length_matches_screen() -> None:
    assert frame_byte_length() == 1024 * 240 * 2 == 491_520


def test_rgb888_bgr_swaps_per_pixel() -> None:
    img = solid((1, 2, 3))
    assert to_rgb888(img) == b"\x01\x02\x03"
    assert to_rgb888(img, order=ChannelOrder.BGR) == b"\x03\x02\x01"


def test_non_rgb_mode_is_converted() -> None:
    gray = Image.new("L", (1, 1), 255)
    assert value_of(to_rgb565(gray)) == 0xFFFF


# --------------------------------------------------------------------------- #
# 错误路径
# --------------------------------------------------------------------------- #
def test_non_image_input_raises() -> None:
    with pytest.raises(PixelFormatError, match="PIL.Image"):
        to_rgb565("not an image")


@pytest.mark.parametrize("bad", [(0, 1), (1, 0), (-5, 5)])
def test_frame_byte_length_rejects_bad_size(bad: tuple[int, int]) -> None:
    with pytest.raises(ValueError):
        frame_byte_length(*bad)


def test_frame_byte_length_rejects_bad_bits() -> None:
    with pytest.raises(ValueError, match="8 的倍数"):
        frame_byte_length(10, 10, bits=12)
