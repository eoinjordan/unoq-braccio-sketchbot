/*
Braccio wrist camera mount - minimal
====================================
A small camera plate on the Braccio wrist, replacing the big boxy
braccio_wrist_camera_bracket.stl (16.6 cm3, 56 x 44 x 49 mm) with something
about a third of the size that does the same job.

It keeps that bracket's mounting interface exactly - the servo-horn pattern
measured off it: four M2 screws on a 7 mm radius cross plus a 6.2 mm centre
bore - so it bolts straight onto the same place with the same screws.

The plate takes whatever camera you have:

  * ESP32-CAM / ESP-EYE - sits on the ledge, two M2 holes at `board_hole_pitch`,
    lens looking through the aperture;
  * a USB webcam module - strap it on through the two slots with a zip tie or a
    loop of elastic, which also suits anything with an odd hole pattern;
  * anything else - the face is flat, so double-sided tape works.

`tilt` cants the plate towards the paper; 0 looks straight out along the arm.

    openscad -o braccio_wrist_camera_mount.stl braccio_wrist_camera_mount.scad
    openscad -o tilted.stl -D tilt=20 braccio_wrist_camera_mount.scad
*/

$fa = 3;
$fs = 0.35;

// --- mounting interface (measured from braccio_wrist_camera_bracket.stl) ---
horn_hole_radius = 7.0;     // screws sit on a 7 mm radius cross
horn_hole_d = 2.4;          // M2 clearance
horn_head_d = 5.6;          // countersink for the screw heads
horn_head_depth = 1.6;
horn_center_bore_d = 6.4;   // clears the servo shaft
hub_diameter = 24;
hub_thickness = 3.6;

// --- camera plate ---
plate_width = 32;           // [20:1:60]
plate_height = 26;          // [16:1:50]
plate_thickness = 3.0;
lens_diameter = 14;         // [6:0.5:24] clear aperture
ledge_depth = 4;            // shelf the board rests on
board_hole_pitch = 20;      // [10:1:40] M2 pair, set to your board
board_hole_d = 2.2;
strap_slot = [11, 2.8];     // zip tie / elastic slots either side
tilt = 0;                   // [0:5:45] degrees, towards the paper

// --- arm ---
arm_thickness = 4;
arm_width = 12;
arm_reach = 16;             // radially out from the hub centre
arm_rise = 20;              // up from the hub face

module hub() {
    difference() {
        cylinder(h = hub_thickness, d = hub_diameter);
        // Servo shaft.
        translate([0, 0, -1])
            cylinder(h = hub_thickness + 2, d = horn_center_bore_d);
        // Four M2 screws with heads countersunk into the top face.
        for (a = [0, 90, 180, 270])
            rotate([0, 0, a]) translate([horn_hole_radius, 0, -1]) {
                cylinder(h = hub_thickness + 2, d = horn_hole_d);
                translate([0, 0, hub_thickness + 1 - horn_head_depth])
                    cylinder(h = horn_head_depth + 1, d = horn_head_d);
            }
    }
}

module arm() {
    // Hub face out to the plate: a flat strap, filleted where it leaves the
    // hub so the load does not concentrate on one layer line.
    hull() {
        translate([0, -arm_width / 2, hub_thickness - 0.01])
            cube([hub_diameter / 2 - 1, arm_width, 0.01]);
        translate([arm_reach - arm_thickness, -arm_width / 2,
                   hub_thickness + arm_rise - 6])
            cube([arm_thickness, arm_width, 6]);
    }
}

module plate_body() {
    // Plate stands in the y-z plane, facing +x.
    difference() {
        union() {
            translate([0, -plate_width / 2, 0])
                cube([plate_thickness, plate_width, plate_height]);
            // Ledge for the board to sit on.
            translate([0, -plate_width / 2, 0])
                cube([plate_thickness + ledge_depth, plate_width, plate_thickness]);
        }
        // Lens aperture.
        translate([-1, 0, plate_height / 2 + 2])
            rotate([0, 90, 0])
                cylinder(h = plate_thickness + 2, d = lens_diameter);
        // Board screw pair.
        for (s = [-1, 1])
            translate([-1, s * board_hole_pitch / 2, plate_height / 2 + 2])
                rotate([0, 90, 0])
                    cylinder(h = plate_thickness + 2, d = board_hole_d);
        // Strap slots, outboard of the board.
        for (s = [-1, 1])
            translate([-1, s * (plate_width / 2 - strap_slot[1] - 1.5)
                       - strap_slot[1] / 2, plate_height / 2 - strap_slot[0] / 2])
                cube([plate_thickness + 2, strap_slot[1], strap_slot[0]]);
    }
}

module braccio_wrist_camera_mount() {
    union() {
        hub();
        arm();
        translate([arm_reach - arm_thickness, 0, hub_thickness + arm_rise - 6])
            rotate([0, -tilt, 0])
                plate_body();
    }
}

echo(str("wrist camera mount: plate ", plate_width, " x ", plate_height,
         " mm, aperture ", lens_diameter, " mm, tilt ", tilt, " deg"));

braccio_wrist_camera_mount();
