"""截图主窗口，检查移除连接面板后的布局。"""
import sys

sys.path.insert(0, r"F:\shuchu\src")

from PySide6.QtCore import QLocale  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from vulcan_lcd.app import build_context  # noqa: E402
from vulcan_lcd.diagnostics.debug_session import DebugSession  # noqa: E402
from vulcan_lcd.ui.main_window import MainWindow  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))

    ctx = build_context(DebugSession(dry_run=True), console_log=False)
    win = MainWindow(ctx)
    win.resize(1200, 780)
    win.showMinimized()
    for _ in range(3):
        app.processEvents()

    win.grab().save(r"F:\shuchu\shot_main.png")
    print("已保存 shot_main.png")
    for index in range(win.tabs.count()):
        win.tabs.setCurrentIndex(index)
        for _ in range(3):
            app.processEvents()
        name = win.tabs.tabText(index).replace("/", "_")
        path = rf"F:\shuchu\shot_tab_{index}_{name}.png"
        win.tabs.grab().save(path)
        print("已保存", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
