/*
Shared geometry for the cameras that ride on top of the Braccio gripper
=======================================================================
Two holders are built on this, and one fit piece:

  - braccio_gripper_xiao_round_display.scad   XIAO ESP32S3 Sense on the Round
                                              Display for XIAO, with a cover
  - braccio_gripper_esp_eye.scad              ESP-EYE
  - braccio_gripper_saddle_fit_test.scad      the saddle alone, to try on the
                                              gripper before printing a holder

WHERE THE CAMERA SITS. On the flat face of the gripper block, the part that
carries the finger pivots and turns with wrist roll, just behind the pivots.
The camera stands up from that face and looks forward along the fingers, in
the gripper's plane of symmetry, tilted down so that its optical axis meets
the gripper centre line `pick_distance` in front of the finger mounting face.
Because the holder is on the gripper block it follows wrist roll.

Everything here is drawn in wrist_roll_link of
sim/gazebo/urdf/braccio_sketchbot.urdf.xacro, in millimetres: z along the
gripper, the fingers opening in the x-z plane, and +y out of the face the
holder sits on.

THE SADDLE. A pad on the face, with a jaw down each sloping side edge of the
block. The block widens towards the fingers, so the jaws stop the pad sliding
forward and stop it twisting; the tie or the screws stop it sliding back.

  servo slot   The gripper servo stands proud of the block. The pad does not
               bridge it: an open-ended slot is cut right through pad and jaw,
               from one side edge inwards, so the servo body, its ears, its
               horn and its lead all sit in the open and the lead leaves
               through the open end.
  cable tie    One tunnel, 4.4 x 2.0 mm, for a 2.5 mm or a 3.6 mm tie, in the
               strip of pad between the servo slot and the finger pivots. The
               tie goes round the block there and never crosses the servo. A
               second tunnel appears behind the slot when servo_from_pivots
               leaves room for one.
  screws       two slots through the pad for M3 screws. NO REFERENCE THIS PART
               IS DRAWN FROM SHOWS A FIXING POINT ON THE GRIPPER BLOCK, so the
               slot positions are placeholders: measure the block, then set
               screw_spacing, screw_centre_x and screw_z.

FOUR THINGS TO MEASURE ON YOUR GRIPPER. No dimensioned drawing or CAD of the
Braccio gripper was found (Arduino's store page gives only the arm's overall
sizes). The block numbers below are read off
hardware/braccio-arm/braccio_wrist_roll.stl, a simulation mesh that draws the
whole gripper block as one 4.5 mm plate with a round hole where the servo
goes. The servo numbers are the SR311's published body size plus margin.

  1. block width across the face at both ends   block_half_width at
                                                block_ref_z, and block_taper
  2. block thickness                            block_thickness
  3. servo body length, width and how far it    servo_slot_length,
     stands above the face                      servo_slot_width,
                                                servo_stand_height
  4. finger pivots to the middle of the servo   servo_from_pivots

Print braccio_gripper_saddle_fit_test.stl and try it on the gripper first.
*/

// Distance in front of the finger mounting face at which the camera's optical
// axis crosses the gripper centre line.
pick_distance = 120;        // [60:5:300]

// ------------------------------------------------- Braccio gripper
finger_mount_z = 30.0;      // [urdf] wrist_roll_link origin to finger mount
finger_tip_below_mount = 61.4;    // braccio_grip_lib.scad, finger_tip_z
block_top_y = -1.5;         // [mesh] the face the saddle sits on
block_thickness = 4.5;      // [mesh] plate y -6.0..-1.5. MEASURE: the real block is thicker
block_centre_x = -0.4;      // [mesh]
block_ref_z = 3.1;          // [mesh] where block_half_width is measured
block_half_width = 20.8;    // [mesh] MEASURE: half the width of the face at block_ref_z
block_taper = 0.612;        // [mesh] MEASURE: half width gained per mm towards the fingers
// The finger blades swing over the face in front of this z, and stand this
// far above the centre line. The pad bridges over them from there on.
finger_space_z = 21.5;      // [mesh] blades reach back to z = 23.5; 2 mm margin
finger_space_y = 2.2;       // [mesh] blade top at y = 0.7; 1.5 mm margin

// ------------------------------------------------- gripper servo
// The Braccio's small servos are SpringRC SR311: 31.3 x 16.5 x 28.6 mm
// (https://store-usa.arduino.cc/products/tinkerkit-braccio-robot). Which way
// round the gripper servo sits in the block, and how far it stands out, are
// not in any reference, so the slot is the whole body with margin either way.
servo_slot_length = 42.0;   // MEASURE: across the gripper, from the open edge inwards. 31.3 body + ears and margin
servo_slot_width = 21.0;    // MEASURE: along the gripper. 16.5 body + 4.5 margin
servo_stand_height = 30.0;  // MEASURE: how far the servo stands above the face. Nothing is built over the slot below this
servo_from_pivots = 17.5;   // MEASURE: finger pivots back to the middle of the slot. The mesh's hole is 15.0
servo_side = 1;             // [1:slot open towards +x, -1:towards -x]

// ------------------------------------------------- the saddle
pad_thick = 7.5;            // thick enough to bridge over the finger bases
pad_z0 = 4.0;               // rear end of the pad; the front end is the bed
jaw = 3.0;                  // jaw thickness
jaw_fit = 0.4;              // clearance each side of the block
jaw_depth = 4.0;            // how far the jaws reach down the block's edges
tie_tunnel_width = 4.4;     // passes a tie up to 3.6 mm wide
tie_tunnel_thick = 2.0;     // ... and 1.4 mm thick
tie_front_z = 26.0;         // the tie between the servo slot and the pivots
tie_front_y = 2.9;          // its tunnel is in the bridge, over the finger bases
tie_rear_y = 0.0;
// Screw slots. Placeholders until the block has been measured (see above).
screw_d = 3.4;              // M3 clearance
screw_slot = 6.0;           // slot length, along the gripper
screw_spacing = 9.0;        // between the two slots
screw_centre_x = -17.5;     // midpoint of the pair
screw_z = 13.0;

// ------------------------------------------------- set by each holder
// Each holder file defines these three itself, after its own dimensions:
//   camera_height   optical axis above the gripper centre line, at face_z
//   face_z          setback: where the holder's face plane crosses the z axis
//   bed_w           depth of the holder from that plane to the print bed

// ------------------------------------------------------------------ derived
function target_z() = finger_mount_z + pick_distance;
function tilt_deg() = atan(camera_height / (target_z() - face_z));
function optical_dir() = [0, -sin(tilt_deg()), cos(tilt_deg())];
// Where the holder's own origin sits. A holder whose lens is not at its
// origin redefines this so that the lens still lands on the optical axis.
function holder_origin() = [0, camera_height, face_z];
function block_half(z) = block_half_width + block_taper * (z - block_ref_z);
function pad_top_y() = block_top_y + pad_thick;
function servo_z0() = finger_mount_z - servo_from_pivots - servo_slot_width / 2;
function servo_z1() = servo_z0() + servo_slot_width;
// A second tie fits behind the servo slot only if the slot leaves room.
function tie_rear_z() = servo_z0() - 0.8 - tie_tunnel_width / 2;
function has_rear_tie() = tie_rear_z() - tie_tunnel_width / 2 >= pad_z0 + 0.8;
function ties() = has_rear_tie()
    ? [[tie_front_z, tie_front_y], [tie_rear_z(), tie_rear_y]]
    : [[tie_front_z, tie_front_y]];

// The holders are built in their own frame and moved onto the gripper last:
// optical axis on +z, face plane at z = 0, bed at z = bed_w, +y up the camera.
module on_gripper() {
    translate(holder_origin()) rotate([tilt_deg(), 0, 0]) children();
}

module from_gripper() {
    rotate([-tilt_deg(), 0, 0]) translate(-holder_origin()) children();
}

// Everything on a holder is on this side of the bed when it is printed.
module bed_clip() {
    translate([0, 0, bed_w]) mirror([0, 0, 1])
        translate([-300, -300, 0]) cube([600, 600, 300]);
}

module to_print() {
    translate([0, 0, bed_w]) rotate([180, 0, 0]) children();
}

module sector(a0, a1, r, w0, w1) {
    span = a1 >= a0 ? a1 - a0 : a1 + 360 - a0;
    steps = max(2, ceil(span / 4));
    translate([0, 0, w0])
        linear_extrude(height = w1 - w0)
            polygon(concat([[0, 0]],
                [for (i = [0 : steps])
                    let(a = a0 + span * i / steps) [r * cos(a), r * sin(a)]]));
}

// An outline in x and z (wrist roll frame) made solid between two y values.
module slab_xz(points, y0, y1) {
    translate([block_centre_x, y1, 0]) rotate([90, 0, 0])
        linear_extrude(height = y1 - y0) polygon(points);
}

function taper_outline(margin, z0, z1) =
    [[-block_half(z0) - margin, z0], [block_half(z0) + margin, z0],
     [block_half(z1) + margin, z1], [-block_half(z1) - margin, z1]];

// Pad and jaws as one block, in the wrist roll frame. saddle_cuts() takes the
// gripper block's own space out of it, which is what shapes the jaws.
module saddle_body() {
    slab_xz(taper_outline(jaw_fit + jaw, pad_z0, 90),
            block_top_y - jaw_depth, pad_top_y());
}

module saddle_cuts() {
    // the gripper block
    slab_xz(taper_outline(jaw_fit, pad_z0 - 12, 120), -100, block_top_y);
    // the finger bases, under the front of the pad. A shade narrower than
    // the cut above, so the two never share a face.
    slab_xz(taper_outline(jaw_fit - 0.3, finger_space_z, 120), -50,
            finger_space_y);
    // The gripper servo: an open-ended slot from one side edge inwards,
    // through the pad, the jaw and anything that might be built above it.
    translate([block_centre_x, 0, 0]) mirror([servo_side > 0 ? 0 : 1, 0, 0])
        translate([block_half(servo_z1()) + jaw_fit + jaw - servo_slot_length,
                   block_top_y - 50, servo_z0()])
            cube([servo_slot_length + 100, 50 + servo_stand_height,
                  servo_slot_width]);
    // cable tie tunnels
    for (t = ties())
        translate([-100, t[1], t[0] - tie_tunnel_width / 2])
            cube([200, tie_tunnel_thick, tie_tunnel_width]);
    // screw slots
    for (sx = [-1, 1])
        translate([screw_centre_x + sx * screw_spacing / 2, block_top_y - 1,
                   screw_z])
            rotate([-90, 0, 0]) hull() {
                for (dz = [-1, 1])
                    translate([0, dz * (screw_slot - screw_d) / 2, 0])
                        cylinder(h = pad_thick + 2, d = screw_d, $fn = 24);
            }
}

// The saddle in the holder's frame, cut off at the bed.
module saddle() {
    intersection() {
        from_gripper() saddle_body();
        bed_clip();
    }
}

// A strip of the pad for a holder to grow a gusset out of, kept just inside
// the pad's own surfaces so the two never share a face.
module pad_strip(x0, x1, z0) {
    intersection() {
        from_gripper()
            translate([x0, block_top_y + 0.5, z0])
                cube([x1 - x0, pad_thick - 0.8, 90]);
        bed_clip();
    }
}

assert(tie_front_z - tie_tunnel_width / 2 >= servo_z1() + 0.6,
       "the front tie would cross the servo slot; move servo_from_pivots or tie_front_z");
