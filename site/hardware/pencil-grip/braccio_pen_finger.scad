/*
Braccio pen finger - pencil clamp that keeps the claws
=====================================================
The original grip (braccio_pencil_grip.scad) *replaces* a Braccio finger, so
while it is fitted the gripper cannot hold anything. This part keeps the whole
finger - claw and all - and carries the split pencil collar beside it, so one
tool does both jobs:

  * pencil/pen/marker in the collar   -> the arm draws;
  * pull the pencil out (one M3 screw, or just slacken it) -> the claws close
    normally and grip as they always did;
  * the wrist camera bracket (braccio_wrist_camera_bracket.stl) clamps the
    wrist, not a finger, so the camera stays on in either mode.

WHICH SIDE. `pen_side` puts the collar on the +y (1) or -y (-1) face of the
finger. It has to go on the OUTSIDE - the face that does not meet the opposing
finger - or the claws will foul the collar. Fit the finger, look at which way
it closes, and set this accordingly; +y is the default. Everything else follows
automatically.

REACH. The collar hangs the pen tip about 165 mm below the wrist axis (the
model echoes the exact number). That is a long tool, and it shrinks the
drawable area a lot - run `python scripts/check_workspace.py --suggest` after
printing, and consider standing the arm on a ~60 mm riser, which roughly
doubles the drawable box.

Hardware: 1 x M3 socket-head screw 16-20 mm + 1 x M3 hex nut, plus the original
Braccio finger screws.

    openscad -o braccio_pen_finger_8mm.stl braccio_pen_finger_8mm.scad
*/

include <braccio_grip_lib.scad>

// Customizer parameters
pencil_diameter = 8.0;      // [6:0.1:12]
fit_clearance = 0.55;       // [0.2:0.05:1.0]
collar_wall = 3.4;          // [2.4:0.1:8]
pen_side = 1;               // [1:+y face, -1:-y face]

// Collar placement. It clears the finger face by clamp_gap, and stops short of
// the tip so the pencil - not the collar - is the lowest point.
clamp_gap = 1.5;
collar_top_z = -19;
collar_bottom_z = -57;
clamp_screw_z = -38;
// Web tying the collar back to the finger blade along its whole length: a
// cantilevered collar would twist the 5 mm blade every time the pen loads up.
web_thickness = 4.5;
web_top_z = -16;

function collar_offset(pencil_d, clearance, wall) =
    finger_half_thickness + clamp_gap
    + collar_diameter(pencil_d, clearance, wall) / 2;

function collar_y(pencil_d, clearance, wall) =
    finger_center_y + pen_side * collar_offset(pencil_d, clearance, wall);

// Wrist axis -> finger mounting face, from unoq_braccio_sim's URDF
// (60 mm to wrist_rotation + 30 mm to the finger).
wrist_axis_to_mount_mm = 90;

function wrist_pen_mm(protrusion = 20) =
    wrist_axis_to_mount_mm - collar_bottom_z + protrusion;

module braccio_pen_finger(
    pencil_d = pencil_diameter,
    clearance = fit_clearance,
    wall = collar_wall
) {
    height = collar_top_z - collar_bottom_z;
    // Slit faces away from the finger, so the collar can flex and the screw is
    // reachable from outside.
    slit_rotation = pen_side > 0 ? 90 : -90;

    assert(collar_bottom_z > finger_tip_z,
           "the collar would reach past the claw tip");

    difference() {
        union() {
            braccio_finger();
            translate([finger_center_x, collar_y(pencil_d, clearance, wall),
                       collar_bottom_z])
                rotate([0, 0, slit_rotation])
                    split_collar_solid(pencil_d, height, clearance, wall,
                                       clamp_screw_z - collar_bottom_z);
            side_web(collar_y(pencil_d, clearance, wall),
                     collar_bottom_z, web_top_z, web_thickness);
        }
        translate([finger_center_x, collar_y(pencil_d, clearance, wall),
                   collar_bottom_z])
            rotate([0, 0, slit_rotation])
                split_collar_cuts(pencil_d, height, clearance, wall,
                                  clamp_screw_z - collar_bottom_z);
    }
}

echo(str("pen finger: bore ", bore_diameter(pencil_diameter, fit_clearance),
         " mm, collar OD ", collar_diameter(pencil_diameter, fit_clearance,
                                            collar_wall),
         " mm, collar ", pen_side > 0 ? "+y" : "-y", " of the blade"));
echo(str("set config/workspace.yaml links.wrist_pen_mm to ~", wrist_pen_mm(20),
         " mm (pencil bottomed out, 20 mm proud of the collar)"));

braccio_pen_finger();
