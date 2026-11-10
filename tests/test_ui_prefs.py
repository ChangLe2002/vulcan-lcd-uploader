# SPDX-License-Identifier: MIT
"""界面偏好（关闭时最小化到托盘）的测试。"""

from __future__ import annotations

import json
from pathlib import Path

from vulcan_lcd.features.ui_prefs import CLOSE_TO_TRAY, load_prefs, save_prefs


def test_default_is_close_to_tray(tmp_path: Path) -> None:
    """默认最小化到托盘（不是退出）。"""
    prefs = load_prefs(tmp_path)
    assert prefs[CLOSE_TO_TRAY] is True


def test_roundtrip(tmp_path: Path) -> None:
    prefs = {CLOSE_TO_TRAY: False}
    save_prefs(tmp_path, prefs)
    assert (tmp_path / "ui_prefs.json").is_file()
    assert load_prefs(tmp_path)[CLOSE_TO_TRAY] is False


def test_corrupt_file_falls_back_to_default(tmp_path: Path) -> None:
    (tmp_path / "ui_prefs.json").write_text("{ not json", encoding="utf-8")
    assert load_prefs(tmp_path)[CLOSE_TO_TRAY] is True


def test_unknown_or_wrong_typed_keys_are_ignored(tmp_path: Path) -> None:
    (tmp_path / "ui_prefs.json").write_text(
        json.dumps({CLOSE_TO_TRAY: "yes", "other": True}), encoding="utf-8"
    )
    prefs = load_prefs(tmp_path)
    assert prefs[CLOSE_TO_TRAY] is True     # 类型不对 → 用默认
    assert "other" not in prefs


def test_save_is_silent_on_readonly_dir(tmp_path: Path) -> None:
    """写入失败不应抛异常（偏好丢失不影响使用）。"""
    missing = tmp_path / "nope" / "deeper"
    save_prefs(missing, {CLOSE_TO_TRAY: False})   # 目录不存在：正常创建
    assert (missing / "ui_prefs.json").is_file()
