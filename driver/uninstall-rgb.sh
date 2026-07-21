#!/bin/bash
# Fully remove acer-kbd-rgb. Run: sudo bash uninstall-rgb.sh
set -euo pipefail
VER=1.0

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo."; exit 1; }

rmmod acer_kbd_rgb 2>/dev/null || true
dkms remove acer-kbd-rgb/$VER --all 2>/dev/null || true
rm -rf /usr/src/acer-kbd-rgb-$VER
rm -f /etc/modules-load.d/acer-kbd-rgb.conf

echo "Removed. Keyboard lighting returns to firmware default on next power cycle."
