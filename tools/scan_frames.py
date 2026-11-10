# SPDX-License-Identifier: MIT
"""在抓包里扫描**每一个 USB 传输内部**的所有协议帧。

为什么需要它
------------
``decode_capture.py`` 只从每个传输的**起始位置**切帧，遇到"数据块 + 后续指令"
挤在同一个 URB 里时，后面的指令会被整体丢弃。

样本 3 已经证明这种打包确实存在：492 个数据块却有 6 MB 数据，说明多个帧合并在
同一次传输里。要找"上传完成后的提交/切屏指令"，必须扫描传输内部。

用法::

    python tools/scan_frames.py capture4.txt
    python tools/scan_frames.py capture4.txt --all
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HEADER = bytes.fromhex("5a9fa9")
DATA_ID = bytes.fromhex("e41b")
ANNOUNCE_ID = bytes.fromhex("e31c")
HEARTBEAT_ID = bytes.fromhex("e51a")
HANDSHAKE_ID = bytes.fromhex("ea15")


def load_chunks(path: Path) -> list[bytes]:
    chunks: list[bytes] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        cleaned = re.sub(r"[^0-9a-fA-F]", "", line.strip())
        if cleaned and len(cleaned) % 2 == 0:
            chunks.append(bytes.fromhex(cleaned))
    return chunks


def scan_chunk(chunk: bytes) -> list[tuple[int, bytes]]:
    """在单个传输内找出所有可解析的帧，返回 [(offset, frame)]。"""
    found: list[tuple[int, bytes]] = []
    index = 0
    length = len(chunk)
    while index < length - 4:
        if chunk[index : index + 3] != HEADER:
            index += 1
            continue
        total = chunk[index + 4] + 5
        if total < 7 or index + total > length:
            index += 1
            continue
        frame = chunk[index : index + total]
        # 校验必须成立，否则只是数据里偶然出现的帧头
        if (sum(frame[:-2]) & 0xFFFF) != int.from_bytes(frame[-2:], "big"):
            index += 1
            continue
        found.append((index, frame))
        index += total
    return found


def describe(frame: bytes) -> str:
    total = frame[4] + 5
    fid = frame[5:7]
    body = frame[7 : total - 2]
    if fid == DATA_ID:
        return f"DATA 块 {int.from_bytes(body[0:2], 'big')} 净荷 {len(frame) - 11}B"
    if fid == ANNOUNCE_ID:
        if len(body) == 3:
            return f"ACK  块 {int.from_bytes(body[0:2], 'big')} 状态 0x{body[2]:02X}"
        name = body[8:].split(b"\x00", 1)[0].decode("ascii", "replace") if len(body) > 8 else ""
        return (
            f"ANN  大小={int.from_bytes(body[2:5], 'big')} "
            f"校验=0x{int.from_bytes(body[5:7], 'big'):04X} flag={body[0:2].hex(' ')} "
            f"名称={name!r}"
        )
    if fid == HEARTBEAT_ID:
        name = body.split(b"\x00", 1)[0].decode("ascii", "replace")
        return f"HEARTBEAT {name}"
    if fid == HANDSHAKE_ID:
        return f"HS   {body.hex(' ')}"
    return f"未知 {fid.hex()} {body.hex(' ')}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="扫描每个传输内部的所有帧")
    ap.add_argument("input")
    ap.add_argument("--all", action="store_true", help="同时打印 ACK 与数据块")
    args = ap.parse_args(argv)

    chunks = load_chunks(Path(args.input))
    print(f"传输块 {len(chunks)}")

    embedded = 0
    total_frames = 0
    timeline: list[str] = []

    for chunk_index, chunk in enumerate(chunks):
        frames = scan_chunk(chunk)
        total_frames += len(frames)
        for offset, frame in frames:
            if offset > 0:
                embedded += 1
            text = describe(frame)
            if not args.all:
                if text.startswith(("ACK", "DATA")):
                    continue
            prefix = f"  #{chunk_index:>4} +{offset:<6}"
            if offset > 0:
                prefix += " [嵌在传输内部] "
            timeline.append(prefix + text)

    print(f"帧总数 {total_frames}，其中 {embedded} 个不在传输起始位置")
    print()
    if timeline:
        print(f"=== 非 ACK/数据 帧时间线（{len(timeline)} 条）===")
        for line in timeline:
            print(line)
    else:
        print("没有找到任何非 ACK/数据 帧。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
