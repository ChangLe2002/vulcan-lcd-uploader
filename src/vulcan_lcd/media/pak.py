# SPDX-License-Identifier: MIT
"""pak 容器：把一串 JPEG 帧打包成设备认识的格式。

格式（由抓包还原，见 ``docs/PROTOCOL.md``）::

    偏移 0    "JP"                      魔数
    偏移 2    uint16 LE = 帧数
    偏移 4    uint16 LE = 帧间隔（ms）
    偏移 6    uint16 LE = 保留（实测 0）
    偏移 8    uint32 LE × N             偏移表，指向每条记录的起点
    ...       逐条记录:  uint32 LE 长度 + JPEG 数据 + 补零对齐到 4 字节

**每条记录带自己的 4 字节长度前缀**，并以 0 补齐到 4 字节边界——
这两点是实测出来的（270/270 条记录的长度都等于其后 JPEG 的实际长度）。

设计约束：
* 只做"打包/解包"，不碰串口，可完全离线测试；
* 解析时严格校验（魔数、表长、偏移单调、长度前缀、JPEG 首尾）；
* 与抓包得到的真实 pak 必须能**逐字节互相验证**（测试里用 2.4MB 真样本回归）。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

__all__ = [
    "MAGIC",
    "HEADER_SIZE",
    "PakError",
    "PakFile",
    "build_pak",
    "parse_pak",
    "sum16",
    "jpeg_frames_from_pak",
]

MAGIC = b"JP"
HEADER_SIZE = 8
_ENTRY_SIZE = 4


class PakError(Exception):
    """pak 结构不合法。"""

    error_code = "PAK_INVALID"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def sum16(data: bytes | bytearray | memoryview) -> int:
    """16 位累加和。公告帧里的"校验"就是它（实测确认，不是 CRC）。"""
    return sum(bytes(data)) & 0xFFFF


@dataclass(frozen=True)
class PakFile:
    """解析结果。"""

    frames: tuple[bytes, ...]
    fps: int
    reserved: int = 0

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @property
    def data_size(self) -> int:
        return sum(len(f) for f in self.frames)


def build_pak(
    frames: list[bytes] | tuple[bytes, ...],
    *,
    fps: int = 0,
    reserved: int = 0,
) -> bytes:
    """把 JPEG 帧列表打包成 pak 字节串。

    Args:
        frames: 每帧的 JPEG 字节（必须非空且以 ``FF D8`` 开头）。
        fps: **源视频帧率**（反编译证实：`iGame_JPG_to_PAK.exe <pak> <sourceFPS>`，
            静态图为 0）。以前误当成"帧间隔毫秒"。
        reserved: 保留字段，实测为 0。

    Raises:
        PakError: 帧为空、不是 JPEG、数量越界。
    """
    if not frames:
        raise PakError("至少需要一帧")
    if len(frames) > 0xFFFF:
        raise PakError(f"帧数过多: {len(frames)} > 65535")
    if not 0 <= fps <= 0xFFFF:
        raise PakError(f"fps 必须是 16 位: {fps}")
    if not 0 <= reserved <= 0xFFFF:
        raise PakError(f"保留字段必须是 16 位: {reserved}")

    for index, frame in enumerate(frames):
        if not frame:
            raise PakError(f"第 {index} 帧为空")
        if not frame.startswith(b"\xff\xd8"):
            raise PakError(f"第 {index} 帧不是 JPEG（缺少 FF D8 头）")

    table_size = HEADER_SIZE + _ENTRY_SIZE * len(frames)
    records: list[bytes] = []
    offsets: list[int] = []
    cursor = table_size
    for frame in frames:
        record = struct.pack("<I", len(frame)) + frame
        padding = (-len(record)) % 4
        record += b"\x00" * padding
        offsets.append(cursor)
        records.append(record)
        cursor += len(record)

    head = bytearray()
    head += MAGIC
    head += struct.pack("<H", len(frames))
    head += struct.pack("<H", fps)
    head += struct.pack("<H", reserved)
    for offset in offsets:
        head += struct.pack("<I", offset)

    return bytes(head) + b"".join(records)


def parse_pak(data: bytes | bytearray | memoryview) -> PakFile:
    """解析 pak，严格校验所有结构性约束。

    Raises:
        PakError: 魔数错、长度不足、偏移表越界、偏移非单调、帧为空。
    """
    raw = bytes(data)
    if len(raw) < HEADER_SIZE:
        raise PakError(f"文件过短: {len(raw)} 字节")
    if raw[:2] != MAGIC:
        raise PakError(f"魔数不是 'JP': {raw[:2]!r}")

    frame_count, fps, reserved = struct.unpack("<HHH", raw[2:8])
    if frame_count == 0:
        raise PakError("帧数为 0")

    table_end = HEADER_SIZE + _ENTRY_SIZE * frame_count
    if table_end > len(raw):
        raise PakError(f"偏移表越界：需要 {table_end} 字节，文件只有 {len(raw)}")

    offsets = [
        struct.unpack("<I", raw[HEADER_SIZE + i * 4 : HEADER_SIZE + (i + 1) * 4])[0]
        for i in range(frame_count)
    ]

    if offsets[0] < table_end:
        raise PakError(f"首帧偏移 {offsets[0]} 落在偏移表内（表结束于 {table_end}）")
    for i in range(1, len(offsets)):
        if offsets[i] <= offsets[i - 1]:
            raise PakError(f"偏移非单调：第 {i} 项 {offsets[i]} <= 前一项 {offsets[i - 1]}")
    if offsets[-1] >= len(raw):
        raise PakError(f"末帧偏移 {offsets[-1]} 超出文件长度 {len(raw)}")

    frames: list[bytes] = []
    for i, start in enumerate(offsets):
        end = offsets[i + 1] if i + 1 < len(offsets) else len(raw)
        record = raw[start:end]
        if len(record) < 4:
            raise PakError(f"第 {i} 条记录过短: {len(record)}")
        declared = struct.unpack("<I", record[:4])[0]
        if declared == 0:
            raise PakError(f"第 {i} 条记录长度为 0")
        if 4 + declared > len(record):
            raise PakError(
                f"第 {i} 条记录声明 {declared} 字节，但只分到 {len(record) - 4} 字节"
            )
        frame = record[4 : 4 + declared]
        if not frame.startswith(b"\xff\xd8"):
            raise PakError(f"第 {i} 条记录不是 JPEG（缺少 FF D8）")
        frames.append(frame)

    return PakFile(frames=tuple(frames), fps=fps, reserved=reserved)


def jpeg_frames_from_pak(data: bytes) -> list[bytes]:
    """便捷函数：只取帧列表。"""
    return list(parse_pak(data).frames)
