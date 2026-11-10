# SPDX-License-Identifier: MIT
"""开机自启动（当前用户级 Run 键，无需管理员）。"""

from __future__ import annotations

import sys
from pathlib import Path

__all__ = ["is_enabled", "enable", "disable", "target_command"]

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "VulcanLCDUploader"


def target_command() -> str:
    """要写进注册表的启动命令。

    * 打包版：exe 自身；
    * 源码运行：pythonw + main.py（避免每次弹控制台）。
    """
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    launcher = pythonw if pythonw.is_file() else exe
    script = Path(__file__).resolve().parents[3] / "main.py"
    return f'"{launcher}" "{script}"'


def _open_key(write: bool):
    import winreg  # noqa: PLC0415 - 仅 Windows

    return winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        _RUN_KEY,
        0,
        winreg.KEY_SET_VALUE if write else winreg.KEY_READ,
    )


def is_enabled() -> bool:
    """注册表里是否有我们的启动项。"""
    try:
        import winreg  # noqa: PLC0415

        with _open_key(write=False) as key:
            value, _ = winreg.QueryValueEx(key, _VALUE_NAME)
            return bool(str(value).strip())
    except FileNotFoundError:
        return False
    except OSError:
        return False


def enable() -> bool:
    """写入开机自启；成功返回 True。"""
    try:
        import winreg  # noqa: PLC0415

        with _open_key(write=True) as key:
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, target_command())
        return True
    except OSError:
        return False


def disable() -> bool:
    """移除开机自启；没有该项也算成功。"""
    try:
        import winreg  # noqa: PLC0415

        with _open_key(write=True) as key:
            winreg.DeleteValue(key, _VALUE_NAME)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False
