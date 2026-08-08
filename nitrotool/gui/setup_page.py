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
            "stale": "Needs loading",
        }.get(self.status, "Not loaded")
        chip_kind = component.chip_kind
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

        # Recovery row: installed drivers missing from the running kernel
        # (a kernel update booted before DKMS finished rebuilding them).
        self.load_widget = QWidget()
        load_row = QHBoxLayout(self.load_widget)
        load_row.setContentsMargins(0, 0, 0, 0)
        load_col = QVBoxLayout()
        load_col.setSpacing(2)
        load_title = QLabel("Load the installed drivers")
        load_title.setStyleSheet("font-size: 14px;")
        load_sub = QLabel(
            "These are already installed, they are just not in the running "
            "kernel — usually because a kernel update rebuilt them after "
            "this boot. Loading them now fixes it until the next reboot, "
            "which will then pick them up on its own."
        )
        load_sub.setProperty("class", "muted")
        load_sub.setWordWrap(True)
        load_col.addWidget(load_title)
        load_col.addWidget(load_sub)
        load_row.addLayout(load_col, 1)
        self.load_button = QPushButton("Load now")
        self.load_button.setProperty("class", "primary")
        self.load_button.setCursor(Qt.PointingHandCursor)
        self.load_button.clicked.connect(self._load_installed)
        load_row.addWidget(self.load_button, 0, Qt.AlignVCenter)
        actions_card.add(self.load_widget)

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
        stale = [k for k, c in comps.items() if c.status == "stale"]
        self.load_widget.setVisible(bool(stale))
        if all(s == "permanent" for s in statuses):
            self.summary.setText(
                "Everything is installed permanently. The drivers load "
                "on their own at every boot."
            )
        elif stale:
            self.summary.setText(
                "Some drivers are installed but not running right now. This "
                "normally means a kernel update landed and the new kernel "
                "booted before the drivers had been rebuilt for it. Use "
                "\"Load now\" below — no reinstall needed."
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
        self.load_button.setEnabled(not busy)
        self.try_button.setEnabled(not busy)
        self.install_button.setEnabled(not busy)
        self.remove_button.setEnabled(not busy)

    def _selected(self, exclude_status: str | None = None) -> list[str]:
        return [
            row.key for row in self.rows
            if row.checkbox.isChecked() and row.status != exclude_status
        ]

    def _load_installed(self) -> None:
        # Every stale component, regardless of the checkboxes: this is a
        # repair, and leaving half the drivers unloaded helps nobody.
        keys = [row.key for row in self.rows if row.status == "stale"]
        if keys:
            self._run(hw.load_installed_command(keys))

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
