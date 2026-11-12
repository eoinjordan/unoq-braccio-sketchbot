/*
Braccio gripper camera - XIAO ESP32S3 Sense on the Round Display for XIAO
=========================================================================
A cradle for the Seeed Studio Round Display for XIAO with a XIAO ESP32S3 Sense
plugged into the socket on its back, assembled the normal way. It stands on
top of the gripper block, just behind the finger pivots, like a small round
face: the camera looks forward along the fingers and down at the grasp point,
and the screen is directly behind it, facing back up the arm towards the
people watching.

The saddle it stands on, the two ways of fixing it (cable ties or screws) and
the gripper block dimensions are in braccio_gripper_camera_lib.scad. Read the
note there about measuring the block before printing.

AIM. The lens is on the gripper's plane of symmetry. The XIAO's camera is
15 mm off the centre of the display, towards the USB-C end, so the display
sits 15 mm to one side with the USB-C socket pointing across the gripper. The
optical axis crosses the gripper centre line `pick_distance` in front of the
finger mounting face; the tilt follows from that and from `camera_height`.

    pick_distance = 90    braccio_gripper_xiao_round_display_near.stl
    pick_distance = 120   braccio_gripper_xiao_round_display.stl      (default)
    pick_distance = 180   braccio_gripper_xiao_round_display_far.stl

`camera_height` (optical axis above the gripper centre line where it leaves
the screen face) and `face_z` (how far along the gripper the screen face is)
are the height and setback. The defaults put the ring's wall into the pad, as
low as the display allows.

WHERE THE NUMBERS COME FROM

  Round Display for XIAO
    [brd]   Seeed's board file, v1.1:
            https://files.seeedstudio.com/wiki/round_display_for_xiao/SeeedStudio_Round_Display_for_XIAO_v1.1_SCH&PCB_230407.zip
            Board outline, connector, switch, card slot and hole positions.
    [case]  Seeed's own printed case for this board pair:
            https://files.seeedstudio.com/wiki/round_display_for_xiao/Seeed_Studio-XIAO-ESP32-S3-Sense-Case-With-Round-Screen.stl
            44.0 mm board cavity, 38.5 mm screen opening, 48.0 mm outside.
    [wiki]  https://wiki.seeedstudio.com/get_start_round_display/
            "39mm disc", JST 1.25 battery connector, switch, card slot.
  XIAO ESP32S3 Sense
    [xiao]  https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/
            21 x 17.8 mm board, 15 mm tall with the camera board fitted.

  Values marked ESTIMATE were not found in a published drawing. Print the fit
  piece first and measure the board against them before printing the holder:

    openscad -D 'part="fit_test"' -o braccio_gripper_xiao_round_display_fit_test.stl \
        braccio_gripper_xiao_round_display.scad

`pose = "gripper"` exports the part where it sits, in the wrist roll frame of
the URDF, for scripts/check_gripper_cameras.py. The default is the print
pose: rear rim of the ring on the bed, screen side up.
*/

include <braccio_gripper_camera_lib.scad>

part = "holder";            // [holder, fit_test, electronics]
pose = "print";             // [print, gripper]

// ------------------------------------------------- Round Display for XIAO
display_pcb_d = 43.1;       // [brd] outline is a 21.53 mm radius circle
display_pcb_thick = 1.6;    // ESTIMATE: the cavity step in [case] is 1.6 mm
display_glass_d = 39.0;     // [wiki] "39mm disc", read as the cover glass
display_glass_proud = 3.0;  // ESTIMATE: glass face above the board's front face
// Angles round the board, seen from the back, 0 at the XIAO's USB-C end and
// counted towards the display flex. All from [brd]: battery connector at 0,
// slide switch at 153.8, microSD at 180, flex notch at 90.
socket_height = 5.0;        // [brd] J4/J5 package "H7-2.54-18.28X2.5X5MM"

// ------------------------------------------------- XIAO ESP32S3 Sense
xiao_length = 21.0;         // [xiao]
xiao_width = 17.8;          // [xiao]
xiao_stack = 15.0;          // [xiao] board underside to the top of the camera
xiao_pin_spacer = 2.5;      // ESTIMATE: plastic of a 2.54 mm pin header
xiao_centre_from_display_centre = 9.65;   // [brd] J4/J5, towards the USB-C end
usb_plug = [22, 12, 7];     // ESTIMATE: USB-C plug body, length x width x thick
// The camera sits over the USB-C end of the XIAO (Seeed's 3D model picture).
lens_from_display_centre = 15.0;  // ESTIMATE, towards the USB-C end
camera_fov_deg = 66;        // ESTIMATE: OV2640 module; later units differ

// ------------------------------------------------- the cradle
board_fit = 0.3;            // radial clearance round the board
wall = 4.0;                 // ring wall: latch, its gap and an unbroken band
screen_opening_d = 40.0;    // 0.5 mm clear of the glass all round
bezel_front = 1.2;          // straight part of the opening, at the screen face
board_slack = 0.25;         // play between the board and the latch hooks
rear_zone = 1.6;            // ring depth behind the board's back face
latch_beam = 1.5;           // radial thickness of a latch
latch_height = 3.0;
latch_reach = 0.7;          // how far a hook stands over the board's rim
latch_gap = 0.9;            // room behind a latch for it to spring outwards
latch_hook_arc = 10;        // degrees
// [anchor angle, tip angle] of each latch, clear of the notches below.
latches = [[312, 345], [112, 140], [205, 250]];
// Notch edges must not land on a latch slot's edge (the slot runs 2 degrees
// past the latch tip): start each notch inside the slot next to it.
battery_notch = [346, 14];  // rear of the ring cut away for the JST plug
switch_card_notch = [141, 196];   // gap in the ring at the switch and the card
foot_sector = [218, 322];   // the part of the ring that grows out of the pad

// ------------------------------------------------- height and setback
camera_height = 29;         // optical axis above the centre line at the screen
face_z = 27;                // screen face, along the gripper from the roll frame

// ------------------------------------------------------------------ derived
function pocket_r() = display_pcb_d / 2 + board_fit;
function ring_r() = pocket_r() + wall;
function opening_r() = screen_opening_d / 2;
function cone_end_w() = bezel_front + pocket_r() - opening_r();
function board_front_w() = bezel_front + display_pcb_d / 2 - opening_r();
function board_back_w() = board_front_w() + display_pcb_thick;
function hook_w() = board_back_w() + board_slack;
function ring_depth() = hook_w() + rear_zone;
function lens_w() =
    board_back_w() + socket_height + xiao_pin_spacer + xiao_stack;
bed_w = ring_depth();

// The holder's origin is the centre of the display. It is set to one side of
// the gripper so that the lens, not the display, is on the optical axis.
function holder_origin() =
    [-lens_from_display_centre, camera_height, face_z];

module ring_solid() {
    difference() {
        cylinder(h = ring_depth(), r = ring_r(), $fn = 144);
        translate([0, 0, -1])
            cylinder(h = ring_depth() + 2, r = opening_r() - 3, $fn = 144);
    }
}

// A piece of the ring for the gusset to grow out of, kept just inside the
// ring's own surfaces so the two never share a face.
module ring_patch(range) {
    intersection() {
        translate([0, 0, ring_depth()]) mirror([0, 0, 1]) difference() {
            cylinder(h = ring_depth() - 0.3, r = ring_r() - 0.4, $fn = 144);
            translate([0, 0, -1])
                cylinder(h = ring_depth() + 2, r = opening_r() - 2, $fn = 144);
        }
        sector(range[0], range[1], ring_r() + 1, -1, ring_depth() + 1);
    }
}

// Space the display, the screen and the plugs need. Cut from everything.
module display_space() {
    // In front of the screen nothing may overhang the glass; then the 45
    // degree seat the board's front rim rests on; then the board itself and
    // everything behind it.
    rotate_extrude($fn = 144)
        polygon([[0, -200], [opening_r(), -200], [opening_r(), bezel_front],
                 [pocket_r(), cone_end_w()], [pocket_r(), 200], [0, 200]]);
    // The battery plug comes in past the rim: the rear of the ring is cut
    // away for it and the band in front is left, a 12 mm bridge when printed.
    sector(battery_notch[0], battery_notch[1], ring_r() + 30,
           board_back_w() - 0.3, 200);
    // The switch and the card are reached through a gap right through the ring.
    sector(switch_card_notch[0], switch_card_notch[1], ring_r() + 30, -1, 200);
    // Each latch springs in a slot in the ring; the band outside the slot is
    // left whole.
    for (l = latches)
        sector(min(l), max(l) + 2, pocket_r() + latch_beam + latch_gap,
               -1, 200);
}

module arc_band(a0, a1, r0, r1, z0, z1) {
    rotate([0, 0, min(a0, a1)])
        rotate_extrude(angle = abs(a1 - a0), $fn = 144)
            translate([r0, z0]) square([r1 - r0, z1 - z0]);
}

module latch(anchor, tip) {
    dir = tip > anchor ? 1 : -1;
    z0 = ring_depth() - latch_height;
    // the beam
    arc_band(anchor + dir * 0.5, tip, pocket_r(), pocket_r() + latch_beam,
             z0, ring_depth());
    // its root, across the slot and into the band of the ring outside it
    arc_band(anchor - dir * 3, anchor + dir * 4, pocket_r() + 0.5,
             pocket_r() + latch_beam + latch_gap + 0.5, z0, ring_depth());
    // the hook, with a lead-in on the side the board is pushed in from
    rotate([0, 0, min(tip - dir * (latch_hook_arc + 0.6), tip - dir * 0.6)])
        rotate_extrude(angle = latch_hook_arc, $fn = 144)
            polygon([[pocket_r() + latch_beam / 2, hook_w()],
                     [pocket_r() - latch_reach, hook_w()],
                     [pocket_r() - latch_reach,
                      ring_depth() - latch_reach - 0.3],
                     [pocket_r() + 0.3, ring_depth()],
                     [pocket_r() + latch_beam / 2, ring_depth()]]);
}

module latches_all() {
    for (l = latches) latch(l[0], l[1]);
}

module gusset() {
    // From the lower part of the ring down into the pad beneath it.
    hull() {
        ring_patch(foot_sector);
        pad_strip(-lens_from_display_centre - 16,
                  -lens_from_display_centre + 16, face_z - 6);
    }
}

module xiao_holder() {
    difference() {
        union() {
            ring_solid();
            saddle();
            gusset();
        }
        display_space();
        from_gripper() saddle_cuts();
    }
    latches_all();
}

module xiao_fit_test() {
    difference() {
        ring_solid();
        display_space();
    }
    latches_all();
}

// The display, the XIAO and a USB-C plug as plain blocks. Not printed: it is
// what the pictures show in the cradle and what the clearance check keeps
// clear of the gripper along with the holder itself.
module xiao_electronics() {
    xiao_w0 = board_back_w() + socket_height + xiao_pin_spacer;
    x0 = xiao_centre_from_display_centre - xiao_length / 2;
    union() {
        color([0.08, 0.08, 0.1])
            translate([0, 0, board_front_w() - display_glass_proud])
                cylinder(h = display_glass_proud + 0.2, d = display_glass_d,
                         $fn = 96);
        color([0.1, 0.35, 0.2])
            translate([0, 0, board_front_w()])
                cylinder(h = display_pcb_thick, d = display_pcb_d, $fn = 96);
        color([0.15, 0.15, 0.15])
            translate([x0, -xiao_width / 2, board_back_w() - 0.2])
                cube([xiao_length, xiao_width, xiao_w0 - board_back_w() + 0.4]);
        color([0.1, 0.35, 0.2])
            translate([x0, -xiao_width / 2, xiao_w0])
                cube([xiao_length, xiao_width, xiao_stack - 4]);
        color([0.05, 0.05, 0.05])
            translate([lens_from_display_centre, 0, xiao_w0 + xiao_stack - 4.5]) {
                translate([-4.5, -4.5, 0]) cube([9, 9, 2.5]);
                cylinder(h = 4.5, d = 7, $fn = 48);
            }
        color([0.75, 0.75, 0.78])
            translate([x0 + xiao_length - 1, -usb_plug[1] / 2, xiao_w0 - 2])
                cube(usb_plug + [1, 0, 0]);
    }
}

// For the pictures: holder and boards where they sit on the gripper.
module xiao_on_gripper() {
    on_gripper() {
        color([0.2, 0.55, 0.75]) xiao_holder();
        xiao_electronics();
    }
}

module the_part() {
    if (part == "fit_test") xiao_fit_test();
    else if (part == "electronics") xiao_electronics();
    else xiao_holder();
}

assert(wall >= latch_beam + latch_gap + 1.2,
       "wall leaves under 1.2 mm of ring outside the latch slots");
assert(ring_depth() - latch_reach > hook_w(),
       "rear_zone is too shallow for the latch hook and its lead-in");
assert(camera_height - pocket_r() >= pad_top_y() + 0.5,
       "camera_height puts the display board into the saddle pad");

// Lens and target in the wrist roll frame, for the clearance check.
echo(str("gripper_camera {",
    "\"holder\": \"xiao_round_display\"",
    ", \"pick_distance\": ", pick_distance,
    ", \"tilt_deg\": ", tilt_deg(),
    ", \"camera_height\": ", camera_height,
    ", \"face_z\": ", face_z,
    ", \"target\": [0, 0, ", target_z(), "]",
    ", \"axis\": ", optical_dir(),
    ", \"lens\": ", [0, camera_height, face_z] + lens_w() * optical_dir(),
    ", \"fov_deg\": ", camera_fov_deg,
    ", \"ties\": ", ties,
    ", \"tie_tunnel\": ", [tie_tunnel_width, tie_tunnel_thick],
    ", \"block\": ", [block_centre_x, block_half_width, block_ref_z,
                      block_taper, block_top_y, block_thickness, jaw_fit + jaw],
    "}"));

if (pose == "gripper") on_gripper() the_part();
else to_print() the_part();
