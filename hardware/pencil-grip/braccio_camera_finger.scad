/*
Braccio camera finger - ESP-EYE on a finger, claws still working
===============================================================
The companion to braccio_pen_finger.scad, built exactly the same way: the
ORIGINAL Braccio finger imported whole and untouched (same shape, same claw,
same mounting holes) with a camera cradle carried beside it. So:

  * the claws still close and grip, with the camera looking on;
  * the board is held by a clamp bar and lifts straight out;
  * fit this on one finger and braccio_pen_finger on the other, and the arm
    can see AND draw without swapping tools.

SIZED FOR AN ESP-EYE v2.1 (firmware/esp_eye_camera), measured off
docs/images/esp-eye.png:

    board            41.0 (long) x 21.0 (wide) x 1.6 mm PCB
    camera barrel    ~7 mm diameter, standing ~6.5 mm off the FRONT face,
                     lens axis 29.5 mm from the USB edge, on the centreline
    micro-USB        on the BACK face, at the 21 mm short edge, centred
    ESP32 module     on the BACK face, ~3.3 mm proud
    BOOT / RST       on the long edges, 26.0 mm from the USB edge
    FFC connector    front face, 11.1..16.4 mm from the USB edge, ~2 mm tall
    mounting hole    ONE only, 2.2 mm bore at (2.3, 38.0) from the USB-edge
                     corner - one hole gives no rotational constraint, so it is
                     used as an anti-slide peg, not as the fixing

WHICH WAY ROUND. The board's 41 mm axis runs ALONG the finger, USB end up
towards the wrist (so the lead routes up the arm) and camera end down towards
the claw. The lens looks outboard, normal to the blade; the arm aims it by
rotating wrist_vertical, which is why there is no tilt here - see
`camera_poses` in config/workspace.yaml.

WHICH SIDE. `camera_side` puts the cradle on the +y (1) or -y (-1) face, and it
must be the OUTSIDE face - the one that does not meet the opposing finger. Same
rule as the pen finger; if you fit both, give them the SAME sign so both tools
sit outboard and the claws still meet in the middle.

MEASURE YOUR BOARD if it is not an ESP-EYE. The `board_*` values below are all
you need to change.

    openscad -o braccio_camera_finger.stl braccio_camera_finger.scad
*/

include <braccio_grip_lib.scad>

// ---------------------------------------------------------------- the board
board_length = 41.0;        // [20:0.5:70] along the finger (z)
board_width = 21.0;         // [10:0.5:40] across the finger (x)
board_thick = 1.6;          // [0.8:0.1:3] PCB only
camera_fit = 0.6;           // clearance around the board

// Features, measured from the USB short edge along the board's long axis.
lens_from_usb = 29.5;       // lens optical axis
buttons_from_usb = 26.0;    // BOOT / RST plunger centres, on the long edges
back_module_thick = 3.3;    // ESP32 module standing off the BACK face
lens_diameter = 11.0;       // clear aperture for the barrel + its cone of view

// ---------------------------------------------------------------- the cradle
rail = 1.6;                 // rail wall thickness (was 2.4 - it is only a rail)
back_plate = 2.0;           // the spine: deliberately thicker than the rails
rail_depth = 5.0;           // rails stand this far off the plate (was 12.0)
hook = 1.6;                 // lip that overhangs the board's front face
ledge = 3.0;                // solid border around the back-plate window
spine = 6.0;                // solid band up the middle of the back plate
web_width = 13.0;           // blade-to-cradle web (was a 4.5 mm strip)
web_thick = 1.5;
button_relief = 5.0;        // notch in the rails so BOOT/RST are reachable
usb_relief = 13.0;          // opening at the USB end for the plug body
peg_diameter = 2.0;         // anti-slide peg into the board's one hole
camera_side = 1;            // [1:+y face, -1:-y face]
board_center_z = -30;       // where the board's centre sits along the finger
clamp_gap = 1.0;            // back plate stands this far off the blade face

// ------------------------------------------------------------------ derived
function pocket_w() = board_width + camera_fit;     // across the finger, x
function pocket_l() = board_length + camera_fit;    // along the finger, z
function cradle_y() =
    finger_center_y + camera_side * (finger_half_thickness + clamp_gap);
// z of the board's USB edge (up, towards the wrist) and camera edge (down).
function usb_z() = board_center_z + pocket_l() / 2;
function cam_z() = board_center_z - pocket_l() / 2;
function lens_z() = usb_z() - lens_from_usb;
function outer_w() = pocket_w() + 2 * rail;
function y_plate() = cradle_y();                    // inner face of the plate
function y_board() = y_plate() + back_plate;        // board's back face rests here
function y_out() = y_board() + rail_depth;          // outer face of the rails

module cradle_shell() {
    dir = camera_side;
    w = pocket_w();
    l = pocket_l();
    ow = outer_w();
    // Everything is built in +y then mirrored, so camera_side costs nothing.
    y0 = y_plate();
    depth = back_plate + rail_depth;

    difference() {
        // Plate + rails as one block, hollowed out below.
        translate([finger_center_x - ow / 2, y0, cam_z() - rail])
            cube([ow, depth, l + 2 * rail]);

        // The board pocket itself, open outboard.
        translate([finger_center_x - w / 2, y_board(), cam_z()])
            cube([w, rail_depth + 1, l]);

        // Window through the back plate: a 3 mm ledge for the PCB to bear on
        // and a 6 mm spine up the middle over the web, two panes either side.
        // This is where the ESP32 module on the BACK face lives, so the board
        // sits flat instead of rocking on it.
        pane_w = (w - spine) / 2 - ledge;
        pane_l = l - 2 * ledge;
        for (sx = [-1, 1])
            translate([finger_center_x + sx * (spine / 2 + ledge + pane_w) - (sx > 0 ? pane_w : 0),
                       y0 - 1, cam_z() + ledge])
                cube([pane_w, back_plate + 2, pane_l]);

        // Lens aperture: the barrel looks outboard through the rails' open
        // face, so this only needs to clear the plate for a back-lit board.
        translate([finger_center_x, y0 - 1, lens_z()])
            rotate([-90, 0, 0])
                cylinder(h = back_plate + 2, d = lens_diameter, $fn = 48);

        // BOOT and RST sit on the long edges: notch both rails so a wall never
        // holds a button down.
        for (sx = [-1, 1])
            translate([finger_center_x + sx * (w / 2) - (sx > 0 ? 0 : rail),
                       y0 - 1, usb_z() - buttons_from_usb - button_relief / 2])
                cube([rail, depth + 2, button_relief]);

        // The micro-USB is on the BACK face at the USB edge: leave that end
        // open wide enough for the plug body and a straight lead-in.
        translate([finger_center_x - usb_relief / 2, y0 - 1, usb_z() - 0.1])
            cube([usb_relief, depth + 2, rail + 0.2]);
    }

    // Hook lips: catch the board's front face along both long edges, middle
    // left open so a thumb can push the board back out.
    for (sx = [-1, 1])
        translate([finger_center_x + sx * (pocket_w() / 2) - (sx > 0 ? rail : 0),
                   y_out() - hook, board_center_z - l / 4])
            cube([rail + hook, hook, l / 2]);

    // Anti-slide peg into the board's single mounting hole. It carries no load
    // - the clamp bar does - it just stops the board creeping in the pocket.
    translate([finger_center_x - pocket_w() / 2 + 2.3,
               y_board(), usb_z() - 38.0])
        rotate([-90, 0, 0])
            cylinder(h = board_thick + 0.4, d = peg_diameter, $fn = 24);
}

module cradle_web() {
    // A plate, not a strip. The old 4.5 mm web bonded over just 38.9 mm2 and
    // hung half off the claw's edge, because the blade's mid-x sweeps while the
    // web sat fixed at finger_center_x. 13 mm spanning x 6..19 tracks the blade
    // and takes the bonded area to ~147 mm2.
    dir = camera_side;
    y_in = finger_center_y + dir * finger_half_thickness;
    translate([finger_center_x - web_width / 2,
               dir > 0 ? y_in : y_in - web_thick,
               cam_z() + 4])
        cube([web_width, clamp_gap + web_thick, pocket_l() - 8]);
}

module clamp_screw() {
    // One M3 above the board, through the plate and the blade, so the cradle
    // pulls off the finger without disturbing the Braccio mounting screws.
    translate([finger_center_x, cradle_y(), usb_z() + rail + 4])
        along_y_cylinder(finger_half_thickness * 2 + back_plate + rail_depth + 12,
                         m3_clearance_diameter);
}

module braccio_camera_finger() {
    assert(cam_z() - rail > finger_tip_z,
           "the camera cradle would reach past the claw tip");

    difference() {
        union() {
            braccio_finger();
            if (camera_side > 0) cradle_shell();
            else mirror([0, 1, 0]) translate([0, -2 * finger_center_y, 0]) cradle_shell();
            cradle_web();
        }
        clamp_screw();
    }
}

echo(str("camera finger: board ", board_length, " x ", board_width,
         " along the finger, cradle ", camera_side > 0 ? "+y" : "-y",
         ", outer width ", outer_w(), " mm, y out ", y_out()));

braccio_camera_finger();
