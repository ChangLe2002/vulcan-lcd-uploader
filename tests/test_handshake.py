# SPDX-License-Identifier: MIT
"""握手指令与结构匹配测试。

核心约束：**不能做整包等值比较**。5070 的应答在偏移 13 是 0x01，5080 是 0x00，
整包比较会把真设备判成假设备。
"""

from __future__ import annotations

import pytest

from vulcan_lcd.core.handshake import (
    HANDSHAKE_REPLY_SAMPLE,
    HANDSHAKE_TX,
    INIT_SEQUENCE,
    matches_reply,
    perform_handshake,
    send_init_sequence,
)
from vulcan_lcd.core.protocol import build_frame
from vulcan_lcd.core.transport import Transport
from tests.test_transport import FakeSerial

DEVICE_REPLY = bytes.fromhex("5A9FA9000CE01F0A00050D0000010002CA")


def make_transport(fake: FakeSerial) -> Transport:
    return Transport("COM_TEST", serial_factory=lambda p, k: fake)


# --------------------------------------------------------------------------- #
# 结构匹配
# --------------------------------------------------------------------------- #
def test_matches_real_5070_reply() -> None:
    matched, reason, info = matches_reply(DEVICE_REPLY)
    assert matched is True, reason
    assert info is not None and info.valid


def test_matches_documented_5080_reply() -> None:
    """5080 样本也必须判为匹配，否则跨型号就废了。"""
    matched, reason, _ = matches_reply(HANDSHAKE_REPLY_SAMPLE)
    assert matched is True, reason


def test_reply_with_trailing_bytes_is_still_matched() -> None:
    """应答后面粘连下一帧时，应按长度字段切出第一帧。"""
    matched, reason, _ = matches_reply(DEVICE_REPLY + b"\x00\x01\x02")
    assert matched is True, reason


def test_empty_reply_is_rejected() -> None:
    matched, reason, _ = matches_reply(b"")
    assert matched is False
    assert "过短" in reason


def test_short_reply_is_rejected() -> None:
    matched, reason, _ = matches_reply(b"\x5a\x9f\xa9\x00")
    assert matched is False
    assert "过短" in reason


def test_truncated_reply_is_rejected() -> None:
    matched, reason, _ = matches_reply(DEVICE_REPLY[:10])
    assert matched is False
    assert "实际只收到" in reason


def test_bad_checksum_is_rejected() -> None:
    broken = bytearray(DEVICE_REPLY)
    broken[-1] ^= 0xFF
    matched, reason, _ = matches_reply(bytes(broken))
    assert matched is False
    assert "校验" in reason


def test_wrong_fixed_id_is_rejected() -> None:
    """时间帧（DD 22）不是握手应答，必须被拒。"""
    wrong = build_frame(b"\xdd\x22" + bytes(8))
    matched, reason, _ = matches_reply(wrong)
    assert matched is False
    assert "固定 ID" in reason


def test_bad_header_is_rejected() -> None:
    broken = bytearray(DEVICE_REPLY)
    broken[0] = 0x00
    matched, reason, _ = matches_reply(bytes(broken))
    assert matched is False
    assert "帧头" in reason


# --------------------------------------------------------------------------- #
# 会话流程
# --------------------------------------------------------------------------- #
def test_perform_handshake_sends_published_bytes() -> None:
    fake = FakeSerial(late_rx=DEVICE_REPLY)
    with make_transport(fake) as transport:
        result = perform_handshake(transport, timeout_ms=30)
    assert fake.written[0] == HANDSHAKE_TX
    assert result.matched is True
    assert result.reply == DEVICE_REPLY
    assert "成功" in result.summary()


def test_perform_handshake_without_reply_reports_reason() -> None:
    fake = FakeSerial()
    with make_transport(fake) as transport:
        result = perform_handshake(transport, timeout_ms=20)
    assert result.matched is False
    assert "无应答" in result.reason
    assert result.summary().startswith("握手失败")


def test_init_sequence_has_four_frames() -> None:
    assert len(INIT_SEQUENCE) == 4
    for frame in INIT_SEQUENCE:
        assert frame[:3] == b"\x5a\x9f\xa9"
        assert frame[4] + 5 == len(frame)


def test_send_init_sequence_writes_all_frames() -> None:
    fake = FakeSerial()
    with make_transport(fake) as transport:
        send_init_sequence(transport, delay_s=0)
    assert fake.written == list(INIT_SEQUENCE)


def test_handshake_tx_is_nine_bytes() -> None:
    assert len(HANDSHAKE_TX) == 9
    assert HANDSHAKE_TX.hex().upper() == "5A9FA90004E01F02A5"


@pytest.mark.parametrize("frame", INIT_SEQUENCE)
def test_init_frames_have_valid_checksum(frame: bytes) -> None:
    from vulcan_lcd.core.protocol import parse_frame

    assert parse_frame(frame).valid is True
