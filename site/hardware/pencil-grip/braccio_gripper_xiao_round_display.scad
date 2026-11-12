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

THE COVER (`part = "cover"`). A cup over the lens side that encloses the XIAO,
the camera board and a small LiPo, with SKETCHBOT let into its face.

  fixing     four sprung arms reach past the outside of the ring and hook over
             its screen-side edge. No tools, and the holder needs no matching
             feature. Lever the arms out with a fingernail to take it off; the
             display comes out as before once the cover is off.
  lens       a collar round the camera barrel steadies the camera board, and
             the window widens at 45 degrees from the collar so the cover
             stays out of the picture.
  battery    a pocket between two ribs for a LiPo standing on its long edge
             beside the XIAO. Defaults are for a 402030 cell (4.0 x 20 x 30 mm,
             about 200 mAh). MEASURE YOUR CELL and set battery_t, battery_w
             and battery_l. The cover's face and the back of the display
             close the pocket, so the cell cannot fall out.
  openings   one slot at the USB-C end for the plug, the battery lead (the
             display's JST connector is under the USB-C socket and its plug
             goes in from the rim) and a pin to the XIAO's buttons; two small
             slots beside it for a 2.5 mm tie as strain relief; four vent
             slots along the top, which also keep the microphone and the LED
             from being sealed in. The display's slide switch and card slot
             are in the ring, below the cover, and stay reachable.
  floor      the cup is cut flat underneath, above the finger bases, so the
             shape depends on the tilt: export the cover with the same
             pick_distance as the holder it goes on.

The lettering is recessed 0.6 mm, because the cover prints face down and
raised letters would need supports. `cover_text` is the word; the font is
Liberation Sans Bold, which ships with OpenSCAD.

`pose = "gripper"` exports the part where it sits, in the wrist roll frame of
the URDF, for scripts/check_gripper_cameras.py. The default is the print
pose: holder with the rear rim of the ring on the bed, screen side up; cover
face down.
*/

include <braccio_gripper_camera_lib.scad>

part = "holder";            // [holder, fit_test, cover, cover_fit_test, electronics]
pose = "print";             // [print, gripper, cradle]

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

// ------------------------------------------------- the cover
cover_wall = 1.6;
cover_gap = 0.2;            // between the cover's rim and the back of the ring
cover_text = "SKETCHBOT";
cover_font = "Liberation Sans:style=Bold";  // bundled with OpenSCAD
cover_text_size = 5.5;      // cap height; strokes come out about 1 mm wide
cover_text_depth = 0.6;     // recessed, three 0.2 mm layers
cover_text_y = 10.5;        // baseline above the display centre
lens_recess = 1.0;          // lens tip behind the inside of the cover's face
window_r = 4.5;             // collar bore: 7 mm barrel + 1 mm all round
collar_r = 6.5;
floor_y = 3.0;              // wrist roll frame: underside of the cover, above the finger bases
// Battery: a 402030 LiPo by default. MEASURE YOUR CELL.
battery_t = 4.0;            // thickness
battery_w = 20.0;           // width, stands up from the display
battery_l = 30.0;           // length, across the cover
battery_fit = 0.5;
battery_x = -7.0;           // centre of the pocket, on the side away from the XIAO
battery_rib = 1.2;
battery_over_board = 3.2;   // ESTIMATE: tallest part on the display's back (RTC cell holder 2.9)
// Snap arms: angle round the ring of each, clear of the notches and the foot.
snap_angles = [40, 118, 207, 332];
snap_arc = 15.4;            // degrees; keeps the arm edges off the ring's 2.5 degree facets
snap_thick = 1.4;
snap_reach = 0.6;           // hook over the ring's screen-side edge
snap_root_z = 13;           // arms are free below this, about 14 mm long
plug_slot = [19, 12.5];     // width across the XIAO, height above the ring
tie_slot_angles = [52, 64];
vent_angles = [76, 86, 96, 106];

// ------------------------------------------------- height and setback
camera_height = 30.5;       // optical axis above the centre line at the screen
face_z = 33;                // screen face, along the gripper from the roll frame

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

// ------------------------------------------------------------------ the cover
function xiao_w0() = board_back_w() + socket_height + xiao_pin_spacer;
function camera_top_w() = xiao_w0() + xiao_stack - 2.0;
function battery_w0() = board_back_w() + battery_over_board;
function cover_rim_w() = ring_depth() + cover_gap;
function cover_in_w() =
    max(lens_w() + lens_recess, battery_w0() + battery_w + 0.3);
function cover_out_w() = cover_in_w() + cover_wall;

// Everything above the cover's flat underside, in the holder's frame.
module above_floor(extra) {
    from_gripper() translate([-200, floor_y + extra, -200]) cube(400);
}

module cover_shell() {
    difference() {
        intersection() {
            translate([0, 0, cover_rim_w()])
                cylinder(h = cover_out_w() - cover_rim_w(), r = ring_r(),
                         $fn = 144);
            above_floor(0);
        }
        intersection() {
            translate([0, 0, cover_rim_w() - 1])
                cylinder(h = cover_in_w() - cover_rim_w() + 1,
                         r = ring_r() - cover_wall, $fn = 144);
            above_floor(cover_wall);
        }
    }
}

module cover_inside_parts() {
    // collar round the camera barrel
    translate([lens_from_display_centre, 0, camera_top_w() + 0.25])
        cylinder(h = cover_in_w() - camera_top_w() + 0.3, r = collar_r,
                 $fn = 64);
    // battery pocket: a rib each side of the cell and a stop at each end
    px = battery_t + battery_fit;
    py = battery_l + battery_fit;
    z0 = battery_w0() + 5;
    for (sx = [-1, 1])
        translate([battery_x + sx * (px / 2 + battery_rib / 2) - battery_rib / 2,
                   -py / 2 - battery_rib, z0])
            cube([battery_rib, py + 2 * battery_rib, cover_in_w() - z0 + 0.5]);
    for (sy = [-1, 1])
        translate([battery_x - px / 2 - 0.5,
                   sy * (py / 2 + battery_rib / 2) - battery_rib / 2, z0])
            cube([px + 1, battery_rib, cover_in_w() - z0 + 0.5]);
}

module snap_arm(a) {
    r0 = ring_r() + 0.3;
    r1 = r0 + snap_thick;
    rotate([0, 0, a - snap_arc / 2])
        rotate_extrude(angle = snap_arc, $fn = 144) {
            // the arm and its hook, with a lead-in for pushing the cover on
            polygon([[r1, snap_root_z + 3], [r1, -1.7], [r0, -1.7],
                     [ring_r() - snap_reach, -1.0],
                     [ring_r() - snap_reach, -0.25], [r0, -0.25],
                     [r0, snap_root_z + 3]]);
            // the root, chamfered underneath so it prints without support
            polygon([[ring_r() - 0.6, snap_root_z], [r1 + 0.3, snap_root_z],
                     [r1 + 0.3, snap_root_z + 3],
                     [ring_r() - 0.6, snap_root_z + 5.5]]);
        }
}

module cover_cuts() {
    // lens window: straight through the collar, then opening at 45 degrees
    translate([lens_from_display_centre, 0, 0]) rotate_extrude($fn = 96)
        polygon([[0, camera_top_w() - 1], [window_r, camera_top_w() - 1],
                 [window_r, cover_in_w()],
                 [window_r + cover_wall + 0.3, cover_out_w() + 0.3],
                 [0, cover_out_w() + 0.3]]);
    // USB-C plug, battery lead and button access, at the USB-C end
    translate([ring_r() - 8, -plug_slot[0] / 2, cover_rim_w() - 1])
        cube([30, plug_slot[0], plug_slot[1] + 1]);
    // strain relief tie
    for (a = tie_slot_angles)
        rotate([0, 0, a]) translate([ring_r() - cover_wall - 1, -0.9, 10])
            cube([cover_wall + 2, 1.8, 3.4]);
    // vents
    for (a = vent_angles)
        rotate([0, 0, a]) translate([ring_r() - cover_wall - 1, -0.8, 9.5])
            cube([cover_wall + 2, 1.6, 12]);
    // lettering, let into the outer face
    translate([0, cover_text_y, cover_out_w() - cover_text_depth])
        linear_extrude(height = cover_text_depth + 1)
            text(cover_text, size = cover_text_size, font = cover_font,
                 halign = "center", valign = "baseline");
}

module cover_body(with_inside) {
    difference() {
        union() {
            cover_shell();
            if (with_inside)
                intersection() {
                    cover_inside_parts();
                    translate([0, 0, cover_rim_w() + 0.5])
                        cylinder(h = 100, r = ring_r() - cover_wall / 2,
                                 $fn = 144);
                    above_floor(cover_wall / 2);
                }
        }
        cover_cuts();
    }
    for (a = snap_angles) snap_arm(a);
}

module xiao_cover() {
    cover_body(true);
}

// Just the rim of the cover and its four arms, to try the snap on the ring.
module xiao_cover_fit_test() {
    intersection() {
        cover_body(false);
        translate([-100, -100, -50]) cube([200, 200, 50 + snap_root_z + 6.5]);
    }
}

module xiao_battery() {
    color([0.55, 0.6, 0.7])
        translate([battery_x - battery_t / 2, -battery_l / 2, battery_w0()])
            cube([battery_t, battery_l, battery_w]);
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

// For the pictures: holder, boards and cover where they sit on the gripper.
module xiao_on_gripper(with_cover = true) {
    on_gripper() {
        color([0.2, 0.55, 0.75]) xiao_holder();
        xiao_electronics();
        if (with_cover) color([0.95, 0.75, 0.2]) xiao_cover();
        else xiao_battery();
    }
}

module the_part() {
    if (part == "fit_test") xiao_fit_test();
    else if (part == "cover") xiao_cover();
    else if (part == "cover_fit_test") xiao_cover_fit_test();
    else if (part == "electronics") { xiao_electronics(); xiao_battery(); }
    else xiao_holder();
}

// The cover prints face down; its fit piece on the cut that made it.
module cover_to_print() {
    top = part == "cover_fit_test" ? snap_root_z + 6.5 : cover_out_w();
    translate([0, 0, top]) rotate([180, 0, 0]) children();
}

assert(wall >= latch_beam + latch_gap + 1.2,
       "wall leaves under 1.2 mm of ring outside the latch slots");
assert(ring_depth() - latch_reach > hook_w(),
       "rear_zone is too shallow for the latch hook and its lead-in");
assert(battery_x + battery_t / 2 + battery_fit / 2 + battery_rib
       <= xiao_centre_from_display_centre - xiao_length / 2,
       "the battery pocket runs into the XIAO; move battery_x");
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
    ", \"cover_face_w\": ", cover_out_w(),
    ", \"window\": ", [window_r, cover_in_w() - lens_w(),
                       window_r + cover_wall, cover_out_w() - lens_w()],
    ", \"fov_deg\": ", camera_fov_deg,
    ", \"ties\": ", ties(),
    ", \"origin\": ", holder_origin(),
    ", \"bed_w\": ", bed_w,
    ", \"tie_tunnel\": ", [tie_tunnel_width, tie_tunnel_thick],
    ", \"block\": ", [block_centre_x, block_half_width, block_ref_z,
                      block_taper, block_top_y, block_thickness, jaw_fit + jaw],
    "}"));

if (pose == "gripper") on_gripper() the_part();
else if (pose == "cradle") the_part();      // as built, for pictures
else if (part == "cover" || part == "cover_fit_test") cover_to_print() the_part();
else to_print() the_part();
