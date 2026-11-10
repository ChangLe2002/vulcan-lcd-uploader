# SPDX-License-Identifier: MIT
"""上传一个 pak 到智屏（真机验证用）。

分两步验证，减少变量：

1. ``--from-pak``：直接用官方抓包还原的 pak（或其中 N 帧）上传 —— 只验证**传输链路**；
2. ``--from-gif``：从 GIF/图片重新编码 —— 额外验证**我们的 pak 构造是否正确**。

安全：默认 dry-run，只打印将发送的内容；必须加 ``--yes`` 才真正写串口。
上传前会停止 iGameCenterService，结束后（含异常）自动恢复。

用法::

    # 先看会发什么
    python tools/upload_pak.py --pak pak_s1.bin --frames 3 --dry-run

    # 真机上传
    python tools/upload_pak.py --pak pak_s1.bin --frames 3 --yes
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vulcan_lcd.core.transport import SerialSettings, Transport, TransportError  # noqa: E402
from vulcan_lcd.features.gif_upload import CHUNK_SIZE, FileEntry, upload_pak  # noqa: E402
from vulcan_lcd.media.pak import PakError, build_pak, parse_pak, sum16  # noqa: E402
from vulcan_lcd.system.service_control import ServiceController, ServiceError  # noqa: E402


def build_from_pak(path: Path, frames: int) -> tuple[bytes, str]:
    source = parse_pak(path.read_bytes())
    selected = list(source.frames[:frames]) if frames > 0 else list(source.frames)
    pak = build_pak(selected, interval_ms=source.interval_ms, reserved=source.reserved)
    return pak, f"{path.name}[{len(selected)}帧]"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="上传 pak 到智屏")
    ap.add_argument("--pak", default="", help="源 pak 文件（--clear-cache 时可省略）")
    ap.add_argument("--frames", type=int, default=0, help="只取前 N 帧（0=全部）")
    ap.add_argument("--name", default="img9.pak", help="设备上的目标文件名")
    ap.add_argument("--port", default="auto")
    ap.add_argument("--service", default="iGameCenterService")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true", help="确认真实写入")
    ap.add_argument("--hold", type=int, default=0, help="上传后保持 N 秒再恢复服务，便于观察屏幕")
    ap.add_argument("--gap-ms", type=int, default=0, help="每块之间的额外延时间隔（毫秒）")
    ap.add_argument("--clear-cache", action="store_true", help="只清理本工具上传过的设备文件后退出")
    ap.add_argument("--notify", action="store_true", help="上传后补发 e619 文件清单（只含本文件）")
    ap.add_argument("--notify-list", default="", help="上传后补发的清单，格式 name:size,name:size")
    args = ap.parse_args(argv)

    if args.clear_cache:
        import vulcan_lcd.features.screen_session as ss
        from vulcan_lcd.features.upload_ledger import UploadLedger
        ledger = UploadLedger(Path(r"F:/shuchu") / "uploaded_files.json")
        port = args.port
        if port == "auto":
            from vulcan_lcd.core.port_scanner import find_lcd_port
            port = find_lcd_port() or "COM5"
        report = ss.run_cache_clean(
            controller=ServiceController(args.service),
            transport=Transport(port, SerialSettings()),
            ledger=ledger,
        )
        print(report.describe())
        return 0 if not report.error else 6

    if not args.clear_cache and not args.pak:
        ap.error("需要 --pak，或使用 --clear-cache")

    try:
        pak, label = build_from_pak(Path(args.pak), args.frames)
    except (PakError, FileNotFoundError) as exc:
        print(f"[错误] 无法读取 pak: {exc}", file=sys.stderr)
        return 2

    chunks = (len(pak) + CHUNK_SIZE - 1) // CHUNK_SIZE
    print(f"源: {label}")
    print(f"pak: {len(pak)} 字节, sum16=0x{sum16(pak):04X}, {chunks} 块")
    print(f"目标: {args.name} @ {args.port}")

    if args.dry_run or not args.yes:
        print("\n[dry-run] 未向串口写入任何内容。确认无误后加 --yes。")
        return 0

    controller = ServiceController(args.service, timeout_s=40, attempt_timeout_s=15)
    print("\n[1/4] 停止官方服务 …")
    try:
        controller.takeover()
    except ServiceError as exc:
        print(f"[错误] 停止服务失败: {exc.message}", file=sys.stderr)
        return 3

    port = args.port
    if port == "auto":
        from vulcan_lcd.core.port_scanner import find_lcd_port
        port = find_lcd_port() or "COM5"
        print(f"[端口] 自动识别: {port}")
    transport = Transport(port, SerialSettings())
    try:
        print("[2/4] 打开串口 …")
        transport.open()
        print("[3/4] 上传 …")
        started = time.monotonic()

        def progress(done: int, total: int) -> None:
            if done == total or done % 10 == 0:
                print(f"      {done}/{total} 块")

        entries = None
        if args.notify_list:
            entries = []
            for item in args.notify_list.split(","):
                item = item.strip()
                if not item:
                    continue
                fname, _, fsize = item.partition(":")
                entries.append(FileEntry(fname.strip(), int(fsize.strip(), 0)))
        elif args.notify:
            entries = [FileEntry(args.name, len(pak))]

        result = upload_pak(
            transport, pak,
            name=args.name,
            on_progress=progress,
            block_gap_ms=args.gap_ms,
            files_after=entries,
            display_name=args.name,
            display_seconds=float(args.hold),
        )
        print(f"[4/4] {result.describe()}")
        print(f"      平均 {result.duration_ms / max(1, result.chunks):.1f} ms/块")
        if args.hold > 0:
            print(f"\n保持 {args.hold} 秒（每秒重发一次显示指令）以便观察屏幕 …")
        print("\n请查看屏幕是否切换为上传内容。")
        print("（服务恢复后屏幕会回到官方素材，需要重新上传才会保持）")
        return 0
    except TransportError as exc:
        print(f"[错误] 串口: {exc.message}", file=sys.stderr)
        return 4
    except Exception as exc:  # noqa: BLE001
        print(f"[错误] 上传失败: {exc}", file=sys.stderr)
        return 5
    finally:
        transport.close()
        print("\n[恢复] 启动官方服务 …")
        try:
            controller.release()
        except ServiceError as exc:
            print(f"[警告] 恢复服务失败: {exc.message}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
