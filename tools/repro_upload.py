"""无人值守复现 GUI 上传：直接驱动 PreviewPanel，打印每个阶段与耗时。"""
import sys
import time

sys.path.insert(0, r"F:\shuchu\src")

from PySide6.QtCore import QLocale, QTimer  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from vulcan_lcd.app import build_context  # noqa: E402
from vulcan_lcd.diagnostics.debug_session import DebugSession  # noqa: E402
from vulcan_lcd.ui.panels.preview_panel import PreviewPanel  # noqa: E402

GIF = r"E:\iGameCenter\LCDResource\LCD40&50\初音未来.gif"


def main() -> int:
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))

    ctx = build_context(DebugSession(dry_run=False), console_log=False)
    panel = PreviewPanel(ctx)

    start = time.monotonic()

    def stamp(label: str) -> None:
        print(f"[{time.monotonic() - start:6.1f}s] {label}", flush=True)

    # 直接喂文件（复刻 pick_file 的内部流程）
    from pathlib import Path

    from vulcan_lcd.ui.panels.preview_panel import _ProbeWorker

    panel._path = Path(GIF)
    probe = _ProbeWorker(panel._path)
    probe.done.connect(panel._on_done)
    probe.failed.connect(panel._on_failed)
    probe.start()
    probe.wait(30000)
    print("预览分析完成")

    QTimer.singleShot(200, lambda: (stamp("开始上传"), panel.send_upload()))
    QTimer.singleShot(180_000, lambda: (stamp("超时退出"), app.quit()))

    # 每 3 秒打印一次当前状态文本与进度条
    def poll() -> None:
        try:
            note = panel.note.text()
            lo, hi = panel.progress.minimum(), panel.progress.maximum()
            val = panel.progress.value()
            stamp(f"状态={note!r} 进度={val}/{hi if hi > 0 else lo}")
        except Exception:  # noqa: BLE001
            pass

    timer = QTimer()
    timer.timeout.connect(poll)
    timer.start(3000)

    app.exec()
    stamp("退出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
