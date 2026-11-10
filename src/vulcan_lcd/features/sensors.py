# SPDX-License-Identifier: MIT
"""本机传感器采集（不依赖 iGame Center）：GPU 走 NVML，CPU/内存走 psutil。"""

from __future__ import annotations

import platform

from .monitor_data import CpuSnapshot, GpuSnapshot

__all__ = ["read_gpu", "read_cpu", "gpu_available"]


def gpu_available() -> bool:
    """能否读到 NVIDIA 显卡（NVML 可用）。"""
    try:
        import pynvml  # noqa: PLC0415

        pynvml.nvmlInit()
        pynvml.nvmlShutdown()
        return True
    except Exception:  # noqa: BLE001
        return False


def read_gpu() -> GpuSnapshot:
    """读取一次 GPU 读数；不可用的项保持 None（发送时按 0 处理）。"""
    snap = GpuSnapshot()
    try:
        import pynvml  # noqa: PLC0415

        pynvml.nvmlInit()
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode(errors="replace")
            clean = str(name).replace("NVIDIA ", "").replace("GeForce ", "").upper()
            snap.name = clean
            snap.load = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
            snap.temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            snap.freq = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_GRAPHICS)
            try:
                snap.freq_max = pynvml.nvmlDeviceGetMaxClockInfo(
                    handle, pynvml.NVML_CLOCK_GRAPHICS
                )
            except Exception:  # noqa: BLE001
                snap.freq_max = 2625
            try:
                snap.fan = pynvml.nvmlDeviceGetFanSpeed(handle)
            except Exception:  # noqa: BLE001 - 水冷/无风扇型号
                snap.fan = 0
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            snap.vram = int(mem.used / mem.total * 100) if mem.total else 0
        finally:
            pynvml.nvmlShutdown()
    except Exception:  # noqa: BLE001 - 无 N 卡/无驱动
        pass
    return snap


def read_cpu() -> CpuSnapshot:
    """读取一次 CPU/内存读数；Windows 上拿不到温度就留 None。"""
    snap = CpuSnapshot(name=_cpu_name())
    try:
        import psutil  # noqa: PLC0415

        snap.load = int(psutil.cpu_percent(interval=None))
        freq = psutil.cpu_freq()
        if freq:
            snap.freq = int(freq.current)
            snap.freq_max = int(freq.max or freq.current)
        snap.ram = int(psutil.virtual_memory().percent)
    except Exception:  # noqa: BLE001
        pass
    return snap


def _cpu_name() -> str:
    """设备端只显示 ASCII 短名，这里尽量压短（如 AMD RYZEN 7 9800X3D）。"""
    raw = platform.processor() or "CPU"
    upper = raw.upper()
    if "AMD" in upper:
        return "AMD RYZEN"
    if "INTEL" in upper:
        return "INTEL CORE"
    return upper[:16]
