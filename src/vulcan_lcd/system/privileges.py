# SPDX-License-Identifier: MIT
"""权限检测。

只做"我们有没有管理员权限"这一件事，**不主动提权**——提权需要重启进程，
属于应用启动流程（模块 9），放在这里会让本模块难以测试。
"""

from __future__ import annotations

import sys

__all__ = ["is_admin", "is_windows"]


def is_windows() -> bool:
    return sys.platform == "win32"


def is_admin() -> bool:
    """当前进程是否具备管理员权限。

    非 Windows 或调用失败一律返回 ``False``——宁可误报"没有权限"，
    也不要误报"有权限"后去操作服务。
    """
    if not is_windows():
        return False
    try:
        import ctypes  # noqa: PLC0415

        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return False
