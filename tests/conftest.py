# SPDX-License-Identifier: MIT
"""pytest 全局配置。

职责：
1. 把 ``src`` 加入导入路径，使测试无需把项目安装成包即可运行；
2. 按需生成测试素材（一段 3 帧 / 1.5 秒的 GIF），避免把二进制文件提交进仓库。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
SAMPLE_GIF = FIXTURE_DIR / "test_upload.gif"


def ensure_sample_gif(path: Path = SAMPLE_GIF) -> Path:
    """生成 800×216、3 帧、每帧 500ms（合计 1.5 秒）的 GIF；已存在则直接返回。"""
    if path.is_file():
        return path

    from PIL import Image  # noqa: PLC0415 - 只有需要时才导入

    path.parent.mkdir(parents=True, exist_ok=True)
    colours = ((220, 40, 40), (40, 200, 80), (40, 80, 220))
    frames = [Image.new("RGB", (800, 216), colour) for colour in colours]
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=500,          # 每帧 500ms × 3 = 1.5s
        loop=0,
        optimize=False,
    )
    return path


@pytest.fixture(scope="session", autouse=True)
def _prepare_fixtures() -> None:
    """会话开始前准备好测试素材（失败不阻断测试，相关用例会自行跳过）。"""
    try:
        ensure_sample_gif()
    except Exception:  # noqa: BLE001 - 素材生成失败时由用例的 skipif 兜底
        pass
