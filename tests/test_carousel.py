# SPDX-License-Identifier: MIT
"""播放列表轮播的离线测试（不碰真机）。"""

from __future__ import annotations

import threading
from pathlib import Path

from vulcan_lcd.features import carousel
from vulcan_lcd.features.carousel import PlaylistEntry, build_entries, run_playlist
from vulcan_lcd.features.gif_upload import FileEntry

DISPLAY_ID = bytes.fromhex("e51a")


class FakeDevice:
    """模拟设备：记录已上传文件，清单从中返回。"""

    def __init__(self, initial: list[str] | None = None) -> None:
        self.names: list[str] = list(initial or [])
        self.writes: list[bytes] = []
        self.opened = False
        self.closed = False

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.closed = True

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def flush(self) -> None:
        pass

    def list_files(self, _transport=None) -> list[FileEntry]:
        return [FileEntry(n, 100) for n in self.names]

    def upload(self, _transport, pak: bytes, *, name: str) -> None:
        self.names.append(name)

    def display_writes(self) -> list[bytes]:
        return [w for w in self.writes if w[5:7] == DISPLAY_ID]


class FakeController:
    def __init__(self) -> None:
        self.took_over = False
        self.released = False

    def takeover(self) -> None:
        self.took_over = True

    def release(self) -> None:
        self.released = True


def _entries(count: int = 2, seconds: float = 1.0) -> list[PlaylistEntry]:
    return [
        PlaylistEntry(path=Path(f"a{i}.gif"), pak=b"\xff\xd8fake", name="", seconds=seconds)
        for i in range(count)
    ]


def _install(monkeypatch, device: FakeDevice) -> None:
    monkeypatch.setattr(carousel, "query_file_list", device.list_files)
    monkeypatch.setattr(carousel, "upload_pak", device.upload)


def test_uploads_all_then_cycles_in_order(monkeypatch) -> None:
    device = FakeDevice(initial=["img1.pak"])
    _install(monkeypatch, device)
    controller = FakeController()
    stop = threading.Event()
    entries = _entries(2)

    def fake_sleep(seconds: float) -> None:
        if len(device.display_writes()) > 2:
            stop.set()

    report = run_playlist(
        entries,
        controller=controller,
        transport=device,
        stop_event=stop,
        settle_s=0.0,
        sleeper=fake_sleep,
    )

    assert report.error is None
    # 设备要求连续槽位：img1 已存在 → 依次 img2、img3
    assert device.names == ["img1.pak", "img2.pak", "img3.pak"]
    assert [e.name for e in entries] == ["img2.pak", "img3.pak"]
    assert controller.took_over and controller.released
    assert device.closed
    assert report.cycled >= 1


def test_settle_happens_before_first_display(monkeypatch) -> None:
    """上传完必须先静置，再发显示指令（避免闪官方图）。"""
    device = FakeDevice()
    _install(monkeypatch, device)
    stop = threading.Event()
    timeline: list[str] = []

    def fake_sleep(seconds: float) -> None:
        timeline.append("settle" if seconds == 3.0 else "tick")
        if timeline.count("tick") > 6:
            stop.set()

    run_playlist(
        _entries(1),
        controller=FakeController(),
        transport=device,
        stop_event=stop,
        settle_s=3.0,
        sleeper=fake_sleep,
    )

    assert "settle" in timeline, timeline
    assert device.display_writes(), "静置后必须有显示指令"


def test_missing_file_after_upload_is_error(monkeypatch) -> None:
    """上传后清单里始终没有该文件 → 报错，不启动轮播。"""
    device = FakeDevice()
    monkeypatch.setattr(carousel, "query_file_list", lambda t: [FileEntry("img1.pak", 10)])
    monkeypatch.setattr(carousel, "upload_pak", lambda t, pak, name: None)

    report = run_playlist(
        _entries(1),
        controller=FakeController(),
        transport=device,
        stop_event=threading.Event(),
        settle_s=0.0,
        sleeper=lambda s: None,
    )

    assert report.error and "未出现在设备清单里" in report.error
    assert device.display_writes() == []


def test_build_entries_encodes_each_file(tmp_path: Path) -> None:
    from PIL import Image

    paths = []
    for i, color in enumerate(((255, 0, 0), (0, 0, 255))):
        p = tmp_path / f"f{i}.png"
        Image.new("RGB", (64, 32), color).save(p)
        paths.append(p)

    seen: list[tuple[int, int, str]] = []
    entries = build_entries(
        [(p, 2.5) for p in paths], on_progress=lambda d, t, n: seen.append((d, t, n))
    )

    assert len(entries) == 2
    assert all(e.pak.startswith(b"JP") for e in entries)
    assert [e.seconds for e in entries] == [2.5, 2.5]
    assert seen == [(1, 2, "f0.png"), (2, 2, "f1.png")]
