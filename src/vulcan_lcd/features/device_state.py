# SPDX-License-Identifier: MIT
"""设备状态缓存：可用空间 / 固件 / 亮度等。

串口是独占的，查这些信息必须停官方服务，不能随时刷新。
因此每次我们自己占用串口（上传、清理、设置、轮播）时顺手读取一次，
存进内存 + JSON，界面显示"上次读取"的值。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

__all__ = ["DeviceState", "remember", "cached", "load", "save", "describe_free"]

_CACHE: "DeviceState | None" = None


@dataclass
class DeviceState:
    free_bytes: int | None = None
    firmware: str = ""
    brightness: int | None = None
    device_id: int | None = None
    op_type: int | None = None
    updated_at: str = ""

    def describe(self) -> str:
        parts: list[str] = []
        if self.free_bytes is not None:
            parts.append(f"可用 {self.free_bytes / 1024 / 1024:.0f} MB")
        if self.firmware:
            parts.append(f"固件 {self.firmware}")
        if self.brightness is not None:
            parts.append(f"亮度 {self.brightness}/10")
        if self.updated_at:
            parts.append(f"上次读取 {self.updated_at}")
        return " · ".join(parts)


def describe_free(free: int | None) -> str:
    """把字节数变成人类可读。"""
    if free is None:
        return "未知"
    mb = free / 1024 / 1024
    return f"{mb:.0f} MB" if mb >= 1 else f"{free / 1024:.0f} KB"


def remember(state: DeviceState, *, path: Path | None = None) -> DeviceState:
    """记住最新状态（内存 + 可选落盘）。"""
    global _CACHE
    state.updated_at = datetime.now().strftime("%H:%M:%S")
    _CACHE = state
    if path is not None:
        save(path, state)
    return state


def cached() -> DeviceState | None:
    return _CACHE


def save(path: Path, state: DeviceState) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(state), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def load(path: Path) -> DeviceState | None:
    """从磁盘恢复上次状态（启动时用，避免空白）。"""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        _CACHE = DeviceState(**{k: data.get(k) for k in DeviceState.__annotations__})
    except (TypeError, ValueError):
        return None
    return _CACHE
