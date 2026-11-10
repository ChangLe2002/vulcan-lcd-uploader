# SPDX-License-Identifier: MIT
"""帧构造与解析（按实机事实重写）。

帧结构（``[V]`` 实机验证 2026-11-04）::

    +--------+--------+--------+--------------+----------+
    | 5A 9F  | seq1   | length | body         | checksum |
    | A9 (3) | (1)    | (1)    | (length-2)   | (2, BE)  |
    +--------+--------+--------+--------------+----------+

* ``length = 总长 − 5``，位于偏移 4；
* 偏移 3 是**帧序号 #1**，不是长度；
* checksum = ``sum(前 length+3 字节) & 0xFFFF``，**大端**写入；
* 帧是**变长**的，36 字节只是 title=17 字节时的特例。

本模块是纯函数，不依赖串口 / GUI / 配置文件。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import datetime

from ..constants import (
    BODY_MONTH,
    BODY_OFFSET,
    BODY_SEQ2,
    BODY_TITLE,
    CHECKSUM_SIZE,
    FIXED_ID_TIME,
    HEADER,
    HEADER_SIZE,
    LENGTH_BIAS,
    LENGTH_OFFSET,
    MAX_FRAME_TOTAL,
    MAX_TITLE_CHARS,
    SEQ1_OFFSET,
    TITLE_ALLOWED_CHARS,
    VERSION_VULCAN,
)

__all__ = [
    "VulcanProtocolError",
    "FrameError",
    "ChecksumError",
    "TitleEncoding",
    "FrameInfo",
    "accumulate16",
    "compute_checksum",
    "checksum_bytes",
    "encode_title",
    "decode_title",
    "build_frame",
    "parse_frame",
    "build_time_frame",
]


# --------------------------------------------------------------------------- #
# 异常
# --------------------------------------------------------------------------- #
class VulcanProtocolError(Exception):
    """协议层异常基类。带 ``error_code`` 便于写进结构化日志。"""

    error_code: str = "PROTOCOL_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class FrameError(VulcanProtocolError):
    """帧结构不合法：帧头不符、长度字段与实长不符、字段越界。"""

    error_code = "FRAME_INVALID"


class ChecksumError(VulcanProtocolError):
    """校验和不匹配。"""

    error_code = "CHECKSUM_MISMATCH"


# --------------------------------------------------------------------------- #
# 校验和（大端）
# --------------------------------------------------------------------------- #
def accumulate16(data: bytes | bytearray | memoryview) -> int:
    """对任意字节缓冲区求 16 位累加和（**不做任何截取**）。

    与 :func:`compute_checksum` 的分工必须清楚：
    本函数对传入的全部字节求和；``compute_checksum`` 专用于"完整帧"，内部会
    自动排除末 2 字节校验位。组帧时若把"不含校验的帧头"误传给后者，
    会静默漏算最后两个字节（本项目踩过：差恰好 2）。
    """
    return sum(bytes(data)) & 0xFFFF


def compute_checksum(frame: bytes | bytearray | memoryview) -> int:
    """对**完整帧**求校验值：自动排除末 2 字节校验位。

    调用方直接传完整帧即可，函数内部自己排除校验位——
    这样不可能出现"把校验位也算进校验"的低级错误。
    """
    raw = bytes(frame)
    if len(raw) < CHECKSUM_SIZE + 1:
        raise FrameError(f"帧太短，无法计算校验: {len(raw)} 字节")
    return accumulate16(raw[:-CHECKSUM_SIZE])


def checksum_bytes(value: int) -> bytes:
    """16 位校验值 → 2 字节 **大端**（MSB 在前）。

    实机证据：``0x02A5`` 在帧内是 ``02 A5``；``0x02CA`` 是 ``02 CA``；
    ``0x083D`` 是 ``08 3D``。若用 ``<H``（小端）会握手失败。
    """
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"校验值必须是 16 位无符号整数: {value}")
    return struct.pack(">H", value)


# --------------------------------------------------------------------------- #
# title 编码
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TitleEncoding:
    """title 编码结果。**必须**把丢弃的字符带回给调用方。

    实机行为：设备会静默丢弃不支持的字节，不报错、也不破坏整帧。
    因此本地过滤不是为了"让设备不崩"，而是为了**可控 + 可告知**。
    静默丢字符会让用户以为程序坏了。
    """

    text: str                 # 清洗后的可显示文本
    raw: bytes                # 编码后的字节（不含结尾 \0）
    dropped: list[str] = field(default_factory=list)
    truncated: bool = False

    @property
    def byte_len(self) -> int:
        return len(self.raw)

    @property
    def was_modified(self) -> bool:
        return bool(self.dropped) or self.truncated

    def user_note(self) -> str:
        """给 UI 直接显示的一句话；无需修改时返回空串。"""
        parts: list[str] = []
        if self.dropped:
            shown = "".join(self.dropped[:8])
            more = f" 等 {len(self.dropped)} 个" if len(self.dropped) > 8 else ""
            parts.append(f"已忽略不支持的字符：{shown}{more}")
        if self.truncated:
            parts.append(f"超长已截断至 {MAX_TITLE_CHARS} 字符")
        return "；".join(parts)


def encode_title(text: str) -> TitleEncoding:
    """把任意文本规整为屏幕可显示的 title。

    * 仅保留 ``A-Z 0-9 . 空格``；
    * 自动转大写；
    * 超过 25 字符截断；
    * 被丢弃的字符原样记入 ``dropped``。
    """
    if not isinstance(text, str):
        raise TypeError(f"title 必须是 str，收到 {type(text).__name__}")

    kept: list[str] = []
    dropped: list[str] = []
    for ch in text.upper():
        if ch in TITLE_ALLOWED_CHARS:
            kept.append(ch)
        else:
            dropped.append(ch)

    truncated = len(kept) > MAX_TITLE_CHARS
    if truncated:
        dropped.extend(kept[MAX_TITLE_CHARS:])
        kept = kept[:MAX_TITLE_CHARS]

    cleaned = "".join(kept)
    return TitleEncoding(
        text=cleaned,
        raw=cleaned.encode("ascii"),
        dropped=dropped,
        truncated=truncated,
    )


def decode_title(body: bytes) -> str:
    """从 body 里取出 title 文本（去掉版本字节与结尾 ``\\0``）。"""
    if len(body) < BODY_TITLE + 1:
        return ""
    region = bytes(body[BODY_TITLE:-1])  # -1 去掉版本字节
    return region.split(b"\x00", 1)[0].decode("ascii", errors="replace")


# --------------------------------------------------------------------------- #
# 构造
# --------------------------------------------------------------------------- #
def build_frame(body: bytes | bytearray | memoryview, *, seq1: int = 0) -> bytes:
    """组装一帧：``header + seq1 + length + body + checksum(BE)``。

    Raises:
        FrameError: body 过长导致 length 字段溢出、seq1 越界。
    """
    if not isinstance(body, (bytes, bytearray, memoryview)):
        raise TypeError(f"body 必须是 bytes-like，收到 {type(body).__name__}")
    raw_body = bytes(body)

    if not isinstance(seq1, int) or isinstance(seq1, bool):
        raise TypeError(f"seq1 必须是 int，收到 {type(seq1).__name__}")
    if not 0 <= seq1 <= 0xFF:
        raise FrameError(f"seq1 必须是 0..255，收到 {seq1}")

    length = len(raw_body) + CHECKSUM_SIZE
    if length > 0xFF:
        raise FrameError(
            f"body 过长：{len(raw_body)} 字节，加上校验后 length 字段={length} 超过 255"
            f"（整帧上限 {MAX_FRAME_TOTAL} 字节）"
        )

    head = HEADER + bytes([seq1, length]) + raw_body
    # 注意：这里用 accumulate16（全量求和），不能用 compute_checksum（会砍末 2 字节）
    return head + checksum_bytes(accumulate16(head))


def build_time_frame(
    title: str | TitleEncoding | bytes,
    *,
    moment: datetime | None = None,
    seq1: int = 0,
    version: int = VERSION_VULCAN,
) -> bytes:
    """构造"时间 + title"帧（step7 / step8 同类）。

    body 布局::

        DD 22 | 年(2,BE) | 月 | 日 | 星期 | 时 | 分 | 秒 | seq2 | title..00 | 版本

    Args:
        title: 字符串（自动清洗）、已编码的 :class:`TitleEncoding`，或原始 bytes。
        moment: 时间，默认取当前本地时间。
        seq1: 帧序号 #1；body 内的序号 #2 自动取 ``seq1 + 1``。
        version: 显示版本，0x02 = vulcan。

    Raises:
        FrameError: title 过长或 seq1/version 越界。
    """
    when = moment or datetime.now()

    if isinstance(title, TitleEncoding):
        title_raw = title.raw
    elif isinstance(title, bytes):
        title_raw = title
    else:
        title_raw = encode_title(title).raw

    if len(title_raw) > MAX_TITLE_CHARS:
        raise FrameError(f"title 字节数 {len(title_raw)} 超过 {MAX_TITLE_CHARS}")
    if not 0 <= version <= 0xFF:
        raise FrameError(f"version 必须是单字节: {version}")

    body = bytearray()
    body += FIXED_ID_TIME
    body += when.year.to_bytes(2, "big")           # 大端，与校验和一致
    body += bytes(
        [
            when.month,
            when.day,
            when.isoweekday() % 7,                 # 周日=0 … 周六=6
            when.hour,
            when.minute,
            when.second,
        ]
    )
    body += bytes([(seq1 + 1) & 0xFF])             # 序号 #2
    body += title_raw + b"\x00"
    body += bytes([version])
    return build_frame(bytes(body), seq1=seq1)


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FrameInfo:
    """解析结果。``raw`` 保留原始字节，便于日志回放。"""

    raw: bytes
    seq1: int
    length_field: int
    body: bytes
    checksum_stored: int
    checksum_calculated: int
    length_ok: bool = True
    header_ok: bool = True

    @property
    def valid(self) -> bool:
        return self.header_ok and self.length_ok and self.checksum_stored == self.checksum_calculated

    @property
    def fixed_id(self) -> bytes:
        return self.body[:2]

    @property
    def version(self) -> int:
        return self.body[-1] if self.body else -1

    @property
    def title(self) -> str:
        return decode_title(self.body)

    @property
    def seq2(self) -> int:
        return self.body[BODY_SEQ2] if len(self.body) > BODY_SEQ2 else -1

    def as_dict(self) -> dict[str, object]:
        return {
            "total_len": len(self.raw),
            "seq1": self.seq1,
            "seq2": self.seq2,
            "length_field": self.length_field,
            "fixed_id": self.fixed_id.hex(),
            "version": f"0x{self.version:02X}",
            "title": self.title,
            "checksum_stored": f"0x{self.checksum_stored:04X}",
            "checksum_calculated": f"0x{self.checksum_calculated:04X}",
            "valid": self.valid,
        }


def parse_frame(
    frame: bytes | bytearray | memoryview,
    *,
    strict: bool = True,
) -> FrameInfo:
    """解析一帧。

    ``strict=True`` 时，帧头/长度/校验任一不符都会抛异常；``False`` 时返回
    ``valid=False`` 的 :class:`FrameInfo`，便于调试面板展示"收到了什么、差多少"。
    """
    raw = bytes(frame)
    if len(raw) < HEADER_SIZE + 2 + CHECKSUM_SIZE:
        raise FrameError(f"帧太短: {len(raw)} 字节")

    header_ok = raw[:HEADER_SIZE] == HEADER
    length_field = raw[LENGTH_OFFSET]
    length_ok = length_field + LENGTH_BIAS == len(raw)
    body = raw[BODY_OFFSET : BODY_OFFSET + max(0, length_field - CHECKSUM_SIZE)]
    stored = struct.unpack(">H", raw[-CHECKSUM_SIZE:])[0]
    calculated = compute_checksum(raw)

    if strict:
        if not header_ok:
            raise FrameError(
                f"帧头不匹配: 期望 {HEADER.hex()}，实际 {raw[:HEADER_SIZE].hex()}"
            )
        if not length_ok:
            raise FrameError(
                f"长度字段 {length_field} 与实长不符: 期望总长 {length_field + LENGTH_BIAS}，实际 {len(raw)}"
            )
        if stored != calculated:
            raise ChecksumError(
                f"校验和不匹配: 帧内 0x{stored:04X}，重算 0x{calculated:04X}"
            )

    return FrameInfo(
        raw=raw,
        seq1=raw[SEQ1_OFFSET],
        length_field=length_field,
        body=body,
        checksum_stored=stored,
        checksum_calculated=calculated,
        length_ok=length_ok,
        header_ok=header_ok,
    )
