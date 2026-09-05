/*
Braccio camera finger - wrist camera that keeps the claws
========================================================
The companion to braccio_pen_finger.scad, built exactly the same way: the
ORIGINAL Braccio finger imported whole and untouched (same shape, same claw,
same mounting holes) with a camera cradle carried beside it. So:

  * the claws still close and grip, with the camera looking on;
  * the camera is held by one M3 screw through a clamp bar and lifts straight
    out when you want the finger bare;
  * fit this on one finger and braccio_pen_finger on the other, and the arm
    can see AND draw without swapping tools.

The cradle is sized for an ESP-EYE (firmware/esp_eye_camera), lens facing the
same way the pen points, so `camera_poses` in config/workspace.yaml aims it at
the visitor and at the paper. MEASURE YOUR BOARD - a USB webcam module or an
ESP32-CAM is a different size, and the three `camera_*` values below are all
you need to change.

WHICH SIDE. `camera_side` puts the cradle on the +y (1) or -y (-1) face, and it
must be the OUTSIDE face - the one that does not meet the opposing finger. Same
rule as the pen finger; if you fit both, give them opposite... no: give them the
SAME sign, so both tools sit outboard and the claws still meet in the middle.

    openscad -o braccio_camera_finger.stl braccio_camera_finger.scad
*/

include <braccio_grip_lib.scad>

// Camera board, millimetres. Defaults: ESP-EYE (41 x 21 mm, ~12 mm deep with
// the lens barrel and headers).
camera_width = 41.0;        // [15:0.5:60] along the finger's x
camera_height = 21.0;       // [10:0.5:40] along z
camera_depth = 12.0;        // [5:0.5:30] standing off the finger
camera_fit = 0.6;           // clearance around the board
wall = 2.4;                 // cradle wall
lip = 2.0;                  // retaining lip over the board edges
lens_diameter = 14.0;       // clear aperture in the back plate
camera_side = 1;            // [1:+y face, -1:-y face]
camera_center_z = -34;      // where the board sits along the finger
cable_slot = 9.0;           // notch for the ribbon/USB lead

// The cradle back plate stands this far off the blade face.
clamp_gap = 1.0;

function pocket_w() = camera_width + camera_fit;
function pocket_h() = camera_height + camera_fit;
function cradle_y() =
    finger_center_y + camera_side * (finger_half_thickness + clamp_gap);

module camera_cradle() {
    w = pocket_w();
    h = pocket_h();
    d = camera_depth;
    outer_w = w + 2 * wall;
    outer_h = h + 2 * wall;
    // Local frame: the back plate lies in the x-z plane, the board stacks
    // outwards along +y, so the lens looks along the finger (-z is "down").
    y0 = cradle_y();
    dir = camera_side;

    difference() {
        // Shell: back plate + surrounding walls.
        translate([finger_center_x - outer_w / 2,
                   dir > 0 ? y0 : y0 - (d + wall),
                   camera_center_z - outer_h / 2])
            cube([outer_w, d + wall, outer_h]);

        // Board pocket, open on the outboard face.
        translate([finger_center_x - w / 2,
                   dir > 0 ? y0 + wall : y0 - (d + wall),
                   camera_center_z - h / 2])
            cube([w, d + 0.1, h]);

        // Lens aperture through the back plate.
        translate([finger_center_x, y0 - dir * 1, camera_center_z])
            rotate([90, 0, 0])
                cylinder(h = wall + 4, d = lens_diameter, center = true);

        // Cable notch out of the bottom edge.
        translate([finger_center_x - cable_slot / 2,
                   dir > 0 ? y0 : y0 - (d + wall),
                   camera_center_z - outer_h / 2 - 0.1])
            cube([cable_slot, d + wall, wall + 0.2]);
    }

    // Retaining lips: catch the board's long edges so it cannot fall out, with
    // the middle left open so you can push it back through with a thumb.
    for (sz = [-1, 1])
        translate([finger_center_x - w / 4,
                   dir > 0 ? y0 + wall + d - lip : y0 - (d + wall) + wall,
                   camera_center_z + sz * (h / 2) - (sz > 0 ? 0 : wall)])
            cube([w / 2, lip, wall]);
}

module camera_clamp_screw() {
    // One M3 through the back plate and the web, so the cradle can be pulled
    // off the finger without disturbing the Braccio mounting screws.
    y0 = cradle_y();
    translate([finger_center_x, y0, camera_center_z + pocket_h() / 2 + wall + 4])
        along_y_cylinder(finger_half_thickness * 2 + camera_depth + 12,
                         m3_clearance_diameter);
}

module braccio_camera_finger() {
    top_z = camera_center_z + pocket_h() / 2 + wall + 8;
    bottom_z = camera_center_z - pocket_h() / 2 - wall;

    assert(bottom_z > finger_tip_z,
           "the camera cradle would reach past the claw tip");

    difference() {
        union() {
            braccio_finger();
            camera_cradle();
            side_web(cradle_y(), bottom_z, top_z, 4.5);
        }
        camera_clamp_screw();
    }
}

echo(str("camera finger: pocket ", pocket_w(), " x ", pocket_h(), " x ",
         camera_depth, " mm, cradle ", camera_side > 0 ? "+y" : "-y",
         " of the blade"));

braccio_camera_finger();
