# SPDX-License-Identifier: MIT
"""抓包解析：把一段串口/ USB 抓包字节切成协议帧并做结构分析。

为什么需要它
------------
抓到的原始数据是一大坨连续字节，肉眼找 ``5A 9F A9`` 既慢又容易错位。
这个工具做四件事：

1. 按帧头 + 长度字段切帧（缺一不可，否则会把 payload 里的偶然字节当帧头）；
2. 同时用**大端**和**小端**验算校验和，并告诉你哪种成立——这直接回答
   "图片帧的校验和是不是也走大端"这个未知项；
3. 按 body 固定 ID 分组统计（``DD 22`` = 时间/标题帧，``E0 1F`` = 握手应答，
   其它 ID 很可能就是图像通道）；
4. 可选把每帧导出成 ``.bin``，方便后续逐帧比对。

用法::

    python tools/decode_capture.py capture.txt
    python tools/decode_capture.py capture.txt --dump-dir frames
    python tools/decode_capture.py capture.txt --format tshark
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

HEADER = b"\x5a\x9f\xa9"
LENGTH_OFFSET = 4
LENGTH_BIAS = 5

_HEX_ONLY = re.compile(r"[^0-9a-fA-F]")


@dataclass
class Frame:
    """切出来的一帧。"""

    offset: int
    data: bytes

    @property
    def total_len(self) -> int:
        return len(self.data)

    @property
    def seq1(self) -> int:
        return self.data[3]

    @property
    def length_field(self) -> int:
        return self.data[LENGTH_OFFSET]

    @property
    def body(self) -> bytes:
        return self.data[5:-2]

    @property
    def fixed_id(self) -> str:
        return self.body[:2].hex() if len(self.body) >= 2 else "??"

    @property
    def payload(self) -> bytes:
        """去掉固定 ID 后的内容，用于看图像数据特征。"""
        return self.body[2:] if len(self.body) >= 2 else b""

    @property
    def checksum_stored(self) -> int:
        return int.from_bytes(self.data[-2:], "big")

    @property
    def checksum_be(self) -> int:
        return sum(self.data[:-2]) & 0xFFFF

    @property
    def checksum_le(self) -> int:
        return int.from_bytes(self.data[-2:], "little")

    @property
    def be_ok(self) -> bool:
        return self.checksum_stored == self.checksum_be

    @property
    def le_ok(self) -> bool:
        raw = self.data[-2:]
        return int.from_bytes(raw, "little") == self.checksum_be


@dataclass
class DecodeResult:
    frames: list[Frame] = field(default_factory=list)
    orphans: int = 0          # 无法成帧的字节数
    truncated: int = 0        # 帧头正确但长度不足的个数


def parse_hex_text(text: str, *, fmt: str = "raw") -> bytes:
    """把各种十六进制文本变成字节。

    * ``raw``：允许空格/换行/冒号/短横线，也允许 ``0x`` 前缀；
    * ``tshark``：每行一个不带空格的十六进制串（``-T fields -e usb.capdata`` 的输出），
      空行与 ``(null)`` 会被跳过。
    """
    if fmt not in {"raw", "tshark"}:
        raise ValueError(f"未知格式: {fmt}")

    chunks: list[bytes] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if fmt == "tshark":
            if line.lower() in {"(null)", "null", "-"}:
                continue
            cleaned = _HEX_ONLY.sub("", line)
        else:
            cleaned = _HEX_ONLY.sub("", line.replace("0x", "").replace("0X", ""))
        if not cleaned:
            continue
        if len(cleaned) % 2:
            # 奇数长度说明这行被截断或混入了非十六进制内容，跳过并提示
            chunks.append(bytes.fromhex(cleaned[:-1]))
            continue
        chunks.append(bytes.fromhex(cleaned))
    return b"".join(chunks)


def split_frames(buffer: bytes, *, min_total: int = 6) -> DecodeResult:
    """按 ``5A 9F A9`` + 长度字段切帧。

    只在"帧头 + 长度字段自洽 + 完整落在缓冲区里"时才认为是一帧，
    避免 payload 里偶然出现的 ``5A 9F A9`` 造成错位。
    """
    result = DecodeResult()
    index = 0
    length = len(buffer)

    while index < length - 2:
        if buffer[index : index + 3] != HEADER:
            index += 1
            result.orphans += 1
            continue

        if index + LENGTH_BIAS > length:
            result.truncated += 1
            break

        total = buffer[index + LENGTH_OFFSET] + LENGTH_BIAS
        if total < min_total:
            # 长度字段不可信：当作噪声，继续往后找
            index += 1
            result.orphans += 1
            continue
        if index + total > length:
            # 帧头对、长度也合理，但数据没抓全 —— 这是"截断"，比"噪声"更值得报告
            result.truncated += 1
            break

        result.frames.append(Frame(offset=index, data=bytes(buffer[index : index + total])))
        index += total

    return result


def summarize(result: DecodeResult) -> str:
    """生成人类可读的统计报告。"""
    lines: list[str] = []
    lines.append(f"帧数: {len(result.frames)}    噪声字节: {result.orphans}    截断: {result.truncated}")
    if not result.frames:
        return "\n".join(lines)

    by_id: dict[str, list[Frame]] = {}
    for frame in result.frames:
        by_id.setdefault(frame.fixed_id, []).append(frame)

    lines.append("")
    lines.append(f"{'固定ID':<8}{'帧数':>6}{'总长范围':>14}{'payload 范围':>16}{'大端校验':>10}{'小端校验':>10}")
    lines.append("-" * 70)
    for fixed_id, frames in sorted(by_id.items(), key=lambda kv: -len(kv[1])):
        totals = [f.total_len for f in frames]
        payloads = [len(f.payload) for f in frames]
        be = sum(1 for f in frames if f.be_ok)
        le = sum(1 for f in frames if f.le_ok)
        lines.append(
            f"{fixed_id:<8}{len(frames):>6}"
            f"{f'{min(totals)}–{max(totals)}':>14}"
            f"{f'{min(payloads)}–{max(payloads)}':>16}"
            f"{f'{be}/{len(frames)}':>10}"
            f"{f'{le}/{len(frames)}':>10}"
        )

    lines.append("")
    lines.append("解读要点：")
    if any(f.be_ok for f in result.frames) and not any(f.le_ok for f in result.frames):
        lines.append("  · 只有大端成立 → 与文字帧一致，图片帧很可能也是大端。")
    elif any(f.le_ok for f in result.frames) and not any(f.be_ok for f in result.frames):
        lines.append("  · 只有小端成立 → 图片通道与文字帧字节序不同，这是个重要发现。")
    elif any(f.be_ok for f in result.frames) and any(f.le_ok for f in result.frames):
        lines.append("  · 两种都成立（校验值为回文或样本少），需要用更多样本再判断。")
    else:
        lines.append("  · 两种都不成立 → 可能不是我校验范围（0..总长−3），需要检查抓包边界。")

    unknown = [fid for fid in by_id if fid not in {"dd22", "e01f"}]
    if unknown:
        lines.append(f"  · 出现未知固定 ID: {', '.join(unknown)} —— 这些很可能就是图像通道。")
    return "\n".join(lines)


def dump_frames(result: DecodeResult, out_dir: Path, *, limit: int = 200) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for index, frame in enumerate(result.frames[:limit]):
        (out_dir / f"frame_{index:04d}_{frame.fixed_id}.bin").write_bytes(frame.data)
        written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="抓包切帧与结构分析")
    ap.add_argument("input", help="抓包文本（十六进制）")
    ap.add_argument("--format", choices=["raw", "tshark"], default="raw")
    ap.add_argument("--dump-dir", default=None, help="把每帧导出为 .bin")
    ap.add_argument("--show", type=int, default=3, help="每种 ID 展示前几帧的十六进制")
    args = ap.parse_args(argv)

    path = Path(args.input)
    if not path.is_file():
        print(f"文件不存在: {path}", file=sys.stderr)
        return 2

    buffer = parse_hex_text(path.read_text(encoding="utf-8", errors="replace"), fmt=args.format)
    print(f"原始字节: {len(buffer)}")
    result = split_frames(buffer)
    print(summarize(result))

    if args.show > 0 and result.frames:
        print("\n样本帧：")
        seen: dict[str, int] = {}
        for frame in result.frames:
            count = seen.get(frame.fixed_id, 0)
            if count >= args.show:
                continue
            seen[frame.fixed_id] = count + 1
            preview = frame.data[:64].hex(" ")
            print(f"  [{frame.fixed_id}] {frame.total_len}B  {preview}" + (" ..." if frame.total_len > 64 else ""))

    if args.dump_dir:
        count = dump_frames(result, Path(args.dump_dir))
        print(f"\n已导出 {count} 帧到 {args.dump_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
