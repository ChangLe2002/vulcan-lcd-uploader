# SPDX-License-Identifier: MIT
"""只读查询：问设备"你现在有哪些文件"。

依据：抓包里 ``e619`` 总是成对出现——9 字节空帧（请求）+ 带列表的帧（应答）。
本工具只发那条 9 字节请求，然后读回应答，**不写任何状态**。

用途：判断我们上传的 pak 到底有没有被设备接受。
如果列表里出现 ``img5.pak`` 且大小正确 → 文件写进去了，问题在"显示切换"；
如果没有 → 文件被拒收，问题在写入阶段。

用法::

    python tools/query_files.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vulcan_lcd.core.transport import SerialSettings, Transport, TransportError  # noqa: E402
from vulcan_lcd.features.gif_upload import FILE_LIST_ID  # noqa: E402
from vulcan_lcd.core.protocol import parse_frame  # noqa: E402
from vulcan_lcd.system.service_control import ServiceController, ServiceError  # noqa: E402
from vulcan_lcd.util.hexfmt import hexdump  # noqa: E402

#: 实测的清单查询请求（9 字节空帧）
QUERY = bytes.fromhex("5A9FA90004E61902A5")


def parse_entries(body: bytes) -> list[tuple[int, int, str]]:
    """解析清单应答：flag u16 + size u24 + name + 0x00，循环到结尾。"""
    entries: list[tuple[int, int, str]] = []
    index = 2  # 跳过固定 ID
    while index + 5 <= len(body):
        flag = int.from_bytes(body[index : index + 2], "big")
        size = int.from_bytes(body[index + 2 : index + 5], "big")
        end = body.find(b"\x00", index + 5)
        if end < 0:
            break
        name = body[index + 5 : end].decode("ascii", errors="replace")
        entries.append((flag, size, name))
        index = end + 1
    return entries


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="查询设备上的文件清单（只读）")
    ap.add_argument("--port", default="auto")
    ap.add_argument("--service", default="iGameCenterService")
    ap.add_argument("--timeout", type=int, default=1500)
    args = ap.parse_args(argv)

    controller = ServiceController(args.service, timeout_s=40, attempt_timeout_s=15)
    port = args.port
    if port == "auto":
        from vulcan_lcd.core.port_scanner import find_lcd_port
        port = find_lcd_port() or "COM5"
        print(f"[端口] {port}")
    transport = Transport(port, SerialSettings())
    try:
        print("[1/3] 停止官方服务 …")
        controller.takeover()
        print("[2/3] 打开串口并发送清单查询 …")
        transport.open()
        transport.reset_input_buffer()
        transport.write(QUERY)
        raw = transport.read_for(args.timeout)
        print(f"[3/3] 收到 {len(raw)} 字节")
        if not raw:
            print("无应答（设备可能未就绪）")
            return 1

        print()
        print(hexdump(raw, limit=512))

        found = False
        offset = 0
        while True:
            start = raw.find(bytes.fromhex("5a9fa9"), offset)
            if start < 0:
                break
            if start + 5 > len(raw):
                break
            total = raw[start + 4] + 5
            if start + total > len(raw):
                break
            frame = raw[start : start + total]
            offset = start + total
            try:
                info = parse_frame(frame, strict=False)
            except Exception:  # noqa: BLE001
                continue
            if info.fixed_id != FILE_LIST_ID:
                continue
            found = True
            entries = parse_entries(info.body)
            print()
            print(f"清单应答（{len(entries)} 个文件）:")
            for flag, size, name in entries:
                print(f"  flag=0x{flag:04X}  size={size:>9}  {name}")

        if not found:
            print()
            print("应答里没有找到 e619 清单帧。")
        return 0
    except (ServiceError, TransportError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2
    finally:
        transport.close()
        try:
            controller.release()
            print("\n[恢复] 官方服务已重启")
        except ServiceError as exc:
            print(f"[警告] 恢复服务失败: {exc.message}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
