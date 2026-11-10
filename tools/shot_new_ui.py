"""截图新界面，检查布局与配色。"""
import os
import sys

sys.path.insert(0, r"F:\shuchu\src")
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QLocale  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from vulcan_lcd.app import build_context  # noqa: E402
from vulcan_lcd.diagnostics.debug_session import DebugSession  # noqa: E402
from vulcan_lcd.ui2.window import NewMainWindow  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))

    ctx = build_context(DebugSession(dry_run=True), console_log=False)
    win = NewMainWindow(ctx)
    win.resize(1480, 900)
    win.showMinimized()
    for _ in range(6):
        app.processEvents()
    win.grab().save(r"F:\shuchu\shot_new.png")
    print("已保存 shot_new.png", win.size())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
