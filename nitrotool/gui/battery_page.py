"""Battery page: live state, charge limiter toggle."""

from __future__ import annotations

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import hw
from .widgets import BatteryBar, Card, ToggleSwitch


class BatteryPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pkexec: QProcess | None = None
        self._was_held = False   # for the one-shot "charging stopped" notification

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        title = QLabel("Battery")
        title.setProperty("class", "pagetitle")
        root.addWidget(title)

        # STATUS CARD
        status_card = Card("Status")
        row = QHBoxLayout()
        row.setSpacing(24)

        self.percent_label = QLabel("—")
        self.percent_label.setStyleSheet(
            "font-size: 44px; font-weight: 600;"
        )
        row.addWidget(self.percent_label, 0, Qt.AlignVCenter)

        col = QVBoxLayout()
        col.setSpacing(6)
        self.status_label = QLabel("Reading…")
        self.status_label.setStyleSheet("font-size: 15px;")
        self.bar = BatteryBar()
        self.bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.detail_label = QLabel("")
        self.detail_label.setProperty("class", "muted")
        col.addWidget(self.status_label)
        col.addWidget(self.bar)
        col.addWidget(self.detail_label)
        row.addLayout(col, 1)
        status_card.add(row)
        root.addWidget(status_card)

        # LIMITER CARD
        limiter_card = Card("Charge limit")
        lrow = QHBoxLayout()
        lcol = QVBoxLayout()
        lcol.setSpacing(4)
        limiter_title = QLabel("Limit charging to 80%")
        limiter_title.setStyleSheet("font-size: 15px;")
        limiter_sub = QLabel(
            "Stops charging at 80% so the battery lasts longer.\n"
            "This is the same firmware feature NitroSense uses on Windows."
        )
        limiter_sub.setProperty("class", "muted")
        lcol.addWidget(limiter_title)
        lcol.addWidget(limiter_sub)
        lrow.addLayout(lcol, 1)
        self.toggle = ToggleSwitch()
        self.toggle.toggled.connect(self._on_toggle)
        lrow.addWidget(self.toggle, 0, Qt.AlignVCenter)
        limiter_card.add(lrow)
        self.limiter_note = QLabel("")
        self.limiter_note.setProperty("class", "muted")
        self.limiter_note.setWordWrap(True)
        limiter_card.add(self.limiter_note)
        root.addWidget(limiter_card)

        # DRIVER-MISSING NOTICE
        self.notice = Card("Driver not loaded")
        notice_label = QLabel(
            "The battery driver (acer-wmi-battery) is not loaded, so the "
            "charge limiter is unavailable. Enable it from the Setup page."
        )
        notice_label.setProperty("class", "muted")
        notice_label.setWordWrap(True)
        notice_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.notice.add(notice_label)
        root.addWidget(self.notice)

        root.addStretch(1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(2000)
        self.refresh()

    def refresh(self) -> None:
        st = hw.Battery.read()

        self.percent_label.setText(f"{st.percent}%")
        self.bar.set_state(st.percent, st.limiter)

        if st.held_at_limit and not self._was_held:
            # entered the held state right now -> desktop notification
            QProcess.startDetached("notify-send", [
                "-i", "battery-good-charging",
                "NitroPenguin",
                "Charging stopped at 80%. The limiter is keeping your "
                "battery topped up, not full.",
            ])
        self._was_held = st.held_at_limit

        if st.held_at_limit:
            self.status_label.setText("Held at 80% by limiter")
        elif st.status == "Charging":
            self.status_label.setText("Charging")
        elif st.status == "Full":
            self.status_label.setText("Fully charged")
        elif st.status == "Discharging":
            self.status_label.setText("On battery")
        else:
            self.status_label.setText(st.status)

        details = []
        details.append("Plugged in" if st.ac_online else "On battery power")
        if st.temp_c is not None:
            details.append(f"battery {st.temp_c:.1f} °C")
        self.detail_label.setText("  ·  ".join(details))

        self.notice.setVisible(not st.available)
        self.toggle.setEnabled(st.available and self._pkexec is None)
        if self._pkexec is None:
            self.toggle.setChecked(st.limiter)

    def _on_toggle(self, on: bool) -> None:
        if hw.Battery.set_limiter_direct(on):
            self.limiter_note.setText("")
            self.refresh()
            return
        # Needs privileges: ask via polkit (system password dialog).
        self.limiter_note.setText("Waiting for authorization…")
        self.toggle.setEnabled(False)
        cmd = hw.Battery.limiter_command(on)
        self._pkexec = QProcess(self)
        self._pkexec.finished.connect(
            lambda code, _s, on=on: self._pkexec_done(code, on)
        )
        self._pkexec.start(cmd[0], cmd[1:])

    def _pkexec_done(self, code: int, wanted_on: bool) -> None:
        self._pkexec = None
        if code == 0:
            self.limiter_note.setText("")
        else:
            self.limiter_note.setText(
                "Authorization was cancelled. The limiter was not changed."
            )
            self.toggle.setChecked(not wanted_on)
        self.toggle.setEnabled(True)
        self.refresh()
