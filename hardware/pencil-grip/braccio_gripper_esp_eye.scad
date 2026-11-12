/*
Braccio gripper camera - ESP-EYE
================================
A frame for an ESP-EYE v2.1 (firmware/esp_eye_camera) that stands on top of
the gripper block, just behind the finger pivots. The board is upright, camera
end down and USB end up, with the lens looking forward along the fingers and
down at the grasp point. The lead leaves upwards, back along the arm.

The saddle it stands on, the two ways of fixing it (cable ties or screws) and
the gripper block dimensions are in braccio_gripper_camera_lib.scad. Read the
note there about measuring the block before printing.

AIM. The lens is on the gripper's plane of symmetry. The optical axis crosses
the gripper centre line `pick_distance` in front of the finger mounting face;
the tilt follows from that and from `camera_height`.

    pick_distance = 90    braccio_gripper_esp_eye_near.stl
    pick_distance = 120   braccio_gripper_esp_eye.stl      (default)
    pick_distance = 180   braccio_gripper_esp_eye_far.stl

THE BOARD, as braccio_camera_finger.scad and braccio_wrist_camera_mount.scad
have it (measured there off docs/images/esp-eye.png), with the outline checked
against the 41 x 21 mm that Espressif's distributors publish:

    board            41.0 (long) x 21.0 (wide) x 1.6 mm PCB
    camera barrel    front face, ~7 mm diameter, ~6.5 mm proud, lens axis
                     29.5 mm from the USB edge, on the centreline
    micro-USB        back face, at the 21 mm short edge, centred
    ESP32 module     back face, ~3.3 mm proud
    BOOT / RST       on the long edges, 26.0 mm from the USB edge

    https://www.espressif.com/en/products/devkits/esp-eye/resources
    https://wiki.dfrobot.com/ESP-EYE%20Development%20Board%20SKU:%20DFR0620

Espressif's own layout files (the ESP-EYE V2.1 reference design archive on the
first page) were not opened for this part, so treat every feature position as
a measurement to repeat on your board. Print the fit piece first:

    openscad -D 'part="fit_test"' -o braccio_gripper_esp_eye_fit_test.stl \
        braccio_gripper_esp_eye.scad

HOW THE BOARD IS HELD. Its back rim rests on a bevelled ledge round a window
that leaves the ESP32 module and the USB socket clear. A fixed hook catches
the camera end of the front face and two sprung latches click over the long
edges near the USB end: put the camera end in under the hook, then press the
USB end home. The frame is open in the middle of the USB end for the plug, and
cut away beside BOOT and RST.

`pose = "gripper"` exports the part where it sits, in the wrist roll frame of
the URDF, for scripts/check_gripper_cameras.py. The default is the print
pose: the lens side of the frame on the bed, the back of the board up.
*/

include <braccio_gripper_camera_lib.scad>

part = "holder";            // [holder, fit_test, electronics]
pose = "print";             // [print, gripper]

// ---------------------------------------------------------------- the board
board_length = 41.0;        // [20:0.5:70]
board_width = 21.0;         // [10:0.5:40]
board_thick = 1.6;
lens_from_usb = 29.5;       // lens optical axis, from the USB short edge
buttons_from_usb = 26.0;    // BOOT / RST, on the long edges
barrel_proud = 6.5;         // camera barrel above the front face
barrel_d = 7.0;
back_module_thick = 3.3;    // ESP32 module on the back face
usb_plug = [20, 11, 7];     // ESTIMATE: micro-USB plug body
camera_fov_deg = 66;        // ESTIMATE: OV2640 module

// ---------------------------------------------------------------- the frame
board_fit = 0.3;            // clearance round the board
board_slide = 0.8;          // extra length, to get the camera end under its hook
wall = 3.6;                 // frame wall: latch, its gap and an unbroken band
ledge = 1.5;                // border of the window the board's back rests on
back_band = 1.2;            // straight part of the window, at the back face
board_slack = 0.25;         // play between the board and the hooks
front_zone = 1.6;           // frame depth in front of the board's front face
latch_beam = 1.5;
latch_height = 3.0;
latch_reach = 0.7;
latch_gap = 0.9;
latch_from = 26.0;          // latch root, measured up from the lens
latch_to = 8.0;             // latch tip
latch_hook_len = 6.0;
end_hook_width = 8.0;
end_hook_reach = 0.8;
usb_relief = 13.0;          // gap in the frame at the USB end
button_relief = 6.0;

// ------------------------------------------------- height and setback
camera_height = 18.5;       // optical axis above the centre line at the frame
face_z = 29;                // back of the frame, along the gripper

// ------------------------------------------------------------------ derived
// Frame coordinates: lens at the origin, x across the board, y up the board
// towards the USB end, z from the back of the frame towards the lens.
function pocket_x() = board_width / 2 + board_fit;
function pocket_y0() = -(board_length - lens_from_usb) - board_fit;
function pocket_y1() = lens_from_usb + board_fit + board_slide;
function board_back_w() = back_band + 1.0;
function board_front_w() = board_back_w() + board_thick;
function hook_w() = board_front_w() + board_slack;
function frame_depth() = hook_w() + front_zone;
function lens_w() = board_front_w() + barrel_proud;
bed_w = frame_depth();

module frame_solid() {
    translate([-pocket_x() - wall, pocket_y0() - wall, 0])
        cube([2 * (pocket_x() + wall), pocket_y1() - pocket_y0() + 2 * wall,
              frame_depth()]);
}

// Space the board and its plugs need. Cut from everything.
module board_space() {
    cy = (pocket_y0() + pocket_y1()) / 2;
    lx = 2 * pocket_x();
    ly = pocket_y1() - pocket_y0();
    // the window behind the board
    translate([-pocket_x() + ledge, pocket_y0() + ledge, -200])
        cube([lx - 2 * ledge, ly - 2 * ledge, 200 + back_band + 0.4]);
    // the bevel the board's back rim rests on
    translate([0, cy, back_band])
        linear_extrude(height = 1.3,
                       scale = [(lx - 2 * ledge + 2.6) / (lx - 2 * ledge),
                                (ly - 2 * ledge + 2.6) / (ly - 2 * ledge)])
            square([lx - 2 * ledge, ly - 2 * ledge], center = true);
    // the board, and everything in front of it
    translate([-pocket_x(), pocket_y0(), board_back_w()])
        cube([lx, ly, 200]);
    // the plug, at the USB end
    translate([-usb_relief / 2, pocket_y1() - 1, -200])
        cube([usb_relief, wall + 30, 400]);
    // BOOT and RST: the frame is cut away beside them, in front of the ledge
    for (sx = [-1, 1])
        translate([sx > 0 ? pocket_x() - 1 : -pocket_x() - wall - 30,
                   lens_from_usb - buttons_from_usb - button_relief / 2,
                   board_back_w() - 0.3])
            cube([wall + 31, button_relief, 200]);
    // each latch springs in a slot; the band of frame outside it is left whole
    for (sx = [-1, 1])
        translate([sx > 0 ? pocket_x() - 1 : -pocket_x() - latch_beam - latch_gap,
                   latch_to - 0.8, -1])
            cube([latch_beam + latch_gap + 1, latch_from - latch_to + 0.8, 200]);
}

module latch_one() {
    // drawn for the +x wall; the other is its mirror image
    // the beam
    translate([pocket_x() + 0.02, latch_to, frame_depth()]) mirror([0, 0, 1])
        cube([latch_beam - 0.02, latch_from - latch_to - 0.2, latch_height]);
    // its root, across the slot and into the frame beyond it
    translate([pocket_x() + 0.5, latch_from - 4, frame_depth()])
        mirror([0, 0, 1])
            cube([latch_beam + latch_gap + 0.5, 7, latch_height]);
    // the hook, with a lead-in on the side the board is pushed in from
    translate([0, latch_to + 0.6 + latch_hook_len, 0]) rotate([90, 0, 0])
        linear_extrude(height = latch_hook_len)
            polygon([[pocket_x() + latch_beam / 2, hook_w()],
                     [pocket_x() - latch_reach, hook_w()],
                     [pocket_x() - latch_reach,
                      frame_depth() - latch_reach - 0.3],
                     [pocket_x() + 0.3, frame_depth()],
                     [pocket_x() + latch_beam / 2, frame_depth()]]);
}

module hooks_all() {
    latch_one();
    mirror([1, 0, 0]) latch_one();
    // the fixed hook over the camera end of the front face
    translate([-end_hook_width / 2, pocket_y0() - 1, frame_depth()])
        mirror([0, 0, 1])
            cube([end_hook_width, 1 + end_hook_reach, front_zone]);
}

module frame_patch() {
    // The foot of the frame, kept just inside its own surfaces.
    translate([0, 0, frame_depth()]) mirror([0, 0, 1])
        translate([-pocket_x() - wall + 0.4, pocket_y0() - wall + 0.4, 0])
            cube([2 * (pocket_x() + wall) - 0.8, wall + 4,
                  frame_depth() - 0.3]);
}

module gusset() {
    hull() {
        frame_patch();
        pad_strip(-pocket_x() - wall + 0.5, pocket_x() + wall - 0.5, face_z - 6);
    }
}

module esp_eye_holder() {
    difference() {
        union() {
            frame_solid();
            saddle();
            gusset();
        }
        board_space();
        from_gripper() saddle_cuts();
    }
    hooks_all();
}

module esp_eye_fit_test() {
    difference() {
        frame_solid();
        board_space();
    }
    hooks_all();
}

// The board, its module, the camera and a plug as plain blocks. Not printed.
module esp_eye_electronics() {
    y0 = -(board_length - lens_from_usb);
    color([0.1, 0.1, 0.12])
        translate([-board_width / 2, y0, board_back_w()])
            cube([board_width, board_length, board_thick]);
    color([0.6, 0.6, 0.62])
        translate([-8, y0 + 8, board_back_w() - back_module_thick])
            cube([16, 24, back_module_thick + 0.2]);
    color([0.05, 0.05, 0.05])
        translate([0, 0, board_front_w() - 0.2])
            cylinder(h = barrel_proud + 0.2, d = barrel_d + 1, $fn = 48);
    color([0.75, 0.75, 0.78])
        translate([-usb_plug[1] / 2, lens_from_usb - 4,
                   board_back_w() - usb_plug[2]])
            cube([usb_plug[1], usb_plug[0] + 4, usb_plug[2] + 0.2]);
}

// For the pictures: holder and board where they sit on the gripper.
module esp_eye_on_gripper() {
    on_gripper() {
        color([0.2, 0.55, 0.75]) esp_eye_holder();
        esp_eye_electronics();
    }
}

module the_part() {
    if (part == "fit_test") esp_eye_fit_test();
    else if (part == "electronics") esp_eye_electronics();
    else esp_eye_holder();
}

assert(wall >= latch_beam + latch_gap + 1.2,
       "wall leaves under 1.2 mm of frame outside the latch slots");
assert(frame_depth() - latch_reach - 0.3 > hook_w(),
       "front_zone is too shallow for the latch hook and its lead-in");

// Lens and target in the wrist roll frame, for the clearance check.
echo(str("gripper_camera {",
    "\"holder\": \"esp_eye\"",
    ", \"pick_distance\": ", pick_distance,
    ", \"tilt_deg\": ", tilt_deg(),
    ", \"camera_height\": ", camera_height,
    ", \"face_z\": ", face_z,
    ", \"target\": [0, 0, ", target_z(), "]",
    ", \"axis\": ", optical_dir(),
    ", \"lens\": ", holder_origin() + lens_w() * optical_dir(),
    ", \"fov_deg\": ", camera_fov_deg,
    ", \"ties\": ", ties(),
    ", \"tie_tunnel\": ", [tie_tunnel_width, tie_tunnel_thick],
    ", \"block\": ", [block_centre_x, block_half_width, block_ref_z,
                      block_taper, block_top_y, block_thickness, jaw_fit + jaw],
    "}"));

if (pose == "gripper") on_gripper() the_part();
else to_print() the_part();
