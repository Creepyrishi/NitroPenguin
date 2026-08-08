"""Hardware backend for NitroPenguin.

Battery: acer-wmi-battery kernel module (sysfs driver attributes).
Keyboard: acer-kbd-rgb kernel module (character devices, payload format
identical to the community facer driver).

Every read degrades gracefully: if a driver is not loaded the feature
reports unavailable and the GUI shows how to enable it instead of failing.
"""

from __future__ import annotations

import colorsys
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

_log = logging.getLogger("hw")

HEALTH_MODE = Path("/sys/bus/wmi/drivers/acer-wmi-battery/health_mode")
BAT_TEMP = Path("/sys/bus/wmi/drivers/acer-wmi-battery/temperature")
BAT = Path("/sys/class/power_supply/BAT1")
AC = Path("/sys/class/power_supply/ACAD")

KBD_DYNAMIC = Path("/dev/acer-gkbbl-0")
KBD_STATIC = Path("/dev/acer-gkbbl-static-0")

CONFIG_DIR = Path.home() / ".config" / "nitrotool"
PROJECT_DIR = Path(__file__).resolve().parent.parent
DRIVER_DIR = PROJECT_DIR / "driver"
GUI_LAUNCHER = PROJECT_DIR / ".venv" / "bin" / "nitropenguin"
PIDFILE = CONFIG_DIR / "daemon.pid"
# Same directory/format the community facer_rgb.py tool uses, so profiles
# saved in either tool show up in both.
FACER_PROFILE_DIR = Path.home() / ".config" / "predator" / "saved profiles"


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def daemon_running() -> bool:
    """True if the background daemon is alive (checked via its pidfile).

    The GUI uses this to avoid double-driving the hardware: when the
    daemon owns the always-on loops, the GUI's own copies stay off.
    """
    try:
        pid = int(PIDFILE.read_text().strip())
    except (OSError, ValueError):
        return False
    return Path(f"/proc/{pid}").exists()


# INSTALL STATE (TEMPORARY VS PERMANENT MODE)

@dataclass
class Component:
    key: str            # "battery" | "rgb"
    name: str
    description: str
    loaded: bool        # kernel module active right now
    installed: bool     # permanent (autoloads at boot via modules-load.d)

    @property
    def status(self) -> str:
        if self.installed and self.loaded:
            return "permanent"
        if self.loaded:
            return "temporary"
        if self.installed:
            # Installed for boot but absent from the running kernel. Normal
            # right after a kernel update: the new kernel booted before DKMS
            # had rebuilt the module, so boot-time autoloading found nothing.
            # A modprobe now (or the next reboot) brings it back.
            return "stale"
        return "off"

    @property
    def chip_kind(self) -> str:
        """Style class for this component's status chip. Single source of
        truth, and total: a status added later can no longer crash one
        screen while another screen happens to handle it."""
        return {
            "permanent": "ok", "temporary": "temp", "stale": "temp",
        }.get(self.status, "off")


def components() -> list[Component]:
    return [
        Component(
            key="battery",
            name="Battery charge limiter",
            description="Firmware 80% charge limit (acer-wmi-battery)",
            loaded=Battery.driver_loaded(),
            installed=Path("/etc/modules-load.d/acer-wmi-battery.conf").exists(),
        ),
        Component(
            key="rgb",
            name="Keyboard RGB",
            description="4-zone lighting control (acer-kbd-rgb)",
            loaded=Keyboard.driver_loaded(),
            installed=Path("/etc/modules-load.d/acer-kbd-rgb.conf").exists(),
        ),
        Component(
            key="fan",
            name="Fan control",
            description="Auto / Max / Custom fan duty (acer-fan-ctl)",
            loaded=Fans.driver_loaded(),
            installed=Path("/etc/modules-load.d/acer-fan-ctl.conf").exists(),
        ),
    ]


def any_temporary() -> bool:
    return any(c.status == "temporary" for c in components())


def any_stale() -> bool:
    return any(c.status == "stale" for c in components())


MODULE_NAMES = {
    "battery": "acer-wmi-battery",
    "rgb": "acer-kbd-rgb",
    "fan": "acer-fan-ctl",
}


def load_installed_command(keys: list[str]) -> list[str]:
    """One pkexec invocation loading already-installed drivers into the
    running kernel — the fix for the "stale" state after a kernel update."""
    parts = [f"modprobe {MODULE_NAMES[k]}" for k in keys]
    if "fan" in keys:
        # Mirrors install-fan.sh: the app writes fan_speed without a
        # password. The udev rule normally does this on module add.
        parts.append(
            "chmod 666 /sys/bus/wmi/drivers/acer-fan-ctl/fan_speed "
            "2>/dev/null || true"
        )
    return ["pkexec", "bash", "-c", " && ".join(parts)]


def load_temp_command(keys: list[str]) -> list[str]:
    """One pkexec invocation loading the chosen drivers for this session."""
    script = DRIVER_DIR / "load-temp.sh"
    inner = " && ".join(f'bash "{script}" {k}' for k in keys)
    return ["pkexec", "bash", "-c", inner]


def install_command(keys: list[str]) -> list[str]:
    """One pkexec invocation permanently installing the chosen drivers."""
    scripts = {
        "battery": DRIVER_DIR / "install.sh",
        "rgb": DRIVER_DIR / "install-rgb.sh",
        "fan": DRIVER_DIR / "install-fan.sh",
    }
    inner = " && ".join(f'bash "{scripts[k]}"' for k in keys)
    return ["pkexec", "bash", "-c", inner]


def uninstall_command(keys: list[str]) -> list[str]:
    """One pkexec invocation removing the chosen drivers completely,
    returning the system to stock (modules unloaded, DKMS + boot config
    removed). Safe to run whether a component is temporary or permanent."""
    scripts = {
        "battery": DRIVER_DIR / "uninstall.sh",
        "rgb": DRIVER_DIR / "uninstall-rgb.sh",
        "fan": DRIVER_DIR / "uninstall-fan.sh",
    }
    inner = " && ".join(f'bash "{scripts[k]}"' for k in keys)
    return ["pkexec", "bash", "-c", inner]


# BATTERY

@dataclass
class BatteryState:
    available: bool = False        # kernel module loaded
    percent: int = 0
    status: str = "Unknown"        # Charging / Discharging / Not charging / Full
    ac_online: bool = False
    limiter: bool = False
    temp_c: float | None = None
    held_at_limit: bool = False    # limiter is actively holding the charge


class Battery:
    _warned_unavailable = False

    @staticmethod
    def driver_loaded() -> bool:
        return HEALTH_MODE.exists()

    @staticmethod
    def read() -> BatteryState:
        st = BatteryState()
        st.available = Battery.driver_loaded()
        st.percent = int(_read(BAT / "capacity") or 0)
        st.status = _read(BAT / "status") or "Unknown"
        st.ac_online = (_read(AC / "online") or "0") == "1"
        if st.available:
            raw = _read(HEALTH_MODE) or "0"
            # The driver reports -1 when the firmware says health mode is
            # unavailable, which happens when another Acer driver (e.g.
            # Linuwu-Sense) has taken over the same WMI interface. Writing
            # in that state is ignored by the driver and blocks forever, so
            # treat it as unavailable instead of offering the toggle.
            if raw.startswith("-"):
                st.available = False
                if not Battery._warned_unavailable:
                    Battery._warned_unavailable = True
                    _log.warning(
                        "health_mode reads %s: firmware reports the limiter "
                        "unavailable (another Acer driver may hold the WMI "
                        "interface)", raw,
                    )
            else:
                Battery._warned_unavailable = False
                st.limiter = raw == "1"
                raw_temp = _read(BAT_TEMP)
                if raw_temp is not None:
                    st.temp_c = int(raw_temp) / 1000.0
        st.held_at_limit = (
            st.limiter and st.ac_online
            and st.status == "Not charging" and st.percent >= 78
        )
        return st

    @staticmethod
    def set_limiter_direct(on: bool) -> bool:
        """Direct sysfs write; works only with sufficient permissions."""
        try:
            HEALTH_MODE.write_text("1" if on else "0")
            _log.info("Battery limiter %s (direct write)",
                      "on" if on else "off")
            return True
        except OSError as err:
            _log.debug("Limiter direct write refused (%s); pkexec needed",
                       err)
            return False

    @staticmethod
    def limiter_command(on: bool) -> list[str]:
        """Privileged fallback command (run via pkexec by the GUI).

        Wrapped in `timeout` so a sysfs write that the driver refuses to
        consume can never leave the GUI waiting forever.
        """
        val = "1" if on else "0"
        return ["pkexec", "timeout", "5", "sh", "-c",
                f"echo {val} > {HEALTH_MODE}"]


# FANS

FAN_SPEED = Path("/sys/bus/wmi/drivers/acer-fan-ctl/fan_speed")
NVIDIA_PCI_POWER = Path("/sys/bus/pci/devices/0000:01:00.0/power/runtime_status")

# GUI guardrails (the kernel module accepts 0-100; the app is stricter)
FAN_FLOOR = 30          # custom sliders cannot go below this
WATCHDOG_TEMP = 90.0    # °C; above this in custom mode -> revert to auto


@dataclass
class FanState:
    available: bool = False
    cpu: int = 0            # 0 = auto for that fan
    gpu: int = 0

    @property
    def mode(self) -> str:
        if self.cpu == 0 and self.gpu == 0:
            return "auto"
        if self.cpu == 100 and self.gpu == 100:
            return "max"
        return "custom"


class Fans:
    @staticmethod
    def driver_loaded() -> bool:
        return FAN_SPEED.exists()

    @staticmethod
    def read() -> FanState:
        st = FanState(available=Fans.driver_loaded())
        raw = _read(FAN_SPEED)
        if raw and "," in raw:
            try:
                cpu_s, gpu_s = raw.split(",", 1)
                st.cpu, st.gpu = int(cpu_s), int(gpu_s)
            except ValueError:
                pass
        return st

    @staticmethod
    def set_direct(cpu: int, gpu: int) -> bool:
        try:
            FAN_SPEED.write_text(f"{cpu},{gpu}")
            _log.info("Fans set cpu=%d gpu=%d (0 = auto)", cpu, gpu)
            return True
        except OSError as err:
            _log.debug("Fan direct write refused (%s); pkexec needed", err)
            return False

    @staticmethod
    def set_command(cpu: int, gpu: int) -> list[str]:
        """Privileged fallback (pkexec) if the sysfs node isn't writable."""
        return ["pkexec", "sh", "-c", f"echo {cpu},{gpu} > {FAN_SPEED}"]


def _hwmon_temp(chip: str) -> float | None:
    """First temperature reading of the named hwmon chip, in °C."""
    for hwmon in Path("/sys/class/hwmon").glob("hwmon*"):
        if _read(hwmon / "name") == chip:
            raw = _read(hwmon / "temp1_input")
            if raw is not None:
                return int(raw) / 1000.0
    return None


def cpu_temp() -> float | None:
    return _hwmon_temp("k10temp")


def igpu_temp() -> float | None:
    return _hwmon_temp("amdgpu")


def dgpu_awake() -> bool:
    return _read(NVIDIA_PCI_POWER) == "active"


# KEYBOARD

MODES = {
    0: "Static",
    1: "Breath",
    2: "Neon",
    3: "Wave",
    4: "Shifting",
    5: "Zoom",
    6: "Temp",      # software mode: zones follow CPU temperature
}
# Modes that use the single color selection
COLOR_MODES = {0, 1, 4, 5}
# Modes that use the direction setting
DIRECTIONAL_MODES = {3, 4}
# Software-only mode driven by the app, not a firmware effect
TEMP_MODE = 6

# Temperature-mode gradient endpoints (°C)
TEMP_COOL = 45.0
TEMP_HOT = 80.0


def temp_to_color(temp_c: float) -> tuple[int, int, int]:
    """Cool cyan-blue at <=45 °C sweeping to red at >=80 °C."""
    span = (temp_c - TEMP_COOL) / (TEMP_HOT - TEMP_COOL)
    span = max(0.0, min(1.0, span))
    hue = (1.0 - span) * 0.55          # 0.55 ~ cyan-blue, 0.0 = red
    r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
    return int(r * 255), int(g * 255), int(b * 255)


@dataclass
class KeyboardState:
    mode: int = 3
    speed: int = 4
    brightness: int = 100
    direction: int = 1
    color: tuple[int, int, int] = (226, 53, 43)
    zones: list[tuple[int, int, int]] = field(
        default_factory=lambda: [(226, 53, 43)] * 4
    )


class Keyboard:
    @staticmethod
    def driver_loaded() -> bool:
        return KBD_DYNAMIC.exists() and KBD_STATIC.exists()

    @staticmethod
    def set_all_zones(color: tuple[int, int, int], brightness: int) -> bool:
        """All four zones to one static color (used by Temp mode)."""
        try:
            for i in range(4):
                KBD_STATIC.write_bytes(bytes([1 << i, *color]))
            dyn = bytearray(16)
            dyn[2] = brightness
            dyn[9] = 1
            KBD_DYNAMIC.write_bytes(bytes(dyn))
            return True
        except OSError as err:
            _log.warning("Keyboard zone write failed: %s", err)
            return False

    # Payload layout identical to facer_rgb.py / facer.c (community-tested).
    @staticmethod
    def apply(state: KeyboardState) -> bool:
        if state.mode == TEMP_MODE:
            return True     # driven by the app's temperature engine
        try:
            if state.mode == 0:
                for i, (r, g, b) in enumerate(state.zones):
                    payload = bytes([1 << i, r, g, b])
                    KBD_STATIC.write_bytes(payload)
                dyn = bytearray(16)
                dyn[2] = state.brightness
                dyn[9] = 1
                KBD_DYNAMIC.write_bytes(bytes(dyn))
            else:
                dyn = bytearray(16)
                dyn[0] = state.mode
                dyn[1] = state.speed
                dyn[2] = state.brightness
                dyn[3] = 8 if state.mode == 3 else 0
                dyn[4] = state.direction
                dyn[5], dyn[6], dyn[7] = state.color
                dyn[9] = 1
                KBD_DYNAMIC.write_bytes(bytes(dyn))
            _log.info(
                "Keyboard effect applied: %s brightness=%d speed=%d",
                MODES.get(state.mode, state.mode), state.brightness,
                state.speed,
            )
            return True
        except OSError as err:
            _log.warning("Keyboard effect write failed: %s", err)
            return False

    # PERSISTENCE

    @staticmethod
    def save_last(state: KeyboardState) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = asdict(state)
        (CONFIG_DIR / "keyboard.json").write_text(json.dumps(data, indent=2))

    @staticmethod
    def load_last() -> KeyboardState:
        try:
            data = json.loads((CONFIG_DIR / "keyboard.json").read_text())
            data["color"] = tuple(data["color"])
            data["zones"] = [tuple(z) for z in data["zones"]][:4]
            return KeyboardState(**data)
        except (OSError, ValueError, TypeError, KeyError):
            return KeyboardState()

    # PROFILES (COMPATIBLE WITH FACER_RGB.PY)

    @staticmethod
    def list_profiles() -> list[str]:
        if not FACER_PROFILE_DIR.exists():
            return []
        return sorted(p.stem for p in FACER_PROFILE_DIR.glob("*.json"))

    @staticmethod
    def save_profile(name: str, state: KeyboardState) -> None:
        FACER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        r, g, b = state.color
        data = {
            "mode": state.mode,
            "zone": 1,
            "speed": state.speed,
            "brightness": state.brightness,
            "direction": state.direction,
            "red": r,
            "green": g,
            "blue": b,
        }
        (FACER_PROFILE_DIR / f"{name}.json").write_text(
            json.dumps(data, indent=4)
        )
        _log.info("Profile saved: %s", name)

    @staticmethod
    def load_profile(name: str) -> KeyboardState | None:
        try:
            data = json.loads(
                (FACER_PROFILE_DIR / f"{name}.json").read_text()
            )
        except (OSError, ValueError) as err:
            _log.warning("Profile %s failed to load: %s", name, err)
            return None
        _log.info("Profile loaded: %s", name)
        st = KeyboardState()
        st.mode = int(data.get("mode", 3))
        st.speed = int(data.get("speed", 4))
        st.brightness = int(data.get("brightness", 100))
        st.direction = int(data.get("direction", 1))
        color = (
            int(data.get("red", 226)),
            int(data.get("green", 53)),
            int(data.get("blue", 43)),
        )
        st.color = color
        st.zones = [color] * 4
        return st
