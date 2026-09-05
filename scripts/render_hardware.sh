#!/usr/bin/env bash
# Re-render the printable parts from their OpenSCAD source and validate them.
#
#   scripts/render_hardware.sh            # both presets + OBJ + checks
#   OPENSCAD=/path/to/openscad scripts/render_hardware.sh
#
# Every STL in hardware/pencil-grip that has a .scad next to it is rebuilt, so
# the shipped meshes always match the source (they did not, before this).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
parts="$here/hardware/pencil-grip"
python="${PYTHON:-python3}"

find_openscad() {
    if [ -n "${OPENSCAD:-}" ]; then echo "$OPENSCAD"; return; fi
    for candidate in openscad openscad.com \
        "/c/Program Files/OpenSCAD/openscad.com" \
        "/mnt/c/Program Files/OpenSCAD/openscad.com" \
        "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD"; do
        if command -v "$candidate" >/dev/null 2>&1; then echo "$candidate"; return; fi
        if [ -x "$candidate" ]; then echo "$candidate"; return; fi
    done
    echo ""
}

openscad_bin="$(find_openscad)"
if [ -z "$openscad_bin" ]; then
    echo "OpenSCAD not found. Install it, or set OPENSCAD=/path/to/openscad." >&2
    exit 1
fi
echo "Using OpenSCAD: $openscad_bin"

for part in braccio_pencil_grip braccio_pen_finger; do
    for preset in 8mm 10mm; do
        src="$parts/${part}_${preset}.scad"
        out="$parts/${part}_${preset}.stl"
        echo "Rendering $(basename "$src") -> $(basename "$out")"
        "$openscad_bin" -o "$out" "$src"
    done
done

echo "Rendering the preview images"
"$openscad_bin" -o "$parts/braccio_pencil_grip_preview.png" --render     --imgsize=1400,1050 --colorscheme=Tomorrow     --camera=16.5,2.5,-26.75,64,0,42,160 "$parts/braccio_pencil_grip_8mm.scad"
"$openscad_bin" -o "$parts/braccio_pen_finger_preview.png" --render     --imgsize=1300,1000 --colorscheme=Tomorrow     --camera=16.5,12,-30,68,0,40,190 "$parts/braccio_pen_finger_8mm.scad"

echo "Converting to binary STL, writing OBJ copies, validating every part"
"$python" "$here/scripts/mesh_check.py" --binary --write-obj \
    "$parts/braccio_pencil_grip_8mm.stl" \
    "$parts/braccio_pencil_grip_10mm.stl"
"$python" "$here/scripts/mesh_check.py" "$parts"/*.stl
