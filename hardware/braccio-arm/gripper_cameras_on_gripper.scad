/*
The gripper-top camera holders on the Braccio gripper - pictures only
=====================================================================
Places hardware/pencil-grip/braccio_gripper_xiao_round_display.scad or
braccio_gripper_esp_eye.scad on the wrist and gripper meshes in this folder,
with the joint frames of sim/gazebo/urdf/braccio_sketchbot.urdf.xacro. The
scene is turned so the gripper reaches away along -y with the face the holder
sits on upwards, the way the arm holds it when it reaches forward.

    which = "xiao_round_display"   or   "esp_eye"

This scene and the pictures rendered from it include the GPL-3.0 meshes in
this folder, so they are kept here under the same licence (see LICENSE).
scripts/render_hardware.sh renders them: one from the side, one from behind,
where the audience stands.
*/

use <../pencil-grip/braccio_gripper_xiao_round_display.scad>
use <../pencil-grip/braccio_gripper_esp_eye.scad>

which = "xiao_round_display";   // [xiao_round_display, esp_eye]
grip = 0.9;                 // gripper joint, radians: 0.175 open, 1.274 closed

module wrist_and_gripper() {
    // wrist_pitch_link, seen from wrist_roll_link at zero roll
    color([0.93, 0.55, 0.14])
        rotate([0, 0, -90]) translate([0, 0, -60]) translate([3, -0.4, -24])
            import("braccio_wrist_pitch.stl", convexity = 6);
    color([0.92, 0.92, 0.9])
        translate([6, 0, 0]) import("braccio_wrist_roll.stl", convexity = 6);
    color([0.6, 0.6, 0.62]) {
        translate([10, 0, 30]) rotate([0, (-0.2967 - grip) * 180 / PI, 0])
            translate([0, -12, 10]) rotate([0, 90, 0])
                import("braccio_right_gripper.stl", convexity = 6);
        translate([-10, 0, 30]) rotate([0, (3.4383 + grip) * 180 / PI, 0])
            translate([0, -12, 0]) rotate([0, 90, 0])
                import("braccio_left_gripper.stl", convexity = 6);
    }
}

rotate([90, 0, 0]) {
    wrist_and_gripper();
    if (which == "esp_eye") esp_eye_on_gripper();
    else xiao_on_gripper();
}
