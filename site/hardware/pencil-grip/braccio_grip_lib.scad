/*
Shared geometry for the Braccio drawing tools
=============================================
`split_collar()` is the clamp both printable parts are built from:

  - braccio_pencil_grip.scad  replaces a Braccio finger with the collar
                              (most rigid, but the claws are then unusable)
  - braccio_pen_finger.scad   keeps the whole finger and carries the collar
                              beside it, so the claws still close and the
                              pencil pulls out when you want them

The collar is built in a local frame: bore on the z axis, slit opening towards
+x, clamp screw on the x axis. Callers translate/rotate it into place.

Hardware: 1 x M3 socket-head screw 16-20 mm + 1 x M3 hex nut.
*/

// Adaptive facets: smooth bore, far quicker than $fn=96 everywhere.
$fa = 3;
$fs = 0.35;

// Clamp hardware, shared by every part.
split_width = 2.4;          // slit the collar closes across
lug_wall = 5.0;             // material each side of the slit at the screw
lug_height = 11;
m3_clearance_diameter = 3.4;
m3_head_diameter = 6.4;
m3_head_recess_depth = 2.0; // shallow, so the web under the head stays thick
m3_nut_across_flats = 5.7;  // 5.5 mm nominal + fit clearance
m3_nut_pocket_depth = 2.9;  // an M3 nut is 2.4 mm thick
bore_lead_in = 1.6;         // chamfer at the collar mouth, eases insertion

function bore_diameter(pencil_d, clearance = 0.55) = pencil_d + clearance;

function collar_diameter(pencil_d, clearance = 0.55, wall = 3.4) =
    bore_diameter(pencil_d, clearance) + 2 * wall;

function lug_diameter() = 2 * lug_wall + split_width;

// Distance from the collar axis to the clamp screw.
function clamp_offset(pencil_d, clearance = 0.55, wall = 3.4) =
    collar_diameter(pencil_d, clearance, wall) / 2 + 2;

// Material left between a recess and the slit face. Both carry the clamping
// load; 0.8 mm (an earlier revision's head recess) tears out.
function head_web() = lug_wall - m3_head_recess_depth;
function nut_web() = lug_wall - m3_nut_pocket_depth;

// ---------------------------------------------------------------- the finger
// Every side-mounted tool is built on the ORIGINAL Braccio finger, imported
// whole and untouched, so the claw keeps its exact shape and still closes.
finger_center_x = 16.5;
finger_center_y = 2.5;
finger_half_thickness = 2.5;   // the blade is 5 mm thick, y = 0..5
finger_tip_z = -61.4;

module braccio_finger() {
    import("braccio_mount_reference_mm.stl", convexity = 20);
}

// Web tying a side-mounted tool back to the finger blade: a cantilevered tool
// would twist the 5 mm blade every time it is loaded.
module side_web(tool_y, bottom_z, top_z, thickness = 4.5, gusset = 6) {
    inner_y = finger_center_y + (tool_y > finger_center_y ? 1 : -1)
              * (finger_half_thickness - 0.5);
    lo = min(inner_y, tool_y);
    hi = max(inner_y, tool_y);
    translate([finger_center_x - thickness / 2, lo, bottom_z])
        cube([thickness, hi - lo, top_z - bottom_z]);
    // Taper into the mounting tab, where the bending moment is largest.
    translate([finger_center_x - thickness / 2, lo, top_z - 0.01])
        linear_extrude(height = gusset, scale = [1, 0.2])
            square([thickness, hi - lo]);
}


module along_y_cylinder(h, d, fn = 0) {
    rotate([90, 0, 0])
        if (fn > 0) cylinder(h = h, d = d, center = true, $fn = fn);
        else cylinder(h = h, d = d, center = true);
}

// Solid part of the collar: tube plus the clamp lug, no cuts yet. Split out so
// callers can union their own neck/web into it before the cuts are applied.
module split_collar_solid(pencil_d, height, clearance = 0.55, wall = 3.4,
                          screw_z = 0) {
    outer_d = collar_diameter(pencil_d, clearance, wall);
    sx = clamp_offset(pencil_d, clearance, wall);
    cylinder(h = height, d = outer_d);
    // Stadium lug hulled onto the collar, so the two ears the slit creates are
    // backed by the tube instead of hanging off it.
    translate([0, 0, screw_z - lug_height / 2])
        hull() {
            cylinder(h = lug_height, d = outer_d);
            translate([sx, 0, 0]) cylinder(h = lug_height, d = lug_diameter());
        }
}

// Everything the collar removes: bore, lead-in, slit, screw, head recess, nut
// pocket. Apply inside the caller's difference() so it also cuts their web.
module split_collar_cuts(pencil_d, height, clearance = 0.55, wall = 3.4,
                         screw_z = 0, slit_bottom = -1, slit_top = 1e9) {
    bore_d = bore_diameter(pencil_d, clearance);
    outer_r = collar_diameter(pencil_d, clearance, wall) / 2;
    sx = clamp_offset(pencil_d, clearance, wall);
    nut_corner_radius = m3_nut_across_flats / sqrt(3);
    slit_hi = min(slit_top, height + 1);

    assert(wall >= 2.4, "collar wall below 2.4 mm is too thin to clamp with");
    assert(head_web() >= 1.6,
           "m3_head_recess_depth leaves under 1.6 mm under the screw head");
    assert(nut_web() >= 1.6,
           "m3_nut_pocket_depth leaves under 1.6 mm behind the nut");

    // Pen bore, blind at the top so the pencil bottoms out at a repeatable
    // depth: that is what makes links.wrist_pen_mm reproducible.
    translate([0, 0, -1]) cylinder(h = height + 1, d = bore_d);
    translate([0, 0, -0.01])
        cylinder(h = bore_lead_in, d1 = bore_d + 2 * bore_lead_in, d2 = bore_d);

    // Radial slit, from the bore out past the lug.
    translate([0, -split_width / 2, slit_bottom])
        cube([outer_r + lug_diameter(), split_width, slit_hi - slit_bottom]);

    // M3 through-hole, head recess (+y) and captive nut pocket (-y).
    translate([sx, 0, screw_z])
        along_y_cylinder(split_width + 2 * lug_wall + 6, m3_clearance_diameter);
    translate([sx, split_width / 2 + lug_wall - m3_head_recess_depth / 2, screw_z])
        along_y_cylinder(m3_head_recess_depth + 0.01, m3_head_diameter);
    translate([sx, -split_width / 2 - lug_wall + m3_nut_pocket_depth / 2, screw_z])
        along_y_cylinder(m3_nut_pocket_depth + 0.01, 2 * nut_corner_radius, 6);
}

// Convenience: a standalone collar with nothing else attached.
module split_collar(pencil_d, height, clearance = 0.55, wall = 3.4,
                    screw_z = 0) {
    difference() {
        split_collar_solid(pencil_d, height, clearance, wall, screw_z);
        split_collar_cuts(pencil_d, height, clearance, wall, screw_z);
    }
}
