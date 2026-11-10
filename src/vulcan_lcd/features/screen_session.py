# SPDX-License-Identifier: MIT
"""一段完整的"接管屏幕并显示自己的内容"会话。

职责边界：
* **不碰 Qt**——纯 Python，可在测试里用假设备驱动；
* 负责顺序：停服务 → 开串口 → 查清单选槽位 → 上传 → 循环发显示指令 → 收尾恢复；
* 显示指令必须**周期性重发**（实测官方每秒一次），停发设备就回默认动画。

UI 侧只需在后台线程调用 :func:`run_screen_session`，并通过回调更新进度。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from ..core.port_scanner import find_lcd_port
from ..core.transport import Transport, TransportError
from ..system.service_control import ServiceController, ServiceError
from .cache_clean import clear_beyond_first, clear_uploaded_files
from .gif_upload import (
    SAFE_SLOT_BASE,
    UploadError,
    UploadResult,
    build_display_frame,
    next_slot_name,
    query_file_list,
    upload_pak,
)

__all__ = ["SessionReport", "run_screen_session", "DEFAULT_DISPLAY_INTERVAL_S"]

#: 显示指令重发间隔（秒）。实测官方为 1 秒。
DEFAULT_DISPLAY_INTERVAL_S = 1.0

#: 停服务后尝试打开串口的次数与间隔。设备偶发卡死时，多试几次往往能恢复；
#: 连续失败说明设备需要硬复位（拔插 USB 或重启）。
PORT_OPEN_ATTEMPTS = 3
PORT_OPEN_GAP_S = 1.5


@dataclass(frozen=True)
class SessionReport:
    """会话结果。"""

    uploaded: bool = False
    name: str = ""
    chunks: int = 0
    display_seconds: float = 0.0
    error: str | None = None
    error_code: str = ""

    def describe(self) -> str:
        if self.error:
            return f"失败：{self.error}"
        return (
            f"{self.name} 已显示 · {self.chunks} 块 · "
            f"持续 {self.display_seconds:.0f}s"
        )


def run_screen_session(
    pak: bytes,
    *,
    controller: ServiceController,
    transport: Transport,
    stop_event: threading.Event,
    name: str | None = None,
    display_interval_s: float = DEFAULT_DISPLAY_INTERVAL_S,
    on_progress: Callable[[int, int], None] | None = None,
    on_uploaded: Callable[[str], None] | None = None,
    ack_timeout_ms: int | None = None,
    block_gap_ms: int = 0,
    ledger: object | None = None,
    on_state: object | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> SessionReport:
    """接管屏幕、上传 pak 并持续显示，直到 ``stop_event`` 被置位。

    Args:
        pak: 已编码好的 pak 字节。
        controller: 官方服务控制器（负责让出/收回串口）。
        transport: :class:`~vulcan_lcd.core.transport.Transport`。
        stop_event: 置位后结束显示循环并恢复官方服务。
        name: 目标文件名；``None`` 时按设备现有清单自动取下一个槽位。
        display_interval_s: 显示指令重发间隔。
        on_progress: ``(已发送块, 总块数)``。
        on_uploaded: 上传完成时回调，参数是实际使用的文件名。

    Returns:
        :class:`SessionReport`。失败时 ``error`` 非空，不抛异常——
        保证调用方（UI 线程）总能拿到结果并恢复服务。
    """
    started = time.monotonic()
    display_seconds = 0.0
    took_over = False

    try:
        controller.takeover()
        took_over = True

        last_error: Exception | None = None
        for attempt in range(1, PORT_OPEN_ATTEMPTS + 1):
            try:
                transport.open()
                last_error = None
                break
            except TransportError as exc:
                last_error = exc
                if attempt == PORT_OPEN_ATTEMPTS:
                    break
                sleeper(PORT_OPEN_GAP_S)
        if last_error is not None:
            raise TransportError(
                f"{getattr(last_error, 'message', last_error)}"
                f"（已重试 {PORT_OPEN_ATTEMPTS} 次）——设备可能需要拔插 USB 或重启",
            )

        # 端口没指定（或配置里写的端口已不存在）时，按 VID:PID 自动识别
        if not getattr(transport, "port", ""):
            detected = find_lcd_port()
            if detected:
                transport = Transport(detected, transport.settings)  # type: ignore[attr-defined]

        # 记录上传前的清单：兜底校验只在"上传前不存在该文件"时采信，
        # 避免同名同大小的旧文件造成误判（审查意见 3）。
        before = query_file_list(transport)
        # 清单查询失败（空）时从 img20 起，避免覆盖用户原有素材
        target = name or next_slot_name(
            before, base=(1 if before else SAFE_SLOT_BASE)
        )
        existed_before = {entry.name for entry in before}
        try:
            result = upload_pak(
                transport,
                pak,
                name=target,
                on_progress=on_progress,
                display_name=target,
                display_seconds=0.0,
                block_gap_ms=block_gap_ms,
                **({} if ack_timeout_ms is None else {"ack_timeout_ms": ack_timeout_ms}),
            )
        except UploadError as exc:
            # 末块 ACK 丢失时数据往往已经写进去了：查清单确认，能确认就继续显示。
            if exc.error_code != "ACK_NOT_RECEIVED":
                raise
            # 设备可能还在写盘：等一会儿再查，最多查 3 次
            ok = False
            for _ in range(3):
                sleeper(2.0)
                entries = query_file_list(transport)
                if any(entry.name == target and entry.size == len(pak) for entry in entries):
                    ok = True
                    break
            if not ok:
                raise
            if target in existed_before:
                # 上传前就存在同名文件：无法确认是这次写入的，保守判失败
                raise UploadError(
                    f"{target} 上传前已存在，且末块 ACK 丢失，无法确认写入结果",
                    error_code="ACK_NOT_RECEIVED",
                )
            result = UploadResult(
                chunks=(len(pak) + 16383) // 16384,
                retries=0,
                duration_ms=0.0,
                name=target,
                size=len(pak),
            )
        if on_state is not None:
            try:
                on_state(transport)  # type: ignore[operator]
            except Exception:  # noqa: BLE001 - 状态读取失败不影响主流程
                pass
        if ledger is not None:
            try:
                ledger.add(target)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - 记账失败不影响显示
                pass
        if on_uploaded is not None:
            on_uploaded(target)

        frame = build_display_frame(target)
        while not stop_event.is_set():
            sleeper(display_interval_s)
            if stop_event.is_set():
                break
            transport.write(frame)
            transport.flush()
            display_seconds = time.monotonic() - started

        return SessionReport(
            uploaded=True,
            name=target,
            chunks=result.chunks,
            display_seconds=display_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - 会话层承诺不向 UI 抛异常
        return SessionReport(
            uploaded=False,
            name=name or "",
            error=getattr(exc, "message", None) or str(exc),
            error_code=getattr(exc, "error_code", "SESSION_FAILED"),
            display_seconds=display_seconds,
        )
    finally:
        try:
            transport.close()
        except Exception:  # noqa: BLE001 - 关闭失败不影响恢复服务
            pass
        if took_over:
            try:
                controller.release()
            except ServiceError:
                pass

def run_cache_clean(
    *,
    controller: ServiceController,
    transport: Transport,
    ledger: object,
    deep: bool = False,
    on_progress: Callable[[str], None] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> "CleanReport":
    """接管设备并清理本工具上传过的文件。

    只删除台账里记录过的名字，绝不碰用户原有素材。
    """
    from .cache_clean import CleanReport

    took_over = False
    try:
        controller.takeover()
        took_over = True

        last_error: Exception | None = None
        for attempt in range(1, PORT_OPEN_ATTEMPTS + 1):
            try:
                transport.open()
                last_error = None
                break
            except TransportError as exc:
                last_error = exc
                if attempt == PORT_OPEN_ATTEMPTS:
                    break
                sleeper(PORT_OPEN_GAP_S)
        if last_error is not None:
            return CleanReport(error=f"打不开串口：{getattr(last_error, 'message', last_error)}")

        names = []
        try:
            names = ledger.load()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            names = []

        if deep:
            report = clear_beyond_first(transport, sleeper=sleeper)
        else:
            report = clear_uploaded_files(transport, names, sleeper=sleeper)
        for name in report.deleted:
            try:
                ledger.remove(name)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass
            if on_progress is not None:
                on_progress(name)
        return report
    except Exception as exc:  # noqa: BLE001
        return CleanReport(error=str(exc))
    finally:
        try:
            transport.close()
        except Exception:  # noqa: BLE001
            pass
        if took_over:
            try:
                controller.release()
            except ServiceError:
                pass
