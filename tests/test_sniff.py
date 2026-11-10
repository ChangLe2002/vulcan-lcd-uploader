# SPDX-License-Identifier: MIT
"""嗅探与十六进制格式化测试。

重点验证"只读"这件事本身：不带双开关时，任何发送路径都不可达。
"""

from __future__ import annotations

import pytest

from vulcan_lcd.core.port_scanner import (
    PortInfo,
    SniffResult,
    _parse_hex,
    format_results,
    scan_targets,
    sniff_port,
    sniff_ports,
)
from vulcan_lcd.core.transport import SerialException, Transport
from tests.test_transport import FakeSerial


def factory_with(fake: FakeSerial):
    """构造一个返回注入了 FakeSerial 的 Transport 的工厂。"""

    def _factory(port: str, settings: object, dry_run: bool) -> Transport:
        return Transport(
            port,
            serial_factory=lambda p, k: fake,
            dry_run=dry_run,
        )

    return _factory


# --------------------------------------------------------------------------- #
# 发送闸门：默认不可达
# --------------------------------------------------------------------------- #
def test_send_without_flag_is_rejected() -> None:
    with pytest.raises(ValueError, match="拒绝发送未验证字节"):
        sniff_port("COM4", 10, send_hex="5A9FA9")


def test_send_with_flag_and_factory_is_allowed() -> None:
    fake = FakeSerial(late_rx=b"\x11\x22")
    result = sniff_port(
        "COM4",
        30,
        send_hex="5A 9F A9",
        allow_unverified_tx=True,
        transport_factory=factory_with(fake),
    )
    assert fake.written == [b"\x5a\x9f\xa9"]
    assert result.tx == b"\x5a\x9f\xa9"
    assert result.rx == b"\x11\x22"
    assert result.opened is True


def test_empty_send_hex_is_rejected() -> None:
    with pytest.raises(ValueError, match="为空"):
        sniff_port("COM4", 10, send_hex="   ", allow_unverified_tx=True)


# --------------------------------------------------------------------------- #
# 被动监听
# --------------------------------------------------------------------------- #
def test_passive_sniff_never_writes() -> None:
    fake = FakeSerial(late_rx=b"\xde\xad")
    result = sniff_port("COM4", 25, transport_factory=factory_with(fake))
    assert fake.written == []  # 一个字节都不许写
    assert result.tx is None
    assert result.rx == b"\xde\xad"
    assert result.got_data is True


def test_passive_sniff_with_no_data() -> None:
    fake = FakeSerial()
    result = sniff_port("COM4", 20, transport_factory=factory_with(fake))
    assert result.opened is True
    assert result.got_data is False
    assert "无任何数据" in result.summary()


def test_dry_run_sniff_does_not_open() -> None:
    fake = FakeSerial(rx=b"\x01")
    result = sniff_port("COM4", 20, dry_run=True, transport_factory=factory_with(fake))
    assert result.dry_run is True
    assert result.rx == b""
    assert fake.reset_calls == 0  # dry-run 连 reset 都不应调用
    assert "dry-run" in result.summary()


def test_busy_port_is_reported_not_raised() -> None:
    def busy_factory(port: str, settings: object, dry_run: bool) -> Transport:
        def explode(p: str, k: dict[str, object]) -> object:
            raise SerialException("Access is denied")

        return Transport(port, serial_factory=explode, dry_run=dry_run)

    result = sniff_port("COM4", 10, transport_factory=busy_factory)
    assert result.opened is False
    assert result.error_code == "PORT_BUSY"
    assert "iGameCenter" in result.error
    assert result.got_data is False


def test_sniff_ports_runs_in_order_and_calls_back() -> None:
    seen: list[str] = []
    results = sniff_ports(
        ["COM1", "COM2"],
        10,
        on_result=lambda r: seen.append(r.port),
    )
    # 用真实串口时可能全部打开失败，但顺序与回调必须成立
    assert [r.port for r in results] == ["COM1", "COM2"]
    assert seen == ["COM1", "COM2"]


# --------------------------------------------------------------------------- #
# hex 解析
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("5A9FA9", b"\x5a\x9f\xa9"),
        ("5a 9f a9", b"\x5a\x9f\xa9"),
        ("5a:9f:a9", b"\x5a\x9f\xa9"),
        ("5a-9f-a9", b"\x5a\x9f\xa9"),
        ("0x5a0x9f0xa9", b"\x5a\x9f\xa9"),
    ],
)
def test_parse_hex_accepts_common_separators(text: str, expected: bytes) -> None:
    assert _parse_hex(text) == expected


def test_parse_hex_rejects_odd_length() -> None:
    with pytest.raises(ValueError, match="偶数"):
        _parse_hex("5A9")


def test_parse_hex_rejects_non_hex() -> None:
    with pytest.raises(ValueError):
        _parse_hex("ZZ")


# --------------------------------------------------------------------------- #
# 结果呈现
# --------------------------------------------------------------------------- #
def test_format_results_covers_all_states() -> None:
    text = format_results(
        [
            SniffResult(port="COM1", opened=False, error_code="PORT_BUSY", error="占用"),
            SniffResult(port="COM2", opened=True, dry_run=True),
            SniffResult(port="COM3", opened=True, duration_ms=100),
            SniffResult(port="COM4", opened=True, duration_ms=100, rx=b"\x5a\x9f"),
        ]
    )
    assert "失败" in text
    assert "dry-run" in text
    assert "无数据" in text
    assert "有数据" in text
    assert "=== 原始数据 ===" in text
    assert "5a 9f" in text


def test_format_results_without_data_omits_dump_section() -> None:
    text = format_results([SniffResult(port="COM1", opened=True, duration_ms=50)])
    assert "=== 原始数据 ===" not in text


def test_port_info_usb_detection() -> None:
    usb = PortInfo(device="COM4", description="USB 串行设备", vid=0x1A86, pid=0x7523)
    onboard = PortInfo(device="COM1", description="通信端口", hwid="ACPI\\PNP0501")
    assert usb.is_usb is True
    assert onboard.is_usb is False
    assert "USB 1A86:7523" in usb.label()


def test_scan_targets_covers_com1_to_com20() -> None:
    targets = scan_targets()
    assert len(targets) == 20
    assert targets[0] == "COM1"
    assert targets[-1] == "COM20"


def test_sniff_result_has_no_data_when_closed() -> None:
    r = SniffResult(port="COM9", opened=False, error="x")
    assert r.got_data is False
    assert "打开失败" in r.summary()
