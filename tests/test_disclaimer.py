# SPDX-License-Identifier: MIT
"""首次启动免责声明的测试（倒计时锁定 + 偏好写入）。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtGui import QCloseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from vulcan_lcd.features.ui_prefs import (  # noqa: E402
    DISCLAIMER_ACCEPTED,
    load_prefs,
    save_prefs,
)
from vulcan_lcd.ui2.disclaimer import DISCLAIMER_HTML, DisclaimerDialog  # noqa: E402


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


def test_prefs_defaults_to_unaccepted(tmp_path: Path) -> None:
    assert load_prefs(tmp_path)[DISCLAIMER_ACCEPTED] is False


def test_html_covers_required_topics() -> None:
    """说明文本必须覆盖：免责声明、功能用法、协议规范、制作方式与语言。"""
    for keyword in (
        "免责声明",
        "01 设备连接",
        "02 硬件监控",
        "03 播放列表",
        "04 投屏内容",
        "05 设备设置",
        "06 调试",
        "CC BY-SA",
        "MIT",
        "Python",
        "PySide6",
        "PyInstaller",
        "ffmpeg",
        "反编译",
    ):
        assert keyword in DISCLAIMER_HTML, keyword


def test_cannot_close_before_countdown(app, tmp_path: Path) -> None:
    dialog = DisclaimerDialog(seconds=5, root=tmp_path)
    assert dialog.btn_accept.isEnabled() is False
    assert "5 秒" in dialog.btn_accept.text()

    event = QCloseEvent()
    dialog.closeEvent(event)          # 期间点 X 应被忽略
    assert event.isAccepted() is False
    assert "还剩" in dialog.hint.text()

    dialog.reject()                   # Esc 同样无效
    assert dialog.isVisible() is False  # 未 show 过，但不该抛异常

    dialog.deleteLater()


def test_unlocks_after_countdown(app, tmp_path: Path) -> None:
    dialog = DisclaimerDialog(seconds=2, root=tmp_path)
    dialog._tick()                    # 2 → 1
    assert dialog.btn_accept.isEnabled() is False
    dialog._tick()                    # 1 → 0
    assert dialog.btn_accept.isEnabled() is True
    assert "秒" not in dialog.btn_accept.text()


def test_accept_persists_preference(app, tmp_path: Path) -> None:
    dialog = DisclaimerDialog(seconds=0, root=tmp_path)
    assert dialog.btn_accept.isEnabled() is True   # 0 秒立即解锁

    dialog._on_accept()
    assert load_prefs(tmp_path)[DISCLAIMER_ACCEPTED] is True


def test_zero_seconds_skips_lock(app, tmp_path: Path) -> None:
    """「帮助 → 免责声明」重开时用 0 秒，应立即可关闭。"""
    dialog = DisclaimerDialog(seconds=0, root=tmp_path)
    event = QCloseEvent()
    dialog.closeEvent(event)
    assert event.isAccepted() is True


def test_accept_does_not_override_existing_prefs(app, tmp_path: Path) -> None:
    save_prefs(tmp_path, {DISCLAIMER_ACCEPTED: True, "close_to_tray": True})
    dialog = DisclaimerDialog(seconds=0, root=tmp_path)
    dialog._on_accept()
    prefs = load_prefs(tmp_path)
    assert prefs[DISCLAIMER_ACCEPTED] is True
    assert prefs["close_to_tray"] is True


def test_prefs_tolerates_bom(tmp_path: Path) -> None:
    """记事本/PowerShell 写出的带 BOM JSON 也要能读（否则偏好静默失效）。"""
    (tmp_path / "ui_prefs.json").write_text(
        '\ufeff{"close_to_tray": false, "standalone_mode": true}',
        encoding="utf-8",
    )
    prefs = load_prefs(tmp_path)
    assert prefs["close_to_tray"] is False
    assert prefs["standalone_mode"] is True
