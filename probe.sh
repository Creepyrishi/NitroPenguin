#!/usr/bin/env bash
#
# NitroPenguin hardware probe. READ-ONLY: it only reads system files,
# installs nothing, changes nothing, needs no root.
#
# Run it and paste the whole output into a GitHub issue:
#   curl -sSL https://raw.githubusercontent.com/Creepyrishi/NitroPenguin/main/probe.sh | bash
#
set -u

# The two firmware mailboxes NitroPenguin uses (see docs/how-it-works.html)
BATTERY_GUID="79772EC5-04B1-4BFD-843C-61E7F77B6CC9"
GAMING_GUID="7A4DDFE7-5B5D-40B4-8595-4408E0CC7F56"

section() { printf '\n== %s ==\n' "$1"; }
show()    { printf '%-18s= %s\n' "$1" "$2"; }
readf()   { cat "$1" 2>/dev/null || echo "(not present)"; }

echo "NITROPENGUIN HARDWARE PROBE"
date -u +"generated: %Y-%m-%dT%H:%M:%SZ"

section "identity (which machine is this exactly)"
for f in sys_vendor product_name product_family board_name; do
    show "$f" "$(readf /sys/class/dmi/id/$f)"
done

section "operating system"
. /etc/os-release 2>/dev/null || true
show "distro"    "${PRETTY_NAME:-unknown}"
show "kernel"    "$(uname -r)"
if [ -e /run/ostree-booted ]; then
    show "immutable" "yes (ostree-based: rpm-ostree/bootc distro)"
else
    show "immutable" "no"
fi
sb="unknown"
if command -v mokutil >/dev/null 2>&1; then
    sb="$(mokutil --sb-state 2>/dev/null | head -1)"
else
    for var in /sys/firmware/efi/efivars/SecureBoot-*; do
        [ -r "$var" ] || continue
        byte=$(od -An -tu1 -j4 -N1 "$var" 2>/dev/null | tr -d ' ')
        [ "$byte" = "1" ] && sb="SecureBoot enabled" || sb="SecureBoot disabled"
        break
    done
fi
show "secure_boot" "$sb"

section "can this machine build the drivers?"
show "gcc"     "$(command -v gcc >/dev/null 2>&1 && echo yes || echo no)"
show "git"     "$(command -v git >/dev/null 2>&1 && echo yes || echo no)"
show "headers" "$([ -d "/lib/modules/$(uname -r)/build" ] && echo yes || echo "no (kernel headers missing)")"
show "dkms"    "$(command -v dkms >/dev/null 2>&1 && echo yes || echo no)"

section "firmware mailboxes (WMI GUIDs)"
if [ -d /sys/bus/wmi/devices ]; then
    ls /sys/bus/wmi/devices/
else
    echo "(no /sys/bus/wmi/devices: WMI support missing?)"
fi
echo
found_b=no; found_g=no
[ -e "/sys/bus/wmi/devices/$BATTERY_GUID" ] && found_b=yes
[ -e "/sys/bus/wmi/devices/$GAMING_GUID" ] && found_g=yes
show "battery mailbox" "$found_b ($BATTERY_GUID)"
show "gaming mailbox"  "$found_g ($GAMING_GUID)"

section "acer kernel modules currently loaded"
lsmod 2>/dev/null | grep -i acer || echo "(none)"

section "what the kernel already sees"
show "leds"      "$(ls /sys/class/leds 2>/dev/null | tr '\n' ' ')"
show "backlight" "$(ls /sys/class/backlight 2>/dev/null | tr '\n' ' ')"
show "power"     "$(ls /sys/class/power_supply 2>/dev/null | tr '\n' ' ')"
chips=""
for h in /sys/class/hwmon/hwmon*; do
    chips="$chips$(readf "$h/name") "
done
show "sensors"   "${chips:-'(none)'}"
show "dev nodes" "$(ls /dev/acer-gkbbl* 2>/dev/null | tr '\n' ' ' || true)"

section "acer input devices"
grep -B1 -i 'acer' /proc/bus/input/devices 2>/dev/null | grep 'Name=' || echo "(none)"

echo
echo "Done. This probe changed nothing. Paste everything above into the issue."
