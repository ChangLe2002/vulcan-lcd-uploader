# SPDX-License-Identifier: MIT
"""独立模式（不管理官方服务）的测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from vulcan_lcd.features.ui_prefs import CLOSE_TO_TRAY, STANDALONE, load_prefs, save_prefs
from vulcan_lcd.system.service_control import (
    ServiceController,
    is_standalone,
    set_standalone,
)


@pytest.fixture(autouse=True)
def _reset():
    set_standalone(False)
    yield
    set_standalone(False)


def test_flag_roundtrip() -> None:
    assert is_standalone() is False
    set_standalone(True)
    assert is_standalone() is True
    set_standalone(False)
    assert is_standalone() is False


def test_standalone_never_touches_service() -> None:
    """独立模式下 takeover/release/stop 都不执行任何服务操作。"""
    set_standalone(True)
    controller = ServiceController("NoSuchService-ForTest")
    assert controller.takeover() is False
    assert controller.release() is False
    assert controller.stop() is False


def test_normal_mode_still_works_on_missing_service() -> None:
    """非独立模式下，服务不存在也不该抛异常（安全降级）。"""
    controller = ServiceController("NoSuchService-ForTest")
    assert controller.takeover() is False


def test_prefs_defaults_to_normal_mode(tmp_path: Path) -> None:
    prefs = load_prefs(tmp_path)
    assert prefs[STANDALONE] is False
    assert prefs[CLOSE_TO_TRAY] is True


def test_prefs_persists_standalone(tmp_path: Path) -> None:
    save_prefs(tmp_path, {CLOSE_TO_TRAY: True, STANDALONE: True})
    assert load_prefs(tmp_path)[STANDALONE] is True
