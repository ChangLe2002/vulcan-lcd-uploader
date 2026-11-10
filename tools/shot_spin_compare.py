"""对照实验：定位 QSpinBox 数字渲染异常的来源。"""
import sys

sys.path.insert(0, r"F:\shuchu\src")

from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QFormLayout,
    QLabel,
    QSpinBox,
    QWidget,
)

from PIL import Image  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    from PySide6.QtCore import QLocale
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
    app.setFont(QFont("Microsoft YaHei UI", 9))

    host = QWidget()
    host.resize(420, 260)
    form = QFormLayout(host)

    a = QSpinBox()
    a.setValue(120)
    form.addRow("① 无样式", a)

    b = QSpinBox()
    b.setValue(120)
    b.setStyleSheet("min-width: 72px; padding: 2px 4px;")
    form.addRow("② 只加 min-width/padding", b)

    c = QSpinBox()
    c.setValue(120)
    c.setFont(QFont("Segoe UI", 10))
    form.addRow("③ 显式 Segoe UI", c)

    d = QLabel("120 秒（QLabel 对照）")
    form.addRow("④ 标签对照", d)

    host.showMinimized()
    app.processEvents()

    host.grab().save(r"F:\shuchu\shot_spin_compare.png")
    print("已保存对比图")
    for name, widget in (("①", a), ("②", b), ("③", c)):
        print(name, "字体:", widget.font().family(), widget.font().pointSize())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
