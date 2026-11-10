# SPDX-License-Identifier: MIT
"""十六进制格式化测试：截断必须显式，避免误判设备只回了很少数据。"""

from __future__ import annotations

import pytest

from vulcan_lcd.util.hexfmt import hexdump, preview, to_hex


def test_to_hex_has_no_separators() -> None:
    assert to_hex(b"\x5a\x9f\xa9") == "5a9fa9"


def test_preview_empty() -> None:
    assert preview(b"") == "<empty>"


def test_preview_short_is_not_truncated() -> None:
    text = preview(b"\x5a\x9f\xa9")
    assert text == "5a 9f a9 (3 B)"


def test_preview_marks_truncation_and_total_size() -> None:
    data = bytes(range(64))
    text = preview(data, limit=8)
    assert text.startswith("00 01 02 03 04 05 06 07")
    assert "+56 B" in text
    assert "(64 B)" in text


def test_hexdump_offsets_and_ascii_column() -> None:
    lines = hexdump(b"HELLO\x00WORLD", width=8).splitlines()
    assert lines[0].startswith("00000000  ")
    assert "|HELLO.WO|" in lines[0]
    assert lines[1].startswith("00000008  ")


def test_hexdump_truncates_and_says_so() -> None:
    text = hexdump(bytes(100), limit=32)
    assert "已截断，剩余 68 字节未显示（总计 100 B）" in text


def test_hexdump_empty() -> None:
    assert hexdump(b"") == "<empty>"


def test_hexdump_base_offset() -> None:
    text = hexdump(b"\xaa", base_offset=34, width=16)
    assert text.startswith("00000022")


@pytest.mark.parametrize("bad", [0, -1])
def test_hexdump_rejects_bad_width(bad: int) -> None:
    with pytest.raises(ValueError, match="width"):
        hexdump(b"\x00", width=bad)
