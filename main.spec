# -*- mode: python ; coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""PyInstaller 打包配置。

关键点
------
* ``pathex`` 必须包含 ``src``，否则 ``vulcan_lcd`` 包不会被收进来；
* ``serial`` 是 **pyserial 的模块名**，写 ``pyserial`` 是无效的；
* 配置与注册表作为**数据文件**随包分发（运行期从 ``_MEIPASS`` 读取）；
* ``VULCAN_CONSOLE=1`` 时生成控制台版（排查闪退用），默认窗口版；
* 刻意排除 numpy/pandas/matplotlib —— 本项目不用，带上会让产物膨胀几十 MB。
"""

import os
from pathlib import Path

ROOT = Path(SPECPATH).resolve()
CONSOLE = os.environ.get("VULCAN_CONSOLE") == "1"

datas = [
    (str(ROOT / "build_assets" / "app.ico"), "."),
    (str(ROOT / "src" / "vulcan_lcd" / "ui2" / "assets"), "ui2_assets"),
    (str(ROOT / "config" / "settings.default.json"), "config"),
    (str(ROOT / "feature_registry.json"), "."),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
]

hiddenimports = [
    "serial",
    "serial.tools",
    "serial.tools.list_ports",
    "pynvml",
    "psutil",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
]

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT / "src"), str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "numpy",
        "pandas",
        "matplotlib",
        "scipy",
        "PySide6.QtWebEngineCore",
        "PySide6.QtQuick",
        "PySide6.QtQml",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VulcanLCDUploader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=CONSOLE,
    icon=str(ROOT / "build_assets" / "app.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="VulcanLCDUploader",
)
