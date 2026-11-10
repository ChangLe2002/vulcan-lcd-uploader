# SPDX-License-Identifier: MIT
"""界面偏好设置（可写目录中的 ui_prefs.json）。

目前两项：关闭窗口是否最小化到托盘（默认是）、独立模式（默认否）。
"""

from __future__ import annotations

import json
from pathlib import Path

__all__ = ["load_prefs", "save_prefs", "CLOSE_TO_TRAY", "STANDALONE", "DISCLAIMER_ACCEPTED"]

CLOSE_TO_TRAY = "close_to_tray"
# 独立模式：不管理官方服务（适合没装/不用 iGame Center 的机器）
STANDALONE = "standalone_mode"
# 首次启动的免责声明是否已确认
DISCLAIMER_ACCEPTED = "disclaimer_accepted"
_DEFAULTS = {CLOSE_TO_TRAY: True, STANDALONE: False, DISCLAIMER_ACCEPTED: False}


def _path(root: str | Path) -> Path:
    return Path(root) / "ui_prefs.json"


def load_prefs(root: str | Path) -> dict:
    """读取偏好；文件不存在或损坏时返回默认值。"""
    prefs = dict(_DEFAULTS)
    try:
        data = json.loads(_path(root).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return prefs
    if isinstance(data, dict):
        for key, value in data.items():
            if key in _DEFAULTS and isinstance(value, bool):
                prefs[key] = value
    return prefs


def save_prefs(root: str | Path, prefs: dict) -> None:
    """写回偏好（失败静默：偏好丢失不该影响使用）。"""
    try:
        path = _path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(prefs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError:
        pass
