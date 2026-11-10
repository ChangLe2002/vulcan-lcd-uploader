# SPDX-License-Identifier: MIT
"""真机验证：向设备发送监控数据帧（设备自己渲染，按页轮播）。"""

from __future__ import annotations

import argparse
import sys
import threading

sys.path.insert(0, r"F:\shuchu\src")

from vulcan_lcd.core.port_scanner import find_lcd_port  # noqa: E402
from vulcan_lcd.core.transport import SerialSettings, Transport  # noqa: E402
from vulcan_lcd.features.monitor_stream import LAYOUTS, run_monitor_stream  # noqa: E402
from vulcan_lcd.system.service_control import ServiceController  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--layout", default="gpu_core", choices=tuple(LAYOUTS))
    args = ap.parse_args()

    port = find_lcd_port() or "COM5"
    print(f"[端口] {port}  layout={args.layout}（{LAYOUTS[args.layout]}）  {args.seconds}s")

    stop = threading.Event()
    threading.Timer(args.seconds, stop.set).start()

    error = run_monitor_stream(
        controller=ServiceController("iGameCenterService"),
        transport=Transport(port, SerialSettings()),
        stop_event=stop,
        layout=args.layout,
        interval_s=args.interval,
        on_status=lambda text: print("  " + text, flush=True),
    )
    print("结果:", error or "正常结束")
    return 0 if error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
