#!/usr/bin/env bash
# Fetch the small line-art model the portrait step prefers.
#
# Informative Drawings (Chan et al.), exported to ONNX: 17 MB, ~4.5 M params,
# about a second a frame on a CPU. Without it the pipeline falls back to the
# classic Canny/DoG tracer, which finds the hair and glasses but not the eyes,
# nose or mouth.
set -euo pipefail
cd "$(dirname "$0")/.."

URL="https://huggingface.co/rocca/informative-drawings-line-art-onnx/resolve/main/model.onnx"
OUT="models/lineart_informative.onnx"

mkdir -p models
if [ -f "$OUT" ]; then
  echo "already have $OUT ($(du -h "$OUT" | cut -f1))"
  exit 0
fi
echo "fetching $URL"
curl -fL --progress-bar -o "$OUT" "$URL"
echo "wrote $OUT ($(du -h "$OUT" | cut -f1))"
echo
echo "onnxruntime is needed to run it:"
echo "  .venv/bin/pip install onnxruntime      # or: sudo apt install python3-onnxruntime"
