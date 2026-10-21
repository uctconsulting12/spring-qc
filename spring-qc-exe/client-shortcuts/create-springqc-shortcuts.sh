#!/usr/bin/env bash
# Spring QC - Linux/other-OS client shortcuts.
#
# The Linux equivalent of Create-SpringQCShortcuts.ps1: creates Desktop +
# application-menu launchers that open Spring QC pages in the default
# browser. Same idea as the Windows version - no app to install on this
# PC, just icons that point a normal browser at the server over the LAN.
#
# Usage:
#   ./create-springqc-shortcuts.sh <server-ip> [port] [pages...]
#
# Examples:
#   ./create-springqc-shortcuts.sh 192.168.1.50
#   ./create-springqc-shortcuts.sh 192.168.1.50 8001 operator
#   ./create-springqc-shortcuts.sh                      # prompts for the IP
#
# Pages: admin operator monitor reports (default: all four)

set -euo pipefail

SERVER="${1:-}"
PORT="${2:-8001}"
shift $(( $# >= 2 ? 2 : $# )) || true
PAGES=("$@")

if [ -z "$SERVER" ]; then
    read -rp "Enter the Spring QC server's IP address (e.g. 192.168.1.50): " SERVER
fi
if [ -z "$SERVER" ]; then
    echo "No address entered - aborting." >&2
    exit 1
fi
if [ ${#PAGES[@]} -eq 0 ]; then
    PAGES=(admin operator monitor reports)
fi

BASE_URL="http://${SERVER}:${PORT}"
echo "Spring QC shortcuts -> ${BASE_URL}"
echo

label_for() {
    case "$1" in
        admin)    echo "Spring QC - Admin" ;;
        operator) echo "Spring QC - Operator" ;;
        monitor)  echo "Spring QC - Monitor" ;;
        reports)  echo "Spring QC - Reports" ;;
        *) echo "Unknown page: $1" >&2; exit 1 ;;
    esac
}

write_launcher() {
    local dir="$1" page="$2" label url dest
    label="$(label_for "$page")"
    url="${BASE_URL}/${page}"
    mkdir -p "$dir"
    dest="${dir}/springqc-${page}.desktop"
    cat > "$dest" <<EOF
[Desktop Entry]
Type=Application
Name=${label}
Comment=Opens ${label} in your default browser
Exec=xdg-open ${url}
Icon=web-browser
Terminal=false
Categories=Network;
EOF
    chmod +x "$dest"
    # GNOME/Nautilus refuses to run a launcher until it's marked trusted;
    # this is a no-op (and harmless if it fails) on distros/file managers
    # that don't use this attribute at all.
    gio set "$dest" metadata::trusted true 2>/dev/null || true
    echo "  Created: $dest -> $url"
}

DESKTOP_DIR="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
MENU_DIR="$HOME/.local/share/applications"

echo "Desktop:"
for p in "${PAGES[@]}"; do
    write_launcher "$DESKTOP_DIR" "$p"
done

echo
echo "Application menu:"
for p in "${PAGES[@]}"; do
    write_launcher "$MENU_DIR" "$p"
done

echo
echo "Done. Double-click a Desktop icon (you may need to right-click -> Allow"
echo "Launching the first time, depending on your file manager), or search"
echo "'Spring QC' in your application menu."
