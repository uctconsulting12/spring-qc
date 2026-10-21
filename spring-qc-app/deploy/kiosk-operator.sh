#!/usr/bin/env bash
# Launches the Operator screen full-screen, kiosk-mode, on a Linux touch panel
# (Raspberry Pi OS, industrial panel Linux, etc). Run at desktop login via the
# accompanying spring-qc-kiosk.service, or drop it in ~/.config/autostart.
#
# Edit EDGE_HOST below to the edge box's IP or hostname first.
set -euo pipefail

EDGE_HOST="${EDGE_HOST:-192.168.1.50}"
EDGE_PORT="${EDGE_PORT:-8001}"
URL="http://${EDGE_HOST}:${EDGE_PORT}/operator"

# Give the desktop / X server a moment to finish starting on boot.
sleep 5

# Screen should never blank or lock on a shop-floor kiosk.
xset s off || true
xset -dpms || true
xset s noblank || true

BROWSER="$(command -v chromium-browser || command -v chromium || command -v google-chrome || true)"
if [ -z "$BROWSER" ]; then
    echo "No Chromium/Chrome found on this panel." >&2
    exit 1
fi

exec "$BROWSER" \
    --kiosk "$URL" \
    --noerrdialogs \
    --disable-session-crashed-bubble \
    --disable-infobars \
    --disable-pinch \
    --overscroll-history-navigation=0 \
    --autoplay-policy=no-user-gesture-required \
    --user-data-dir="$HOME/.config/spring-qc-kiosk"
