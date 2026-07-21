#!/bin/bash
# Install acer-fan-ctl permanently (DKMS + autoload at boot).
# Fans always start in firmware AUTO mode — the module never changes
# fan state at load; only explicit writes do.
# Run as root: sudo bash install-fan.sh
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/acer-fan-ctl" && pwd)"
VER=1.0
DEST=/usr/src/acer-fan-ctl-$VER

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo."; exit 1; }

echo "==> Installing dkms (if missing)"
command -v dkms >/dev/null || apt-get install -y dkms

echo "==> Copying source to $DEST (space-free path for kbuild)"
rm -rf "$DEST"
mkdir -p "$DEST"
cp "$SRC_DIR"/acer-fan-ctl.c "$SRC_DIR"/Makefile "$SRC_DIR"/dkms.conf "$DEST"/

echo "==> Registering with DKMS (auto-rebuilds on kernel updates)"
dkms remove acer-fan-ctl/$VER --all 2>/dev/null || true
dkms add acer-fan-ctl/$VER
dkms build acer-fan-ctl/$VER
dkms install acer-fan-ctl/$VER

echo "==> Autoload at boot"
echo "acer-fan-ctl" > /etc/modules-load.d/acer-fan-ctl.conf

echo "==> Desktop app fan access without password prompts"
cat > /etc/udev/rules.d/90-acer-fan-ctl.rules <<'EOF'
ACTION=="add", SUBSYSTEM=="module", KERNEL=="acer_fan_ctl", RUN+="/bin/chmod 666 /sys/bus/wmi/drivers/acer-fan-ctl/fan_speed"
EOF
udevadm control --reload-rules 2>/dev/null || true

echo "==> Reloading module"
rmmod acer_fan_ctl 2>/dev/null || true
modprobe acer-fan-ctl
chmod 666 /sys/bus/wmi/drivers/acer-fan-ctl/fan_speed 2>/dev/null || true

echo "==> Done. fan_speed interface:"
ls -la /sys/bus/wmi/drivers/acer-fan-ctl/fan_speed
