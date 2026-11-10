# SPDX-License-Identifier: MIT
"""素材库（上传历史）与开机自启的测试。"""

from __future__ import annotations

from pathlib import Path

from vulcan_lcd.features.autostart import target_command
from vulcan_lcd.features.history import MAX_ITEMS, History


def test_history_empty_by_default(tmp_path: Path) -> None:
    assert History(tmp_path / "recent_files.json").load() == []


def test_history_add_dedupes_and_moves_to_front(tmp_path: Path) -> None:
    media = tmp_path / "a.gif"
    media.write_bytes(b"GIF89a")
    other = tmp_path / "b.gif"
    other.write_bytes(b"GIF89a")

    ledger = History(tmp_path / "recent_files.json")
    ledger.add(media)
    ledger.add(other)
    ledger.add(media)   # 再用一次 → 提到最前

    items = ledger.load()
    assert [i.name for i in items] == ["a.gif", "b.gif"]
    assert items[0].used_at  # 有时间戳


def test_history_prune_missing(tmp_path: Path) -> None:
    alive = tmp_path / "alive.gif"
    alive.write_bytes(b"GIF89a")
    gone = tmp_path / "gone.gif"
    gone.write_bytes(b"x")

    ledger = History(tmp_path / "recent_files.json")
    ledger.add(alive)
    ledger.add(gone)
    gone.unlink()

    items = ledger.prune_missing()
    assert [i.name for i in items] == ["alive.gif"]


def test_history_caps_length(tmp_path: Path) -> None:
    ledger = History(tmp_path / "recent_files.json")
    for index in range(MAX_ITEMS + 5):
        path = tmp_path / f"f{index}.gif"
        path.write_bytes(b"x")
        ledger.add(path)
    assert len(ledger.load()) == MAX_ITEMS


def test_history_tolerates_corrupt_file(tmp_path: Path) -> None:
    (tmp_path / "recent_files.json").write_text("{oops", encoding="utf-8")
    assert History(tmp_path / "recent_files.json").load() == []


def test_autostart_command_points_at_app() -> None:
    command = target_command()
    assert command.startswith('"')
    assert "main.py" in command or command.lower().endswith(".exe\"")
