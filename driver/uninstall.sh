#!/bin/bash
# Fully remove acer-wmi-battery and return to stock. Run: sudo bash uninstall.sh
set -euo pipefail
VER=0.2.0

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo."; exit 1; }

# Turn limiter off first so the battery behaves stock immediately
echo 0 > /sys/bus/wmi/drivers/acer-wmi-battery/health_mode 2>/dev/null || true

rmmod acer_wmi_battery 2>/dev/null || true
dkms remove acer-wmi-battery/$VER --all 2>/dev/null || true
rm -rf /usr/src/acer-wmi-battery-$VER
rm -f /etc/modules-load.d/acer-wmi-battery.conf
rm -f /etc/modprobe.d/acer-wmi-battery.conf

echo "Removed. System is back to stock (stock acer_wmi was never touched)."
