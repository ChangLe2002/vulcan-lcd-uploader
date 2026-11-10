# SPDX-License-Identifier: MIT
"""新界面通用控件：面板、动画按钮、指标条、机箱视图。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    Signal,
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import theme

__all__ = ["Panel", "AccentButton", "MetricBar", "CaseView", "Dot"]


class Panel(QFrame):
    """带编号标题的面板，对应设计图里的 01/02/… 卡片。"""

    def __init__(
        self,
        number: str,
        title: str,
        subtitle: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("role", "panel")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(12, 10, 12, 12)
        self.body.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)

        badge = QLabel(number)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(20, 16)
        badge.setStyleSheet(
            f"color:{theme.ACCENT}; border:1px solid {theme.ACCENT};"
            "font-size:10px; border-radius:2px;"
        )
        header.addWidget(badge)

        text = QVBoxLayout()
        text.setSpacing(0)
        name = QLabel(title)
        name.setStyleSheet(f"color:{theme.TEXT}; font-size:13px; font-weight:600;")
        text.addWidget(name)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setStyleSheet(f"color:{theme.MUTED}; font-size:9px; letter-spacing:1px;")
            text.addWidget(sub)
        header.addLayout(text)
        header.addStretch(1)

        self.header_right = QLabel("")
        self.header_right.setStyleSheet(f"color:{theme.MUTED}; font-size:10px;")
        header.addWidget(self.header_right)
        self.body.addLayout(header)

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{theme.BORDER};")
        self.body.addWidget(line)

    def set_right_text(self, text: str) -> None:
        self.header_right.setText(text)


class AccentButton(QPushButton):
    """带悬停/按下动画的按钮（自绘，Hover 有颜色过渡）。"""

    def __init__(
        self,
        text: str,
        *,
        variant: str = "normal",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._variant = variant
        self._hover = 0.0
        self._pressed = False
        self._anim = QPropertyAnimation(self, b"hover", self)
        self._anim.setDuration(120)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(28)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def get_hover(self) -> float:
        return self._hover

    def set_hover(self, value: float) -> None:
        self._hover = float(value)
        self.update()

    hover = Property(float, get_hover, set_hover)

    def enterEvent(self, event: object) -> None:  # noqa: N802
        self._animate(1.0)
        super().enterEvent(event)  # type: ignore[arg-type]

    def leaveEvent(self, event: object) -> None:  # noqa: N802
        self._animate(0.0)
        super().leaveEvent(event)  # type: ignore[arg-type]

    def mousePressEvent(self, event: object) -> None:  # noqa: N802
        self._pressed = True
        self.update()
        super().mousePressEvent(event)  # type: ignore[arg-type]

    def mouseReleaseEvent(self, event: object) -> None:  # noqa: N802
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)  # type: ignore[arg-type]

    def _animate(self, target: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(target)
        self._anim.start()

    def paintEvent(self, event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(0, 0, -1, -1)
        t = self._hover

        if not self.isEnabled():
            fill = QColor("#191d24")
            border = QColor("#242a33")
            text = QColor("#5a6473")
        elif self._variant == "primary":
            fill = _mix(QColor(theme.ACCENT), QColor("#fff75a"), t)
            if self._pressed:
                fill = QColor("#d8cc00")
            border = fill
            text = QColor("#0a0a0a")
        elif self._variant == "nav":
            fill = QColor(0, 0, 0, 0)
            border = QColor(0, 0, 0, 0)
            text = _mix(QColor(theme.MUTED), QColor(theme.ACCENT), t)
            if self.property("active"):
                text = QColor(theme.ACCENT)
        elif self._variant == "ghost":
            fill = QColor(255, 255, 255, int(8 + 14 * t))
            border = _mix(QColor(theme.BORDER), QColor(theme.ACCENT), t)
            text = _mix(QColor(theme.MUTED), QColor(theme.ACCENT), t)
        else:
            fill = _mix(QColor(theme.PANEL_ALT), QColor("#1d2530"), t)
            border = _mix(QColor(theme.BORDER), QColor(theme.ACCENT), t)
            text = _mix(QColor(theme.TEXT), QColor(theme.ACCENT), t)

        painter.setBrush(fill)
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(rect, 3, 3)

        font = QFont(self.font())
        font.setBold(self._variant == "primary")
        painter.setFont(font)
        painter.setPen(text)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())

        if self._variant == "nav" and self.property("active"):
            painter.setPen(QPen(QColor(theme.ACCENT), 2))
            painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.end()

    def sizeHint(self) -> QSize:  # noqa: N802
        width = self.fontMetrics().horizontalAdvance(self.text()) + 28
        return QSize(max(72, width), 28)


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
        int(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


class MetricBar(QWidget):
    """一条指标：名称 + 温度 + 进度条 + 百分比。"""

    def __init__(self, label: str, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.name = QLabel(label)
        self.name.setFixedWidth(34)
        self.name.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        layout.addWidget(self.name)

        self.badge_label = QLabel("")
        self.badge_label.setFixedWidth(46)
        self.badge_label.setStyleSheet(f"color:{theme.TEXT}; font-size:11px;")
        layout.addWidget(self.badge_label)

        self.track = _BarTrack(self._color, self)
        layout.addWidget(self.track, 1)

        self.value_label = QLabel("—")
        self.value_label.setFixedWidth(38)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.value_label.setStyleSheet(f"color:{theme.TEXT}; font-size:11px;")
        layout.addWidget(self.value_label)

    def update_metric(self, *, badge: str, value: int, text: str) -> None:
        self.badge_label.setText(badge)
        self.value_label.setText(text)
        self.track.set_value(value)


class _BarTrack(QWidget):
    def __init__(self, color: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = color
        self._value = 0
        self.setFixedHeight(6)
        self.setMinimumWidth(60)

    def set_value(self, value: int) -> None:
        self._value = max(0, min(100, int(value)))
        self.update()

    def paintEvent(self, event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1b222c"))
        painter.drawRoundedRect(rect, 3, 3)
        if self._value > 0:
            fill_width = max(2, int(rect.width() * self._value / 100))
            painter.setBrush(self._color)
            painter.drawRoundedRect(QRect(0, 0, fill_width, rect.height()), 3, 3)
        painter.end()


class Dot(QLabel):
    """状态圆点。"""

    def __init__(self, color: str = theme.MUTED, parent: QWidget | None = None) -> None:
        super().__init__("●", parent)
        self.set_color(color)

    def set_color(self, color: str) -> None:
        self.setStyleSheet(f"color:{color}; font-size:12px;")


class CaseView(QWidget):
    """机箱视图：底图 + 在显卡小屏位置叠加竖屏预览（圆角 + 微光）。"""

    clicked = Signal()

    def __init__(
        self,
        background: Path | None,
        lcd_rect: QRect,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._bg = QPixmap(str(background)) if background and background.is_file() else QPixmap()
        self._lcd_rect = lcd_rect
        self._preview: QPixmap | None = None

    def set_preview(self, pixmap: QPixmap | None) -> None:
        self._preview = pixmap
        self.update()

    def mouseReleaseEvent(self, event: object) -> None:  # noqa: N802
        self.clicked.emit()
        super().mouseReleaseEvent(event)  # type: ignore[arg-type]

    def paintEvent(self, event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        rect = self.rect()

        if self._bg.isNull():
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "机箱底图缺失")
            painter.end()
            return

        scaled = self._bg.scaled(
            rect.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = rect.x() + (rect.width() - scaled.width()) // 2
        y = rect.y() + (rect.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)

        sx = scaled.width() / self._bg.width()
        sy = scaled.height() / self._bg.height()
        lcd = QRect(
            int(x + self._lcd_rect.x() * sx),
            int(y + self._lcd_rect.y() * sy),
            max(2, int(self._lcd_rect.width() * sx)),
            max(2, int(self._lcd_rect.height() * sy)),
        )

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(89, 207, 255, 26))
        painter.drawRoundedRect(lcd.adjusted(-7, -7, 7, 7), 12, 12)
        painter.setBrush(QColor(89, 207, 255, 48))
        painter.drawRoundedRect(lcd.adjusted(-3, -3, 3, 3), 9, 9)

        painter.setBrush(QColor(0, 0, 0))
        painter.setPen(QPen(QColor(36, 48, 64), 2))
        painter.drawRoundedRect(lcd, 7, 7)

        if self._preview is not None and not self._preview.isNull():
            inner = lcd.adjusted(3, 3, -3, -3)
            target = self._preview.scaled(
                inner.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            path = QPainterPath()
            path.addRoundedRect(QRectF(inner), 5, 5)
            painter.save()
            painter.setClipPath(path)
            painter.drawPixmap(
                inner.x() + (inner.width() - target.width()) // 2,
                inner.y() + (inner.height() - target.height()) // 2,
                target,
            )
            painter.restore()
        else:
            painter.setPen(QColor(89, 207, 255, 120))
            painter.drawText(lcd, Qt.AlignmentFlag.AlignCenter, "竖屏\n预览")
        painter.end()
