# SPDX-License-Identifier: MIT
"""对比多次抓包，判定公告帧（e31c）里未知字段是常量还是计算值。

背景：实测公告帧结构为

    5A 9F A9 00 15 | E3 1C | 00 00 | <大小 3B BE> | 7F 76 | 01 | "img2.pak" 00 | 校验

其中 ``00 00`` / ``7F 76`` / ``01`` 含义未知。**关键判据**：换一个大小/帧数不同的
素材再抓一次——

* 若这三个字段不变 → 是固定常量，实现时照抄即可；
* 若 ``7F 76`` 变化 → 它是校验/版本相关，必须反推算法。

用法::

    python tools/compare_captures.py capture.txt capture2.txt --format tshark
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

#: 数据块：9 字节包头 + N 字节净荷 + 2 字节校验
BLOCK_HEADER = 9
BLOCK_TRAILER = 2


def load_chunks(path: Path) -> list[bytes]:
    """按传输块读取抓包文本（每行一个 USB 传输）。"""
    chunks: list[bytes] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        cleaned = re.sub(r"[^0-9a-fA-F]", "", line.strip())
        if cleaned and len(cleaned) % 2 == 0:
            chunks.append(bytes.fromhex(cleaned))
    return chunks


def find_announce(chunks: list[bytes]) -> bytes | None:
    for chunk in chunks:
        if chunk[:3] != HEADER or chunk[5:7] != ANNOUNCE_ID:
            continue
        total = chunk[4] + 5
        frame = chunk[:total]
        if b".pak" in frame:
            return frame
    return None


def parse_announce(frame: bytes) -> dict[str, object]:
    """拆公告帧。``frame`` 含完整帧头与校验。"""
    total = frame[4] + 5
    body = frame[5 : total - 2]          # 含固定 ID
    payload = body[2:]                    # 去掉 E3 1C
    name_bytes = payload[8:].split(b"\x00", 1)[0] if len(payload) > 8 else b""
    return {
        "raw_hex": frame.hex(" "),
        "unknown1": payload[0:2].hex(" "),
        "size": int.from_bytes(payload[2:5], "big"),
        "unknown2": payload[5:7].hex(" "),
        "version": payload[7] if len(payload) > 7 else None,
        "name": name_bytes.decode("ascii", errors="replace"),
    }


def collect_blocks(chunks: list[bytes]) -> tuple[int, int, int]:
    """返回 (块数, 净荷总字节, 首块净荷长度)。"""
    sizes: list[int] = []
    for chunk in chunks:
        if len(chunk) <= 1000 or chunk[:3] != HEADER or chunk[5:7] != DATA_ID \
                or chunk[3] != 0x40:
            continue
        sizes.append(len(chunk) - BLOCK_HEADER - BLOCK_TRAILER)
    return len(sizes), sum(sizes), (sizes[0] if sizes else 0)


def analyze(path: Path) -> dict[str, object]:
    chunks = load_chunks(path)
    announce = find_announce(chunks)
    count, payload_bytes, first_len = collect_blocks(chunks)

    heartbeat = ""
    for chunk in chunks:
        if chunk[:3] == HEADER and chunk[5:7] == HEARTBEAT_ID:
            total = chunk[4] + 5
            heartbeat = chunk[7 : total - 2].split(b"\x00", 1)[0].decode("ascii", "replace")
            break

    info: dict[str, object] = {
        "file": path.name,
        "chunks": len(chunks),
        "blocks": count,
        "payload_bytes": payload_bytes,
        "first_block": first_len,
        "heartbeat": heartbeat,
    }
    if announce is not None:
        info.update(parse_announce(announce))
    return info


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="对比多次抓包的公告帧")
    ap.add_argument("inputs", nargs="+")
    args = ap.parse_args(argv)

    rows = [analyze(Path(p)) for p in args.inputs]
    keys = [
        ("file", "文件"),
        ("heartbeat", "心跳文件名"),
        ("blocks", "数据块数"),
        ("payload_bytes", "净荷字节"),
        ("first_block", "首块净荷"),
        ("size", "公告尺寸"),
        ("unknown1", "未知1"),
        ("unknown2", "未知2"),
        ("version", "版本"),
        ("name", "公告文件名"),
    ]

    width = 28
    print(f"{'字段':<12}" + "".join(f"{str(r['file']):>{width}}" for r in rows))
    print("-" * (12 + width * len(rows)))
    for key, label in keys:
        line = f"{label:<12}"
        for row in rows:
            value = row.get(key, "-")
            if isinstance(value, int):
                value = f"{value} (0x{value:X})"
            line += f"{str(value):>{width}}"
        print(line)

    print()
    if len(rows) >= 2 and all("size" in r for r in rows):
        sizes_differ = len({r.get("size") for r in rows}) > 1
        u1_same = len({r.get("unknown1") for r in rows}) == 1
        u2_same = len({r.get("unknown2") for r in rows}) == 1
        ver_same = len({r.get("version") for r in rows}) == 1

        print("结论：")
        print(f"  · 公告尺寸随文件{'变化 ✓' if sizes_differ else '未变化（可疑）'}"
              f"；等于净荷字节：{[r.get('size') == r.get('payload_bytes') for r in rows]}")
        print(f"  · 未知1 {rows[0].get('unknown1')}：{'常量 ✓（照抄）' if u1_same else '随文件变化 → 需反推'}")
        print(f"  · 未知2 {rows[0].get('unknown2')}：{'常量 ✓（照抄）' if u2_same else '随文件变化 → 需反推'}")
        print(f"  · 版本  {rows[0].get('version')}：{'常量 ✓' if ver_same else '随文件变化'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
