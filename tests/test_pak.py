# SPDX-License-Identifier: MIT
"""pak 容器测试：构造、解析、与真实抓包样本回归。"""

from __future__ import annotations

from pathlib import Path

import pytest

from vulcan_lcd.media.pak import (
    HEADER_SIZE,
    MAGIC,
    PakError,
    build_pak,
    jpeg_frames_from_pak,
    parse_pak,
    sum16,
)

REAL_PAK = Path(__file__).resolve().parent.parent / "pak_s1.bin"


def jpeg(size: int = 64, marker: int = 0x41) -> bytes:
    """造一个"看起来像 JPEG"的最小片段（只要求头部 FF D8）。"""
    return b"\xff\xd8\xff" + bytes([marker]) * max(0, size - 3)


# --------------------------------------------------------------------------- #
# 构造
# --------------------------------------------------------------------------- #
def test_build_header_layout() -> None:
    pak = build_pak([jpeg(10)], fps=20)
    assert pak[:2] == MAGIC == b"JP"
    assert int.from_bytes(pak[2:4], "little") == 1
    assert int.from_bytes(pak[4:6], "little") == 20
    assert int.from_bytes(pak[6:8], "little") == 0
    assert len(pak) == HEADER_SIZE + 4 + 4 + 10 + 2  # 表 + 长度前缀 + JPEG + 2 字节对齐


def test_first_offset_points_past_table() -> None:
    frames = [jpeg(16), jpeg(16, 0x42)]
    pak = build_pak(frames)
    table_end = HEADER_SIZE + 4 * 2
    first = int.from_bytes(pak[8:12], "little")
    assert first == table_end


def test_offsets_are_monotonic_and_match_frames() -> None:
    frames = [jpeg(20, 0x41), jpeg(30, 0x42), jpeg(25, 0x43)]
    parsed = parse_pak(build_pak(frames))
    assert [f[3] for f in parsed.frames] == [0x41, 0x42, 0x43]
    assert [len(f) for f in parsed.frames] == [20, 30, 25]


def test_roundtrip_is_lossless() -> None:
    frames = [jpeg(100, i) for i in range(5)]
    pak = build_pak(frames, fps=33)
    parsed = parse_pak(pak)
    assert list(parsed.frames) == frames
    assert parsed.fps == 33


# --------------------------------------------------------------------------- #
# 拒绝路径
# --------------------------------------------------------------------------- #
def test_empty_frames_rejected() -> None:
    with pytest.raises(PakError, match="至少需要一帧"):
        build_pak([])


def test_non_jpeg_frame_rejected() -> None:
    with pytest.raises(PakError, match="不是 JPEG"):
        build_pak([b"not a jpeg"])


def test_empty_frame_rejected() -> None:
    with pytest.raises(PakError, match="为空"):
        build_pak([b""])


def test_bad_magic_rejected() -> None:
    with pytest.raises(PakError, match="魔数"):
        parse_pak(b"XX" + bytes(20))


def test_short_file_rejected() -> None:
    with pytest.raises(PakError, match="过短"):
        parse_pak(b"JP")


def test_zero_frames_rejected() -> None:
    with pytest.raises(PakError, match="帧数为 0"):
        parse_pak(b"JP" + bytes(6))


def test_offset_table_overflow_rejected() -> None:
    data = b"JP" + (5).to_bytes(2, "little") + bytes(4) + bytes(4)  # 声称 5 帧但表不全
    with pytest.raises(PakError, match="偏移表越界"):
        parse_pak(data)


def test_non_monotonic_offsets_rejected() -> None:
    head = b"JP" + (2).to_bytes(2, "little") + (20).to_bytes(2, "little") + bytes(2)
    head += (16).to_bytes(4, "little") + (16).to_bytes(4, "little")
    with pytest.raises(PakError, match="非单调"):
        parse_pak(head + bytes(40))


def test_first_offset_inside_table_rejected() -> None:
    head = b"JP" + (1).to_bytes(2, "little") + (20).to_bytes(2, "little") + bytes(2)
    head += (4).to_bytes(4, "little")
    with pytest.raises(PakError, match="落在偏移表内"):
        parse_pak(head + bytes(20))


# --------------------------------------------------------------------------- #
# sum16（公告帧的校验）
# --------------------------------------------------------------------------- #
def test_sum16_known_values() -> None:
    assert sum16(b"") == 0
    assert sum16(b"\x01\x02\x03") == 6
    assert sum16(bytes(0xFF for _ in range(300))) == (255 * 300) & 0xFFFF


# --------------------------------------------------------------------------- #
# 真实样本回归（抓包还原的 2.4MB pak）
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not REAL_PAK.is_file(), reason="缺少抓包还原的样本 pak_s1.bin")
def test_real_captured_pak() -> None:
    raw = REAL_PAK.read_bytes()
    parsed = parse_pak(raw)

    assert parsed.frame_count == 270
    assert parsed.fps == 20
    assert parsed.reserved == 0
    assert len(raw) == 2_397_564
    assert sum16(raw) == 0x7F76          # 公告帧里记录的值
    assert parsed.frames[0].startswith(b"\xff\xd8\xff")
    assert all(f.endswith(b"\xff\xd9") for f in parsed.frames)


@pytest.mark.skipif(not REAL_PAK.is_file(), reason="缺少抓包还原的样本 pak_s1.bin")
def test_rebuild_real_pak_is_byte_identical() -> None:
    """用我们的构造器重建同一批帧，必须与官方产物逐字节一致。"""
    raw = REAL_PAK.read_bytes()
    parsed = parse_pak(raw)
    rebuilt = build_pak(list(parsed.frames), fps=parsed.fps, reserved=parsed.reserved)
    assert rebuilt == raw


@pytest.mark.skipif(not REAL_PAK.is_file(), reason="缺少抓包还原的样本 pak_s1.bin")
def test_jpeg_frames_helper() -> None:
    frames = jpeg_frames_from_pak(REAL_PAK.read_bytes())
    assert len(frames) == 270
