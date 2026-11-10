# SPDX-License-Identifier: MIT
"""十六进制格式化：控制台输出与日志截断统一走这里。

两个硬性要求：
1. **必须截断**。生产模式下不经截断地打印整帧图像数据会把日志撑爆（一个 800x216
   RGB565 帧就是 345,600 字节）。
2. 截断后必须让人一眼看出"这是截断过的"，否则会误判成"设备只回了这么点数据"。
"""

from __future__ import annotations

from typing import Iterable

__all__ = ["to_hex", "preview", "hexdump"]

DEFAULT_PREVIEW_BYTES = 32
DEFAULT_DUMP_BYTES = 256


def to_hex(data: bytes | bytearray | memoryview) -> str:
    """连续 hex，无分隔符（便于和抓包工具比对、也便于复制进配置）。"""
    return bytes(data).hex()


def preview(data: bytes | bytearray | memoryview, limit: int = DEFAULT_PREVIEW_BYTES) -> str:
    """单行摘要，形如 ``5a 9f a9 1e ... (36 B)``。"""
    raw = bytes(data)
    if not raw:
        return "<empty>"
    head = raw[:limit]
    text = " ".join(f"{b:02x}" for b in head)
    if len(raw) > limit:
        text += f" ... (+{len(raw) - limit} B)"
    return f"{text} ({len(raw)} B)"


def hexdump(
    data: bytes | bytearray | memoryview,
    *,
    limit: int = DEFAULT_DUMP_BYTES,
    width: int = 16,
    base_offset: int = 0,
) -> str:
    """多行 hexdump，每行 ``偏移  十六进制  可打印字符``。

    Args:
        data: 待打印字节。
        limit: 最多打印多少字节，超出部分只显示汇总行。
        width: 每行字节数。
        base_offset: 起始偏移（用于"这是整帧中的第 N 字节"场景）。
    """
    if width <= 0:
        raise ValueError(f"width 必须为正数，收到 {width}")
    if limit <= 0:
        raise ValueError(f"limit 必须为正数，收到 {limit}")

    raw = bytes(data)
    if not raw:
        return "<empty>"

    shown = raw[:limit]
    lines: list[str] = []
    for i in range(0, len(shown), width):
        chunk = shown[i : i + width]
        offset = base_offset + i
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        # 补齐，保证 ASCII 列对齐
        hex_part = hex_part.ljust(width * 3 - 1)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset:08x}  {hex_part}  |{ascii_part}|")

    if len(raw) > limit:
        lines.append(f"... 已截断，剩余 {len(raw) - limit} 字节未显示（总计 {len(raw)} B）")
    return "\n".join(lines)


def dump_lines(data: bytes, *, limit: int = DEFAULT_DUMP_BYTES) -> Iterable[str]:
    """按行迭代 hexdump，便于逐行写日志。"""
    yield from hexdump(data, limit=limit).splitlines()
