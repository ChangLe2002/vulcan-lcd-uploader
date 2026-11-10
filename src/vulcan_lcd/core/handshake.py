# SPDX-License-Identifier: MIT
"""握手与设备识别。

判定策略是**结构匹配**，不是整包等值比较 —— 这一点由实机差异决定：

* 文档（RTX 5080）应答：``5A 9F A9 00 0C E0 1F 0A 00 05 0D 00 00 00 00 02 C9``
* 实测（RTX 5070）应答：``5A 9F A9 00 0C E0 1F 0A 00 05 0D 00 00 01 00 02 CA``

差异只在偏移 13（状态位 ``00`` vs ``01``）及其连带校验。若做整包比较，
5070 会被误判成"不是智屏"。因此只校验三个不变量：

1. 帧头 ``5A 9F A9``
2. 长度字段自洽（``length + 5 == 总长``）
3. 校验和自洽（大端 16 位累加）
4. body 前两字节为 ``E0 1F``（握手应答的固定 ID）
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..constants import FIXED_ID_HANDSHAKE, HEADER_SIZE
from .protocol import FrameError, FrameInfo, parse_frame
from .transport import Transport, TransportError

__all__ = [
    "HANDSHAKE_TX",
    "HANDSHAKE_REPLY_SAMPLE",
    "INIT_SEQUENCE",
    "HandshakeResult",
    "matches_reply",
    "perform_handshake",
    "send_init_sequence",
]

#: [V] 握手请求（实机发送成功并收到应答）
HANDSHAKE_TX: bytes = bytes.fromhex("5A9FA90004E01F02A5")

#: [V] 文档样本应答（5080 抓包）。仅用于比对展示，**不要**用于等值判定。
HANDSHAKE_REPLY_SAMPLE: bytes = bytes.fromhex("5A9FA9000CE01F0A00050D0000000002C9")

#: [V] 握手应答的固定 ID
HS_REPLY_FIXED_ID: bytes = FIXED_ID_HANDSHAKE

#: [V] 进入"时间/标题显示模式"的初始化序列（step3–6）
INIT_SEQUENCE: tuple[bytes, ...] = (
    bytes.fromhex("5A9FA90005EC130102A7"),
    bytes.fromhex("5A9FA90005EB140002A6"),
    bytes.fromhex("5A9FA90006E11E6400030B"),
    bytes.fromhex("5A9FA90006E11E0A0002B1"),
)


@dataclass(frozen=True)
class HandshakeResult:
    """握手结果。"""

    sent: bytes
    reply: bytes
    matched: bool
    reason: str
    info: FrameInfo | None = None

    def summary(self) -> str:
        if self.matched:
            return f"握手成功，应答 {len(self.reply)} 字节"
        return f"握手失败：{self.reason}"


def matches_reply(reply: bytes) -> tuple[bool, str, FrameInfo | None]:
    """按结构不变量判断应答是否为火神智屏的握手回应。

    Returns:
        ``(matched, reason, info)``。``reason`` 在成功时为空串。
    """
    raw = bytes(reply)
    if len(raw) < HEADER_SIZE + 2 + 2:
        return (False, f"应答过短（{len(raw)} 字节）", None)

    # 应答可能粘着下一帧的数据，先按长度字段切出第一帧
    length_field = raw[4]
    total = length_field + 5
    if total > len(raw):
        return (False, f"长度字段声明 {total} 字节，实际只收到 {len(raw)}", None)
    raw = raw[:total]

    try:
        info = parse_frame(raw, strict=False)
    except FrameError as exc:
        return (False, f"解析失败：{exc}", None)

    if not info.header_ok:
        return (False, "帧头不匹配", info)
    if not info.length_ok:
        return (False, "长度字段与实长不符", info)
    if info.checksum_stored != info.checksum_calculated:
        return (
            False,
            f"校验不符（帧内 0x{info.checksum_stored:04X} / 重算 0x{info.checksum_calculated:04X}）",
            info,
        )
    if info.fixed_id != HS_REPLY_FIXED_ID:
        return (False, f"固定 ID 不符：期望 {HS_REPLY_FIXED_ID.hex()}，实际 {info.fixed_id.hex()}", info)
    return (True, "", info)


def perform_handshake(
    transport: Transport,
    *,
    timeout_ms: int = 900,
) -> HandshakeResult:
    """发送握手并判定应答。

    不负责开/关串口（由调用方管理生命周期），这样便于在同一会话里连续
    做握手 → 初始化 → 发帧。
    """
    transport.reset_input_buffer()
    try:
        transport.write(HANDSHAKE_TX)
    except TransportError as exc:
        return HandshakeResult(sent=HANDSHAKE_TX, reply=b"", matched=False, reason=f"发送失败：{exc}")

    reply = transport.read_for(timeout_ms)
    if not reply:
        return HandshakeResult(
            sent=HANDSHAKE_TX,
            reply=b"",
            matched=False,
            reason="设备无应答（端口可能不是智屏，或屏幕未上电）",
        )

    matched, reason, info = matches_reply(reply)
    return HandshakeResult(sent=HANDSHAKE_TX, reply=reply, matched=matched, reason=reason, info=info)


def send_init_sequence(transport: Transport, *, delay_s: float = 0.08) -> None:
    """发送 step3–6 初始化序列，进入时间/标题显示模式。"""
    for frame in INIT_SEQUENCE:
        transport.write(frame)
        time.sleep(delay_s)
