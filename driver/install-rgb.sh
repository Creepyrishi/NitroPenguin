#!/bin/bash
# Install acer-kbd-rgb permanently (DKMS + autoload at boot)
# Run as root: sudo bash install-rgb.sh
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/acer-kbd-rgb" && pwd)"
VER=1.0
DEST=/usr/src/acer-kbd-rgb-$VER

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo."; exit 1; }

echo "==> Installing dkms (if missing)"
command -v dkms >/dev/null || apt-get install -y dkms

echo "==> Copying source to $DEST (space-free path for kbuild)"
rm -rf "$DEST"
mkdir -p "$DEST"
cp "$SRC_DIR"/acer-kbd-rgb.c "$SRC_DIR"/Makefile "$SRC_DIR"/dkms.conf "$DEST"/

echo "==> Registering with DKMS (auto-rebuilds on kernel updates)"
dkms remove acer-kbd-rgb/$VER --all 2>/dev/null || true
dkms add acer-kbd-rgb/$VER
dkms build acer-kbd-rgb/$VER
dkms install acer-kbd-rgb/$VER

echo "==> Autoload at boot"
echo "acer-kbd-rgb" > /etc/modules-load.d/acer-kbd-rgb.conf

echo "==> Reloading module"
rmmod acer_kbd_rgb 2>/dev/null || true
modprobe acer-kbd-rgb

echo "==> Done. Devices:"
ls -la /dev/acer-gkbbl-0 /dev/acer-gkbbl-static-0
