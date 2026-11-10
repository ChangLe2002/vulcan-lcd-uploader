# SPDX-License-Identifier: MIT
"""把监控数据持续发给屏幕（设备自己渲染，无需上传图片）。

实测（2026-11-06 真机）：发送 `CPU5` / `GPU3` 帧后，屏幕会切换到**设备自带的
监控界面**并显示数值；停止发送并恢复官方服务后回到官方画面。
"""

from __future__ import annotations

import time
from typing import Callable

from .monitor_data import (
    CPU_FREQ,
    CPU_LOAD,
    CPU_RAM,
    GPU_FREQ,
    GPU_LOAD,
    GPU_TEMP,
    build_cpu1,
    build_cpu5,
    build_gpu1,
    build_gpu3,
)
from .sensors import read_cpu, read_gpu

__all__ = ["LAYOUTS", "PAGES", "run_monitor_stream"]

#: 布局选项：只发 GPU / 只发 CPU / 两者都发
#: 每个「页」= 设备上的一屏。轮播时按顺序每 N 秒切一页。
#: 只保留**本机确实读得到**的指标：CPU 温度、CPU/GPU 电压在 Windows +
#: 消费级显卡上都拿不到，强制发送会让屏幕显示 0°C / 0.00V，所以不放进页面。
PAGES = {
    "gpu_core": "显卡：负载 / 温度 / 频率（全部指标本机可读）",
    "cpu_cycle": "处理器：负载 → 频率 → 内存（单指标轮显，不含读不到的温度/电压）",
}

LAYOUTS = {
    "gpu_core": "显卡：负载/温度/频率",
    "cpu_cycle": "处理器：负载/频率/内存（轮显）",
}


def run_monitor_stream(
    *,
    controller: object,
    transport: object,
    stop_event: object,
    layout: str = "both",
    interval_s: float = 1.0,
    on_status: Callable[[str], None] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> str | None:
    """持续发送监控帧，直到 ``stop_event`` 置位。返回错误信息（成功为 None）。"""
    took_over = False
    try:
        controller.takeover()  # type: ignore[attr-defined]
        took_over = True

        last: Exception | None = None
        for _ in range(20):
            try:
                transport.open()  # type: ignore[attr-defined]
                last = None
                break
            except Exception as exc:  # noqa: BLE001
                last = exc
                sleeper(1.0)
        if last is not None:
            return f"打不开串口：{last}"

        # 把 layout 展开成「页面序列」，每页停留 page_seconds
        pages: list[tuple[str, int | None]] = []
        if layout == "cpu_cycle":
            pages = [("cpu1", CPU_LOAD), ("cpu1", CPU_FREQ), ("cpu1", CPU_RAM)]
        else:  # gpu_core（也是未知值的兜底）
            pages = [("gpu3", 1)]

        page_seconds = max(2.0, interval_s * 4)
        index = 0
        sent = 0
        next_switch = time.monotonic() + page_seconds
        while not stop_event.is_set():  # type: ignore[attr-defined]
            if len(pages) > 1 and time.monotonic() >= next_switch:
                index = (index + 1) % len(pages)
                next_switch = time.monotonic() + page_seconds

            kind, arg = pages[index]
            gpu = read_gpu()
            cpu = read_cpu()
            if kind == "gpu3":
                frame = build_gpu3(gpu, part=int(arg or 1))
                label = "显卡" if arg == 1 else "显卡(风扇/显存)"
            elif kind == "cpu5":
                frame = build_cpu5(cpu)
                label = "处理器(全部)"
            else:
                frame = build_cpu1(cpu, int(arg if arg is not None else CPU_LOAD))
                label = {CPU_LOAD: "CPU 负载", CPU_FREQ: "CPU 频率", CPU_RAM: "内存占用"}.get(
                    int(arg if arg is not None else 0), "CPU"
                )
            try:
                transport.write(frame)  # type: ignore[attr-defined]
                transport.flush()  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                return f"发送中断：{exc}"
            sent += 1
            if on_status is not None:
                on_status(
                    f"[{label}] 第 {sent} 次 · GPU {gpu.load}% {gpu.temp}°C"
                    f" · CPU {cpu.load}% {cpu.freq}MHz"
                )
            sleeper(max(0.3, interval_s))
        return None
    except Exception as exc:  # noqa: BLE001 - 监控失败不应炸 UI
        return str(exc)
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
