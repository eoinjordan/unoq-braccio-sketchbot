/*
Braccio wrist camera mount - ESP-EYE on the wrist
=================================================
A small cradle on the Braccio wrist, replacing the big boxy
braccio_wrist_camera_bracket.stl (56 x 44 x 49 mm, 16.6 cm3).

It keeps that bracket's mounting interface EXACTLY - the servo-horn pattern of
four M2 screws on a 7 mm radius cross plus a 6.2 mm centre bore - so it bolts
straight onto the same face with the same screws.

SIZED FOR AN ESP-EYE v2.1 (firmware/esp_eye_camera). See
braccio_camera_finger.scad for the full dimensioned survey of the board; the
short version, measured off docs/images/esp-eye.png:

    board          41.0 x 21.0 x 1.6 mm PCB
    FRONT face     camera barrel ~6.5 mm proud, FFC connector, BOOT and RST -
                   nothing may lie against it
    BACK face      ESP32 module ~3.3 mm proud, and the micro-USB at the short
                   edge
    fixing         ONE 2.2 mm hole at (2.3, 38.0) from the USB-edge corner

SO THE BOARD IS HELD BY ITS EDGES, BACK OUTWARD. Two rails run the board's long
edges and hook over the front face; the ESP32 module hangs free in the gap
between them, which is why there is no backing plate. The front is left
completely open for the lens, the buttons and the flex. One M2 through the end
brace picks up the board's single hole to stop it sliding.

NO TILT. The IK holds the pen vertical (PEN_ELEVATION_DEG = -90), so in the
drawing pose a plate perpendicular to the wrist axis looks horizontally. Aiming
at the paper from here would need 74-90 degrees of cant, which would then ruin
the `person` pose. The plate stays perpendicular and the arm aims the camera by
rotating wrist_vertical - see `camera_poses` in config/workspace.yaml.

    openscad -o braccio_wrist_camera_mount.stl braccio_wrist_camera_mount.scad
*/

// --- servo-horn interface: measured off braccio_wrist_camera_bracket.stl.
//     Do not change these; they are what makes the part bolt on.
horn_hole_radius = 7.0;     // screws sit on a 7 mm radius cross
horn_hole_d = 2.4;          // M2 clearance
horn_head_d = 5.6;          // countersink for the screw heads
horn_head_depth = 1.6;
horn_center_bore_d = 6.4;   // clears the servo shaft
hub_diameter = 24;
hub_thickness = 3.6;        // leaves 2.0 mm under each screw head

// --- the board ---
board_length = 41.0;        // [20:0.5:70]
board_width = 21.0;         // [10:0.5:40]
board_thick = 1.6;
board_fit = 0.6;            // clearance, matching braccio_camera_finger.scad
hole_from_usb = 38.0;       // the board's one mounting hole, along the length
hole_from_edge = 2.3;       // ... and in from the long edge
buttons_from_usb = 26.0;    // BOOT / RST, on the long edges
button_relief = 6.0;        // notch so a rail never holds a button down

// --- the cradle ---
rail = 1.8;                 // rail wall
ledge = 1.5;                // shelf the PCB bears on
hook = 1.5;                 // lip over the board's front face
brace = 4.0;                // end brace at the camera end
m2_clear = 2.4;

// --- the arm ---
arm_thickness = 4;
arm_width = 12;
arm_reach = 14;             // radially out from the hub centre
arm_rise = 11;              // up from the hub face (was 20)
saddle_length = 14;         // how much of the board's length the arm carries

function pocket_l() = board_length + board_fit;
function pocket_w() = board_width + board_fit;
function cradle_z() = hub_thickness + arm_rise;   // plane the PCB back sits on

module hub() {
    difference() {
        cylinder(h = hub_thickness, d = hub_diameter, $fn = 96);
        translate([0, 0, -1])
            cylinder(h = hub_thickness + 2, d = horn_center_bore_d, $fn = 64);
        for (a = [0, 90, 180, 270])
            rotate([0, 0, a]) translate([horn_hole_radius, 0, -1]) {
                cylinder(h = hub_thickness + 2, d = horn_hole_d, $fn = 32);
                // Counterbore from the OUTER face, leaving 2.0 mm of material.
                translate([0, 0, hub_thickness + 1 - horn_head_depth])
                    cylinder(h = horn_head_depth + 1, d = horn_head_d, $fn = 40);
            }
    }
}

module arm() {
    // Hub face out to the cradle: a flat strap, filleted where it leaves the
    // hub so the load does not concentrate on one layer line.
    hull() {
        translate([-arm_width / 2, -arm_width / 2, hub_thickness - 0.01])
            cube([arm_width, arm_width, 0.01]);
        translate([arm_reach - arm_width / 2, -arm_width / 2,
                   cradle_z() - arm_thickness])
            cube([arm_width, arm_width, arm_thickness]);
    }
}

module cradle() {
    l = pocket_l();
    w = pocket_w();
    z0 = cradle_z();
    // Board long axis along x, centred on the arm; lens looks +z.
    x0 = arm_reach - l / 2;

    // Two rails down the long edges. Each is a ledge for the PCB to bear on
    // plus a hook over its front face; the ESP32 module on the back hangs free
    // in the gap between them, so no backing plate is needed at all.
    for (sy = [-1, 1])
        difference() {
            translate([x0, sy * (w / 2) - (sy > 0 ? 0 : rail), z0 - ledge])
                cube([l, rail, ledge + board_thick + hook]);
            // BOOT / RST relief
            translate([x0 + l - buttons_from_usb - button_relief / 2,
                       sy * (w / 2) - (sy > 0 ? 0 : rail) - 1, z0 - 1])
                cube([button_relief, rail + 2, ledge + board_thick + hook + 2]);
        }

    // Inward hooks at the top of each rail, over the board's front face.
    for (sy = [-1, 1])
        translate([x0 + l / 6, sy * (w / 2) - (sy > 0 ? 0 : hook),
                   z0 + board_thick])
            cube([l * 2 / 3, hook, hook]);

    // End brace at the CAMERA end only. The USB end stays completely open so a
    // micro-USB plug body has somewhere to go.
    translate([x0 - brace, -w / 2 - rail, z0 - ledge])
        cube([brace, w + 2 * rail, ledge + board_thick + hook]);

    // Ledges the PCB actually rests on, inboard of each rail.
    for (sy = [-1, 1])
        translate([x0, sy * (w / 2 - ledge) - (sy > 0 ? 0 : ledge), z0 - ledge])
            cube([l, ledge, ledge]);

    // Saddle: ties both rails back onto the arm. Without it the rails sit at
    // y = +-10.8 while the arm only spans +-6, so the cradle prints as a
    // separate loose piece - it did, until this was added.
    translate([arm_reach - saddle_length / 2, -w / 2 - rail, z0 - ledge])
        cube([saddle_length, w + 2 * rail, ledge]);
}

module board_fixing() {
    // One M2 up through the end brace into the board's single hole. It is an
    // anti-slide fixing, not the retention - the rails and hooks hold the board.
    l = pocket_l();
    x0 = arm_reach - l / 2;
    translate([x0 + l - hole_from_usb, -pocket_w() / 2 + hole_from_edge,
               cradle_z() - ledge - 1])
        cylinder(h = ledge + 4, d = m2_clear, $fn = 32);
}

module braccio_wrist_camera_mount() {
    difference() {
        union() {
            hub();
            arm();
            cradle();
        }
        board_fixing();
    }
}

echo(str("wrist camera mount: pocket ", pocket_l(), " x ", pocket_w(),
         " mm, board plane z = ", cradle_z(), " mm above the mating face"));

braccio_wrist_camera_mount();
