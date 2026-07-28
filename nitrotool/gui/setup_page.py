"""Setup page: temporary vs permanent driver installation.

Workflow for a new machine: tick components -> "Try temporarily" ->
test everything in the app -> come back -> "Install permanently".
Nothing touches the system without an explicit action + system password.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import hw
from .widgets import Card

_log = logging.getLogger("setup")


class ComponentRow(QWidget):
    def __init__(self, component: hw.Component, parent=None):
        super().__init__(parent)
        self.key = component.key
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        self.checkbox = QCheckBox()
        row.addWidget(self.checkbox)

        col = QVBoxLayout()
        col.setSpacing(2)
        name_label = QLabel(component.name)
        name_label.setStyleSheet("font-size: 14px;")
        desc_label = QLabel(component.description)
        desc_label.setProperty("class", "muted")
        col.addWidget(name_label)
        col.addWidget(desc_label)
        row.addLayout(col, 1)

        self.chip = QLabel()
        self.chip.setProperty("class", "chip")
        row.addWidget(self.chip, 0, Qt.AlignVCenter)

        self.update_status(component)

    def update_status(self, component: hw.Component) -> None:
        self.status = component.status
        text = {
            "permanent": "Permanent",
            "temporary": "Temporary",
            "off": "Not loaded",
        }[self.status]
        chip_kind = {
            "permanent": "ok", "temporary": "temp", "off": "off",
        }[self.status]
        self.chip.setText(text)
        self.chip.setProperty("chip", chip_kind)
        # re-polish so the [chip=...] style refreshes
        self.chip.style().unpolish(self.chip)
        self.chip.style().polish(self.chip)
        # default selection once: whatever is not yet permanent
        if not getattr(self, "_default_set", False):
            self.checkbox.setChecked(self.status != "permanent")
            self._default_set = True


class SetupPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._process: QProcess | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        title = QLabel("Setup")
        title.setProperty("class", "pagetitle")
        root.addWidget(title)

        self.summary = QLabel()
        self.summary.setProperty("class", "muted")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        # COMPONENTS
        comp_card = Card("Components")
        self.rows: list[ComponentRow] = []
        for component in hw.components():
            row = ComponentRow(component)
            comp_card.add(row)
            self.rows.append(row)
        root.addWidget(comp_card)

        # ACTIONS
        actions_card = Card("Actions")

        try_row = QHBoxLayout()
        try_col = QVBoxLayout()
        try_col.setSpacing(2)
        try_title = QLabel("Try temporarily")
        try_title.setStyleSheet("font-size: 14px;")
        try_sub = QLabel(
            "Loads the selected drivers for this session only. A reboot "
            "removes them. Test everything this way first."
        )
        try_sub.setProperty("class", "muted")
        try_sub.setWordWrap(True)
        try_col.addWidget(try_title)
        try_col.addWidget(try_sub)
        try_row.addLayout(try_col, 1)
        self.try_button = QPushButton("Load temporarily")
        self.try_button.setProperty("class", "action")
        self.try_button.setCursor(Qt.PointingHandCursor)
        self.try_button.clicked.connect(self._try_temp)
        try_row.addWidget(self.try_button, 0, Qt.AlignVCenter)
        actions_card.add(try_row)

        install_row = QHBoxLayout()
        install_col = QVBoxLayout()
        install_col.setSpacing(2)
        install_title = QLabel("Install permanently")
        install_title.setStyleSheet("font-size: 14px;")
        install_sub = QLabel(
            "Registers the selected drivers with DKMS so they survive "
            "reboots and kernel updates, and turns them on at every boot. "
            "You can undo this with the uninstall scripts in driver/."
        )
        install_sub.setProperty("class", "muted")
        install_sub.setWordWrap(True)
        install_col.addWidget(install_title)
        install_col.addWidget(install_sub)
        install_row.addLayout(install_col, 1)
        self.install_button = QPushButton("Install permanently")
        self.install_button.setProperty("class", "primary")
        self.install_button.setCursor(Qt.PointingHandCursor)
        self.install_button.clicked.connect(self._install)
        install_row.addWidget(self.install_button, 0, Qt.AlignVCenter)
        actions_card.add(install_row)

        remove_row = QHBoxLayout()
        remove_col = QVBoxLayout()
        remove_col.setSpacing(2)
        remove_title = QLabel("Uninstall")
        remove_title.setStyleSheet("font-size: 14px;")
        remove_sub = QLabel(
            "Removes the selected drivers. Modules are unloaded and the "
            "boot and DKMS entries are deleted. The system goes back to "
            "how it was before this project."
        )
        remove_sub.setProperty("class", "muted")
        remove_sub.setWordWrap(True)
        remove_col.addWidget(remove_title)
        remove_col.addWidget(remove_sub)
        remove_row.addLayout(remove_col, 1)
        self.remove_button = QPushButton("Uninstall")
        self.remove_button.setProperty("class", "action")
        self.remove_button.setCursor(Qt.PointingHandCursor)
        self.remove_button.clicked.connect(self._uninstall)
        remove_row.addWidget(self.remove_button, 0, Qt.AlignVCenter)
        actions_card.add(remove_row)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(160)
        self.log.hide()
        actions_card.add(self.log)

        root.addWidget(actions_card)
        root.addStretch(1)

        self.refresh()

    def refresh(self) -> None:
        comps = {c.key: c for c in hw.components()}
        for row in self.rows:
            row.update_status(comps[row.key])

        statuses = [c.status for c in comps.values()]
        if all(s == "permanent" for s in statuses):
            self.summary.setText(
                "Everything is installed permanently. The drivers load "
                "on their own at every boot."
            )
        elif any(s == "temporary" for s in statuses):
            self.summary.setText(
                "You are in temporary mode: the drivers work now but will "
                "be gone after a reboot. When you are happy everything "
                "works, install them permanently below."
            )
        else:
            self.summary.setText(
                "Drivers are not loaded. Pick what you want and try it "
                "temporarily first. Nothing survives a reboot until you "
                "install it."
            )

        busy = self._process is not None
        self.try_button.setEnabled(not busy)
        self.install_button.setEnabled(not busy)
        self.remove_button.setEnabled(not busy)

    def _selected(self, exclude_status: str | None = None) -> list[str]:
        return [
            row.key for row in self.rows
            if row.checkbox.isChecked() and row.status != exclude_status
        ]

    def _try_temp(self) -> None:
        keys = self._selected(exclude_status="permanent")
        if keys:
            self._run(hw.load_temp_command(keys))

    def _install(self) -> None:
        keys = self._selected(exclude_status="permanent")
        if keys:
            self._run(hw.install_command(keys))

    def _uninstall(self) -> None:
        keys = self._selected(exclude_status="off")
        if keys:
            self._run(hw.uninstall_command(keys))

    def _run(self, cmd: list[str]) -> None:
        _log.info("Driver action: %s", " ".join(cmd))
        self.log.show()
        self.log.appendPlainText(f"$ {' '.join(cmd[3:] if len(cmd) > 3 else cmd)}")
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.MergedChannels)
        self._process.readyReadStandardOutput.connect(
            lambda: self.log.appendPlainText(
                bytes(self._process.readAllStandardOutput()).decode(errors="replace").rstrip()
            )
        )
        self._process.finished.connect(self._done)
        self._process.start(cmd[0], cmd[1:])
        self.refresh()

    def _done(self, code: int, _status) -> None:
        self._process = None
        if code == 0:
            _log.info("Driver action finished ok")
            self.log.appendPlainText("Done.")
        elif code in (126, 127):
            _log.warning("Driver action: authorization cancelled")
            self.log.appendPlainText("Authorization was cancelled.")
        else:
            _log.warning("Driver action failed (exit code %d)", code)
            self.log.appendPlainText(f"Failed (exit code {code}).")
        self.refresh()
