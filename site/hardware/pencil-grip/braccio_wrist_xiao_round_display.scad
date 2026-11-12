/*
Braccio wrist holder - XIAO ESP32S3 Sense on the Round Display for XIAO
=======================================================================
A cradle for the Seeed Studio Round Display for XIAO with a XIAO ESP32S3 Sense
plugged into the socket on its back, assembled the normal way. The camera on
the Sense board looks out of the back of the display, towards whatever the
gripper is reaching for, and the screen faces the other way, towards the
people watching.

ONE PART, TWO WAYS TO FIT IT

  screws      The hub is the one braccio_wrist_camera_mount.scad uses: four M2
              screws on a 7 mm radius cross and a 6.4 mm centre bore, on the
              wrist roll horn. The holder then turns with the gripper.

  cable ties  The saddle sits on one cheek of the wrist body, below the roll
              joint, and two ties go round the wrist through the tunnels in
              the saddle. The holder then stays put while the gripper rolls.

The two fittings are the same part turned half a turn about the camera's
optical axis and slid `tie_slide()` back along it, so the camera looks down
the same line either way and meets the gripper centre line at the same point.
Whichever fitting is not in use is spare: the saddle face takes a small LiPo
or the cable when the hub is screwed down, and the hub takes them when the
saddle is tied on.

AIM. The optical axis crosses the gripper centre line `pick_distance` in front
of the finger mounting face. The tilt follows from that; it is not set
directly. Three distances are exported:

    pick_distance = 90    braccio_wrist_xiao_round_display_near.stl
    pick_distance = 120   braccio_wrist_xiao_round_display.stl      (default)
    pick_distance = 180   braccio_wrist_xiao_round_display_far.stl

The claw tips of braccio_mount_reference_mm.stl are 61.4 mm in front of the
mounting face, so the default aims 59 mm past the closed claws.

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
  Braccio
    [urdf]  sim/gazebo/urdf/braccio_sketchbot.urdf.xacro in this repository.
    [mesh]  braccio_wrist_pitch.stl and braccio_wrist_roll.stl, the meshes that
            URDF loads (GPL-3.0, not vendored here; see sim/render_arm.py).
    [mount] braccio_wrist_camera_mount.scad, measured off the older bracket.

  Values marked ESTIMATE were not found in a published drawing. Print the fit
  piece first and measure the board against them before printing the holder:

    openscad -D 'part="fit_test"' -o braccio_wrist_xiao_round_display_fit_test.stl \
        braccio_wrist_xiao_round_display.scad

FRAMES. `pose` picks the frame the part is exported in:

    print   rear rim of the cradle on the bed, screen side up (default)
    screw   wrist roll frame of the URDF, fitted by the hub
    tie     wrist roll frame of the URDF, fitted by the saddle

scripts/check_xiao_holder.py exports the last two and measures the clearance
to the wrist, the gripper and the pen finger.

    openscad -o braccio_wrist_xiao_round_display.stl braccio_wrist_xiao_round_display.scad
*/

part = "holder";            // [holder, fit_test, electronics]
pose = "print";             // [print, screw, tie]

// Distance in front of the finger mounting face at which the camera's optical
// axis crosses the gripper centre line.
pick_distance = 120;        // [60:5:300]

// ------------------------------------------------- Round Display for XIAO
display_pcb_d = 43.1;       // [brd] outline is a 21.53 mm radius circle
display_pcb_thick = 1.6;    // ESTIMATE: the cavity step in [case] is 1.6 mm
display_glass_d = 39.0;     // [wiki] "39mm disc", read as the cover glass
display_glass_proud = 3.0;  // ESTIMATE: glass face above the board's front face
// Angles round the board, seen from the back, 0 at the XIAO's USB-C end and
// counted towards the display flex. All from [brd].
battery_angle = 0;          // J1, JST 1.25 side entry, under the USB-C socket
card_angle = 180;           // J2, microSD, the card goes in from the rim
switch_angle = 153.8;       // SW1, slide switch at the rim
flex_angle = 90;            // the board outline is notched here for the flex
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

// ------------------------------------------------- Braccio wrist and gripper
finger_mount_z = 30.0;      // [urdf] wrist_roll_link origin to finger mount
finger_tip_below_mount = 61.4;    // braccio_grip_lib.scad, finger_tip_z
horn_face_z = 2.62;         // [mesh] top of the horn disc in the roll frame
wrist_top_z = 1.0;          // [mesh] top face of the wrist body, roll frame
wrist_width = 35.0;         // [mesh] wrist body across the cheek, x -16.4..18.6
wrist_face_y = 29.0;        // [mesh] roll axis to the cheek's outer face

// Servo-horn interface: [mount]. Do not change these; they are what makes the
// part bolt on with the screws the existing wrist mount uses.
horn_hole_radius = 7.0;
horn_hole_d = 2.4;          // M2 clearance
horn_head_d = 5.6;
horn_head_depth = 1.6;
horn_center_bore_d = 6.4;
hub_diameter = 24;
hub_thickness = 3.6;        // leaves 2.0 mm under each screw head

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
// [anchor angle, tip angle] of each latch. They sit where the board's rim is
// free: clear of the connector, switch and card notches and of the arm and
// the saddle.
latches = [[312, 345], [112, 140], [205, 250]];
// Notch edges must not land on a latch slot's edge (the slot runs 2 degrees
// past the latch tip): start each notch inside the slot next to it.
battery_notch = [346, 14];  // rear of the ring cut away for the JST plug
switch_card_notch = [141, 196];   // gap in the ring at the switch and the card

// ------------------------------------------------- where the cradle sits
// The tie pose fixes the camera's line: the ring sits against the saddle,
// level with the top of the wrist. The screw pose is the same line, moved
// forward just far enough for the hub to clear the bed in printing.
cradle_min_offset = 40;     // closest the optical axis may come to the roll axis
arm_sector = [268, 308];    // where the arm joins the ring
print_margin = 0.3;         // hub's outer face stays this far above the bed
arm_lift = 1.5;             // the arm leaves the hub this far above the horn

// ------------------------------------------------- the saddle and the ties
saddle_pad = 7.0;           // pad thickness
saddle_bottom_z = -26.0;    // roll frame, in the tie pose
saddle_ring_z = -3.0;       // roll frame: lowest point of the ring, tie pose
jaw = 3.0;                  // jaw thickness
jaw_fit = 0.4;              // clearance each side of the wrist body
jaw_depth = 5.0;            // how far the jaws wrap round the cheek's edges
lip_reach = 2.5;            // the lip that hooks over the top of the wrist
// A tunnel passes one cable tie up to 3.6 mm wide and 1.4 mm thick, so both
// the common 2.5 mm and 3.6 mm ties fit.
tie_tunnel_width = 4.4;
tie_tunnel_thick = 2.0;
tie_z = [-6.0, -20.0];      // roll frame: both are below the roll joint
tie_skin = 3.0;             // pad material between the wrist and a tunnel
cable_groove_width = 7.0;   // the gripper servo lead runs under the pad here
cable_groove_depth = 2.4;
gusset_sector = [20, 108];  // where the saddle joins the ring

// ------------------------------------------------------------------ derived
function pocket_r() = display_pcb_d / 2 + board_fit;
function ring_r() = pocket_r() + wall;
function opening_r() = screen_opening_d / 2;
function cone_end_w() = bezel_front + pocket_r() - opening_r();
// Distances along the optical axis from the screen face of the ring.
function board_front_w() = bezel_front + display_pcb_d / 2 - opening_r();
function board_back_w() = board_front_w() + display_pcb_thick;
function hook_w() = board_back_w() + board_slack;
function ring_depth() = hook_w() + rear_zone;
function lens_w() =
    board_back_w() + socket_height + xiao_pin_spacer + xiao_stack;

function saddle_ring_y() = wrist_face_y + saddle_pad - (ring_r() - opening_r());
// Tie pose, wrist roll frame: where the optical axis leaves the screen face,
// and the tilt that takes it from there to the pick point.
function target_roll_z() = finger_mount_z + pick_distance;
function tie_foot_y(t) = saddle_ring_y() + ring_r() * cos(t);
function tie_foot_z(t) = saddle_ring_z + ring_r() * sin(t);
function tilt_step(t) =
    atan(tie_foot_y(t) / (target_roll_z() - tie_foot_z(t)));
function tilt_solve(t, n) = n <= 0 ? t : tilt_solve(tilt_step(t), n - 1);
tilt = tilt_solve(20, 30);
// Screw pose: slide forward along the axis until the hub's outer face is
// print_margin above the bed with the part printed rear rim down.
function slide_needed() =
    ((tie_foot_y(tilt) + hub_diameter / 2) * tan(tilt) + hub_thickness
     - ring_depth() / cos(tilt) + print_margin
     - (tie_foot_z(tilt) - horn_face_z)) * cos(tilt);
function tie_slide() = max(0, slide_needed());
// Part frame: hub mating face at z = 0, wrist roll axis on z.
cradle_offset = tie_foot_y(tilt) - tie_slide() * sin(tilt);
cradle_height = tie_foot_z(tilt) - horn_face_z + tie_slide() * cos(tilt);
function optical_dir() = [0, -sin(tilt), cos(tilt)];
function axis_foot() = [0, cradle_offset, cradle_height];
function cradle_origin() =
    [-lens_from_display_centre, cradle_offset, cradle_height];
function saddle_half() = wrist_width / 2 + jaw_fit + jaw;

// ------------------------------------------------------------------ helpers
// The whole part is built in the cradle's own frame and only moved into a
// pose at the very end: screen face at z = 0 looking down -z, the board's back
// and the camera towards +z, USB-C end towards +x, rear rim at
// z = ring_depth(). That plane is the print bed, and building against it
// exactly is what keeps the mesh closed.
module sector(a0, a1, r, w0, w1) {
    span = a1 >= a0 ? a1 - a0 : a1 + 360 - a0;
    steps = max(2, ceil(span / 4));
    translate([0, 0, w0])
        linear_extrude(height = w1 - w0)
            polygon(concat([[0, 0]],
                [for (i = [0 : steps])
                    let(a = a0 + span * i / steps) [r * cos(a), r * sin(a)]]));
}

// Cradle frame to the part frame (hub mating face at z = 0, roll axis on z).
module in_cradle() {
    translate(cradle_origin()) rotate([tilt, 0, 0]) children();
}

// ... and back.
module to_cradle() {
    rotate([-tilt, 0, 0]) translate(-cradle_origin()) children();
}

// Half a turn about the optical axis, then back out along it: takes anything
// drawn where it sits in the tie pose to where it is on the part.
module tie_to_part() {
    translate(axis_foot()) rotate(a = 180, v = optical_dir())
        translate(-axis_foot()) translate(tie_slide() * optical_dir())
            children();
}

// Wrist roll frame in the tie pose to the cradle frame.
module from_tie() {
    to_cradle() tie_to_part() translate([0, 0, -horn_face_z]) children();
}

// Everything on the part is on this side of the bed when it is printed.
module bed_clip() {
    translate([0, 0, ring_depth()]) mirror([0, 0, 1])
        translate([-300, -300, 0]) cube([600, 600, 300]);
}

// --------------------------------------------------------------- the cradle
module ring_solid() {
    difference() {
        cylinder(h = ring_depth(), r = ring_r(), $fn = 144);
        translate([0, 0, -1])
            cylinder(h = ring_depth() + 2, r = opening_r() - 3, $fn = 144);
    }
}

// A piece of the ring for the arm and the saddle to grow out of. It is kept
// just inside the ring's own surfaces, so the two never share a face.
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
    // The switch and the card are reached through a gap right through the
    // ring. Nothing is lost: the arm and the saddle join round the other side.
    sector(switch_card_notch[0], switch_card_notch[1], ring_r() + 30, -1, 200);
    // each latch springs in a slot in the ring; the band outside the slot is
    // left whole, because the ring is what joins the arm to the saddle
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

// ------------------------------------------------------------------ the hub
module hub_block() {
    // The hub disc, carried up to the bed so it prints without support. The
    // wedge this leaves above the hub is the root of the arm.
    intersection() {
        to_cradle() cylinder(h = 200, d = hub_diameter, $fn = 96);
        bed_clip();
    }
}

module hub_cuts() {
    to_cradle() {
        translate([0, 0, -1])
            cylinder(h = 300, d = horn_center_bore_d, $fn = 64);
        for (a = [0, 90, 180, 270])
            rotate([0, 0, a]) translate([horn_hole_radius, 0, -1]) {
                cylinder(h = hub_thickness + 2, d = horn_hole_d, $fn = 32);
                // Counterbore from the outer face, leaving 2.0 mm of
                // material, and carried on through the arm so a driver
                // reaches the screw.
                translate([0, 0, hub_thickness + 1 - horn_head_depth])
                    cylinder(h = 300, d = horn_head_d, $fn = 40);
            }
    }
}

module arm() {
    // From the hub's upper part only, so the underside of the arm lifts
    // clear of the horn disc straight away. The root is a little smaller than
    // the hub so the two never share a face.
    hull() {
        intersection() {
            to_cradle() translate([0, 0, arm_lift])
                cylinder(h = 200, d = hub_diameter - 1, $fn = 90);
            bed_clip();
        }
        ring_patch(arm_sector);
    }
}

// --------------------------------------------------------------- the saddle
// Drawn where it sits in the tie pose, in the wrist roll frame of the URDF:
// pad on the cheek's outer face, jaws round the cheek's two edges so it cannot
// turn, lip over the top of the wrist so it cannot slide towards the elbow.
// It is one block; saddle_cuts_tie() takes the wrist's own space out of it,
// and out of everything else, which is what shapes the jaws and the lip.
module saddle_solid_tie() {
    h = saddle_half();
    translate([-h, wrist_face_y - jaw_depth, saddle_bottom_z])
        cube([2 * h, jaw_depth + saddle_pad, 80 - saddle_bottom_z]);
}

module saddle_cuts_tie() {
    h = saddle_half();
    // the wrist body, and above it everything inboard of the lip
    rotate([90, 0, 90])
        linear_extrude(height = 2 * (h - jaw), center = true)
            polygon([[-100, -100], [wrist_face_y, -100],
                     [wrist_face_y, wrist_top_z + 0.2],
                     [wrist_face_y - lip_reach, wrist_top_z + 0.2],
                     [wrist_face_y - lip_reach, 100], [-100, 100]]);
    // cable tie tunnels
    for (z = tie_z)
        translate([-h - 1, wrist_face_y + tie_skin, z - tie_tunnel_width / 2])
            cube([2 * h + 2, tie_tunnel_thick, tie_tunnel_width]);
    // groove for the gripper servo lead
    translate([-cable_groove_width / 2, wrist_face_y - lip_reach - 1,
               saddle_bottom_z - 1])
        cube([cable_groove_width, lip_reach + 1 + cable_groove_depth, 200]);
}

module saddle_gusset_block_tie() {
    h = saddle_half() - 0.5;
    translate([-h, wrist_face_y + 0.5, saddle_ring_z])
        cube([2 * h, saddle_pad - 1, 80]);
}

module saddle() {
    intersection() {
        from_tie() saddle_solid_tie();
        bed_clip();
    }
    hull() {
        intersection() {
            from_tie() saddle_gusset_block_tie();
            bed_clip();
        }
        ring_patch(gusset_sector);
    }
}

// ----------------------------------------------------------------- the part
module holder() {
    difference() {
        union() {
            ring_solid();
            hub_block();
            arm();
            saddle();
        }
        display_space();
        from_tie() saddle_cuts_tie();
        hub_cuts();
    }
    latches_all();
}

module fit_test() {
    difference() {
        ring_solid();
        display_space();
    }
    latches_all();
}

// The display, the XIAO and a USB-C plug as plain blocks. Not printed: it is
// what the pictures show in the cradle and what scripts/check_xiao_holder.py
// keeps clear of the gripper along with the holder itself.
module electronics() {
    xiao_w0 = board_back_w() + socket_height + xiao_pin_spacer;
    x0 = xiao_centre_from_display_centre - xiao_length / 2;
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

module the_part() {
    if (part == "fit_test") fit_test();
    else if (part == "electronics") electronics();
    else holder();
}

// Cradle frame to the printer's: rear rim on the bed, screen side up.
module to_print() {
    translate([0, 0, ring_depth()]) rotate([180, 0, 0]) children();
}

module to_screw() {
    translate([0, 0, horn_face_z]) in_cradle() children();
}

module to_tie() {
    translate([0, 0, horn_face_z]) translate(-tie_slide() * optical_dir())
        translate(axis_foot()) rotate(a = 180, v = optical_dir())
            translate(-axis_foot()) in_cradle() children();
}

assert(wall >= latch_beam + latch_gap + 1.2,
       "wall leaves under 1.2 mm of ring outside the latch slots");
assert(ring_depth() - latch_reach > hook_w(),
       "rear_zone is too shallow for the latch hook and its lead-in");
assert(cradle_offset >= cradle_min_offset,
       "the cradle would sit too close to the gripper; thicken saddle_pad");

// Lens and target in the wrist roll frame, for scripts/check_xiao_holder.py.
lens_part = cradle_origin()
    + [lens_from_display_centre, 0, 0] + lens_w() * optical_dir();
echo(str("xiao_holder {",
    "\"pick_distance\": ", pick_distance,
    ", \"tilt_deg\": ", tilt,
    ", \"cradle_height\": ", cradle_height,
    ", \"tie_slide\": ", tie_slide(),
    ", \"ring_depth\": ", ring_depth(),
    ", \"ring_outer_d\": ", 2 * ring_r(),
    ", \"pocket_d\": ", 2 * pocket_r(),
    ", \"cradle_offset\": ", cradle_offset,
    ", \"target\": [0, 0, ", target_roll_z(), "]",
    ", \"axis\": ", optical_dir(),
    ", \"lens_screw\": ", lens_part + [0, 0, horn_face_z],
    ", \"lens_tie\": ",
        lens_part + [0, 0, horn_face_z] - tie_slide() * optical_dir(),
    ", \"fov_deg\": ", camera_fov_deg,
    ", \"tie_z\": ", tie_z,
    ", \"tie_tunnel\": ", [tie_tunnel_width, tie_tunnel_thick],
    "}"));

if (pose == "screw") to_screw() the_part();
else if (pose == "tie") to_tie() the_part();
else to_print() the_part();
