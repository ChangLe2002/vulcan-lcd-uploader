# SPDX-License-Identifier: MIT
"""标题投屏 CLI —— 把一行文字显示到火神智屏。

这是**调试/验收工具**，不是 GUI 功能。正式的投屏能力由 ``core/protocol.py``
的 ``build_time_frame`` 提供，GUI（模块 9）会直接调用它。

用法（运行前须停止 iGameCenterService）::

    python tools/title_demo.py --title "I LOVE YOU" --seconds 10
    python tools/title_demo.py --title "下雨223" --dry-run     # 看会被过滤成什么
    python tools/title_demo.py --raw --title "下雨223"          # 探测未公开字符集

字符集：设备只渲染 ``A-Z 0-9 . 空格``；其他字节被**静默丢弃**（实机验证）。
``--raw`` 绕过本地过滤，仅用于实验，正常使用不要开。
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vulcan_lcd.constants import MAX_TITLE_CHARS  # noqa: E402
from vulcan_lcd.core.handshake import perform_handshake, send_init_sequence  # noqa: E402
from vulcan_lcd.core.protocol import TitleEncoding, build_time_frame, encode_title  # noqa: E402
from vulcan_lcd.core.transport import SerialSettings, Transport, TransportError  # noqa: E402
from vulcan_lcd.util.hexfmt import hexdump, preview  # noqa: E402


def resolve_title(text: str, raw: bool) -> TitleEncoding:
    """按是否 raw 模式生成待发送的 title。"""
    if not raw:
        return encode_title(text)
    payload = text.encode("utf-8")[:MAX_TITLE_CHARS]
    return TitleEncoding(text=text, raw=payload, dropped=[], truncated=len(text.encode("utf-8")) > MAX_TITLE_CHARS)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="火神智屏标题投屏")
    ap.add_argument("--port", default="COM4")
    ap.add_argument("--title", default="I LOVE YOU")
    ap.add_argument("--seconds", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--raw", action="store_true", help="不过滤字符，按 UTF-8 原样发送（仅实验）")
    args = ap.parse_args(argv)

    encoding = resolve_title(args.title, args.raw)
    if not encoding.raw:
        print("标题清洗后为空。屏幕只支持 A-Z 0-9 . 空格；若想探测其它字符请加 --raw。")
        return 2

    if encoding.was_modified:
        print(f"⚠️ {encoding.user_note()}")
    print(f"发送内容: {encoding.text!r} -> {encoding.raw.hex() or '<empty>'}")
    print(f"目标 {args.port}，持续 {args.seconds}s{'（dry-run）' if args.dry_run else ''}")

    transport = Transport(args.port, SerialSettings(), dry_run=args.dry_run)
    try:
        transport.open()
    except TransportError as exc:
        print(f"\n打开失败 [{exc.error_code}] {exc}")
        if exc.error_code == "PORT_BUSY":
            print("请先执行：Stop-Service iGameCenterService")
        return 2

    try:
        print("\n[1/3] 握手")
        result = perform_handshake(transport)
        if args.dry_run:
            print("  dry-run：跳过应答判定")
        elif not result.matched:
            print(f"  失败：{result.summary()}")
            return 1
        else:
            print(f"  成功，应答 {preview(result.reply)}")

        print("\n[2/3] 初始化序列 step3-6")
        send_init_sequence(transport, delay_s=0 if args.dry_run else 0.08)
        print(f"  已发送 {4} 帧")

        print("\n[3/3] 标题帧")
        deadline = time.monotonic() + args.seconds
        count = 0
        while time.monotonic() < deadline:
            frame = build_time_frame(encoding, moment=datetime.now())
            transport.write(frame)
            if count == 0:
                print(f"  首帧 {len(frame)}B: {preview(frame)}")
                print(hexdump(frame))
            count += 1
            if args.dry_run:
                break
            time.sleep(1.0)
        print(f"  共 {count} 帧")
    except TransportError as exc:
        print(f"\n串口错误 [{exc.error_code}] {exc}")
        return 1
    finally:
        transport.close()
        print("\n串口已关闭（避免下次开机 COM 口异常）。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
