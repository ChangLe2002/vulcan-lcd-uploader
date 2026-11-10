# SPDX-License-Identifier: MIT
"""子进程调用工具：保证不弹控制台窗口。

打包后的 GUI 程序没有控制台，直接 ``subprocess.run(["sc", ...])`` 会让 Windows
为子进程分配一个新的控制台窗口 —— 表现就是"桌面一直闪黑框"。
所有子进程调用都必须带上 ``CREATE_NO_WINDOW``。
"""

from __future__ import annotations

import subprocess

__all__ = ["CREATE_NO_WINDOW", "hidden_kwargs", "run"]

# Windows: 不为子进程创建控制台窗口
CREATE_NO_WINDOW = 0x08000000


def hidden_kwargs() -> dict:
    """返回让子进程**不弹窗**的 kwargs（非 Windows 上为空字典）。"""
    import os  # noqa: PLC0415

    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": CREATE_NO_WINDOW, "startupinfo": startupinfo}


def run(args, **kwargs):
    """``subprocess.run`` 的隐藏窗口版本（参数与返回值完全一致）。"""
    merged = hidden_kwargs()
    merged.update(kwargs)          # 允许调用方覆盖（极少需要）
    return subprocess.run(args, **merged)
