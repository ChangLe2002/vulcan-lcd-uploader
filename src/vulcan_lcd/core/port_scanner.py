# SPDX-License-Identifier: MIT
"""串口枚举与**只读嗅探**。

这一模块解决一个现实问题：**握手字节尚未确认**（``settings.default.json`` 里
``handshake_tx_hex`` / ``handshake_rx_hex`` 都是 ``null``），所以现在不能做
"发握手 → 等应答 → 判定设备"的自动识别。

在字节被确认之前，这里只提供两条安全路径：

1. :func:`sniff_port` —— **纯被动监听**：打开端口，只读不写，把这段时间内收到的
   所有字节原样记录。零发送、零猜测。
2. :func:`sniff_port` 的 ``send_hex`` 参数 —— 需要**两个显式开关同时为真**
   （``send_hex`` 非空 **且** ``allow_unverified_tx=True``），否则直接拒绝。
   这是给"你抓到了握手包、想手动验证一次"的场景留的口子，默认不可达。

禁止在此模块里"顺手补一个看起来像握手"的字节序列 —— 那正是项目安全边界要防的事。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..util.hexfmt import hexdump, preview
from .transport import PortBusyError, SerialSettings, Transport, TransportError

try:  # pragma: no cover - 依赖缺失时降级
    from serial.tools import list_ports
except ImportError:  # pragma: no cover
    list_ports = None  # type: ignore[assignment]

__all__ = [
    "PortInfo",
    "SniffResult",
    "DEFAULT_SNIFF_MS",
    "list_serial_ports",
    "scan_targets",
    "sniff_port",
    "sniff_ports",
    "format_results",
]

DEFAULT_SNIFF_MS = 2000

# 被动监听时不知道设备会回多少，单端口最多保留这么多字节进内存/日志
MAX_SNIFF_RX = 64 * 1024


# --------------------------------------------------------------------------- #
# 端口枚举
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PortInfo:
    """一个已存在的串口及其系统描述。"""

    device: str
    description: str = ""
    hwid: str = ""
    manufacturer: str = ""
    vid: int | None = None
    pid: int | None = None

    @property
    def is_usb(self) -> bool:
        """USB 转串口（智屏几乎必然走这条路，主板 COM1 不是）。"""
        return self.vid is not None or "USB" in self.hwid.upper()

    def label(self) -> str:
        parts = [self.device]
        if self.description:
            parts.append(f"({self.description})")
        if self.vid is not None and self.pid is not None:
            parts.append(f"[USB {self.vid:04X}:{self.pid:04X}]")
        elif self.hwid:
            parts.append(f"[{self.hwid}]")
        return " ".join(parts)


def list_serial_ports() -> list[PortInfo]:
    """枚举当前系统上真实存在的串口（按 COM 号排序）。

    注意：Windows 上 COM1 常常是主板自带的 16550 端口，与显卡无关。
    不要对"扫到 COM1"感到兴奋。
    """
    if list_ports is None:
        raise TransportError("pyserial 未安装，无法枚举串口")
    found: list[PortInfo] = []
    for p in list_ports.comports():
        found.append(
            PortInfo(
                device=p.device,
                description=p.description or "",
                hwid=p.hwid or "",
                manufacturer=getattr(p, "manufacturer", "") or "",
                vid=getattr(p, "vid", None),
                pid=getattr(p, "pid", None),
            )
        )
    return sorted(found, key=lambda x: _com_sort_key(x.device))


def _com_sort_key(device: str) -> tuple[int, str]:
    """COM2 排在 COM10 前面。"""
    digits = "".join(ch for ch in device if ch.isdigit())
    return (int(digits) if digits else 999, device)


def scan_targets(start: int = 1, end: int = 20) -> list[str]:
    """生成 COM1..COM20 的候选列表（自动发现机制的扫描范围）。"""
    return [f"COM{i}" for i in range(start, end + 1)]


# --------------------------------------------------------------------------- #
# 嗅探结果
# --------------------------------------------------------------------------- #
@dataclass
class SniffResult:
    """单端口嗅探结果。"""

    port: str
    duration_ms: int = 0
    opened: bool = False
    dry_run: bool = False
    rx: bytes = b""
    tx: bytes | None = None
    error: str = ""
    error_code: str = ""

    @property
    def got_data(self) -> bool:
        return len(self.rx) > 0

    def summary(self) -> str:
        if not self.opened:
            return f"{self.port}: 打开失败 [{self.error_code or 'ERROR'}] {self.error}"
        if self.dry_run:
            return f"{self.port}: dry-run，未触碰硬件"
        if not self.got_data:
            return f"{self.port}: 已打开，{self.duration_ms}ms 内无任何数据"
        return f"{self.port}: 收到 {len(self.rx)} 字节 → {preview(self.rx)}"


# --------------------------------------------------------------------------- #
# 嗅探
# --------------------------------------------------------------------------- #
def _parse_hex(text: str) -> bytes:
    cleaned = text.replace(" ", "").replace(":", "").replace("-", "").replace("0x", "")
    if len(cleaned) % 2 != 0:
        raise ValueError(f"十六进制长度必须为偶数，收到 {len(cleaned)} 个字符: {text!r}")
    return bytes.fromhex(cleaned)


def sniff_port(
    port: str,
    duration_ms: int = DEFAULT_SNIFF_MS,
    *,
    settings: SerialSettings | None = None,
    send_hex: str | None = None,
    allow_unverified_tx: bool = False,
    dry_run: bool = False,
    transport_factory: object = None,
) -> SniffResult:
    """打开端口，监听 ``duration_ms``，返回收到的原始字节。

    Args:
        port: 目标串口，如 ``"COM4"``。
        duration_ms: 监听窗口。
        settings: 串口参数，默认 115200 8N1 / 50ms。
        send_hex: 可选，先发送这段十六进制再监听。
            **必须同时置 ``allow_unverified_tx=True``**，否则抛 :class:`ValueError`。
        allow_unverified_tx: 未验证发送的显式确认开关。
        dry_run: True 时完全不打开端口。

    Raises:
        ValueError: 试图在未确认的情况下发送未验证字节，或 hex 串非法。
    """
    payload: bytes | None = None
    if send_hex is not None:
        if not allow_unverified_tx:
            raise ValueError(
                "拒绝发送未验证字节：send_hex 必须与 allow_unverified_tx=True 同时使用。"
                "握手/数据帧格式未确认前，默认只读不写。"
            )
        payload = _parse_hex(send_hex)
        if not payload:
            raise ValueError("send_hex 解析后为空")

    result = SniffResult(port=port, duration_ms=duration_ms, dry_run=dry_run, tx=payload)

    if transport_factory is not None:
        transport = transport_factory(port, settings, dry_run)  # type: ignore[operator]
    else:
        transport = Transport(port, settings, dry_run=dry_run)
    try:
        transport.open()
        result.opened = True
        transport.reset_input_buffer()
        if payload:
            transport.write(payload)
        result.rx = transport.read_for(duration_ms)[:MAX_SNIFF_RX]
    except PortBusyError as exc:
        result.error_code = exc.error_code
        result.error = str(exc)
    except TransportError as exc:
        result.error_code = exc.error_code
        result.error = str(exc)
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 - 嗅探失败不能把 CLI/UI 打崩
        result.error_code = "UNKNOWN"
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        transport.close()

    return result


def sniff_ports(
    ports: list[str],
    duration_ms: int = DEFAULT_SNIFF_MS,
    *,
    settings: SerialSettings | None = None,
    dry_run: bool = False,
    on_result: object = None,
) -> list[SniffResult]:
    """逐个嗅探多个端口（串行执行，避免多端口同时打开造成干扰）。"""
    results: list[SniffResult] = []
    for port in ports:
        result = sniff_port(port, duration_ms, settings=settings, dry_run=dry_run)
        results.append(result)
        if callable(on_result):
            on_result(result)  # type: ignore[operator]
    return results


# --------------------------------------------------------------------------- #
# 呈现
# --------------------------------------------------------------------------- #
def format_results(results: list[SniffResult]) -> str:
    """把嗅探结果渲染成可贴进 Issue 的文本（不含机器标识，仅端口与字节）。"""
    lines: list[str] = []
    lines.append(f"{'端口':<8}{'状态':<10}{'接收':<10}说明")
    lines.append("-" * 72)
    for r in results:
        if not r.opened:
            status, rx, note = "失败", "-", f"[{r.error_code}] {r.error}"
        elif r.dry_run:
            status, rx, note = "dry-run", "-", "未触碰硬件"
        elif r.got_data:
            status, rx, note = "有数据", f"{len(r.rx)} B", preview(r.rx)
        else:
            status, rx, note = "无数据", "0 B", "该时间窗内设备未主动发送"
        lines.append(f"{r.port:<8}{status:<10}{rx:<10}{note}")

    with_data = [r for r in results if r.got_data]
    if with_data:
        lines.append("")
        lines.append("=== 原始数据 ===")
        for r in with_data:
            lines.append(f"--- {r.port} ({len(r.rx)} B) ---")
            if r.tx:
                lines.append(f"[tx] {preview(r.tx)}")
            lines.append(hexdump(r.rx))
    return "\n".join(lines)

# --------------------------------------------------------------------------- #
# 智屏串口自动识别
# --------------------------------------------------------------------------- #
LCD_VID = "1B3F"
LCD_PID = "0123"


def find_lcd_port() -> str | None:
    """返回智屏所在串口（按 USB VID:PID 匹配），找不到返回 None。

    不依赖固定 COM 号：换 USB 针脚后端口号会变（实测从 COM4 变 COM5），
    靠 VID/PID 识别才稳。
    """
    try:
        from serial.tools import list_ports  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - 缺少 pyserial 时静默返回
        return None

    target = f"{LCD_VID}:{LCD_PID}"
    for port in list_ports.comports():
        hwid = (getattr(port, "hwid", "") or "").upper()
        if target in hwid or f"VID_{LCD_VID}" in hwid:
            return port.device
    return None
