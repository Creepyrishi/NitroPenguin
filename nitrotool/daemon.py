"""NitroPenguin background daemon.

Pure-stdlib, Qt-free (~15-20 MB). Owns the always-on work so the GUI can
open on demand and fully quit on close:

  - Temp keyboard mode: zones follow the CPU temperature
  - Fan thermal watchdog: revert to Auto above the safety limit
  - 80% battery-limit notification
  - Re-apply the last keyboard effect on start (RGB is volatile firmware)
  - Nitro key: open the GUI when the physical key is pressed

Runs as a systemd --user service. Reuses nitrotool.hw for all hardware
access; imports no GUI code.
"""

from __future__ import annotations

import os
import select
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path

from nitrotool import hw

POLL_SECONDS = 3.0
BATTERY_POLL_SECONDS = 5.0
HOTKEY_DEVICE_NAME = "Acer WMI hotkeys"

# linux/input.h: struct input_event = timeval + type + code + value.
# On 64-bit, timeval is 16 bytes -> 24-byte record, "llHHi".
_EVENT_FORMAT = "llHHi"
_EVENT_SIZE = struct.calcsize(_EVENT_FORMAT)
EV_KEY = 0x01


def _notify(title: str, body: str, icon: str = "nitropenguin") -> None:
    try:
        subprocess.Popen(
            ["notify-send", "-i", icon, title, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def _find_hotkey_event_device(name: str) -> str | None:
    """Resolve /dev/input/eventN for a device by name, robust to the
    kernel renumbering event devices between boots."""
    try:
        text = Path("/proc/bus/input/devices").read_text()
    except OSError:
        return None
    for block in text.split("\n\n"):
        if f'Name="{name}"' in block:
            for token in block.replace("=", " ").split():
                if token.startswith("event"):
                    return f"/dev/input/{token}"
    return None


class Daemon:
    def __init__(self) -> None:
        self._running = True
        self._last_kbd_color: tuple[int, int, int] | None = None
        self._battery_held = False
        self._last_battery_poll = 0.0
        self._hotkey_fd: int | None = None
        self._gui: subprocess.Popen | None = None

    # ----- lifecycle -----

    def start(self) -> None:
        hw.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        hw.PIDFILE.write_text(str(os.getpid()))
        signal.signal(signal.SIGTERM, self._stop)
        signal.signal(signal.SIGINT, self._stop)
        self._open_hotkey()
        self._reapply_keyboard()
        try:
            self._loop()
        finally:
            self._cleanup()

    def _stop(self, *_a) -> None:
        self._running = False

    def _cleanup(self) -> None:
        if self._hotkey_fd is not None:
            try:
                os.close(self._hotkey_fd)
            except OSError:
                pass
        try:
            if hw.PIDFILE.read_text().strip() == str(os.getpid()):
                hw.PIDFILE.unlink()
        except (OSError, ValueError):
            pass

    # ----- hotkey -----

    def _open_hotkey(self) -> None:
        dev = _find_hotkey_event_device(HOTKEY_DEVICE_NAME)
        if not dev:
            return
        try:
            self._hotkey_fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            # No read permission (user not in the 'input' group): the
            # GNOME shortcut path handles the key instead.
            self._hotkey_fd = None

    def _read_hotkey(self) -> None:
        if self._hotkey_fd is None:
            return
        try:
            data = os.read(self._hotkey_fd, _EVENT_SIZE * 64)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            self._hotkey_fd = None
            return
        for i in range(0, len(data) - _EVENT_SIZE + 1, _EVENT_SIZE):
            _s, _us, etype, _code, value = struct.unpack_from(
                _EVENT_FORMAT, data, i
            )
            # Any key-down on this device is the Nitro/hotkey press.
            if etype == EV_KEY and value == 1:
                self._launch_gui()

    def _launch_gui(self) -> None:
        if self._gui is not None and self._gui.poll() is None:
            return  # already open
        launcher = hw.GUI_LAUNCHER
        if not launcher.exists():
            return
        try:
            self._gui = subprocess.Popen([str(launcher)])
        except OSError:
            pass

    # ----- hardware loops -----

    def _reapply_keyboard(self) -> None:
        if not hw.Keyboard.driver_loaded():
            return
        state = hw.Keyboard.load_last()
        if state.mode == hw.TEMP_MODE:
            self._tick_keyboard(state)
        else:
            hw.Keyboard.apply(state)

    def _tick_keyboard(self, state=None) -> None:
        if not hw.Keyboard.driver_loaded():
            return
        if state is None:
            state = hw.Keyboard.load_last()
        if state.mode != hw.TEMP_MODE:
            self._last_kbd_color = None
            return
        temp = hw.cpu_temp()
        if temp is None:
            return
        bucket = round(temp / 2) * 2
        color = hw.temp_to_color(bucket)
        if color != self._last_kbd_color:
            if hw.Keyboard.set_all_zones(color, state.brightness):
                self._last_kbd_color = color

    def _tick_fan_watchdog(self) -> None:
        if not hw.Fans.driver_loaded():
            return
        state = hw.Fans.read()
        if state.mode != "custom":
            return
        temps = [hw.cpu_temp(), hw.igpu_temp()]
        if hw.dgpu_awake():
            temps.append(self._dgpu_temp())
        hot = max((t for t in temps if t is not None), default=0.0)
        if hot > hw.WATCHDOG_TEMP:
            hw.Fans.set_direct(0, 0)
            _notify(
                "NitroPenguin",
                f"{hot:.0f} °C exceeded {hw.WATCHDOG_TEMP:.0f} °C. "
                "Fans put back on Auto.",
            )

    @staticmethod
    def _dgpu_temp() -> float | None:
        try:
            out = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=temperature.gpu", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            )
            return float(out.stdout.strip())
        except (OSError, ValueError, subprocess.SubprocessError):
            return None

    def _tick_battery(self) -> None:
        state = hw.Battery.read()
        if state.held_at_limit and not self._battery_held:
            _notify(
                "NitroPenguin",
                "Charging stopped at 80%. The limiter is keeping your "
                "battery topped up, not full.",
                icon="battery-good-charging",
            )
        self._battery_held = state.held_at_limit

    # ----- main loop -----

    def _loop(self) -> None:
        while self._running:
            rlist = [self._hotkey_fd] if self._hotkey_fd is not None else []
            try:
                ready, _, _ = select.select(rlist, [], [], POLL_SECONDS)
            except InterruptedError:
                continue
            if ready:
                self._read_hotkey()
                continue  # a keypress woke us; skip the poll this pass
            # timed out: run the periodic hardware work
            self._tick_keyboard()
            self._tick_fan_watchdog()
            now = time.monotonic()
            if now - self._last_battery_poll >= BATTERY_POLL_SECONDS:
                self._last_battery_poll = now
                self._tick_battery()


def main() -> int:
    Daemon().start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
