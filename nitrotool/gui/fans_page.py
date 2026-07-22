"""Fans page: Auto / Max / Custom fan control with safety guardrails.

Guardrails (deliberately stricter than NitroSense):
- custom sliders bottom out at hw.FAN_FLOOR, never 0
- thermal watchdog: in custom mode, CPU or GPU above hw.WATCHDOG_TEMP
  forces fans back to Auto and says so
- the app never re-applies fan settings at startup: every boot begins
  in firmware Auto mode
"""

from __future__ import annotations

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .. import hw
from .widgets import Card, TempGraph


class FansPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pkexec: QProcess | None = None
        self._nvidia: QProcess | None = None
        self._dgpu_temp: float | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        title = QLabel("Fans")
        title.setProperty("class", "pagetitle")
        root.addWidget(title)

        # TEMPERATURES
        temp_card = Card("Temperatures")
        temp_row = QHBoxLayout()
        temp_row.setSpacing(40)
        self.cpu_temp_label = self._temp_block(temp_row, "CPU")
        self.igpu_temp_label = self._temp_block(temp_row, "GPU (Vega)")
        self.dgpu_temp_label = self._temp_block(temp_row, "GPU (GTX 1650)")
        temp_row.addStretch(1)
        temp_card.add(temp_row)
        self.graph = TempGraph()
        temp_card.add(self.graph)
        root.addWidget(temp_card)

        # MODE
        mode_card = Card("Fan mode")
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        self.auto_button = QPushButton("Auto")
        self.max_button = QPushButton("Max")
        self.custom_button = QPushButton("Custom")
        for button in (self.auto_button, self.max_button, self.custom_button):
            button.setProperty("class", "mode")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            mode_row.addWidget(button)
        mode_row.addStretch(1)
        self.auto_button.clicked.connect(lambda: self._apply_mode("auto"))
        self.max_button.clicked.connect(lambda: self._apply_mode("max"))
        self.custom_button.clicked.connect(lambda: self._apply_mode("custom"))
        mode_card.add(mode_row)
        mode_hint = QLabel(
            "Auto: firmware curve, the default on every boot.  "
            "Max: both fans at 100%.  Custom: set each fan yourself."
        )
        mode_hint.setProperty("class", "muted")
        mode_hint.setWordWrap(True)
        mode_card.add(mode_hint)
        root.addWidget(mode_card)

        # CUSTOM SLIDERS
        self.custom_card = Card("Custom fan duty")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(14)

        grid.addWidget(QLabel("CPU fan"), 0, 0)
        self.cpu_slider = QSlider(Qt.Horizontal)
        self.cpu_slider.setRange(hw.FAN_FLOOR, 100)
        self.cpu_slider.setValue(60)
        self.cpu_value = QLabel("60%")
        self.cpu_value.setProperty("class", "muted")
        self.cpu_value.setMinimumWidth(44)
        grid.addWidget(self.cpu_slider, 0, 1)
        grid.addWidget(self.cpu_value, 0, 2)

        grid.addWidget(QLabel("GPU fan"), 1, 0)
        self.gpu_slider = QSlider(Qt.Horizontal)
        self.gpu_slider.setRange(hw.FAN_FLOOR, 100)
        self.gpu_slider.setValue(60)
        self.gpu_value = QLabel("60%")
        self.gpu_value.setProperty("class", "muted")
        self.gpu_value.setMinimumWidth(44)
        grid.addWidget(self.gpu_slider, 1, 1)
        grid.addWidget(self.gpu_value, 1, 2)

        grid.setColumnStretch(1, 1)
        self.custom_card.add(grid)
        floor_hint = QLabel(
            f"Sliders stop at {hw.FAN_FLOOR}% on purpose. If the CPU or GPU "
            f"goes past {hw.WATCHDOG_TEMP:.0f} °C, the app puts the fans "
            "back on Auto."
        )
        floor_hint.setProperty("class", "muted")
        floor_hint.setWordWrap(True)
        self.custom_card.add(floor_hint)
        root.addWidget(self.custom_card)

        for slider, label in (
            (self.cpu_slider, self.cpu_value),
            (self.gpu_slider, self.gpu_value),
        ):
            slider.valueChanged.connect(
                lambda v, lab=label: lab.setText(f"{v}%")
            )
            slider.sliderReleased.connect(self._custom_changed)

        self.status_note = QLabel("")
        self.status_note.setProperty("class", "muted")
        self.status_note.setWordWrap(True)
        root.addWidget(self.status_note)

        # DRIVER-MISSING NOTICE
        self.notice = Card("Driver not loaded")
        notice_label = QLabel(
            "The fan driver (acer-fan-ctl) is not loaded, so fan control "
            "is unavailable. Enable it from the Setup page."
        )
        notice_label.setProperty("class", "muted")
        notice_label.setWordWrap(True)
        self.notice.add(notice_label)
        root.addWidget(self.notice)

        root.addStretch(1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(3000)
        self.refresh()

    @staticmethod
    def _temp_block(row: QHBoxLayout, name: str) -> QLabel:
        col = QVBoxLayout()
        col.setSpacing(2)
        value = QLabel("—")
        value.setStyleSheet("font-size: 26px; font-weight: 600;")
        caption = QLabel(name)
        caption.setProperty("class", "muted")
        col.addWidget(value)
        col.addWidget(caption)
        row.addLayout(col)
        return value

    def refresh(self) -> None:
        st = hw.Fans.read()
        self.notice.setVisible(not st.available)
        for w in (self.auto_button, self.max_button, self.custom_button):
            w.setEnabled(st.available and self._pkexec is None)

        self.auto_button.setChecked(st.mode == "auto")
        self.max_button.setChecked(st.mode == "max")
        self.custom_button.setChecked(st.mode == "custom")
        self.custom_card.setVisible(st.mode == "custom")

        cpu = hw.cpu_temp()
        igpu = hw.igpu_temp()
        self.cpu_temp_label.setText(f"{cpu:.0f} °C" if cpu else "—")
        self.igpu_temp_label.setText(f"{igpu:.0f} °C" if igpu else "—")
        self._poll_dgpu()
        if self._dgpu_temp is not None:
            self.dgpu_temp_label.setText(f"{self._dgpu_temp:.0f} °C")
        else:
            self.dgpu_temp_label.setText("asleep")

        self.graph.add_sample(cpu, igpu, self._dgpu_temp)

        # THERMAL WATCHDOG (fallback: the daemon owns this when running)
        if st.available and st.mode == "custom" and not hw.daemon_running():
            hot = max(
                t for t in (cpu, igpu, self._dgpu_temp, 0.0) if t is not None
            )
            if hot > hw.WATCHDOG_TEMP:
                self._set_fans(0, 0)
                self.status_note.setText(
                    f"Thermal watchdog: {hot:.0f} °C exceeded "
                    f"{hw.WATCHDOG_TEMP:.0f} °C. Fans put back on Auto."
                )

    def _poll_dgpu(self) -> None:
        """Read the dGPU temp only when it is already awake — polling it
        while suspended would keep waking it and drain the battery."""
        if not hw.dgpu_awake():
            self._dgpu_temp = None
            return
        if self._nvidia is not None:
            return
        self._nvidia = QProcess(self)
        self._nvidia.finished.connect(self._nvidia_done)
        self._nvidia.start(
            "nvidia-smi",
            ["--query-gpu=temperature.gpu", "--format=csv,noheader"],
        )

    def _nvidia_done(self, code: int, _status) -> None:
        if code == 0 and self._nvidia is not None:
            out = bytes(self._nvidia.readAllStandardOutput()).decode().strip()
            try:
                self._dgpu_temp = float(out)
            except ValueError:
                self._dgpu_temp = None
        else:
            self._dgpu_temp = None
        self._nvidia = None

    def _apply_mode(self, mode: str) -> None:
        if mode == "auto":
            self._set_fans(0, 0)
        elif mode == "max":
            self._set_fans(100, 100)
        else:
            self._custom_changed()
        self.refresh()

    def _custom_changed(self) -> None:
        self._set_fans(self.cpu_slider.value(), self.gpu_slider.value())
        self.refresh()

    def _set_fans(self, cpu: int, gpu: int) -> None:
        self.status_note.setText("")
        if hw.Fans.set_direct(cpu, gpu):
            return
        if self._pkexec is not None:
            return
        self.status_note.setText("Waiting for authorization…")
        cmd = hw.Fans.set_command(cpu, gpu)
        self._pkexec = QProcess(self)
        self._pkexec.finished.connect(self._pkexec_done)
        self._pkexec.start(cmd[0], cmd[1:])

    def _pkexec_done(self, code: int, _status) -> None:
        self._pkexec = None
        if code == 0:
            self.status_note.setText("")
        else:
            self.status_note.setText(
                "Authorization was cancelled. Fan settings were not changed."
            )
        self.refresh()
