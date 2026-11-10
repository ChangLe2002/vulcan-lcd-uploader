# SPDX-License-Identifier: MIT
"""帧构造与解析测试。

基准全部来自实机 / 公开抓包，逐字节可比对：

* step1 握手请求：``5A9FA90004E01F02A5``
* 文档 step7（无 title）：``5A9FA9000FDD2207E9050A061233280100020425``
* 文档 step8（含 title）：``5A9FA9001FDD2207E9050A0612332A014745464F5243452052545820353038300002083D``
* 实机应答：``5A9FA9000CE01F0A00050D0000010002CA``
"""

from __future__ import annotations

from datetime import datetime

import pytest

from vulcan_lcd.constants import (
    FIXED_ID_HANDSHAKE,
    FIXED_ID_TIME,
    MAX_TITLE_CHARS,
    VERSION_VULCAN,
)
from vulcan_lcd.core.protocol import (
    ChecksumError,
    FrameError,
    TitleEncoding,
    build_frame,
    build_time_frame,
    compute_checksum,
    decode_title,
    encode_title,
    parse_frame,
)

STEP1 = bytes.fromhex("5A9FA90004E01F02A5")
DEVICE_REPLY = bytes.fromhex("5A9FA9000CE01F0A00050D0000010002CA")
DOC_STEP7 = bytes.fromhex("5A9FA9000FDD2207E9050A061233280100020425")
DOC_STEP8 = bytes.fromhex(
    "5A9FA9001FDD2207E9050A0612332A014745464F5243452052545820353038300002083D"
)
DOC_TIME_7 = datetime(2025, 5, 10, 18, 51, 40)
DOC_TIME_8 = datetime(2025, 5, 10, 18, 51, 42)


# --------------------------------------------------------------------------- #
# 逐字节复现官方帧（这是本模块最重要的回归测试）
# --------------------------------------------------------------------------- #
def test_build_time_frame_reproduces_doc_step7_without_title() -> None:
    assert build_time_frame("", moment=DOC_TIME_7).hex().upper() == DOC_STEP7.hex().upper()


def test_build_time_frame_reproduces_doc_step8_with_title() -> None:
    built = build_time_frame("GEFORCE RTX 5080", moment=DOC_TIME_8)
    assert built.hex().upper() == DOC_STEP8.hex().upper()


# --------------------------------------------------------------------------- #
# 帧结构
# --------------------------------------------------------------------------- #
def test_variable_length_not_fixed_36() -> None:
    """短 title 的帧必须比 36 字节短——证明没有写死长度。"""
    short = build_time_frame("HI", moment=DOC_TIME_8)
    assert len(short) < 36
    assert len(short) == short[4] + 5


def test_length_field_equals_total_minus_five() -> None:
    frame = build_frame(b"\xdd\x22" + b"\x00" * 8)
    assert frame[4] == len(frame) - 5


def test_header_and_seq_offsets() -> None:
    frame = build_frame(b"\xdd\x22\x00", seq1=7)
    assert frame[0:3] == b"\x5a\x9f\xa9"
    assert frame[3] == 7


def test_checksum_is_last_two_bytes_big_endian() -> None:
    frame = build_frame(b"\xdd\x22\x00\x00\x00")
    assert frame[-2:] == compute_checksum(frame).to_bytes(2, "big")


def test_body_too_long_raises() -> None:
    with pytest.raises(FrameError, match="body 过长"):
        build_frame(bytes(255))


def test_seq1_range_is_validated() -> None:
    with pytest.raises(FrameError, match="seq1"):
        build_frame(b"\x00", seq1=256)
    with pytest.raises(TypeError):
        build_frame(b"\x00", seq1="1")  # type: ignore[arg-type]


def test_body_must_be_bytes_like() -> None:
    with pytest.raises(TypeError, match="body"):
        build_frame("abc")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #
def test_parse_device_reply() -> None:
    info = parse_frame(DEVICE_REPLY)
    assert info.valid
    assert info.seq1 == 0
    assert info.length_field == 0x0C
    assert info.fixed_id == FIXED_ID_HANDSHAKE
    assert info.checksum_stored == 0x02CA


def test_parse_doc_step8_title_and_version() -> None:
    info = parse_frame(DOC_STEP8)
    assert info.valid
    assert info.fixed_id == FIXED_ID_TIME
    assert info.title == "GEFORCE RTX 5080"
    assert info.version == VERSION_VULCAN
    assert info.seq2 == 1


def test_parse_roundtrip_keeps_title() -> None:
    frame = build_time_frame("RTX 5070", moment=DOC_TIME_8)
    info = parse_frame(frame)
    assert info.valid
    assert info.title == "RTX 5070"
    assert info.length_field == len(frame) - 5


def test_parse_rejects_bad_header() -> None:
    broken = bytearray(DEVICE_REPLY)
    broken[1] = 0x00
    with pytest.raises(FrameError, match="帧头不匹配"):
        parse_frame(bytes(broken))


def test_parse_rejects_length_mismatch() -> None:
    broken = bytearray(DEVICE_REPLY)
    broken[4] = 0x20
    with pytest.raises(FrameError, match="长度字段"):
        parse_frame(bytes(broken))


def test_parse_rejects_bad_checksum() -> None:
    broken = bytearray(DEVICE_REPLY)
    broken[13] = 0x02  # 改一个 data 字节，校验必然不对
    with pytest.raises(ChecksumError, match="校验和不匹配"):
        parse_frame(bytes(broken))


def test_parse_loose_mode_reports_flags() -> None:
    broken = bytearray(DEVICE_REPLY)
    broken[13] = 0x02
    info = parse_frame(bytes(broken), strict=False)
    assert info.valid is False
    assert info.header_ok is True
    assert info.length_ok is True
    assert info.checksum_stored != info.checksum_calculated


def test_parse_too_short_raises() -> None:
    with pytest.raises(FrameError, match="帧太短"):
        parse_frame(b"\x5a\x9f\xa9")


def test_frame_info_serialises() -> None:
    data = parse_frame(DOC_STEP8).as_dict()
    assert data["title"] == "GEFORCE RTX 5080"
    assert data["valid"] is True
    assert data["version"] == "0x02"
    assert data["length_field"] == 0x1F


# --------------------------------------------------------------------------- #
# title 编码
# --------------------------------------------------------------------------- #
def test_encode_title_keeps_allowed_chars() -> None:
    enc = encode_title("ABC 123.")
    assert enc.text == "ABC 123."
    assert enc.raw == b"ABC 123."
    assert enc.dropped == []
    assert enc.was_modified is False


def test_encode_title_uppercases() -> None:
    assert encode_title("hello").text == "HELLO"


def test_encode_title_drops_chinese_and_reports_it() -> None:
    """实机行为：中文被设备静默丢弃。本地必须先丢并**告诉用户**。"""
    enc = encode_title("下雨223")
    assert enc.text == "223"
    assert enc.dropped == ["下", "雨"]
    assert "已忽略" in enc.user_note()


def test_encode_title_truncates_to_25() -> None:
    enc = encode_title("A" * 30)
    assert len(enc.text) == MAX_TITLE_CHARS
    assert enc.truncated is True
    assert "截断" in enc.user_note()


def test_encode_title_empty_after_filtering() -> None:
    enc = encode_title("中文")
    assert enc.text == ""
    assert len(enc.dropped) == 2


def test_encode_title_rejects_non_str() -> None:
    with pytest.raises(TypeError):
        encode_title(123)  # type: ignore[arg-type]


def test_decode_title_matches_encode() -> None:
    frame = build_time_frame("HELLO WORLD", moment=DOC_TIME_8)
    assert decode_title(parse_frame(frame).body) == "HELLO WORLD"


def test_build_time_frame_accepts_title_encoding() -> None:
    enc = encode_title("下雨223")
    frame = build_time_frame(enc, moment=DOC_TIME_8)
    assert parse_frame(frame).title == "223"


def test_build_time_frame_accepts_raw_bytes_for_experiments() -> None:
    frame = build_time_frame("下雨223".encode("utf-8"), moment=DOC_TIME_8)
    info = parse_frame(frame)
    assert info.length_field == len(frame) - 5


def test_build_time_frame_rejects_overlong_raw_title() -> None:
    with pytest.raises(FrameError, match="超过"):
        build_time_frame(b"A" * 26)


def test_weekday_mapping_sunday_is_zero() -> None:
    sunday = datetime(2026, 11, 8, 12, 0, 0)  # 2026-11-08 是周日
    info = parse_frame(build_time_frame("X", moment=sunday))
    assert info.body[6] == 0


def test_weekday_mapping_saturday_is_six() -> None:
    assert DOC_TIME_8.isoweekday() % 7 == 6
    info = parse_frame(build_time_frame("X", moment=DOC_TIME_8))
    assert info.body[6] == 6


def test_year_is_big_endian_in_body() -> None:
    info = parse_frame(build_time_frame("X", moment=datetime(2026, 1, 2, 3, 4, 5)))
    assert info.body[2:4] == (2026).to_bytes(2, "big")
