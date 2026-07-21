"""Custom-painted controls: toggle switch, color swatch, card, zone strip."""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QColorDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import theme


class Card(QFrame):
    """Rounded panel with a small uppercase title."""

    def __init__(self, title: str | None = None, parent=None):
        super().__init__(parent)
        self.setProperty("class", "card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(20, 16, 20, 18)
        self._layout.setSpacing(12)
        if title:
            label = QLabel(title.upper())
            label.setProperty("class", "cardtitle")
            self._layout.addWidget(label)

    def add(self, widget_or_layout):
        if isinstance(widget_or_layout, QWidget):
            self._layout.addWidget(widget_or_layout)
        else:
            self._layout.addLayout(widget_or_layout)
        return widget_or_layout


class ToggleSwitch(QWidget):
    """Animated iOS-style switch. Emits toggled(bool) on user action only."""

    toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checked = False
        self._knob = 0.0
        self.setFixedSize(46, 26)
        self.setCursor(Qt.PointingHandCursor)
        # NB: property must not be called "pos" — it would shadow
        # QWidget.pos and the animation would move the widget instead.
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def _get_knob(self) -> float:
        return self._knob

    def _set_knob(self, v: float) -> None:
        self._knob = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        """Programmatic set — animates but does not emit toggled."""
        if checked == self._checked:
            return
        self._checked = checked
        self._anim.stop()
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.setChecked(not self._checked)
            self.toggled.emit(self._checked)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        off = QColor(theme.BORDER)
        on = QColor(theme.ACCENT)

        def mix(a, b):
            return int(a + (b - a) * self._knob)

        track = QColor(
            mix(off.red(), on.red()),
            mix(off.green(), on.green()),
            mix(off.blue(), on.blue()),
        )
        if not self.isEnabled():
            track.setAlpha(120)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, 46, 26), 13, 13)
        x = 3 + self._knob * (46 - 26)
        knob = QColor("#ffffff" if self.isEnabled() else theme.MUTED)
        p.setBrush(knob)
        p.drawEllipse(QRectF(x, 3, 20, 20))


class ColorSwatch(QPushButton):
    """Clickable color square opening a color dialog."""

    colorChanged = Signal(QColor)

    def __init__(self, color: QColor, size: int = 34, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(QSize(size, size))
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._pick)

    def color(self) -> QColor:
        return self._color

    def setColor(self, color: QColor) -> None:
        self._color = color
        self.update()

    def _pick(self) -> None:
        chosen = QColorDialog.getColor(self._color, self, "Choose color")
        if chosen.isValid():
            self._color = chosen
            self.update()
            self.colorChanged.emit(chosen)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(self._color)
        p.drawRoundedRect(r, 8, 8)


class ZoneStrip(QWidget):
    """Visual of the 4 keyboard zones; each zone is a clickable swatch."""

    zoneColorChanged = Signal(int, QColor)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.swatches: list[ColorSwatch] = []
        for i in range(4):
            column = QVBoxLayout()
            column.setSpacing(6)
            swatch = ColorSwatch(QColor(theme.ACCENT), size=52)
            swatch.colorChanged.connect(
                lambda c, idx=i: self.zoneColorChanged.emit(idx, c)
            )
            label = QLabel(f"Zone {i + 1}")
            label.setProperty("class", "muted")
            label.setAlignment(Qt.AlignHCenter)
            column.addWidget(swatch)
            column.addWidget(label)
            layout.addLayout(column)
            self.swatches.append(swatch)
        layout.addStretch(1)

    def set_colors(self, colors: list[tuple[int, int, int]]) -> None:
        for swatch, (r, g, b) in zip(self.swatches, colors, strict=False):
            swatch.setColor(QColor(r, g, b))

    def set_uniform_enabled(self, enabled: bool) -> None:
        for swatch in self.swatches:
            swatch.setEnabled(enabled)


class TempGraph(QWidget):
    """Rolling temperature history. Bounded deque (~6 min at one sample
    per 3 s), custom-painted — no chart library, negligible memory."""

    CAPACITY = 120
    Y_MIN, Y_MAX = 30.0, 100.0
    WATCHDOG = 90.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.samples: deque[tuple] = deque(maxlen=self.CAPACITY)
        self.setMinimumHeight(170)

    def add_sample(self, cpu: float | None, igpu: float | None,
                   dgpu: float | None) -> None:
        self.samples.append((cpu, igpu, dgpu))
        self.update()

    def _series(self):
        result = [
            ("CPU", QColor(theme.ACCENT), [s[0] for s in self.samples]),
            ("GPU Vega", QColor(theme.BLUE), [s[1] for s in self.samples]),
        ]
        dgpu = [s[2] for s in self.samples]
        if any(v is not None for v in dgpu):
            result.append(("GTX 1650", QColor(theme.YELLOW), dgpu))
        return result

    def _y(self, value: float, top: float, bottom: float) -> float:
        span = self.Y_MAX - self.Y_MIN
        frac = (value - self.Y_MIN) / span
        frac = max(0.0, min(1.0, frac))
        return bottom - frac * (bottom - top)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        left, right = 34.0, self.width() - 10.0
        top, bottom = 10.0, self.height() - 20.0
        if right <= left or bottom <= top:
            return

        font = p.font()
        font.setPointSize(8)
        p.setFont(font)

        # grid + labels
        for level in (40, 60, 80):
            y = self._y(level, top, bottom)
            p.setPen(QPen(QColor(theme.BORDER), 1))
            p.drawLine(int(left), int(y), int(right), int(y))
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(0, y - 7, 30, 14),
                       Qt.AlignRight | Qt.AlignVCenter, f"{level}°")

        # watchdog threshold
        wd_y = self._y(self.WATCHDOG, top, bottom)
        wd_pen = QPen(QColor(theme.ACCENT), 1, Qt.DashLine)
        p.setPen(wd_pen)
        p.drawLine(int(left), int(wd_y), int(right), int(wd_y))

        # series polylines (fixed x-step: time scale stays constant,
        # graph scrolls once the deque is full; None values break lines)
        step = (right - left) / (self.CAPACITY - 1)
        for _name, color, values in self._series():
            p.setPen(QPen(color, 2))
            prev = None
            for i, value in enumerate(values):
                if value is None:
                    prev = None
                    continue
                x = left + i * step
                y = self._y(value, top, bottom)
                if prev is not None:
                    p.drawLine(prev[0], prev[1], x, y)
                prev = (x, y)

        # legend, top-right
        x = right
        for name, color, values in reversed(self._series()):
            latest = next(
                (v for v in reversed(values) if v is not None), None
            )
            label = f"{name} {latest:.0f}°" if latest is not None else name
            width = p.fontMetrics().horizontalAdvance(label) + 16
            x -= width
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawEllipse(QRectF(x, top + 2, 7, 7))
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(x + 11, top - 3, width - 11, 16),
                       Qt.AlignLeft | Qt.AlignVCenter, label)

        p.setPen(QColor(theme.MUTED))
        p.drawText(QRectF(left, bottom + 4, right - left, 14),
                   Qt.AlignLeft, "last 6 minutes")


class BatteryBar(QWidget):
    """Slim battery level bar with an 80% limit marker."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._percent = 0
        self._limiter = False
        self.setFixedHeight(14)
        self.setMinimumWidth(220)

    def set_state(self, percent: int, limiter: bool) -> None:
        self._percent = percent
        self._limiter = limiter
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.BORDER))
        p.drawRoundedRect(QRectF(0, h / 2 - 3, w, 6), 3, 3)
        fill_w = w * self._percent / 100
        color = QColor(theme.OK) if self._percent > 20 else QColor(theme.ACCENT)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(0, h / 2 - 3, fill_w, 6), 3, 3)
        if self._limiter:
            x = w * 0.8
            p.setPen(QPen(QColor(theme.TEXT), 2))
            p.drawLine(int(x), 0, int(x), h)
