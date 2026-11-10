# SPDX-License-Identifier: MIT
"""从抓包里还原 pak 文件，并核对公告帧里的「大小」与「16 位累加和」。

支持**一次抓包里包含多次上传**：以公告帧 `e31c` 为分段点，后续数据块归入该段。
每段独立校验 ``len == size`` 且 ``sum16 == checksum``。

这是对协议理解的**闭环自检**，比"上传后看屏幕变没变"精确得多。

用法::

    python tools/extract_pak.py capture.txt                 # 校验每一段
    python tools/extract_pak.py capture.txt --out pak.bin   # 只导出唯一/第一段
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

HEADER = bytes.fromhex("5a9fa9")
DATA_ID = bytes.fromhex("e41b")
ANNOUNCE_ID = bytes.fromhex("e31c")
BLOCK_HEAD = 9      # 5A9FA9 40 06 E41B <idx 2B>
BLOCK_TAIL = 2      # 16 位累加和（大端）


@dataclass
class Segment:
    """一次上传事务。"""

    name: str
    size: int
    checksum: int
    flag: str
    version: int
    blocks: int = 0
    data: bytearray = field(default_factory=bytearray)

    def result(self) -> tuple[bool, bool]:
        pak = bytes(self.data[: self.size])
        return (
            len(pak) == self.size,
            (sum(pak) & 0xFFFF) == self.checksum,
        )


def load_chunks(path: Path) -> list[bytes]:
    chunks: list[bytes] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        cleaned = re.sub(r"[^0-9a-fA-F]", "", line.strip())
        if cleaned and len(cleaned) % 2 == 0:
            chunks.append(bytes.fromhex(cleaned))
    return chunks


def parse_announce(chunk: bytes) -> Segment | None:
    if len(chunk) < 13 or chunk[:3] != HEADER or chunk[5:7] != ANNOUNCE_ID:
        return None
    total = chunk[4] + 5
    frame = chunk[:total]
    if b".pak" not in frame:
        return None
    payload = frame[7 : total - 2]      # 去掉 帧头+seq+len+ID 与 尾校验
    if len(payload) < 9:
        return None
    name = payload[8:].split(b"\x00", 1)[0].decode("ascii", "replace")
    return Segment(
        name=name,
        size=int.from_bytes(payload[2:5], "big"),
        checksum=int.from_bytes(payload[5:7], "big"),
        flag=payload[0:2].hex(" "),
        version=payload[7],
    )


def is_data_block(chunk: bytes) -> bool:
    return (
        len(chunk) > BLOCK_HEAD + BLOCK_TAIL
        and chunk[:3] == HEADER
        and chunk[5:7] == DATA_ID
    )


def segment_stream(chunks: list[bytes]) -> list[Segment]:
    segments: list[Segment] = []
    current: Segment | None = None
    for chunk in chunks:
        announce = parse_announce(chunk)
        if announce is not None:
            current = announce
            segments.append(current)
            continue
        if current is not None and is_data_block(chunk):
            if len(current.data) < current.size:
                current.data += chunk[BLOCK_HEAD : len(chunk) - BLOCK_TAIL]
            current.blocks += 1
    return segments


def describe_container(pak: bytes) -> None:
    if pak[:2] != b"JP":
        return
    frames = struct.unpack("<H", pak[2:4])[0]
    interval = struct.unpack("<H", pak[4:6])[0]
    reserved = struct.unpack("<H", pak[6:8])[0]
    print(f"      容器: 'JP' 帧数={frames} 间隔={interval} 保留={reserved}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="从抓包还原 pak 并核对协议理解")
    ap.add_argument("input")
    ap.add_argument("--out", default=None, help="把第一段导出为该文件")
    args = ap.parse_args(argv)

    chunks = load_chunks(Path(args.input))
    print(f"传输块 {len(chunks)}")
    segments = segment_stream(chunks)
    if not segments:
        print("未找到公告帧（e31c + .pak），无法校验。", file=sys.stderr)
        return 1

    print(f"识别到 {len(segments)} 次上传\n")
    all_ok = True
    for index, seg in enumerate(segments, 1):
        pak = bytes(seg.data[: seg.size])
        size_ok, sum_ok = seg.result()
        all_ok = all_ok and size_ok and sum_ok
        print(f"[{index}] {seg.name}  size={seg.size} checksum=0x{seg.checksum:04X} "
              f"flag={seg.flag} ver={seg.version}")
        print(f"      收到 {seg.blocks} 块 / {len(seg.data)} 字节")
        print(f"      大小一致: {size_ok}   校验一致: {sum_ok}"
              f"   (实算 0x{(sum(pak) & 0xFFFF):04X})")
        describe_container(pak)

    out = Path(args.out) if args.out else Path(args.input).with_suffix(".pak")
    out.write_bytes(bytes(segments[0].data[: segments[0].size]))
    print(f"\n已导出第一段: {out}")
    print("结论：全部通过 ✓" if all_ok else "结论：存在不一致 ✗")
    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
