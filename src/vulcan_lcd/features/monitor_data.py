# SPDX-License-Identifier: MIT
"""设备端监控数据帧（设备自己渲染 CPU/GPU 数值，宿主不上传图片）。

协议来自反编译 `LCD5ACore.cs`（枚举 + `CreateCPU1Data/CreateCPU5Data/
CreateGPU1Data/CreateGPU3Data/CraeteTimeData`），不是猜测：

* 每条数据 4 字节：``[类型][高字节][低字节][百分比]``，
  数值 = 高字节*256 + 低字节；
* ``CPU1``  = 单条 CPU 指标；``CPU5`` = 5 条（Load/Temp/Freq/Volt/Ram）；
* ``GPU1``  = 单条 GPU 指标（附时间）；``GPU3`` = 3 条；
* 每帧 body 开头是 ``[设备型号][语言]``（CPU 帧的型号是 Intel/AMD，
  GPU 帧的型号是 Vulcan/Kudan），末尾是 ASCII 名字 + ``\\0``。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..core.protocol import build_frame

__all__ = [
    "GpuSnapshot",
    "CpuSnapshot",
    "CMD_CPU1",
    "CMD_CPU5",
    "CMD_GPU1",
    "CMD_GPU3",
    "CMD_TIME",
    "build_cpu1",
    "build_cpu5",
    "build_gpu1",
    "build_gpu3",
    "build_time",
]

CMD_CPU1 = 4590
CMD_CPU5 = 4845
CMD_GPU1 = 8925
CMD_GPU3 = 9180
CMD_TIME = 56610

#: CPU 类型（LCD5ACPU）
CPU_INTEL = 0
CPU_AMD = 1
#: GPU 型号（LCD5AGPU）
GPU_VULCAN = 0
GPU_KUDAN = 1
#: 语言
LANG_EN = 0
LANG_CH = 1

#: CPU 指标顺序（LCD5ACPUType）
CPU_LOAD, CPU_TEMP, CPU_FREQ, CPU_VOLT, CPU_RAM = 0, 1, 2, 3, 4
#: GPU 指标（LCD5AGPUType）
GPU_LOAD, GPU_TEMP, GPU_FREQ, GPU_FAN, GPU_VOLT, GPU_VRAM = 0, 1, 2, 3, 4, 5


@dataclass
class GpuSnapshot:
    """一次 GPU 读数。``None`` 表示该项不可用（按 0 发送）。"""

    name: str = "GEFORCE RTX 5070"
    load: int | None = None          # %
    temp: float | None = None        # °C
    freq: int | None = None          # MHz
    freq_max: int | None = None      # MHz
    fan: int | None = None           # %
    vram: int | None = None          # %
    volt: int | None = None          # mV


@dataclass
class CpuSnapshot:
    name: str = "CPU"
    load: int | None = None
    temp: float | None = None
    freq: int | None = None
    freq_max: int | None = None
    ram: int | None = None
    volt: int | None = None
    vendor_amd: bool = False


def _metric(kind: int, value: int, percent: int) -> bytes:
    value = max(0, min(0xFFFF, int(value)))
    return bytes([kind & 0xFF, (value >> 8) & 0xFF, value & 0xFF, max(0, min(100, percent))])


def _name_bytes(name: str) -> bytes:
    return name.upper().encode("ascii", errors="replace") + b"\x00"


def _pct(value: int | None, maximum: int | None) -> int:
    if not value or not maximum:
        return 0
    return max(0, min(100, int(round(value / maximum * 100))))


def build_time(moment: time.struct_time | None = None) -> bytes:
    """时间帧 body：年(2) 月 日 周 时 分 秒 + 语言 + 名字 + 类型。"""
    now = moment or time.localtime()
    body = bytes(
        [
            (now.tm_year >> 8) & 0xFF,
            now.tm_year & 0xFF,
            now.tm_mon,
            now.tm_mday,
            (now.tm_wday + 1) % 7,   # .NET DayOfWeek：周日=0
            now.tm_hour,
            now.tm_min,
            now.tm_sec,
            LANG_CH,
        ]
    )
    return build_frame(CMD_TIME.to_bytes(2, "big") + body + _name_bytes("GEFORCE RTX 5070") + b"\x00")


def build_cpu1(cpu: CpuSnapshot, kind: int = CPU_LOAD, *, lang: int = LANG_CH) -> bytes:
    """CPU 单指标帧（设备只显示这一个指标，不会带出温度/电压等空槽）。"""
    values = {
        CPU_LOAD: (cpu.load or 0, cpu.load or 0),
        CPU_TEMP: (int(cpu.temp or 0), int(cpu.temp or 0)),
        CPU_FREQ: (cpu.freq or 0, _pct(cpu.freq, cpu.freq_max)),
        CPU_VOLT: (cpu.volt or 0, _pct(cpu.volt, 1500)),
        CPU_RAM: (cpu.ram or 0, cpu.ram or 0),
    }
    value, percent = values.get(kind, (0, 0))
    body = bytearray([CPU_AMD if cpu.vendor_amd else CPU_INTEL, lang])
    body += _metric(kind, value, percent)
    body += _name_bytes(cpu.name)
    return build_frame(CMD_CPU1.to_bytes(2, "big") + bytes(body))


def build_gpu1(
    gpu: GpuSnapshot,
    kind: int = GPU_LOAD,
    *,
    moment: time.struct_time | None = None,
    lang: int = LANG_CH,
) -> bytes:
    """GPU 单指标帧（附时间，设备只显示这一个指标）。"""
    now = moment or time.localtime()
    values = {
        GPU_LOAD: (gpu.load or 0, gpu.load or 0),
        GPU_TEMP: (int(round((gpu.temp or 0) * 10)), int(gpu.temp or 0)),
        GPU_FREQ: (gpu.freq or 0, _pct(gpu.freq, gpu.freq_max)),
        GPU_FAN: (gpu.fan or 0, gpu.fan or 0),
        GPU_VOLT: (gpu.volt or 0, _pct(gpu.volt, 1200)),
        GPU_VRAM: (gpu.vram or 0, gpu.vram or 0),
    }
    value, percent = values.get(kind, (0, 0))
    body = bytearray([GPU_VULCAN, lang])
    body += _metric(kind, value, percent)
    body += bytes(
        [
            (now.tm_year >> 8) & 0xFF, now.tm_year & 0xFF,
            now.tm_mon, now.tm_mday, (now.tm_wday + 1) % 7,
            now.tm_hour, now.tm_min, now.tm_sec,
        ]
    )
    body += _name_bytes(gpu.name)
    return build_frame(CMD_GPU1.to_bytes(2, "big") + bytes(body))


def build_cpu5(cpu: CpuSnapshot, *, lang: int = LANG_CH) -> bytes:
    """CPU 五项指标（Load/Temp/Freq/Volt/Ram）。"""
    body = bytearray([CPU_AMD if cpu.vendor_amd else CPU_INTEL, lang])
    body += _metric(CPU_LOAD, cpu.load or 0, cpu.load or 0)
    body += _metric(CPU_TEMP, int(cpu.temp or 0), int(cpu.temp or 0))
    body += _metric(
        CPU_FREQ, cpu.freq or 0, _pct(cpu.freq, cpu.freq_max)
    )
    body += _metric(CPU_VOLT, cpu.volt or 0, _pct(cpu.volt, 1500))
    body += _metric(CPU_RAM, cpu.ram or 0, cpu.ram or 0)
    body += _name_bytes(cpu.name)
    return build_frame(CMD_CPU5.to_bytes(2, "big") + bytes(body))


def build_gpu3(gpu: GpuSnapshot, *, part: int = 1, lang: int = LANG_CH) -> bytes:
    """GPU 三项指标：part=1 → Load/Temp/Freq；part=2 → Fan/Volt/VRam。"""
    body = bytearray([GPU_VULCAN, lang])
    if part == 1:
        body += _metric(GPU_LOAD, gpu.load or 0, gpu.load or 0)
        # GPU 温度：数值是「摄氏度 × 10」
        body += _metric(GPU_TEMP, int(round((gpu.temp or 0) * 10)), int(gpu.temp or 0))
        body += _metric(GPU_FREQ, gpu.freq or 0, _pct(gpu.freq, gpu.freq_max))
    else:
        body += _metric(GPU_FAN, gpu.fan or 0, gpu.fan or 0)
        body += _metric(GPU_VOLT, gpu.volt or 0, _pct(gpu.volt, 1200))
        body += _metric(GPU_VRAM, gpu.vram or 0, gpu.vram or 0)
    body += _name_bytes(gpu.name)
    return build_frame(CMD_GPU3.to_bytes(2, "big") + bytes(body))
