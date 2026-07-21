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
    if [ -r /dev/tty ]; then
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
    rm -f "$BIN_DIR/nitropenguin" "$BIN_DIR/nitro-gui"
    rm -f "$APP_DIR/nitropenguin.desktop"
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
    if   have apt-get; then
        cmd="sudo apt-get install -y build-essential dkms git linux-headers-$KREL"
    elif have pacman;  then
        cmd="sudo pacman -S --needed base-devel dkms git linux-headers"
    elif have dnf;     then
        cmd="sudo dnf install -y @development-tools dkms git kernel-devel-$KREL"
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
    git -C "$INSTALL_DIR" fetch --depth 1 origin "$BRANCH"
    git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH"
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

# ---- 6. done ----
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
