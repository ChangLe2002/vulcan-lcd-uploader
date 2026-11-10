"""分析抓包：找出清理无效缓存对应的指令。"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

CAPTURE = Path(r"F:\shuchu\captureA.txt")
HEADER = bytes.fromhex("5a9fa9")

NAMES = {
    0xEA15: "GetSD/握手",
    0xE01F: "GetSetting",
    0xE11E: "SetSetting",
    0xEC13: "SetID",
    0xE31C: "WriteHeader/ACK",
    0xE41B: "WriteData",
    0xE51A: "PlayFile",
    0xE619: "GetFiles",
    0xE718: "DeleteFile",
    0xE916: "SetStartImg",
    0xEB14: "SetOP",
    0xE21D: "PlayOP",
    0xDD22: "Time/标题",
}


def load_chunks() -> list[bytes]:
    chunks: list[bytes] = []
    for line in CAPTURE.read_text(encoding="utf-8", errors="replace").splitlines():
        text = re.sub(r"[^0-9a-fA-F]", "", line.strip())
        if text and len(text) % 2 == 0:
            chunks.append(bytes.fromhex(text))
    return chunks


def parse_frames(chunks: list[bytes]) -> list[bytes]:
    frames: list[bytes] = []
    for chunk in chunks:
        index = 0
        while index + 5 <= len(chunk):
            if chunk[index : index + 3] != HEADER:
                index += 1
                continue
            total = chunk[index + 4] + 5
            if index + total > len(chunk):
                break
            frames.append(chunk[index : index + total])
            index += total
    return frames


def main() -> int:
    chunks = load_chunks()
    frames = parse_frames(chunks)
    print(f"数据块 {len(chunks)}，解析出帧 {len(frames)}")

    counts: Counter[int] = Counter()
    for frame in frames:
        counts[int.from_bytes(frame[5:7], "big")] += 1
    print("\n=== 指令统计 ===")
    for cmd, count in counts.most_common():
        print(f"  {cmd:04X} {NAMES.get(cmd, '未知'):16s} × {count}")

    print("\n=== 全部帧序列（仅非数据块的 body）===")
    for order, frame in enumerate(frames):
        cmd = int.from_bytes(frame[5:7], "big")
        body = frame[7 : len(frame) - 2]
        if cmd == 0xE41B:
            continue
        label = NAMES.get(cmd, "未知")
        shown = body[:48].hex(" ")
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in body[:48])
        print(f"  #{order:3d} {cmd:04X} {label:14s} len={len(body):3d} {shown}  |{text}|")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
