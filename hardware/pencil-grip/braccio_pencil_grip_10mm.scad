/*
Braccio Pencil / Pen Drawing Grip
=================================
Parametric OpenSCAD model using the exact mounting interface extracted from
"c_DITO PER CILINDRI.stl" supplied with the project.

Hardware:
- 1 x M3 socket-head screw, 16-20 mm long
- 1 x M3 hex nut

Print two perimeter walls minimum; four walls and 30-40% infill recommended.
PLA+, PETG or ABS/ASA are suitable. PETG provides the best clamp flex.
*/

$fn = 96;

// Customizer parameters
pencil_diameter = 10.0; // [6:0.1:12]
fit_clearance = 0.55; // [0.2:0.05:1.0]
collar_outer_diameter = 22;
collar_top_z = -14;
collar_bottom_z = -54;
split_width = 2.4;
mount_center_x = 16.5;
mount_center_y = 2.5;
clamp_screw_z = -33;
m3_clearance_diameter = 3.4;
m3_head_diameter = 6.4;
m3_nut_across_flats = 5.7;

module exact_braccio_mount() {
    // The companion STL is already converted to millimetres.
    intersection() {
        import("braccio_mount_reference_mm.stl", convexity=20);
        translate([-18, -22.5, -18]) cube([70, 50, 26]);
    }
}

module along_y_cylinder(h, d, fn=$fn) {
    rotate([90, 0, 0]) cylinder(h=h, d=d, center=true, $fn=fn);
}

module braccio_pencil_grip(
    pencil_d=pencil_diameter,
    clearance=fit_clearance,
    outer_d=collar_outer_diameter
) {
    holder_h = collar_top_z - collar_bottom_z;
    outer_r = outer_d / 2;
    ear_t = 4;
    ear_overlap = 2.5;
    ear_extension = 7;
    ear_h = 11;
    ear_x_len = ear_extension + ear_overlap;
    ear_x = mount_center_x + outer_r - ear_overlap;
    y_offset = split_width / 2 + ear_t / 2;
    screw_x = mount_center_x + outer_r + 2;
    nut_corner_radius = m3_nut_across_flats / sqrt(3);

    difference() {
        union() {
            exact_braccio_mount();

            // Main split collar.
            translate([mount_center_x, mount_center_y, collar_bottom_z])
                cylinder(h=holder_h, d=outer_d);

            // Neck and broad shoulder transfer drawing load into the mount.
            translate([mount_center_x - 8.5, mount_center_y - 7, -23.5])
                cube([17, 14, 11]);
            translate([mount_center_x - 12, mount_center_y - 7, -21])
                cube([24, 14, 7]);

            // Clamp ears.
            translate([ear_x, mount_center_y + y_offset - ear_t / 2, clamp_screw_z - ear_h / 2])
                cube([ear_x_len, ear_t, ear_h]);
            translate([ear_x, mount_center_y - y_offset - ear_t / 2, clamp_screw_z - ear_h / 2])
                cube([ear_x_len, ear_t, ear_h]);
        }

        // Pencil / pen bore.
        translate([mount_center_x, mount_center_y, collar_bottom_z - 1])
            cylinder(h=holder_h + 2, d=pencil_d + clearance);

        // Radial split permitting the collar to flex closed.
        translate([mount_center_x, mount_center_y - split_width / 2, collar_bottom_z - 1])
            cube([outer_r + ear_extension + 3, split_width, holder_h + 2]);

        // M3 through-hole.
        translate([screw_x, mount_center_y, clamp_screw_z])
            along_y_cylinder(split_width + 2 * ear_t + 6, m3_clearance_diameter);

        // Socket-head recess on +Y side.
        translate([screw_x, mount_center_y + split_width / 2 + ear_t - 1.6, clamp_screw_z])
            along_y_cylinder(3.2, m3_head_diameter);

        // Captive M3 nut pocket on -Y side.
        translate([screw_x, mount_center_y - split_width / 2 - ear_t + 1.55, clamp_screw_z])
            along_y_cylinder(3.1, 2 * nut_corner_radius, 6);
    }
}

braccio_pencil_grip();
