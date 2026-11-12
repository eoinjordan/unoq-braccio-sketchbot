#!/usr/bin/env bash
# Show the pick-and-place page full screen on a touchscreen plugged into the
# UNO Q. Meant to be started by the desktop session (see the .desktop file
# next to this script). Does nothing, quietly, when no display is connected
# or no browser is installed.
set -u
url="${PICKPLACE_URL:-http://127.0.0.1:7110/?kiosk=1}"
connected=no
for status in /sys/class/drm/card*-*/status; do
  [[ -r "$status" && "$(cat "$status")" == connected ]] && connected=yes
done
[[ "$connected" == yes ]] || { echo "no display connected"; exit 0; }
for _ in $(seq 1 60); do
  (echo > /dev/tcp/127.0.0.1/7110) >/dev/null 2>&1 && break
  sleep 2
done
for browser in chromium chromium-browser; do
  if command -v "$browser" >/dev/null 2>&1; then
    exec "$browser" --kiosk --noerrdialogs --disable-infobars --no-first-run \
      --disable-pinch --overscroll-history-navigation=0 --touch-events=enabled "$url"
  fi
done
for browser in firefox-esr firefox; do
  command -v "$browser" >/dev/null 2>&1 && exec "$browser" --kiosk "$url"
done
command -v epiphany >/dev/null 2>&1 && exec epiphany --application-mode "$url"
# No browser: the image has WebKitGTK and its Python bindings.
viewer="$(dirname "$(readlink -f "$0")")/pickplace-kiosk.py"
[[ -r "$viewer" ]] || viewer="$HOME/sketchbot-pickplace/deploy/pickplace/pickplace-kiosk.py"
if python3 -c "import gi; gi.require_version('WebKit2', '4.1')" 2>/dev/null; then
  exec python3 "$viewer" "$url"
fi
echo "no browser and no WebKitGTK bindings: sudo apt install chromium" >&2
exit 0
