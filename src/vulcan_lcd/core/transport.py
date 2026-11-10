# SPDX-License-Identifier: MIT
"""串口传输层。

这一层是**唯一**允许调用 ``serial.Serial`` 的地方。所有上层功能（GIF 上传、监控、
播放列表）都只能经过 :class:`Transport`，这样"生产模式闸门"和"dry-run 拦截"
只需要在单点实现，不可能被某个模块绕过。

安全默认值：
* ``dry_run=False`` 时不代表会自动发包 —— 每次写入都必须显式调用 :meth:`write`；
* :meth:`open` 在 ``dry_run=True`` 下**完全不触碰硬件**，只做记录；
* 所有写入都会先落进 ``tx_log`` 再决定是否真的写串口，所以 dry-run 与真实发送
  的日志格式完全一致，便于比对。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Sequence

from ..constants import (
    SERIAL_BAUDRATE,
    SERIAL_BYTESIZE,
    SERIAL_PARITY,
    SERIAL_STOPBITS,
    SERIAL_TIMEOUT_MS,
)

try:  # pragma: no cover - 依赖缺失时走下面的降级分支
    import serial
    from serial import SerialException
except ImportError:  # pragma: no cover
    serial = None  # type: ignore[assignment]

    class SerialException(Exception):  # type: ignore[no-redef]
        """pyserial 缺失时的占位异常，避免模块级 import 失败。"""


__all__ = [
    "TransportError",
    "PortBusyError",
    "TransportClosedError",
    "SerialSettings",
    "Transport",
    "RAW_LOG_LIMIT",
]

# 日志/回调里单条记录的保留上限，防止大帧把内存和日志撑爆
RAW_LOG_LIMIT = 256


# --------------------------------------------------------------------------- #
# 异常
# --------------------------------------------------------------------------- #
class TransportError(Exception):
    """传输层异常基类。"""

    error_code: str = "TRANSPORT_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PortBusyError(TransportError):
    """串口打不开：被占用、无权限、或设备已拔出。"""

    error_code = "PORT_BUSY"


class TransportClosedError(TransportError):
    """在未打开的传输层上读写。"""

    error_code = "TRANSPORT_CLOSED"


# --------------------------------------------------------------------------- #
# 串口参数
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SerialSettings:
    """串口参数。默认值即 115200 8N1 / 50ms（已确认）。"""

    baudrate: int = SERIAL_BAUDRATE
    bytesize: int = SERIAL_BYTESIZE
    parity: str = SERIAL_PARITY
    stopbits: float = SERIAL_STOPBITS
    timeout_ms: int = SERIAL_TIMEOUT_MS
    #: 16 KB 数据块在 115200 下理论需 ~1.4s，设备偶尔更慢；1s 会直接 Write timeout。
    write_timeout_ms: int = 5000

    def to_kwargs(self) -> dict[str, object]:
        """转成 ``serial.Serial`` 的关键字参数。

        注意：pyserial 的 timeout 单位是**秒**，这里做毫秒→秒转换，
        写错会表现为"读超时立刻返回"或"线程卡死"。
        """
        return {
            "baudrate": self.baudrate,
            "bytesize": self.bytesize,
            "parity": self.parity,
            "stopbits": self.stopbits,
            "timeout": self.timeout_ms / 1000.0,
            "write_timeout": self.write_timeout_ms / 1000.0,
        }

    def describe(self) -> str:
        return (
            f"{self.baudrate} {self.bytesize}{self.parity}{int(self.stopbits)}"
            f" timeout={self.timeout_ms}ms"
        )


# --------------------------------------------------------------------------- #
# 传输层
# --------------------------------------------------------------------------- #
class Transport:
    """串口收发封装（上下文管理器）。

    Args:
        port: 串口名，如 ``"COM4"``。
        settings: 串口参数。
        dry_run: True 时**不打开端口、不写任何字节**，只记录将要发送的内容。
        on_tx / on_rx: 收发回调（用于调试面板实时刷新）。收到的是截断后的副本。
        serial_factory: 测试注入点，签名 ``(port, kwargs) -> 串口对象``。
            生产代码不要传这个参数。
    """

    def __init__(
        self,
        port: str,
        settings: SerialSettings | None = None,
        *,
        dry_run: bool = False,
        on_tx: Callable[[bytes], None] | None = None,
        on_rx: Callable[[bytes], None] | None = None,
        serial_factory: Callable[[str, dict[str, object]], object] | None = None,
    ) -> None:
        if not port:
            raise ValueError("port 不能为空")
        self.port = port
        self.settings = settings or SerialSettings()
        self.dry_run = dry_run
        self._on_tx = on_tx
        self._on_rx = on_rx
        self._factory = serial_factory or self._default_factory
        self._ser: object | None = None

        # 统计与回放日志（截断副本）
        self.bytes_tx = 0
        self.bytes_rx = 0
        self.write_count = 0
        self.read_count = 0
        self.tx_log: list[bytes] = []
        self.rx_log: list[bytes] = []

    # -- 工厂 ------------------------------------------------------------- #
    @staticmethod
    def _default_factory(port: str, kwargs: dict[str, object]) -> object:
        if serial is None:
            raise TransportError(
                "pyserial 未安装。请在项目虚拟环境中执行 pip install -r requirements.txt"
            )
        return serial.Serial(port=port, **kwargs)  # type: ignore[union-attr]

    # -- 生命周期 --------------------------------------------------------- #
    def open(self) -> "Transport":
        """打开串口。dry-run 下不触碰硬件。"""
        if self.is_open:
            return self

        if self.dry_run:
            # 关键：dry-run 不构造 Serial 对象，连端口都不打开
            return self

        try:
            self._ser = self._factory(self.port, self.settings.to_kwargs())
        except SerialException as exc:
            raise PortBusyError(
                f"无法打开 {self.port}：{exc}。"
                "常见原因：iGameCenter 服务正在占用、端口号不存在、或设备已拔出。"
            ) from exc
        except OSError as exc:
            raise PortBusyError(f"打开 {self.port} 失败（系统错误）：{exc}") from exc
        return self

    def close(self) -> None:
        ser, self._ser = self._ser, None
        if ser is None:
            return
        try:
            ser.close()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - 关闭失败不应影响主流程/退出恢复
            pass

    @property
    def is_open(self) -> bool:
        """dry-run 视为"逻辑上已打开"，这样上层无需分支判断。"""
        return self.dry_run or self._ser is not None

    def __enter__(self) -> "Transport":
        return self.open()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    # -- 记录 ------------------------------------------------------------- #
    def _record_tx(self, data: bytes) -> None:
        self.tx_log.append(data[:RAW_LOG_LIMIT])
        self.bytes_tx += len(data)
        self.write_count += 1
        if self._on_tx is not None:
            self._on_tx(data[:RAW_LOG_LIMIT])

    def _record_rx(self, data: bytes) -> None:
        if not data:
            return
        self.rx_log.append(data[:RAW_LOG_LIMIT])
        self.bytes_rx += len(data)
        self.read_count += 1
        if self._on_rx is not None:
            self._on_rx(data[:RAW_LOG_LIMIT])

    # -- 写 --------------------------------------------------------------- #
    def write(self, data: bytes | bytearray | memoryview, *, flush: bool = True) -> int:
        """写入字节，返回实际写入长度（dry-run 恒为 0）。

        dry-run 下仍会记录 ``tx_log``，因此可以离线检查"到底会发什么"。
        """
        raw = bytes(data)
        if not raw:
            return 0

        self._record_tx(raw)

        if self.dry_run:
            return 0

        if self._ser is None:
            raise TransportClosedError(f"{self.port} 未打开，无法写入")

        try:
            written = self._ser.write(raw)  # type: ignore[attr-defined]
        except SerialException as exc:
            raise TransportError(f"写入 {self.port} 失败：{exc}") from exc

        if written != len(raw):
            raise TransportError(
                f"写入不完整：期望 {len(raw)} 字节，实际 {written} 字节（端口可能超时或断开）"
            )
        if flush:
            try:
                self._ser.flush()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - flush 失败不改变"已写入"的事实
                pass
        return written

    # -- 读 --------------------------------------------------------------- #
    def flush(self) -> None:
        """等待发送缓冲清空。分批写之后需要它来确认数据真的出去了。"""
        if self.dry_run or self._ser is None:
            return
        try:
            self._ser.flush()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - flush 失败不改变"已写入"的事实
            pass

    def read(self, max_bytes: int = 4096) -> bytes:
        """读一次，最多 ``max_bytes``；无数据时返回 ``b""``（受 timeout 约束）。"""
        if self.dry_run:
            return b""
        if self._ser is None:
            raise TransportClosedError(f"{self.port} 未打开，无法读取")
        try:
            chunk = self._ser.read(max_bytes)  # type: ignore[attr-defined]
        except SerialException as exc:
            raise TransportError(f"读取 {self.port} 失败：{exc}") from exc
        data = bytes(chunk or b"")
        self._record_rx(data)
        return data

    def read_for(self, duration_ms: int, *, chunk_size: int = 4096, idle_sleep_ms: float = 5.0) -> bytes:
        """在 ``duration_ms`` 时间窗内持续读取，返回累计字节。

        用于握手 / 嗅探：不知道设备会回多少、什么时候回，只能"听一段时间"。
        """
        if duration_ms <= 0:
            raise ValueError(f"duration_ms 必须为正数，收到 {duration_ms}")
        deadline = time.monotonic() + duration_ms / 1000.0
        collected = bytearray()
        while time.monotonic() < deadline:
            chunk = self.read(chunk_size)
            if chunk:
                collected.extend(chunk)
            else:
                time.sleep(idle_sleep_ms / 1000.0)
        return bytes(collected)

    def reset_input_buffer(self) -> None:
        """清空接收缓冲：发探测包之前调用，避免把旧数据当成应答。"""
        if self.dry_run or self._ser is None:
            return
        try:
            self._ser.reset_input_buffer()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass


def open_transport(
    port: str,
    settings: SerialSettings | None = None,
    **kwargs: object,
) -> Transport:
    """便捷函数：创建并打开（``with`` 语义不适用时的替代写法）。"""
    transport = Transport(port, settings, **kwargs)  # type: ignore[arg-type]
    return transport.open()
