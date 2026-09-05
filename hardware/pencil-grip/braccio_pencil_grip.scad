/*
Braccio Pencil / Pen Drawing Grip
=================================
Parametric OpenSCAD model using the exact mounting interface extracted from
"c_DITO PER CILINDRI.stl" supplied with the project. It replaces one Braccio
finger with a rigid split collar that clamps a pencil, pen or marker.

Hardware:
- 1 x M3 socket-head screw, 16-20 mm long
- 1 x M3 hex nut

Print: PETG preferred (best clamp flex), PLA+ fine. 0.2 mm layers, 4 walls,
30-40 % infill. See README.md.

Render the presets (or any diameter) with:
    openscad -o braccio_pencil_grip_8mm.stl braccio_pencil_grip_8mm.scad
    openscad -o my_grip.stl -D pencil_diameter=9 braccio_pencil_grip.scad
    ../../scripts/render_hardware.sh          # both presets + validation

The wrapper files use <> this one, so the geometry lives here only.
*/

// Adaptive facets: fine enough for a smooth bore, much faster than $fn=96.
$fa = 3;
$fs = 0.35;

// ---------------------------------------------------------------- parameters

// Customizer parameters
pencil_diameter = 8.0;      // [6:0.1:12]
fit_clearance = 0.55;       // [0.2:0.05:1.0] added to the bore diameter
collar_wall = 3.4;          // [2.4:0.1:8] collar wall around the pencil

// Collar position, in the mounting interface's own frame (z = 0 is the
// Braccio finger mounting face; the tool hangs below it, towards -z).
collar_top_z = -14;
collar_bottom_z = -54;
mount_center_x = 16.5;
mount_center_y = 2.5;

// Clamp
split_width = 2.4;          // slit the collar closes across
clamp_screw_z = -33;
lug_wall = 5.0;             // material each side of the slit at the screw
lug_height = 11;
m3_clearance_diameter = 3.4;
m3_head_diameter = 6.4;
m3_head_recess_depth = 2.0; // shallow: keeps a thick web under the screw head
m3_nut_across_flats = 5.7;  // 5.5 mm nominal + fit clearance
m3_nut_pocket_depth = 2.9;  // M3 nut is 2.4 mm thick

// Neck + shoulder that carry the drawing load into the mount. Sized to the
// mounting interface, so they do not follow the collar diameter.
neck_size = [17, 14, 11];
neck_origin = [mount_center_x - 8.5, mount_center_y - 7, -23.5];
shoulder_size = [24, 14, 7];
shoulder_origin = [mount_center_x - 12, mount_center_y - 7, -21];
fillet_height = 3;          // conical blend from the collar into the neck

// The slit stops below the mounting interface so the Braccio mounting boss is
// never cut in half; the collar still gets ~34 mm of slit to flex across.
split_top_z = -20;
bore_lead_in = 1.6;         // chamfer at the collar mouth, eases insertion

// ------------------------------------------------------------------- derived

function bore_diameter(pencil_d = pencil_diameter, clearance = fit_clearance) =
    pencil_d + clearance;

function collar_diameter(pencil_d = pencil_diameter, clearance = fit_clearance,
                         wall = collar_wall) =
    bore_diameter(pencil_d, clearance) + 2 * wall;

function lug_diameter(wall = lug_wall, slit = split_width) =
    2 * wall + slit;

function screw_x(pencil_d = pencil_diameter, clearance = fit_clearance,
                 wall = collar_wall) =
    mount_center_x + collar_diameter(pencil_d, clearance, wall) / 2 + 2;

// Material left between a recess and the slit face. Both must stay thick
// enough to take the clamping load; 0.8 mm (the previous head recess) tore.
function head_web(wall = lug_wall) = wall - m3_head_recess_depth;
function nut_web(wall = lug_wall) = wall - m3_nut_pocket_depth;

// Distance from the Braccio wrist_vertical axis to the mounting face of a
// finger, from unoq_braccio_sim/urdf/braccio.urdf.xacro:
//   wrist_vertical -> wrist_rotation 60 mm, wrist_rotation -> finger 30 mm.
wrist_axis_to_mount_mm = 90;

// What to put in config/workspace.yaml as links.wrist_pen_mm, for a pencil
// inserted until it bottoms out in the bore.
function wrist_pen_mm(protrusion = 30) =
    wrist_axis_to_mount_mm - collar_bottom_z + protrusion;

// --------------------------------------------------------------------- parts

module exact_braccio_mount() {
    // The companion STL is already converted to millimetres.
    intersection() {
        import("braccio_mount_reference_mm.stl", convexity = 20);
        translate([-18, -22.5, -18]) cube([70, 50, 26]);
    }
}

module along_y_cylinder(h, d, fn = 0) {
    rotate([90, 0, 0])
        if (fn > 0) cylinder(h = h, d = d, center = true, $fn = fn);
        else cylinder(h = h, d = d, center = true);
}

// The clamp lug: a stadium-shaped boss hulled onto the collar, so the two ears
// the slit creates are fully backed by the collar instead of hanging off it.
module clamp_lug(outer_d, sx) {
    translate([0, 0, clamp_screw_z - lug_height / 2])
        hull() {
            translate([mount_center_x, mount_center_y, 0])
                cylinder(h = lug_height, d = outer_d);
            translate([sx, mount_center_y, 0])
                cylinder(h = lug_height, d = lug_diameter());
        }
}

module braccio_pencil_grip(
    pencil_d = pencil_diameter,
    clearance = fit_clearance,
    wall = collar_wall
) {
    bore_d = bore_diameter(pencil_d, clearance);
    outer_d = collar_diameter(pencil_d, clearance, wall);
    outer_r = outer_d / 2;
    holder_h = collar_top_z - collar_bottom_z;
    sx = screw_x(pencil_d, clearance, wall);
    nut_corner_radius = m3_nut_across_flats / sqrt(3);

    assert(wall >= 2.4, "collar_wall below 2.4 mm is too thin to clamp with");
    assert(head_web(lug_wall) >= 1.6,
           "m3_head_recess_depth leaves under 1.6 mm of material under the screw head");
    assert(nut_web(lug_wall) >= 1.6,
           "m3_nut_pocket_depth leaves under 1.6 mm of material behind the nut");
    assert(sx + lug_diameter() / 2 <= 35.4,
           "the clamp lug would stick out past the Braccio mounting interface");

    difference() {
        union() {
            exact_braccio_mount();

            // Main split collar.
            translate([mount_center_x, mount_center_y, collar_bottom_z])
                cylinder(h = holder_h, d = outer_d);

            // Conical blend from the collar into the neck, clipped to the neck
            // footprint so it never bulges past it. Relieves the sharpest
            // stress riser on the part.
            intersection() {
                translate([mount_center_x, mount_center_y,
                           neck_origin[2] - fillet_height])
                    cylinder(h = fillet_height, d1 = outer_d,
                             d2 = outer_d + 2 * fillet_height);
                translate([neck_origin[0], neck_origin[1],
                           neck_origin[2] - fillet_height])
                    cube([neck_size[0], neck_size[1], fillet_height]);
            }

            // Neck and broad shoulder transfer drawing load into the mount.
            translate(neck_origin) cube(neck_size);
            translate(shoulder_origin) cube(shoulder_size);

            clamp_lug(outer_d, sx);
        }

        // Pencil / pen bore, blind at the top so the pencil bottoms out at a
        // repeatable depth (that is what makes wrist_pen_mm reproducible).
        translate([mount_center_x, mount_center_y, collar_bottom_z - 1])
            cylinder(h = holder_h + 2, d = bore_d);

        // Lead-in chamfer at the collar mouth.
        translate([mount_center_x, mount_center_y, collar_bottom_z - 0.01])
            cylinder(h = bore_lead_in, d1 = bore_d + 2 * bore_lead_in, d2 = bore_d);

        // Radial slit permitting the collar to flex closed.
        translate([mount_center_x, mount_center_y - split_width / 2,
                   collar_bottom_z - 1])
            cube([outer_r + lug_diameter(), split_width,
                  split_top_z - collar_bottom_z + 1]);

        // M3 through-hole.
        translate([sx, mount_center_y, clamp_screw_z])
            along_y_cylinder(split_width + 2 * lug_wall + 6, m3_clearance_diameter);

        // Socket-head recess on +Y side.
        translate([sx, mount_center_y + split_width / 2 + lug_wall
                       - m3_head_recess_depth / 2, clamp_screw_z])
            along_y_cylinder(m3_head_recess_depth + 0.01, m3_head_diameter);

        // Captive M3 nut pocket on -Y side.
        translate([sx, mount_center_y - split_width / 2 - lug_wall
                       + m3_nut_pocket_depth / 2, clamp_screw_z])
            along_y_cylinder(m3_nut_pocket_depth + 0.01, 2 * nut_corner_radius, 6);
    }
}

echo(str("bore ", bore_diameter(), " mm, collar OD ", collar_diameter(),
         " mm, wall ", collar_wall, " mm"));
echo(str("set config/workspace.yaml links.wrist_pen_mm to ~", wrist_pen_mm(30),
         " mm (pencil bottomed out, 30 mm proud of the collar)"));

braccio_pencil_grip();
