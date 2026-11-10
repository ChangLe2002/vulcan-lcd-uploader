"""离屏渲染播放列表面板，导出截图以检查控件外观。"""
import os
import sys

os.environ.pop("QT_QPA_PLATFORM", None)
sys.path.insert(0, r"F:\shuchu\src")

from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout  # noqa: E402

from vulcan_lcd.app import build_context  # noqa: E402
from vulcan_lcd.diagnostics.debug_session import DebugSession  # noqa: E402
from vulcan_lcd.ui.panels.playlist_panel import PlaylistPanel  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    from PySide6.QtCore import QLocale
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
    from PySide6.QtGui import QFont
    app.setFont(QFont("Microsoft YaHei UI", 9))
    ctx = build_context(DebugSession(dry_run=True), console_log=False)

    host = QWidget()
    host.setStyleSheet(
        "QSpinBox { min-width: 72px; padding: 2px 4px; }"
        "QDoubleSpinBox { min-width: 72px; padding: 2px 4px; }"
    )
    host.resize(520, 300)
    layout = QVBoxLayout(host)
    panel = PlaylistPanel(ctx)
    layout.addWidget(panel)
    host.showMinimized()
    app.processEvents()

    out = r"F:\shuchu\shot_playlist.png"
    host.grab().save(out)
    print("已保存", out)
    panel.seconds.setValue(120)
    panel.seconds.clearFocus()
    app.processEvents()
    spin = panel.seconds.grab()
    spin.save(r"F:\shuchu\shot_spinbox.png")
    spin.save(r"F:\shuchu\shot_spinbox_raw.png")
    from PIL import Image as _Im
    src = _Im.open(r"F:\shuchu\shot_spinbox_raw.png")
    src.resize((src.width * 4, src.height * 4), _Im.LANCZOS).save(
        r"F:\shuchu\shot_spinbox_big.png"
    )
    print("输入框截图:", spin.size())
    print("停留输入框几何:", panel.seconds.geometry(), " 字体:", panel.seconds.font().family())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
