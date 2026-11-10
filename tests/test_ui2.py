# SPDX-License-Identifier: MIT
"""新界面（ui2）的结构冒烟测试：只验证能否装配，不碰设备。"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from vulcan_lcd.app import build_context  # noqa: E402
from vulcan_lcd.diagnostics.debug_session import DebugSession  # noqa: E402
from vulcan_lcd.ui2.window import LCD_RECT, NewMainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


@pytest.fixture(scope="module")
def window(app):
    ctx = build_context(DebugSession(dry_run=True), console_log=False)
    win = NewMainWindow(ctx)
    yield win
    win.close()


def test_window_builds(window) -> None:
    assert window.windowTitle().startswith("火神智屏")
    assert window.centralWidget() is not None


def test_has_all_cards(window) -> None:
    """01-06 六张卡片齐全。"""
    assert window.link_card is not None          # 01 设备连接
    assert window.telemetry is not None          # 02 硬件监控
    assert window.playlist is not None           # 03 播放列表
    assert window.feed is not None               # 04 投屏内容
    assert window.settings is not None           # 05 设备设置
    assert window.debug is not None              # 06 调试


def test_nav_buttons(window) -> None:
    labels = [btn.text() for btn in window.nav_buttons]
    assert labels == ["控制台", "播放列表", "硬件监控", "调试"]
    assert window.nav_buttons[0].property("active") is True


def test_case_view_has_background_and_lcd(window) -> None:
    """机箱底图要加载成功，且 LCD 位置在底图范围内。"""
    assert not window.case._bg.isNull()
    assert 0 <= LCD_RECT.x() < window.case._bg.width()
    assert 0 <= LCD_RECT.y() < window.case._bg.height()


def test_feed_and_settings_controls(window) -> None:
    assert window.feed.btn_pick.text() == "选择文件"
    assert window.feed.btn_upload.text() == "上传到屏幕"
    assert window.settings.brightness.maximum() == 10
    assert window.settings.start_image.count() >= 1


def test_portrait_preview_reaches_case(window, tmp_path) -> None:
    """选中素材后，机箱小屏应该拿到一张竖装预览图。"""
    from PIL import Image

    path = tmp_path / "still.png"
    Image.new("RGB", (800, 216), (10, 120, 200)).save(path)

    window.feed.load_path(path)
    for _ in range(40):
        QApplication.processEvents()

    assert window.feed._portrait is not None
    assert not window.feed._portrait.isNull()
    # 旋转 90° 后应该是竖图
    assert window.feed._portrait.height() > window.feed._portrait.width()


def test_hidden_parks_all_timers(window) -> None:
    """最小化到托盘后所有轮询定时器必须停掉（否则托盘不省电）。"""
    window.show()
    QApplication.processEvents()
    assert window.telemetry.timer.isActive()
    assert window.debug.timer.isActive()
    assert window._clock.isActive()

    window.hide()
    QApplication.processEvents()
    assert not window.telemetry.timer.isActive()
    assert not window.debug.timer.isActive()
    assert not window._clock.isActive()

    window.show()
    QApplication.processEvents()
    assert window.telemetry.timer.isActive()
    assert window._clock.isActive()


def test_working_set_trim_is_safe_to_call() -> None:
    """工作集回收只做优化，任何环境调用都不能抛异常。"""
    from vulcan_lcd.ui2.window import _trim_working_set

    _trim_working_set()
