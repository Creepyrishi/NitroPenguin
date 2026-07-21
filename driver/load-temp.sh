#!/bin/bash
# Temporarily load a driver for this session only (gone after reboot).
# Builds the module first if no .ko exists (in a space-free temp dir,
# because kbuild cannot handle the space in this project's path).
# Usage (as root): load-temp.sh battery|rgb
set -euo pipefail

DRIVER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "${1:-}" in
  battery) SRC="$DRIVER_DIR/acer-wmi-battery"; KO="acer-wmi-battery.ko"; MOD=acer_wmi_battery ;;
  rgb)     SRC="$DRIVER_DIR/acer-kbd-rgb";     KO="acer-kbd-rgb.ko";     MOD=acer_kbd_rgb ;;
  fan)     SRC="$DRIVER_DIR/acer-fan-ctl";     KO="acer-fan-ctl.ko";     MOD=acer_fan_ctl ;;
  *) echo "usage: load-temp.sh battery|rgb|fan" >&2; exit 1 ;;
esac

if lsmod | grep -q "^${MOD} "; then
  echo "$1: already loaded"
  exit 0
fi

KO_PATH="$SRC/$KO"
if [ ! -f "$KO_PATH" ]; then
  echo "$1: no prebuilt module, building..."
  BUILD="$(mktemp -d)"
  trap 'rm -rf "$BUILD"' EXIT
  cp "$SRC"/*.c "$SRC"/Makefile "$BUILD"/
  make -C "$BUILD" >/dev/null
  KO_PATH="$BUILD/$KO"
fi

insmod "$KO_PATH"

# Fan control: let the desktop app adjust fans without a password each
# time (single-user machine; values are validated 0-100 by the module).
if [ "$1" = "fan" ]; then
  chmod 666 /sys/bus/wmi/drivers/acer-fan-ctl/fan_speed 2>/dev/null || true
fi

echo "$1: loaded temporarily (until reboot)"
