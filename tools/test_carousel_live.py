"""真机验证：播放列表轮播（上传两个 GIF 后循环切换）。"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, r"F:\shuchu\src")

from vulcan_lcd.core.port_scanner import find_lcd_port  # noqa: E402
from vulcan_lcd.core.transport import SerialSettings, Transport  # noqa: E402
from vulcan_lcd.features.carousel import build_entries, run_playlist  # noqa: E402
from vulcan_lcd.system.service_control import ServiceController  # noqa: E402

SRC = Path(r"E:\iGameCenter\LCDResource\LCD40&50")

paths = [SRC / "初音未来.gif", SRC / "TOP9Lee.gif"]
missing = [str(p) for p in paths if not p.is_file()]
if missing:
    print("缺少素材:", missing)
    raise SystemExit(2)

t0 = time.perf_counter()
entries = build_entries([(p, 4.0) for p in paths], on_progress=lambda d, t, n: print(f"  编码 {d}/{t}: {n}"))
print(f"编码完成：{time.perf_counter() - t0:.2f}s，共 {len(entries)} 项")

stop = threading.Event()
threading.Timer(22.0, stop.set).start()

report = run_playlist(
    entries,
    controller=ServiceController("iGameCenterService"),
    transport=Transport(find_lcd_port() or "COM5", SerialSettings()),
    stop_event=stop,
    on_status=lambda s: print("  [状态]", s),
)
print("结果:", report.describe())
print("已上传:", report.uploaded, " 切换次数:", report.cycled)
