# SPDX-License-Identifier: MIT
"""「关于」窗口：作者署名与目录说明的回归测试。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from vulcan_lcd.meta import (  # noqa: E402
    APP_AUTHOR,
    APP_LICENSE,
    APP_NAME,
    APP_VERSION,
    PROJECT_URL,
    runtime_folder_rows,
)
from vulcan_lcd.ui2.about import about_html  # noqa: E402


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


def test_meta_has_author_and_license() -> None:
    assert APP_AUTHOR == "常乐"
    assert APP_LICENSE == "MIT"
    assert APP_NAME in ("火神智屏图传工具",)
    assert APP_VERSION
    assert PROJECT_URL.startswith("https://")


def test_about_html_mentions_author_and_folders() -> None:
    html = about_html(r"F:\shuchu")
    assert "常乐" in html
    assert "MIT" in html
    assert "作者" in html
    # 目录说明：日志 / 偏好 / 素材库 / 设备缓存
    for keyword in ("logs", "ui_prefs.json", "recent_files.json", "device_state.json"):
        assert keyword in html, keyword


def test_about_html_shows_current_install_dir() -> None:
    """顶部显示真实安装目录，表格用占位符保持可读。"""
    html = about_html(r"D:\Apps\Vulcan")
    assert r"D:\Apps\Vulcan" in html
    assert r"<安装目录>\logs" in html


def test_author_not_duplicated() -> None:
    """作者名只应出现一次展示（曾出现「常乐（常乐（Changle））」）。"""
    html = about_html(r"F:\shuchu")
    assert "常乐（常乐" not in html


def test_runtime_folder_rows_are_complete() -> None:
    rows = runtime_folder_rows()
    assert len(rows) >= 5
    for name, path, desc in rows:
        assert name and path and desc


def test_about_dialog_builds(app) -> None:
    from vulcan_lcd.ui2.about import AboutDialog

    dialog = AboutDialog(install_dir=Path(r"F:\shuchu"))
    assert dialog.windowTitle() == f"关于 {APP_NAME}"
    dialog.deleteLater()


def test_about_follows_install_dir() -> None:
    """关于里的路径必须跟着程序实际位置走，不能写死。"""
    first = about_html(r"F:\shuchu")
    second = about_html(r"C:\Users\someone\AppData\Local\Programs\VulcanLCDUploader")
    assert "F:\\shuchu" in first
    assert "C:\\Users\\someone\\AppData\\Local\\Programs\\VulcanLCDUploader" in second
    assert "F:\\shuchu" not in second


def test_about_does_not_hardcode_install_path() -> None:
    rows = runtime_folder_rows()
    paths = [path for _name, path, _desc in rows]
    assert not any("Programs" in p for p in paths), paths
