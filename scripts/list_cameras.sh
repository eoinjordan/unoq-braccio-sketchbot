#!/usr/bin/env bash
# List USB video devices with their vendor:product IDs so you can fill in
# config/cameras.yaml. Works on the UNO Q (Linux).
set -euo pipefail

echo "== lsusb =="
lsusb 2>/dev/null || echo "(lsusb not available)"

echo
echo "== /dev/video* -> USB VID:PID =="
shopt -s nullglob
for dev in /sys/class/video4linux/video*; do
  name=$(basename "$dev")
  path=$(readlink -f "$dev/device")
  vid=""; pid=""
  for _ in 1 2 3 4 5 6; do
    if [[ -f "$path/idVendor" && -f "$path/idProduct" ]]; then
      vid=$(cat "$path/idVendor"); pid=$(cat "$path/idProduct"); break
    fi
    path=$(dirname "$path")
  done
  label=$(cat "$dev/name" 2>/dev/null || echo "?")
  printf "/dev/%s\t%s:%s\t%s\n" "$name" "${vid:-????}" "${pid:-????}" "$label"
done
