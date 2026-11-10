# SPDX-License-Identifier: MIT
"""清理设备缓存（e718 删除指令）与上传台账的测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from vulcan_lcd.features import cache_clean
from vulcan_lcd.features.cache_clean import clear_uploaded_files
from vulcan_lcd.features.gif_upload import FileEntry, build_delete_frame
from vulcan_lcd.features.upload_ledger import UploadLedger

#: 抓包实测的删除帧（清理 img3.pak）
CAPTURED_DELETE = bytes.fromhex("5A9FA9000EE71800696D67332E70616B000589")


# --------------------------------------------------------------------------- #
# 删除帧
# --------------------------------------------------------------------------- #
def test_delete_frame_matches_capture() -> None:
    assert build_delete_frame("img3.pak") == CAPTURED_DELETE


def test_delete_frame_length_field() -> None:
    frame = build_delete_frame("img3.pak")
    assert frame[4] == len(frame) - 5
    assert (sum(frame[:-2]) & 0xFFFF) == int.from_bytes(frame[-2:], "big")


# --------------------------------------------------------------------------- #
# 台账
# --------------------------------------------------------------------------- #
def test_ledger_add_remove_clear(tmp_path: Path) -> None:
    ledger = UploadLedger(tmp_path / "uploaded_files.json")
    assert ledger.load() == []

    ledger.add("img3.pak")
    ledger.add("img4.pak")
    ledger.add("img3.pak")          # 去重
    assert ledger.load() == ["img3.pak", "img4.pak"]

    ledger.remove("img3.pak")
    assert ledger.load() == ["img4.pak"]

    ledger.clear()
    assert ledger.load() == []


def test_ledger_tolerates_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "uploaded_files.json"
    path.write_text("{ not json", encoding="utf-8")
    assert UploadLedger(path).load() == []


# --------------------------------------------------------------------------- #
# 清理逻辑
# --------------------------------------------------------------------------- #
def test_clear_only_deletes_ledger_files(monkeypatch, tmp_path: Path) -> None:
    """设备上有 img1/img3/img9，台账只有 img3/img9 → 只删这两个。"""
    on_device = [FileEntry("img1.pak", 100), FileEntry("img3.pak", 200), FileEntry("img9.pak", 300)]
    monkeypatch.setattr(cache_clean, "query_file_list", lambda transport: on_device)

    deleted: list[str] = []
    monkeypatch.setattr(cache_clean, "delete_file", lambda transport, name: deleted.append(name))

    report = clear_uploaded_files(object(), ["img3.pak", "img9.pak", "img7.pak"], sleeper=lambda s: None)

    assert report.error is None
    assert deleted == ["img3.pak", "img9.pak"]     # img7 不在设备上 → 跳过
    assert "img7.pak" in report.skipped
    assert "img1.pak" not in deleted               # 绝不碰非台账文件


def test_clear_reports_error_when_query_fails(monkeypatch) -> None:
    def boom(transport):
        raise RuntimeError("串口炸了")

    monkeypatch.setattr(cache_clean, "query_file_list", boom)
    report = clear_uploaded_files(object(), ["img3.pak"], sleeper=lambda s: None)
    assert report.error
    assert "串口炸了" in report.error


def test_clear_with_empty_ledger_deletes_nothing(monkeypatch) -> None:
    monkeypatch.setattr(cache_clean, "query_file_list", lambda t: [FileEntry("img1.pak", 10)])
    deleted: list[str] = []
    monkeypatch.setattr(cache_clean, "delete_file", lambda t, n: deleted.append(n))
    report = clear_uploaded_files(object(), [], sleeper=lambda s: None)
    assert deleted == []
    assert "没有需要清理" in report.describe()
