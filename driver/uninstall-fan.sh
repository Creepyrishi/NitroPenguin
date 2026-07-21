#!/bin/bash
# Fully remove acer-fan-ctl. Run: sudo bash uninstall-fan.sh
set -euo pipefail
VER=1.0

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo."; exit 1; }

# Return fans to firmware auto before removing
echo "0,0" > /sys/bus/wmi/drivers/acer-fan-ctl/fan_speed 2>/dev/null || true

rmmod acer_fan_ctl 2>/dev/null || true
dkms remove acer-fan-ctl/$VER --all 2>/dev/null || true
rm -rf /usr/src/acer-fan-ctl-$VER
rm -f /etc/modules-load.d/acer-fan-ctl.conf
rm -f /etc/udev/rules.d/90-acer-fan-ctl.rules
udevadm control --reload-rules 2>/dev/null || true

echo "Removed. Fans are controlled by firmware (auto), as stock."
