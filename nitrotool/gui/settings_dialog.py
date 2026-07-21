"""Settings dialog: theme, per-component install/remove, full uninstall,
about & credits."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QProcess, Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import hw
from . import theme


def _section(layout: QVBoxLayout, title: str) -> None:
    label = QLabel(title.upper())
    label.setProperty("class", "cardtitle")
    layout.addSpacing(6)
    layout.addWidget(label)


class SettingsDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main = main_window
        self._proc: QProcess | None = None
        self.setWindowTitle("Settings")
        # Fixed-size utility dialog: no maximize, no fullscreen stretch.
        self.setWindowFlags(
            Qt.Dialog
            | Qt.CustomizeWindowHint
            | Qt.WindowTitleHint
            | Qt.WindowCloseButtonHint
        )
        self.setFixedWidth(620)
        self.setSizeGripEnabled(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(10)

        # THEME
        _section(root, "Theme")
        theme_row = QHBoxLayout()
        theme_row.setSpacing(8)
        self.theme_buttons: dict[str, QPushButton] = {}
        for key, label in (("dark", "Dark"), ("light", "Light"),
                           ("auto", "Auto (match system)")):
            button = QPushButton(label)
            button.setProperty("class", "mode")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _=False, k=key: self._pick_theme(k))
            theme_row.addWidget(button)
            self.theme_buttons[key] = button
        theme_row.addStretch(1)
        root.addLayout(theme_row)
        self._sync_theme_buttons()

        # COMPONENTS
        _section(root, "Components")
        comp_hint = QLabel(
            "Install only what you need. You can add the rest here later. "
            "Install and Make permanent both survive reboots and kernel "
            "updates. Remove puts that driver back to stock."
        )
        comp_hint.setProperty("class", "muted")
        comp_hint.setWordWrap(True)
        root.addWidget(comp_hint)

        self.comp_container = QWidget()
        self.comp_layout = QVBoxLayout(self.comp_container)
        self.comp_layout.setContentsMargins(0, 4, 0, 0)
        self.comp_layout.setSpacing(10)
        root.addWidget(self.comp_container)

        self.status_note = QLabel("")
        self.status_note.setProperty("class", "muted")
        self.status_note.setWordWrap(True)
        root.addWidget(self.status_note)

        # DANGER ZONE + ABOUT
        _section(root, "Everything")
        wipe_row = QHBoxLayout()
        wipe_hint = QLabel("Remove all drivers and boot configuration.")
        wipe_hint.setProperty("class", "muted")
        wipe_row.addWidget(wipe_hint, 1)
        self.wipe_button = QPushButton("Uninstall everything…")
        self.wipe_button.setProperty("class", "action")
        self.wipe_button.setCursor(Qt.PointingHandCursor)
        self.wipe_button.clicked.connect(self._uninstall_all)
        wipe_row.addWidget(self.wipe_button)
        root.addLayout(wipe_row)

        _section(root, "About")
        link_style = f"style='color:{theme.ACCENT}'"
        about = QLabel(
            "NitroPenguin v0.1.0. NitroSense features for the Acer "
            "Nitro 5 (AN515-45) on Linux.<br><br>"
            "This app builds on the reverse-engineering work of three "
            "community projects (all GPL-2.0):<br>"
            f"•  <a {link_style} "
            "href='https://github.com/frederik-h/acer-wmi-battery'>"
            "acer-wmi-battery</a> by Frederik Harwath<br>"
            f"•  <a {link_style} href='https://github.com/JafarAkhondali/"
            "acer-predator-turbo-and-rgb-keyboard-linux-module'>"
            "acer-predator-turbo-rgb-keyboard</a> by Jafar Akhondali "
            "&amp; contributors<br>"
            f"•  <a {link_style} "
            "href='https://github.com/0x7375646F/Linuwu-Sense'>"
            "Linuwu-Sense</a> by 0x7375646F"
        )
        about.setTextFormat(Qt.RichText)
        about.setOpenExternalLinks(True)
        about.setWordWrap(True)
        about.setProperty("class", "muted")
        root.addWidget(about)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_button = QPushButton("Close")
        close_button.setProperty("class", "primary")
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        root.addLayout(close_row)

        self._rebuild_components()
        # Lock height to the content so the window can't be stretched.
        self.adjustSize()
        self.setFixedHeight(self.height())

    def changeEvent(self, event: QEvent) -> None:
        # GNOME/Mutter draws its own title bar and ignores Qt's
        # "no maximize" hint, so if the WM maximizes us anyway, snap
        # straight back to the normal fixed size.
        if event.type() == QEvent.WindowStateChange:
            if self.windowState() & (Qt.WindowMaximized | Qt.WindowFullScreen):
                self.setWindowState(Qt.WindowNoState)
        super().changeEvent(event)

    def _pick_theme(self, pref: str) -> None:
        self.main.apply_theme_pref(pref)
        self._sync_theme_buttons()

    def _sync_theme_buttons(self) -> None:
        for key, button in self.theme_buttons.items():
            button.setChecked(key == self.main.theme_pref)

    def _rebuild_components(self) -> None:
        while self.comp_layout.count():
            item = self.comp_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        busy = self._proc is not None
        self.wipe_button.setEnabled(not busy)
        for component in hw.components():
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(10)

            col = QVBoxLayout()
            col.setSpacing(1)
            name = QLabel(component.name)
            desc = QLabel(component.description)
            desc.setProperty("class", "muted")
            col.addWidget(name)
            col.addWidget(desc)
            row_layout.addLayout(col, 1)

            chip = QLabel({
                "permanent": "Permanent",
                "temporary": "Temporary",
                "off": "Not installed",
            }[component.status])
            chip.setProperty("class", "chip")
            chip.setProperty("chip", {
                "permanent": "ok", "temporary": "temp", "off": "off",
            }[component.status])
            row_layout.addWidget(chip)

            if component.status == "off":
                install = QPushButton("Install")
                install.setProperty("class", "primary")
                install.clicked.connect(
                    lambda _=False, k=component.key:
                    self._run(hw.install_command([k]))
                )
                install.setEnabled(not busy)
                row_layout.addWidget(install)
            elif component.status == "temporary":
                make_perm = QPushButton("Make permanent")
                make_perm.setProperty("class", "primary")
                make_perm.clicked.connect(
                    lambda _=False, k=component.key:
                    self._run(hw.install_command([k]))
                )
                make_perm.setEnabled(not busy)
                row_layout.addWidget(make_perm)
            if component.status != "off":
                remove = QPushButton("Remove")
                remove.setProperty("class", "action")
                remove.clicked.connect(
                    lambda _=False, k=component.key:
                    self._run(hw.uninstall_command([k]))
                )
                remove.setEnabled(not busy)
                row_layout.addWidget(remove)

            self.comp_layout.addWidget(row)

    def _run(self, cmd: list[str]) -> None:
        if self._proc is not None:
            return
        self.status_note.setText("Working. You may be asked for a password…")
        self._proc = QProcess(self)
        self._proc.finished.connect(self._done)
        self._proc.start(cmd[0], cmd[1:])
        self._rebuild_components()

    def _done(self, code: int, _status) -> None:
        self._proc = None
        if code == 0:
            self.status_note.setText("Done.")
        elif code in (126, 127):
            self.status_note.setText("Authorization was cancelled.")
        else:
            self.status_note.setText(f"Failed (exit code {code}).")
        self._rebuild_components()
        self.main.refresh_after_setup_change()

    def _uninstall_all(self) -> None:
        keys = [c.key for c in hw.components() if c.loaded or c.installed]
        if not keys:
            self.status_note.setText("Nothing is installed.")
            return
        answer = QMessageBox.question(
            self,
            "Uninstall everything?",
            "This removes all NitroPenguin drivers (battery limiter, "
            "keyboard RGB, fan control) and their boot configuration.\n\n"
            "Your system will be exactly as it was before this project. "
            "The stock drivers were never modified.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer == QMessageBox.Yes:
            self._run(hw.uninstall_command(keys))
