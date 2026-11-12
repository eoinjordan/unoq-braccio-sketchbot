/*
The XIAO round display holder on the Braccio wrist - picture only
=================================================================
Places hardware/pencil-grip/braccio_wrist_xiao_round_display.scad on the wrist
and gripper meshes in this folder, with the joint frames of
sim/gazebo/urdf/braccio_sketchbot.urdf.xacro. Everything is drawn in
wrist_roll_link, in millimetres.

    fit = "screws"   hub on the wrist roll horn; the holder turns with the gripper
    fit = "ties"     saddle tied to the wrist body; the gripper rolls past it

This scene and the pictures rendered from it include the GPL-3.0 meshes in
this folder, so they are kept here under the same licence (see LICENSE).

    openscad -o xiao_round_display_on_wrist.png --render --imgsize=1400,1050 \
        --colorscheme=Tomorrow --camera=0,25,25,62,0,118,430 \
        xiao_round_display_on_wrist.scad
*/

use <../pencil-grip/braccio_wrist_xiao_round_display.scad>

fit = "screws";             // [screws, ties]
grip = 0.6;                 // gripper joint, radians: 0.175 open, 1.274 closed
show_pen_finger = true;

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
    if (show_pen_finger)
        color([0.35, 0.6, 0.4])
            translate([-16.5, 14.175, 30]) rotate([180, 0, 0])
                import("../pencil-grip/braccio_pen_finger_8mm.stl",
                       convexity = 10);
}

module fitted() {
    if (fit == "ties") to_tie() children();
    else to_screw() children();
}

wrist_and_gripper();
color([0.2, 0.55, 0.75]) fitted() holder();
fitted() electronics();
