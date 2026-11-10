# SPDX-License-Identifier: MIT
"""分析一次抓包里的传输事务：按时间顺序重建帧序列，推断协议语义。

在 ``decode_capture.py`` 切帧的基础上多做三件事：

1. **按时间顺序**列出帧（含 seq1、长度、payload 预览），看交互节奏；
2. 按固定 ID 统计（数量、seq1 变化、payload 总字节）；
3. 找出"文件名"帧与"数据体"帧，把数据体按顺序拼接，判断它是不是
   原始 RGB565 位图（800×216×2 = 345600 字节/帧）、还是压缩格式（PNG/JPG/GIF）。

用法::

    python tools/analyze_transfer.py capture.txt --format tshark
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from decode_capture import Frame, parse_hex_text, split_frames  # noqa: E402

FRAME_BYTES = 800 * 216 * 2  # 一帧 RGB565 的字节数


def preview_ascii(data: bytes, limit: int = 24) -> str:
    text = "".join(chr(b) if 32 <= b < 127 else "." for b in data[:limit])
    return text


def describe_sequence(frames: list[Frame]) -> str:
    seqs = [f.seq1 for f in frames]
    if len(set(seqs)) == 1:
        return f"固定 {seqs[0]}"
    steps = Counter((b - a) % 256 for a, b in zip(seqs, seqs[1:]))
    common = ", ".join(f"+{k}(x{v})" for k, v in steps.most_common(3))
    return f"{min(seqs)}..{max(seqs)}  步进: {common}"


def signature(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "GIF"
    if data[:4] in (b"GIF8",):
        return "GIF?"
    if data.startswith(b"BM"):
        return "BMP"
    return "未知/裸数据"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="按时间顺序分析一次传输事务")
    ap.add_argument("input")
    ap.add_argument("--format", choices=["raw", "tshark"], default="tshark")
    ap.add_argument("--timeline", type=int, default=30, help="按时间顺序展示前 N 帧")
    args = ap.parse_args(argv)

    text = Path(args.input).read_text(encoding="utf-8", errors="replace")
    buffer = parse_hex_text(text, fmt=args.format)
    result = split_frames(buffer)
    frames = result.frames
    print(f"总字节 {len(buffer)}，切出 {len(frames)} 帧，噪声 {result.orphans}")

    print(f"\n=== 按时间顺序（前 {args.timeline} 帧）===")
    print(f"{'#':>4} {'ID':<6}{'seq1':>5}{'总长':>6}{'payload':>8}  内容预览")
    for index, frame in enumerate(frames[: args.timeline]):
        payload = frame.payload
        print(
            f"{index:>4} {frame.fixed_id:<6}{frame.seq1:>5}{frame.total_len:>6}"
            f"{len(payload):>8}  {preview_ascii(payload)}"
        )

    print("\n=== 按固定 ID 汇总 ===")
    groups: "OrderedDict[str, list[Frame]]" = OrderedDict()
    for frame in frames:
        groups.setdefault(frame.fixed_id, []).append(frame)

    print(f"{'ID':<6}{'帧数':>5}{'payload总字节':>14}{'单包payload':>14}  seq1 情况")
    for fixed_id, group in groups.items():
        total = sum(len(f.payload) for f in group)
        sizes = [len(f.payload) for f in group]
        size_text = f"{min(sizes)}–{max(sizes)}"
        print(f"{fixed_id:<6}{len(group):>5}{total:>14}{size_text:>14}  {describe_sequence(group)}")

    # 文件名帧
    print("\n=== 含文件名的帧 ===")
    for index, frame in enumerate(frames):
        if b".pak" in frame.payload:
            name = frame.payload.split(b"\x00")[0]
            print(f"#{index} [{frame.fixed_id}] seq1={frame.seq1} -> {name!r}")

    # 找数据体最大的 ID，尝试当作图像数据
    if groups:
        data_id, data_frames = max(groups.items(), key=lambda kv: sum(len(f.payload) for f in kv[1]))
        blob = b"".join(f.payload for f in data_frames)
        print(f"\n=== 数据体候选: ID {data_id} ===")
        print(f"  帧数 {len(data_frames)}，拼接后 {len(blob)} 字节")
        print(f"  头 32 字节: {blob[:32].hex(' ')}")
        print(f"  特征: {signature(blob)}")
        ratio = len(blob) / FRAME_BYTES
        print(f"  与 800×216 RGB565 的比值: {ratio:.2f} 帧（{FRAME_BYTES} 字节/帧）")
        if len(blob) >= 16:
            uniq = len(set(blob[:4096]))
            print(f"  前 4KB 唯一字节数: {uniq}（接近 256 说明像压缩/加密数据，较小说明像位图）")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
