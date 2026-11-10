# SPDX-License-Identifier: MIT
"""握手验证 CLI —— 确认指定串口后面是不是火神智屏。

用法（运行前须停止 iGameCenterService）::

    python tools/handshake_test.py --port COM4            # 只握手
    python tools/handshake_test.py --port COM4 --full     # 握手 + 初始化序列
    python tools/handshake_test.py --port COM4 --dry-run  # 空跑，不写串口

判定逻辑在 ``core/handshake.py``：结构匹配（帧头 + 长度 + 校验 + 固定 ID），
不是整包等值比较 —— 5070 与 5080 的应答有 1 个字节不同。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vulcan_lcd.core.handshake import (  # noqa: E402
    HANDSHAKE_REPLY_SAMPLE,
    perform_handshake,
    send_init_sequence,
)
from vulcan_lcd.core.transport import SerialSettings, Transport, TransportError  # noqa: E402
from vulcan_lcd.util.hexfmt import hexdump, preview  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="火神智屏握手验证")
    ap.add_argument("--port", default="COM4")
    ap.add_argument("--timeout", type=int, default=900, help="等待应答的毫秒数")
    ap.add_argument("--full", action="store_true", help="握手后再发初始化序列")
    ap.add_argument("--dry-run", action="store_true", help="不写串口")
    args = ap.parse_args(argv)

    if not args.dry_run:
        print("前置条件：iGameCenterService 必须已停止，否则 COM4 被占用。")
    print(f"目标 {args.port}，超时 {args.timeout}ms{'（dry-run）' if args.dry_run else ''}")

    transport = Transport(args.port, SerialSettings(), dry_run=args.dry_run)
    try:
        transport.open()
    except TransportError as exc:
        print(f"\n打开失败 [{exc.error_code}] {exc}")
        if exc.error_code == "PORT_BUSY":
            print("请先执行：Stop-Service iGameCenterService")
        return 2

    try:
        result = perform_handshake(transport, timeout_ms=args.timeout)
        print(f"\n[tx] {preview(result.sent)}")
        if args.dry_run:
            print("dry-run：未真正发送，跳过应答判定。")
            return 0
        if result.reply:
            print(f"[rx] {preview(result.reply)}")
            print(hexdump(result.reply))
        print(f"\n判定: {result.summary()}")
        if not result.matched:
            return 1

        if result.info is not None:
            data = result.info.as_dict()
            print(f"  seq1={data['seq1']} seq2={data['seq2']} fixed_id={data['fixed_id']}")
            print(f"  校验 0x{result.info.checksum_calculated:04X} 自洽")

        drift = [i for i in range(min(len(HANDSHAKE_REPLY_SAMPLE), len(result.reply)))
                 if HANDSHAKE_REPLY_SAMPLE[i] != result.reply[i]]
        if drift:
            print(f"  与 5080 文档样本的差异字节位置: {drift}（预期可能存在，属状态位差异）")

        if args.full:
            print("\n发送初始化序列 step3-6 ...")
            send_init_sequence(transport)
            print("完成。端口仍打开，可用 title_demo 继续发帧。")
    finally:
        transport.close()
        print("\n串口已关闭。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
