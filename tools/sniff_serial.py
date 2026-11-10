# SPDX-License-Identifier: MIT
"""串口只读嗅探 CLI —— 用于在确认握手字节之前，先看清"设备到底会不会说话"。

用法::

    # 列出所有串口（不打开任何端口）
    python tools/sniff_serial.py --list

    # 被动监听全部串口，每个端口听 2 秒（默认，零发送）
    python tools/sniff_serial.py

    # 只监听某一个端口，听 5 秒
    python tools/sniff_serial.py --port COM4 --duration 5000

    # 空跑：不触碰硬件，只看会执行什么
    python tools/sniff_serial.py --port COM4 --dry-run

    # 只有在你自己抓到并确认了握手字节时才这么用（双开关，缺一不可）
    python tools/sniff_serial.py --port COM4 --send-hex "5A 9F A9 ..." \
        --allow-unverified-tx --yes

安全说明：默认路径**不向串口写任何字节**，只读。带 ``--send-hex`` 时必须同时给出
``--allow-unverified-tx``，且交互确认一次（除非再加 ``--yes``）。
"""

from __future__ import annotations

import argparse
import ctypes
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vulcan_lcd.core.port_scanner import (  # noqa: E402
    DEFAULT_SNIFF_MS,
    format_results,
    list_serial_ports,
    sniff_port,
)

try:
    import serial  # noqa: E402

    PYSERIAL_VERSION = getattr(serial, "__version__", "unknown")
except ImportError:  # pragma: no cover
    PYSERIAL_VERSION = "未安装"


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - 非 Windows 或受限环境
        return False


def print_environment() -> None:
    print("=" * 76)
    print("Vulcan LCD Uploader - 串口只读嗅探")
    print("=" * 76)
    print(f"Python      : {sys.version.split()[0]}")
    print(f"解释器      : {sys.executable}")
    print(f"pyserial    : {PYSERIAL_VERSION}")
    print(f"管理员权限  : {'是' if is_admin() else '否（读取通常够用；接管服务才需要）'}")
    print()


def print_ports() -> list:
    ports = list_serial_ports()
    if not ports:
        print("未发现任何串口。")
        return []
    print(f"发现 {len(ports)} 个串口：")
    for p in ports:
        kind = "USB" if p.is_usb else "主板/未知"
        print(f"  {p.device:<8} {kind:<8} {p.description}")
        if p.hwid:
            print(f"           {p.hwid}")
    print()
    return ports


def confirm_send(payload_hex: str, yes: bool) -> bool:
    print("!" * 76)
    print("警告：你正在向串口发送**未经本项目验证**的字节。")
    print(f"待发送：{payload_hex}")
    print("协议未确认前，这类发送可能导致设备无响应或需要重新插拔。")
    print("!" * 76)
    if yes:
        print("已通过 --yes 自动确认。\n")
        return True
    answer = input("输入大写 YES 继续，其它任意输入取消: ").strip()
    return answer == "YES"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="串口只读嗅探：确认设备是否会主动/被动应答",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--port", action="append", default=[], metavar="COMn", help="只嗅探指定端口，可重复")
    parser.add_argument("--duration", type=int, default=DEFAULT_SNIFF_MS, metavar="MS", help="每端口监听时长（毫秒）")
    parser.add_argument("--list", action="store_true", help="只列出串口，不打开")
    parser.add_argument("--dry-run", action="store_true", help="空跑，不打开任何端口")
    parser.add_argument("--send-hex", default=None, metavar="HEX", help="先发送这段十六进制（需 --allow-unverified-tx）")
    parser.add_argument(
        "--allow-unverified-tx",
        action="store_true",
        help="显式确认要发送未验证字节（与 --send-hex 同时使用）",
    )
    parser.add_argument("--yes", action="store_true", help="跳过交互确认（危险）")
    args = parser.parse_args(argv)

    if args.duration <= 0:
        print("--duration 必须为正数", file=sys.stderr)
        return 2
    if args.send_hex and not args.allow_unverified_tx:
        print(
            "拒绝执行：--send-hex 必须与 --allow-unverified-tx 同时使用。\n"
            "默认策略是只读不写；握手字节未确认前不要发送任何内容。",
            file=sys.stderr,
        )
        return 2

    print_environment()
    ports = print_ports()
    if args.list:
        return 0
    if not ports:
        print("没有可用端口，退出。")
        return 0

    if args.send_hex:
        if not confirm_send(args.send_hex, args.yes):
            print("已取消。")
            return 1

    targets = args.port or [p.device for p in ports]
    print(f"开始嗅探 {len(targets)} 个端口，每个 {args.duration} ms"
          f"{'（dry-run）' if args.dry_run else '（只读，不发送）'}：\n")

    results = []
    for port in targets:
        result = sniff_port(
            port,
            args.duration,
            send_hex=args.send_hex,
            allow_unverified_tx=bool(args.send_hex),
            dry_run=args.dry_run,
        )
        results.append(result)
        print(f"  {result.summary()}")

    print()
    print(format_results(results))

    print()
    if any(r.got_data for r in results):
        print("结论：有端口返回了数据。请把上面的原始十六进制与公开协议比对，")
        print("      确认应答字节后填入 config/settings.default.json 的 handshake_rx_hex。")
    else:
        print("结论：监听期间没有任何端口返回数据。可能原因：")
        print("  1) 官方软件从未初始化过智屏，屏幕处于休眠/未枚举状态；")
        print("  2) 智屏只在收到握手后才应答，而握手字节目前仍是 null（本项目未发送任何内容）；")
        print("  3) 端口选错（COM1 通常是主板串口）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
