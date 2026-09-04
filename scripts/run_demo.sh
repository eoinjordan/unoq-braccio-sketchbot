#!/usr/bin/env bash
# Convenience runner for the sketchbot demo.
#
#   ./scripts/run_demo.sh setup          # create .venv and install requirements
#   ./scripts/run_demo.sh dry            # dry-run from the sample image
#   ./scripts/run_demo.sh sim            # draw the sample on the software sim
#   ./scripts/run_demo.sh agent          # run the standalone sim arm agent :8765
#   ./scripts/run_demo.sh draw           # full capture + draw
#   ./scripts/run_demo.sh gallery        # start the live gallery (:7100)
#   ./scripts/run_demo.sh test           # run the pytest suite
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
    # Native deps (numpy/opencv) are best provided by Debian's prebuilt
    # packages on the UNO Q (arm64): there is no numpy<2 wheel for Python 3.13,
    # so a plain `pip install` would slowly compile it from source. Prefer apt,
    # then make a --system-site-packages venv so it can see them, and only pip
    # what the system didn't provide.
    if command -v apt-get >/dev/null 2>&1; then
      echo "Installing Debian prebuilt native deps (no source compile)..."
      sudo apt-get update
      sudo apt-get install -y python3-venv python3-pip \
        python3-numpy python3-opencv opencv-data python3-pil python3-yaml || \
        echo "apt install failed; will fall back to pip wheels." >&2
    fi
    rm -rf "$VENV"
    if ! err="$(python3 -m venv --system-site-packages "$VENV" 2>&1)"; then
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
    # Install only the modules the system packages did not already satisfy, so
    # numpy/opencv come from apt (prebuilt) and never trigger a source build.
    "$PY" - <<'PYDEPS'
import importlib.util as u, subprocess, sys
want = [("cv2", "opencv-python-headless>=4.8"),
        ("numpy", "numpy>=1.24"),
        ("PIL", "Pillow>=10.0"),
        ("yaml", "PyYAML>=6.0")]
missing = [pip for mod, pip in want if u.find_spec(mod) is None]
if missing:
    print("pip installing (not provided by system):", missing)
    subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
else:
    print("All native deps satisfied by Debian packages; nothing to compile.")
PYDEPS
    echo "Done. Virtualenv ready at $VENV."
    ;;
  dry)
    ensure_venv
    "$PY" -m sketch_artist.cli --image examples/sample_face_eoin.png --dry-run
    ;;
  sim)
    # End-to-end on the built-in software simulator (no arm, no Gazebo).
    # Extra args pass through, e.g. --style engineer or --image other.jpg.
    ensure_venv
    "$PY" -m sketch_artist.cli --sim --image examples/sample_face_eoin.png "${@:2}"
    ;;
  agent)
    # Standalone simulator arm agent speaking the M/S protocol on :8765,
    # a drop-in for the real UNO Q agent. Draw against it from another shell:
    #   ./scripts/run_demo.sh draw --style engineer
    ensure_venv
    "$PY" -m sketch_artist.sim "${@:2}"
    ;;
  draw)
    ensure_venv
    "$PY" -m sketch_artist.cli "${@:2}"
    ;;
  gallery)
    ensure_venv
    "$PY" -m web.server
    ;;
  test)
    ensure_venv
    if ! "$PY" -c "import pytest" 2>/dev/null; then
      echo "pytest not installed. Run: $PY -m pip install -r requirements-dev.txt" >&2
      exit 1
    fi
    "$PY" -m pytest "${@:2}"
    ;;
  *)
    echo "usage: $0 {setup|dry|sim|agent|draw|gallery|test}" >&2
    exit 2
    ;;
esac
