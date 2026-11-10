# SPDX-License-Identifier: MIT
"""像素格式转换：RGB → 设备可接受的字节流。

**当前状态：接口已定，字节排列未验证（experimental）。**

公开资料没有说明智屏真正接受哪种排列。已知的可能是：

* 通道顺序：RGB 还是 BGR；
* 16 位字节序：低字节在前还是高字节在前。

所以这里把三种可能做成**显式参数**，默认值只是占位，不代表事实。
抓包/实测确认后，只需改一处默认值或配置项，不用翻遍代码。
未确认前，任何调用都不得把结果写进串口——由 :mod:`vulcan_lcd.features.gate`
的 ``media.pixel_format_verified`` 闸门负责拦截。
"""

from __future__ import annotations

from enum import Enum

from ..constants import SCREEN_HEIGHT, SCREEN_WIDTH

__all__ = [
    "ChannelOrder",
    "ByteOrder",
    "PixelFormatError",
    "to_rgb565",
    "to_rgb888",
    "frame_byte_length",
]


class ChannelOrder(str, Enum):
    """通道顺序。"""

    RGB = "rgb"
    BGR = "bgr"


class ByteOrder(str, Enum):
    """16 位像素的字节序。"""

    LITTLE = "little"   # 低字节在前
    BIG = "big"         # 高字节在前


class PixelFormatError(Exception):
    """转换失败。"""

    error_code = "PIXEL_FORMAT_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def frame_byte_length(width: int = SCREEN_WIDTH, height: int = SCREEN_HEIGHT, bits: int = 16) -> int:
    """单帧字节数。用于 UI 预估与分包计算。"""
    if width <= 0 or height <= 0:
        raise ValueError(f"尺寸非法: {width}x{height}")
    if bits % 8:
        raise ValueError(f"位深必须是 8 的倍数: {bits}")
    return width * height * (bits // 8)


def _require_rgb_bytes(img: object) -> tuple[int, int, bytes]:
    try:
        from PIL import Image  # noqa: PLC0415 - 延迟导入，避免无图像场景加载 Pillow
    except ImportError as exc:  # pragma: no cover
        raise PixelFormatError("Pillow 未安装") from exc

    if not isinstance(img, Image.Image):
        raise PixelFormatError(f"需要 PIL.Image，收到 {type(img).__name__}")
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img.width, img.height, img.tobytes()


def to_rgb888(img: object, *, order: ChannelOrder = ChannelOrder.RGB) -> bytes:
    """交错 RGB（或 BGR）字节流，每像素 3 字节。"""
    width, height, raw = _require_rgb_bytes(img)
    if order is ChannelOrder.RGB:
        return raw
    out = bytearray(len(raw))
    for i in range(0, len(raw), 3):
        out[i] = raw[i + 2]
        out[i + 1] = raw[i + 1]
        out[i + 2] = raw[i]
    return bytes(out)


def to_rgb565(
    img: object,
    *,
    order: ChannelOrder = ChannelOrder.RGB,
    byte_order: ByteOrder = ByteOrder.LITTLE,
) -> bytes:
    """转换为 RGB565（每像素 2 字节）。

    位布局（按 RGB 顺序解释时）::

        bit 15..11 = R5
        bit 10..5  = G6
        bit 4..0   = B5

    注意：``order`` 影响"把哪个通道放到高位"，``byte_order`` 只影响两个字节
    谁先谁后。二者都要等抓包确认。
    """
    width, height, raw = _require_rgb_bytes(img)
    if len(raw) != width * height * 3:
        raise PixelFormatError(f"像素缓冲区长度异常: {len(raw)}")

    out = bytearray(width * height * 2)
    swap = order is ChannelOrder.BGR
    big = byte_order is ByteOrder.BIG

    j = 0
    for i in range(0, len(raw), 3):
        r = raw[i]
        g = raw[i + 1]
        b = raw[i + 2]
        if swap:
            r, b = b, r
        value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        if big:
            out[j] = (value >> 8) & 0xFF
            out[j + 1] = value & 0xFF
        else:
            out[j] = value & 0xFF
            out[j + 1] = (value >> 8) & 0xFF
        j += 2
    return bytes(out)
