# SPDX-License-Identifier: MIT
"""抓包解析工具测试：用合成的字节流验证切帧与校验判定。

这些用例模拟的是"抓包文件里到底会看到什么"：正常帧、粘连帧、噪声字节、
被截断的尾帧，以及一种**未知固定 ID**（很可能就是图像通道）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from decode_capture import (  # noqa: E402
    Frame,
    parse_hex_text,
    split_frames,
    summarize,
)

from vulcan_lcd.core.protocol import build_frame  # noqa: E402

HANDSHAKE_TX = bytes.fromhex("5A9FA90004E01F02A5")
HANDSHAKE_RX = bytes.fromhex("5A9FA9000CE01F0A00050D0000010002CA")


def title_frame() -> bytes:
    return build_frame(b"\xdd\x22" + bytes([0x07, 0xEA, 11, 4, 3, 9, 0, 0, 1]) + b"HI\x00\x02")


def image_frame(payload_len: int = 200) -> bytes:
    return build_frame(b"\x8a\x01" + bytes(range(payload_len % 251)))


# --------------------------------------------------------------------------- #
# 文本解析
# --------------------------------------------------------------------------- #
def test_parse_raw_accepts_spaces_and_prefixes() -> None:
    text = "5a 9f a9 00 04\n0xE0 0x1F:02-A5\n"
    assert parse_hex_text(text) == bytes.fromhex("5a9fa90004e01f02a5")


def test_parse_tshark_skips_null_lines() -> None:
    text = "5a9fa90004\n(null)\n\n759f\n"
    assert parse_hex_text(text, fmt="tshark") == bytes.fromhex("5a9fa90004759f")


def test_parse_tshark_ignores_comments() -> None:
    text = "# comment\n5a9f\n"
    assert parse_hex_text(text, fmt="tshark") == bytes.fromhex("5a9f")


def test_parse_rejects_unknown_format() -> None:
    with pytest.raises(ValueError, match="未知格式"):
        parse_hex_text("00", fmt="pcap")


# --------------------------------------------------------------------------- #
# 切帧
# --------------------------------------------------------------------------- #
def test_split_handshake_frames() -> None:
    result = split_frames(HANDSHAKE_TX + HANDSHAKE_RX)
    assert len(result.frames) == 2
    assert result.orphans == 0
    assert [f.total_len for f in result.frames] == [9, 17]
    assert result.frames[0].fixed_id == "e01f"
    assert result.frames[0].length_field == 4


def test_split_mixed_frames_with_unknown_id() -> None:
    buffer = HANDSHAKE_TX + HANDSHAKE_RX + title_frame() + image_frame()
    result = split_frames(buffer)
    assert len(result.frames) == 4
    assert result.frames[3].fixed_id == "8a01"
    assert result.frames[3].total_len == 209


def test_noise_between_frames_is_counted() -> None:
    result = split_frames(b"\x00\x01\x02" + HANDSHAKE_TX + b"\xff" + HANDSHAKE_RX)
    assert len(result.frames) == 2
    assert result.orphans >= 4


def test_truncated_tail_is_reported() -> None:
    buffer = HANDSHAKE_TX + HANDSHAKE_RX[:8]
    result = split_frames(buffer)
    assert len(result.frames) == 1
    assert result.truncated == 1


def test_false_header_inside_payload_is_skipped() -> None:
    """payload 里出现 5A 9F A9 时，长度字段不自洽，不能被当成新帧。"""
    payload = b"\x5a\x9f\xa9\xff\xff" + bytes(40)
    frame = build_frame(b"\x8a\x01" + payload)
    result = split_frames(frame)
    assert len(result.frames) == 1
    assert result.frames[0].total_len == len(frame)


# --------------------------------------------------------------------------- #
# 校验判定
# --------------------------------------------------------------------------- #
def test_big_endian_checksum_detected() -> None:
    frame = split_frames(title_frame()).frames[0]
    assert frame.be_ok is True
    assert frame.le_ok is False


def test_little_endian_frame_is_detected_as_le() -> None:
    """故意构造一个"小端校验"的帧，验证工具能识别出差异。"""
    body = b"\x8a\x01" + bytes(20)
    raw = bytes.fromhex("5a9fa9") + bytes([0, len(body) + 2]) + body
    value = sum(raw) & 0xFFFF
    frame_bytes = raw + value.to_bytes(2, "little")

    frame = split_frames(frame_bytes).frames[0]
    assert frame.le_ok is True
    assert frame.be_ok is False


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #
def test_summary_lists_ids_and_flags_unknown_channel() -> None:
    result = split_frames(HANDSHAKE_TX + HANDSHAKE_RX + title_frame() + image_frame())
    text = summarize(result)
    assert "e01f" in text
    assert "dd22" in text
    assert "8a01" in text
    assert "未知固定 ID" in text


def test_summary_reports_endianness_conclusion() -> None:
    text = summarize(split_frames(HANDSHAKE_TX))
    assert "大端" in text


def test_summary_without_frames() -> None:
    text = summarize(split_frames(b"\x00\x01\x02"))
    assert "帧数: 0" in text


def test_frame_properties() -> None:
    frame = split_frames(title_frame()).frames[0]
    assert isinstance(frame, Frame)
    assert frame.seq1 == 0
    assert frame.payload[9:11] == b"HI"
