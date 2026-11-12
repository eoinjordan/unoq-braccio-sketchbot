#!/usr/bin/env bash
# Install the pick-and-place service for the current user. Run on the UNO Q
# from the root of this checkout. Needs no sudo. Does not start anything and
# does not change which service comes up at boot: use sketchbot-mode for that.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ "$here" != "$HOME/sketchbot-pickplace" ]]; then
  echo "This checkout is at $here; the unit expects $HOME/sketchbot-pickplace." >&2
  exit 1
fi
if [[ ! -x "$here/.venv/bin/python" ]]; then
  python3 -m venv --system-site-packages "$here/.venv"
fi
"$here/.venv/bin/python" -c "import serial" 2>/dev/null \
  || "$here/.venv/bin/pip" install --quiet "pyserial>=3.5"
(cd "$here" && "$here/.venv/bin/python" -c "import serial, yaml, numpy; from sketch_artist import pick_place_service")
mkdir -p "$HOME/.config/systemd/user" "$HOME/.config/sketchbot" "$HOME/bin"
install -m 0644 "$here/deploy/pickplace/sketchbot-pickplace.service" "$HOME/.config/systemd/user/"
[[ -e "$HOME/.config/sketchbot/pickplace.env" ]] \
  || install -m 0644 "$here/deploy/pickplace/pickplace-options.conf" "$HOME/.config/sketchbot/pickplace.env"
install -m 0755 "$here/deploy/pickplace/sketchbot-mode" "$HOME/bin/"
install -m 0755 "$here/deploy/pickplace/pickplace-kiosk.sh" "$HOME/bin/"
systemctl --user daemon-reload
echo "Installed. Linger: $(loginctl show-user "$USER" -p Linger --value)"
echo "Next: sketchbot-mode pickplace   (or: sketchbot-mode studio to go back)"
