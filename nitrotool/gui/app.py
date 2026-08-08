"""NitroPenguin main window."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import applog, hw
from . import theme
from .battery_page import BatteryPage
from .fans_page import FansPage
from .keyboard_page import KeyboardPage
from .settings_dialog import SettingsDialog
from .setup_page import SetupPage


def resolve_theme(pref: str) -> str:
    """Map a preference (dark/light/auto) to a concrete palette name."""
    if pref in ("dark", "light"):
        return pref
    scheme = QApplication.styleHints().colorScheme()
    return "light" if scheme == Qt.ColorScheme.Light else "dark"

CONTENT_MAX_WIDTH = 880


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NitroPenguin")
        self.setMinimumSize(760, 560)
        self.resize(960, 640)

        root = QWidget()
        root.setObjectName("root")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # SIDEBAR
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(210)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(16, 20, 16, 16)
        side_layout.setSpacing(4)

        brand = QLabel("NITROPENGUIN")
        brand.setObjectName("brand")
        brand_sub = QLabel("Nitro 5 · AN515-45")
        brand_sub.setObjectName("brandsub")
        side_layout.addWidget(brand)
        side_layout.addWidget(brand_sub)
        side_layout.addSpacing(20)

        # CONTENT COLUMN: BANNER ABOVE THE PAGE STACK
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.banner = QFrame()
        self.banner.setObjectName("banner")
        banner_layout = QHBoxLayout(self.banner)
        banner_layout.setContentsMargins(16, 8, 16, 8)
        self.banner_label = QLabel()
        self.banner_label.setProperty("class", "muted")
        banner_button = QPushButton("Open Setup")
        banner_button.setProperty("class", "action")
        banner_button.setCursor(Qt.PointingHandCursor)
        banner_button.clicked.connect(lambda: self._navigate(3))
        banner_layout.addWidget(self.banner_label, 1)
        banner_layout.addWidget(banner_button)
        content_layout.addWidget(self.banner)

        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, 1)

        self.setup_page = SetupPage()
        self.nav_buttons: list[QPushButton] = []
        pages = (
            ("Battery", BatteryPage()),
            ("Keyboard", KeyboardPage()),
            ("Fans", FansPage()),
            ("Setup", self.setup_page),
        )
        for index, (label, page) in enumerate(pages):
            self.stack.addWidget(self._wrap_page(page))
            button = QPushButton(label)
            button.setProperty("class", "nav")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _=False, i=index: self._navigate(i))
            side_layout.addWidget(button)
            self.nav_buttons.append(button)

        side_layout.addStretch(1)

        # LIVE TEMPS IN THE SIDEBAR
        self.side_temps = QLabel("CPU —   ·   GPU —")
        self.side_temps.setProperty("class", "muted")
        self.side_temps.setStyleSheet("font-size: 12px; padding: 4px 4px 10px 4px;")
        side_layout.addWidget(self.side_temps)
        self._temps_timer = QTimer(self)
        self._temps_timer.timeout.connect(self._refresh_side_temps)
        self._temps_timer.start(3000)
        self._refresh_side_temps()

        # FOOTER: VERSION + SETTINGS
        footer_row = QHBoxLayout()
        version_label = QLabel("v0.1.0")
        version_label.setProperty("class", "muted")
        version_label.setStyleSheet("font-size: 11px; padding: 6px 0 0 4px;")
        footer_row.addWidget(version_label)
        footer_row.addStretch(1)
        settings_button = QPushButton("⚙")
        settings_button.setProperty("class", "action")
        settings_button.setFixedSize(28, 28)
        settings_button.setStyleSheet(
            "border-radius: 14px; padding: 0; font-size: 15px;"
        )
        settings_button.setCursor(Qt.PointingHandCursor)
        settings_button.setToolTip("Settings")
        settings_button.clicked.connect(self._show_settings)
        footer_row.addWidget(settings_button)
        side_layout.addLayout(footer_row)

        layout.addWidget(sidebar)
        layout.addWidget(content, 1)
        self.setCentralWidget(root)

        self.theme_pref = theme.load_saved_theme()
        self.apply_theme_pref(self.theme_pref, save=False)
        QApplication.styleHints().colorSchemeChanged.connect(
            self._system_scheme_changed
        )

        self.setWindowIcon(
            QIcon(str(hw.PROJECT_DIR / "assets" / "nitropenguin.svg"))
        )

        self._navigate(0)
        self._refresh_banner()
        self._banner_timer = QTimer(self)
        self._banner_timer.timeout.connect(self._refresh_banner)
        self._banner_timer.start(4000)

    @staticmethod
    def _wrap_page(page: QWidget) -> QScrollArea:
        """Scrollable, with content width capped so huge windows keep
        readable line lengths instead of stretching cards edge to edge."""
        page.setMaximumWidth(CONTENT_MAX_WIDTH)
        page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        holder = QWidget()
        holder.setObjectName("page")
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.addStretch(1)
        holder_layout.addWidget(page)
        holder_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setWidget(holder)
        return scroll

    def _navigate(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)
        if index == 3:
            self.setup_page.refresh()
        self._refresh_banner()

    def _refresh_side_temps(self) -> None:
        cpu = hw.cpu_temp()
        gpu = hw.igpu_temp()
        cpu_s = f"{cpu:.0f}°" if cpu else "—"
        gpu_s = f"{gpu:.0f}°" if gpu else "—"
        self.side_temps.setText(f"CPU {cpu_s}   ·   GPU {gpu_s}")

    def _refresh_banner(self) -> None:
        comps = hw.components()
        temp = [c for c in comps if c.status == "temporary"]
        stale = [c for c in comps if c.status == "stale"]

        # Setup tab shows while there is a pending decision: something in
        # temporary mode, drivers installed but not loaded, or a first run
        # with nothing set up at all. Partial installs are a valid end
        # state; adding or removing components later happens in Settings.
        first_run = all(c.status == "off" for c in comps)
        show_setup = bool(temp) or bool(stale) or first_run
        self.nav_buttons[3].setVisible(show_setup)
        if not show_setup and self.stack.currentIndex() == 3:
            self._navigate(0)

        if stale:
            self.banner_label.setText(
                "Drivers are installed but not loaded, so nothing works "
                "right now — usually a kernel update. Open Setup and press "
                "\"Load now\" to fix it."
            )
            self.banner.setVisible(self.stack.currentIndex() != 3)
        elif temp:
            self.banner_label.setText(
                "Temporary mode. Drivers are active until reboot. "
                "Install them permanently once you're happy."
            )
            self.banner.setVisible(self.stack.currentIndex() != 3)
        else:
            self.banner.setVisible(False)

    def _show_settings(self) -> None:
        SettingsDialog(self).exec()

    def refresh_after_setup_change(self) -> None:
        """Called by the settings dialog after an install/remove."""
        self._refresh_banner()
        self.setup_page.refresh()

    def apply_theme_pref(self, pref: str, save: bool = True) -> None:
        self.theme_pref = pref
        theme.set_theme(resolve_theme(pref))
        if save:
            theme.save_theme(pref)
        QApplication.instance().setStyleSheet(theme.build_qss())
        for widget in QApplication.allWidgets():
            widget.update()

    def _system_scheme_changed(self) -> None:
        if self.theme_pref == "auto":
            self.apply_theme_pref("auto", save=False)


def main() -> int:
    applog.setup("gui")
    logging.getLogger("app").info(
        "GUI opened (daemon running: %s)", hw.daemon_running()
    )
    app = QApplication(sys.argv)
    app.setApplicationName("NitroPenguin")
    app.setDesktopFileName("nitropenguin")
    app.setStyleSheet(theme.build_qss())
    window = MainWindow()
    window.show()
    code = app.exec()
    logging.getLogger("app").info("GUI closed")
    return code
