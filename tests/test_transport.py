# SPDX-License-Identifier: MIT
"""传输层测试（不触碰真实硬件）。

用 ``FakeSerial`` 注入 ``serial_factory``，覆盖三件最容易出事的行为：
1. **dry-run 绝对不能打开端口**（用"一旦被调用就崩"的工厂来验证）；
2. 写入长度不完整必须报错，而不是静默成功；
3. 读超时不能把线程卡死（```read_for`` 必须在截止时间返回）。
"""

from __future__ import annotations

import time

import pytest

from vulcan_lcd.core.transport import (
    RAW_LOG_LIMIT,
    PortBusyError,
    SerialException,
    SerialSettings,
    Transport,
    TransportClosedError,
    TransportError,
)


class FakeSerial:
    """最小串口替身。

    ``late_rx`` 模拟"reset_input_buffer 之后才到达"的数据 —— 真实设备就是这样：
    打开端口时缓冲里可能有上电残留，必须先清掉才能把之后的字节当作应答。
    """

    def __init__(self, rx: bytes = b"", short_write: bool = False, late_rx: bytes = b"") -> None:
        self._rx = bytearray(rx)
        self.late_rx = late_rx
        self.written: list[bytes] = []
        self.closed = False
        self.flushed = 0
        self.short_write = short_write
        self.reset_calls = 0

    # pyserial 接口子集
    def write(self, data: bytes) -> int:
        self.written.append(bytes(data))
        return len(data) - 1 if self.short_write else len(data)

    def read(self, n: int) -> bytes:
        out = bytes(self._rx[:n])
        del self._rx[:n]
        return out

    def close(self) -> None:
        self.closed = True

    def flush(self) -> None:
        self.flushed += 1

    def reset_input_buffer(self) -> None:
        self.reset_calls += 1
        self._rx.clear()
        self._rx.extend(self.late_rx)


def make_transport(fake: FakeSerial, **kwargs: object) -> Transport:
    return Transport(
        "COM_TEST",
        serial_factory=lambda port, kw: fake,  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- #
# dry-run：最关键的安全边界
# --------------------------------------------------------------------------- #
def test_dry_run_never_touches_hardware() -> None:
    def exploding_factory(port: str, kwargs: dict[str, object]) -> object:
        raise AssertionError("dry-run 模式绝不能构造 Serial 对象")

    t = Transport("COM4", dry_run=True, serial_factory=exploding_factory)
    t.open()  # 不应抛异常，也不应调用工厂
    assert t.is_open is True
    assert t.write(b"\x5a\x9f\xa9") == 0
    t.close()


def test_dry_run_still_records_what_would_be_sent() -> None:
    t = Transport("COM4", dry_run=True, serial_factory=lambda p, k: FakeSerial())
    t.open()
    t.write(b"\x01\x02\x03")
    assert t.tx_log == [b"\x01\x02\x03"]
    assert t.bytes_tx == 3
    assert t.write_count == 1


def test_dry_run_read_returns_empty_without_error() -> None:
    t = make_transport(FakeSerial(rx=b"junk"), dry_run=True)
    t.open()
    assert t.read() == b""
    assert t.read_for(20) == b""


# --------------------------------------------------------------------------- #
# 真实写入路径（用替身）
# --------------------------------------------------------------------------- #
def test_write_sends_bytes_and_counts() -> None:
    fake = FakeSerial()
    with make_transport(fake) as t:
        assert t.write(b"\x5a\x9f\xa9") == 3
    assert fake.written == [b"\x5a\x9f\xa9"]
    assert fake.flushed == 1
    assert t.bytes_tx == 3


def test_write_empty_is_noop() -> None:
    fake = FakeSerial()
    with make_transport(fake) as t:
        assert t.write(b"") == 0
    assert fake.written == []
    assert t.write_count == 0


def test_write_before_open_raises() -> None:
    t = make_transport(FakeSerial())
    with pytest.raises(TransportClosedError, match="未打开"):
        t.write(b"\x01")


def test_incomplete_write_raises() -> None:
    fake = FakeSerial(short_write=True)
    with make_transport(fake) as t:
        with pytest.raises(TransportError, match="写入不完整"):
            t.write(b"\x01\x02\x03")


def test_open_failure_raises_port_busy() -> None:
    def busy_factory(port: str, kwargs: dict[str, object]) -> object:
        raise SerialException("Access is denied")

    t = Transport("COM4", serial_factory=busy_factory)
    with pytest.raises(PortBusyError, match="iGameCenter"):
        t.open()


def test_read_records_rx() -> None:
    fake = FakeSerial(rx=b"\xaa\xbb")
    with make_transport(fake) as t:
        assert t.read() == b"\xaa\xbb"
        assert t.rx_log == [b"\xaa\xbb"]
        assert t.bytes_rx == 2


def test_read_for_respects_deadline_and_accumulates() -> None:
    fake = FakeSerial(rx=b"0123456789")
    with make_transport(fake) as t:
        started = time.monotonic()
        data = t.read_for(40)
        elapsed = time.monotonic() - started
    assert data == b"0123456789"
    assert 0.03 <= elapsed < 0.5  # 不能提前返回，也不能卡死


def test_read_for_rejects_non_positive_duration() -> None:
    with make_transport(FakeSerial()) as t:
        with pytest.raises(ValueError, match="必须为正数"):
            t.read_for(0)


def test_context_manager_closes_port() -> None:
    fake = FakeSerial()
    t = make_transport(fake)
    with t:
        pass
    assert fake.closed is True
    assert t.is_open is False


def test_reset_input_buffer_is_forwarded() -> None:
    fake = FakeSerial(rx=b"stale")
    with make_transport(fake) as t:
        t.reset_input_buffer()
    assert fake.reset_calls == 1


# --------------------------------------------------------------------------- #
# 回调与日志截断
# --------------------------------------------------------------------------- #
def test_callbacks_receive_truncated_copies() -> None:
    seen_tx: list[bytes] = []
    seen_rx: list[bytes] = []
    big = bytes(RAW_LOG_LIMIT + 100)

    fake = FakeSerial(rx=big)
    with make_transport(fake, on_tx=seen_tx.append, on_rx=seen_rx.append) as t:
        t.write(big)
        t.read(RAW_LOG_LIMIT + 100)

    assert len(seen_tx) == 1 and len(seen_tx[0]) == RAW_LOG_LIMIT
    assert len(seen_rx) == 1 and len(seen_rx[0]) == RAW_LOG_LIMIT
    # 统计值必须是完整长度，不能是截断后的长度
    assert t.bytes_tx == RAW_LOG_LIMIT + 100
    assert t.bytes_rx == RAW_LOG_LIMIT + 100


# --------------------------------------------------------------------------- #
# 参数
# --------------------------------------------------------------------------- #
def test_settings_convert_ms_to_seconds() -> None:
    kwargs = SerialSettings(timeout_ms=50, write_timeout_ms=1000).to_kwargs()
    assert kwargs["timeout"] == 0.05
    assert kwargs["write_timeout"] == 1.0
    assert kwargs["baudrate"] == 115200
    assert kwargs["parity"] == "N"


def test_settings_describe_is_readable() -> None:
    assert SerialSettings().describe() == "115200 8N1 timeout=50ms"


def test_port_must_not_be_empty() -> None:
    with pytest.raises(ValueError, match="port 不能为空"):
        Transport("")
