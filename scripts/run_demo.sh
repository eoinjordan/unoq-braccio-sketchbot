#!/usr/bin/env bash
# Convenience runner for the sketchbot demo.
#
#   ./scripts/run_demo.sh setup          # create .venv and install requirements
#   ./scripts/run_demo.sh dry            # dry-run from the sample image
#   ./scripts/run_demo.sh draw           # full capture + draw
#   ./scripts/run_demo.sh gallery        # start the live gallery (:7100)
#
# On Debian/Arduino UNO Q the system Python is "externally managed" (PEP 668)
# and only `python3` exists, so we always run through a local virtualenv.
set -euo pipefail
cd "$(dirname "$0")/.."

VENV=".venv"
PY="$VENV/bin/python"

ensure_venv() {
  if [ ! -x "$PY" ]; then
    echo "No virtualenv found at $VENV. Run: ./scripts/run_demo.sh setup" >&2
    exit 1
  fi
}

case "${1:-dry}" in
  setup)
    rm -rf "$VENV"
    if ! err="$(python3 -m venv "$VENV" 2>&1)"; then
      echo "$err" >&2
      rm -rf "$VENV"
      if printf '%s' "$err" | grep -q "ensurepip"; then
        minor="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
        cat >&2 <<EOF

The Python 'venv' module is missing its pip bootstrap (Debian splits it out).
Install it, then re-run this command:

  sudo apt update
  sudo apt install -y python3-venv python3-pip python${minor}-venv
  ./scripts/run_demo.sh setup

Alternatively, skip Python setup entirely and use Docker:

  docker compose up -d --build
EOF
      fi
      exit 1
    fi
    "$PY" -m pip install --upgrade pip
    "$PY" -m pip install -r requirements.txt
    echo "Done. Virtualenv ready at $VENV."
    ;;
  dry)
    ensure_venv
    "$PY" -m sketch_artist.cli --image examples/sample_face.jpg --dry-run
    ;;
  draw)
    ensure_venv
    "$PY" -m sketch_artist.cli "${@:2}"
    ;;
  gallery)
    ensure_venv
    "$PY" -m web.server
    ;;
  *)
    echo "usage: $0 {setup|dry|draw|gallery}" >&2
    exit 2
    ;;
esac
