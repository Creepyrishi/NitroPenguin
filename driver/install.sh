#!/bin/bash
# Install acer-wmi-battery permanently (DKMS + autoload + limiter on at boot)
# Acer Nitro 5 AN515-45 — run as root: sudo bash install.sh
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/acer-wmi-battery" && pwd)"
VER=0.2.0
DEST=/usr/src/acer-wmi-battery-$VER

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo."; exit 1; }

echo "==> Installing dkms (if missing)"
command -v dkms >/dev/null || apt-get install -y dkms

echo "==> Copying source to $DEST (space-free path for kbuild)"
rm -rf "$DEST"
mkdir -p "$DEST"
cp "$SRC_DIR"/acer-wmi-battery.c "$SRC_DIR"/Makefile "$SRC_DIR"/dkms.conf "$DEST"/

echo "==> Registering with DKMS (auto-rebuilds on kernel updates)"
dkms remove acer-wmi-battery/$VER --all 2>/dev/null || true
dkms add acer-wmi-battery/$VER
dkms build acer-wmi-battery/$VER
dkms install acer-wmi-battery/$VER

echo "==> Autoload at boot"
echo "acer-wmi-battery" > /etc/modules-load.d/acer-wmi-battery.conf

echo "==> Enable 80% charge limit at every boot"
echo "options acer_wmi_battery enable_health_mode=1" > /etc/modprobe.d/acer-wmi-battery.conf

# Reload cleanly so the running module is the DKMS-installed one
echo "==> Reloading module"
rmmod acer_wmi_battery 2>/dev/null || true
modprobe acer-wmi-battery

echo "==> Done. State:"
echo "  limiter: $(cat /sys/bus/wmi/drivers/acer-wmi-battery/health_mode)"
echo "  battery: $(cat /sys/class/power_supply/BAT1/capacity)% - $(cat /sys/class/power_supply/BAT1/status)"
