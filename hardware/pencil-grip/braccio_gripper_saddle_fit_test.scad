/*
Braccio gripper saddle - fit piece
==================================
The saddle the gripper-top camera holders stand on, by itself: pad, jaws,
servo slot, tie tunnel and screw slots, with no camera on it. It is a short
print for trying the fit on the gripper block before printing a holder.

Measure the gripper, set the values marked MEASURE in
braccio_gripper_camera_lib.scad, export this, and check that:

  - the jaws sit down both sloping edges of the block and the pad cannot twist;
  - the gripper servo, its horn and its lead are clear in the slot;
  - the claws open and close under the front of the pad without touching it;
  - a cable tie through the tunnel goes round the block without crossing the
    servo or the finger linkage.

    openscad -o braccio_gripper_saddle_fit_test.stl braccio_gripper_saddle_fit_test.scad

It prints standing on its front end, the end nearest the fingers.
*/

include <braccio_gripper_camera_lib.scad>

pose = "print";             // [print, gripper]
front_z = 30.0;             // about where the holders' pads end, in the wrist roll frame

// Unused by this part, but the shared file expects each part to define them.
// These put its idea of the pad's front end at front_z.
camera_height = 0;
face_z = front_z;
bed_w = 0;

module saddle_fit_test() {
    difference() {
        intersection() {
            saddle_body();
            translate([-200, -200, front_z]) mirror([0, 0, 1]) cube(400);
        }
        saddle_cuts();
    }
}

echo(str("gripper_camera {\"holder\": \"saddle_fit_test\"",
    ", \"ties\": ", ties(),
    ", \"tie_tunnel\": ", [tie_tunnel_width, tie_tunnel_thick],
    ", \"front_z\": ", front_z, "}"));

if (pose == "gripper") saddle_fit_test();
else translate([0, 0, front_z]) rotate([180, 0, 0]) saddle_fit_test();
