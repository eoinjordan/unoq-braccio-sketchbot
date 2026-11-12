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

arm="$here/hardware/braccio-arm"
for camera in xiao_round_display esp_eye; do
    holder="braccio_gripper_$camera"
    echo "Rendering $holder: three aim distances and the fit piece"
    "$openscad_bin" -o "$parts/$holder.stl" "$parts/$holder.scad"
    "$openscad_bin" -o "$parts/${holder}_near.stl" -D pick_distance=90 "$parts/$holder.scad"
    "$openscad_bin" -o "$parts/${holder}_far.stl" -D pick_distance=180 "$parts/$holder.scad"
    "$openscad_bin" -o "$parts/${holder}_fit_test.stl" -D 'part="fit_test"' "$parts/$holder.scad"
    "$openscad_bin" -o "$parts/${holder}_preview.png" --render --imgsize=1400,1050 --colorscheme=Tomorrow --camera=10,5,10,55,0,25,270 "$parts/$holder.scad"
    # The pictures of it on the gripper include the GPL-3.0 arm meshes, so
    # they are written beside those meshes, not here.
    "$openscad_bin" -o "$arm/gripper_${camera}_side.png" --imgsize=1400,1050 --colorscheme=Tomorrow --camera=0,-30,10,78,0,90,380 -D "which=\"$camera\"" "$arm/gripper_cameras_on_gripper.scad"
    "$openscad_bin" -o "$arm/gripper_${camera}_audience.png" --imgsize=1400,1050 --colorscheme=Tomorrow --camera=0,-15,15,60,0,205,380 -D "which=\"$camera\"" "$arm/gripper_cameras_on_gripper.scad"
    "$python" "$here/scripts/mesh_check.py" --binary "$parts/$holder.stl" "$parts/${holder}_near.stl" "$parts/${holder}_far.stl" "$parts/${holder}_fit_test.stl"
done

holder="braccio_gripper_xiao_round_display"
echo "Rendering the round display cover: one per aim distance, and its fit piece"
"$openscad_bin" -o "$parts/${holder}_cover.stl" -D 'part="cover"' "$parts/$holder.scad"
"$openscad_bin" -o "$parts/${holder}_near_cover.stl" -D 'part="cover"' -D pick_distance=90 "$parts/$holder.scad"
"$openscad_bin" -o "$parts/${holder}_far_cover.stl" -D 'part="cover"' -D pick_distance=180 "$parts/$holder.scad"
"$openscad_bin" -o "$parts/${holder}_cover_fit_test.stl" -D 'part="cover_fit_test"' "$parts/$holder.scad"
"$openscad_bin" -o "$parts/${holder}_cover_preview.png" --render --imgsize=1400,1050 --colorscheme=Tomorrow --camera=0,0,25,28,0,15,170 -D 'part="cover"' -D 'pose="cradle"' "$parts/$holder.scad"
"$openscad_bin" -o "$arm/gripper_xiao_round_display_front.png" --imgsize=1400,1050 --colorscheme=Tomorrow --camera=0,-30,12,66,0,20,340 "$arm/gripper_cameras_on_gripper.scad"
echo "Rendering the saddle fit piece"
"$openscad_bin" -o "$parts/braccio_gripper_saddle_fit_test.stl" "$parts/braccio_gripper_saddle_fit_test.scad"
"$python" "$here/scripts/mesh_check.py" --binary "$parts/${holder}_cover.stl" "$parts/${holder}_near_cover.stl" "$parts/${holder}_far_cover.stl" "$parts/${holder}_cover_fit_test.stl" "$parts/braccio_gripper_saddle_fit_test.stl"

echo "Converting to binary STL, writing OBJ copies, validating every part"
"$python" "$here/scripts/mesh_check.py" --binary --write-obj \
    "$parts/braccio_pencil_grip_8mm.stl" \
    "$parts/braccio_pencil_grip_10mm.stl"
"$python" "$here/scripts/mesh_check.py" "$parts"/*.stl

echo "Recording where each tie tunnel is and checking a tie passes through"
"$python" "$here/scripts/check_tie_tunnels.py" --write

echo "Copying the parts to the setup site and rewriting its parts page"
"$python" "$here/scripts/build_parts_page.py"
