# SPDX-License-Identifier: MIT
"""播放列表轮播：一次接管串口，先全部上传，校验后再循环显示。

设计要点（针对实测现象）
------------------------
* 上传刚结束时设备还在做文件注册，此时立刻发显示指令会出现
  「闪一下官方图 / 显示上传中」——所以上传完要**校验清单**并**等待稳定**
  （``settle_s``）再开始轮播。
* 轮播只重复发送 ``E51A <name> 00``，每秒一次，切文件时天然无缝。
* 全程只接管一次串口，避免每个素材都停/启官方服务。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from ..media.encode import encode_media_to_pak
from .gif_upload import (
    FileEntry,
    build_display_frame,
    next_slot_name,
    query_file_list,
    query_free_space,
    upload_pak,
)

__all__ = [
    "PlaylistEntry",
    "PlaylistReport",
    "build_entries",
    "run_playlist",
]


@dataclass
class PlaylistEntry:
    """一条播放项：本地文件 → 已编码的 pak + 设备文件名。"""

    path: Path
    pak: bytes
    name: str
    seconds: float


@dataclass
class PlaylistReport:
    uploaded: list[str] = field(default_factory=list)
    cycled: int = 0
    error: str | None = None

    def describe(self) -> str:
        if self.error:
            return f"轮播失败：{self.error}"
        return f"已上传 {len(self.uploaded)} 个，轮播 {self.cycled} 次切换"


def build_entries(
    items: Sequence[tuple[Path | str, float]],
    *,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> list[PlaylistEntry]:
    """把本地文件逐个编码成 pak（纯 CPU，可在工作线程里跑）。

    Args:
        items: ``[(路径, 停留秒数), …]``；每项可以有自己的停留时间。
    """
    entries: list[PlaylistEntry] = []
    total = len(items)
    for index, (raw, seconds) in enumerate(items):
        path = Path(raw)
        encoded = encode_media_to_pak(path, rotation="180", target_fps=0)
        entries.append(
            PlaylistEntry(
                path=path,
                pak=encoded.pak,
                name=path.name,
                seconds=max(1.0, float(seconds)),
            )
        )
        if on_progress is not None:
            on_progress(index + 1, total, path.name)
    return entries


def _wait_registered(
    transport: object,
    name: str,
    *,
    attempts: int = 6,
    sleeper: Callable[[float], None] = time.sleep,
) -> bool:
    """轮询清单直到文件出现（设备登记有延迟）。"""
    for _ in range(max(1, attempts)):
        try:
            if any(item.name == name for item in query_file_list(transport)):
                return True
        except Exception:  # noqa: BLE001
            pass
        sleeper(0.5)
    return False


def run_playlist(
    entries: Sequence[PlaylistEntry],
    *,
    controller: object,
    transport: object,
    stop_event: object,
    on_status: Callable[[str], None] | None = None,
    on_state: Callable[[object], None] | None = None,
    settle_s: float = 2.5,
    verify_attempts: int = 5,
    sleeper: Callable[[float], None] = time.sleep,
) -> PlaylistReport:
    """上传全部素材后循环显示，直到 ``stop_event`` 被置位。

    Args:
        settle_s: 全部上传完后的静置时间；设备此刻仍在做文件注册，
            立刻切换会闪官方图（实测）。
        verify_attempts: 校验清单的轮询次数（每次 1 秒）。
    """
    report = PlaylistReport()
    if not entries:
        report.error = "播放列表为空"
        return report

    took_over = False
    try:
        controller.takeover()  # type: ignore[attr-defined]
        took_over = True

        last_error: Exception | None = None
        for _ in range(20):
            try:
                transport.open()  # type: ignore[attr-defined]
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                sleeper(1.0)
        if last_error is not None:
            report.error = f"打不开串口：{last_error}"
            return report

        # 0) 空间预检：无效缓存会占着空间不释放，空间不足时上传会假成功
        total_bytes = sum(len(entry.pak) for entry in entries)
        free = query_free_space(transport)
        if free is not None and total_bytes > max(0, free - 1024 * 1024):
            report.error = (
                f"设备空间不足：需要 {total_bytes / 1024 / 1024:.1f} MB，"
                f"可用 {free / 1024 / 1024:.1f} MB。"
                "请先在 iGame Center 里点图库右下角的垃圾桶清理无效缓存。"
            )
            return report

        # 1) 逐个上传。
        #    设备清单有延迟：刚传完的文件可能还没出现在 e619 应答里，
        #    所以槽位要把「本次已分配的」一起算进去，否则第二项会重名覆盖；
        #    每传完一个还要等它真的登记，再继续下一项。
        assigned: list[str] = []
        for entry in entries:
            try:
                listed = query_file_list(transport)
            except Exception:  # noqa: BLE001
                listed = []
            merged = list(listed) + [FileEntry(name, 0) for name in assigned]
            slot = next_slot_name(merged)

            upload_pak(transport, entry.pak, name=slot)
            entry.name = slot
            assigned.append(slot)
            report.uploaded.append(slot)
            if on_status is not None:
                on_status(f"已上传 {entry.path.name} → {slot}")

            if not _wait_registered(transport, slot, sleeper=sleeper):
                # 设备偶尔漏登记：补传一次再等
                if on_status is not None:
                    on_status(f"{slot} 暂未登记，补传一次…")
                upload_pak(transport, entry.pak, name=slot)
                if not _wait_registered(transport, slot, sleeper=sleeper):
                    report.error = f"{slot} 上传后未出现在设备清单里"
                    return report

        # 2) 校验：所有文件都出现在清单里才算上传完成。
        #    设备注册有延迟，缺哪个就补传哪个（最多两轮）。
        for attempt in range(2):
            missing: set[str] = set()
            for _ in range(verify_attempts):
                try:
                    present = {item.name for item in query_file_list(transport)}
                except Exception:  # noqa: BLE001
                    present = set()
                missing = {entry.name for entry in entries} - present
                if not missing:
                    break
                sleeper(1.0)
            if not missing:
                break
            if attempt == 0:
                if on_status is not None:
                    on_status(f"清单暂未出现 {sorted(missing)}，补传一次…")
                for entry in entries:
                    if entry.name in missing:
                        upload_pak(transport, entry.pak, name=entry.name)
        if missing:
            report.error = f"上传后清单缺少文件：{sorted(missing)}"
            return report

        if on_state is not None:
            try:
                on_state(transport)
            except Exception:  # noqa: BLE001
                pass

        # 3) 静置：等设备结束注册/收起"上传中"提示，避免第一圈闪烁
        if settle_s > 0:
            sleeper(settle_s)

        # 4) 循环显示
        if on_status is not None:
            on_status("开始轮播")
        index = 0
        while not stop_event.is_set():  # type: ignore[attr-defined]
            entry = entries[index % len(entries)]
            if on_status is not None:
                on_status(f"正在显示 {entry.name}（{entry.seconds:.0f}s）")
            deadline = time.monotonic() + max(0.5, entry.seconds)
            while time.monotonic() < deadline:
                if stop_event.is_set():  # type: ignore[attr-defined]
                    break
                transport.write(build_display_frame(entry.name))  # type: ignore[attr-defined]
                transport.flush()  # type: ignore[attr-defined]
                sleeper(min(1.0, max(0.05, deadline - time.monotonic())))
            report.cycled += 1
            index += 1
        return report
    except Exception as exc:  # noqa: BLE001 - 轮播失败不该炸 UI
        report.error = str(exc)
        return report
    finally:
        try:
            transport.close()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
        if took_over:
            try:
                controller.release()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass
