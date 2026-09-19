#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="https://github.com/eoinjordan/unoq-braccio-sketchbot.git"
SETUP_URL="https://eoinjordan.github.io/unoq-braccio-sketchbot/"
INSTALL_DIR="${HOME}/unoq-braccio-sketchbot"
CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME}/.config}"
DRY_RUN=false
START=true
INSTALL_AGENT=false
SERVOS_OFF=false
ALLOW_MOTION=false
TABLET_CAMERA=false

fail() { printf 'Installation stopped: %s\n' "$*" >&2; exit 1; }

for argument in "$@"; do
  case "$argument" in
    --dry-run) DRY_RUN=true ;;
    --no-start) START=false ;;
    --install-agent) INSTALL_AGENT=true ;;
    --servo-power-off) SERVOS_OFF=true ;;
    --allow-motion) ALLOW_MOTION=true ;;
    --tablet-camera) TABLET_CAMERA=true ;;
    --help)
      printf '%s\n' 'Sketchbot UNO Q installer' \
        'Default: install Studio, preserve settings, enable boot startup, disable motion.' \
        '--dry-run          Show the installation plan; change nothing.' \
        '--no-start         Install files and dependencies without service changes.' \
        '--install-agent    Build/flash the Braccio MCU agent; also requires --servo-power-off.' \
        '--servo-power-off  Confirm servo power is physically disconnected for driver installation.' \
        '--allow-motion     Explicit supervised opt-in; sessions still start disarmed.'
      printf '%s\n' '--tablet-camera    Configure the face role for photos from a phone/tablet.'
      exit 0 ;;
    *) fail "Unknown option: $argument (use --help)" ;;
  esac
done

if "$INSTALL_AGENT" && ! "$SERVOS_OFF"; then
  fail 'Driver installation may flash the MCU. Disconnect servo power and add --servo-power-off.'
fi
if "$INSTALL_AGENT" && ! "$START"; then
  fail '--install-agent starts App Lab and cannot be combined with --no-start.'
fi
if [[ "$HOME" == *$'\n'* || "$HOME" == *'"'* || "$HOME" == *'%'* || "$HOME" == *'\'* ]]; then
  fail 'The home directory contains characters unsupported by the service template.'
fi

printf 'Install directory: %s\nPublic setup: %s\n' "$INSTALL_DIR" "$SETUP_URL"
printf 'Driver installation: %s; hardware motion opt-in: %s; start service: %s\n' \
  "$INSTALL_AGENT" "$ALLOW_MOTION" "$START"
if "$DRY_RUN"; then
  printf '%s\n' 'Dry run: no network access, package install, firmware flash or service changes.'
  exit 0
fi

[[ "$(uname -s)" == Linux ]] || fail 'Run this installer inside the UNO Q Linux SSH session, not on your laptop.'
[[ "$(id -u)" != 0 ]] || fail 'Run as the normal arduino user, not root or sudo.'
for executable in git python3 install; do
  command -v "$executable" >/dev/null || fail "Missing $executable. Install the prerequisite and rerun."
done
if "$START"; then command -v systemctl >/dev/null || fail 'systemctl is required for boot startup.'; fi
if "$START"; then
  for override in "$CONFIG_HOME/systemd/user/sketchbot-studio.service.d/"*.conf; do
    [[ -e "$override" ]] || continue
    [[ "$(basename "$override")" == 10-installer.conf ]] || fail 'Custom Studio service overrides exist and were preserved. Review them before using the installer, or choose --no-start.'
  done
fi
if "$INSTALL_AGENT"; then
  command -v arduino-app-cli >/dev/null || fail 'Arduino App Lab CLI is required for the optional driver installation.'
  [[ ! -e "$HOME/ArduinoApps/braccio_remote_agent" ]] || fail 'An arm-agent installation already exists and was preserved. Update it separately after reviewing local changes.'
fi

if [[ -e "$INSTALL_DIR" ]]; then
  [[ -d "$INSTALL_DIR/.git" ]] || fail 'Install directory exists but is not a Git checkout; nothing was overwritten.'
  origin=$(git -C "$INSTALL_DIR" remote get-url origin)
  [[ "$origin" == "$REPOSITORY" || "$origin" == "${REPOSITORY%.git}" ]] || fail 'Existing checkout has a different origin; nothing was changed.'
  [[ -z "$(git -C "$INSTALL_DIR" status --porcelain --untracked-files=normal)" ]] || fail 'Existing checkout has local changes. Preserve them before updating; no reset was performed.'
  [[ "$(git -C "$INSTALL_DIR" symbolic-ref --short HEAD)" == main ]] || fail 'Existing checkout is not on main. No branch was switched or reset.'
  if "$START" && systemctl --user is-active --quiet sketchbot-studio.service; then
    systemctl --user stop sketchbot-studio.service
  fi
  git -C "$INSTALL_DIR" pull --ff-only origin main
else
  git clone --depth 1 "$REPOSITORY" "$INSTALL_DIR"
fi

PYTHON="$INSTALL_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  if ! python3 -m venv --system-site-packages "$INSTALL_DIR/.venv"; then
    fail 'Python venv support is missing. Run sudo apt install python3-venv python3-pip yourself, then rerun. No privilege escalation was attempted.'
  fi
fi
"$PYTHON" -m pip install --only-binary=:all: -r "$INSTALL_DIR/requirements.txt"
"$PYTHON" -c 'import cv2, numpy, PIL, yaml; print("Vision dependencies ready")'
if "$TABLET_CAMERA"; then
  pushd "$INSTALL_DIR" >/dev/null
  "$PYTHON" -c 'from web.control import ControlApp; app=ControlApp(); app.save_camera("face", {"format":"tablet", "enabled":True, "mounted_on_arm":False, "width":1280, "height":720}); app.close()'
  popd >/dev/null
fi

if "$INSTALL_AGENT"; then
  agent="$HOME/ArduinoApps/braccio_remote_agent"
  mkdir -p "$HOME/ArduinoApps" "$HOME/bin" "$CONFIG_HOME/systemd/user"
  cp -R "$INSTALL_DIR/app_lab/braccio_remote_agent" "$agent"
  install -m 755 "$INSTALL_DIR/app_lab/braccio_remote_agent/braccio-agent-start.sh" "$HOME/bin/braccio-agent-start.sh"
  install -m 644 "$INSTALL_DIR/app_lab/braccio_remote_agent/braccio-agent.service" "$CONFIG_HOME/systemd/user/braccio-agent.service"
  arduino-app-cli app start "$agent"
  if "$START"; then
    systemctl --user daemon-reload
    systemctl --user enable braccio-agent.service
  fi
fi

if "$START"; then
  systemctl --user show-environment >/dev/null || fail 'No user systemd session. Run from an SSH login as arduino.'
  mkdir -p "$CONFIG_HOME/systemd/user/sketchbot-studio.service.d"
  unit="$CONFIG_HOME/systemd/user/sketchbot-studio.service"
  install -m 644 "$INSTALL_DIR/app_lab/braccio_remote_agent/sketchbot-studio.service" "$unit"
  extra=""
  if "$ALLOW_MOTION"; then extra=" --allow-motion"; fi
  temporary=$(mktemp "$CONFIG_HOME/systemd/user/sketchbot-studio.service.d/.install-XXXXXX")
  printf '[Service]\nWorkingDirectory="%s"\nExecStart=\nExecStart="%s" -m web.server --port 7100%s\n' \
    "$INSTALL_DIR" "$PYTHON" "$extra" > "$temporary"
  chmod 600 "$temporary"
  mv "$temporary" "$CONFIG_HOME/systemd/user/sketchbot-studio.service.d/10-installer.conf"
  if systemctl --user cat braccio-calibrate.service >/dev/null 2>&1; then
    systemctl --user disable --now braccio-calibrate.service
  fi
  systemctl --user daemon-reload
  systemctl --user enable sketchbot-studio.service
  systemctl --user restart sketchbot-studio.service
  systemctl --user is-active --quiet sketchbot-studio.service
fi

device_name=$(hostname -s)
printf '\nOpen on a phone or tablet on the same Wi-Fi: http://%s.local:7100\n' "$device_name"
printf 'Device launcher: %s#device=http%%3A%%2F%%2F%s.local%%3A7100\n' "$SETUP_URL" "$device_name"
if command -v loginctl >/dev/null; then
  linger=$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null || true)
  if [[ "$linger" != yes ]]; then
    printf '%s\n' 'Boot startup needs user lingering. Ask the device administrator to run loginctl enable-linger arduino.'
  fi
fi
printf '%s\n' 'Settings in config/runtime.yaml were preserved. No drawing or calibration was run.'
if ! "$ALLOW_MOTION"; then printf '%s\n' 'Hardware motion remains disabled.'; fi