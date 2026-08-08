#!/usr/bin/env bash
#
# NitroPenguin web installer.
#
#   curl -sSL https://raw.githubusercontent.com/Creepyrishi/NitroPenguin/main/install.sh | bash
#
# Installs the app (not the kernel drivers — those you enable from the
# app's Settings page, consciously, with a password). Idempotent: re-run
# to update. Uninstall the app with:  bash install.sh --uninstall
#
set -euo pipefail

# ---- config (override with env vars) ----
REPO_URL="${NITROPENGUIN_REPO:-https://github.com/Creepyrishi/NitroPenguin.git}"
BRANCH="${NITROPENGUIN_BRANCH:-main}"
INSTALL_DIR="${NITROPENGUIN_DIR:-$HOME/.local/share/nitropenguin}"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"

C_BOLD=$'\033[1m'; C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YEL=$'\033[33m'; C_0=$'\033[0m'
say()  { printf '%s==>%s %s\n' "$C_BOLD" "$C_0" "$*"; }
warn() { printf '%s!  %s%s\n' "$C_YEL" "$*" "$C_0"; }
die()  { printf '%sx  %s%s\n' "$C_RED" "$*" "$C_0" >&2; exit 1; }

ask() {
    # Prompt on the terminal even when the script arrives via a pipe.
    local prompt="$1" reply
    # Test by actually opening it: /dev/tty can pass -r and still fail to
    # open when there is no controlling terminal, which turned the prompts
    # below into errors and silently took the "no" branch.
    if { : < /dev/tty; } 2>/dev/null; then
        printf '%s [y/N] ' "$prompt" > /dev/tty
        read -r reply < /dev/tty || reply=""
    else
        reply="n"   # non-interactive: default to the safe choice
    fi
    [[ "$reply" =~ ^[Yy] ]]
}

# ---- uninstall path ----
if [ "${1:-}" = "--uninstall" ]; then
    say "Removing the NitroPenguin app (drivers are left untouched — remove"
    echo "   those first from the app's Settings if you want them gone)."
    systemctl --user disable --now nitropenguin-daemon.service 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/nitropenguin-daemon.service"
    systemctl --user daemon-reload 2>/dev/null || true
    rm -f "$BIN_DIR/nitropenguin" "$BIN_DIR/nitro-gui"
    rm -f "$APP_DIR/nitropenguin.desktop"
    if [ -f /etc/udev/rules.d/99-nitropenguin-hotkey.rules ]; then
        ask "Remove the Nitro-key udev rule? (needs sudo)" \
            && sudo rm -f /etc/udev/rules.d/99-nitropenguin-hotkey.rules \
            && sudo udevadm control --reload-rules 2>/dev/null || true
    fi
    if [ -f /etc/udev/hwdb.d/61-nitropenguin-kbd.hwdb ]; then
        ask "Remove the backlight-key remap? (restores the stock, buggy mapping; needs sudo)" \
            && sudo rm -f /etc/udev/hwdb.d/61-nitropenguin-kbd.hwdb \
            && sudo systemd-hwdb update 2>/dev/null || true
    fi
    if [ -d "$INSTALL_DIR" ]; then
        ask "Delete the cloned project at $INSTALL_DIR?" && rm -rf "$INSTALL_DIR"
    fi
    say "Done."
    exit 0
fi

echo
echo "  ${C_BOLD}NitroPenguin installer${C_0}"
echo "  NitroSense features for the Acer Nitro 5 on Linux"
echo

# ---- 1. hardware sanity check ----
MODEL="$(cat /sys/class/dmi/id/product_name 2>/dev/null || echo unknown)"
say "Detected model: ${C_BOLD}${MODEL}${C_0}"
case "$MODEL" in
    "Nitro AN515-45") : ;;                       # the tested model
    *Nitro*|*Predator*)
        warn "This was built and verified on the Nitro AN515-45. Your Acer"
        warn "model is related but untested — the app will still probe your"
        warn "firmware safely and only show features it actually finds." ;;
    *)
        warn "This does not look like an Acer Nitro/Predator laptop."
        ask "Continue anyway?" || die "Aborted." ;;
esac

# ---- 2. prerequisites ----
need_pkgs=0
have() { command -v "$1" >/dev/null 2>&1; }

have git || need_pkgs=1
have gcc || have cc || need_pkgs=1
KREL="$(uname -r)"
[ -d "/lib/modules/$KREL/build" ] || need_pkgs=1   # kernel headers

if [ "$need_pkgs" = 1 ]; then
    warn "Some build prerequisites are missing (git, a C compiler, or the"
    warn "kernel headers for $KREL). These need your system package manager."
    # The unversioned headers package matters as much as the versioned one:
    # without it a kernel upgrade brings no headers, DKMS cannot rebuild the
    # drivers for the new kernel, and they silently vanish after the reboot.
    if   have apt-get; then
        cmd="sudo apt-get install -y build-essential dkms git linux-headers-$KREL linux-headers-generic"
    elif have pacman;  then
        cmd="sudo pacman -S --needed base-devel dkms git linux-headers"
    elif have dnf;     then
        cmd="sudo dnf install -y @development-tools dkms git kernel-devel-$KREL kernel-devel"
    else
        cmd=""
    fi
    if [ -n "$cmd" ]; then
        echo "    $cmd"
        if ask "Run that now?"; then
            eval "$cmd" || die "Package install failed."
        else
            warn "Skipping — install them yourself before enabling drivers."
        fi
    else
        warn "Unknown package manager; install git, a compiler and kernel"
        warn "headers for $KREL manually."
    fi
fi

# uv (userspace, no sudo) — the Python runtime manager
if ! have uv; then
    say "Installing uv (Python project manager, user-space)…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    have uv || die "uv install failed; see https://docs.astral.sh/uv/"
fi

# ---- 3. clone or update ----
if [ -d "$INSTALL_DIR/.git" ]; then
    say "Updating existing install at $INSTALL_DIR"
    # FETCH_HEAD, not origin/$BRANCH: the clone is shallow and single-
    # branch, so other branches never get remote-tracking refs.
    git -C "$INSTALL_DIR" fetch --depth 1 origin "$BRANCH"
    git -C "$INSTALL_DIR" reset --hard FETCH_HEAD
else
    say "Cloning into $INSTALL_DIR"
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

# ---- 4. python environment ----
say "Setting up the Python environment (uv sync)…"
( cd "$INSTALL_DIR" && uv sync )

# ---- 5. launcher + desktop entry ----
say "Installing launcher and menu entry"
mkdir -p "$BIN_DIR" "$APP_DIR"
ln -sf "$INSTALL_DIR/bin/nitropenguin" "$BIN_DIR/nitropenguin"
ln -sf "$INSTALL_DIR/bin/nitropenguin" "$BIN_DIR/nitro-gui"

cat > "$APP_DIR/nitropenguin.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=NitroPenguin
Comment=Battery limiter, keyboard RGB and fan control for Acer Nitro
Exec=$BIN_DIR/nitropenguin
Icon=$INSTALL_DIR/assets/nitropenguin.svg
Terminal=false
Categories=Settings;HardwareSettings;
StartupWMClass=nitropenguin
EOF
update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true

# ---- 6. background daemon (autostart) ----
say "Setting up the background daemon (~20 MB; runs the fan watchdog,"
echo "   keyboard Temp mode and 80% notification without the window open)"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
cp "$INSTALL_DIR/packaging/nitropenguin-daemon.service" "$UNIT_DIR/"
if systemctl --user daemon-reload 2>/dev/null; then
    # restart, not "enable --now": an already-running daemon must pick
    # up the updated code too
    systemctl --user enable nitropenguin-daemon.service 2>/dev/null || true
    systemctl --user restart nitropenguin-daemon.service 2>/dev/null \
        && say "Daemon (re)started and set to auto-start at login." \
        || warn "Could not start the user service; check: systemctl --user status nitropenguin-daemon"
else
    warn "No systemd user session here; the daemon will start next login."
fi

# ---- 7. Nitro key opens the app (optional, needs sudo once) ----
HOTKEY_RULE=/etc/udev/rules.d/99-nitropenguin-hotkey.rules
if [ ! -f "$HOTKEY_RULE" ] && ask "Make the physical Nitro key open the app? (needs sudo once)"; then
    # uaccess grants the logged-in user read access to ONLY this device
    # (least privilege — not the whole 'input' group), so the daemon can
    # watch it for the keypress.
    sudo tee "$HOTKEY_RULE" >/dev/null <<'EOF'
SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="Acer WMI hotkeys", TAG+="uaccess"
EOF
    sudo udevadm control --reload-rules
    sudo udevadm trigger --subsystem-match=input
    systemctl --user restart nitropenguin-daemon.service 2>/dev/null || true
    say "Nitro key set up. If it doesn't work yet, reboot once."
fi

# ---- 8. keyboard-backlight key fix (AN515-45, needs sudo once) ----
HWDB_FILE=/etc/udev/hwdb.d/61-nitropenguin-kbd.hwdb
if [ "$MODEL" = "Nitro AN515-45" ] && [ ! -f "$HWDB_FILE" ]; then
    if ask "Fix the Fn+F9/F10 backlight keys? (they wrongly change SCREEN brightness; needs sudo)"; then
        sudo cp "$INSTALL_DIR/packaging/61-nitropenguin-kbd.hwdb" "$HWDB_FILE"
        sudo systemd-hwdb update
        sudo udevadm trigger --sysname-match="event*"
        say "Backlight keys remapped."
    fi
fi

# ---- 9. done ----
echo
say "${C_GRN}Installed.${C_0}"
echo "   Launch it:   ${C_BOLD}nitropenguin${C_0}   (or find NitroPenguin in your apps)"
echo "   Enable the battery / RGB / fan drivers from the app's Setup page —"
echo "   nothing touches your kernel until you choose to there."
echo
case ":$PATH:" in
    *":$BIN_DIR:"*) : ;;
    *) warn "$BIN_DIR is not on your PATH — add it, or launch from the app menu." ;;
esac
