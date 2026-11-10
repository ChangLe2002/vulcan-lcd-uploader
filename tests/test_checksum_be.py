# SPDX-License-Identifier: MIT
"""16 位累加校验（**大端**）测试。

真实向量全部来自实机或公开抓包，不再使用手算假设：

* 握手请求 ``5A9FA90004E01F02A5`` → 累加 677 = ``0x02A5``，字节 ``02 A5``
* 设备应答 ``...02CA`` → 累加 714 = ``0x02CA``，字节 ``02 CA``
* 文档 step8 ``...083D`` → 累加 2109 = ``0x083D``，字节 ``08 3D``

历史教训：本项目第一版按"小端"实现，握手会被设备判定校验错误。
"""

from __future__ import annotations

import pytest

from vulcan_lcd.core.protocol import (
    FrameError,
    checksum_bytes,
    compute_checksum,
)

STEP1 = bytes.fromhex("5A9FA90004E01F02A5")
DOC_STEP2 = bytes.fromhex("5A9FA9000CE01F0A00050D0000000002C9")
DEVICE_STEP2 = bytes.fromhex("5A9FA9000CE01F0A00050D0000010002CA")
DOC_STEP8 = bytes.fromhex(
    "5A9FA9001FDD2207E9050A0612332A014745464F5243452052545820353038300002083D"
)


# --------------------------------------------------------------------------- #
# 真实向量
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        (STEP1, 0x02A5),
        (DOC_STEP2, 0x02C9),
        (DEVICE_STEP2, 0x02CA),
        (DOC_STEP8, 0x083D),
    ],
    ids=["handshake_tx", "doc_reply", "device_reply", "doc_step8"],
)
def test_compute_checksum_matches_real_frames(frame: bytes, expected: int) -> None:
    assert compute_checksum(frame) == expected


@pytest.mark.parametrize(
    ("frame", "tail"),
    [
        (STEP1, b"\x02\xa5"),
        (DOC_STEP2, b"\x02\xc9"),
        (DEVICE_STEP2, b"\x02\xca"),
        (DOC_STEP8, b"\x08\x3d"),
    ],
)
def test_checksum_is_stored_big_endian(frame: bytes, tail: bytes) -> None:
    assert frame[-2:] == tail
    assert frame[-2:] == checksum_bytes(compute_checksum(frame))


def test_little_endian_would_be_wrong() -> None:
    """把 0x02A5 写成 A5 02 就会错——这条测试锁住历史缺陷。"""
    assert checksum_bytes(0x02A5) == b"\x02\xa5"
    assert checksum_bytes(0x02A5) != b"\xa5\x02"


# --------------------------------------------------------------------------- #
# 编码
# --------------------------------------------------------------------------- #
def test_checksum_bytes_zero_and_max() -> None:
    assert checksum_bytes(0x0000) == b"\x00\x00"
    assert checksum_bytes(0xFFFF) == b"\xff\xff"


@pytest.mark.parametrize("bad", [-1, 0x10000, 70000])
def test_checksum_bytes_rejects_out_of_range(bad: int) -> None:
    with pytest.raises(ValueError, match="16 位"):
        checksum_bytes(bad)


def test_checksum_is_two_bytes_not_one() -> None:
    assert len(checksum_bytes(0x1234)) == 2


# --------------------------------------------------------------------------- #
# 累加行为
# --------------------------------------------------------------------------- #
def test_sum_wraps_and_keeps_low_16_bits() -> None:
    # 36 个 0xFF：前 34 字节参与校验 = 8670 = 0x21DE
    frame = b"\xff" * 36
    assert compute_checksum(frame) == 8670 == 0x21DE


def test_checksum_excludes_last_two_bytes() -> None:
    body = bytes(range(10))
    frame_a = body + b"\x00\x00"
    frame_b = body + b"\xff\xff"
    assert compute_checksum(frame_a) == compute_checksum(frame_b)


def test_too_short_frame_raises() -> None:
    with pytest.raises(FrameError, match="帧太短"):
        compute_checksum(b"\x5a")
