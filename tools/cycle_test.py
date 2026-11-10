"""验证设备能否在多个已上传文件之间即时切换显示（轮播前提）。"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, r"F:\shuchu\src")

from vulcan_lcd.core.port_scanner import find_lcd_port  # noqa: E402
from vulcan_lcd.system.service_control import ServiceController  # noqa: E402
from vulcan_lcd.core.transport import SerialSettings, Transport  # noqa: E402
from vulcan_lcd.features.gif_upload import build_display_frame  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", required=True, help="逗号分隔，如 img4.pak,img5.pak")
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--seconds", type=float, default=24.0)
    args = ap.parse_args()

    names = [n.strip() for n in args.names.split(",") if n.strip()]
    if not names:
        print("没有文件")
        return 2

    controller = ServiceController("iGameCenterService")
    port = find_lcd_port() or "COM5"
    transport = Transport(port, SerialSettings())
    print(f"[端口] {port}  文件 {names}  每 {args.interval}s 切换")

    controller.takeover()
    try:
        # 服务停止后端口释放需要一点时间：带重试地打开
        last = None
        for attempt in range(20):
            try:
                transport.open()
                last = None
                break
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(1.0)
        if last is not None:
            raise last
        deadline = time.monotonic() + args.seconds
        i = 0
        while time.monotonic() < deadline:
            name = names[i % len(names)]
            print(f"  {time.strftime('%H:%M:%S')} → {name}", flush=True)
            item_deadline = time.monotonic() + args.interval
            while time.monotonic() < item_deadline and time.monotonic() < deadline:
                transport.write(build_display_frame(name))
                transport.flush()
                time.sleep(1.0)
            i += 1
    finally:
        try:
            transport.close()
        except Exception:
            pass
        controller.release()
        print("[恢复] 已启动官方服务")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
