# SPDX-License-Identifier: MIT
"""Vulcan LCD Uploader —— 七彩虹 iGame RTX 50 系火神智屏（800x216）图传工具。

非官方工具，与七彩虹 / iGame 无隶属关系。

包导入时刻意不导入任何重依赖（PySide6 / serial / pynvml），
以便单元测试与无 GUI 场景（--dry-run、打包前自检）可以低成本导入本包。
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
