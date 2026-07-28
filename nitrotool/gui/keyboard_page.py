"""Keyboard page: 4-zone RGB modes, colors, speed, brightness, profiles."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .. import hw
from .widgets import Card, ColorSwatch, ToggleSwitch, ZoneStrip

_log = logging.getLogger("keyboard")


class KeyboardPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = hw.Keyboard.load_last()
        self._suspend_apply = True   # don't fire while building the UI

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        title = QLabel("Keyboard")
        title.setProperty("class", "pagetitle")
        root.addWidget(title)

        # EFFECT MODE
        mode_card = Card("Effect")
        mode_grid = QGridLayout()
        mode_grid.setSpacing(8)
        self.mode_buttons: dict[int, QPushButton] = {}
        for column, (mode_id, name) in enumerate(hw.MODES.items()):
            button = QPushButton(name)
            button.setProperty("class", "mode")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(
                lambda _=False, m=mode_id: self._set_mode(m)
            )
            mode_grid.addWidget(button, 0, column)
            self.mode_buttons[mode_id] = button
        mode_card.add(mode_grid)
        root.addWidget(mode_card)

        # ZONES / COLOR
        self.zones_card = Card("Zone colors")
        self.zone_strip = ZoneStrip()
        self.zone_strip.zoneColorChanged.connect(self._zone_color_changed)
        self.zones_card.add(self.zone_strip)

        same_row = QHBoxLayout()
        same_label = QLabel("Use one color for all zones")
        same_label.setProperty("class", "muted")
        self.same_toggle = ToggleSwitch()
        self.same_toggle.toggled.connect(self._same_all_toggled)
        same_row.addWidget(same_label)
        same_row.addStretch(1)
        same_row.addWidget(self.same_toggle)
        self.zones_card.add(same_row)
        root.addWidget(self.zones_card)

        self.color_card = Card("Effect color")
        color_row = QHBoxLayout()
        self.effect_swatch = ColorSwatch(QColor(*self.state.color), size=52)
        self.effect_swatch.colorChanged.connect(self._effect_color_changed)
        color_hint = QLabel("Color used by this effect")
        color_hint.setProperty("class", "muted")
        color_row.addWidget(self.effect_swatch)
        color_row.addWidget(color_hint)
        color_row.addStretch(1)
        self.color_card.add(color_row)
        root.addWidget(self.color_card)

        self.temp_hint = Card("Temperature mode")
        temp_label = QLabel(
            "All four zones follow the CPU temperature. Blue when cool "
            "(45 °C or less), through green and yellow, to red when hot "
            "(80 °C or more). One sensor read every 3 seconds, so it "
            "barely touches the CPU. Set brightness to 0 to pause it and "
            "let the keyboard's own Fn keys control the backlight."
        )
        temp_label.setProperty("class", "muted")
        temp_label.setWordWrap(True)
        self.temp_hint.add(temp_label)
        root.addWidget(self.temp_hint)

        # SLIDERS
        tune_card = Card("Tuning")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(14)

        bright_label = QLabel("Brightness")
        self.brightness = QSlider(Qt.Horizontal)
        self.brightness.setRange(0, 100)
        self.brightness.valueChanged.connect(self._tune_changed)
        self.bright_value = QLabel("100")
        self.bright_value.setProperty("class", "muted")
        self.bright_value.setMinimumWidth(34)
        grid.addWidget(bright_label, 0, 0)
        grid.addWidget(self.brightness, 0, 1)
        grid.addWidget(self.bright_value, 0, 2)

        self.speed_label = QLabel("Speed")
        self.speed = QSlider(Qt.Horizontal)
        self.speed.setRange(1, 9)
        self.speed.valueChanged.connect(self._tune_changed)
        self.speed_value = QLabel("4")
        self.speed_value.setProperty("class", "muted")
        grid.addWidget(self.speed_label, 1, 0)
        grid.addWidget(self.speed, 1, 1)
        grid.addWidget(self.speed_value, 1, 2)

        self.dir_label = QLabel("Direction")
        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        self.dir_left = QPushButton("Right to left")
        self.dir_right = QPushButton("Left to right")
        for button in (self.dir_left, self.dir_right):
            button.setProperty("class", "mode")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
        self.dir_left.clicked.connect(lambda: self._set_direction(1))
        self.dir_right.clicked.connect(lambda: self._set_direction(2))
        dir_row.addWidget(self.dir_left)
        dir_row.addWidget(self.dir_right)
        dir_row.addStretch(1)
        grid.addWidget(self.dir_label, 2, 0)
        grid.addLayout(dir_row, 2, 1, 1, 2)

        grid.setColumnStretch(1, 1)
        tune_card.add(grid)
        root.addWidget(tune_card)

        # PROFILES
        profile_card = Card("Profiles")
        profile_row = QHBoxLayout()
        profile_row.setSpacing(8)
        self.profile_box = QComboBox()
        self.profile_box.setMinimumWidth(180)
        load_button = QPushButton("Load")
        self.save_button = QPushButton("Save as…")
        for button in (load_button, self.save_button):
            button.setProperty("class", "action")
            button.setCursor(Qt.PointingHandCursor)
        load_button.clicked.connect(self._load_profile)
        self.save_button.clicked.connect(self._save_profile)
        profile_row.addWidget(self.profile_box, 1)
        profile_row.addWidget(load_button)
        profile_row.addWidget(self.save_button)
        profile_card.add(profile_row)
        profile_hint = QLabel("Shared with the facer_rgb command-line tool.")
        profile_hint.setProperty("class", "muted")
        profile_card.add(profile_hint)
        root.addWidget(profile_card)

        # DRIVER-MISSING NOTICE
        self.notice = Card("Driver not loaded")
        notice_label = QLabel(
            "The keyboard driver (acer-kbd-rgb) is not loaded, so lighting "
            "control is unavailable. Enable it from the Setup page."
        )
        notice_label.setProperty("class", "muted")
        notice_label.setWordWrap(True)
        notice_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.notice.add(notice_label)
        root.addWidget(self.notice)

        root.addStretch(1)

        # debounce so slider drags don't flood the firmware
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(120)
        self._apply_timer.timeout.connect(self._apply_now)

        # Temp mode engine: one sysfs read every 3 s, writes only when the
        # color bucket actually changes — negligible CPU/memory.
        self._temp_timer = QTimer(self)
        self._temp_timer.setInterval(3000)
        self._temp_timer.timeout.connect(self._temp_tick)
        self._last_temp_color: tuple[int, int, int] | None = None

        self._load_state_into_controls()
        self._refresh_profiles()
        self._update_visibility()
        self._suspend_apply = False

        available = hw.Keyboard.driver_loaded()
        self.notice.setVisible(not available)
        if available:
            self._apply_now()   # restore last lighting on launch

    def _load_state_into_controls(self) -> None:
        st = self.state
        # Snapshot before touching widgets: setValue() fires valueChanged,
        # whose handler writes back into self.state mid-load.
        mode, speed, brightness = st.mode, st.speed, st.brightness
        direction, zones = st.direction, list(st.zones)
        for mode_id, button in self.mode_buttons.items():
            button.setChecked(mode_id == mode)
        self.zone_strip.set_colors(zones)
        self.effect_swatch.setColor(QColor(*st.color))
        self.brightness.setValue(brightness)
        self.speed.setValue(speed)
        self._set_direction_buttons(direction)
        st.mode, st.speed, st.brightness = mode, speed, brightness
        st.direction, st.zones = direction, zones
        self.bright_value.setText(str(brightness))
        self.speed_value.setText(str(speed))
        uniform = len(set(zones)) == 1
        self.same_toggle.setChecked(uniform)

    def _update_visibility(self) -> None:
        static = self.state.mode == 0
        temp = self.state.mode == hw.TEMP_MODE
        self.zones_card.setVisible(static)
        self.color_card.setVisible(self.state.mode in hw.COLOR_MODES and not static)
        self.temp_hint.setVisible(temp)
        animated = not static and not temp
        self.speed.setEnabled(animated)
        self.speed_label.setEnabled(animated)
        directional = self.state.mode in hw.DIRECTIONAL_MODES
        for w in (self.dir_label, self.dir_left, self.dir_right):
            w.setEnabled(directional)
        # profiles use the firmware format; Temp is app-driven
        self.save_button.setEnabled(not temp)
        # Temperature engine lifecycle. When the daemon is running it owns
        # this loop, so the GUI does not drive it too; the GUI only runs it
        # as a fallback when the daemon is absent.
        want = temp and not hw.daemon_running()
        if want and not self._temp_timer.isActive():
            self._last_temp_color = None
            self._temp_timer.start()
            self._temp_tick()
        elif not want and self._temp_timer.isActive():
            self._temp_timer.stop()
            self._last_temp_color = None

    def _set_direction_buttons(self, direction: int) -> None:
        self.dir_left.setChecked(direction == 1)
        self.dir_right.setChecked(direction == 2)

    # HANDLERS

    def _set_mode(self, mode: int) -> None:
        self.state.mode = mode
        for mode_id, button in self.mode_buttons.items():
            button.setChecked(mode_id == mode)
        self._update_visibility()
        self._schedule_apply()

    def _zone_color_changed(self, index: int, color: QColor) -> None:
        rgb = (color.red(), color.green(), color.blue())
        if self.same_toggle.isChecked():
            self.state.zones = [rgb] * 4
            self.zone_strip.set_colors(self.state.zones)
        else:
            self.state.zones[index] = rgb
        self._schedule_apply()

    def _same_all_toggled(self, on: bool) -> None:
        if on:
            first = self.state.zones[0]
            self.state.zones = [first] * 4
            self.zone_strip.set_colors(self.state.zones)
            self._schedule_apply()

    def _effect_color_changed(self, color: QColor) -> None:
        self.state.color = (color.red(), color.green(), color.blue())
        self._schedule_apply()

    def _tune_changed(self) -> None:
        self.state.brightness = self.brightness.value()
        self.state.speed = self.speed.value()
        self.bright_value.setText(str(self.state.brightness))
        self.speed_value.setText(str(self.state.speed))
        self._schedule_apply()

    def _set_direction(self, direction: int) -> None:
        self.state.direction = direction
        self._set_direction_buttons(direction)
        self._schedule_apply()

    # PROFILES

    def _refresh_profiles(self) -> None:
        self.profile_box.clear()
        self.profile_box.addItems(hw.Keyboard.list_profiles())

    def _load_profile(self) -> None:
        name = self.profile_box.currentText()
        if not name:
            return
        state = hw.Keyboard.load_profile(name)
        if state is None:
            return
        self.state = state
        self._suspend_apply = True
        self._load_state_into_controls()
        self._update_visibility()
        self._suspend_apply = False
        self._schedule_apply()

    def _save_profile(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Save profile", "Profile name:"
        )
        if not ok or not name.strip():
            return
        hw.Keyboard.save_profile(name.strip(), self.state)
        self._refresh_profiles()
        self.profile_box.setCurrentText(name.strip())

    # APPLY

    def _schedule_apply(self) -> None:
        if not self._suspend_apply:
            self._apply_timer.start()

    def _apply_now(self) -> None:
        if not hw.Keyboard.driver_loaded():
            return
        if self.state.mode == hw.TEMP_MODE:
            # brightness or mode changed: force the engine to resend
            self._last_temp_color = None
            self._temp_tick()
        else:
            hw.Keyboard.apply(self.state)
        hw.Keyboard.save_last(self.state)

    def _temp_tick(self) -> None:
        if not hw.Keyboard.driver_loaded():
            return
        # Brightness 0 means hands off: keep the engine from forcing the
        # backlight dark and fighting the EC's Fn+F9/F10 keys.
        if self.state.brightness == 0:
            self._last_temp_color = None
            return
        temp = hw.cpu_temp()
        if temp is None:
            return
        bucket = round(temp / 2) * 2   # 2 °C steps -> fewer writes
        color = hw.temp_to_color(bucket)
        if (color, self.state.brightness) != self._last_temp_color:
            if hw.Keyboard.set_all_zones(color, self.state.brightness):
                self._last_temp_color = (color, self.state.brightness)
                _log.info("Temp mode: %.0f °C -> #%02x%02x%02x "
                          "brightness=%d", temp, *color,
                          self.state.brightness)
