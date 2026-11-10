# SPDX-License-Identifier: MIT
"""彻底清理（与官方垃圾桶一致）的测试。"""

from __future__ import annotations

import threading

from vulcan_lcd.features import carousel, cache_clean
from vulcan_lcd.features.cache_clean import clear_beyond_first
from vulcan_lcd.features.gif_upload import FileEntry


class FakeTransport:
    def __init__(self) -> None:
        self.deleted: list[str] = []


def _install(monkeypatch, files: list[str]) -> FakeTransport:
    transport = FakeTransport()
    monkeypatch.setattr(
        cache_clean, "query_file_list", lambda t: [FileEntry(n, 100) for n in files]
    )
    monkeypatch.setattr(
        cache_clean, "delete_file", lambda t, name: t.deleted.append(name)
    )
    return transport


def test_deep_clean_deletes_all_but_first(monkeypatch) -> None:
    """官方行为：保留 img1，删除 img2 及以后全部。"""
    transport = _install(monkeypatch, ["img1.pak", "img2.pak", "img3.pak", "img6.pak"])

    report = clear_beyond_first(transport, sleeper=lambda s: None)

    assert report.error is None
    assert transport.deleted == ["img2.pak", "img3.pak", "img6.pak"]
    assert "img1.pak" in report.skipped
    assert "已清理 3 个" in report.describe()


def test_deep_clean_noop_when_only_first(monkeypatch) -> None:
    transport = _install(monkeypatch, ["img1.pak"])
    report = clear_beyond_first(transport, sleeper=lambda s: None)
    assert transport.deleted == []
    assert "没有需要清理" in report.describe()


def test_deep_clean_reports_error(monkeypatch) -> None:
    def boom(_transport):
        raise RuntimeError("串口炸了")

    monkeypatch.setattr(cache_clean, "query_file_list", boom)
    report = clear_beyond_first(FakeTransport(), sleeper=lambda s: None)
    assert report.error and "串口炸了" in report.error
