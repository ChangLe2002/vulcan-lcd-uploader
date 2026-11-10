# SPDX-License-Identifier: MIT
"""清理设备上的「无效缓存」——即本工具上传过、但官方软件不认的文件。

依据抓包（2026-11-05）：官方清理时逐条发送 ``e718 <00> "imgN.pak" 00``。
本模块只删除**台账里记录过的文件**，绝不触碰其他素材。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterable

from .gif_upload import delete_file, query_file_list

__all__ = ["CleanReport", "clear_uploaded_files", "clear_beyond_first"]


@dataclass
class CleanReport:
    deleted: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    error: str | None = None

    def describe(self) -> str:
        if self.error:
            return f"清理失败：{self.error}"
        if not self.deleted:
            return "没有需要清理的文件"
        return f"已清理 {len(self.deleted)} 个：{', '.join(self.deleted)}"


def clear_uploaded_files(
    transport: object,
    names: Iterable[str],
    *,
    settle_s: float = 0.4,
    sleeper=time.sleep,
) -> CleanReport:
    """删除 ``names`` 中确实存在于设备上的文件。

    Args:
        transport: 已打开、已接管串口的 Transport。
        names: 台账里记录的文件名（只删这些）。
        settle_s: 每条删除后的等待时间，给设备处理。
    """
    report = CleanReport()
    try:
        on_device = {entry.name for entry in query_file_list(transport)}
        for name in names:
            if name not in on_device:
                report.skipped.append(name)
                continue
            delete_file(transport, name)
            report.deleted.append(name)
            sleeper(settle_s)
        return report
    except Exception as exc:  # noqa: BLE001 - 清理失败不该抛给 UI
        report.error = str(exc)
        return report


def clear_beyond_first(
    transport: object,
    *,
    keep: str = "img1.pak",
    settle_s: float = 0.4,
    sleeper=time.sleep,
) -> CleanReport:
    """删除除 ``keep`` 之外的**全部**文件（官方垃圾桶的行为）。

    实测（2026-11-06 抓包）：官方「清理无效的LCD图片缓存」就是依次发送
    ``e718 img2 … img6``，保留 img1；删除后设备可用空间从 37.8 MB 回到 49.0 MB。
    也就是说 —— 空间**只能靠删除现存文件回收**。

    Args:
        keep: 要保留的文件名（默认官方占用的 img1.pak）。
    """
    report = CleanReport()
    try:
        on_device = [entry.name for entry in query_file_list(transport)]
        for name in on_device:
            if name == keep:
                report.skipped.append(name)
                continue
            delete_file(transport, name)
            report.deleted.append(name)
            sleeper(settle_s)
        return report
    except Exception as exc:  # noqa: BLE001 - 清理失败不该抛给 UI
        report.error = str(exc)
        return report
