#!/usr/bin/env bash
# Convenience runner for the sketchbot demo.
#
#   ./scripts/run_demo.sh dry            # dry-run from the sample image
#   ./scripts/run_demo.sh draw           # full capture + draw
#   ./scripts/run_demo.sh gallery        # start the live gallery (:7100)
set -euo pipefail
cd "$(dirname "$0")/.."

case "${1:-dry}" in
  dry)
    python -m sketch_artist.cli --image examples/sample_face.jpg --dry-run
    ;;
  draw)
    python -m sketch_artist.cli "${@:2}"
    ;;
  gallery)
    python -m web.server
    ;;
  *)
    echo "usage: $0 {dry|draw|gallery}" >&2
    exit 2
    ;;
esac
